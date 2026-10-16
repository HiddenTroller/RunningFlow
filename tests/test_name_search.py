import unittest
from unittest.mock import Mock
from mfds_client import ServiceError
from name_search import search_variants, similar_search
from workflow import AnalysisWorkflow
from test_workflow import FakeClient
from test_matcher import detail

class NameSearchTests(unittest.TestCase):
    def test_variants_bounded(self):
        self.assertIn('타이레놀',search_variants('타이레놀500밀리그램'))
        self.assertLessEqual(len(search_variants('이가탄 에프캡슐')),3)
        self.assertEqual(search_variants('정'),[])

    def test_no_match_fallback_requires_selection(self):
        client=FakeClient()
        client.search=Mock(side_effect=[{'items':[],'total':0}, {'items':[detail()['product']],'total':1}])
        result=AnalysisWorkflow(client).match_extracted({'product_name_raw':'가상 제품'})
        self.assertEqual(result['search_mode'],'similar')
        self.assertTrue(result['requires_selection'])
        self.assertEqual(len(result['candidates']),1)

    def test_exact_does_not_expand(self):
        client=FakeClient();client.search=Mock(wraps=client.search)
        result=AnalysisWorkflow(client).match_extracted({'product_name_raw':'가상 제품'})
        self.assertFalse(result['requires_selection']);self.assertEqual(client.search.call_count,1)

    def test_error_not_retried_as_name_mismatch(self):
        client=FakeClient();client.search=Mock(side_effect=ServiceError('인증 오류'))
        result=AnalysisWorkflow(client).match_extracted({'product_name_raw':'가상 제품'})
        self.assertEqual(result['status'],'확인 필요');self.assertEqual(client.search.call_count,1)

    def test_unrelated_candidates_filtered(self):
        client=Mock();client.search.return_value={'items':[{'ITEM_SEQ':'1','ITEM_NAME':'다른약'}],'total':1}
        result=similar_search(client,'타이레놀500밀리그램')
        self.assertFalse(result['items']);self.assertLessEqual(client.search.call_count,3)
