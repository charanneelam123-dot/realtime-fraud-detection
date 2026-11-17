"""Log a reproducible model artifact and holdout metrics to a local MLflow experiment."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mlflow.tracking import MlflowClient
from mlflow.entities import Metric,Param
from model import get_model
from platform_common import DATA
import time
import json

model,report=get_model()
client=MlflowClient(tracking_uri='sqlite:///'+(DATA/'mlflow.sqlite').resolve().as_posix())
experiment=client.get_experiment_by_name('synthetic-fraud')
eid=experiment.experiment_id if experiment else client.create_experiment('synthetic-fraud',artifact_location=(DATA/'mlflow-artifacts').resolve().as_uri())
run=client.create_run(eid,tags={'data':'synthetic','model_version':report['model_version']})
client.log_batch(run.info.run_id,metrics=[Metric(k,report[k],int(time.time()*1000),0) for k in ('precision','recall','pr_auc','roc_auc')],params=[Param('seed',str(report['seed'])),Param('threshold',str(report['threshold']))])
client.log_artifact(run.info.run_id,str(DATA/'model.json'))
client.log_artifact(run.info.run_id,str(DATA/'training-report.json'))
client.set_terminated(run.info.run_id,'FINISHED')
print(json.dumps({'mlflow_run_id':run.info.run_id,'model_version':report['model_version'],'holdout':{k:report[k] for k in ('precision','recall','pr_auc','roc_auc')}}))
