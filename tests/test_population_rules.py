import unittest
from calculator import calculate
from population_rules import matches,validate_profile,require_complete_profile
from mfds_client import ServiceError

class PopulationTests(unittest.TestCase):
    def rule(self):
        return dict(id='synthetic',reviewed=True,reviewer='test',reviewed_at='test',source_url='https://example.test',ingredient_code='X',mode='single',population='child',product_codes=['P'],limit_mg='10',min_age_years=5,max_age_years=10)
    def product(self):
        return dict(name='가상약',code='P',confirmed=True,quantity='1',quantity_unit='정',ingredients=[dict(name='가상성분',ingredient_code='X',amount='12',unit='mg',basis_quantity='1',basis_unit='정',evidence='synthetic')])
    def test_child_rule_and_boundary(self):
        p={'age_group':'child','sex':'unspecified','age_years':'7'}
        self.assertEqual(calculate([self.product()],rules=[self.rule()],profile=p)['ingredients'][0]['criterion_status'],'exceeded')
        p['age_years']='10'
        self.assertEqual(calculate([self.product()],rules=[self.rule()],profile=p)['ingredients'][0]['criterion_status'],'unknown')
    def test_no_adult_fallback(self):
        r=self.rule();r['population']='adult'
        self.assertEqual(calculate([self.product()],rules=[r],profile={'age_group':'adolescent','sex':'male'})['ingredients'][0]['criterion_status'],'unknown')
    def test_sex_and_weight_missing_not_applied(self):
        r=self.rule();r.update(sex='female',min_weight_kg=20,max_weight_kg=40)
        self.assertFalse(matches(r,{'age_group':'child','sex':'male','age_years':'7','weight_kg':'30'},['P']))
        self.assertFalse(matches(r,{'age_group':'child','sex':'female','age_years':'7'},['P']))
        self.assertTrue(matches(r,{'age_group':'child','sex':'female','age_years':'7','weight_kg':'30'},['P']))
    def test_no_child_rule_without_product_scope(self):
        r=self.rule();r.pop('product_codes')
        self.assertFalse(matches(r,{'age_group':'child','sex':'male','age_years':'7'},['P']))
    def test_invalid_profile(self):
        for weight in ('NaN','-1','Infinity'):
            with self.assertRaises(ServiceError):validate_profile({'age_group':'child','sex':'male','weight_kg':weight})

    def test_required_profile_fields(self):
        profile=dict(age_group='child',sex='female',age_years='0',weight_kg='7')
        self.assertEqual(require_complete_profile(profile)['age_years'],'0')
        for field in ('age_years','weight_kg'):
            incomplete=dict(profile);incomplete.pop(field)
            with self.assertRaises(ServiceError):require_complete_profile(incomplete)
        for field,value in [('weight_kg','0'),('age_years','NaN')]:
            invalid=dict(profile);invalid[field]=value
            with self.assertRaises(ServiceError):require_complete_profile(invalid)
