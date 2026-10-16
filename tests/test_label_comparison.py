import unittest
from label_comparison import compare_label

class LabelTests(unittest.TestCase):
    def check(self,text,quantity,mode='single',age='30',unit='정'):
        return compare_label({'name':'검사제품','code':'123','quantity':str(quantity),'quantity_unit':unit,'directions_text':text},{'age_years':age},mode)
    def test_geb(self):
        text='성인 1회 1정 1일 3회까지 복용한다. 복용간격은 4시간 이상. 15세 미만의 소아는 이 약을 복용하지 않는다.'
        self.assertEqual(self.check(text,2)['status'],'exceeded')
        self.assertEqual(self.check(text,3,'day')['limit_quantity'],'3')
        self.assertEqual(self.check(text,1,age='14')['status'],'age_restricted')
        self.assertEqual(self.check(text,1,age='16')['status'],'unknown')
    def test_liquid_and_capsule(self):
        self.assertEqual(self.check('성인 1회 30ml 1일 3회 식후 복용',100,'day',unit='mL')['excess_quantity'],'10')
        self.assertEqual(self.check('성인 1회 1캡슐을 1일 3회 식후 복용',1,unit='캡슐')['limit_quantity'],'1')
    def test_explicit_age_and_max(self):
        text='만 12세 이상 소아 및 성인: 1회 1~2정씩 1일 3-4회 복용. 1일 최대 4그램 (8정)을 초과하여 복용하지 않는다.'
        self.assertEqual(self.check(text,3,age='12')['limit_quantity'],'2')
        self.assertEqual(self.check(text,9,'day',age='12')['excess_quantity'],'1')
        self.assertEqual(self.check(text,1,age='11')['status'],'unknown')
    def test_ambiguous_or_unit_mismatch_stays_unknown(self):
        for text in ('1회 1정 1일 3회','성인 1회 1정 1일 3회. 다른 질환은 1회 2정 1일 4회.'):
            self.assertEqual(self.check(text,2)['status'],'unknown')
        self.assertEqual(self.check('성인 1회 30ml 1일 3회',1,unit='정')['status'],'unknown')

    def test_er_interval_and_24_hour_ceiling(self):
        text='12세 이상의 소아 및 성인: 매 8시간마다 2정씩 복용\n24시간 동안 6정을 초과하지 말 것'
        single=self.check(text,4,age='30')
        daily=self.check(text,4,'day',age='30')
        self.assertEqual(single['status'],'exceeded')
        self.assertEqual(single['limit_quantity'],'2')
        self.assertEqual(daily['status'],'not_exceeded')
        self.assertEqual(daily['limit_quantity'],'6')
        self.assertEqual(daily['criterion_kind'],'explicit_maximum')
        self.assertEqual(self.check(text,7,'day')['excess_quantity'],'1')
        self.assertEqual(self.check(text.replace('\n',' '),7,'day')['limit_quantity'],'6')
    def test_age_table_exact_row(self):
        text='<DOC><PARAGRAPH tagName="table"><![CDATA[<table><tr><th>연령</th><th>1회 용량</th><th>1일 최대용량</th></tr><tr><td>7~10세</td><td>150~200mg (7.5~10mL)</td><td>800mg (40mL)</td></tr><tr><td>11~14세</td><td>200~250mg (10~12.5mL)</td><td>1000mg (50mL)</td></tr></table>]]></PARAGRAPH></DOC>'
        self.assertEqual(self.check(text,11,age='10',unit='mL')['limit_quantity'],'10')
        self.assertEqual(self.check(text,51,'day',age='11',unit='mL')['limit_quantity'],'50')
        self.assertEqual(self.check(text,10,age='15',unit='mL')['status'],'unknown')
        self.assertEqual(self.check(text.replace('<td>7~10세','<td colspan="2">7~10세'),10,age='10',unit='mL')['status'],'unknown')

    def test_single_ingredient_mass_conversion_not_compound_guess(self):
        p={'name':'검사제품','code':'123','quantity':'3','quantity_unit':'정','directions_text':'만 12세 이상: 1회 500~1000mg 1일 3회',
           'ingredients':[{'amount':'500','unit':'mg','basis_quantity':'1','basis_unit':'정'}]}
        self.assertEqual(compare_label(p,{'age_years':'30'},'single')['limit_quantity'],'2')
        self.assertEqual(compare_label(p,{'age_years':'30'},'day')['limit_quantity'],'6')
        p['ingredients'][0]['measurement_basis']='potency'
        self.assertEqual(compare_label(p,{'age_years':'30'},'single')['status'],'unknown')
        p['ingredients'].append(dict(p['ingredients'][0]))
        self.assertEqual(compare_label(p,{'age_years':'30'},'single')['status'],'unknown')
