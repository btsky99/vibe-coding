import argparse
import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITOR_DIR = PROJECT_ROOT / '.ai_monitor'
if str(MONITOR_DIR) not in __import__('sys').path:
    __import__('sys').path.insert(0, str(MONITOR_DIR))

from src.file_store import ensure_legacy_store, save_skill_chain_rows, upsert_memory_entry


def _read_memory(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key, title, content, tags, author, project, timestamp, updated_at FROM memory"
        ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        tags = item.get('tags') or '[]'
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
        entries.append({
            'key': item.get('key', ''),
            'title': item.get('title', '') or item.get('key', ''),
            'content': item.get('content', ''),
            'tags': tags if isinstance(tags, list) else [],
            'author': item.get('author', 'unknown'),
            'project': item.get('project', ''),
            'created_at': item.get('timestamp', '') or item.get('updated_at', ''),
            'updated_at': item.get('updated_at', '') or item.get('timestamp', ''),
        })
    return entries


def _read_sessions(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_logs'"
        ).fetchone()
        if not exists:
            return []
        rows = conn.execute("SELECT * FROM session_logs ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _read_skill_chains(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_chains'"
        ).fetchone()
        if not exists:
            return []
        rows = conn.execute("SELECT * FROM skill_chains ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _write_sessions_jsonl(data_dir: Path, rows: list[dict]) -> None:
    session_path = data_dir / 'session_logs.jsonl'
    lines = []
    for row in rows:
        item = dict(row)
        files_changed = item.get('files_changed')
        if isinstance(files_changed, str):
            try:
                files_changed = json.loads(files_changed)
            except Exception:
                files_changed = []
        item['files_changed'] = files_changed if isinstance(files_changed, list) else []
        lines.append(json.dumps(item, ensure_ascii=False))
    session_path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')


def migrate(data_dir: Path) -> dict:
    ensure_legacy_store(data_dir)
    memory_entries = _read_memory(data_dir / 'shared_memory.db')
    for entry in memory_entries:
        upsert_memory_entry(data_dir, entry)
    session_rows = _read_sessions(data_dir / 'hive_mind.db')
    _write_sessions_jsonl(data_dir, session_rows)
    skill_rows = _read_skill_chains(data_dir / 'skill_chain.db')
    save_skill_chain_rows(data_dir, skill_rows)
    return {
        'memory_entries': len(memory_entries),
        'session_logs': len(session_rows),
        'skill_chain_rows': len(skill_rows),
        'memory_file': str(data_dir / 'shared_memory.json'),
        'session_file': str(data_dir / 'session_logs.jsonl'),
        'skill_chain_file': str(data_dir / 'skill_chain.json'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Export legacy SQLite stores to JSON/JSONL files.')
    parser.add_argument(
        '--data-dir',
        default=str(PROJECT_ROOT / '.ai_monitor' / 'data'),
        help='Directory containing legacy SQLite databases.',
    )
    args = parser.parse_args()
    result = migrate(Path(args.data_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
