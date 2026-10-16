import json,unittest
from unittest.mock import Mock
from studio_client import product_names_from_final
from workflow import AnalysisWorkflow

class MultiProductTests(unittest.TestCase):
    def test_one_two_three(self):
        for count in (1,2,3):
            names=['약정500mg','약정650mg','약서방정'][:count]
            self.assertEqual(product_names_from_final(json.dumps({'제품목록':[{'제품명':n} for n in names]})),names)
    def test_empty_unknown_and_dedup(self):
        self.assertEqual(product_names_from_final('{"제품목록":[]}'),[])
        self.assertEqual(product_names_from_final('{"제품목록":[{"제품명":"약정"},{"제품명":"약정"},{"제품명":"확인필요"}]}'),['약정','확인필요'])
    def test_isolated_extraction_and_partial_failure(self):
        analyzer=lambda *args:{'final_text':'{"제품목록":[{"제품명":"약A"},{"제품명":"확인필요"},{"제품명":"약B"}]}','extracted':{'effective_ingredients':[{'ingredient_name':'혼합금지'}]}}
        w=AnalysisWorkflow(analyzer=analyzer)
        w.match_extracted=Mock(side_effect=lambda extracted,name:{'candidates':[],'photo_extracted':extracted})
        result=w.analyze_and_match(b'fake','image/png')
        self.assertEqual(len(result['products']),3)
        self.assertEqual([c.kwargs['name'] for c in w.match_extracted.call_args_list],['약A','','약B'])
        for c in w.match_extracted.call_args_list:self.assertEqual(c.args[0],{})
    def test_empty_has_no_search(self):
        w=AnalysisWorkflow(analyzer=lambda *args:{'final_text':'{"제품목록":[]}'})
        w.match_extracted=Mock();self.assertEqual(w.analyze_and_match(b'fake','image/png')['products'],[])
        w.match_extracted.assert_not_called()

class MultilineProductsTests(unittest.TestCase):
    def test_five_names_real_newlines(self):
        names=['타이레놀8시간이알서방정','판콜에스','이가탄에프캡슐','타이레놀정','게보린정']
        output='\n'.join(name+'【†'+str(i)+'】' for i,name in enumerate(names,1))
        self.assertEqual(product_names_from_final(output),names)
        self.assertEqual(product_names_from_final(json.dumps(output,ensure_ascii=False)),names)
        self.assertEqual(product_names_from_final('"'+output.replace('\n',r'\n')+'"'),names)
    def test_no_comma_split_or_extract_fallback(self):
        self.assertIsNone(product_names_from_final('약A, 약B'))
        self.assertIsNone(product_names_from_final('약A'))
    def test_workflow_searches_all_five(self):
        names=['약A','약B','약C','약D','약E']
        w=AnalysisWorkflow(analyzer=lambda *args:{'final_text':json.dumps('\n'.join(names))})
        w.match_extracted=Mock(side_effect=lambda extracted,name:{'candidates':[],'photo_extracted':extracted})
        result=w.analyze_and_match(b'fake','image/png')
        self.assertEqual([p['search_name'] for p in result['products']],names)
        self.assertEqual(w.match_extracted.call_count,5)
