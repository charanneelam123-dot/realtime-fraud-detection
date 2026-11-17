"""Publish synthetic events; never use customer transactions in this demo."""
import argparse
from datetime import datetime,timedelta,timezone
import json
import random
import time
from kafka import KafkaProducer

parser=argparse.ArgumentParser();parser.add_argument('--broker',default='localhost:9092');parser.add_argument('--count',type=int,default=100)
args=parser.parse_args()
producer=KafkaProducer(bootstrap_servers=args.broker,value_serializer=lambda value:json.dumps(value).encode(),acks='all')
rng=random.Random(41);start=datetime.now(timezone.utc)
for index in range(args.count):
    event={'transaction_id':f'demo-stream-{int(start.timestamp())}-{index}','account_id':f'demo-{rng.randrange(20)}',
           'timestamp':(start+timedelta(seconds=index)).isoformat(),'amount':round(rng.uniform(5,2000),2),
           'account_age_days':rng.randrange(1,2000),'distance_km':round(rng.uniform(0,1000),2),'foreign':rng.random()<.15}
    producer.send('transactions',key=event['account_id'].encode(),value=event).get(timeout=15)
    time.sleep(.1)
producer.flush();producer.close()
