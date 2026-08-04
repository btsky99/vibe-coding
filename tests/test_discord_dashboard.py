"""
FILE: tests/test_discord_dashboard.py
DESCRIPTION: Discord Components V2 dashboard 렌더링과 webhook upsert 회귀 테스트.

REVISION HISTORY:
- 2026-08-03 Codex: 최초 작성
"""

import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import discord_dashboard as dashboard


class _Response:
    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body.read()


def test_payload_contains_quota_advice_and_terminal_identity(monkeypatch):
    monkeypatch.setattr(dashboard.time, "time", lambda: 1000)
    quota = {"claude": {"available": True, "five_hour": {"utilization": 20},
                         "advice": {"level": "large_ok", "action": "큰 작업 진행",
                                    "reason": "여유 있음"}}}
    terminals = {"T1": {"cli": "claude", "status": "running", "project_id": "vibe"}}
    payload = dashboard.build_payload(quota, terminals, "vibe")
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["flags"] == 32768
    assert "큰 작업 진행" in text
    assert "T1" in text and "claude" in text


def test_patch_keeps_message_id(monkeypatch):
    seen = []

    def fake(request, timeout=0):
        seen.append((request.method, request.full_url))
        return _Response({"id": "42"})

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", fake)
    result = dashboard.upsert("https://discord.com/api/webhooks/a/b", {"components": []}, "42")
    assert result == "42"
    assert seen == [("PATCH", "https://discord.com/api/webhooks/a/b/messages/42?with_components=true&wait=true")]


def test_missing_message_falls_back_to_post(monkeypatch):
    methods = []

    def fake(request, timeout=0):
        methods.append(request.method)
        if request.method == "PATCH":
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        return _Response({"id": "new"})

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", fake)
    assert dashboard.upsert("https://discord.com/api/webhooks/a/b", {}, "old") == "new"
    assert methods == ["PATCH", "POST"]
