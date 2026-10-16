"""작업 폴더에 상관없이 이 프로젝트의 .env를 읽습니다. 비밀값은 출력하지 않습니다.

.env 파일이 있으면 그 파일만 사용합니다(로컬 실행). 파일이 없으면 Render 등 배포 환경으로 보고
운영체제 환경변수를 사용합니다. 두 값을 섞지 않습니다."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def settings():
    path = ROOT / '.env'
    if not path.exists():
        return dict(os.environ)
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('\"\'')
    return values
