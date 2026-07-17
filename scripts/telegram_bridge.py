# -*- coding: utf-8 -*-
"""
FILE: scripts/telegram_bridge.py
DESCRIPTION: Telegram Multi-Bot Bridge 진입점 — BotManager(최대 8봇 생명주기 +
             ITCP→그룹 미러링) + 싱글턴 락 + main. AgentBot 클래스는
             telegram_agent_bot.py로 분리됨.

             [핵심 설계 — "에이전트 = 봇" 패턴]
             - T1~T8 각각 독립된 텔레그램 봇 (BotFather에서 8개 생성)
             - 개인 채팅: claude CLI stream-json 직접 spawn → 실시간 스트리밍
             - 그룹 채팅: 모든 봇이 초대된 공용 공간
               → ITCP 메시지가 발신자 봇의 이름으로 그룹에 표시
               → 봇끼리 대화하듯 보이는 협업 UX
               → 사용자가 관전 + @멘션으로 개입

             [프로세스 구조]
             1개 프로세스에서 asyncio로 최대 8개 봇 동시 구동.
             python-telegram-bot v22의 Application.start() + updater.start_polling()을
             비동기로 병렬 실행합니다.

             [호출자] infra/daemons.py run_telegram_bridge가 이 파일을 스크립트 경로로
             spawn — 진입점 경로(scripts/telegram_bridge.py) 변경 금지.

REVISION HISTORY:
- 2026-07-16 Claude: 1455줄 → AgentBot 클래스를 telegram_agent_bot.py로 분리
  (1500줄 규칙 §2 예방 분할). BotManager의 공유 전역 갱신은 모듈 속성 경유로 전환.
- 2026-03-25 Claude: 동시 입출력 교착(deadlock) 해결 — 3대 병목 제거
  - concurrent_updates(256): 핸들러 병렬 실행 허용 (미설정 시 순차 실행 → 이벤트 루프 차단)
  - stderr=DEVNULL: stderr 버퍼 풀 → 자식 프로세스 block → stdout 멈춤 데드락 근절
  - asyncio.gather(): 봇 폴링 병렬 시작 (순차 await 대비 N배 빠름)
- 2026-03-24 Claude: cokacdir 패턴 적용 — stream-json 직접 spawn 방식으로 전환
- 2026-03-23 Claude: 완전 재설계 — 중계기 패턴 → 에이전트=봇 패턴
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

# 경로 설정: scripts/ 폴더 기준
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"

# ITCP 모듈 임포트
sys.path.insert(0, str(_SCRIPT_DIR))
try:
    import itcp
except ImportError:
    itcp = None  # type: ignore

# 로깅 설정 — telegram_agent_bot의 로거("telegram_bridge")도 이 설정을 공유
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TG] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("telegram_bridge")

# [불변식] TERMINAL_CLI_MAP/GROUP_CHAT_ID의 소유 모듈은 telegram_agent_bot —
# `from ... import`로 값을 가져오면 스냅샷 바인딩이라 갱신이 AgentBot에 안 보임.
# 갱신·조회는 반드시 agent_bot_mod.<이름> 모듈 속성 경유. (.env 로드도 저 모듈이 수행)
import telegram_agent_bot as agent_bot_mod  # noqa: E402 — sys.path 삽입(위) 이후라야 import 가능
from telegram_agent_bot import AgentBot, _get_terminal_cli_map  # noqa: E402
from telegram_helpers import (  # noqa: E402
    SERVER_PORT, MSG_TYPE_EMOJI, _get_emoji, _truncate,
)


# ═══════════════════════════════════════════════════════════════════
#  BotManager — 최대 8봇 생명주기 관리
# ═══════════════════════════════════════════════════════════════════

class BotManager:
    """여러 AgentBot을 asyncio로 동시 구동하고 ITCP 메시지를 그룹채팅에 라우팅.

    [동작 흐름]
    1. .env에서 TELEGRAM_BOT_T1~T8 토큰 로드
    2. 유효한 토큰이 있는 터미널만 AgentBot 생성
    3. asyncio.gather로 모든 봇 + ITCP 폴링 + PTY 폴링 동시 실행

    [ITCP → 그룹채팅 미러링]
    pg_messages에 새 메시지가 오면, 발신자 터미널의 봇이 그룹채팅에 해당 메시지를 자기 이름으로 발화.
    예: Claude(T1)이 Antigravity(T2)에게 보낸 메시지 → T1봇이 그룹에 "T1(Claude): ..." 전송
    이로써 그룹채팅에서 봇끼리 대화하는 것처럼 보입니다.
    """

    def __init__(self):
        self.bots: dict[int, AgentBot] = {}
        # 터미널 번호 → AgentBot 매핑 (발신자 봇 찾기용)
        self._cli_to_bots: dict[str, list[AgentBot]] = defaultdict(list)
        self._last_pg_id: int = 0

    def load_bots(self) -> int:
        """.env에서 봇 토큰 로드, AgentBot 생성. 생성된 봇 수 반환.
        서버에서 실제 실행 중인 CLI 정보를 가져와서 동적 매핑합니다."""
        # 서버에서 실제 터미널 CLI 정보 가져오기 — AgentBot이 읽는 소유 모듈 속성에 대입
        agent_bot_mod.TERMINAL_CLI_MAP = _get_terminal_cli_map()
        log.info(f"  CLI 매핑: {agent_bot_mod.TERMINAL_CLI_MAP}")

        count = 0
        for tid in range(1, 9):
            token = os.environ.get(f"TELEGRAM_BOT_T{tid}", "").strip()
            if token:
                bot = AgentBot(tid, token)
                self.bots[tid] = bot
                self._cli_to_bots[bot.cli].append(bot)
                count += 1
                log.info(f"  봇 로드: T{tid} ({bot.cli}) ✅")
            else:
                log.debug(f"  T{tid} 토큰 미설정 — 스킵")
        return count

    def _refresh_bot_bindings(self) -> None:
        """Refresh bot labels and lookup indexes from the live terminal map."""
        agent_bot_mod.TERMINAL_CLI_MAP = _get_terminal_cli_map()
        self._cli_to_bots = defaultdict(list)
        for tid, bot in self.bots.items():
            bot._apply_cli_binding(agent_bot_mod.TERMINAL_CLI_MAP.get(tid, bot.cli))
            self._cli_to_bots[bot.cli].append(bot)

    def _find_bot_for_agent(self, agent_name: str, terminal_id: str = "") -> Optional[AgentBot]:
        """ITCP 메시지 발신자에 매핑되는 봇 찾기.

        [우선순위]
        1. terminal_id가 명시된 경우 → 해당 터미널의 봇
        2. 에이전트 이름으로 첫 번째 매칭 봇
        3. 없으면 None
        """
        # terminal_id로 직접 매핑
        self._refresh_bot_bindings()
        if terminal_id:
            try:
                tid_num = int(terminal_id.replace("T", "").replace("t", ""))
                if tid_num in self.bots:
                    return self.bots[tid_num]
            except ValueError:
                pass

        # 에이전트 이름으로 매핑
        agent_lower = agent_name.lower()
        candidates = self._cli_to_bots.get(agent_lower, [])
        if candidates:
            return candidates[0]

        # 아무거나 하나
        if self.bots:
            return next(iter(self.bots.values()))
        return None

    async def _poll_itcp_to_group(self) -> None:
        """ITCP 메시지를 폴링 → 발신자 봇이 그룹채팅에 발화.

        [핵심 메커니즘]
        이 루프가 에이전트 간 대화를 그룹채팅에 시각화하는 핵심입니다.
        pg_messages 새 메시지 → 발신자 터미널의 봇을 찾아 → 그 봇이 그룹에 발화
        → 텔레그램에서 봇끼리 대화하는 것처럼 보임
        """
        if not itcp or not agent_bot_mod.GROUP_CHAT_ID:
            log.warning("ITCP 또는 GROUP_CHAT_ID 미설정 — 그룹 미러링 비활성화")
            return

        # 현재 최신 ID부터 시작 (과거 메시지 스킵)
        try:
            history = itcp.history(limit=1)
            if history:
                self._last_pg_id = int(history[0].get("id", 0))
        except Exception:
            pass

        log.info(f"ITCP→그룹 폴링 시작 (last_id={self._last_pg_id})")

        hb_tick = 0  # heartbeat 아웃박스는 2초 틱 15회(≈30초)마다 확인 — psql 호출 절약
        while True:
            try:
                msgs = itcp.history(limit=20)
                new_msgs = [m for m in msgs if int(m.get("id", 0)) > self._last_pg_id]
                new_msgs.sort(key=lambda m: int(m.get("id", 0)))

                for msg in new_msgs:
                    msg_id = int(msg.get("id", 0))
                    if msg_id > self._last_pg_id:
                        self._last_pg_id = msg_id

                    from_agent = msg.get("from_agent", msg.get("from", ""))
                    # 텔레그램 브릿지 자체 메시지는 스킵 (무한 루프 방지)
                    metadata = msg.get("metadata", {}) or {}
                    if from_agent == "telegram_bridge":
                        continue
                    if metadata.get("source") == "telegram":
                        continue

                    to_agent = msg.get("to_agent", "all")
                    terminal_id = msg.get("terminal_id", "")
                    content = msg.get("content", "")
                    msg_type = msg.get("msg_type", msg.get("type", "info"))
                    channel = msg.get("channel", "general")

                    # 텔레그램 응답 채널: 에이전트 응답 → 해당 봇의 개인채팅으로 전달
                    if channel == "telegram_response" and to_agent == "user":
                        target_bot = self._find_bot_for_agent(from_agent, terminal_id)
                        if target_bot and target_bot.private_chat_id:
                            response_text = (
                                f"{target_bot.emoji} *{target_bot.label} 응답:*\n"
                                f"{_truncate(content, 3800)}"
                            )
                            await target_bot.send_to_private(response_text)
                            log.info(f"[{target_bot.label}] 텔레그램 응답 전달 ({len(content)}자)")
                        continue  # 그룹에는 안 보냄

                    # 발신자 봇 찾기
                    sender_bot = self._find_bot_for_agent(from_agent, terminal_id)
                    if not sender_bot:
                        continue

                    # 메시지 포맷팅
                    type_emoji = MSG_TYPE_EMOJI.get(msg_type, "")
                    to_str = ""
                    if to_agent and to_agent != "all":
                        to_str = f" → {_get_emoji(to_agent)} {to_agent}"
                    ch_str = f" [{channel}]" if channel not in ("general", "") else ""

                    formatted = (
                        f"{sender_bot.emoji} *{sender_bot.label}*{to_str}"
                        f"{ch_str} {type_emoji}\n{content}"
                    )

                    # 발신자 봇이 그룹에 발화 → 해당 봇 이름으로 표시
                    await sender_bot.send_to_group(formatted)

            except Exception as e:
                log.error(f"ITCP 그룹 폴링 오류: {e}")

            hb_tick += 1
            if hb_tick >= 15:
                hb_tick = 0
                try:
                    await self._flush_heartbeat_outbox()
                except Exception as e:
                    log.debug(f"heartbeat 아웃박스 방출 오류: {e}")

            await asyncio.sleep(2.0)

    # [WHY] 읽기+클리어를 단일 UPDATE..RETURNING으로 — 별도 SELECT 후 클리어 사이에
    # 데몬이 append하면 유실된다. encode(base64)+개행 제거는 psql CSV가 멀티라인
    # JSON을 따옴표 이스케이프하는 문제 회피 (단일 토큰으로 수신).
    _HB_OUTBOX_SQL = (
        "WITH old AS (SELECT payload->'outbox' AS ob FROM hive_state WHERE state_key='heartbeat') "
        "UPDATE hive_state SET payload = payload || '{\"outbox\": []}'::jsonb, updated_at = now()::text "
        "WHERE state_key='heartbeat' AND COALESCE(payload->'outbox','[]'::jsonb) <> '[]'::jsonb "
        "RETURNING replace(encode(convert_to((SELECT ob::text FROM old), 'UTF8'), 'base64'), E'\\n', '');"
    )

    async def _flush_heartbeat_outbox(self) -> None:
        """자율 heartbeat 데몬의 보고(hive_state 'heartbeat'.outbox)를 그룹채팅으로 방출.

        [제약] 데몬은 상태 전체를 read-modify-write — 클리어와 데몬 저장이 겹치면
        같은 보고가 한 번 더 올 수 있다 (중복 허용이 유실보다 낫다는 선택).
        """
        if not itcp:
            return
        ok, out = itcp._run_psql(self._HB_OUTBOX_SQL)
        if not ok or not out.strip():
            return
        # [함정] --tuples-only여도 psql은 UPDATE 커맨드 태그('UPDATE 0')를 stdout에
        # 남긴다 (실측) — base64 데이터 라인만 골라낸다.
        lines = [ln.strip().strip('"') for ln in out.strip().splitlines()
                 if ln.strip() and not ln.strip().startswith("UPDATE ")]
        if not lines:
            return
        import base64
        try:
            items = json.loads(base64.b64decode(lines[0]).decode("utf-8"))
        except Exception as e:
            log.debug(f"heartbeat 아웃박스 파싱 실패: {e}")
            return
        bot = next(iter(self.bots.values()), None)
        if not bot or not isinstance(items, list):
            return
        for item in items[-10:]:
            text = str((item or {}).get("text", "")).strip()
            if text:
                await bot.send_to_group(f"🫀 *자율 클로드*\n{text}")

    async def run(self) -> None:
        """모든 봇 + 폴링 루프를 asyncio로 동시 실행.

        [실행 구조]
        python-telegram-bot v22에서 여러 Application을 하나의 이벤트 루프에서 실행하려면
        app.initialize() → app.start() → updater.start_polling()을 수동으로 호출하고,
        종료 시 역순으로 정리합니다.
        """
        if not self.bots:
            log.error("활성 봇 없음 — 종료")
            return

        # 1) 모든 봇 초기화 (순차 — 각 봇 내부 상태 셋업)
        for tid, bot in sorted(self.bots.items()):
            await bot.app.initialize()
            await bot.app.start()

        # 2) 모든 봇 폴링을 asyncio.gather로 병렬 시작 — 순차 await 대비 N배 빠름
        async def _start_polling(bot):
            await bot.app.updater.start_polling(drop_pending_updates=True)
            log.info(f"[{bot.label}] 폴링 시작 ✅")

        await asyncio.gather(*[_start_polling(bot) for bot in self.bots.values()])

        # 2) 백그라운드 태스크: ITCP→그룹 미러링 + 대시보드 버스 폴링
        tasks = []
        tasks.append(asyncio.create_task(self._poll_itcp_to_group()))

        # 3) 각 봇별 대시보드 메시지 버스 폴링 (대시보드 → 텔레그램 동기화)
        for tid, bot in sorted(self.bots.items()):
            tasks.append(asyncio.create_task(bot._poll_dashboard_bus()))

        log.info(f"전체 {len(self.bots)}봇 + {len(tasks)} 태스크 실행 중 (대시보드 버스 폴링 포함)")

        # 3) 무한 대기 (Ctrl+C로 종료)
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            # 정리
            log.info("종료 중...")
            for t in tasks:
                t.cancel()
            for tid, bot in sorted(self.bots.items()):
                try:
                    await bot.app.updater.stop()
                    await bot.app.stop()
                    await bot.app.shutdown()
                except Exception:
                    pass
            log.info("종료 완료")


# ═══════════════════════════════════════════════════════════════════
#  메인 실행
# ═══════════════════════════════════════════════════════════════════

_LOCK_PORT = 19876  # 텔레그램 브릿지 싱글턴 포트 (사용하지 않는 포트)
_lock_socket = None

def _acquire_pid_lock() -> bool:
    """포트 바인딩 기반 중복 실행 방지 — OS-level 싱글턴.
    같은 포트에 두 프로세스가 동시에 bind할 수 없으므로 레이스컨디션 완전 차단."""
    import socket
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        _lock_socket.listen(1)
        # PID 파일도 남겨놓음 (서버 코드가 참조)
        pid_file = _DATA_DIR / "telegram_bridge.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))
        return True
    except OSError:
        return False  # 포트 이미 점유됨 = 이미 실행 중


def main() -> None:
    """텔레그램 멀티봇 브릿지 메인 진입점"""
    # 중복 실행 방지 (PID lock)
    if not _acquire_pid_lock():
        print("[telegram_bridge] 이미 실행 중 — 종료")
        sys.exit(0)

    log.info("=" * 55)
    log.info("Vibe Coding Telegram Multi-Bot Bridge")
    log.info(f"  서버: http://127.0.0.1:{SERVER_PORT}")
    log.info(f"  그룹 채팅: {agent_bot_mod.GROUP_CHAT_ID or '미설정'}")
    log.info("=" * 55)

    manager = BotManager()
    count = manager.load_bots()

    if count == 0:
        log.error(
            "활성 봇 없음! .env에 TELEGRAM_BOT_T1~T8 토큰을 설정하세요.\n"
            "  예: TELEGRAM_BOT_T1=123456789:ABCdef...\n"
            "  BotFather에서 /newbot으로 봇 생성 후 토큰을 입력합니다."
        )
        sys.exit(1)

    log.info(f"총 {count}개 봇 로드 완료 — 시작합니다")

    asyncio.run(manager.run())


if __name__ == "__main__":
    main()
