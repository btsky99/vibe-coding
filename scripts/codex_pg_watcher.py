"""
FILE: scripts/codex_pg_watcher.py
DESCRIPTION: Mirror Codex CLI history entries into PostgreSQL pg_logs.

REVISION HISTORY:
- 2026-05-03 Codex: Add Codex history watcher so Codex turns are logged automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / ".ai_monitor" / "data"
DEFAULT_STATE_PATH = DATA_DIR / "codex_pg_watcher_state.json"
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


@dataclass(frozen=True)
class CodexHistoryEntry:
    session_id: str
    ts: int
    text: str

    @property
    def key(self) -> str:
        return f"history:{self.session_id}:{self.ts}"


@dataclass(frozen=True)
class CodexLogEvent:
    key: str
    task: str
    status: str
    metadata: dict


def _decode_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return " ".join(text.split())


def read_history(path: Path) -> list[CodexHistoryEntry]:
    if not path.exists():
        return []

    entries: list[CodexHistoryEntry] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        session_id = str(row.get("session_id") or "").strip()
        text = _decode_text(row.get("text"))
        try:
            ts = int(row.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0

        if session_id and ts and text:
            entries.append(CodexHistoryEntry(session_id=session_id, ts=ts, text=text))
    return entries


def _short(value: object, limit: int = 500) -> str:
    text = _decode_text(value)
    return text[:limit]


def _command_text(payload: dict) -> str:
    command = payload.get("command")
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    if command:
        return str(command)

    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed.get("command") or parsed.get("cmd") or arguments
        except json.JSONDecodeError:
            return arguments
    return ""


def _assistant_text(payload: dict) -> str:
    parts = payload.get("content") or []
    if not isinstance(parts, list):
        return ""
    texts = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
            texts.append(str(part.get("text") or ""))
    return _decode_text(" ".join(texts))


def read_session_events(codex_home: Path) -> list[CodexLogEvent]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []

    events: list[CodexLogEvent] = []
    files = sorted(sessions_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)[-20:]
    for file_path in files:
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            row_type = row.get("type")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            key = f"session:{file_path.name}:{idx}:{row_type}:{payload.get('call_id', '')}"

            if row_type == "response_item" and payload.get("type") == "function_call":
                name = str(payload.get("name") or "tool")
                detail = _command_text(payload)
                events.append(CodexLogEvent(
                    key=key,
                    task=f"[Codex 도구 호출] {name}: {_short(detail, 400)}",
                    status="started",
                    metadata={"source": "codex_session", "event": "function_call", "tool": name},
                ))
            elif row_type == "event_msg" and payload.get("type") == "exec_command_end":
                exit_code = payload.get("exit_code")
                status = "success" if exit_code == 0 else "error"
                detail = _command_text(payload)
                events.append(CodexLogEvent(
                    key=key,
                    task=f"[Codex 명령 완료] exit={exit_code}: {_short(detail, 400)}",
                    status=status,
                    metadata={"source": "codex_session", "event": "exec_command_end", "exit_code": exit_code},
                ))
            elif row_type == "response_item" and payload.get("type") == "message":
                if payload.get("role") == "assistant" and payload.get("phase") == "final":
                    text = _assistant_text(payload)
                    if text:
                        events.append(CodexLogEvent(
                            key=key,
                            task=f"[Codex 응답 완료] {_short(text, 500)}",
                            status="success",
                            metadata={"source": "codex_session", "event": "assistant_final"},
                        ))
    return events


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(str(item) for item in data.get("seen", []))


def save_seen(path: Path, seen: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(set(seen))[-5000:]
    path.write_text(json.dumps({"seen": keys}, ensure_ascii=False, indent=2), encoding="utf-8")


def _history_seen(entry: CodexHistoryEntry, seen: set[str]) -> bool:
    if entry.key in seen:
        return True
    legacy_prefix = f"{entry.session_id}:{entry.ts}:"
    return any(key.startswith(legacy_prefix) for key in seen)


def _insert_pg_log(task: str, status: str, metadata: dict) -> bool:
    sys.path.insert(0, str(PROJECT_ROOT / ".ai_monitor"))
    try:
        from infra.project_context import slugify
        from src.pg_store import insert_pg_log

        insert_pg_log(
            agent="Codex",
            task=task,
            status=status,
            terminal_id="CODEX",
            project_id=slugify(PROJECT_ROOT),
            metadata=metadata,
        )
        return True
    except Exception:
        return False


def _log_history_entry(entry: CodexHistoryEntry) -> bool:
    return _insert_pg_log(
        task=f"[Codex 입력] {entry.text[:500]}",
        status="success",
        metadata={
            "source": "codex_history",
            "session_id": entry.session_id,
            "codex_ts": entry.ts,
        },
    )


def _log_session_event(event: CodexLogEvent) -> bool:
    return _insert_pg_log(task=event.task, status=event.status, metadata=event.metadata)


def sync_once(
    codex_home: Path = DEFAULT_CODEX_HOME,
    state_path: Path = DEFAULT_STATE_PATH,
    mark_existing: bool = False,
    backfill_recent: int = 0,
) -> int:
    history_path = codex_home / "history.jsonl"
    entries = read_history(history_path)
    session_events = read_session_events(codex_home)
    seen = load_seen(state_path)

    if mark_existing and not seen and backfill_recent <= 0:
        save_seen(state_path, [entry.key for entry in entries] + [event.key for event in session_events])
        return 0

    pending = [entry for entry in entries if not _history_seen(entry, seen)]
    pending_events = [event for event in session_events if event.key not in seen]
    if backfill_recent > 0:
        pending = pending[-backfill_recent:]
        pending_events = pending_events[-backfill_recent:]

    logged = 0
    for entry in pending:
        if _log_history_entry(entry):
            logged += 1
            seen.add(entry.key)
    for event in pending_events:
        if _log_session_event(event):
            logged += 1
            seen.add(event.key)

    if pending or pending_events or not state_path.exists():
        remaining = [entry.key for entry in entries if entry not in pending]
        remaining.extend(event.key for event in session_events if event not in pending_events)
        save_seen(state_path, seen.union(remaining))
    return logged


def run_daemon(interval: float = 5.0) -> None:
    sync_once(mark_existing=True)
    while True:
        sync_once()
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror Codex CLI history into pg_logs.")
    parser.add_argument("--once", action="store_true", help="Run one sync pass and exit.")
    parser.add_argument("--mark-existing", action="store_true", help="Mark existing history as seen.")
    parser.add_argument("--backfill-recent", type=int, default=0, help="Log the newest N unseen entries.")
    parser.add_argument("--interval", type=float, default=5.0, help="Daemon polling interval seconds.")
    args = parser.parse_args()

    if args.once:
        print(sync_once(mark_existing=args.mark_existing, backfill_recent=args.backfill_recent))
        return 0

    run_daemon(interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
