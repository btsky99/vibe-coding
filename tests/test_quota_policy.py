"""
FILE: tests/test_quota_policy.py
DESCRIPTION: 사용량 snapshot의 다섯 권고 상태와 guard 동작 회귀 테스트.

REVISION HISTORY:
- 2026-08-03 Codex: quota policy 최초 테스트 작성
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".ai_monitor"))
from src.quota_policy import advise, advise_all


NOW = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)


def _snapshot(five_used=20, five_minutes=180, seven_used=20, seven_days=5):
    return {
        "available": True,
        "five_hour": {"utilization": five_used,
                      "resets_at": (NOW + timedelta(minutes=five_minutes)).isoformat()},
        "seven_day": {"utilization": seven_used,
                      "resets_at": (NOW + timedelta(days=seven_days)).isoformat()},
    }


def test_large_work_when_short_and_weekly_windows_have_room():
    assert advise(_snapshot(), now=NOW)["level"] == "large_ok"


def test_weekly_risk_has_priority_over_short_window_room():
    result = advise(_snapshot(five_used=5, seven_used=90, seven_days=5), now=NOW)
    assert result["level"] == "weekly_risk"
    assert result["recommended_task_size"] == "small"


def test_wait_when_short_window_reset_is_close():
    assert advise(_snapshot(five_used=90, five_minutes=20, seven_days=1), now=NOW)["level"] == "wait_reset"


def test_small_only_when_short_window_is_low_and_reset_is_far():
    assert advise(_snapshot(five_used=80, five_minutes=180, seven_days=1), now=NOW)["level"] == "small_only"


def test_weekly_only_snapshot_is_normal_when_pace_is_safe():
    snapshot = _snapshot(seven_used=20, seven_days=1)
    snapshot["five_hour"] = None
    assert advise(snapshot, now=NOW)["level"] == "normal"


def test_unavailable_is_fail_open_and_preserves_reason():
    result = advise({"available": False, "reason": "offline"}, now=NOW)
    assert result["level"] == "unavailable"
    assert result["blocks_new_work"] is False
    assert result["reason"] == "offline"


def test_pause_and_approve_modes_are_distinct():
    snapshot = _snapshot(five_used=90, five_minutes=180, seven_days=1)
    assert advise(snapshot, {"mode": "pause"}, NOW)["blocks_new_work"] is True
    assert advise(snapshot, {"mode": "approve"}, NOW)["requires_approval"] is True


def test_advise_all_keeps_provider_names():
    result = advise_all({"claude": _snapshot(), "codex": _snapshot()}, now=NOW)
    assert set(result) == {"claude", "codex"}
