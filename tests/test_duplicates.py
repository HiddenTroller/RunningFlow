import unittest
from unittest.mock import patch
from duplicates import compare_duplicates
from main import dispatch_post

class DuplicateOnlyTests(unittest.TestCase):
    def test_no_quantity_required_and_one_product_not_duplicate(self):
        p={'code':'1','name':'A','ingredients':[{'name':'성분','ingredient_code':'M1'},{'name':'성분','ingredient_code':'M1'}]}
        report=compare_duplicates([p])
        self.assertEqual(report['duplicate_count'],0)
        self.assertNotIn('total_mg',report['ingredients'][0])
    def test_codes_and_missing_code_names(self):
        report=compare_duplicates([
            {'code':'1','name':'A','ingredients':[{'name':'성분A','ingredient_code':'M1'},{'name':'성분 B'}]},
            {'code':'2','name':'B','ingredients':[{'name':'다른표기','ingredient_code':'M1'},{'name':'성분B'}]}])
        self.assertEqual(report['duplicate_count'],2)
class ProductSummaryTests(unittest.TestCase):
    def test_explicit_daily_max_only(self):
        from duplicates import product_summary
        p={'code':'123','name':'약','directions_text':'성인 1회 1정, 1일 3회.','warning_text':'함께 복용하지 마세요.'}
        self.assertEqual(product_summary(p)['daily_max_text'],'')
        p['directions_text']='성인 1회 1정.\n1일 최대 8정을 초과하지 않는다.'
        result=product_summary(p)
        self.assertIn('8정',result['daily_max_text'])
        self.assertIn('함께',result['warnings_text'])

class OfficialTitleDoseTests(unittest.TestCase):
    def test_directions_do_not_become_maximum(self):
        from duplicates import product_summary
        result=product_summary({'code':'1','directions_text':'성인 1회 1캡슐을 1일 3회 식후에 복용한다.'})
        self.assertEqual(result['daily_max_text'],'')
        self.assertIn('1일 3회',result['daily_directions_text'])
        self.assertEqual(result['daily_max_status'],'directions_only')

class IdentityOnlyTests(unittest.TestCase):
    def test_unknown_strength_keeps_identity(self):
        from duplicates import identity_only_product
        p=identity_only_product({'detail':{'product':{'ITEM_SEQ':'1','ITEM_NAME':'약'},'ingredients_raw':[{'MTRAL_NM':'성분A','MTRAL_CODE':'M1','QNT':None}],'warnings':[]}})
        self.assertEqual(p['ingredients'],[{'name':'성분A','ingredient_code':'M1'}])
        self.assertTrue(p['amount_unconfirmed'])
        self.assertNotIn('amount',p['ingredients'][0])
    def test_material_name_without_dose(self):
        from duplicates import identity_only_product
        p=identity_only_product({'detail':{'product':{'ITEM_SEQ':'1','ITEM_NAME':'약','MATERIAL_NAME':'총량:1정|성분명:성분A|분량:미상;성분명:성분B|단위:기타'},'ingredients_raw':[],'warnings':[]}})
        self.assertEqual([i['name'] for i in p['ingredients']],['성분A','성분B'])
    def test_missing_identity_reported(self):
        r=compare_duplicates([{'code':'1','name':'미확인','ingredients':[]}])
        self.assertEqual(len(r['unconfirmed_products']),1)
        self.assertEqual(r['product_count'],1)
