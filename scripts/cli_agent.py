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
# [2026-03-04] Claude: [버그수정] Windows shell=True 환경 '중간 멈춤' 버그 수정
#   - stop(): terminate()가 cmd.exe만 종료 → 자식(claude.exe)이 stdout 파이프를 붙들어
#     readline()이 영원히 블로킹되는 문제 수정
#   - Windows: taskkill /F /T 로 프로세스 트리 전체 강제 종료
#   - Linux/Mac: os.killpg로 프로세스 그룹 전체 SIGTERM
# [2026-03-04] Claude: [버그수정] subprocess 파이프 버퍼링으로 중간 출력 뭉침 수정
#   - Popen에 bufsize=0 추가: 파이프 측 버퍼링 비활성화
#   - Windows에서 클라이언트 파이프 버퍼(기본 4KB)로 인해 출력이 몰려 오던 현상 완화
# [2026-03-04] Claude: [버그수정] subprocess 멈춤 시 readline() 영구 블로킹 '중건 멈춤' 버그 수정
#   - run()에 워치독 스레드 추가: MAX_RUN_SECONDS(600초) 초과 시 프로세스 트리 강제 종료
#   - readline()이 블로킹된 상태에서도 EOF를 강제 유도하여 run() 함수 정상 종료 보장
#   - UI에 타임아웃 원인 메시지 출력 (type=error로 SSE 전송)
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
DATA_DIR  = _PROJECT_ROOT / ".ai_monitor" / "data"
RUNS_FILE = DATA_DIR / "agent_runs.jsonl"
# 포트 9000 자율 에이전트 UI가 tail하는 실시간 라이브 로그 파일
LIVE_FILE = DATA_DIR / "agent_live.jsonl"

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


