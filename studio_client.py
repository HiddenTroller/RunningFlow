"""Studio Extract 우선 선택, 설정 버전 정책, 업로드 파일 정리."""
import json
import logging
import re
import time
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from config import settings
from mfds_client import ServiceError
from extraction_adapter import normalize_extraction

BASE = 'https://api.upstage.ai/v2'
LOG = logging.getLogger(__name__)
PINNED_CONFIG_ID = '15'


def build_job_payload(agent, file_id, config_id=None):
    """사용자 요청으로 설정 15 고정. 호환 인자나 환경 변수로 변경하지 않습니다."""
    payload = {'model': agent, 'config_id': PINNED_CONFIG_ID, 'include': ['all'], 'input': [
        {'role': 'user', 'content': [{'type': 'input_file', 'file_id': file_id}]}]}
    return payload


def _request(path, key, payload=None, content_type='application/json', method=None):
    request = Request(BASE + path, data=payload,
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': content_type}, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ServiceError('Studio 결과 크기를 초과했습니다. 확인 필요.')
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raise ServiceError(f'Upstage HTTP {error.code}: 키·접근 권한·사용 한도를 확인하세요.') from None
    except (URLError, TimeoutError):
        raise ServiceError('Upstage에 연결하지 못했습니다. 확인 필요.') from None
    except (ValueError, TypeError, UnicodeError):
        raise ServiceError('Upstage 응답 형식을 확인할 수 없습니다.') from None


def _step_text(step):
    if not isinstance(step, dict):
        return ''
    parts = step.get('content')
    if isinstance(parts, str):
        return parts
    if not isinstance(parts, list):
        return ''
    return '\n'.join(p['text'] for p in parts if isinstance(p, dict)
                     and p.get('type') == 'output_text' and isinstance(p.get('text'), str))


def _parse_json(text):
    text = text.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.I)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


def select_output(job):
    outputs = job.get('output')
    outputs = outputs if isinstance(outputs, list) else []
    extracts = [s for s in outputs if isinstance(s, dict) and 'extract' in str(s.get('model', '')).lower()]
    for step in reversed(extracts):
        text = _step_text(step)
        parsed = _parse_json(text)
        if parsed is not None:
            return text, parsed, str(step.get('model')), []
    warnings = ['Extract 결과를 JSON으로 읽지 못해 마지막 출력으로 대체했습니다. 확인 필요.'] if extracts else []
    step = outputs[-1] if outputs else {}
    text = _step_text(step) or (job.get('output_text') if isinstance(job.get('output_text'), str) else '')
    return text, _parse_json(text), str(step.get('model', 'last')) if isinstance(step, dict) else 'last', warnings



def search_name_from_final(value):
    """최종 출력의 단일 제품명만 연결. 화면용 원문은 변경하지 않습니다."""
    candidate = value.strip()
    fenced = re.fullmatch(r'```(?:json|text)?\s*([\s\S]*?)\s*```', candidate, re.I)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        candidate = next((parsed[k] for k in ('search_product_name', 'product_name_raw', 'product_name', '제품명', 'content')
                          if isinstance(parsed.get(k), str) and parsed[k].strip()), '')
    elif isinstance(parsed, str):
        candidate = parsed
    candidate = candidate.strip()
    # 한 줄 출력의 표시용 인용·굵게·제목·출처 번호만 제거합니다.
    candidate = re.sub(r'(?:\s*(?:\[\d+\]|【†\d+】|【\d+†[^】]*】))+\s*$', '', candidate).strip()
    candidate = re.sub(r'^#{1,6}\s+', '', candidate)
    for left, right in (('**', '**'), ('`', '`'), ('"', '"'), ('“', '”'), ("'", "'")):
        if candidate.startswith(left) and candidate.endswith(right) and len(candidate) > len(left) + len(right):
            candidate = candidate[len(left):-len(right)].strip()
    candidate = re.sub(r'(?:\s*(?:\[\d+\]|【†\d+】|【\d+†[^】]*】))+\s*$', '', candidate).strip()
    valid = bool(re.fullmatch(r'[가-힣a-zA-Z0-9®™().· /%+_-]{1,150}', candidate))
    return candidate if valid else ''


