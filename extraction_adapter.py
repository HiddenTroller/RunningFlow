"""Studio의 한국어/영문 Extract를 공통 구조로 연결. 원문 보존, 정보 추정 금지."""
import re


def scalar(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        values = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        # 제품명처럼 단일 값은 한 값이 명확할 때만 사용합니다.
        return values[0] if len(values) == 1 else ''
    return ''


def original_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return '\n'.join(v.strip() for v in value if isinstance(v, str) and v.strip())
    return ''


def pick(data, *keys):
    for key in keys:
        value = data.get(key)
        if value not in (None, '', []):
            return value
    return None


def ingredient_row(value):
    if isinstance(value, dict):
        result = dict(value)
        name = scalar(pick(value, 'ingredient_name', '성분명'))
        strength = scalar(pick(value, 'strength_per_unit', '함량 원문'))
        if not strength:
            amount, unit = pick(value, '함량', 'amount'), scalar(pick(value, '단위', 'unit'))
            if isinstance(amount, (str, int, float)) and not isinstance(amount, bool) and unit:
                strength = str(amount).strip() + ' ' + unit
                basis = scalar(pick(value, '함량 기준', '함량기준', 'basis'))
                if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?\s*(?:정|캡슐|포|mL)', basis, re.I):
                    strength = basis + ' 중 ' + strength
        result.update(ingredient_name=name,
                      base_ingredient_name=scalar(pick(value, 'base_ingredient_name', '기본성분명')) or name,
                      strength_per_unit=strength,
                      ingredient_standard=scalar(pick(value, 'ingredient_standard', '규격')),
                      source_raw=value.get('source_raw', value))
        return result
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    parts = [part.strip() for part in raw.split('/')]
    name, strength = '', ''
    if len(parts) in (3, 4) and parts[0]:
        # 실제 저장 결과 예: 아세트아미노펜 / 500 / mg / 1정.
        # 숫자와 단위를 결합할 뿐, 해석 불가 함량을 유효 숫자로 만들지 않습니다.
        name = parts[0]
        strength = parts[1] + ' ' + parts[2]
        if len(parts) == 4:
            basis = parts[3]
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?\s*(?:정|캡슐|포|mL)', basis, re.I):
                strength = basis + ' 중 ' + strength
            elif basis not in ('', '기재 없음', '판독 불가', '확인 필요'):
                # 알 수 없는 분모를 버려 잘못 일치시키지 않습니다.
                strength = raw
    else:
        # 사람이 보기 좋은 결합 표기도 명시된 숫자/단위가 있을 때만 분리.
        match = re.fullmatch(r'(.+?)\s+([0-9]+(?:\.[0-9]+)?\s*(?:밀리그램|마이크로그램|그램|mg|mcg|ug|μg|µg|g))(?:\s*\(([0-9]+(?:\.[0-9]+)?\s*(?:정|캡슐|포|mL))당\))?', raw, re.I)
        if match:
            name, strength = match.group(1).strip(), match.group(2)
            if match.group(3):
                strength = match.group(3) + ' 중 ' + strength
    return {'ingredient_name': name or raw, 'base_ingredient_name': name or raw,
            'strength_per_unit': strength, 'ingredient_standard': '', 'source_raw': value}


def normalize_extraction(data):
    if not isinstance(data, dict):
        return {}, ['Extract JSON 객체를 확인하지 못했습니다. 확인 필요.']
    # 한 단계의 표준 래퍼만 해제합니다. 임의 재귀 검색으로 다른 제품을 섞지 않음.
    for wrapper in ('extracted', 'data'):
        if not any(k in data for k in ('제품명', 'product_name_raw', 'effective_ingredients', '유효성분 목록')) and isinstance(data.get(wrapper), dict):
            data = data[wrapper]
            break
    warnings = list(data.get('adapter_warnings', [])) if isinstance(data.get('adapter_warnings'), list) else []
    result = dict(data)
    result.update(product_name_raw=scalar(pick(data, 'product_name_raw', '제품명', 'product_name')),
                  manufacturer=scalar(pick(data, 'manufacturer', '제조사', '업체명')),
                  dosage_and_administration=original_text(pick(data, 'dosage_and_administration', '성인 용법·용량', '성인 용법용량')),
                  max_daily_dose=original_text(pick(data, 'max_daily_dose', '하루 최대량')))
    values = pick(data, 'effective_ingredients', '유효성분 목록')
    if isinstance(values, str):
        values = re.split(r'(?:\r?\n|<br\s*/?>)', values, flags=re.I)
    if not isinstance(values, list):
        values = []
        warnings.append('사진의 유효성분 목록이 없거나 지원하지 않는 형식입니다. 확인 필요.')
    converted = []
    for value in values[:100]:
        row = ingredient_row(value)
        if row is not None:
            converted.append(row)
        else:
            warnings.append('사진의 일부 성분 행을 읽지 못했습니다. 확인 필요.')
    if len(values) > 100:
        warnings.append('성분 목록이 100개를 초과하여 일부만 읽었습니다. 확인 필요.')
    result['effective_ingredients'] = converted
    cautions = pick(data, 'do_not_take_with', '중복·병용 관련 주의사항')
    if isinstance(cautions, str):
        cautions = [{'item_name': cautions.strip()}] if cautions.strip() else []
    elif isinstance(cautions, list):
        cautions = [dict(v) if isinstance(v, dict) else {'item_name': v} for v in cautions if isinstance(v, (dict,str))]
    else:
        cautions = []
    result['do_not_take_with'] = cautions
    result['schema_source'] = 'korean' if any(k in data for k in ('제품명','유효성분 목록')) else 'english'
    if not result['product_name_raw']:
        warnings.append('제품명을 한 개로 확인하지 못했습니다. 직접 검색하세요.')
    warnings = list(dict.fromkeys(w for w in warnings if isinstance(w, str)))
    result['adapter_warnings'] = warnings
    return result, warnings
