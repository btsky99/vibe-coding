"""
FILE: .ai_monitor/__init__.py
DESCRIPTION: ai_monitor 패키지 초기화 — pip install 시 패키지로 인식되도록 함.
  server.py 내부의 `import api.*`, `import src.*` 등 기존 절대 임포트를
  패키지 모드에서도 정상 동작시키기 위해 .ai_monitor 디렉토리를 sys.path에 추가.

REVISION HISTORY:
- 2026-03-25 Claude: 신규 생성 — pip install 배포 전환. sys.path 호환성 패치 추가.
"""
import sys
from pathlib import Path

# server.py 내부에서 `import api.mcp_api` 등 절대 임포트를 사용함.
# pip 패키지 모드에서는 `ai_monitor.api.mcp_api`가 정식 경로이지만,
# 기존 dev 모드(python server.py)와의 호환성을 위해 .ai_monitor 디렉토리를
# sys.path에 추가하여 양쪽 모드 모두 동작하도록 함.
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from ._version import __version__

__all__ = ["__version__"]
