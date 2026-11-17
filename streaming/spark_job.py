"""Optional Spark/Kafka adapter. The API owns canonical feature and deduplication state."""
import json
import os
import urllib.request
from pyspark.sql import SparkSession
from pyspark.sql.functions import col,from_json,to_timestamp
from pyspark.sql.types import StructType,StructField,StringType,DoubleType,IntegerType,BooleanType

spark=SparkSession.builder.appName('synthetic-fraud-stream').getOrCreate()
schema=StructType([StructField('transaction_id',StringType()),StructField('account_id',StringType()),
                  StructField('timestamp',StringType()),StructField('amount',DoubleType()),StructField('account_age_days',IntegerType()),
                  StructField('distance_km',DoubleType()),StructField('foreign',BooleanType())])
raw=spark.readStream.format('kafka').option('kafka.bootstrap.servers',os.environ.get('KAFKA_BROKERS','localhost:9092')).option('subscribe','transactions').option('startingOffsets','earliest').load()
events=raw.select(from_json(col('value').cast('string'),schema).alias('event')).select('event.*')


def score_batch(batch,batch_id):
    # Reject overlarge batches instead of silently dropping rows. Retry-safe IDs live in the API.
    if batch.limit(1001).count()>1000:raise ValueError('Demo microbatch exceeds 1000 events')
    invalid=batch.filter(col('transaction_id').isNull()|col('amount').isNull()|(col('amount')<=0)|to_timestamp(col('timestamp')).isNull()).count()
    if invalid:raise ValueError(f'Microbatch contains {invalid} malformed events; quarantine upstream before retrying')
    for row in batch.orderBy(to_timestamp(col('timestamp'))).toLocalIterator():
        request=urllib.request.Request(os.environ.get('SCORING_URL','http://localhost:8000/api/score'),
            data=json.dumps(row.asDict()).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:
            result=json.load(response)
        print(json.dumps({'batch_id':batch_id,'transaction_id':result['transaction_id'],'review_flag':result['review_flag']}))


events.writeStream.foreachBatch(score_batch).option('checkpointLocation',os.environ.get('SPARK_CHECKPOINT','runtime/spark-checkpoint')).start().awaitTermination()
