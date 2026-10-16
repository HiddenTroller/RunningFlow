"""Strict official label quantity comparison; never estimates a safe dose."""
from decimal import Decimal
import re
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from official_text import dosage_text

D=r'(\d+(?:\.\d+)?)(?:\s*[~～∼−–-]\s*(\d+(?:\.\d+)?))?'

class DoseTables(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.tables=[];self.rows=None;self.row=None;self.cell=None;self.ambiguous=False
    def handle_starttag(self,tag,attrs):
        if tag in ('td','th') and any(k in ('colspan','rowspan') and v not in ('1',None) for k,v in attrs):self.ambiguous=True
        if tag in ('tbody','table') and self.rows is None:self.rows=[]
        if tag=='tr' and self.rows is not None:self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
        if tag in ('p','br') and self.cell is not None:self.cell.append(' ')
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None
        if tag in ('tbody','table') and self.rows is not None:self.tables.append(self.rows);self.rows=None

def _native_amount(value,unit):
    units={'mL':r'ml|밀리리터','g':r'g|그램'}.get(unit,re.escape(unit))
    found=list(re.finditer(D+r'\s*(?:'+units+r')(?=$|[\s),.;]|을|를|씩|까지|이하|초과|미만|이상)',value,re.I))
    amounts={Decimal(m[2] or m[1]) for m in found}
    return next(iter(amounts)) if len(amounts)==1 else None

def _table_amount(raw,profile,unit,mode):
    try:
        root=ET.fromstring(raw)
        html=''.join(''.join(p.itertext()) for p in root.iter('PARAGRAPH') if p.attrib.get('tagName')=='table')
    except (ET.ParseError,TypeError):html=raw or ''
    parser=DoseTables();parser.feed(html);parser.close()
    if parser.ambiguous:return []
    age=Decimal(profile['age_years']); matches=[]
    for table in parser.tables:
        if not table:continue
        header=[re.sub(r'\s+','',h) for h in table[0]]
        if not header or header[0]!='연령':continue
        columns=[i for i,h in enumerate(header) if ('1일최대' in h if mode=='day' else '1회' in h)]
        for row in table[1:]:
            if len(row)!=len(header) or '개월' in row[0]:continue
            label=re.sub(r'\s+|만','',row[0])
            bracket=re.fullmatch(r'(\d+)(?:세)?[~～∼-](\d+)세',label)
            exact=re.fullmatch(r'(\d+)세',label)
            eligible=(Decimal(bracket[1])<=age<Decimal(bracket[2])+1) if bracket else (Decimal(exact[1])<=age<Decimal(exact[1])+1) if exact else False
            if not eligible:continue
            if '몸무게' in header:
                if not profile.get('weight_kg'):continue
                weight=Decimal(profile['weight_kg']);value=row[header.index('몸무게')]
                band=re.fullmatch(r'\s*'+D+r'\s*kg\s*(이상)?\s*',value,re.I)
                if not band:continue
                lo=Decimal(band[1]);hi=Decimal(band[2]) if band[2] else None
                if not (weight>=lo and (weight<=hi if hi is not None else bool(band[3]))):continue
            values=[_native_amount(row[i],unit) for i in columns]
            values={v for v in values if v is not None}
            if len(values)==1:matches.append((next(iter(values)),' | '.join(row)))
    return matches


def compare_label(product,profile,mode):
    raw=product.get('directions_text','')
    source=unicodedata.normalize('NFKC',dosage_text(raw))
    result={'product_name':product.get('name',''),'product_code':product.get('code',''),
            'quantity':str(product.get('quantity','0')),'unit':product.get('quantity_unit',''),
            'mode':mode,'status':'unknown','limit_quantity':None,'excess_quantity':None,
            'source_text':source,'source_url':'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq='+str(product.get('code','')) if str(product.get('code','')).isdigit() else ''}
    def unknown(reason):result['note']=reason;return result
    if not source:return unknown('공식 용법 원문이 없습니다.')
    if not profile.get('age_years'):return unknown('만 나이가 없어 용법의 연령 조건을 확인하지 못했습니다.')
    age=Decimal(profile['age_years'])
    contraindication=re.search(r'(\d+)\s*세\s*미만[^.\n]{0,45}(?:복용하지|투여하지)',source)
    if contraindication and age<Decimal(contraindication[1]):
        result.update(status='age_restricted',note='공식 용법에 명시된 복용 금지 연령에 해당합니다.');return result
    table_matches=_table_amount(raw,profile,product.get('quantity_unit',''),mode)
    if len(table_matches)==1:
        upper,evidence=table_matches[0];actual=Decimal(result['quantity'])
        result.update(status='exceeded' if actual>upper else 'not_exceeded',limit_quantity=format(upper.normalize(),'f'),
                      excess_quantity=str(max(Decimal('0'),actual-upper)),criterion_kind='age_table',matched_evidence=evidence,
                      note='공식 연령·체중 표의 해당 행을 비교했습니다. 복용 간격과 다른 약의 안전성을 평가한 결과는 아닙니다.')
        return result
    if len(table_matches)>1:return unknown('적용되는 연령·체중 표가 여러 개여서 자동 선택하지 않았습니다.')
    lower=re.search(r'(?:만\s*)?(\d+)\s*세\s*이상',source)
    # Only the single-dose adult regimen is automated. 19+ is a conservative
    # service coverage restriction, not a universal medical definition of adult.
    if lower:
        if age<Decimal(lower[1]):return unknown('공식 용법의 적용 시작 나이보다 어립니다.')
        if re.search(r'세\s*이하|세\s*미만|개월',source):return unknown('다른 연령별 조건이 함께 있어 자동 해석하지 않습니다.')
    elif '성인' in source:
        if age<19:return unknown('성인 표시 용법만 있습니다. 자동 비교는 서비스 범위상 만 19세 이상에 한정합니다.')
    else:return unknown('적용 연령 조건을 명확히 확인하지 못했습니다.')
    doses=list(re.finditer(r'1\s*회\s*'+D+r'\s*(정|캡슐|포|mL|ml|밀리그램|mg|마이크로그램|μg|그램|g|매|개)',source,re.I))
    frequencies=list(re.finditer(r'1\s*일\s*'+D+r'\s*회',source))
    if not doses:
        doses=list(re.finditer(r'매\s*\d+(?:\.\d+)?\s*시간\s*마다\s*'+D+r'\s*(정|캡슐|포|mL|ml|밀리그램|mg|마이크로그램|μg|그램|g|매|개)',source,re.I))
    if len(doses)!=1:return unknown('1회 수량 또는 시간 간격형 용법을 명확히 읽지 못했습니다. 복수 용법·미지원 표는 자동 선택하지 않습니다.')
    dose=doses[0];unit=dose[3];unit='mL' if unit.lower()=='ml' else 'g' if unit=='그램' else unit
    upper=Decimal(dose[2] or dose[1]);kind='label_upper'
    factor=None
    if unit!=product.get('quantity_unit'):
        mass={'mg':Decimal('1'),'밀리그램':Decimal('1'),'g':Decimal('1000'),'μg':Decimal('0.001'),'마이크로그램':Decimal('0.001')}
        ingredients=product.get('ingredients',[])
        if unit not in mass or len(ingredients)!=1:return unknown('용법과 입력 단위가 다르고 단일 성분 질량으로 환산할 근거가 없습니다.')
        ingredient=ingredients[0]
        if ingredient.get('unit')!='mg' or ingredient.get('measurement_basis','mass')!='mass' or ingredient.get('equivalence') or ingredient.get('basis_unit')!=product.get('quantity_unit'):
            return unknown('역가·환산 성분·기준 단위 차이 때문에 수량을 자동 환산하지 않았습니다.')
        amount=Decimal(str(ingredient['amount']));basis=Decimal(str(ingredient['basis_quantity']))
        if amount<=0 or basis<=0:return unknown('공식 1단위당 질량을 확인하지 못했습니다.')
        factor=mass[unit]*basis/amount
        upper*=factor
        kind='official_mass_conversion'

    if mode=='day':
        explicit=[]
        for line in source.split('\n'):
            if not re.search(r'(?:1\s*일|하루|24\s*시간)',line):continue
            if not re.search(r'최대|최고|초과하지',line):continue
            starts=list(re.finditer(r'(?:1\s*일|하루|24\s*시간)',line))
            segment=line[starts[-1].start():] if starts else line
            amount=_native_amount(segment,product.get('quantity_unit'))
            if amount is None and factor is not None:
                value=_native_amount(segment,unit)
                amount=value*factor if value is not None else None
            if amount is not None:explicit.append(amount)
        if len(set(explicit))==1:
            upper=explicit[0];kind='explicit_maximum'
        elif explicit:return unknown('서로 다른 하루 최대량이 여러 개 있어 자동 적용하지 않았습니다.')
        elif len(frequencies)==1:
            freq=frequencies[0];upper*=Decimal(freq[2] or freq[1])
        else:return unknown('하루 횟수 또는 24시간 최대 수량을 명확히 확인하지 못했습니다.')
    if upper<=0:return unknown('용법 수량을 확인하지 못했습니다.')
    actual=Decimal(result['quantity'])
    result.update(status='exceeded' if actual>upper else 'not_exceeded',limit_quantity=format(upper.normalize(),'f'),
                  excess_quantity=str(max(Decimal('0'),actual-upper)),criterion_kind=kind,
                  note='공식 표시 용법의 수량 상한 비교입니다. 다른 약과의 합산 안전 최대량 또는 복용 허가가 아닙니다.')
    return result
