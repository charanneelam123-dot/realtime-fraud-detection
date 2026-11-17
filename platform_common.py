from collections import defaultdict, deque
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

DATA=Path(os.environ.get('DATA_DIR') or 'runtime')
DATA.mkdir(parents=True,exist_ok=True)
TRACER=TracerProvider().get_tracer('portfolio-service')
REGISTRY=CollectorRegistry()
REQUESTS=Counter('http_requests_total','Completed HTTP requests',['method','route','status'],registry=REGISTRY)
LATENCY=Histogram('http_request_duration_seconds','HTTP latency',['route'],registry=REGISTRY)
RATE=defaultdict(deque)
RATE_LOCK=threading.Lock()
LIMIT=threading.BoundedSemaphore(2)

@contextmanager
def database():
    db=sqlite3.connect(DATA/'records.sqlite',timeout=15)
    db.row_factory=sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

with database() as db:
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP)')

def create(payload):
    record_id,token=uuid.uuid4().hex,secrets.token_urlsafe(24)
    with database() as db:
        db.execute('INSERT INTO records(id,token_hash,payload) VALUES(?,?,?)',(record_id,hashlib.sha256(token.encode()).hexdigest(),json.dumps(payload)))
    return {'id':record_id,'token':token,'version':0,**payload}

def read(record_id,token):
    with database() as db:
        row=db.execute('SELECT * FROM records WHERE id=?',(record_id,)).fetchone()
    if not row or not secrets.compare_digest(row['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
        raise HTTPException(404,'Record not found')
    return {'id':record_id,'version':row['version'],**json.loads(row['payload'])}

def update(record_id,token,payload,version):
    read(record_id,token)
    with database() as db:
        count=db.execute('UPDATE records SET payload=?,version=version+1 WHERE id=? AND version=?',(json.dumps(payload),record_id,version)).rowcount
        if count!=1:
            raise HTTPException(409,'The record has already changed')
    return read(record_id,token)

def operator(token):
    configured=os.environ.get('ADMIN_API_TOKEN','')
    if not configured or not secrets.compare_digest(configured,token or ''):
        raise HTTPException(403,'This operation requires the server operator token')

@contextmanager
def bounded():
    if not LIMIT.acquire(blocking=False):
        raise HTTPException(429,'Two computations are already running')
    try:
        yield
    finally:
        LIMIT.release()

def application(title,description):
    app=FastAPI(title=title,description=description,version='0.1.0')
    @app.middleware('http')
    async def observability(request:Request,call_next):
        started=time.perf_counter()
        host=request.client.host if request.client else 'unknown'
        with RATE_LOCK:
            bucket=RATE[host]
            now=time.monotonic()
            while bucket and now-bucket[0]>60:bucket.popleft()
            if len(bucket)>=120 and request.url.path not in {'/health','/metrics'}:
                return Response('Request limit reached',429,headers={'Retry-After':'60'})
            bucket.append(now)
            if len(RATE)>1000:
                stale=[key for key,value in RATE.items() if not value or now-value[-1]>60]
                for key in stale:RATE.pop(key,None)
        with TRACER.start_as_current_span(request.method+' '+request.url.path) as span:
            response=await call_next(request)
            response.headers['X-Trace-ID']=format(span.get_span_context().trace_id,'032x')
        route=getattr(request.scope.get('route'),'path','unmatched')
        REQUESTS.labels(request.method,route,str(response.status_code)).inc()
        LATENCY.labels(route).observe(time.perf_counter()-started)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response
    @app.get('/health')
    def health():return {'status':'ok','service':title,'data':'synthetic portfolio examples'}
    @app.get('/metrics')
    def metrics():return Response(generate_latest(REGISTRY),media_type='text/plain; version=0.0.4')
    @app.get('/',response_class=HTMLResponse)
    def index():return Path('web/index.html').read_text(encoding='utf-8')
    return app
