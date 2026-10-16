"""Official ingredient identity comparison only; no quantities or dose judgments."""
from normalization import normalize_name
from official_text import dosage_text
from matcher import official_ingredients
import re

def compare_duplicates(products):
    groups = {}
    for product in products:
        seen = set()
        for ingredient in product.get('ingredients', []):
            name = ingredient.get('name', '')
            code = str(ingredient.get('ingredient_code') or '').strip()
            key = ('code', code) if code else ('name', normalize_name(name))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            entry = groups.setdefault(key, {'ingredient': name, 'ingredient_code': code,
                'grouping': '공식 성분코드' if code else '이름 기준으로 묶음', 'products': []})
            if not any(p['code'] == product['code'] for p in entry['products']):
                entry['products'].append({'code': product['code'], 'name': product['name']})
    rows = list(groups.values())
    for row in rows:
        row['duplicate'] = len(row['products']) > 1
    return {'kind': 'duplicates_only', 'product_count': len(products), 'ingredients': rows,
            'duplicate_count': sum(row['duplicate'] for row in rows),
            'unconfirmed_products': [{'code':p['code'],'name':p['name']} for p in products if not p.get('ingredients') or p.get('ingredient_identity_partial')],
            'products': [product_summary(p) for p in products],
            'note': '공식 성분에서 확인한 중복만 표시합니다. 섭취량·용량 초과·복용 가능 여부는 판단하지 않습니다.'}


def product_summary(product):
    directions = dosage_text(product.get('directions_text', ''))
    warnings = dosage_text(product.get('warning_text', ''))
    # Quote only explicit daily maximum language. Never multiply frequency by dose.
    paragraphs = [line.strip() for line in directions.splitlines() if line.strip()]
    maximum = [line for line in paragraphs if re.search(r'1일|하루|24\s*시간', line)
               and re.search(r'최대|최고|초과.{0,15}(?:않|말|안)|넘지', line)]
    daily = [line for line in paragraphs if re.search(r'1일|하루|24\s*시간', line)]
    code = str(product.get('code', ''))
    return {'code': code, 'name': product.get('name', ''),
            'daily_max_text': '\n'.join(maximum),
            'daily_directions_text': '\n'.join(daily),
            'amount_unconfirmed': bool(product.get('amount_unconfirmed')),
            'ingredient_identity_partial': bool(product.get('ingredient_identity_partial') or not product.get('ingredients')),
            'daily_max_status': 'explicit' if maximum else 'directions_only' if daily else 'missing', 'directions_text': directions,
            'warnings_text': warnings,
            'source_url': 'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=' + code if code.isdigit() else ''}


def identity_only_product(record):
    """Names/codes from the selected official candidate; never reuse photo amounts."""
    detail=record['detail'];product=detail.get('product',{})
    ingredients=[{'name':row['name'],'ingredient_code':row['ingredient_code']} for row in official_ingredients(detail) if row['name']]
    # MATERIAL_NAME is structured official active-ingredient data, not free prose.
    # Parse only explicitly labelled ingredient names; do not split arbitrary drug names.
    if not ingredients:
        for block in str(product.get('MATERIAL_NAME') or '').split(';'):
            fields={}
            for part in block.split('|'):
                key,sep,value=part.partition(':')
                if sep:fields[key.strip()]=value.strip()
            if fields.get('성분명'):
                ingredients.append({'name':fields['성분명'],'ingredient_code':''})
    return {'code':str(product.get('ITEM_SEQ','')), 'name':product.get('ITEM_NAME','제품 확인 필요'),
            'ingredients':ingredients, 'amount_unconfirmed':True,
            'ingredient_identity_partial':bool(detail.get('warnings')) or not ingredients,
            'directions_text':product.get('UD_DOC_DATA',''), 'warning_text':product.get('NB_DOC_DATA','')}
