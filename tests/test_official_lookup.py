import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from mfds_client import ServiceError
from official_lookup import resolve_official, apply_resolution, OfficialRedirect, fetch_official
from test_matcher import detail, photo
from test_workflow import FakeClient
from workflow import AnalysisWorkflow
from calculator import calculate
from matcher import compare_ingredients, official_calculation_product


def page(amount='500',name='아세트아미노펜',basis='1정 중',code='123',manufacturer='가상제약',extra=''):
    return '<table><tr><th>제품명</th><td>가상 제품</td></tr><tr><th>업체명</th><td>'+manufacturer+'</td></tr><tr><th>품목기준코드</th><td>'+code+'</td></tr></table><h3>'+basis+'</h3><table><tr><th>성분명</th><th>분량</th><th>단위</th></tr><tr><td>'+name+'</td><td>'+amount+'</td><td>mg</td></tr>'+extra+'</table>'


def resolve(d,html):return resolve_official(d,lambda code:{'html':html,'retrieved_at':'test','sha256':'test'})


class OfficialLookupTests(unittest.TestCase):
    def test_missing_amount_recovered_with_exact_identity(self):
        d=detail(qnt=None);r=resolve(d,page())
        self.assertEqual(r['status'],'matched')
        fixed=apply_resolution(d,r)
        self.assertTrue(compare_ingredients(photo(),fixed)['calculation_ready'])
        self.assertIsNone(d['ingredients_raw'][0]['QNT'])
        p=official_calculation_product(fixed,compare_ingredients(photo(),fixed),photo());p['quantity']='2'
        self.assertEqual(calculate([p])['ingredients'][0]['total_mg'],'1000')

    def test_amount_conflict_requires_review_and_prefill(self):
        d=detail(qnt='650');r=resolve(d,page())
        self.assertEqual(r['status'],'matched');self.assertTrue(r['api_differences'])
        self.assertEqual(apply_resolution(d,r)['ingredients_raw'][0]['QNT'],'500')
        self.assertEqual(d['ingredients_raw'][0]['QNT'],'650')

    def test_identity_mismatch_blocked(self):
        for html in (page(code='999'),page(manufacturer='다른제약'),page().replace('가상 제품','다른제품')):
            self.assertIsNone(resolve(detail(),html)['proposal'])

    def test_extra_or_missing_ingredient_blocked(self):
        self.assertEqual(resolve(detail(),page(name='다른성분'))['status'],'review')
        d=detail();d['ingredients_raw'].append({'MTRAL_NM':'다른성분','MTRAL_CODE':'other','QNT':'1','INGD_UNIT_CD':'mg'})
        self.assertIsNone(resolve(d,page())['proposal'])

    def test_unsupported_unit_and_missing_basis_blocked(self):
        self.assertEqual(resolve(detail(),page().replace('>mg<','>알수없는단위<'))['status'],'review')
        self.assertEqual(resolve(detail(),page(basis='기준없음'))['status'],'review')

    def test_duplicate_rows_not_summed(self):
        extra='<tr><td>아세트아미노펜</td><td>500</td><td>mg</td></tr>'
        self.assertIsNone(resolve(detail(),page(extra=extra))['proposal'])

    def test_product_basis_conflict_blocked(self):
        self.assertEqual(resolve(detail(basis='2정 중'),page())['status'],'matched')

    def test_fetch_error_nonblocking(self):
        with patch('official_lookup.fetch_official',side_effect=ServiceError('공식 사이트 연결 실패')):
            self.assertEqual(resolve_official(detail())['status'],'review')

    def test_public_layer_fixture_conflict_then_consistent(self):
        html=Path('tests/official_page_sample.html').read_text(encoding='utf-8')
        d={'product':{'ITEM_SEQ':'202200407','ITEM_NAME':'타이레놀8시간이알서방정(아세트아미노펜)','ENTP_NAME':'켄뷰코리아판매유한회사'},'ingredients_raw':[
         {'MTRAL_NM':'아세트아미노펜','MTRAL_CODE':'M040353','QNT':'650','INGD_UNIT_CD':'mg','CPNT_CTNT_CONT':'속방층'},
         {'MTRAL_NM':'아세트아미노펜','MTRAL_CODE':'M040353','QNT':None,'INGD_UNIT_CD':'mg','CPNT_CTNT_CONT':'서방층'}],'warnings':[]}
        r=resolve(d,html)
        self.assertEqual(r['status'],'matched');self.assertEqual(r['proposal'][0]['amount'],'650.00')
        self.assertTrue(r['api_differences'])
        d['ingredients_raw'][0]['QNT']='325'
        r=resolve(d,html);self.assertEqual(r['status'],'matched')

    def test_model_cannot_override_server_snapshot(self):
        flow=AnalysisWorkflow(FakeClient(details={'123':detail(qnt=None)}))
        candidate=flow.match_extracted(photo())['candidates'][0]['candidate_id']
        with patch('workflow.resolve_official',return_value=resolve(detail(qnt=None),page())):
            result=flow.resolve_candidate(candidate)
        self.assertTrue(result['comparison']['calculation_ready'])
        approved=flow.auto_apply_candidate(candidate)
        self.assertEqual(approved['product']['ingredients'][0]['amount'],'500')
        self.assertTrue(approved['product']['automatic_resolution'])

    def test_review_not_bypassed_by_auto_apply(self):
        flow=AnalysisWorkflow(FakeClient(details={'123':detail(qnt='650')}))
        candidate=flow.match_extracted(photo())['candidates'][0]['candidate_id']
        with patch('workflow.resolve_official',return_value=resolve(detail(qnt='650'),page(code='999'))):
            flow.resolve_candidate(candidate)
        with self.assertRaises(ServiceError):flow.auto_apply_candidate(candidate)

    def test_packaged_liquid_and_identical_market_variants(self):
        d=detail(qnt=None,basis='30mL 중')
        html=page(basis='1병(30mL)중 - [내수용]')
        table=html[html.index('<h3>'):].replace('[내수용]','[수출용]')
        r=resolve(d,html+table)
        self.assertEqual(r['status'],'matched')
        self.assertEqual(r['proposal'][0]['basis_quantity'],'30')
        self.assertEqual(r['proposal'][0]['basis_unit'],'mL')
        self.assertEqual(r['proposal'][0]['amount'],'500')
        d['ingredients_raw']=[dict(d['ingredients_raw'][0],CPNT_CTNT_CONT=market) for market in ('[내수용]','[수출용]')]
        self.assertEqual(resolve(d,html+table)['status'],'matched')
        d['ingredients_raw'][1]['QNT']='650'
        self.assertEqual(resolve(d,html+table)['status'],'matched')

        self.assertEqual(resolve(d,html+table.replace('>500<','>650<'))['status'],'review')

    def test_equivalence_preserves_raw_mass_not_active_mass(self):
        d=detail(qnt=None)
        html=page(amount='156').replace('<th>단위</th>','<th>단위</th><th>성분정보</th>').replace('<td>mg</td>','<td>mg</td><td>아스코르브산(으)로서 150 밀리그램</td>')
        r=resolve(d,html)
        self.assertEqual(r['status'],'matched')
        fixed=apply_resolution(d,r)
        product=official_calculation_product(fixed,compare_ingredients({},fixed),{})
        self.assertEqual(product['ingredients'][0]['amount'],'156')
        self.assertIn('150',product['ingredients'][0]['equivalence'])

    def test_potency_mass_separate_from_mass(self):
        d=detail(qnt=None)
        html=page(amount='30').replace('<th>단위</th>','<th>단위</th><th>비교</th>').replace('<td>mg</td>','<td>mg</td><td>역가</td>')
        r=resolve(d,html);self.assertEqual(r['status'],'matched')
        fixed=apply_resolution(d,r)
        p=official_calculation_product(fixed,compare_ingredients({},fixed),{});p['quantity']='1'
        q=copy.deepcopy(p);q['code']='other';q['ingredients'][0]['measurement_basis']='mass'
        report=calculate([p,q])
        self.assertEqual(len(report['ingredients']),2)
        self.assertFalse(any(i['duplicate'] for i in report['ingredients']))

    def test_iu_kept_as_iu_and_never_compared_to_mg_limit(self):
        d=detail(qnt=None,unit='IU')
        r=resolve(d,page(amount='5').replace('>mg<','>IU<'))
        self.assertEqual(r['status'],'matched')
        fixed=apply_resolution(d,r)
        p=official_calculation_product(fixed,compare_ingredients({},fixed),{});p['quantity']='2'
        result=calculate([p])['ingredients'][0]
        self.assertIsNone(result['total_mg'])
        self.assertEqual(result['total_unit'],'IU')
        self.assertEqual(result['total_amount'],'10')
        self.assertEqual(result['criterion_status'],'unknown')

    def test_unknown_equivalence_blocked(self):
        html=page().replace('<th>단위</th>','<th>단위</th><th>성분정보</th>').replace('<td>mg</td>','<td>mg</td><td>환산 불명</td>')
        self.assertEqual(resolve(detail(),html)['status'],'review')

    def test_explicit_ointment_basis(self):
        d=detail(qnt=None,basis='100그램 중')
        r=resolve(d,page(basis='100그램 중'))
        self.assertEqual(r['status'],'matched')
        fixed=apply_resolution(d,r)
        p=official_calculation_product(fixed,compare_ingredients({},fixed),{});p['quantity']='2'
        self.assertEqual(p['quantity_unit'],'g')
        self.assertEqual(calculate([p])['ingredients'][0]['total_mg'],'10')

    def test_no_external_redirect(self):
        with self.assertRaises(ServiceError):
            OfficialRedirect().redirect_request(None,None,302,'',{},'https://example.test/')

    def test_url_accepts_only_numeric_item_code(self):
        with self.assertRaises(ServiceError):fetch_official('../outside')
