"""Validated profile conditions only; no inferred pediatric or sex dose factors."""
from decimal import Decimal, InvalidOperation
from mfds_client import ServiceError


def validate_profile(profile=None):
    if profile is None: return {'age_group':'adult','sex':'unspecified'}
    if not isinstance(profile,dict) or profile.get('age_group') not in ('child','adolescent','adult','age_based') or profile.get('sex') not in ('male','female','unspecified'):
        raise ServiceError('연령대와 성별 선택값을 확인하세요.')
    result={'age_group':profile['age_group'],'sex':profile['sex']}
    for field,maximum in [('age_years',130),('weight_kg',500)]:
        value=profile.get(field)
        if value in (None,''): continue
        try: value=Decimal(str(value))
        except (InvalidOperation,ValueError):raise ServiceError('나이·체중을 숫자로 입력하세요.') from None
        if not value.is_finite() or value<0 or (field=='weight_kg' and value==0) or value>maximum:
            raise ServiceError('나이·체중의 입력 범위를 확인하세요.')
        result[field]=str(value)
    return result


def require_complete_profile(profile):
    if not isinstance(profile,dict):raise ServiceError('만 나이와 체중을 입력해 주세요.')
    for field,label in [('age_years','만 나이'),('weight_kg','체중')]:
        if profile.get(field) is None or str(profile[field]).strip() == '':
            raise ServiceError(label+'를 입력해 주세요.')
    # No demographic category inferred; exact label ages determine applicability.
    return validate_profile({'age_group':'age_based','sex':'unspecified',
                             'age_years':profile['age_years'],'weight_kg':profile['weight_kg']})


def matches(rule,profile,products):
    ingredient_scope = rule.get('scope') == 'ingredient'
    if ingredient_scope:
        # Cross-product references require explicit adult coverage and exact code matching by caller.
        if rule.get('population') != 'adult' or Decimal(str(rule.get('min_age_years',0))) < 19:return False
        if not profile.get('age_years') or Decimal(profile['age_years']) < 19:return False
    if profile['age_group']=='age_based':
        if (not ingredient_scope and not rule.get('product_codes')) or ('min_age_years' not in rule and 'max_age_years' not in rule):return False
    elif rule.get('population') != profile['age_group']:return False
    if rule.get('sex','any') not in ('any','male','female'):return False
    if rule.get('sex','any') not in ('any',profile['sex']):return False
    # Minors need explicit product scope and exact numerical age constraints.
    if profile['age_group'] != 'adult' and not ingredient_scope and (not rule.get('product_codes') or rule.get('min_age_years') is None or (rule.get('max_age_years') is None and rule.get('min_age_years') is None)):return False
    for field,lower,upper in [('age_years','min_age_years','max_age_years'),('weight_kg','min_weight_kg','max_weight_kg')]:
        if lower not in rule and upper not in rule:continue
        if field not in profile:return False
        value=Decimal(profile[field])
        try:
            if lower in rule and value < Decimal(str(rule[lower])):return False
            if upper in rule and value >= Decimal(str(rule[upper])):return False
        except InvalidOperation:return False
    if rule.get('product_codes') and not set(products).issubset(set(rule['product_codes'])):return False
    if 'limit_mg_per_kg' in rule and 'weight_kg' not in profile:return False
    # Unknown conditions must not silently be ignored.
    allowed={'id','reviewed','ingredient_code','mode','population','reviewer','reviewed_at','source_url','product_codes','limit_mg','sex','min_age_years','max_age_years','min_weight_kg','max_weight_kg','limit_mg_per_kg','source_evidence','product_name','review_method','scope'}
    return not (set(rule)-allowed)
