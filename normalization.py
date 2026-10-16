"""표기만 정리합니다. 염형·동의어·다른 화학명은 변환하지 않습니다."""
import re
import unicodedata

STANDARD = re.compile(r'^(?:kp|usp(?:-?nf)?|ep|bp|jp|ph\.?eur\.?|별규|약전|규격)[\s.\-\d]*$', re.I)


def normalize_name(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value).lower()
    value = re.sub(r'\(([^()]*)\)', lambda m: '' if STANDARD.fullmatch(m.group(1).strip()) else m.group(0), value)
    return re.sub(r'\s+', '', value)
