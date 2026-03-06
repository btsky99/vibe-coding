# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/claude_watchdog.py
# 📝 설명: Claude 자율 에이전트 워치독.
#          messages.jsonl을 실시간으로 감시하여 터미널(Claude Code / Gemini)에서
#          보낸 지시를 감지하고, cli_agent.py를 통해 자율 에이전트를 자동 실행합니다.
#          "터미널에서 지시 → 에이전트 자동 동작" 루프의 핵심 연결 고리입니다.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - messages.jsonl 실시간 감시 (1초 폴링)
#   - to: claude / to: agent / to: orchestrator 메시지 자동 감지
#   - cli_agent.run()을 백그라운드 스레드로 실행 (블로킹 방지)
#   - 실행 결과를 messages.jsonl에 응답으로 기록
#   - 중복 실행 방지: 이미 실행 중이면 큐에 대기
# ------------------------------------------------------------------------
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from pathlib import Path

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"
MSG_FILE = DATA_DIR / "messages.jsonl"

# cli_agent.py 임포트 (같은 scripts/ 폴더에 있음)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import cli_agent
    print("✅ cli_agent 모듈 로드 성공")
except ImportError as e:
    print(f"❌ cli_agent 임포트 실패: {e}")
    sys.exit(1)

# ─── 감지 대상 수신자 목록 ────────────────────────────────────────────────────
# messages.jsonl의 'to' 필드가 아래 값이면 에이전트가 처리
AGENT_TARGETS = {'claude', 'agent', 'orchestrator', 'auto'}

# ─── 대기 작업 큐 (실행 중일 때 들어온 요청 보관) ───────────────────────────
_pending_queue: list[dict] = []
_queue_lock = threading.Lock()


def _write_message(from_: str, to: str, content: str, extra: dict = None):
    """messages.jsonl에 메시지를 기록합니다 (에이전트 응답 전송용)."""
    msg = {
        'from': from_,
        'to': to,
        'content': content,
        'ts': datetime.now().isoformat(),
    }
    if extra:
        msg.update(extra)
    try:
        MSG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MSG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"[응답 기록 실패] {e}")


def _run_agent_thread(task: str, from_: str, cli: str = 'auto'):
    """cli_agent.run()을 실행하고 결과를 messages.jsonl에 기록합니다.

    블로킹 작업이므로 반드시 별도 스레드에서 호출해야 합니다.
    완료 후 대기 큐에 다음 작업이 있으면 자동으로 이어서 실행합니다.
    """
    print(f"🤖 에이전트 실행 시작: [{cli}] {task[:60]}...")
    _write_message('agent', from_, f"⚙️ 작업 시작: {task[:100]}", {'status': 'started'})

    try:
        result = cli_agent.run(task=task, cli=cli)
        status = result.get('status', 'done')
        used_cli = result.get('cli', cli)
        lines = result.get('output_lines', [])
        summary = '\n'.join(lines[-5:]) if lines else '(출력 없음)'

        print(f"✅ 에이전트 완료 [{used_cli}]: {status}")
        _write_message(
            'agent', from_,
            f"✅ 완료 [{used_cli}]\n{summary}",
            {'status': status, 'cli': used_cli}
        )
    except Exception as e:
        print(f"❌ 에이전트 실행 오류: {e}")
        _write_message('agent', from_, f"❌ 오류 발생: {e}", {'status': 'error'})

    # ─── 대기 큐 처리: 완료 후 다음 작업 자동 실행 ──────────────────────────
    with _queue_lock:
        if _pending_queue:
            next_task = _pending_queue.pop(0)
            print(f"📋 대기 작업 실행: {next_task['task'][:60]}...")
            t = threading.Thread(
                target=_run_agent_thread,
                args=(next_task['task'], next_task['from'], next_task.get('cli', 'auto')),
                daemon=True
            )
            t.start()


def _dispatch(data: dict):
    """감지된 메시지를 분석하여 에이전트를 실행하거나 큐에 추가합니다."""
    content = data.get('content', '').strip()
    from_ = data.get('from', 'unknown')

    # 빈 메시지 무시
    if not content:
        return

    # [Terminal N] 접두어 제거 (실제 지시 내용만 추출)
    actual_task = content
    if "] " in content:
        actual_task = content.split("] ", 1)[-1].strip()

    # cli 강제 지정 파싱: "!claude 지시내용" 또는 "!gemini 지시내용"
    cli = 'auto'
    if actual_task.startswith('!claude '):
        cli = 'claude'
        actual_task = actual_task[8:].strip()
    elif actual_task.startswith('!gemini '):
        cli = 'gemini'
        actual_task = actual_task[8:].strip()

    print(f"📥 지시 감지 [{from_}→agent | cli={cli}]: {actual_task[:80]}")

    # 현재 실행 중이면 큐에 추가, 아니면 즉시 실행
    with _queue_lock:
        is_running = cli_agent._run_status == 'running'
        if is_running:
            _pending_queue.append({'task': actual_task, 'from': from_, 'cli': cli})
            print(f"⏳ 실행 중 — 대기 큐 추가 (현재 대기: {len(_pending_queue)}개)")
            _write_message('agent', from_, f"⏳ 대기 중 ({len(_pending_queue)}번째)...")
            return

    # 백그라운드 스레드로 실행 (메인 감시 루프 블로킹 방지)
    t = threading.Thread(
        target=_run_agent_thread,
        args=(actual_task, from_, cli),
        daemon=True
    )
    t.start()


def main():
    """messages.jsonl을 실시간 감시하며 에이전트 지시를 처리합니다."""
    print("🤖 Claude 자율 에이전트 워치독 가동...")
    print(f"📂 감시 파일: {MSG_FILE}")
    print(f"🎯 수신 대상: {AGENT_TARGETS}")
    print("─" * 50)

    # 파일이 없으면 생성
    MSG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MSG_FILE.exists():
        MSG_FILE.touch()

    # 기존 내용은 무시하고 새로 들어오는 메시지만 처리
    with MSG_FILE.open('r', encoding='utf-8') as f:
        f.seek(0, os.SEEK_END)
        last_pos = f.tell()

    print(f"✅ 준비 완료. 지시 대기 중... (파일 위치: {last_pos}바이트)")

    while True:
        try:
            curr_size = MSG_FILE.stat().st_size if MSG_FILE.exists() else 0

            if curr_size > last_pos:
                with MSG_FILE.open('r', encoding='utf-8') as f:
                    f.seek(last_pos)
                    lines = f.readlines()
                    last_pos = f.tell()

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 수신 대상 확인
                    to = str(data.get('to', '')).lower()
                    from_ = str(data.get('from', ''))

                    # 에이전트 자신이 보낸 메시지는 무시 (무한 루프 방지)
                    if from_ == 'agent':
                        continue

                    if to in AGENT_TARGETS:
                        _dispatch(data)

            # 파일이 초기화(재시작)된 경우 대응
            elif curr_size < last_pos:
                print("⚠️ 파일 초기화 감지 — 위치 리셋")
                last_pos = 0

        except Exception as e:
            print(f"[워치독 오류] {e}")

        time.sleep(1)


if __name__ == "__main__":
    main()
