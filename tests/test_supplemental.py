import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs
import io
import json
from supplemental_client import SupplementalClient
from mfds_client import MFDSClient, ServiceError
from matcher import compare_ingredients
from test_matcher import detail, photo
from workflow import AnalysisWorkflow
from test_workflow import FakeClient
import main


class SupplementalTests(unittest.TestCase):
    def test_disabled_does_not_call_api(self):
        api=Mock()
        with patch('supplemental_client.settings',return_value={}):
            self.assertEqual(SupplementalClient(api).product_info('123')['status'],'disabled')
            self.assertEqual(SupplementalClient(api).ingredient_limits('M1')['status'],'disabled')
        api.query.assert_not_called()

    def test_easy_exact_code_and_endpoint(self):
        api=Mock();api.query.return_value={'total':1,'items':[{'itemSeq':'123','useMethodQesitm':'용법 원문'}]}
        with patch('supplemental_client.settings',return_value={'MFDS_EASY_ENABLED':'true'}):
            result=SupplementalClient(api).product_info('123')
            self.assertEqual(result['status'],'ok')
            self.assertEqual(api.query.call_args.kwargs['service_key_param'],'ServiceKey')
            api.query.return_value={'total':1,'items':[{'itemSeq':'999'}]}
            self.assertEqual(SupplementalClient(api).product_info('123')['status'],'unconfirmed')

    def test_maximum_keeps_conditions_not_product_amount(self):
        api=Mock();api.query.return_value={'total':1,'items':[{'CPNT_CD':'M1','DAY_MAX_DOSG_QY':'4','DAY_MAX_DOSG_QY_UNIT':'g','DOSAGE_ROUTE_CODE':'경구','FOML_NM':'정제'}]}
        with patch('supplemental_client.settings',return_value={'MFDS_MAX_DOSE_ENABLED':'true'}):
            result=SupplementalClient(api).ingredient_limits('M1')
        self.assertEqual(result['items'][0]['DAY_MAX_DOSG_QY'],'4')
        self.assertEqual(api.query.call_args.kwargs['CPNT_CD'],'M1')
        self.assertNotIn('reviewed',result)

    def test_maximum_truncated_not_confirmed(self):
        api=Mock();api.query.return_value={'total':2,'items':[{'CPNT_CD':'M1'}]}
        with patch('supplemental_client.settings',return_value={'MFDS_MAX_DOSE_ENABLED':'true'}):
            self.assertEqual(SupplementalClient(api).ingredient_limits('M1')['status'],'unconfirmed')

    def test_failure_is_nonblocking(self):
        api=Mock();api.query.side_effect=ServiceError('인증 실패')
        with patch('supplemental_client.settings',return_value={'MFDS_EASY_ENABLED':'true'}):
            self.assertEqual(SupplementalClient(api).product_info('123')['status'],'error')

    def test_separate_key_and_query_parameter(self):
        seen=[]
        def transport(request,**kwargs):
            seen.append(request.full_url)
            return io.BytesIO(json.dumps({'header':{'resultCode':'00'},'body':{'items':[],'totalCount':0}}).encode())
        with patch('mfds_client.settings',return_value={'MFDS_SERVICE_KEY':'base-key','MFDS_EASY_SERVICE_KEY':'easy-key'}):
            MFDSClient(transport).query('getDrbEasyDrugList',service_base='https://apis.data.go.kr/1471000/DrbEasyDrugInfoService',key_name='MFDS_EASY_SERVICE_KEY',service_key_param='ServiceKey',itemSeq='123')
        params=parse_qs(urlsplit(seen[0]).query)
        self.assertEqual(params['ServiceKey'],['easy-key'])
        self.assertNotIn('serviceKey',params)

    def test_single_material_recovers_missing_amount(self):
        d=detail(qnt=None)
        d['product']['MATERIAL_NAME']='총량 : 1정 중|성분명 : 아세트아미노펜|분량 : 500|단위 : 밀리그램'
        result=compare_ingredients(photo(),d)
        self.assertTrue(result['calculation_ready'])
        self.assertIn('MATERIAL_NAME_EVIDENCE',result['official_ingredients'][0]['raw'])
        self.assertIsNone(d['ingredients_raw'][0]['QNT'])

    def test_different_name_not_recovered(self):
        d=detail(qnt=None)
        d['product']['MATERIAL_NAME']='총량 : 1정 중|성분명 : 다른성분|분량 : 500|단위 : mg'
        self.assertFalse(compare_ingredients(photo(),d)['calculation_ready'])

    def test_layered_missing_amount_still_blocked(self):
        d=detail(qnt=None)
        d['product']['MATERIAL_NAME']='총량 : 1정 중-속방층|성분명 : 아세트아미노펜|분량 : 650|단위 : mg;총량 : -서방층|성분명 : 아세트아미노펜|분량 : 325|단위 : mg'
        self.assertFalse(compare_ingredients(photo(),d)['calculation_ready'])

    def test_support_route_uses_server_snapshot(self):
        flow=AnalysisWorkflow(FakeClient())
        candidate=flow.match_extracted(photo())['candidates'][0]['candidate_id']
        with patch('main.WORKFLOW',flow),patch('workflow.SupplementalClient') as factory:
            factory.return_value.for_product.return_value={'easy':{'status':'disabled'}}
            result=main.dispatch_post('/api/product-support',{'candidate_id':candidate,'ITEM_SEQ':'tampered'})
        self.assertEqual(factory.return_value.for_product.call_args.args[0]['product']['ITEM_SEQ'],'123')
        self.assertEqual(result['easy']['status'],'disabled')
