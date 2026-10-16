"""추가 공식 API. 제품 함량과 성분별 최대투여량을 구분해 보존합니다."""
from config import settings
from mfds_client import MFDSClient, ServiceError

EASY_SOURCE = 'https://www.data.go.kr/data/15075057/openapi.do'
MAX_SOURCE = 'https://www.data.go.kr/data/15098095/openapi.do'


class SupplementalClient:
    def __init__(self, client=None):
        self.client = client or MFDSClient()

    def product_info(self, code):
        if settings().get('MFDS_EASY_ENABLED', 'false').lower() != 'true':
            return {'status':'disabled', 'source':EASY_SOURCE, 'items':[]}
        try:
            data = self.client.query('getDrbEasyDrugList',
                service_base='https://apis.data.go.kr/1471000/DrbEasyDrugInfoService',
                key_name='MFDS_EASY_SERVICE_KEY', service_key_param='ServiceKey', itemSeq=code)
            rows = [r for r in data['items'] if str(r.get('itemSeq','')) == str(code)]
            if len(rows) != 1 or data['total'] != 1:
                return {'status':'unconfirmed', 'source':EASY_SOURCE, 'items':[], 'note':'동일 품목의 정보를 한 개로 확인하지 못했습니다.'}
            return {'status':'ok', 'source':EASY_SOURCE, 'items':rows}
        except ServiceError as error:
            return {'status':'error', 'source':EASY_SOURCE, 'items':[], 'note':str(error)}

    def ingredient_limits(self, code):
        if settings().get('MFDS_MAX_DOSE_ENABLED', 'false').lower() != 'true':
            return {'status':'disabled', 'source':MAX_SOURCE, 'items':[]}
        if not code:
            return {'status':'unconfirmed', 'source':MAX_SOURCE, 'items':[], 'note':'공식 성분코드 미확인'}
        try:
            data = self.client.query('getDayMaxDosgQyByIngdInq',
                service_base='https://apis.data.go.kr/1471000/DayMaxDosgQyByIngdService',
                key_name='MFDS_MAX_DOSE_SERVICE_KEY', CPNT_CD=code, numOfRows=100)
            rows = [r for r in data['items'] if str(r.get('CPNT_CD','')) == str(code)]
            return {'status':'ok' if rows and data['total'] == len(rows) else 'unconfirmed',
                    'source':MAX_SOURCE, 'items':rows,
                    'note':'제형·투여경로・대상 조건 검증 전 참고 기준입니다. 1정당 함량으로 사용하지 않습니다.'}
        except ServiceError as error:
            return {'status':'error', 'source':MAX_SOURCE, 'items':[], 'note':str(error)}

    def for_product(self, detail):
        code = str(detail['product'].get('ITEM_SEQ',''))
        codes = sorted({r.get('MTRAL_CODE') for r in detail.get('ingredients_raw',[])
                        if isinstance(r.get('MTRAL_CODE'),str) and r['MTRAL_CODE']})
        return {'easy':self.product_info(code),
                'maximum_dose':{c:self.ingredient_limits(c) for c in codes}}
