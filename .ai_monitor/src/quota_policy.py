"""
FILE: src/quota_policy.py
DESCRIPTION: provider 쿼터 snapshot을 작업 크기 권고로 변환하는 순수 정책 계층.
             외부 connector와 Vibe View가 동일한 판단을 공유하도록 UI에서 분리한다.

REVISION HISTORY:
- 2026-08-03 Codex: usage-coach의 페이스 비교 개념을 기존 quota 계약에 맞춰 구현
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_POLICY = {
    "margin": 0.10,
    "floor": 0.10,
    "big_task_threshold": 0.40,
    "soon_minutes": 30,
    "mode": "warn",
}

_WINDOW_SECONDS = {"five_hour": 5 * 60 * 60, "seven_day": 7 * 24 * 60 * 60}


def _parse_reset(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _window(snapshot: dict, key: str, now: datetime) -> dict | None:
    raw = snapshot.get(key)
    if not isinstance(raw, dict) or raw.get("utilization") is None:
        return None
    try:
        used = min(100.0, max(0.0, float(raw["utilization"])))
    except (TypeError, ValueError):
        return None
    reset = _parse_reset(raw.get("resets_at"))
    if reset is None or reset.timestamp() <= 0:
        return None
    seconds_left = max(0.0, (reset - now).total_seconds())
    window_seconds = float(raw.get("window_seconds") or _WINDOW_SECONDS[key])
    return {
        "left": (100.0 - used) / 100.0,
        "time_left": min(1.0, seconds_left / max(1.0, window_seconds)),
        "minutes_to_reset": seconds_left / 60.0,
        "resets_at": reset.isoformat(),
    }


def advise(snapshot: dict, policy: dict | None = None,
           now: datetime | None = None) -> dict:
    """단일 provider snapshot을 권고로 변환한다. 입력을 변경하지 않는다."""
    cfg = {**DEFAULT_POLICY, **(policy or {})}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    mode = cfg["mode"] if cfg["mode"] in {"off", "warn", "approve", "pause"} else "warn"
    base = {"mode": mode, "stale": bool(snapshot.get("stale"))}
    if not snapshot.get("available"):
        return {**base, "level": "unavailable", "recommended_task_size": "unknown",
                "action": "사용량을 확인할 수 없어 로컬 정책으로 진행하세요.",
                "reason": snapshot.get("reason") or "quota_unavailable", "blocks_new_work": False}

    five = _window(snapshot, "five_hour", current)
    seven = _window(snapshot, "seven_day", current)
    if five is None and seven is None:
        return {**base, "level": "unavailable", "recommended_task_size": "unknown",
                "action": "유효한 리셋 정보를 기다리세요.", "reason": "valid_window_missing",
                "blocks_new_work": False}

    margin = float(cfg["margin"])
    floor = float(cfg["floor"])
    weekly_risk = bool(seven and (seven["left"] < seven["time_left"] - margin
                                  or seven["left"] < floor))
    if weekly_risk:
        level, size = "weekly_risk", "small"
        action = "큰 작업은 미루고 꼭 필요한 작은 작업만 진행하세요."
        reason = "7일 잔량이 리셋까지 유지할 페이스보다 부족합니다."
    elif five and five["left"] >= float(cfg["big_task_threshold"]):
        level, size = "large_ok", "large"
        action = "지금 큰 작업을 진행해도 됩니다."
        reason = "5시간 잔량과 7일 페이스에 여유가 있습니다."
    elif five and five["minutes_to_reset"] <= float(cfg["soon_minutes"]):
        level, size = "wait_reset", "wait"
        action = "리셋 후 큰 작업을 시작하고 지금은 짧은 작업만 진행하세요."
        reason = "5시간 잔량은 부족하지만 리셋이 임박했습니다."
    elif five:
        level, size = "small_only", "small"
        action = "작은 작업만 진행하세요."
        reason = "5시간 잔량이 큰 작업 임계치보다 낮고 리셋까지 시간이 남았습니다."
    else:
        level, size = "normal", "normal"
        action = "평소대로 진행하세요."
        reason = "7일 페이스가 안전하며 5시간 데이터는 없습니다."

    risky = level in {"weekly_risk", "small_only"}
    blocks = risky and mode == "pause"
    requires_approval = risky and mode == "approve"
    return {**base, "level": level, "recommended_task_size": size, "action": action,
            "reason": reason, "blocks_new_work": blocks,
            "requires_approval": requires_approval,
            "windows": {k: v for k, v in (("five_hour", five), ("seven_day", seven)) if v}}


def advise_all(providers: dict, policy: dict | None = None,
               now: datetime | None = None) -> dict:
    """provider 이름을 보존한 채 모든 snapshot에 같은 정책을 적용한다."""
    return {name: advise(snapshot, policy=policy, now=now)
            for name, snapshot in providers.items() if isinstance(snapshot, dict)}
