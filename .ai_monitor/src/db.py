# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/db.py
# 📝 설명: 레거시 DB 진입점 (SQLite 런타임 저장소 폐기 잔재). get_connection()은
#          RuntimeError로 차단하고, init_db()는 file_store 레거시 스토어 초기화로 위임.
#          프로젝트 루트 탐색(.git/CLAUDE.md/GEMINI.md 마커)도 여기서 제공.
# 🕒 변경 이력:
# [2026-07-18] Claude — 헤더 누락 보강 (코드 품질 점검 규칙 5 준수)
# ────────────────────────────────────────────────────────────────────────────
import os
import sys
from pathlib import Path

from src.file_store import ensure_legacy_store


def _find_project_root() -> Path:
    if os.getenv('VIBE_PROJECT_ROOT'):
        return Path(os.getenv('VIBE_PROJECT_ROOT'))
    start_path = Path(__file__).resolve().parent.parent.parent
    markers = ['.git', 'CLAUDE.md', 'GEMINI.md']
    for path in [start_path, *start_path.parents]:
        if any((path / marker).exists() for marker in markers):
            return path
    return start_path


PROJECT_ROOT = _find_project_root()
DATA_DIR = Path(__file__).resolve().parent.parent / 'data'


def get_connection():
    raise RuntimeError('SQLite runtime storage was removed. Use file_store or pg_store helpers instead.')


def init_db():
    ensure_legacy_store(DATA_DIR)


if __name__ == '__main__':
    print(f'Initializing file-backed legacy store at: {DATA_DIR}')
    init_db()
    print('[OK] Legacy file store initialized.')
