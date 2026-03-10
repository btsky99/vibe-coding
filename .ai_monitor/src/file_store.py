import json
import threading
import time
from pathlib import Path


MEMORY_FILE_NAME = 'shared_memory.json'
SESSION_LOGS_FILE_NAME = 'session_logs.jsonl'
SKILL_CHAIN_FILE_NAME = 'skill_chain.json'

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def memory_file(data_dir: Path) -> Path:
    return data_dir / MEMORY_FILE_NAME


def session_logs_file(data_dir: Path) -> Path:
    return data_dir / SESSION_LOGS_FILE_NAME


def skill_chain_file(data_dir: Path) -> Path:
    return data_dir / SKILL_CHAIN_FILE_NAME


def ensure_legacy_store(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_file(data_dir)
    if not memory_path.exists():
        _write_json(memory_path, [])
    sessions_path = session_logs_file(data_dir)
    if not sessions_path.exists():
        sessions_path.write_text('', encoding='utf-8')
    skill_path = skill_chain_file(data_dir)
    if not skill_path.exists():
        _write_json(skill_path, [])


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _write_json(path: Path, payload) -> None:
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + '.tmp')
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        tmp_path.replace(path)


def load_memory_entries(data_dir: Path) -> list[dict]:
    ensure_legacy_store(data_dir)
    entries = _read_json(memory_file(data_dir), [])
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        tags = item.get('tags', [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
        if not isinstance(tags, list):
            tags = []
        item['tags'] = tags
        result.append(item)
    result.sort(key=lambda row: row.get('updated_at', ''), reverse=True)
    return result


def get_memory_entry(data_dir: Path, key: str) -> dict | None:
    for entry in load_memory_entries(data_dir):
        if entry.get('key') == key:
            return entry
    return None


def upsert_memory_entry(data_dir: Path, entry: dict) -> dict:
    ensure_legacy_store(data_dir)
    entries = load_memory_entries(data_dir)
    payload = dict(entry)
    payload['key'] = str(payload.get('key', '')).strip()
    payload['title'] = str(payload.get('title', '') or payload['key'])
    payload['content'] = str(payload.get('content', ''))
    payload['author'] = str(payload.get('author', 'unknown'))
    payload['project'] = str(payload.get('project', ''))
    payload['created_at'] = str(payload.get('created_at', '') or payload.get('updated_at', '') or _now_iso())
    payload['updated_at'] = str(payload.get('updated_at', '') or _now_iso())
    tags = payload.get('tags', [])
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
    payload['tags'] = tags if isinstance(tags, list) else []
    replaced = False
    for index, current in enumerate(entries):
        if current.get('key') == payload['key']:
            payload['created_at'] = current.get('created_at', payload['created_at'])
            entries[index] = payload
            replaced = True
            break
    if not replaced:
        entries.append(payload)
    entries.sort(key=lambda row: row.get('updated_at', ''), reverse=True)
    _write_json(memory_file(data_dir), entries)
    return payload


def delete_memory_entry(data_dir: Path, key: str) -> bool:
    ensure_legacy_store(data_dir)
    entries = load_memory_entries(data_dir)
    filtered = [entry for entry in entries if entry.get('key') != key]
    if len(filtered) == len(entries):
        return False
    _write_json(memory_file(data_dir), filtered)
    return True


def merge_memory_files(source_dir: Path, target_dir: Path) -> tuple[int, int]:
    ensure_legacy_store(source_dir)
    ensure_legacy_store(target_dir)
    merged = 0
    skipped = 0
    target_entries = {entry.get('key'): entry for entry in load_memory_entries(target_dir)}
    for entry in load_memory_entries(source_dir):
        key = entry.get('key')
        if not key:
            continue
        current = target_entries.get(key)
        if current is None or str(current.get('updated_at', '')) < str(entry.get('updated_at', '')):
            target_entries[key] = entry
            merged += 1
        else:
            skipped += 1
    rows = list(target_entries.values())
    rows.sort(key=lambda row: row.get('updated_at', ''), reverse=True)
    _write_json(memory_file(target_dir), rows)
    return merged, skipped


def load_session_logs(data_dir: Path, limit: int | None = None) -> list[dict]:
    ensure_legacy_store(data_dir)
    path = session_logs_file(data_dir)
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return []
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            result.append(item)
    result.sort(key=lambda row: row.get('ts_start', ''), reverse=True)
    if limit is not None:
        return result[:limit]
    return result


def get_agent_last_seen_from_sessions(data_dir: Path, agent_names: list[str]) -> dict[str, str | None]:
    result = {name: None for name in agent_names}
    for row in load_session_logs(data_dir):
        agent = str(row.get('agent', '')).lower()
        ts_start = row.get('ts_start')
        for wanted in agent_names:
            if wanted in agent and result.get(wanted) is None:
                result[wanted] = ts_start
    return result


def load_skill_chain_rows(data_dir: Path) -> list[dict]:
    ensure_legacy_store(data_dir)
    rows = _read_json(skill_chain_file(data_dir), [])
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def save_skill_chain_rows(data_dir: Path, rows: list[dict]) -> None:
    ensure_legacy_store(data_dir)
    payload = [dict(row) for row in rows if isinstance(row, dict)]
    payload.sort(
        key=lambda row: (
            row.get('updated_at', ''),
            row.get('started_at', ''),
            str(row.get('id', '')),
        ),
        reverse=True,
    )
    _write_json(skill_chain_file(data_dir), payload)
