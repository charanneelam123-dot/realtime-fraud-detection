from datetime import datetime
import time
from fastapi import HTTPException
from pydantic import BaseModel,Field,AwareDatetime,ConfigDict
from platform_common import application,bounded
from model import get_model,score

app=application('Real-Time Fraud Detection','Synthetic transaction scoring with XGBoost, rolling features, idempotent ingestion and held-out evaluation.')


class Transaction(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    transaction_id:str=Field(pattern='^demo-[A-Za-z0-9-]{1,60}$')
    account_id:str=Field(pattern='^demo-[A-Za-z0-9-]{1,40}$')
    timestamp:AwareDatetime
    amount:float=Field(gt=0,le=50000)
    account_age_days:int=Field(ge=0,le=30000)
    distance_km:float=Field(ge=0,le=20000)
    foreign:bool


@app.get('/api/model')
def model_report():
    with bounded():return get_model()[1]


@app.post('/api/score')
def score_transaction(body:Transaction):
    if not 2000<=body.timestamp.year<=2100:raise HTTPException(422,'Timestamp must be in 2000–2100')
    event=body.model_dump(exclude={'timestamp'});event['timestamp_epoch']=body.timestamp.timestamp();event['timestamp_hour']=body.timestamp.hour
    started=time.perf_counter()
    with bounded():
        try:result=score(event)
        except ValueError as error:raise HTTPException(409,str(error)) from None
    return {**result,'elapsed_ms':round((time.perf_counter()-started)*1000,3)}
