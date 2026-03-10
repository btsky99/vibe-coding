import os
import sys
from pathlib import Path

from src.file_store import ensure_legacy_store


def _find_project_root() -> Path:
    if os.getenv('VIBE_PROJECT_ROOT'):
        return Path(os.getenv('VIBE_PROJECT_ROOT'))
    start_path = (
        Path(sys.executable).resolve().parent
        if getattr(sys, 'frozen', False)
        else Path(__file__).resolve().parent.parent.parent
    )
    markers = ['.git', 'CLAUDE.md', 'GEMINI.md']
    for path in [start_path, *start_path.parents]:
        if any((path / marker).exists() for marker in markers):
            return path
    return start_path


PROJECT_ROOT = _find_project_root()
if getattr(sys, 'frozen', False):
    local_data = PROJECT_ROOT / '.ai_monitor' / 'data'
    if local_data.exists():
        DATA_DIR = local_data
    elif os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA', '')) / 'VibeCoding'
    else:
        DATA_DIR = Path.home() / '.vibe-coding'
else:
    DATA_DIR = Path(__file__).resolve().parent.parent / 'data'


def get_connection():
    raise RuntimeError('SQLite runtime storage was removed. Use file_store or pg_store helpers instead.')


def init_db():
    ensure_legacy_store(DATA_DIR)


if __name__ == '__main__':
    print(f'Initializing file-backed legacy store at: {DATA_DIR}')
    init_db()
    print('[OK] Legacy file store initialized.')
