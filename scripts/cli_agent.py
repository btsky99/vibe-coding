# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/cli_agent.py
# 📝 설명: CLI 오케스트레이터 자율 에이전트 핵심 엔진.
#          Claude Code CLI / Gemini CLI를 비대화형 모드로 실행하여
#          대시보드에서 직접 자율 작업을 수행합니다.
#          도커 없이, API 키 없이, 기존 CLI 도구만 사용합니다.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - CLIAgent 클래스: 라우팅 + subprocess 실행 + 실시간 스트리밍
#   - 키워드 기반 Claude Code / Gemini CLI 자동 선택
#   - agent_runs.jsonl 실행 히스토리 영구 저장
#   - CLI 단독 테스트 지원 (python scripts/cli_agent.py "지시내용")
# ------------------------------------------------------------------------
"""

import os
import sys
import json
import uuid
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
# 이 스크립트는 scripts/ 폴더에 위치하므로, 데이터 디렉토리는 상위 .ai_monitor/data
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"
RUNS_FILE = DATA_DIR / "agent_runs.jsonl"

# ─── 라우팅 키워드 테이블 ─────────────────────────────────────────────────────
# Claude Code CLI: 코드 작성/수정/버그 수정 등 구현 작업
CLAUDE_KEYWORDS = [
    '코드', '구현', '수정', '버그', '파일', '함수', '클래스', '테스트',
    '추가', '삭제', '리팩터', '리팩토링', '컴포넌트', '빌드',
    'code', 'fix', 'implement', 'write', 'create', 'test', 'build',
    'refactor', 'bug', 'error', 'class', 'function', 'component',
]
# Gemini CLI: 설계/분석/검토 등 사고 중심 작업
GEMINI_KEYWORDS = [
    '설계', '분석', '검토', '브레인', '아키텍처', '계획', '문서',
    '리뷰', '평가', '조사', '정리', '요약',
    'design', 'analyze', 'review', 'plan', 'architecture',
    'document', 'research', 'summary', 'evaluate',
]

# ─── 전역 상태 (모듈 레벨 — agent_api.py에서 직접 접근) ──────────────────────
_current_process: subprocess.Popen | None = None  # 현재 실행 중인 subprocess
_output_queue: Queue = Queue()                     # SSE 스트리밍용 출력 큐
_run_status: str = 'idle'                          # idle | running | done | error
_current_run: dict = {}                            # 현재 실행 중인 태스크 정보
_status_lock = threading.Lock()                    # 상태 동시 접근 보호 락


def route_task(task: str) -> str:
    """키워드 분석으로 최적 CLI를 자동 선택합니다.

    판단 기준:
    - Gemini 키워드 수 > Claude 키워드 수 → gemini
    - 그 외 모든 경우 → claude (코딩 작업이 기본)
    반환값: 'claude' | 'gemini'
    """
    task_lower = task.lower()
    claude_score = sum(1 for kw in CLAUDE_KEYWORDS if kw in task_lower)
    gemini_score = sum(1 for kw in GEMINI_KEYWORDS if kw in task_lower)

    if gemini_score > claude_score:
        return 'gemini'
    return 'claude'  # 기본값: Claude Code CLI


def _stream_output(process: subprocess.Popen, run_id: str) -> list[str]:
    """subprocess 출력을 줄 단위로 읽어 전역 큐에 Push합니다.

    프로세스 stdout을 실시간으로 읽어 _output_queue에 넣으면
    SSE 핸들러(/api/events/agent)가 즉시 클라이언트로 전달합니다.
    반환값: 전체 출력 줄 리스트 (저장용)
    """
    global _output_queue
    all_lines = []

    # 시작 이벤트 전송
    _output_queue.put(json.dumps({
        'type': 'started',
        'run_id': run_id,
        'ts': datetime.now().isoformat(),
    }, ensure_ascii=False))

    try:
        for raw_line in iter(process.stdout.readline, b''):
            if raw_line:
                # UTF-8 디코딩 (Windows 환경 cp949 오류 방지)
                line = raw_line.decode('utf-8', errors='replace').rstrip()
                all_lines.append(line)
                # 큐에 출력 이벤트 Push
                _output_queue.put(json.dumps({
                    'type': 'output',
                    'line': line,
                    'ts': datetime.now().isoformat(),
                }, ensure_ascii=False))
    except Exception as e:
        _output_queue.put(json.dumps({
            'type': 'error',
            'line': f'[출력 스트림 오류] {e}',
            'ts': datetime.now().isoformat(),
        }, ensure_ascii=False))

    return all_lines


def run(task: str, cli: str = 'auto', working_dir: str | None = None) -> dict:
    """CLI를 비대화형 모드로 실행하고 결과를 반환합니다.

    백그라운드 스레드에서 호출되어야 합니다 (agent_api.py가 스레드 생성).

    Args:
        task: 실행할 지시 내용
        cli: 'auto' | 'claude' | 'gemini' — auto면 route_task()로 자동 선택
        working_dir: 작업 디렉토리 (None이면 PROJECT_ROOT 사용)

    Returns:
        실행 결과 dict (status, cli, output_lines, run_id 포함)
    """
    global _current_process, _run_status, _current_run, _output_queue

    run_id = str(uuid.uuid4())[:8]
    cwd = working_dir or str(_PROJECT_ROOT)

    # CLI 자동 선택
    if cli == 'auto':
        cli = route_task(task)

    # 상태 업데이트
    with _status_lock:
        _run_status = 'running'
        _current_run = {
            'id': run_id,
            'task': task,
            'cli': cli,
            'ts': datetime.now().isoformat(),
            'cwd': cwd,
        }

    output_lines = []
    status = 'done'

    try:
        # ── CLI별 명령어 구성 ─────────────────────────────────────────────
        if cli == 'claude':
            # Claude Code CLI: -p 플래그로 비대화형(print) 모드 실행
            # --no-stream: 스트리밍 없이 전체 출력 한 번에 (안정성)
            # --dangerously-skip-permissions: 자동 승인 (오케스트레이터 자율 실행)
            cmd = ['claude', '-p', task, '--dangerously-skip-permissions']
        elif cli == 'gemini':
            # Gemini CLI: stdin으로 지시 전달
            # Windows에서 echo | gemini 방식
            cmd = ['gemini', '-p', task]
        else:
            raise ValueError(f'알 수 없는 CLI: {cli}')

        # ── subprocess 실행 ───────────────────────────────────────────────
        # Windows 환경: CREATE_NO_WINDOW로 콘솔 창 팝업 방지
        creationflags = 0
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW

        _current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # stderr를 stdout으로 합쳐서 통합 출력
            cwd=cwd,
            creationflags=creationflags,
        )

        # 실시간 출력 스트리밍 (프로세스 종료까지 블로킹)
        output_lines = _stream_output(_current_process, run_id)
        _current_process.wait()

        # 종료 코드 확인
        if _current_process.returncode != 0:
            status = 'error'

    except FileNotFoundError:
        # CLI 실행 파일을 찾을 수 없음 (설치 안 됨)
        err_msg = f'[오류] {cli} CLI를 찾을 수 없습니다. 설치 여부를 확인하세요.'
        output_lines.append(err_msg)
        _output_queue.put(json.dumps({
            'type': 'output',
            'line': err_msg,
            'ts': datetime.now().isoformat(),
        }, ensure_ascii=False))
        status = 'error'

    except Exception as e:
        err_msg = f'[오류] 실행 실패: {e}'
        output_lines.append(err_msg)
        _output_queue.put(json.dumps({
            'type': 'output',
            'line': err_msg,
            'ts': datetime.now().isoformat(),
        }, ensure_ascii=False))
        status = 'error'

    finally:
        # 상태 업데이트
        with _status_lock:
            _run_status = status
            _current_process = None

        # 완료 이벤트 전송
        _output_queue.put(json.dumps({
            'type': 'done' if status == 'done' else 'error',
            'run_id': run_id,
            'status': status,
            'ts': datetime.now().isoformat(),
        }, ensure_ascii=False))

    result = {
        'id': run_id,
        'task': task,
        'cli': cli,
        'status': status,
        'output_lines': output_lines,
        'ts': _current_run.get('ts', ''),
    }

    # 실행 히스토리 저장
    _save_run(result)
    return result


def stop() -> None:
    """현재 실행 중인 CLI 프로세스를 강제 종료합니다."""
    global _current_process, _run_status

    with _status_lock:
        if _current_process and _current_process.poll() is None:
            try:
                _current_process.terminate()
            except Exception:
                try:
                    _current_process.kill()
                except Exception:
                    pass
        _run_status = 'idle'
        _current_process = None

    # 중단 이벤트 전송
    _output_queue.put(json.dumps({
        'type': 'stopped',
        'line': '[에이전트] 사용자에 의해 실행이 중단되었습니다.',
        'ts': datetime.now().isoformat(),
    }, ensure_ascii=False))


def get_status() -> dict:
    """현재 에이전트 상태를 반환합니다."""
    with _status_lock:
        return {
            'status': _run_status,
            'current': _current_run.copy() if _current_run else None,
        }


def _save_run(result: dict) -> None:
    """실행 결과를 agent_runs.jsonl에 영구 저장합니다.

    출력 줄 수가 많으면 처음 100줄만 저장하여 파일 크기를 제한합니다.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            'id': result['id'],
            'task': result['task'],
            'cli': result['cli'],
            'status': result['status'],
            'ts': result['ts'],
            # 출력은 처음 100줄만 저장 (파일 크기 제한)
            'output_preview': result['output_lines'][:100],
        }
        with open(RUNS_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[cli_agent] 실행 기록 저장 실패: {e}')


def get_recent_runs(limit: int = 20) -> list[dict]:
    """agent_runs.jsonl에서 최근 실행 기록을 반환합니다."""
    if not RUNS_FILE.exists():
        return []
    try:
        lines = RUNS_FILE.read_text(encoding='utf-8').strip().splitlines()
        records = []
        for line in reversed(lines[-limit * 2:]):  # 최근 레코드 우선
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records[:limit]
    except Exception:
        return []


# ─── CLI 단독 테스트 진입점 ───────────────────────────────────────────────────
if __name__ == '__main__':
    """직접 실행 시 테스트 모드:
    python scripts/cli_agent.py "지시내용" [claude|gemini|auto]
    """
    if len(sys.argv) < 2:
        print('사용법: python scripts/cli_agent.py "지시내용" [claude|gemini|auto]')
        sys.exit(1)

    task_input = sys.argv[1]
    cli_choice = sys.argv[2] if len(sys.argv) > 2 else 'auto'

    # 라우팅 결과 먼저 출력
    chosen = route_task(task_input) if cli_choice == 'auto' else cli_choice
    print(f'[cli_agent] 라우팅 결과: {chosen}')
    print(f'[cli_agent] 지시: {task_input}')
    print(f'[cli_agent] 실행 시작...\n{"─" * 50}')

    # 실행 (메인 스레드에서 동기 실행)
    result = run(task_input, cli_choice)

    print(f'\n{"─" * 50}')
    print(f'[cli_agent] 완료: {result["status"]} (ID: {result["id"]})')
    print(f'[cli_agent] 출력 줄 수: {len(result["output_lines"])}')
