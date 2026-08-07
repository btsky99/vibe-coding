#!/usr/bin/env python3
"""
FILE: scripts/discord_claude_bridge.py
DESCRIPTION: Discord 채널 ↔ 로컬 Claude Code(claude -p) 직결 브리지.
             vibe 서버(9000)를 거치지 않고 claude CLI를 직접 호출한다.

             [WHY 서버를 안 거치나] discord_gateway.py는 메시지를 vibe 서버의 태스크
             버스에 넣는 구조라 server.py가 떠 있어야 한다. 그런데 server.py는
             **데스크톱 앱 전제**(pywebview/PTY/GUI)라 헤드리스 리눅스 VPS에서는
             HTTP 리스너까지 도달하지 못한다(2026-08-08 실측: 포트 미개방).
             VPS의 목적은 "어디서든 에이전트를 부르는 것" 하나뿐이므로,
             데스크톱 스택 전체를 헤드리스로 이식하는 대신 필요한 한 줄기만 잇는다.

             [경계] 이 브리지는 터미널 멀티플렉싱·PTY·대시보드를 제공하지 않는다.
             그건 데스크톱 앱의 역할이고, 여기서는 의도적으로 다루지 않는다.

환경변수:
  DISCORD_BOT_TOKEN     봇 토큰
  DISCORD_CHANNEL_IDS   허용 채널 ID(쉼표 구분)
  DISCORD_USER_IDS      허용 사용자 ID(쉼표 구분)
  CLAUDE_WORKDIR        claude 실행 디렉터리 (기본 /opt/vibe/vibe-coding)
  CLAUDE_TIMEOUT        응답 제한 초 (기본 600)

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — VPS에서 server.py 헤드리스 기동이 막혀 대체 경로로 신설.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time

try:
    import websockets
except ImportError:
    print("[bridge] websockets 미설치: pip install websockets", flush=True)
    raise SystemExit(1)

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
API = "https://discord.com/api/v10"

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNELS = {c.strip() for c in os.environ.get("DISCORD_CHANNEL_IDS", "").split(",") if c.strip()}
USERS = {u.strip() for u in os.environ.get("DISCORD_USER_IDS", "").split(",") if u.strip()}
WORKDIR = os.environ.get("CLAUDE_WORKDIR", "/opt/vibe/vibe-coding")
TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
NODE = os.environ.get("VIBE_NODE_ID", "vps")

# 응답에서 비밀이 새는 것을 막는다 — 로그·채널 양쪽에 적용.
SECRET = re.compile(
    r"(?i)\b(token|api[_-]?key|password|secret|authorization)\b(\s*[:=]\s*)\S+")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def log(msg: str) -> None:
    print(f"[bridge] {msg}", flush=True)


def scrub(text: str) -> str:
    return SECRET.sub(r"\1\2[REDACTED]", ANSI.sub("", text))


def chunks(text: str, size: int = 1900) -> list[str]:
    """Discord 메시지 2000자 제한 대비 분할. 빈 문자열도 1개는 반환한다."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


async def send(session, channel: str, content: str) -> None:
    import aiohttp  # noqa: F401  (session 타입 힌트용 — 상단 import는 선택 의존)
    for part in chunks(scrub(content)):
        try:
            async with session.post(
                f"{API}/channels/{channel}/messages",
                headers={"Authorization": f"Bot {TOKEN}",
                         "User-Agent": "vibe-bridge/1.0"},
                json={"content": part},
            ) as resp:
                if resp.status >= 400:
                    log(f"전송 실패 {resp.status}: {(await resp.text())[:120]}")
        except Exception as e:
            log(f"전송 예외: {e}")


def run_claude(prompt: str) -> str:
    """claude -p 를 동기 실행한다.

    [제약] stdin을 반드시 닫는다(</dev/null 상당). 안 닫으면 claude가 파이프 입력을
      기다리며 "no stdin data received" 경고 후 진행이 늦어진다.
    [제약] 타임아웃은 넉넉히 준다 — 에이전트 작업은 수 분이 걸리는 것이 정상이다.
      대신 초과 시 부분 출력이라도 돌려준다(침묵보다 낫다).
    """
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            cwd=WORKDIR, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=TIMEOUT,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if out:
            return out
        return f"(출력 없음)\n{err[:800]}" if err else "(응답이 비어 있습니다)"
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return f"⏱ {TIMEOUT}초 초과로 중단했습니다.\n{partial[-1500:]}"
    except FileNotFoundError:
        return "claude 명령을 찾을 수 없습니다. 설치/PATH를 확인하세요."
    except Exception as e:
        return f"실행 오류: {type(e).__name__}: {e}"


async def handle(session, channel: str, author: str, content: str) -> None:
    if channel not in CHANNELS or (USERS and author not in USERS):
        return
    if not content or content.startswith(("!", "/")):
        return

    log(f"수신 ch={channel} user={author} len={len(content)}")
    await send(session, channel, f"🟢 `{NODE}` 처리 중…")
    t0 = time.time()
    # [WHY 스레드인가] claude 호출은 수 분 블로킹이다. 그대로 await하면 그 사이
    #   Discord heartbeat가 끊겨 세션이 죽는다. 별도 스레드로 밀어 이벤트 루프를 살린다.
    reply = await asyncio.to_thread(run_claude, content)
    await send(session, channel, f"{reply}\n\n— `{NODE}` {time.time() - t0:.0f}초")


async def serve() -> None:
    import aiohttp
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with websockets.connect(GATEWAY, max_size=None) as ws:
                    hello = json.loads(await ws.recv())
                    interval = hello["d"]["heartbeat_interval"] / 1000

                    async def beat():
                        while True:
                            await asyncio.sleep(interval)
                            await ws.send(json.dumps({"op": 1, "d": None}))

                    hb = asyncio.create_task(beat())
                    await ws.send(json.dumps({
                        "op": 2,
                        "d": {
                            "token": TOKEN,
                            # intents 33280 = GUILD_MESSAGES(512) + MESSAGE_CONTENT(32768)
                            # [제약] MESSAGE_CONTENT는 개발자 포털에서 켜야 실제로 내용이 온다.
                            #   안 켜면 content가 빈 문자열로 도착해 "봇은 붙었는데 무반응"이 된다.
                            "intents": 33280,
                            "properties": {"os": "linux", "browser": "vibe", "device": "vibe"},
                        },
                    }))
                    log(f"게이트웨이 연결 — 채널 {len(CHANNELS)}개 / 사용자 {len(USERS)}명 감시")

                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("t") != "MESSAGE_CREATE":
                            continue
                        d = msg.get("d") or {}
                        if (d.get("author") or {}).get("bot"):
                            continue
                        asyncio.create_task(handle(
                            session,
                            str(d.get("channel_id") or ""),
                            str((d.get("author") or {}).get("id") or ""),
                            str(d.get("content") or "").strip(),
                        ))
                    hb.cancel()
            except Exception as e:
                log(f"연결 끊김: {type(e).__name__}: {e} — 10초 후 재접속")
                await asyncio.sleep(10)


def main() -> int:
    if not TOKEN or not CHANNELS:
        log("DISCORD_BOT_TOKEN 과 DISCORD_CHANNEL_IDS 가 필요하다")
        return 1
    log(f"node={NODE} workdir={WORKDIR} timeout={TIMEOUT}s")
    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
