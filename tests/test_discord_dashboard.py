"""
FILE: tests/test_discord_dashboard.py
DESCRIPTION: Discord Components V2 dashboard 렌더링과 webhook upsert 회귀 테스트.

REVISION HISTORY:
- 2026-08-04 Codex: Bot Token 기반 대시보드 upsert 회귀 테스트 추가
- 2026-08-04 Codex: 남은 비율·리셋 시각·Gemini 컨텍스트 잔량 회귀 테스트 추가
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


def test_payload_shows_remaining_reset_and_gemini_context(monkeypatch):
    monkeypatch.setattr(dashboard.time, "time", lambda: 1000)
    quota = {
        "claude": {"available": True, "five_hour": {
            "utilization": 20, "resets_at": "2026-08-04T12:00:00+00:00"}},
        "codex": {"available": True, "seven_day": {"utilization": 65}},
        "gemini": dashboard._gemini_snapshot({"percentage": 30, "context_window": 1000000}),
    }
    text = json.dumps(dashboard.build_payload(quota, {}, "vibe"), ensure_ascii=False)
    assert "5시간 80% 남음" in text
    assert "7일 35% 남음" in text
    assert "리셋 <t:" in text
    assert "GEMINI" in text and "현재 컨텍스트 70% 남음" in text
    assert "플랜 쿼터가 아닌 현재 세션 컨텍스트 잔량" in text


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


def test_bot_upsert_uses_channel_api_and_authorization(monkeypatch):
    seen = []

    def fake(request, timeout=0):
        seen.append((request.method, request.full_url, request.headers.get("Authorization")))
        return _Response({"id": "77"})

    monkeypatch.setattr(dashboard.urllib.request, "urlopen", fake)
    result = dashboard.upsert_bot("secret", "123", {"components": []}, "77")
    assert result == "77"
    assert seen == [("PATCH", "https://discord.com/api/v10/channels/123/messages/77", "Bot secret")]
