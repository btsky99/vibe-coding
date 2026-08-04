"""
FILE: tests/test_pg_connectors.py
DESCRIPTION: connector event PostgreSQL 중복 claim과 상태 갱신 테스트.

REVISION HISTORY:
- 2026-08-03 Codex: 최초 작성
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".ai_monitor"))
from src import pg_connectors


def test_claim_returns_true_only_when_insert_returns_row(monkeypatch):
    monkeypatch.setattr(pg_connectors, "ensure_connector_schema", lambda: True)
    monkeypatch.setattr(pg_connectors, "query_rows", lambda _sql: [{"id": "1"}])
    assert pg_connectors.claim_event("discord:pc", "event") is True
    monkeypatch.setattr(pg_connectors, "query_rows", lambda _sql: [])
    assert pg_connectors.claim_event("discord:pc", "event") is False


def test_mark_merges_metadata(monkeypatch):
    seen = []
    monkeypatch.setattr(pg_connectors, "execute", lambda sql: seen.append(sql) or True)
    assert pg_connectors.mark_event("discord:pc", "event", "completed", {"ok": True})
    assert "completed" in seen[0]
    assert "metadata ||" in seen[0]
