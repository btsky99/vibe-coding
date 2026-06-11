"""
FILE: scripts/hive_heartbeat.py
DESCRIPTION: Paperclip 스타일 하트비트 러너 — 에이전트 자율 실행 엔진.
    PostgreSQL LISTEN/NOTIFY로 태스크 할당을 감지하고,
    원자적 체크아웃 → CLI 실행 → 결과 기록의 프로토콜을 자동 수행한다.

REVISION HISTORY:
- 2026-03-30 Claude: 최초 작성 — Paperclip 오케스트레이션 전환
"""

import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

# ── 경로 설정 ────────────────────────────────────────────────────────────────
# pg_store 모듈 임포트를 위해 .ai_monitor 경로 추가
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_AI_MONITOR = _PROJECT_ROOT / '.ai_monitor'
sys.path.insert(0, str(_AI_MONITOR))

try:
    import psycopg2
except ImportError:
    print("[하트비트] psycopg2 미설치 — pip install psycopg2-binary")
    sys.exit(1)

from src.pg_store import (
    ensure_schema,
    atomic_checkout,
    release_checkout,
    find_tasks_for_agent,
    add_task_comment,
    record_heartbeat,
)

# ── 설정 상수 ────────────────────────────────────────────────────────────────
PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')
PG_USER = 'postgres'
MAX_RETRIES = 3          # 태스크 실행 실패 시 최대 재시도 횟수
CLI_TIMEOUT = 120        # CLI 실행 타임아웃 (초)


def _get_pg_db() -> str:
    """현재 프로젝트의 PostgreSQL DB 이름을 반환한다."""
    db = os.environ.get('VIBE_PG_DB', '')
    if db:
        return db
    # PROJECT_ROOT 기반 자동 생성 (server.py와 동일한 로직)
    raw = str(_PROJECT_ROOT).replace(':', '-').replace('\\', '-').replace('/', '-')
    slug = raw.lower().replace('-', '_').replace(' ', '_')
    while '__' in slug:
        slug = slug.replace('__', '_')
    slug = slug.strip('_')
    return f"vibe_{slug}"


def _connect_listen() -> 'psycopg2.connection':
    """LISTEN용 PostgreSQL 연결 생성 — autocommit 모드."""
    conn = psycopg2.connect(
        host='127.0.0.1',
        port=int(PG_PORT),
        user=PG_USER,
        dbname=_get_pg_db(),
    )
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        cur.execute("LISTEN task_assigned;")
    return conn


# ── CLI 어댑터 ───────────────────────────────────────────────────────────────
# Task 9: 각 에이전트 CLI를 실행하고 결과를 반환하는 어댑터

def _run_claude(task: dict, project_dir: str) -> tuple[str, int]:
    """Claude Code CLI로 태스크 실행."""
    prompt = (
        f"다음 태스크를 수행하세요:\n\n"
        f"제목: {task.get('title', '')}\n"
        f"설명: {task.get('description', '')}\n\n"
        f"완료 후 결과를 간단히 요약해주세요."
    )
    try:
        result = subprocess.run(
            ['claude', '--print', '-p', prompt],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=CLI_TIMEOUT,
            cwd=project_dir,
        )
        return result.stdout[:2000], result.returncode
    except FileNotFoundError:
        return "claude CLI를 찾을 수 없습니다", 1
    except subprocess.TimeoutExpired:
        return f"타임아웃 ({CLI_TIMEOUT}초 초과)", 1


