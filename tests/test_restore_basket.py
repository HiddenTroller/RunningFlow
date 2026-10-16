import unittest
from unittest.mock import patch
import main
from workflow import AnalysisWorkflow

class RestoreTests(unittest.TestCase):
    def test_server_snapshot_not_browser_ingredients(self):
        flow=AnalysisWorkflow()
        approval=flow._put('approved',dict(code='123',name='공식 제품',ingredients=[dict(amount='500')]))
        with patch('main.WORKFLOW',flow):
            r=main.dispatch_post('/api/restore-basket',{'items':[dict(approval_id=approval,code='123',name='변조명',quantity='2',ingredients=[dict(amount='999')])]})
        self.assertEqual(r['items'][0]['name'],'공식 제품')
        self.assertEqual(r['items'][0]['ingredients'][0]['amount'],'500')
        self.assertEqual(r['items'][0]['quantity'],'2')
    def test_expired_snapshot_pending(self):
        with patch('main.WORKFLOW',AnalysisWorkflow()):
            r=main.dispatch_post('/api/restore-basket',{'items':[dict(approval_id='expired',code='123',name='이전 제품',quantity='2')]})
        self.assertTrue(r['items'][0]['restored_pending'])
        self.assertTrue(r['items'][0]['pending'])
        self.assertEqual(r['items'][0]['ingredients'],[])
