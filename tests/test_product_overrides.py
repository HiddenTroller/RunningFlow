import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
import main
from mfds_client import ServiceError
from matcher import compare_ingredients, official_calculation_product
from test_matcher import detail, photo
from test_workflow import FakeClient
from workflow import AnalysisWorkflow
from product_overrides import validate_override, apply_override, save_override


def record(amount='0.5',unit='g'):
    return {'reviewed':True,'complete':True,'reviewer':'시험 검토자','reviewed_at':date.today().isoformat(),
      'source_url':'https://example.test/official','source_evidence':'가상 검증 원문: 1정 중 성분 500mg',
      'ingredients':[{'name':'아세트아미노펜','ingredient_code':'ingredient-test','amount':amount,
                      'unit':unit,'basis_quantity':'1','basis_unit':'정'}]}


class ProductOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'verified_products.json'
        self.patch=patch('product_overrides.PATH',self.path);self.patch.start()
    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()

    def test_g_and_micrograms_convert_to_mg(self):
        self.assertEqual(validate_override(record(),detail()['product'])['ingredients'][0]['amount'],'500.0')
        self.assertEqual(validate_override(record('500000','μg'),detail()['product'])['ingredients'][0]['amount'],'500.000')

    def test_unknown_units_rejected(self):
        with self.assertRaises(ServiceError):validate_override(record('500','IU'),detail()['product'])

    def test_invalid_numbers_and_basis_rejected(self):
        for value in ('0','-1','NaN','Infinity'):
            with self.subTest(value=value),self.assertRaises(ServiceError):
                validate_override(record(value,'mg'),detail()['product'])
        r=record();r['ingredients'][0]['basis_unit']='병'
        with self.assertRaises(ServiceError):validate_override(r,detail()['product'])

    def test_required_review_metadata(self):
        for key in ('reviewer','source_evidence','source_url','reviewed_at','complete','reviewed'):
            r=record();r.pop(key)
            with self.subTest(key=key),self.assertRaises(ServiceError):validate_override(r,detail()['product'])

    def test_duplicate_and_mixed_basis_rejected(self):
        r=record();r['ingredients']*=2
        with self.assertRaises(ServiceError):validate_override(r,detail()['product'])
        r=record();r['ingredients'].append({'name':'다른 성분','ingredient_code':'other','amount':'1','unit':'mg','basis_quantity':'1','basis_unit':'mL'})
        with self.assertRaises(ServiceError):validate_override(r,detail()['product'])

    def test_persistence_history_and_code_bound(self):
        save_override(record(),detail()['product'])
        r=record('600','mg');r['product_code']='999'
        save_override(r,detail()['product'])
        saved=json.loads(self.path.read_text(encoding='utf-8'))
        self.assertNotIn('999',saved)
        self.assertEqual(len(saved['123']['history']),1)
        self.assertEqual(saved['123']['ingredients'][0]['amount'],'600')
        untouched=detail(code='999')
        self.assertIs(apply_override(untouched),untouched)

    def test_layered_incomplete_data_replaced_with_reviewed_total(self):
        d=detail(qnt=None)
        d['ingredients_raw'].append(copy.deepcopy(d['ingredients_raw'][0]))
        d['warnings']=['원본 조회 누락']
        self.assertFalse(compare_ingredients(photo(),d)['calculation_ready'])
        save_override(record(),d['product'])
        amended=apply_override(d)
        self.assertEqual(len(amended['ingredients_raw']),1)
        self.assertTrue(compare_ingredients(photo(),amended)['calculation_ready'])
        self.assertEqual(amended['original_official']['warnings'],['원본 조회 누락'])
        self.assertIsNone(d['ingredients_raw'][0]['QNT'])

    def test_register_route_then_calculate_official_snapshot(self):
        flow=AnalysisWorkflow(FakeClient(details={'123':detail(qnt=None)}))
        candidate=flow.match_extracted(photo())['candidates'][0]['candidate_id']
        with patch('main.WORKFLOW',flow):
            result=main.dispatch_post('/api/register-product-override',{'candidate_id':candidate,'override':record()})
        self.assertEqual(result['product']['ingredients'][0]['unit'],'mg')
        output=flow.evaluate([{'approval_id':result['approval_id'],'quantity':'2','ingredients':[{'amount':'99999'}]}],'single',[])
        self.assertEqual(float(output['ingredients'][0]['total_mg']),1000)
        self.assertIn('원문',output['ingredients'][0]['contributions'][0]['evidence'])

    def test_future_analysis_reuses_saved_record(self):
        save_override(record(),detail()['product'])
        flow=AnalysisWorkflow(FakeClient(details={'123':detail(qnt=None)}))
        candidate=flow.match_extracted(photo())['candidates'][0]
        self.assertTrue(candidate['comparison']['calculation_ready'])

    def test_corrupt_store_blocks(self):
        self.path.write_text('invalid',encoding='utf-8')
        with self.assertRaises(ServiceError):apply_override(detail())

    def test_normal_api_g_amount_normalized_to_mg(self):
        d=detail(qnt='0.5',unit='g')
        p=official_calculation_product(d,compare_ingredients(photo(),d),photo())
        self.assertEqual(p['ingredients'][0]['unit'],'mg')
        self.assertEqual(p['ingredients'][0]['amount'],'500.0')