def _run_gemini(task: dict, project_dir: str) -> tuple[str, int]:
    """Antigravity CLI(agy)로 태스크 실행 — 어댑터 경유 (gemini CLI는 2026-06-18 종료)."""
    prompt = (
        f"다음 태스크를 수행하세요:\n\n"
        f"제목: {task.get('title', '')}\n"
        f"설명: {task.get('description', '')}"
    )
    try:
        from antigravity_adapter import run_print, AntigravityPrintCaptureError
        try:
            return run_print(prompt, timeout=CLI_TIMEOUT, cwd=project_dir)[:2000], 0
        except AntigravityPrintCaptureError as e:
            # [실측 2026-06-11] agy -p 파이프 캡처 결함 — 작업은 수행됐을 수 있으나
            # 응답 회수 불가. 조용한 빈 성공 대신 명시적 실패로 보고.
            return f"agy 비대화형 캡처 불가: {e}", 1
    except FileNotFoundError:
        return "agy CLI를 찾을 수 없습니다", 1
    except subprocess.TimeoutExpired:
        return f"타임아웃 ({CLI_TIMEOUT}초 초과)", 1


def _run_codex(task: dict, project_dir: str) -> tuple[str, int]:
    """Codex CLI로 태스크 실행."""
    prompt = (
        f"다음 태스크를 수행하세요:\n\n"
        f"제목: {task.get('title', '')}\n"
        f"설명: {task.get('description', '')}"
    )
    try:
        result = subprocess.run(
            ['codex', '--approval-mode', 'full-auto', '-q', prompt],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=CLI_TIMEOUT,
            cwd=project_dir,
        )
        return result.stdout[:2000], result.returncode
    except FileNotFoundError:
        return "codex CLI를 찾을 수 없습니다", 1
    except subprocess.TimeoutExpired:
        return f"타임아웃 ({CLI_TIMEOUT}초 초과)", 1


# 에이전트 이름 → CLI 어댑터 매핑
_ADAPTERS = {
    'claude': _run_claude,
    'claude-T1': _run_claude,
    'gemini': _run_gemini,
    'gemini-T2': _run_gemini,
    'codex': _run_codex,
    'codex-T3': _run_codex,
}


# ── 하트비트 프로토콜 9단계 ──────────────────────────────────────────────────

def _process_task(agent_id: str, task: dict, project_dir: str) -> bool:
    """단일 태스크 처리 — 체크아웃 → 실행 → 결과 기록.

    반환: 성공 여부
    """
    task_id = task['id']
    title = task.get('title', '(제목 없음)')

    # Step 5: 원자적 체크아웃
    checked = atomic_checkout(agent_id, task_id)
    if not checked:
        print(f"  [스킵] {title} — 이미 체크아웃됨")
        return False

    print(f"  [체크아웃] {title}")

    # Step 6: 상태 갱신
    record_heartbeat(agent_id, status='working', current_task=task_id)
    add_task_comment(task_id, agent_id, f"작업 시작: {agent_id}가 체크아웃")

    # Step 7: CLI 실행 (재시도 포함)
    adapter = _ADAPTERS.get(agent_id, _run_claude)
    output, exit_code = '', 1

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"  [실행] 시도 {attempt}/{MAX_RETRIES}...")
        output, exit_code = adapter(task, project_dir)
        if exit_code == 0:
            break
        if attempt < MAX_RETRIES:
            add_task_comment(task_id, agent_id,
                             f"실행 실패 (시도 {attempt}/{MAX_RETRIES}): {output[:200]}")
            time.sleep(5)

    # Step 8: 결과 기록
    if exit_code == 0:
        release_checkout(task_id, new_status='done', result=output[:500])
        add_task_comment(task_id, agent_id, f"완료: {output[:500]}")
        print(f"  [완료] {title}")
    else:
        # 3회 실패 → blocked 전환
        release_checkout(task_id, new_status='blocked', result=f"실패: {output[:300]}")
        add_task_comment(task_id, agent_id,
                         f"실패 (blocked): {MAX_RETRIES}회 시도 후 실패\n{output[:300]}")
        print(f"  [실패→blocked] {title}")

    return exit_code == 0


