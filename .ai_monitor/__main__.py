"""
FILE: .ai_monitor/__main__.py
DESCRIPTION: `python -m ai_monitor` 실행 지원 — pip install 후 모듈 직접 실행용.

REVISION HISTORY:
- 2026-03-25 Claude: 신규 생성 — pip install 배포 전환
"""
from .server import main

if __name__ == "__main__":
    main()
