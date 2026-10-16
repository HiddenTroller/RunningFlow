import json
from pathlib import Path
import unittest
from calculator import calculate

class RegisteredRulesTests(unittest.TestCase):
    def setUp(self):self.rules=json.loads(Path('verified_rules.json').read_text(encoding='utf-8'))
    def result(self,code,component,amount,quantity,age,weight=None,sex='unspecified',mode='day',group='child'):
        p=dict(name='등록 기준 검사',code=code,confirmed=True,quantity=str(quantity),quantity_unit='mL',ingredients=[dict(name='등록 성분',ingredient_code=component,amount=str(amount),unit='mg',basis_quantity='1',basis_unit='mL',evidence='공식 기준 단위 테스트')])
        profile=dict(age_group=group,sex=sex,age_years=str(age))
        if weight is not None:profile['weight_kg']=str(weight)
        return calculate([p],mode,self.rules,profile)['ingredients'][0]
    def test_ibuprofen_age_band_and_boundary(self):
        self.assertEqual(self.result('198601920','M051259',20,20,2)['criterion_status'],'not_exceeded')
        self.assertEqual(self.result('198601920','M051259',20,21,2)['criterion_status'],'exceeded')
        self.assertEqual(self.result('198601920','M051259',20,21,3)['limit_mg'],'600')
        self.assertEqual(self.result('198601920','M051259',20,21,15)['criterion_status'],'unknown')
    def test_weight_limit_requires_weight_and_scope(self):
        self.assertEqual(self.result('202200525','M281939',32,40,7)['criterion_status'],'unknown')
        self.assertEqual(self.result('202200525','M281939',32,40,7,20)['limit_mg'],'1500')
        self.assertEqual(self.result('202200525','M281939',32,50,7,20)['criterion_status'],'exceeded')
        self.assertEqual(self.result('202200525','M281939',32,40,7,43)['criterion_status'],'unknown')
    def test_12plus_exact_product_only(self):
        self.assertEqual(self.result('202106092','M040353',500,8,12,group='adolescent')['limit_mg'],'4000')
        self.assertEqual(self.result('202106092','M040353',500,8,11)['criterion_status'],'unknown')
        self.assertEqual(self.result('different','M040353',500,8,12)['criterion_status'],'unknown')
    def test_no_sex_difference_and_no_single_limit(self):
        for sex in ('male','female','unspecified'):
            self.assertEqual(self.result('198601920','M051259',20,20,2,sex=sex)['limit_mg'],'400')
        self.assertEqual(self.result('198601920','M051259',20,20,2,mode='single')['criterion_status'],'unknown')

    def test_age_only_profile_has_no_duplicate_demographic_rule(self):
        from population_rules import require_complete_profile
        profile=require_complete_profile({'age_years':'7','weight_kg':'25'})
        self.assertEqual(profile['sex'],'unspecified')
        result=self.result('198601920','M051259',20,41,7,25,group='age_based')
        self.assertEqual(result['limit_mg'],'800')
        self.assertEqual(result['criterion_status'],'exceeded')
