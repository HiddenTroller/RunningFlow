"""의약품안전나라 품목별 원료약품 표 조회. 고정 공식 도메인·전체 성분 대조."""
import copy
import hashlib
import re
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from mfds_client import ServiceError
from matcher import parse_strength, parse_basis, text
from normalization import normalize_name

BASE = 'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq='
CACHE = {}
LOCK = threading.Lock()


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p=urlsplit(newurl)
        if p.scheme != 'https' or p.hostname != 'nedrug.mfds.go.kr' or p.port not in (None,443):
            raise ServiceError('공식 출처 외부로 이동하여 자동 확인을 중단했습니다.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_official(code):
    if not isinstance(code,str) or not code.isdigit() or len(code)>20:
        raise ServiceError('공식 품목코드를 확인하세요.')
    with LOCK:
        cached=CACHE.get(code)
        if cached and time.monotonic()-cached[0]<900: return copy.deepcopy(cached[1])
    url=BASE+code
    try:
        with build_opener(OfficialRedirect()).open(Request(url,headers={'User-Agent':'Learningflow/1.0','Accept':'text/html'}),timeout=15) as response:
            raw=response.read(3*1024*1024+1)
            if len(raw)>3*1024*1024: raise ServiceError('공식 페이지 크기를 초과했습니다.')
            if urlsplit(response.url).hostname != 'nedrug.mfds.go.kr': raise ServiceError('공식 출처 미확인')
            result={'html':raw.decode('utf-8'),'url':url,'retrieved_url':response.url,
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(raw).hexdigest()}
    except ServiceError: raise
    except Exception:
        raise ServiceError('의약품안전나라 공식 페이지를 읽지 못했습니다. 직접 확인이 필요합니다.') from None
    with LOCK:
        if len(CACHE)>=100: CACHE.pop(next(iter(CACHE)))
        CACHE[code]=(time.monotonic(),result)
    return result


class MaterialPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignore=0;self.heading=None;self.heading_parts=[];self.last_heading=''
        self.table=None;self.row=None;self.cell=None;self.tables=[];self.stack=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.ignore+=1
        if self.ignore:return
        if tag in ('h2','h3'):self.heading=tag;self.heading_parts=[]
        if tag=='table':
            self.stack.append((self.table,self.row,self.cell))
            self.table={'heading':self.last_heading,'rows':[]}
            self.row=None;self.cell=None
        if tag=='tr' and self.table is not None:self.row=[]
        if tag in ('th','td') and self.row is not None:
            if any(k in ('colspan','rowspan') and v not in ('1',None) for k,v in attrs):
                self.table['spanned']=True
            self.cell=[]
    def handle_data(self,data):
        if self.ignore:return
        if self.heading:self.heading_parts.append(data)
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            self.ignore=max(0,self.ignore-1);return
        if self.ignore:return
        if tag==self.heading:
            self.last_heading=' '.join(''.join(self.heading_parts).split());self.heading=None
        if tag in ('th','td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:
            self.table['rows'].append(self.row);self.row=None
        if tag=='table' and self.table is not None:
            self.tables.append(self.table)
            self.table,self.row,self.cell=self.stack.pop()


def resolve_official(detail, fetcher=None):
    """proposal은 확인용입니다. 충돌값은 자동 사용하지 않습니다."""
    product=detail['product'];code=str(product.get('ITEM_SEQ',''))
    result={'status':'review','notes':[],'proposal':None,'source_url':BASE+code}
    try:
        page=(fetcher or fetch_official)(code)
        parser=MaterialPage();parser.feed(page['html']);parser.close()
        identity={}
        for table in parser.tables:
            for row in table['rows']:
                if len(row)==2 and row[0] in ('제품명','업체명','품목기준코드'):
                    if row[0] in identity and identity[row[0]]!=row[1]: raise ServiceError('공식 페이지의 품목 식별정보 충돌')
                    identity[row[0]]=row[1]
        if identity.get('품목기준코드')!=code or normalize_name(identity.get('제품명'))!=normalize_name(product.get('ITEM_NAME')) or not normalize_name(product.get('ENTP_NAME')) or normalize_name(identity.get('업체명'))!=normalize_name(product.get('ENTP_NAME')):
            raise ServiceError('공식 페이지와 API의 품목코드·제품명·업체명이 일치하지 않습니다.')
        materials=[t for t in parser.tables if t['rows'] and all(h in t['rows'][0] for h in ('성분명','분량','단위'))]
        if not materials or len(materials)>20: raise ServiceError('공식 성분 표를 찾지 못했습니다.')
        # Domestic/export presentations may repeat the exact same full formula.
        # Collapse only explicitly labelled variants with identical rows AND basis.
        identical_markets = False
        if len(materials) > 1 and all(re.search(r'\[(?:내수용|수출용)\]', t['heading']) for t in materials):
            first = materials[0]
            first_basis = parse_basis(first['heading'])
            if first_basis[0] is not None and all(t['rows'] == first['rows'] and
                    parse_basis(t['heading']) == first_basis and not t.get('spanned') for t in materials):
                materials = [first]
                identical_markets = True
        original=detail.get('ingredients_raw',[])
        if identical_markets and original:
            domestic=[r for r in original if text(r.get('CPNT_CTNT_CONT'))=='[내수용]']
            export=[r for r in original if text(r.get('CPNT_CTNT_CONT'))=='[수출용]']
            def formula(rows):
                return sorted(tuple(text(r.get(k)) for k in ('MTRAL_NM','MTRAL_CODE','QNT','INGD_UNIT_CD')) for r in rows)
            if domestic and export and len(domestic)+len(export)==len(original) and formula(domestic)==formula(export):
                original=domestic
        names={normalize_name(r.get('MTRAL_NM')) for r in original if text(r.get('MTRAL_NM'))}
        # 주성분 목록 자체가 없으면 원료 표의 완전성을 대조할 수 없습니다.
        if not names: raise ServiceError('공식 API 주성분 목록이 없어 전체 성분을 대조할 수 없습니다.')
        groups={};basis=None;layer_labels=set();evidence=[]
        for table in materials:
            heading=table['heading']
            current=parse_basis(heading)
            if current[0] is not None:
                if basis and basis!=current: raise ServiceError('성분 표에 서로 다른 함량 기준이 있습니다.')
                basis=current
            elif not (basis and re.fullmatch(r'-\s*[가-힣]+층',heading)):
                raise ServiceError('성분 표의 함량 기준을 확인하지 못했습니다.')
            layer=re.search(r'([가-힣]+층)\s*$',heading)
            label=layer.group(1) if layer else ''
            if label in layer_labels or (not label and len(materials)>1): raise ServiceError('층별 표가 중복되거나 구분되지 않습니다.')
            layer_labels.add(label)
            if table.get('spanned'): raise ServiceError('병합 셀이 있는 성분 표는 직접 확인이 필요합니다.')
            header=table['rows'][0];seen=set()
            for cells in table['rows'][1:]:
                if len(cells)!=len(header): raise ServiceError('성분 표의 일부 행을 읽지 못했습니다.')
                row=dict(zip(header,cells));name=row['성분명'];key=normalize_name(name)
                equivalence = row.get('성분정보','')
                remark = row.get('비교','') or row.get('비고','')
                if remark not in ('','역가'):
                    raise ServiceError('해석되지 않은 성분 비고가 있습니다: '+remark)
                if equivalence and not re.fullmatch(r'.+?(?:\(으\)로서|으로서|로서)\s*[0-9]+(?:\.[0-9]+)?\s*(?:밀리그램|마이크로그램|그램|mg|g|μg|아이\.유|IU|국제단위)', equivalence, re.I):
                    raise ServiceError('환산 성분 표현을 정확히 읽지 못했습니다: '+equivalence)
                measurement_basis = 'potency' if remark == '역가' else 'mass'

                if not key or key in seen: raise ServiceError('성분 표의 중복 행 확인 필요')
                seen.add(key)
                strength=parse_strength(row['분량']+row['단위'])
                if strength['status'] != '확인됨': raise ServiceError('공식 표에 지원되지 않는 함량 단위가 있습니다.')
                amount = strength['mg'] if strength['mg'] is not None else strength['amount']
                unit = 'mg' if strength['mg'] is not None else strength['unit']
                matches=[r for r in original if normalize_name(r.get('MTRAL_NM'))==key]
                codes={text(r.get('MTRAL_CODE')) for r in matches}-{''}
                if not matches or len(codes)!=1: raise ServiceError('공식 성분명·코드를 정확히 대조하지 못했습니다.')
                group=groups.setdefault(key,{'name':name,'ingredient_code':next(iter(codes)),'amount':Decimal('0'),'unit':unit,'measurement_basis':measurement_basis,'equivalence':equivalence,'basis_quantity':basis[0],'basis_unit':basis[1],'layers':{}})
                if group['unit'] != unit or group['measurement_basis'] != measurement_basis or group['equivalence'] != equivalence:
                    raise ServiceError('층별 성분의 측정 기준 또는 환산 정보가 다릅니다.')
                group['amount']+=Decimal(amount);group['layers'][label]=amount
                evidence.append(heading+' | '+name+' | '+row['분량']+' '+row['단위'])
        if set(groups)!=names: raise ServiceError('공식 페이지와 API의 전체 유효성분 목록이 다릅니다.')
        conflicts=[]
        api_basis=parse_basis(product.get('TOTAL_CONTENT'))
        if api_basis[0] is not None and api_basis!=basis:conflicts.append('공식 페이지와 API의 제품 함량 기준 충돌')
        for key,group in groups.items():
            rows=[r for r in original if normalize_name(r.get('MTRAL_NM'))==key]
            labels=set()
            for row in rows:
                layer_match=re.search(r'([가-힣]+층)',text(row.get('CPNT_CTNT_CONT')))
                label=layer_match.group(1) if layer_match else ''
                if label in labels: conflicts.append('API 동일 성분·층이 중복됨')
                labels.add(label)
                raw_amount=row.get('QNT')
                if raw_amount not in (None,''):
                    strength=parse_strength(str(raw_amount)+text(row.get('INGD_UNIT_CD')))
                    expected=group['layers'].get(label) if label else str(group['amount'])
                    api_amount = strength['mg'] if strength['mg'] is not None else strength['amount']
                    api_unit = 'mg' if strength['mg'] is not None else strength['unit']
                    if expected is None or api_amount is None or api_unit != group['unit'] or Decimal(api_amount)!=Decimal(expected):
                        conflicts.append(group['name']+': 공식 페이지와 API 함량 충돌')
                row_basis=parse_basis(row.get('CPNT_CTNT_CONT'))
                if row_basis[0] is not None and row_basis!=(group['basis_quantity'],group['basis_unit']):conflicts.append('API 함량 기준 충돌')
        for group in groups.values():group['amount']=str(group['amount'])
        result.update(proposal=[{k:v for k,v in g.items() if k!='layers'} for g in groups.values()],
                      source_evidence='\n'.join(evidence),retrieved_at=page.get('retrieved_at'),sha256=page.get('sha256'),
                      api_differences=list(dict.fromkeys(conflicts)),
                      selection_policy='official_page_priority',
                      notes=[])
        # The validated page's full formula and explicit denominator take priority
        # over conflicting API quantity/layer fields. Identity, ingredient coverage,
        # table ambiguity and code checks above are never bypassed.
        if detail.get('warnings'):result['notes'].extend(detail['warnings'])
        if not result['notes']:
            result['status']='matched'
            if conflicts:result['notes'].append('공식 성분표 우선 적용. API 차이는 api_differences에 보존했습니다.')
        return result
    except ServiceError as error:
        result['notes'].append(str(error));return result
    except (ValueError,KeyError,TypeError):
        result['notes'].append('공식 페이지 구조를 정확히 해석하지 못했습니다.');return result


def apply_resolution(detail, resolution):
    if resolution.get('status')!='matched':return detail
    result=copy.deepcopy(detail);result['original_official']=copy.deepcopy(detail)
    result['automatic_resolution']=resolution
    result['product']['TOTAL_CONTENT']=''
    result['ingredients_raw']=[{'MTRAL_NM':r['name'],'MTRAL_CODE':r['ingredient_code'],'QNT':r['amount'],'INGD_UNIT_CD':r['unit'],'MEASUREMENT_BASIS':r.get('measurement_basis','mass'),'EQUIVALENCE':r.get('equivalence',''),
       'CPNT_CTNT_CONT':r['basis_quantity']+r['basis_unit']+' 중','OFFICIAL_PAGE_EVIDENCE':resolution['source_evidence'],
       'SOURCE_URL':resolution['source_url']} for r in resolution['proposal']]
    result['source']=resolution['source_url'];result['warnings']=[]
    return result
