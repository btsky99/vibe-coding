"""
FILE: tests/test_claude_quota.py
DESCRIPTION: Claude 사용량 응답에서 신규 모델별 주간 한도를 보존하는 회귀 테스트.

REVISION HISTORY:
- 2026-07-26 Codex: Fable 모델 한도 누락 회귀 테스트 추가.
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".ai_monitor"))
from src import claude_quota


class _Response:
    def __init__(self, payload):
        self._body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body.read()


def test_fetch_preserves_new_model_quota(monkeypatch):
    payload = {
        "five_hour": {"utilization": 3, "resets_at": "2026-07-26T12:00:00Z"},
        "seven_day": {"utilization": 92, "resets_at": "2026-07-28T00:00:00Z"},
        "seven_day_fable": {"utilization": 100, "resets_at": "2026-07-28T00:00:00Z"},
        "unrelated": {"enabled": True},
    }
    monkeypatch.setattr(
        claude_quota.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    result = claude_quota._fetch("token")

    assert result["seven_day"]["utilization"] == 92
    assert result["model_windows"] == {
        "seven_day_fable": {
            "utilization": 100,
            "resets_at": "2026-07-28T00:00:00Z",
        }
    }
