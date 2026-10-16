import unittest
from calculator import calculate
from official_text import dosage_text
from mfds_client import ServiceError

class DoseResultTests(unittest.TestCase):
    def product(self,amount):
        return dict(name='가상약',code='123',confirmed=True,quantity='1',quantity_unit='정',directions_text='<DOC><PARAGRAPH><![CDATA[<p>공식 용법 1정</p><table><tr><td>연령</td><td>용량</td></tr></table>]]></PARAGRAPH></DOC>',ingredients=[dict(name='가상성분',ingredient_code='X',amount=amount,unit='mg',basis_quantity='1',basis_unit='정',evidence='test')])
    def rule(self):
        return dict(id='test',reviewed=True,reviewer='test',reviewed_at='test',source_url='https://example.test',ingredient_code='X',mode='day',population='adult',product_codes=['123'],limit_mg='400')
    def test_exact_excess_and_official_directions(self):
        r=calculate([self.product('450.125')],'day',[self.rule()],quantity_intent='taken')
        self.assertEqual(r['ingredients'][0]['excess_mg'],'50.125')
        self.assertEqual(r['quantity_intent'],'taken')
        self.assertEqual(float(r['intake_reference']['percent']),112.53125)
        self.assertEqual(r['intake_reference']['ingredient'],'가상성분')
        self.assertIn('공식 용법 1정',r['official_directions'][0]['text'])
        self.assertIn('연령 | 용량',r['official_directions'][0]['text'])
        self.assertNotIn('<DOC>',r['official_directions'][0]['text'])
    def test_no_negative_or_unknown_excess(self):
        self.assertEqual(calculate([self.product('300')],'day',[self.rule()])['ingredients'][0]['excess_mg'],'0')
        self.assertIsNone(calculate([self.product('300')])['ingredients'][0]['excess_mg'])
    def test_invalid_intent(self):
        with self.assertRaises(ServiceError):calculate([self.product('300')],quantity_intent='other')
    def test_script_removed_and_missing_text(self):
        self.assertEqual(dosage_text(None),'')
        self.assertNotIn('alert',dosage_text('<p>원문</p><script>alert(1)</script>'))

    def test_unknown_not_zero_percent_and_planned_no_bar(self):
        r=calculate([self.product('300')],quantity_intent='taken')
        self.assertIsNone(r['intake_reference']['percent'])
        self.assertEqual(r['intake_reference']['unknown_count'],1)
        self.assertIsNone(calculate([self.product('300')],quantity_intent='planned')['intake_reference'])
