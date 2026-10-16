"""사용자 검토 완료 품목별 전체 성분 보완. 출처 보존·mg 환산·원자적 저장."""
import copy
import json
import os
import threading
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from config import ROOT
from calculator import number, to_mg
from normalization import normalize_name
from mfds_client import ServiceError

PATH = ROOT / 'verified_products.json'
LOCK = threading.RLock()


def validate_override(data, product):
    if not isinstance(data, dict) or data.get('reviewed') is not True or data.get('complete') is not True:
        raise ServiceError('전체 유효성분과 1단위당 총함량을 검토했다는 확인이 필요합니다.')
    out = {'product_code':str(product.get('ITEM_SEQ','')), 'product_name':str(product.get('ITEM_NAME',''))}
    if not out['product_code'].isdigit() or not out['product_name']:
        raise ServiceError('조회된 공식 품목을 선택하세요.')
    for field in ('reviewer','reviewed_at','source_url','source_evidence'):
        value = data.get(field)
        if not isinstance(value,str) or not value.strip() or len(value) > 20000:
            raise ServiceError('검토자·확인일·출처 URL·근거 원문이 모두 필요합니다.')
        out[field] = value.strip()
    url = urlsplit(out['source_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ServiceError('공식 자료의 HTTPS 출처 URL을 입력하세요.')
    try:
        if date.fromisoformat(out['reviewed_at']) > date.today():
            raise ValueError()
    except ValueError:
        raise ServiceError('확인일은 오늘 이전의 YYYY-MM-DD 형식이어야 합니다.') from None
    rows = data.get('ingredients')
    if not isinstance(rows,list) or not 1 <= len(rows) <= 100:
        raise ServiceError('제품의 전체 유효성분을 1~100행 입력하세요.')
    converted, codes, names, basis_units = [], set(), set(), set()
    units = {'밀리그램':'mg','그램':'g','마이크로그램':'μg'}
    for row in rows:
        if not isinstance(row,dict):
            raise ServiceError('성분 행 형식을 확인하세요.')
        name = row.get('name'); code = row.get('ingredient_code','')
        if not isinstance(name,str) or not name.strip() or not isinstance(code,str):
            raise ServiceError('성분명과 성분코드 형식을 확인하세요.')
        name, code = name.strip(), code.strip()
        normalized = normalize_name(name)
        if normalized in names or (code and code in codes):
            raise ServiceError('같은 성분을 여러 행에 입력하지 말고 검증된 총함량 한 행으로 입력하세요.')
        names.add(normalized)
        if code: codes.add(code)
        unit = units.get(row.get('unit'), row.get('unit'))
        amount = to_mg(row.get('amount'),unit)
        basis = number(row.get('basis_quantity'),'함량 기준 수량')
        basis_unit = row.get('basis_unit')
        if basis_unit not in ('정','캡슐','포','mL'):
            raise ServiceError('함량 기준 단위는 정·캡슐·포·mL 중 하나여야 합니다.')
        basis_units.add(basis_unit)
        converted.append({'name':name,'ingredient_code':code,'amount':str(amount),'unit':'mg',
                          'basis_quantity':str(basis),'basis_unit':basis_unit,
                          'original':copy.deepcopy(row)})
    if len(basis_units) != 1:
        raise ServiceError('한 제품의 복용 기준 단위는 같아야 합니다.')
    out.update(ingredients=converted, reviewed=True, complete=True,
               saved_at=datetime.now(timezone.utc).isoformat())
    return out


def load_records():
    if not PATH.exists(): return {}
    try:
        data = json.loads(PATH.read_text(encoding='utf-8'))
        if not isinstance(data,dict): raise ValueError()
        return data
    except (ValueError,OSError):
        raise ServiceError('품목별 보완 데이터 파일을 읽지 못했습니다. 계산을 중단합니다.') from None


def save_override(data, product):
    record = validate_override(data,product)
    with LOCK:
        records = load_records()
        old = records.get(record['product_code'])
        record['history'] = ([{k:v for k,v in old.items() if k != 'history'}] + old.get('history',[])) if isinstance(old,dict) else []
        records[record['product_code']] = record
        temporary = PATH.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,PATH)
    return record


def apply_override(detail):
    with LOCK:
        record = load_records().get(str(detail['product'].get('ITEM_SEQ','')))
    if not record: return detail
    # 저장 파일도 다시 검증해 값/단위가 손상된 상태로 사용되지 않게 합니다.
    record = validate_override(record,detail['product'])
    result = copy.deepcopy(detail)
    result['original_official'] = copy.deepcopy(detail)
    result['product_override'] = record
    result['product']['TOTAL_CONTENT'] = ''
    result['ingredients_raw'] = [
        {'MTRAL_NM':r['name'],'MTRAL_CODE':r['ingredient_code'],'QNT':r['amount'],
         'INGD_UNIT_CD':'mg','CPNT_CTNT_CONT':r['basis_quantity']+r['basis_unit']+' 중',
         'VERIFIED_PRODUCT_EVIDENCE':record['source_evidence'],'SOURCE_URL':record['source_url'],
         'REVIEWER':record['reviewer'],'REVIEWED_AT':record['reviewed_at']}
        for r in record['ingredients']]
    result['warnings'] = []
    result['source'] = record['source_url']
    return result
