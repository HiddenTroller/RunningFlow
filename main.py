"""Python 표준 라이브러리만으로 실행하는 로컬 웹 앱: python main.py"""
import argparse
import base64
import binascii
import hmac
import json
import secrets
import socket
import webbrowser
import hashlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import build_opener, ProxyHandler
from urllib.parse import urlsplit

from config import ROOT, settings
from mfds_client import MFDSClient, ServiceError
from studio_client import analyze_photo, CONFIG_POLICY
from calculator import calculate
from duplicates import compare_duplicates, identity_only_product
from population_rules import require_complete_profile
from workflow import AnalysisWorkflow

TOKEN = secrets.token_urlsafe(32)
ALLOWED_HOST = ''
PUBLIC = False  # Render 등 공개 배포: https, 0.0.0.0 바인딩, 보완 데이터 등록 차단
PASSWORD = ''   # APP_PASSWORD. 값이 있으면 모든 요청에 Basic 인증을 요구합니다.
STATIC = ROOT / 'static'
WORKFLOW = AnalysisWorkflow()


def client_revision():
    """페이지 새로고침 때 JS/CSS 변경을 즉시 반영하기 위한 내용 기반 버전."""
    digest = hashlib.sha256()
    for name in ('index.html', 'app.js', 'style.css'):
        digest.update((STATIC / name).read_bytes())
    return digest.hexdigest()[:12]


def status_payload():
    """요청마다 .env 재조회. 키 값이나 과거 고정 버전은 클라이언트에 보내지 않음."""
    conf = settings()
    return {'mfds_ready': bool(conf.get('MFDS_SERVICE_KEY')),
            'studio_ready': bool(conf.get('UPSTAGE_API_KEY')),
            'agent_id': conf.get('UPSTAGE_AGENT_ID', ''),
            'config_policy': CONFIG_POLICY, 'requested_config_id': None,
            'legacy_config_ignored': bool(conf.get('UPSTAGE_CONFIG_ID', '').strip()),
            'refresh_behavior': 'status_only', 'features': ['duplicates_only_v1'], 'client_revision': client_revision(),
            'checked_at': datetime.now(timezone.utc).isoformat(), 'token': TOKEN}