def heartbeat_cycle(agent_id: str, project_dir: str) -> int:
    """하트비트 한 사이클 — 할당된 태스크를 모두 처리.

    반환: 처리한 태스크 수
    """
    # Step 2: 하트비트 등록
    record_heartbeat(agent_id, status='idle')

    # Step 3-4: 할당된 태스크 조회 (우선순위 순)
    tasks = find_tasks_for_agent(agent_id)
    if not tasks:
        print(f"[{agent_id}] 할당된 태스크 없음 — 대기 복귀")
        return 0

    print(f"[{agent_id}] {len(tasks)}개 태스크 발견")
    processed = 0

    for task in tasks:
        success = _process_task(agent_id, task, project_dir)
        if success:
            processed += 1

    # Step 9: idle 복귀
    record_heartbeat(agent_id, status='idle')
    print(f"[{agent_id}] 사이클 완료 — {processed}/{len(tasks)}개 처리")
    return processed


# ── 메인 루프 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Hive 하트비트 러너')
    parser.add_argument('--agent', required=True, help='에이전트 ID (예: claude-T1)')
    parser.add_argument('--interval', type=int, default=300,
                        help='폴링 간격 (초, 기본 300)')
    parser.add_argument('--project-dir', default=str(_PROJECT_ROOT),
                        help='프로젝트 루트 디렉토리')
    parser.add_argument('--once', action='store_true',
                        help='한 사이클만 실행 후 종료')
    args = parser.parse_args()

    agent_id = args.agent
    interval = args.interval
    project_dir = args.project_dir

    # DB 스키마 초기화
    ensure_schema()
    print(f"[하트비트] {agent_id} 시작 — 간격 {interval}초, 프로젝트 {project_dir}")

    # 단발 실행 모드
    if args.once:
        record_heartbeat(agent_id, status='idle')
        processed = heartbeat_cycle(agent_id, project_dir)
        record_heartbeat(agent_id, status='offline')
        print(f"[하트비트] 단발 실행 완료 — {processed}개 처리")
        return

    # LISTEN 연결
    try:
        listen_conn = _connect_listen()
    except Exception as e:
        print(f"[하트비트] PostgreSQL LISTEN 연결 실패: {e}")
        print("[하트비트] 폴링 모드로 전환...")
        listen_conn = None

    record_heartbeat(agent_id, status='idle')
    print(f"[하트비트] LISTEN 대기 시작{'(NOTIFY)' if listen_conn else '(폴링)'}")

    try:
        while True:
            triggered = False

            # NOTIFY 수신 대기 (또는 타이머 만료)
            if listen_conn:
                try:
                    # select()로 NOTIFY 대기 — interval 초까지만 대기
                    if select.select([listen_conn], [], [], interval) != ([], [], []):
                        listen_conn.poll()
                        while listen_conn.notifies:
                            notify = listen_conn.notifies.pop(0)
                            try:
                                payload = json.loads(notify.payload)
                                # 내 에이전트에게 온 알림인지 확인
                                target = payload.get('agent', '')
                                if target == agent_id or target in ('all', ''):
                                    triggered = True
                                    print(f"[NOTIFY] 태스크 할당: {payload.get('task_id', '?')}")
                            except (json.JSONDecodeError, AttributeError):
                                triggered = True
                except Exception as e:
                    print(f"[하트비트] LISTEN 에러: {e} — 재연결 시도")
                    try:
                        listen_conn.close()
                    except Exception:
                        pass
                    time.sleep(5)
                    try:
                        listen_conn = _connect_listen()
                    except Exception:
                        listen_conn = None
                    continue
            else:
                time.sleep(interval)
                triggered = True

            # 타이머 만료 또는 NOTIFY 수신 → 하트비트 사이클 실행
            if triggered or True:  # 타이머 만료 시에도 실행
                heartbeat_cycle(agent_id, project_dir)

    except KeyboardInterrupt:
        print(f"\n[하트비트] {agent_id} 종료")
    finally:
        record_heartbeat(agent_id, status='offline')
        if listen_conn:
            try:
                listen_conn.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
