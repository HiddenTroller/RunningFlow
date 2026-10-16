import unittest
from unittest.mock import patch
from studio_client import final_output, analyze_photo
from workflow import AnalysisWorkflow


def step(model, value):
    return {'model': model, 'content': [{'type': 'output_text', 'text': value}]}


class InstructUpgradeTests(unittest.TestCase):
    def test_latest_observed_product_name(self):
        result = final_output({'output': [step('extract', '{}'), step('instruct', '타이레놀정8시간이알서방정')]})
        self.assertEqual(result['search_product_name'], '타이레놀정8시간이알서방정')

    def test_prose_not_used_as_product_name(self):
        for value in ('제품 A\n제품 B', '|제품명|결과|', '제품을 확인하세요: A', '<script>alert(1)</script>'):
            self.assertEqual(final_output({'output':[step('instruct', value)]})['search_product_name'], '')

    def test_extract_only_does_not_invent_search_name(self):
        self.assertEqual(final_output({'output':[step('extract', '{}')]})['search_product_name'], '')

    def test_json_name(self):
        result=final_output({'output':[step('instruct', '{"product_name_raw":"공식 검색명"}')]})
        self.assertEqual(result['search_product_name'], '공식 검색명')

    def test_analyze_keeps_extract_and_final(self):
        def request(path, key, *args, **kwargs):
            if path == '/files': return {'id':'file-test'}
            if kwargs.get('method') == 'DELETE': return {'deleted':True}
            return {'id':'job-test', 'status':'completed', 'output':[
                step('extract', '{"제품명":"사진 원문", "유효성분 목록":"아세트아미노펜 / 650 / mg"}'),
                step('instruct', '타이레놀정8시간이알서방정')]}
        with patch('studio_client.settings',return_value={'UPSTAGE_API_KEY':'test','UPSTAGE_AGENT_ID':'agt_test'}), patch('studio_client._request',side_effect=request):
            result=analyze_photo(b'photo','image/png')
        self.assertEqual(result['extracted']['product_name_raw'],'사진 원문')
        self.assertEqual(result['extracted']['effective_ingredients'][0]['strength_per_unit'],'650 mg')
        self.assertEqual(result['search_product_name'],'타이레놀정8시간이알서방정')
        self.assertEqual(result['file_cleanup'],'deleted')

    def test_workflow_uses_search_name_preserves_evidence(self):
        studio={'extracted':{'product_name_raw':'사진 원문'},'search_product_name':'정리된 제품명'}
        flow=AnalysisWorkflow(analyzer=lambda *args:studio)
        with patch.object(flow,'match_extracted',return_value={}) as match:
            result=flow.analyze_and_match(b'photo','image/png')
        match.assert_called_once_with(studio['extracted'],name='정리된 제품명')
        self.assertEqual(result['studio']['extracted']['product_name_raw'],'사진 원문')

    def test_workflow_empty_final_falls_back(self):
        flow=AnalysisWorkflow(analyzer=lambda *args:{'extracted':{'product_name_raw':'사진명'}})
        with patch.object(flow,'match_extracted',return_value={}) as match:
            flow.analyze_and_match(b'photo','image/png')
        self.assertEqual(match.call_args.kwargs['name'],'')

    def test_no_instruct_never_substitutes_extract_text(self):
        result=final_output({'output':[step('extract','사진 추출 결과')], 'output_text':'Extract 결과'})
        self.assertEqual(result['final_text'],'')

    def test_final_text_preserved_exactly(self):
        raw='  # 제목\n|성분|함량|\n|---|---|\n|A|650 mg|\n'
        self.assertEqual(final_output({'output':[step('instruct',raw)]})['final_text'],raw)

    def test_solar_final_message_connected(self):
        result=final_output({'output':[step('step_extract','{}'),step('solar-pro3','타이레놀정8시간이알서방정')]})
        self.assertEqual(result['search_product_name'],'타이레놀정8시간이알서방정')

    def test_display_wrappers_connected_without_changing_original(self):
        for raw in ('**타이레놀정500밀리그램**', '"타이레놀정500밀리그램"', '# 타이레놀정500밀리그램 [1]', '{"content":"타이레놀정500밀리그램"}'):
            result=final_output({'output':[step('instruct',raw)]})
            self.assertEqual(result['search_product_name'],'타이레놀정500밀리그램')
            self.assertEqual(result['final_text'],raw)

    def test_top_level_final_text_connected(self):
        self.assertEqual(final_output({'output_text':'타이레놀정500밀리그램'})['search_product_name'],'타이레놀정500밀리그램')

    def test_instruct_name_reaches_mfds_search(self):
        from test_workflow import FakeClient
        name='타이레놀정8시간이알서방정'
        studio=final_output({'output':[step('step_extract','{}'),step('solar-pro3',name)]})
        studio['extracted']={'product_name_raw':'다른 Extract 이름'}
        client=FakeClient([])
        with patch.object(client,'search',wraps=client.search) as search:
            result=AnalysisWorkflow(client,lambda *args:studio).analyze_and_match(b'photo','image/png')
        self.assertEqual(search.call_args_list[0].args,(name,1))
        self.assertEqual(search.call_args_list[0].kwargs,{'page_size':10})
        self.assertEqual(result['search_name'],name)

    def test_actual_studio_citation_response_connected(self):
        raw='"타이레놀정8시간이알서방정【†1】"'
        result=final_output({'output':[step('Instruct - 지시-1',raw)]})
        self.assertEqual(result['final_text'],raw)
        self.assertEqual(result['search_product_name'],'타이레놀정8시간이알서방정')

    def test_multiple_studio_citations(self):
        result=final_output({'output':[step('instruct','**타이레놀정【†1】【†2】**')]})
        self.assertEqual(result['search_product_name'],'타이레놀정')
