import os,tempfile
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='fraud-test-')
import unittest
from fastapi.testclient import TestClient
from app import app
from model import training_data,get_model


def transaction(identifier='demo-test-1',time='2026-01-01T12:00:00Z'):
    return {'transaction_id':identifier,'account_id':identifier+'-account','timestamp':time,'amount':900,'account_age_days':20,'distance_km':700,'foreign':True}


class FraudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.client=TestClient(app);cls.report=get_model()[1]
    def test_chronological_holdout_is_reported(self):
        self.assertEqual(self.report['test_rows'],1000);self.assertIn('validation only',self.report['split'])
        self.assertGreaterEqual(self.report['pr_auc'],0);self.assertLessEqual(self.report['pr_auc'],1)
    def test_training_seed_reproducible(self):
        x,y=training_data(30);xx,yy=training_data(30);self.assertTrue((x==xx).all());self.assertTrue((y==yy).all())
    def test_scores_and_local_contributions(self):
        result=self.client.post('/api/score',json=transaction()).json();self.assertGreaterEqual(result['risk_score'],0);self.assertLessEqual(result['risk_score'],1)
        self.assertEqual(len(result['top_contributions']),3)
    def test_idempotent_retry(self):
        body=transaction('demo-retry');first=self.client.post('/api/score',json=body).json();second=self.client.post('/api/score',json=body).json()
        self.assertEqual(first['risk_score'],second['risk_score']);self.assertTrue(second['duplicate'])
    def test_payload_mismatch_conflicts(self):
        body=transaction('demo-collision');self.client.post('/api/score',json=body);body['amount']=500
        self.assertEqual(self.client.post('/api/score',json=body).status_code,409)
    def test_event_time_order_enforced(self):
        later=transaction('demo-later','2026-03-01T12:00:00Z');self.client.post('/api/score',json=later)
        earlier=transaction('demo-earlier','2026-03-01T11:00:00Z')
        earlier['account_id']=later['account_id']
        self.assertEqual(self.client.post('/api/score',json=earlier).status_code,409)
    def test_non_demo_accounts_rejected(self):
        body=transaction('demo-real');body['account_id']='real-account'
        self.assertEqual(self.client.post('/api/score',json=body).status_code,422)
    def test_rolling_count_excludes_current_event(self):
        one=transaction('demo-velocity-1','2026-04-01T12:00:00Z');one['account_id']='demo-velocity'
        two={**one,'transaction_id':'demo-velocity-2','timestamp':'2026-04-01T12:01:00Z'}
        self.assertEqual(self.client.post('/api/score',json=one).json()['tx_count_1h'],0)
        self.assertEqual(self.client.post('/api/score',json=two).json()['tx_count_1h'],1)


if __name__=='__main__':unittest.main()
