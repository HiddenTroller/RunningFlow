import unittest
from extraction_adapter import normalize_extraction
from matcher import photo_ingredients, compare_ingredients
from workflow import AnalysisWorkflow
from test_workflow import FakeClient
from test_matcher import detail


OBSERVED = {
    '제품명': '타이레놀 500 밀리그람',
    '유효성분 목록': '아세트아미노펜 / 500 / mg / 1정',
    '성인 용법·용량': '', '하루 최대량': '', '중복·병용 관련 주의사항': ''
}


class ExtractionAdapterTests(unittest.TestCase):
    def test_observed_config7_result(self):
        canonical, warnings = normalize_extraction(OBSERVED)
        self.assertEqual(canonical['product_name_raw'], '타이레놀 500 밀리그람')
        self.assertEqual(canonical['effective_ingredients'][0]['strength_per_unit'], '1정 중 500 mg')
        self.assertEqual(photo_ingredients(canonical)[0]['strength']['mg'], '500')
        self.assertEqual(canonical['manufacturer'], '')
        self.assertEqual(canonical['dosage_and_administration'], '')
        self.assertFalse(warnings)

    def test_observed_result_full_workflow(self):
        flow = AnalysisWorkflow(FakeClient(), lambda c, m: {'extracted': OBSERVED, 'search_product_name': '타이레놀정500밀리그램'})
        result = flow.analyze_and_match(b'photo', 'image/png')
        self.assertEqual(result['candidates'][0]['comparison']['status'], '일치')
        candidate_id = result['candidates'][0]['candidate_id']
        product = flow.confirm_candidate(candidate_id, True)['product']
        self.assertEqual(product['ingredients'][0]['amount'], '500')

    def test_three_part_string(self):
        canonical, _ = normalize_extraction({'제품명':'제품', '유효성분 목록':'아세트아미노펜 / 650 / mg'})
        row = photo_ingredients(canonical)[0]
        self.assertEqual(row['strength']['mg'], '650')
        self.assertIsNone(row['strength']['basis_quantity'])

    def test_multiple_lines_not_collapsed(self):
        canonical, _ = normalize_extraction({'제품명':['제품'], '유효성분 목록':'성분A / 1 / mg / 1정<br>성분B / 2 / mg / 1정'})
        self.assertEqual(len(canonical['effective_ingredients']), 2)

    def test_list_of_strings(self):
        canonical, _ = normalize_extraction({'제품명':'제품','유효성분 목록':['성분A / 1 / mg','성분B / 2 / mg']})
        self.assertEqual(len(canonical['effective_ingredients']), 2)

    def test_structured_korean_row(self):
        canonical, _ = normalize_extraction({'제품명':'제품','유효성분 목록':[{'성분명':'성분A','함량':'1','단위':'mg','함량 기준':'1정'}]})
        self.assertEqual(canonical['effective_ingredients'][0]['strength_per_unit'], '1정 중 1 mg')

    def test_joined_display_format(self):
        canonical, _ = normalize_extraction({'제품명':'제품','유효성분 목록':'아세트아미노펜 650mg (1정당)'})
        self.assertEqual(canonical['effective_ingredients'][0]['ingredient_name'], '아세트아미노펜')
        self.assertEqual(photo_ingredients(canonical)[0]['strength']['basis_unit'], '정')

    def test_unknown_fourth_part_not_dropped(self):
        canonical, _ = normalize_extraction({'제품명':'제품','유효성분 목록':'성분A / 500 / mg / 한병'})
        self.assertIsNone(photo_ingredients(canonical)[0]['strength']['mg'])

    def test_english_shape_still_works(self):
        original = {'product_name_raw':'제품','manufacturer':'회사','effective_ingredients':[
            {'ingredient_name':'아세트아미노펜','strength_per_unit':'0.5g'}],
            'dosage_and_administration':'문서 원문','max_daily_dose':'최대량 원문',
            'do_not_take_with':[{'item_name':'주의 원문'}]}
        canonical, _ = normalize_extraction(original)
        self.assertEqual(compare_ingredients(canonical, detail())['status'], '일치')
        self.assertEqual(canonical['dosage_and_administration'], '문서 원문')

    def test_idempotent_no_evidence_growth(self):
        first, _ = normalize_extraction(OBSERVED)
        second, _ = normalize_extraction(first)
        self.assertEqual(first, second)

    def test_unreadable_not_made_up(self):
        canonical, warnings = normalize_extraction({'제품명':['제품A','제품B'],'유효성분 목록':[None]})
        self.assertEqual(canonical['product_name_raw'], '')
        self.assertEqual(canonical['effective_ingredients'], [])
        self.assertTrue(warnings)

    def test_missing_basis_cannot_use_photo_to_fill_official(self):
        canonical, _ = normalize_extraction(OBSERVED)
        result = compare_ingredients(canonical, detail(basis='미확인'))
        self.assertFalse(result['calculation_ready'])


if __name__ == '__main__':
    unittest.main()