def final_output(job):
    """Instruct 또는 Extract/Parse가 아닌 최종 메시지를 읽습니다."""
    outputs = job.get('output')
    outputs = [s for s in outputs if isinstance(s, dict)] if isinstance(outputs, list) else []
    instructs = [s for s in outputs if 'instruct' in str(s.get('model', '')).lower()]
    # Instruct는 실제 모델명(solar 등)으로 반환될 수도 있습니다.
    last = outputs[-1] if outputs else {}
    model = str(last.get('model', '')).lower()
    final_message = last if last and not any(v in model for v in ('extract', 'parse')) else {}
    step = instructs[-1] if instructs else final_message
    value = _step_text(step)
    if not value and (step or not outputs) and isinstance(job.get('output_text'), str):
        value = job['output_text']
    return {'final_text': value, 'final_model': str(step.get('model', 'final')) if value else '',
            'search_product_name': search_name_from_final(value)}


def analyze_photo(content, mime):
    config = settings()
    key, agent = config.get('UPSTAGE_API_KEY', ''), config.get('UPSTAGE_AGENT_ID', '')
    if not key or not agent.startswith('agt_'):
        raise ServiceError('.env에 UPSTAGE_API_KEY와 UPSTAGE_AGENT_ID를 입력하세요.')
    extension = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}.get(mime)
    if not extension or not content or len(content) > 10 * 1024 * 1024:
        raise ServiceError('JPG·PNG·WEBP 사진 한 장(10MB 이하)을 선택하세요.')
    boundary = 'Learningflow' + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="photo.{extension}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    file_id, result = None, None
    try:
        uploaded = _request('/files', key, body, 'multipart/form-data; boundary=' + boundary)
        file_id = uploaded.get('id') if isinstance(uploaded, dict) else None
        if not file_id or not isinstance(file_id, str):
            raise ServiceError('Upstage 파일 ID를 받지 못했습니다.')
        payload = build_job_payload(agent, file_id)
        job = _request('/responses', key, json.dumps(payload).encode())
        if not isinstance(job, dict) or not job.get('id'):
            raise ServiceError('Upstage 작업 ID를 받지 못했습니다.')
        deadline = time.monotonic() + 240
        while job.get('status') in ('queued', 'in_progress'):
            if time.monotonic() >= deadline:
                raise ServiceError('분석 대기 시간이 초과되었습니다. Studio 작업 상태를 확인하세요.')
            time.sleep(2)
            job = _request('/responses/' + quote(str(job['id']), safe='') + '?include=all', key)
        if job.get('status') != 'completed':
            raise ServiceError('Studio 작업이 완료되지 않았습니다. 실패 노드를 확인하세요.')
        text, raw_extracted, selected, warnings = select_output(job)
        extracted, adapter_warnings = normalize_extraction(raw_extracted)
        warnings.extend(adapter_warnings)
        result = {'job_id': job['id'], 'agent_id': agent,
                  'config_policy': 'pinned',
                  'requested_config_id': PINNED_CONFIG_ID, 'config_id': job.get('config_id'),
                  'legacy_config_ignored': bool(config.get('UPSTAGE_CONFIG_ID', '').strip()),
                  'selected_model': selected, 'text': text, 'extracted': extracted,
                  'raw_extracted': raw_extracted, 'warnings': warnings}
        result['extract_text'] = text
        result.update(final_output(job))
        result['text'] = result['final_text']
        return result
    finally:
        if file_id:
            try:
                deleted = _request('/files/' + quote(file_id, safe=''), key, method='DELETE')
                if isinstance(deleted, dict) and deleted.get('deleted') is False:
                    raise ServiceError('파일 삭제 미완료')
                if result is not None:
                    result['file_cleanup'] = 'deleted'
            except Exception:
                message = 'Upstage 업로드 파일 삭제를 완료하지 못했습니다. Studio에서 파일 보관 상태를 확인하세요.'
                LOG.warning(message)
                if result is not None:
                    result['warnings'].append(message)
                    result['file_cleanup'] = 'warning'