def _stream_output(process: subprocess.Popen, run_id: str, cli: str = '') -> list[str]:
    """subprocess 출력을 줄 단위로 읽어 전역 큐에 Push합니다.

    프로세스 stdout을 실시간으로 읽어 _output_queue에 넣으면
    SSE 핸들러(/api/events/agent)가 즉시 클라이언트로 전달합니다.
    반환값: 전체 출력 줄 리스트 (저장용)
    """
    global _output_queue
    all_lines = []

    def _write_live(event: dict):
        """agent_live.jsonl에 이벤트를 기록합니다 (포트 9000 UI용)."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with LIVE_FILE.open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
        except Exception:
            pass  # 라이브 파일 기록 실패는 무시 (메인 흐름 영향 없음)

    # 시작 이벤트 전송 + 파일 기록
    # cli 필드 포함: 프론트엔드 AgentPanel이 activeCli 표시에 사용
    start_event = {
        'type': 'started',
        'run_id': run_id,
        'cli': cli,
        'ts': datetime.now().isoformat(),
    }
    _output_queue.put(json.dumps(start_event, ensure_ascii=False))
    _write_live(start_event)

    try:
        for raw_line in iter(process.stdout.readline, b''):
            if raw_line:
                # UTF-8 디코딩 (Windows 환경 cp949 오류 방지)
                line = raw_line.decode('utf-8', errors='replace').rstrip()
                all_lines.append(line)
                # 큐에 출력 이벤트 Push + 라이브 파일 기록
                out_event = {
                    'type': 'output',
                    'line': line,
                    'run_id': run_id,
                    'ts': datetime.now().isoformat(),
                }
                _output_queue.put(json.dumps(out_event, ensure_ascii=False))
                _write_live(out_event)
    except Exception as e:
        err_event = {
            'type': 'error',
            'line': f'[출력 스트림 오류] {e}',
            'run_id': run_id,
            'ts': datetime.now().isoformat(),
        }
        _output_queue.put(json.dumps(err_event, ensure_ascii=False))
        _write_live(err_event)

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
    _was_stopped = False  # stop() 호출 여부 추적 플래그

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
        # shell=True: Windows에서 .cmd 확장자(claude.cmd, gemini.cmd 등 npm 설치 CLI)를
        #             PATH에서 찾으려면 shell=True가 필요함. 리스트를 문자열로 변환 필요.
        creationflags = 0
        use_shell = False
        if os.name == 'nt':
            creationflags = subprocess.CREATE_NO_WINDOW
            use_shell = True
            cmd = subprocess.list2cmdline(cmd)  # 리스트 → 문자열 (shell=True용)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,  # 자식 프로세스가 stdin 대기로 블로킹되는 현상 방지
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # stderr를 stdout으로 합쳐서 통합 출력
            cwd=cwd,
            creationflags=creationflags,
            shell=use_shell,
            bufsize=0,  # 파이프 버퍼링 비활성화 — Windows에서 중간 출력이 뭉쳐 오는 현상 방지
        )
        _current_process = proc  # 전역에 등록 (stop()이 이 참조로 kill)

        # ── 워치독 타이머: 최대 실행 시간(10분) 초과 시 프로세스 자동 종료 ──────
        # readline()이 subprocess 멈춤으로 영원히 블로킹되는 '중간 멈춤' 버그 방지.
        # 10분 내 완료되지 않으면 프로세스 트리 전체를 kill하여 readline()의 EOF를 강제 유도.
        MAX_RUN_SECONDS = 600  # 10분 — 대부분의 Claude/Gemini 작업에 충분한 시간

        def _watchdog(target_proc: subprocess.Popen, rid: str) -> None:
            """MAX_RUN_SECONDS 후에도 프로세스가 살아있으면 강제 종료합니다."""
            import time as _time
            _time.sleep(MAX_RUN_SECONDS)
            # 아직 실행 중인지 확인 (정상 완료 후 워치독이 깨어나는 경우 무시)
            if target_proc.poll() is not None:
                return
            # 타임아웃 오류 메시지를 큐에 추가 (UI에 타임아웃 사유 표시)
            _output_queue.put(json.dumps({
                'type': 'error',
                'line': f'[워치독] 최대 실행 시간({MAX_RUN_SECONDS // 60}분) 초과 — 프로세스를 강제 종료합니다.',
                'run_id': rid,
                'ts': datetime.now().isoformat(),
            }, ensure_ascii=False))
            # stop()과 동일한 방식으로 프로세스 트리 전체 종료
            try:
                if os.name == 'nt':
                    subprocess.call(
                        ['taskkill', '/F', '/T', '/PID', str(target_proc.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    import signal as _sig
                    os.killpg(os.getpgid(target_proc.pid), _sig.SIGTERM)
            except Exception:
                try:
                    target_proc.kill()
                except Exception:
                    pass

        # 워치독 스레드는 daemon=True — 메인 프로세스 종료 시 자동 소멸
        watchdog_thread = threading.Thread(
            target=_watchdog,
            args=(proc, run_id),
            daemon=True,
            name=f'watchdog-{run_id}',
        )
        watchdog_thread.start()

        # 실시간 출력 스트리밍 (프로세스 종료까지 블로킹)
        # 로컬 변수 proc 사용 — stop()이 전역 _current_process를 None으로 설정해도
        # AttributeError 없이 wait() / returncode 접근 가능
        output_lines = _stream_output(proc, run_id, cli)
        proc.wait()

        # 종료 코드 확인 (stop()으로 kill된 경우 returncode는 음수/1로 반환됨)
        if proc.returncode != 0:
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
        # stop()이 먼저 호출된 경우 _run_status == 'idle'로 설정되어 있음
        # done/error로 덮어씌우지 않아야 UI가 idle 상태를 유지함
        with _status_lock:
            _was_stopped = (_run_status == 'idle')
            if not _was_stopped:
                _run_status = status
            _current_process = None

        final_status = 'stopped' if _was_stopped else status

        # stop() 호출 시에는 done 이벤트를 보내지 않음
        # (stopped 이벤트가 이미 전송됐으므로 done이 추가되면 UI 상태가 혼란스러움)
        if not _was_stopped:
            done_event = {
                'type': 'done',
                'run_id': run_id,
                'task': task,
                'cli': cli,
                'status': status,
                'ts': datetime.now().isoformat(),
            }
            _output_queue.put(json.dumps(done_event, ensure_ascii=False))
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with LIVE_FILE.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(done_event, ensure_ascii=False) + '\n')
            except Exception:
                pass

        # 히스토리 저장 (중단된 경우도 'stopped' 상태로 기록)
        result = {
            'id': run_id,
            'task': task,
            'cli': cli,
            'status': final_status,
            'output_lines': output_lines,
            'ts': _current_run.get('ts', ''),
        }
        _save_run(result)

    return result  # type: ignore[return-value]


def stop() -> None:
    """현재 실행 중인 CLI 프로세스를 강제 종료합니다.

    Windows shell=True 환경에서는 cmd.exe → claude.exe 트리 구조가 형성됩니다.
    terminate()는 cmd.exe만 종료하고 자식(claude.exe 등)이 stdout 파이프를 붙들어
    readline()이 영원히 블로킹되는 '중간 멈춤' 버그가 발생합니다.
    → taskkill /F /T 로 프로세스 트리 전체를 강제 종료합니다.

    [수정] subprocess.call(taskkill)을 Lock 밖에서 실행:
    Lock 안에서 블로킹 시스템 콜을 수행하면 run() finally 블록의 Lock 획득이
    지연되어 상태 업데이트가 늦어지는 잠금 경쟁 문제가 발생합니다.
    → Lock 안에서는 proc 참조와 상태만 변경하고, Lock 밖에서 실제 kill 수행.
    """
    global _current_process, _run_status

    # Lock 안에서는 상태 예약과 proc 참조 획득만 수행 (블로킹 작업 금지)
    with _status_lock:
        proc = _current_process
        _run_status = 'idle'
        _current_process = None

    # Lock 해제 후 실제 프로세스 종료 (blocking 작업이므로 Lock 밖에서)
    if proc and proc.poll() is None:
        try:
            if os.name == 'nt':
                # Windows: /F 강제 종료, /T 자식 프로세스 트리 전체 종료
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                # Linux/Mac: 프로세스 그룹 전체에 SIGTERM
                import signal as _signal
                os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
        except Exception:
            # fallback: 직접 kill
            try:
                proc.kill()
            except Exception:
                pass

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
