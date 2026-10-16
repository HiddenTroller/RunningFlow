import base64
import io
import json
import unittest
from unittest.mock import patch

import config
import main
from mfds_client import ServiceError


def handler(headers, path='/api/status', body=b''):
    h = object.__new__(main.Handler)
    h.headers, h.path, h.rfile, h.sent = headers, path, io.BytesIO(body), []
    h.send = lambda status, payload, *a: h.sent.append(status)
    h.send_response = h.sent.append
    h.send_header = lambda *a: None
    h.end_headers = lambda: None
    return h


def basic(password):
    return 'Basic ' + base64.b64encode(f'user:{password}'.encode()).decode()


class DeployTests(unittest.TestCase):
    def test_env_vars_used_only_without_env_file(self):
        with patch.dict('os.environ', {'MFDS_SERVICE_KEY': 'from-env'}), patch.object(config, 'ROOT', config.ROOT / 'missing'):
            self.assertEqual(config.settings()['MFDS_SERVICE_KEY'], 'from-env')

    def test_password_required_for_get_and_post(self):
        host = {'Host': 'app.onrender.com'}
        with patch.multiple('main', ALLOWED_HOST='app.onrender.com', PUBLIC=True, PASSWORD='pw'):
            for headers in ({}, {'Authorization': basic('wrong')}, {'Authorization': 'Basic %%%'}):
                h = handler({**host, **headers}); h.do_GET(); self.assertEqual(h.sent, [401])
            h = handler({**host, 'Authorization': basic('wrong')}); h.do_POST(); self.assertEqual(h.sent, [401])
            h = handler({**host, 'Authorization': basic('pw')}); h.do_GET(); self.assertEqual(h.sent, [200])

    def test_public_post_needs_https_origin(self):
        raw = json.dumps({'base64': 'eA==', 'consent': False}).encode()
        base = {'Host': 'app.onrender.com', 'Authorization': basic('pw'), 'X-App-Token': main.TOKEN, 'Content-Length': str(len(raw))}
        with patch.multiple('main', ALLOWED_HOST='app.onrender.com', PUBLIC=True, PASSWORD='pw'):
            h = handler({**base, 'Origin': 'http://app.onrender.com'}, '/api/analyze-and-match', raw); h.do_POST()
            self.assertEqual(h.sent, [403])
            h = handler({**base, 'Origin': 'https://app.onrender.com'}, '/api/analyze-and-match', raw); h.do_POST()
            self.assertEqual(h.sent, [400])  # 인증·출처 통과 후 동의 없음으로 거절

    def test_public_blocks_override_registration(self):
        with patch('main.PUBLIC', True), self.assertRaises(ServiceError):
            main.dispatch_post('/api/register-product-override', {})

    def test_public_without_password_refuses_to_start(self):
        conf = {'RENDER_EXTERNAL_HOSTNAME': 'app.onrender.com', 'PORT': '10000'}
        with patch('main.settings', return_value=conf), patch('sys.argv', ['main.py']), \
                patch('main.LocalHTTPServer') as server, self.assertRaises(SystemExit):
            main.run()
        server.assert_not_called()


if __name__ == '__main__':
    unittest.main()
