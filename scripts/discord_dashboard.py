"""
FILE: scripts/discord_dashboard.py
DESCRIPTION: Vibe Coding 상태를 Discord Components V2 웹훅 메시지 하나로 갱신한다.
             bot Gateway 없이 읽기 전용 대시보드만 담당한다.

REVISION HISTORY:
- 2026-08-04 Codex: 저장된 Bot Token+T1 채널로 Webhook 없이 대시보드 자동 게시
- 2026-08-04 Codex: Claude/Codex 남은 비율·리셋 시각과 Gemini 컨텍스트 잔량 표시
- 2026-08-03 Codex: 단일 메시지 upsert, PostgreSQL 상태, 5분 daemon 최초 구현
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


COMPONENTS_V2_FLAG = 1 << 15
DEFAULT_INTERVAL = 300


def _get_json(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _bar(used: Any) -> str:
    try:
        value = min(100.0, max(0.0, float(used)))
    except (TypeError, ValueError):
        return "░░░░░░░░░░"
    filled = round(value / 10)
    return "█" * filled + "░" * (10 - filled)


def _reset_label(value: Any) -> str:
    """ISO reset time을 Discord의 사용자 현지 시각으로 표시한다."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return f" · 리셋 <t:{int(parsed.timestamp())}:R>"
    except (TypeError, ValueError):
        return ""


def _quota_section(name: str, snapshot: dict) -> dict:
    advice = snapshot.get("advice") or {}
    level = advice.get("level") or "unavailable"
    icon = {"large_ok": "🟢", "normal": "⚪", "wait_reset": "⏳",
            "small_only": "🟡", "weekly_risk": "🔴"}.get(level, "⚫")
    lines = [f"### {icon} {name.upper()}"]
    if snapshot.get("available"):
        primary_label = "현재 컨텍스트" if name.lower() == "gemini" else "5시간"
        windows = [("five_hour", primary_label), ("seven_day", "7일"),
                   ("seven_day_opus", "7일 Opus"), ("seven_day_sonnet", "7일 Sonnet")]
        windows.extend((key, str(key).replace("_", " "))
                       for key in (snapshot.get("model_windows") or {}))
        model_windows = snapshot.get("model_windows") or {}
        for key, label in windows:
            window = (model_windows.get(key) if key in model_windows else snapshot.get(key)) or {}
            if window.get("utilization") is not None:
                used = float(window["utilization"])
                remaining = max(0.0, 100.0 - used)
                lines.append(
                    f"`{_bar(used)}` **{label} {remaining:.0f}% 남음** "
                    f"({used:.0f}% 사용){_reset_label(window.get('resets_at'))}")
    else:
        lines.append("사용량 조회 불가")
    if advice.get("action"):
        lines.append(f"**권고:** {advice['action']}")
    if advice.get("reason") and level != "unavailable":
        lines.append(str(advice["reason"]))
    return {"type": 10, "content": "\n".join(lines)}


def _gemini_snapshot(usage: dict) -> dict:
    """Antigravity는 계정 쿼터 API가 없어 현재 세션 컨텍스트 잔량만 표시한다."""
    try:
        used = min(100.0, max(0.0, float(usage.get("percentage"))))
    except (TypeError, ValueError):
        return {"available": False, "reason": "context_usage_unavailable"}
    return {
        "available": bool(usage.get("context_window")),
        "five_hour": {"utilization": used},
        "advice": {
            "level": "normal",
            "action": "Gemini는 플랜 쿼터가 아닌 현재 세션 컨텍스트 잔량입니다.",
        },
    }


def _terminal_lines(payload: dict, limit: int = 12) -> list[str]:
    source = payload.get("terminals", payload)
    items = source.items() if isinstance(source, dict) else []
    lines = []
    for terminal_id, raw in list(items)[:limit]:
        value = raw if isinstance(raw, dict) else {}
        agent = value.get("cli") or value.get("agent") or value.get("type") or "idle"
        project = value.get("project_id") or value.get("cwd") or "-"
        state = value.get("status") or ("running" if value.get("running") else "idle")
        lines.append(f"• **{terminal_id}** · {agent} · {state} · `{str(project)[:60]}`")
    return lines


def build_payload(quota: dict, terminals: dict, project_id: str) -> dict:
    """Discord Components V2 payload를 만든다. 네트워크와 무관한 순수 변환이다."""
    children = [
        {"type": 10, "content": f"# Vibe Coding · {project_id}\n마지막 갱신 <t:{int(time.time())}:R>"},
        {"type": 14, "divider": True, "spacing": 1},
    ]
    for provider in ("claude", "codex", "gemini"):
        children.append(_quota_section(provider, quota.get(provider) or {}))
    lines = _terminal_lines(terminals)
    children.extend([
        {"type": 14, "divider": True, "spacing": 1},
        {"type": 10, "content": "### 터미널\n" + ("\n".join(lines) if lines else "활성 터미널 없음")},
    ])
    return {"flags": COMPONENTS_V2_FLAG, "components": [{"type": 17, "components": children}]}


