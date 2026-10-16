import json
from pathlib import Path
import unittest
from calculator import calculate
from population_rules import require_complete_profile

class IngredientScopeTests(unittest.TestCase):
    def setUp(self):self.rules=json.loads(Path('verified_rules.json').read_text(encoding='utf-8'))
    def product(self,code,amount,quantity):
        return dict(name='검사제품'+code,code=code,confirmed=True,quantity=str(quantity),quantity_unit='정',ingredients=[dict(name='아세트아미노펜',ingredient_code='M040353',amount=str(amount),unit='mg',basis_quantity='1',basis_unit='정',evidence='공식 데이터 구조 검사')])
    def compare(self,products,age='30',mode='day'):
        return calculate(products,mode,self.rules,require_complete_profile({'age_years':age,'weight_kg':'60'}))['ingredients'][0]
    def test_mixed_products_below_and_over(self):
        row=self.compare([self.product('197900277',300,3),self.product('202200407',650,4)])
        self.assertEqual(row['total_mg'],'3500');self.assertEqual(row['limit_mg'],'4000')
        self.assertEqual(row['criterion_status'],'not_exceeded');self.assertEqual(row['criterion_scope'],'ingredient')
        row=self.compare([self.product('197900277',300,4),self.product('202200407',650,5)])
        self.assertEqual(row['criterion_status'],'exceeded');self.assertEqual(row['excess_mg'],'450')
    def test_no_single_or_child_extrapolation(self):
        products=[self.product('197900277',300,3),self.product('202200407',650,4)]
        row=self.compare(products,mode='single');self.assertEqual(row['criterion_status'],'unknown')
        self.assertIn('하루 총량용',row['criterion_note'])
        self.assertEqual(self.compare(products,age='18')['criterion_status'],'unknown')
    def test_product_rule_preferred_without_conflict(self):
        row=self.compare([self.product('202106092',500,8)])
        self.assertEqual(row['criterion_status'],'not_exceeded')
        self.assertEqual(row['criterion_scope'],'product')
    def test_unit_and_measurement_not_mixed(self):
        p=self.product('197900277',300,3);p['ingredients'][0]['measurement_basis']='potency'
        self.assertEqual(self.compare([p])['criterion_status'],'unknown')
