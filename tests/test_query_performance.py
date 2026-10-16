import unittest,threading
from unittest.mock import Mock,patch
from workflow import AnalysisWorkflow

class QueryPerformanceTests(unittest.TestCase):
    def test_cache_copy_and_expiry(self):
        client=Mock();client.detail.return_value={'ingredients_raw':[{'name':'x'}],'warnings':[]}
        w=AnalysisWorkflow(client=client)
        with patch('workflow.time.monotonic',return_value=1):
            first=w.cached_search_detail('1');first['ingredients_raw'].clear()
            self.assertEqual(len(w.cached_search_detail('1')['ingredients_raw']),1)
        self.assertEqual(client.detail.call_count,1)
        with patch('workflow.time.monotonic',return_value=302):w.cached_search_detail('1')
        self.assertEqual(client.detail.call_count,2)
    def test_incomplete_not_cached(self):
        client=Mock();client.detail.return_value={'ingredients_raw':[],'warnings':['missing']}
        w=AnalysisWorkflow(client=client);w.cached_search_detail('1');w.cached_search_detail('1')
        self.assertEqual(client.detail.call_count,2)
    def test_parallel_order_and_state_isolation(self):
        barrier=threading.Barrier(2)
        w=AnalysisWorkflow(analyzer=lambda *args:{'final_text':'{"제품목록":[{"제품명":"A"},{"제품명":"B"}]}'})
        def match(extracted,name):
            barrier.wait(timeout=2)
            return {'candidates':[{'candidate_id':name}],'photo_extracted':extracted}
        w.match_extracted=match
        result=w.analyze_and_match(b'x','image/png')
        self.assertEqual([p['search_name'] for p in result['products']],['A','B'])
        self.assertEqual(result['products'][1]['candidates'][0]['candidate_id'],'B')
