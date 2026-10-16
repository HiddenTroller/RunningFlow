"""대조·후보 정렬·명시적 확인과 공식 데이터 계산 경계를 담당합니다."""
import copy
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from matcher import compare_ingredients, manufacturer_matches, official_calculation_product, text
from mfds_client import MFDSClient, ServiceError
from studio_client import analyze_photo, product_names_from_final
from calculator import calculate
from supplemental_client import SupplementalClient
from extraction_adapter import normalize_extraction
from product_overrides import apply_override, save_override
from official_lookup import resolve_official, apply_resolution
from name_search import similar_search


class AnalysisWorkflow:
    def __init__(self, client=None, analyzer=None):
        self.client = client or MFDSClient()
        self.analyzer = analyzer or analyze_photo
        self.records = {}
        self.lock = threading.Lock()
        self.detail_cache = {}

    def _put(self, kind, value):
        with self.lock:
            now = time.monotonic()
            self.records = {k: v for k, v in self.records.items() if now - v[0] < 1800}
            if len(self.records) >= 300:
                oldest = min(self.records, key=lambda k: self.records[k][0])
                del self.records[oldest]
            token = secrets.token_urlsafe(24)
            self.records[token] = (now, kind, copy.deepcopy(value))
            return token

    def _get(self, token, kind):
        if not isinstance(token, str):
            raise ServiceError('확인 정보가 없습니다. 후보를 다시 조회하세요.')
        with self.lock:
            record = self.records.get(token)
            if not record or record[1] != kind or time.monotonic() - record[0] >= 1800:
                raise ServiceError('확인 정보가 만료되었습니다. 후보를 다시 조회하세요.')
            return copy.deepcopy(record[2])

    def analyze_and_match(self, content, mime):
        studio = self.analyzer(content, mime)
        names = product_names_from_final(studio.get('final_text', ''))
        if names is not None:
            def match_product(entry):
                index,name=entry
                # Never share a mixed-photo ingredient record between products.
                try:
                    result=self.match_extracted({},name='' if name=='확인필요' else name)
                except ServiceError as error:
                    result={'candidates':[],'total':0,'photo_extracted':{},'reason':str(error)}
                result.update(product_index=index,search_name=name)
                return result
            # Bounded concurrency keeps product states separate and respects API load.
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(match_product,enumerate(names,1)))
            return {'multi_product':True,'products':results,'studio':studio,
                    'photo_extracted':{},'candidates':[], 'total':len(results),
                    'reason':'' if results else '사진에서 식별 가능한 약품을 찾지 못했습니다.'}
        extracted = studio.get('extracted')
        extracted = extracted if isinstance(extracted, dict) else {}
        search_name = studio.get('search_product_name')
        result = self.match_extracted(extracted, name=search_name if isinstance(search_name, str) else '')
        result['search_name'] = search_name if isinstance(search_name, str) else ''
        if not result['search_name']:
            result['reason'] = 'Instruct 최종 결과에서 단일 검색용 제품명을 확인하지 못했습니다. Extract 제품명으로 대체하지 않았습니다. 직접 검색하세요.'
        result['studio'] = studio
        return result

    def cached_search_detail(self, code):
        """Reuse only complete successful official details, at most 5 minutes."""
        with self.lock:
            cached=self.detail_cache.get(code)
            if cached and time.monotonic()-cached[0]<300:
                return copy.deepcopy(cached[1])
        detail=self.client.detail(code)
        if detail.get('ingredients_raw') and not detail.get('warnings'):
            with self.lock:
                now=time.monotonic()
                self.detail_cache={k:v for k,v in self.detail_cache.items() if now-v[0]<300}
                if len(self.detail_cache)>=100:self.detail_cache.pop(next(iter(self.detail_cache)))
                self.detail_cache[code]=(now,copy.deepcopy(detail))
        return detail

    def match_extracted(self, extracted, name=None, page=1):
        extracted, extraction_warnings = normalize_extraction(extracted)
        photo_id = self._put('photo', extracted)
        name = text(name) if name is not None else text(extracted.get('product_name_raw'))
        if not name:
            return {'status': '제품을 찾지 못함', 'reason': '사진의 제품명이 미확인입니다. 직접 검색하세요.',
                    'photo_extracted': extracted, 'photo_id': photo_id, 'candidates': [], 'total': 0,
                    'warnings': extraction_warnings}
        try:
            found = self.client.search(name, page, page_size=10)
        except ServiceError as error:
            return {'status': '확인 필요', 'reason': str(error), 'photo_extracted': extracted,
                    'photo_id': photo_id, 'candidates': [], 'total': 0, 'warnings': extraction_warnings}
        search_mode = 'exact'
        if not found['items'] and page == 1:
            fallback = similar_search(self.client,name)
            if fallback['items']:
                found = fallback
                search_mode = 'similar'
        candidates, warnings = [], list(extraction_warnings)
        if search_mode == 'similar':
            warnings.append('정확한 검색 결과가 없어 비슷한 이름의 제품을 표시합니다. 사진의 제품명·제형·함량·제조사를 확인하고 직접 선택하세요.')
            if found.get('truncated'): warnings.append('유사 검색 결과의 일부만 표시했습니다.')
        # 후보별 상세 호출 폭증을 막고, 일부만 평가되면 명확히 알립니다.
        limit = 10
        seen = set()
        for item in found['items'][:limit]:
            code = str(item.get('ITEM_SEQ', ''))
            if not code or code in seen:
                continue
            seen.add(code)
            try:
                detail = apply_override(self.cached_search_detail(code))
                comparison = compare_ingredients(extracted, detail)
            except ServiceError:
                detail = {'product': item, 'ingredients_raw': [], 'warnings': ['공식 상세 조회 실패. 확인 필요.'],
                          'source': found.get('source', '')}
                comparison = compare_ingredients(extracted, detail)
            if extraction_warnings:
                comparison['warnings'].extend(extraction_warnings)
                comparison['status'] = '확인 필요'
                comparison['all_match'] = False
            manufacturer_match = manufacturer_matches(extracted.get('manufacturer'), detail['product'].get('ENTP_NAME'))
            record = {'detail': detail, 'comparison': comparison, 'extracted': extracted}
            candidate_id = self._put('candidate', record)
            candidates.append({'candidate_id': candidate_id, 'product': detail['product'],
                               'manufacturer_match': manufacturer_match,
                               'comparison': comparison, 'source': detail.get('source', ''),
                               'search_mode':search_mode,'name_similarity':found.get('similarity',{}).get(code)})
        candidates.sort(key=lambda c: (not c['manufacturer_match'], not c['comparison']['all_match'],
                                       str(c['product'].get('ITEM_SEQ', ''))))
        if search_mode == 'similar':
            candidates.sort(key=lambda c: (not c['manufacturer_match'], -(c.get('name_similarity') or 0), not c['comparison']['all_match']))
        if found['total'] > len(candidates):
            warnings.append('이번 페이지의 최대 10개 후보를 대조했습니다. 다른 후보는 제품명을 좁혀 검색하거나 다음 페이지에서 확인하세요.')
        return {'status': '후보 확인 필요' if candidates else '제품을 찾지 못함',
                'reason': '' if candidates else '해당 제품명으로 공식 제품을 찾지 못했습니다. 직접 검색하세요.',
                'photo_extracted': extracted, 'photo_id': photo_id, 'candidates': candidates,
                'total': found['total'], 'page': page, 'warnings': warnings,
                'search_mode':search_mode,'requires_selection':search_mode == 'similar'}

    def search_again(self, photo_id, name, page=1):
        extracted = self._get(photo_id, 'photo') if photo_id else {}
        return self.match_extracted(extracted, name=name, page=page)

    def confirm_candidate(self, candidate_id, confirmed, mismatch_ack=False):
        if confirmed is not True:
            raise ServiceError('제품과 공식 성분을 확인한 후 확인 버튼을 누르세요.')
        record = self._get(candidate_id, 'candidate')
        comparison = record['comparison']
        if comparison['status'] != '일치' and mismatch_ack is not True:
            raise ServiceError('불일치·누락 항목을 다시 확인하고 추가 확인을 완료하세요.')
        product = official_calculation_product(record['detail'], comparison, record['extracted'])
        approval = self._put('approved', product)
        return {'approval_id': approval, 'product': product, 'comparison_status': comparison['status']}

    def register_product_override(self, candidate_id, data):
        record = self._get(candidate_id, 'candidate')
        save_override(data, record['detail']['product'])
        return self.auto_apply_candidate(candidate_id)

    def resolve_candidate(self, candidate_id):
        record = self._get(candidate_id, 'candidate')
        base = record['detail'].get('original_official',record['detail'])
        # A temporary search-time detail failure must not permanently freeze an empty formula.
        if not base.get('ingredients_raw') or base.get('warnings'):
            code = str(base.get('product',{}).get('ITEM_SEQ',''))
            try:
                refreshed = self.client.detail(code)
                if str(refreshed.get('product',{}).get('ITEM_SEQ','')) == code and refreshed.get('ingredients_raw'):
                    base = refreshed
            except ServiceError:
                pass
        detail = apply_override(base)
        comparison = compare_ingredients(record['extracted'],detail)
        if detail.get('product_override') or (comparison['calculation_ready'] and comparison['all_match']):
            resolution = {'status':'matched','source_url':detail.get('source',''),'notes':['기존 검토 보완값 또는 명확히 일치한 공식 API 사용']}
        else:
            resolution = resolve_official(base)
            detail = apply_resolution(base,resolution)
            comparison = compare_ingredients(record['extracted'],detail)
            if any(r['status'] in ('함량 불일치','사진에만 있음') for r in comparison['rows']):
                resolution['status']='review'
                resolution['notes'].append('사진과 공식 자료의 성분·함량이 일치하지 않습니다.')
        ready = resolution['status']=='matched' and comparison['calculation_ready']
        if not ready:
            comparison['calculation_ready']=False
            comparison['warnings']=list(dict.fromkeys(comparison['warnings']+resolution.get('notes',[])))
        record.update(detail=detail,comparison=comparison,automatic_resolution=resolution,needs_review=not ready)
        with self.lock:
            stored=self.records.get(candidate_id)
            if not stored or stored[1]!='candidate':raise ServiceError('후보가 만료되었습니다. 다시 분석하세요.')
            self.records[candidate_id]=(stored[0],'candidate',copy.deepcopy(record))
        return {'candidate_id':candidate_id,'product':detail['product'],'comparison':comparison,
                'resolution':resolution}

    def product_support(self, candidate_id):
        record = self._get(candidate_id, 'candidate')
        return SupplementalClient().for_product(record['detail'])

    def auto_apply_candidate(self, candidate_id):
        record = self._get(candidate_id, 'candidate')
        record['detail'] = apply_override(record['detail'].get('original_official', record['detail']))
        if not record['detail'].get('product_override'):
            if record.get('needs_review'):
                raise ServiceError('공식 자료 대조가 불명확합니다. 찾은 근거를 확인하고 보완값을 등록하세요.')
            if record.get('automatic_resolution',{}).get('proposal'):
                record['detail'] = apply_resolution(record['detail'],record['automatic_resolution'])
        record['comparison'] = compare_ingredients(record['extracted'], record['detail'])
        comparison = record['comparison']
        product = official_calculation_product(record['detail'], comparison, record['extracted'])
        product['automatic_resolution'] = record['detail'].get('automatic_resolution')
        product['product_override'] = record['detail'].get('product_override')
        if product['product_override'] or product['automatic_resolution']:
            product['original_official'] = record['detail'].get('original_official')
        product['selection_method'] = 'automatic'
        product['user_reviewed'] = False
        product['comparison_status'] = comparison['status']
        product['comparison_warnings'] = list(comparison.get('warnings', []))
        product['comparison_rows'] = comparison.get('rows', [])
        approval = self._put('approved', product)
        return {'approval_id': approval, 'product': product, 'comparison_status': comparison['status']}

    def evaluate(self, submitted, mode, rules, profile=None, quantity_intent='planned'):
        if not isinstance(submitted, list) or not submitted or len(submitted) > 30:
            raise ServiceError('확인된 제품을 1~30개 추가하세요.')
        canonical = []
        for item in submitted:
            if not isinstance(item, dict):
                raise ServiceError('계산 입력을 확인하세요.')
            product = self._get(item.get('approval_id'), 'approved')
            # 클라이언트가 바꾼 성분명·함량·코드는 사용하지 않습니다.
            product['quantity'] = item.get('quantity')
            canonical.append(product)
        return calculate(canonical, mode, rules, profile=profile,quantity_intent=quantity_intent)