def _webhook_url(base: str, message_id: str = "") -> str:
    clean = base.split("?", 1)[0].rstrip("/")
    if message_id:
        clean += f"/messages/{urllib.parse.quote(message_id, safe='')}"
    return clean + "?with_components=true&wait=true"


def upsert(webhook_url: str, payload: dict, message_id: str = "") -> str:
    """기존 message를 PATCH하고 없거나 삭제됐으면 POST로 새로 만든다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if message_id:
        request = urllib.request.Request(
            _webhook_url(webhook_url, message_id), data=body,
            headers={"Content-Type": "application/json"}, method="PATCH")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            return str(result.get("id") or message_id)
        except urllib.error.HTTPError as error:
            if error.code not in {404, 400}:
                raise
    request = urllib.request.Request(
        _webhook_url(webhook_url), data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    return str(result.get("id") or "")


def upsert_bot(token: str, channel_id: str, payload: dict, message_id: str = "") -> str:
    """공용 Bot Token으로 채널의 단일 대시보드 메시지를 생성하거나 갱신한다."""
    base = f"https://discord.com/api/v10/channels/{urllib.parse.quote(channel_id, safe='')}/messages"
    url = f"{base}/{urllib.parse.quote(message_id, safe='')}" if message_id else base
    method = "PATCH" if message_id else "POST"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "VibeCoding-DiscordDashboard/1.0",
    }
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
        return str(result.get("id") or message_id)
    except urllib.error.HTTPError as error:
        if not message_id or error.code not in {400, 404}:
            raise
    # 저장된 메시지가 삭제됐으면 같은 채널에 새 메시지를 만든다.
    return upsert_bot(token, channel_id, payload)


def _pg_modules(project_root: Path):
    monitor = project_root / ".ai_monitor"
    if str(monitor) not in sys.path:
        sys.path.insert(0, str(monitor))
    from src.pg_memory import get_memory, set_memory
    return get_memory, set_memory


def load_message_id(project_root: Path, project_id: str) -> str:
    try:
        get_memory, _ = _pg_modules(project_root)
        row = get_memory(f"discord_dashboard_state:{project_id}") or {}
        content = json.loads(row.get("content") or "{}")
        return str(content.get("message_id") or "")
    except Exception:
        return ""


def save_message_id(project_root: Path, project_id: str, message_id: str) -> None:
    if not message_id:
        return
    try:
        _, set_memory = _pg_modules(project_root)
        set_memory(
            f"discord_dashboard_state:{project_id}",
            json.dumps({"message_id": message_id}),
            title="Discord dashboard state", tags=["discord", "runtime-state"],
            author="discord-dashboard", project_id=project_id,
        )
    except Exception as error:
        print(f"[discord-dashboard] state save failed: {type(error).__name__}", flush=True)


def update_once(server: str, webhook: str, project_root: Path, project_id: str,
                token: str = "", channel_id: str = "") -> str:
    quota = _get_json(f"{server}/api/agent-quota")
    quota["gemini"] = _gemini_snapshot(_get_json(f"{server}/api/antigravity-context-usage"))
    terminals = _get_json(f"{server}/api/agent/terminals")
    previous = load_message_id(project_root, project_id)
    payload = build_payload(quota, terminals, project_id)
    current = (upsert(webhook, payload, previous) if webhook
               else upsert_bot(token, channel_id, payload, previous))
    save_message_id(project_root, project_id, current)
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord read-only Vibe dashboard")
    parser.add_argument("--server", default=os.environ.get("VIBE_SERVER_URL", "http://127.0.0.1:9000"))
    parser.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK_URL", ""))
    parser.add_argument("--token", default=os.environ.get("DISCORD_BOT_TOKEN", ""))
    parser.add_argument("--channel", default=os.environ.get("DISCORD_DASHBOARD_CHANNEL_ID", ""))
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--project-id", default=os.environ.get("VIBE_PROJECT_ID", "vibe-coding"))
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.webhook and not (args.token and args.channel):
        print("[discord-dashboard] webhook or bot token+channel not configured", flush=True)
        return 0
    root = Path(args.project_root).resolve()
    while True:
        try:
            update_once(args.server.rstrip("/"), args.webhook, root, args.project_id,
                        args.token, args.channel)
        except Exception as error:
            print(f"[discord-dashboard] update failed: {type(error).__name__}", flush=True)
        if args.once:
            return 0
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
