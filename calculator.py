"""확인된 입력만 계산합니다. 성분명 유사도 매칭 및 최대량 추정은 하지 않습니다."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from mfds_client import ServiceError
from normalization import normalize_name
from population_rules import validate_profile, matches
from official_text import dosage_text
from label_comparison import compare_label

FACTORS = {'mg': Decimal('1'), 'g': Decimal('1000'), 'μg': Decimal('0.001'),
           'µg': Decimal('0.001'), 'ug': Decimal('0.001'), 'mcg': Decimal('0.001')}


def number(value, label, allow_zero=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ServiceError(label + ': 숫자를 입력하세요.') from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0) or result > 1000000:
        raise ServiceError(label + ': 유효한 범위의 양수를 입력하세요.')
    return result


def to_mg(value, unit):
    """대조와 계산에서 공통 Decimal 환산 로직 사용."""
    if unit not in FACTORS:
        raise ServiceError('지원하지 않는 함량 단위입니다. 확인 필요.')
    return number(value, '함량') * FACTORS[unit]


def calculate(products, mode='single', rules=None, profile=None, quantity_intent='planned'):
    if quantity_intent not in ('taken','planned'):raise ServiceError('이미 먹은 양인지 앞으로 먹을 양인지 선택하세요.')
    profile = validate_profile(profile)
    if mode not in ('single', 'day'):
        raise ServiceError('1회 가정 또는 1일 가정을 선택하세요.')
    if not isinstance(products, list) or not products or len(products) > 30:
        raise ServiceError('계산할 제품을 1~30개 추가하세요.')
    totals, seen, exclusions = {}, set(), []
    official_directions = []
    product_comparisons = []
    for product in products:
        if not isinstance(product, dict):
            raise ServiceError('제품 데이터 형식이 잘못되었습니다.')
        name = str(product.get('name', '')).strip()
        code = str(product.get('code', '')).strip()
        if not name or not code or code in seen:
            raise ServiceError('제품명·품목코드를 확인하고 같은 제품을 여러 번 추가하지 마세요.')
        seen.add(code)
        if product.get('confirmed') is not True:
            raise ServiceError(name + ': 공식 원문과 함량 기준 확인이 필요합니다.')
        quantity = number(product.get('quantity'), name + ' 가정 수량', allow_zero=True)
        if quantity == 0:
            exclusions.append(name + ': 가정 수량 0으로 제외')
            continue
        product_comparisons.append(compare_label(product,profile,mode))
        official_directions.append({'product_code':code,'product_name':name,
            'text':dosage_text(product.get('directions_text','')),
            'warnings_text':dosage_text(product.get('warning_text','')),
            'source_url':'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq='+code if code.isdigit() else '',
            'quantity':str(quantity),'quantity_unit':product.get('quantity_unit','')})
        basis_unit = product.get('quantity_unit')
        ingredients = product.get('ingredients')
        if basis_unit not in ('정', '캡슐', 'mL', '포', 'g', '매', '개', '회') or not isinstance(ingredients, list) or not ingredients:
            raise ServiceError(name + ': 성분과 수량 단위를 확인하세요.')
        ingredient_seen = set()
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                raise ServiceError(name + ': 성분 형식이 잘못되었습니다.')
            component = str(ingredient.get('name', '')).strip()
            mapping_code = str(ingredient.get('ingredient_code', '')).strip()
            unit = ingredient.get('unit')
            evidence = str(ingredient.get('evidence', '')).strip()
            if not component or not evidence or unit not in (*FACTORS, 'IU') or ingredient.get('basis_unit') != basis_unit:
                raise ServiceError(name + ': 성분명·지원 단위·함량 기준·원문 근거를 확인하세요.')
            # 코드가 있으면 코드로, 없으면 정확한 표기명으로만 묶고 일치 수준을 별도 표시합니다.
            key = 'code:' + mapping_code if mapping_code else 'name:' + normalize_name(component)
            measurement_basis = ingredient.get('measurement_basis','mass')
            if measurement_basis not in ('mass','potency'): raise ServiceError('성분 측정 기준을 확인하세요.')
            if unit == 'IU' or measurement_basis != 'mass': key += ':' + unit + ':' + measurement_basis
            if key in ingredient_seen:
                raise ServiceError(name + ': 동일 성분 행이 반복됩니다. 중복 행을 확인하세요.')
            ingredient_seen.add(key)
            amount = number(ingredient.get('amount'), component + ' 함량')
            basis = number(ingredient.get('basis_quantity'), component + ' 기준 수량')
            dose = (amount if unit == 'IU' else to_mg(amount, unit)) * quantity / basis
            row = totals.setdefault(key, {'ingredient': component, 'ingredient_code': mapping_code,
                                         'total_unit': 'IU' if unit == 'IU' else 'mg', 'measurement_basis': measurement_basis,
                                         'matching': '공식 성분코드' if mapping_code else '이름 기준으로 묶음',
                                         'total': Decimal('0'), 'products': [], 'contributions': []})
            row['total'] += dose
            row['products'].append(code)
            row['contributions'].append({'product': name, 'product_code': code, 'mg': str(dose) if unit != 'IU' else None, 'amount':str(dose), 'unit':row['total_unit'],
                                         'measurement_basis':measurement_basis, 'equivalence':ingredient.get('equivalence',''),
                                         'evidence': evidence, 'source': product.get('source', ''),
                                         'quantity': str(quantity), 'quantity_unit': basis_unit})
    if not totals:
        raise ServiceError('0보다 큰 가정 수량을 하나 이상 입력하세요.')
    output = []
    for row in totals.values():
        row['total_amount'] = str(row.pop('total'))
        row['total_mg'] = row['total_amount'] if row['total_unit'] == 'mg' else None
        row['duplicate'] = len(row['products']) > 1
        # 기준은 서버 로컬의 검토 완료 규칙에서만 가져오며 클라이언트 최대량은 받지 않습니다.
        candidates = [r for r in (rules or []) if row['total_unit']=='mg' and row['measurement_basis']=='mass' and r.get('reviewed') is True
                      and r.get('ingredient_code') and r.get('ingredient_code') == row['ingredient_code']
                      and r.get('mode') == mode and matches(r,profile,row['products'])
                      and r.get('reviewer') and r.get('reviewed_at') and r.get('source_url')
                      and (not r.get('product_codes') or
                           set(row['products']).issubset(set(r['product_codes'])))]
        if profile['age_group']=='age_based':
            # Child/adolescent copies of the same exact age rule are one criterion.
            unique={}
            for rule in candidates:
                identity=tuple(sorted((k,str(v)) for k,v in rule.items() if k not in ('id','population')))
                unique.setdefault(identity,rule)
            candidates=list(unique.values())
        # A product-specific rule that covers every contribution is more specific.
        specific=[r for r in candidates if r.get('scope','product')=='product']
        if specific:candidates=specific
        row['reference_percent'] = None
        row['excess_mg'] = None
        row['criterion_status'] = 'unknown'
        row['criterion_note'] = '이 성분·나이·체중·제품 조합에 적용할 공식 합산 기준이 없습니다. 제품별 표시 용법을 별도로 확인하세요.'
        related=[r for r in (rules or []) if r.get('reviewed') is True and r.get('ingredient_code')==row['ingredient_code']]
        if related and not any(r.get('mode')==mode for r in related):
            row['criterion_note']='등록된 기준은 하루 총량용입니다. 하루 기준과 비교하려면 ‘하루 총수량’을 선택하고 실제 하루 총량을 입력하세요. 1회량에 하루 기준을 적용하지 않습니다.'
        if len(candidates) == 1:
            rule = candidates[0]
            if ('limit_mg' in rule) == ('limit_mg_per_kg' in rule):
                raise ServiceError('용량 기준은 고정량 또는 체중당 용량 중 하나여야 합니다.')
            limit = (number(rule['limit_mg_per_kg'], '체중당 기준') * number(profile.get('weight_kg'), '체중')
                     if 'limit_mg_per_kg' in rule else number(rule.get('limit_mg'), '검증 기준'))
            row.update(criterion_status='exceeded' if Decimal(row['total_mg']) > limit else 'not_exceeded',
                       reference_percent=str(Decimal(row['total_mg']) / limit * Decimal('100')),
                       criterion_scope=rule.get('scope','product'),
                       limit_mg=str(limit), excess_mg=str(max(Decimal('0'),Decimal(row['total_mg'])-limit)), rule_source=rule['source_url'], rule_id=rule.get('id', ''), rule_evidence=rule.get('source_evidence',''),
                       rule_review_method=rule.get('review_method',''),
                       criterion_note=('여러 제품의 동일 성분 합산에 대한 공식 하루 기준 비교입니다. 제품별 제한과 복용 간격은 별도로 확인하세요.' if rule.get('scope')=='ingredient' else '등록된 품목·연령 조건의 용량 기준 비교입니다. 다른 제품에 일괄 적용하는 기준이 아닙니다.'))
        elif len(candidates) > 1:
            row['criterion_note'] = '적용 기준이 여러 개입니다. 기준 충돌 확인 필요.'
        output.append(row)
    reference=None
    if quantity_intent == 'taken':
        comparable=[r for r in output if r.get('reference_percent') is not None]
        highest=max(comparable,key=lambda r:Decimal(r['reference_percent'])) if comparable else None
        reference={'comparable_count':len(comparable),'unknown_count':len(output)-len(comparable),
                   'ingredient':highest['ingredient'] if highest else None,
                   'percent':highest['reference_percent'] if highest else None,
                   'total_mg':highest['total_mg'] if highest else None,
                   'limit_mg':highest['limit_mg'] if highest else None,
                   'excess_mg':highest['excess_mg'] if highest else None,
                   'criterion_status':highest['criterion_status'] if highest else 'unknown'}
    return {'mode': mode, 'created_at': datetime.now(timezone.utc).isoformat(), 'ingredients': output,
            'overall': 'not_a_safety_assessment', 'excluded': exclusions,
            'unassessed': ['실제 복용 이력·시간·간격', '병용금기 및 효능군 중복의 자동 조회',
                           '개인 질환·임신·간·신장 기능', '성분코드가 없는 성분의 동의어·염형 차이'],
            'profile': profile, 'quantity_intent':quantity_intent,'official_directions':official_directions,'product_comparisons':product_comparisons,'intake_reference':reference,
            'notice': '가정 수량에 따른 계산입니다. 최대량 미초과는 추가 복용 가능 또는 병용 안전을 의미하지 않습니다.'}
