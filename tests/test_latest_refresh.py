import io
import json
import unittest
from unittest.mock import Mock, patch

import main
from studio_client import analyze_photo


class LatestRefreshTests(unittest.TestCase):
    def test_status_latest_even_with_old_pin(self):
        with patch('main.settings', return_value={'UPSTAGE_CONFIG_ID':'7','UPSTAGE_AGENT_ID':'agt_test','UPSTAGE_API_KEY':'secret-test'}):
            status = main.status_payload()
        self.assertEqual(status['config_policy'], 'latest')
        self.assertIsNone(status['requested_config_id'])
        self.assertTrue(status['legacy_config_ignored'])
        self.assertNotIn('secret-test', json.dumps(status))

    def test_status_rereads_settings(self):
        with patch('main.settings', side_effect=[{'UPSTAGE_AGENT_ID':'agt_one'},{'UPSTAGE_AGENT_ID':'agt_two'}]):
            self.assertEqual(main.status_payload()['agent_id'], 'agt_one')
            self.assertEqual(main.status_payload()['agent_id'], 'agt_two')

    def test_refresh_has_no_external_analysis_calls(self):
        handler = object.__new__(main.Handler)
        handler.headers = {'Host':'127.0.0.1:8767'}
        handler.path = '/api/status'
        sent = []
        handler.send = lambda status, data: sent.append((status, data))
        with patch('main.ALLOWED_HOST','127.0.0.1:8767'), patch('main.WORKFLOW') as flow, patch('main.analyze_photo') as analyze:
            handler.do_GET()
            flow.analyze_and_match.assert_not_called()
            analyze.assert_not_called()
        self.assertEqual(sent[0][1]['refresh_behavior'], 'status_only')

    def test_client_revision_changes_with_assets(self):
        with patch('main.Path.read_bytes', side_effect=[b'html',b'js',b'css',b'html',b'updated-js',b'css']):
            first = main.client_revision()
            self.assertNotEqual(first, main.client_revision())

    def test_page_includes_fresh_asset_revision(self):
        handler = object.__new__(main.Handler)
        handler.headers = {'Host':'127.0.0.1:8767'}
        handler.path = '/'
        sent = []
        handler.send = lambda *args: sent.append(args)
        with patch('main.ALLOWED_HOST','127.0.0.1:8767'):
            handler.do_GET()
        self.assertIn(b'/app.js?v=',sent[0][1])
        self.assertIn(b'/style.css?v=',sent[0][1])

    def test_no_cache_headers(self):
        handler = object.__new__(main.Handler)
        handler.send_response = Mock()
        handler.end_headers = Mock()
        headers = {}
        handler.send_header = lambda k,v:headers.update({k:v})
        handler.wfile = io.BytesIO()
        handler.send(200, {'ok':True})
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertEqual(headers['Pragma'], 'no-cache')
        self.assertEqual(headers['Expires'], '0')

    def test_analysis_rereads_agent_without_pinning(self):
        models = []
        def request(path, key, payload=None, content_type=None, method=None):
            if path == '/files': return {'id':'file-test'}
            if method == 'DELETE': return {'deleted':True}
            body = json.loads(payload)
            models.append(body['model'])
            self.assertNotIn('config_id',body)
            return {'id':'job-test','status':'completed','output_text':'{}'}
        configs = [{'UPSTAGE_API_KEY':'test','UPSTAGE_AGENT_ID':'agt_first','UPSTAGE_CONFIG_ID':'1'},
                   {'UPSTAGE_API_KEY':'test','UPSTAGE_AGENT_ID':'agt_second','UPSTAGE_CONFIG_ID':'2'}]
        with patch('studio_client.settings',side_effect=configs),patch('studio_client._request',side_effect=request):
            analyze_photo(b'photo','image/png')
            analyze_photo(b'photo','image/png')
        self.assertEqual(models,['agt_first','agt_second'])


if __name__ == '__main__': unittest.main()
