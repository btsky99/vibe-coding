# -*- coding: utf-8 -*-
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"

sys.path.insert(0, str(_AI_MONITOR))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from src import db_helper


def test_send_message_passes_channel_terminal_and_metadata(monkeypatch):
    captured = {}

    def fake_itcp_send(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(db_helper, "itcp_send", fake_itcp_send)

    ok = db_helper.send_message(
        "msg-1",
        "user",
        "all",
        "request",
        "hello",
        channel="general",
        terminal_id="T1",
        metadata={"source": "dashboard"},
    )

    assert ok is True
    assert captured == {
        "from_terminal": "user",
        "to_terminal": "all",
        "content": "hello",
        "channel": "general",
        "msg_type": "request",
        "terminal_id": "T1",
        "metadata": {"source": "dashboard"},
    }


def test_get_messages_filters_private_telegram_channel(monkeypatch):
    captured = {}

    def fake_query_rows(sql):
        captured["sql"] = sql
        return [{
            "id": "1",
            "msg_from": "claude",
            "msg_to": "all",
            "msg_type": "info",
            "content": "synced",
            "is_read": "false",
            "timestamp": "2026-03-27T22:00:00",
        }]

    monkeypatch.setattr(db_helper, "query_rows", fake_query_rows)

    rows = db_helper.get_messages(limit=25)

    assert "WHERE channel <> 'telegram_response'" in captured["sql"]
    assert rows == [{
        "id": "1",
        "from": "claude",
        "to": "all",
        "type": "info",
        "content": "synced",
        "read": False,
        "timestamp": "2026-03-27T22:00:00",
    }]
