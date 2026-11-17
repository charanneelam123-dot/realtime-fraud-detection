"""Train/test separation and bounded scoring for synthetic transactions."""
from collections import defaultdict,deque
import hashlib
import json
from pathlib import Path
import threading

import numpy as np
from sklearn.metrics import average_precision_score,confusion_matrix,precision_score,recall_score,roc_auc_score,fbeta_score
from xgboost import XGBClassifier,DMatrix
from platform_common import DATA,database

FEATURES=['amount','account_age_days','distance_km','tx_count_1h','foreign','hour']
LOCK=threading.RLock()
CACHED=None


def feature_values(event,velocity):
    return [event['amount'],event['account_age_days'],event['distance_km'],velocity,int(event['foreign']),int(event['timestamp_hour'])]


def training_data(n=5000,seed=41):
    rng=np.random.default_rng(seed);history=defaultdict(deque);x=[];y=[]
    for i in range(n):
        account=int(rng.integers(0,60));time=i*15;queue=history[account]
        while queue and queue[0]<=time-3600:queue.popleft()
        event={'amount':round(float(min(20000,rng.lognormal(4.3,1.3))),2),
               'account_age_days':int(rng.integers(1,2500)),'distance_km':float(min(8000,rng.exponential(180))),
               'foreign':bool(rng.random()<.12),'timestamp_hour':(time//3600)%24}
        velocity=len(queue);x.append(feature_values(event,velocity));queue.append(time)
        logit=-4.8+1.8*event['foreign']+1.7*(event['amount']>1000)+1.3*(velocity>5)+1.2*(event['account_age_days']<30)+1.0*(event['distance_km']>500)+float(rng.normal(0,.35))
        y.append(int(rng.random()<1/(1+np.exp(-logit))))
    return np.asarray(x,dtype=np.float32),np.asarray(y,dtype=np.int32)


def train():
    x,y=training_data();n=len(y);a,b=int(.6*n),int(.8*n)
    model=XGBClassifier(n_estimators=70,max_depth=3,learning_rate=.08,subsample=.9,colsample_bytree=.9,
                        eval_metric='logloss',n_jobs=1,random_state=41,tree_method='hist',
                        scale_pos_weight=float((a-y[:a].sum())/max(1,y[:a].sum())))
    model.fit(x[:a],y[:a])
    validation=model.predict_proba(x[a:b])[:,1]
    thresholds=np.linspace(.05,.95,37)
    threshold=float(max(thresholds,key=lambda t:fbeta_score(y[a:b],validation>=t,beta=2,zero_division=0)))
    probabilities=model.predict_proba(x[b:])[:,1];prediction=probabilities>=threshold
    report={'dataset':'synthetic probabilistic transactions','seed':41,'rows':n,'split':'chronological 60/20/20; threshold selected on validation only',
            'train_rows':a,'validation_rows':b-a,'test_rows':n-b,'threshold':threshold,
            'test_positive_rate':float(y[b:].mean()),'precision':float(precision_score(y[b:],prediction,zero_division=0)),
            'recall':float(recall_score(y[b:],prediction,zero_division=0)),
            'pr_auc':float(average_precision_score(y[b:],probabilities)),
            'roc_auc':float(roc_auc_score(y[b:],probabilities)),
            'confusion_matrix':confusion_matrix(y[b:],prediction,labels=[0,1]).tolist(),
            'features':FEATURES,'warning':'Synthetic holdout results are not evidence of real-world fraud performance.'}
    artifact=DATA/'model.json';model.save_model(artifact)
    report['model_version']=hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
    (DATA/'training-report.json').write_text(json.dumps(report,indent=2))
    return model,report


def get_model():
    global CACHED
    with LOCK:
        if CACHED is None:
            if (DATA/'model.json').exists() and (DATA/'training-report.json').exists():
                model=XGBClassifier();model.load_model(DATA/'model.json');report=json.loads((DATA/'training-report.json').read_text())
                if report['features']!=FEATURES:raise ValueError('Stored model feature order is incompatible')
                if hashlib.sha256((DATA/'model.json').read_bytes()).hexdigest()[:16]!=report['model_version']:raise ValueError('Model artifact hash does not match the training report')
                CACHED=model,report
            else:CACHED=train()
        return CACHED


def score(event):
    model,report=get_model()
    payload_hash=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
    timestamp=float(event['timestamp_epoch'])
    with LOCK,database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY, account TEXT, timestamp REAL, payload_hash TEXT, result TEXT)')
        db.execute('CREATE INDEX IF NOT EXISTS account_time ON transactions(account,timestamp)')
        old=db.execute('SELECT payload_hash,result FROM transactions WHERE id=?',(event['transaction_id'],)).fetchone()
        if old:
            if old['payload_hash']!=payload_hash:raise ValueError('Transaction ID already exists with a different payload')
            return {**json.loads(old['result']),'duplicate':True}
        latest=db.execute('SELECT MAX(timestamp) FROM transactions WHERE account=?',(event['account_id'],)).fetchone()[0]
        if latest is not None and timestamp<latest:raise ValueError('Out-of-order events are rejected; submit each account in event-time order')
        velocity=db.execute('SELECT COUNT(*) FROM transactions WHERE account=? AND timestamp>? AND timestamp<=?',(event['account_id'],timestamp-3600,timestamp)).fetchone()[0]
        values=np.asarray([feature_values(event,velocity)],dtype=np.float32)
        probability=float(model.predict_proba(values)[0,1])
        contributions=model.get_booster().predict(DMatrix(values),pred_contribs=True)[0,:-1]
        ranked=sorted(zip(FEATURES,values[0].tolist(),contributions.tolist()),key=lambda row:abs(row[2]),reverse=True)[:3]
        result={'transaction_id':event['transaction_id'],'risk_score':round(probability,6),'review_flag':probability>=report['threshold'],
                'threshold':report['threshold'],'model_version':report['model_version'],'tx_count_1h':velocity,
                'top_contributions':[{'feature':name,'value':value,'contribution_log_odds':round(contribution,5)} for name,value,contribution in ranked],
                'decision':'synthetic review suggestion only; no payment was blocked','duplicate':False}
        db.execute('INSERT INTO transactions VALUES(?,?,?,?,?)',(event['transaction_id'],event['account_id'],timestamp,payload_hash,json.dumps(result)))
        return result