def dispatch_post(path, data):
    """HTTP 처리와 분리해 새 경로도 외부 API 없이 테스트할 수 있게 합니다."""
    client = MFDSClient()
    if path in ('/api/check-duplicates', '/api/demo-duplicates'):
        if path == '/api/demo-duplicates':
            products = json.loads((STATIC / 'sample.json').read_text(encoding='utf-8'))
        else:
            submitted = data.get('products')
            if not isinstance(submitted, list) or not 1 <= len(submitted) <= 30:
                raise ServiceError('확인된 제품을 1~30개 추가하세요.')
            products = []
            for item in submitted:
                if not isinstance(item, dict): raise ServiceError('제품 목록을 확인하세요.')
                if item.get('approval_id'):
                    product = WORKFLOW._get(item.get('approval_id'), 'approved')
                else:
                    product = identity_only_product(WORKFLOW._get(item.get('candidate_id'), 'candidate'))
                if not any(p['code'] == product['code'] for p in products): products.append(product)
        return compare_duplicates(products)
    if path == '/api/search':
        page = int(data.get('page', 1))
        if not 1 <= page <= 1000:
            raise ServiceError('페이지 범위를 확인하세요.')
        return client.search(data.get('name', ''), page)
    if path == '/api/detail':
        return client.detail(data.get('code', ''))
    if path in ('/api/studio', '/api/analyze-and-match'):
        if data.get('consent') is not True:
            raise ServiceError('사진의 Upstage 전송에 동의해야 분석할 수 있습니다.')
        try:
            content = base64.b64decode(data.get('base64', ''), validate=True)
        except (binascii.Error, TypeError):
            raise ServiceError('사진 데이터 형식이 잘못되었습니다.') from None
        if not content or len(content) > 10 * 1024 * 1024:
            raise ServiceError('사진 한 장은 10MB 이하로 입력하세요.')
        return (WORKFLOW.analyze_and_match(content, data.get('mime', ''))
                if path == '/api/analyze-and-match' else analyze_photo(content, data.get('mime', '')))
    if path == '/api/match-search':
        page = int(data.get('page', 1))
        if not 1 <= page <= 1000:
            raise ServiceError('페이지 범위를 확인하세요.')
        return WORKFLOW.search_again(data.get('photo_id'), data.get('name', ''), page)
    if path == '/api/import-and-match':
        extracted = data.get('extracted')
        if not isinstance(extracted, dict):
            raise ServiceError('Extract JSON 객체가 필요합니다.')
        return WORKFLOW.match_extracted(extracted)
    if path == '/api/resolve-official':
        return WORKFLOW.resolve_candidate(data.get('candidate_id'))
    if path == '/api/register-product-override':
        if PUBLIC:
            # 배포 서버의 디스크는 재시작 때 지워집니다. 로컬에서 등록한 verified_products.json을 커밋하세요.
            raise ServiceError('배포 사이트에서는 보완 데이터를 등록할 수 없습니다. 로컬 실행에서 등록하세요.')
        return WORKFLOW.register_product_override(data.get('candidate_id'), data.get('override'))
    if path == '/api/product-support':
        return WORKFLOW.product_support(data.get('candidate_id'))
    if path == '/api/auto-apply':
        return WORKFLOW.auto_apply_candidate(data.get('candidate_id'))
    if path == '/api/confirm-match':
        return WORKFLOW.confirm_candidate(data.get('candidate_id'), data.get('confirmed'), data.get('mismatch_ack'))
    if path in ('/api/evaluate','/api/demo-evaluate'):
        data['profile'] = require_complete_profile(data.get('profile'))
    if path == '/api/restore-basket':
        rows = data.get('items')
        if not isinstance(rows,list) or len(rows)>30: raise ServiceError('복원할 목록을 확인하세요.')
        items=[]
        for row in rows:
            if not isinstance(row,dict):continue
            try:
                product=WORKFLOW._get(row.get('approval_id'),'approved')
                product.update(approval_id=row['approval_id'],quantity=row.get('quantity','0'))
                items.append(product)
            except ServiceError:
                code=str(row.get('code',''))
                if code.isdigit() and len(code)<=20:
                    items.append(dict(code=code,name=str(row.get('name','제품 확인 필요'))[:200],quantity=row.get('quantity','0'),quantity_unit='',ingredients=[],pending=True,restored_pending=True,comparison_warnings=['서버 재시작 또는 확인 시간 만료로 공식 함량 재확인이 필요합니다.']))
        return {'items':items}
    if path == '/api/recheck-product':
        code=data.get('code')
        detail=WORKFLOW.client.detail(code)
        candidate=WORKFLOW._put('candidate',{'detail':detail,'extracted':{},'comparison':{}})
        resolved=WORKFLOW.resolve_candidate(candidate)
        if resolved['comparison']['calculation_ready']:
            return WORKFLOW.auto_apply_candidate(candidate)
        return dict(pending=True,**resolved)
    if path == '/api/evaluate':
        rules = json.loads((ROOT / 'verified_rules.json').read_text(encoding='utf-8'))
        return WORKFLOW.evaluate(data.get('products'), data.get('mode', 'single'), rules, profile=data.get('profile'),quantity_intent=data.get('quantity_intent','planned'))
    if path == '/api/demo-evaluate':
        # 가상 예제는 별도 경로에서 서버의 고정 데이터만 사용합니다.
        samples = json.loads((STATIC / 'sample.json').read_text(encoding='utf-8'))
        quantities = data.get('quantities')
        if not isinstance(quantities, list) or len(quantities) != len(samples):
            raise ServiceError('예제 수량을 확인하세요.')
        for sample, quantity in zip(samples, quantities):
            sample['quantity'] = quantity
        result = calculate(samples, data.get('mode', 'single'), [], profile=data.get('profile'),quantity_intent=data.get('quantity_intent','planned'))
        result['demo'] = True
        return result
    raise ServiceError('지원하지 않는 요청입니다.')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # API 키, 제품 검색어, 사진 내용 등이 요청 로그에 남지 않도록 합니다.
        pass

    def send(self, status, payload, mime='application/json; charset=utf-8'):
        raw = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def valid_host(self):
        return self.headers.get('Host') == ALLOWED_HOST

    def authorized(self):
        if not PASSWORD:
            return True
        header = self.headers.get('Authorization', '')
        try:
            given = base64.b64decode(header.removeprefix('Basic '), validate=True).decode('utf-8').partition(':')[2]
        except ValueError:
            return False
        return hmac.compare_digest(given.encode(), PASSWORD.encode())

    def require_auth(self):
        if self.authorized():
            return False
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="runningflow", charset="UTF-8"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return True

    def do_GET(self):
        if self.require_auth():
            return
        if not self.valid_host():
            self.send(403, {'error': '허용되지 않은 호스트입니다.'})
            return
        path = urlsplit(self.path).path
        if path == '/api/status':
            self.send(200, status_payload())
            return
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/sample.json': ('sample.json', 'application/json; charset=utf-8')}
        if path not in assets:
            self.send(404, {'error': '페이지를 찾을 수 없습니다.'})
            return
        filename, mime = assets[path]
        raw = (STATIC / filename).read_bytes()
        if path == '/':
            revision = client_revision()
            html = raw.decode('utf-8').replace('src="/app.js"', f'src="/app.js?v={revision}"')
            html = html.replace('href="/style.css"', f'href="/style.css?v={revision}"')
            raw = html.encode('utf-8')
        self.send(200, raw, mime)

    def do_POST(self):
        if self.require_auth():
            return
        if (not self.valid_host() or self.headers.get('Origin') != ('https://' if PUBLIC else 'http://') + ALLOWED_HOST
                or not hmac.compare_digest(self.headers.get('X-App-Token', ''), TOKEN)):
            self.send(403, {'error': '이 앱 화면에서 요청해 주세요.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 15 * 1024 * 1024:
                raise ServiceError('요청 크기가 허용 범위를 벗어났습니다.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ServiceError('요청 형식을 확인하세요.')
            path = urlsplit(self.path).path
            result = dispatch_post(path, data)
            self.send(200, result)
        except ServiceError as error:
            self.send(400, {'error': str(error)})
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            self.send(400, {'error': '입력 데이터 또는 로컬 기준 파일 형식을 확인하세요.'})
        except Exception:
            self.send(500, {'error': '처리 중 오류가 발생했습니다. 인증키를 제외한 입력 형식을 확인해 주세요.'})


class LocalHTTPServer(ThreadingHTTPServer):
    """Windows에서 같은 포트의 구버전 서버가 함께 응답하는 것을 방지합니다."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def run():
    global ALLOWED_HOST, PUBLIC, PASSWORD
    parser = argparse.ArgumentParser(description='러닝플로우 약품 성분 확인')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    conf = settings()
    port = int(conf.get('PORT', '8767'))
    PASSWORD = conf.get('APP_PASSWORD', '')
    # Render는 RENDER_EXTERNAL_HOSTNAME을 자동으로 넣습니다. 다른 도메인은 PUBLIC_HOST로 지정합니다.
    public_host = conf.get('PUBLIC_HOST') or conf.get('RENDER_EXTERNAL_HOSTNAME', '')
    if public_host:
        if not PASSWORD:
            raise SystemExit('공개 배포에는 APP_PASSWORD 환경변수가 필요합니다. 키가 노출되지 않도록 실행을 중단합니다.')
        PUBLIC, ALLOWED_HOST, bind = True, public_host, '0.0.0.0'
        args.no_browser = True
    else:
        ALLOWED_HOST, bind = f'127.0.0.1:{port}', '127.0.0.1'
    try:
        server = LocalHTTPServer((bind, port), Handler)
    except OSError:
        # Reopening the launcher should open the running app rather than report a failure.
        try:
            with build_opener(ProxyHandler({})).open('http://' + ALLOWED_HOST + '/api/status', timeout=3) as response:
                existing = json.loads(response.read(65536))
            same_app = (existing.get('refresh_behavior') == 'status_only'
                        and existing.get('config_policy') == CONFIG_POLICY
                        and 'duplicates_only_v1' in existing.get('features', [])
                        and existing.get('client_revision') == client_revision())
        except Exception:
            same_app = False
        if same_app:
            print('이미 실행 중입니다: http://' + ALLOWED_HOST)
            if not args.no_browser:
                webbrowser.open('http://' + ALLOWED_HOST)
            return
        raise SystemExit('이 포트를 다른 프로그램 또는 다른 버전의 앱이 사용 중입니다. 기존 실행 창을 종료한 뒤 다시 실행하세요.') from None
    if PUBLIC:
        print(f'러닝플로우 배포 실행: https://{ALLOWED_HOST} (포트 {port})', flush=True)
    else:
        print(f'러닝플로우 실행: http://{ALLOWED_HOST}')
        print('키는 .env에 입력하세요. 종료: Ctrl+C. 현재 PC에서만 접속할 수 있습니다.')
    if not args.no_browser:
        webbrowser.open('http://' + ALLOWED_HOST)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    run()
