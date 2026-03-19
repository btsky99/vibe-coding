# -*- coding: utf-8 -*-
"""
FILE: scripts/vibe_mux_agent.py
DESCRIPTION: 터미널별 MUX 에이전트 — vibe_mux 서버에 등록하고 수신한 명령을 자동 실행하는 루프.

    [핵심 설계 원칙 — cmux pane agent 모방]
    cmux에서 각 터미널 pane은 독립적인 세션으로, MUX가 surface.send_text를 보내면
    해당 pane의 stdin에 텍스트가 직접 주입됩니다.

    이 파일은 Windows Named Pipe를 통해 동일한 동작을 구현합니다:
    1. 자신의 Named Pipe(\\.\pipe\vibe-mux-T{n}) 생성
    2. vibe_mux 서버에 terminal.register로 자동 등록
    3. 파이프에서 명령 수신 → cli_agent.run()으로 자동 실행
    4. 실행 결과를 ITCP로 반환

    [사용법]
    # 백그라운드 스레드로 실행 (cli_agent.py에서 자동 호출)
    from vibe_mux_agent import start_mux_agent
    start_mux_agent('T2', 'gemini')

    # 단독 실행 (테스트용)
    python vibe_mux_agent.py T2 gemini

    [수신 가능한 명령 타입]
    - send_text: 텍스트를 받아 cli_agent.run()으로 실행
    - send_key: 특수 키 수신 (현재는 로그만)
    - shutdown: 에이전트 루프 종료

REVISION HISTORY:
- 2026-03-18 Claude: 최초 구현 — MUX 에이전트 수신/실행 루프 (P6 Task 33)
  - Windows Named Pipe 서버 스레드 (per-terminal)
  - vibe_mux 서버에 자동 등록/해제
  - cli_agent.run() 통합: 수신한 텍스트를 자동으로 에이전트에 전달하여 실행
  - PostgreSQL LISTEN 병행: ITCP 메시지도 자동 수신/실행
  - 결과 ITCP 반환 (auto_dispatcher.report_task_completion)
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ── 상수 ─────────────────────────────────────────────────────────────────────
PIPE_BUFFER_SIZE = 65536
TERMINAL_PIPE_PATTERN = r'\\.\pipe\vibe-mux-{terminal_id}'
MUX_PIPE_NAME = r'\\.\pipe\vibe-mux'

# ── 에이전트 상태 ────────────────────────────────────────────────────────────
_running = False
_terminal_id: str = ''
_agent_name: str = ''
_pipe_thread: Optional[threading.Thread] = None
_itcp_thread: Optional[threading.Thread] = None
# 외부에서 주입 가능한 실행 콜백: (task_text, cli_name) → result_dict
_execute_callback: Optional[Callable] = None


# ══════════════════════════════════════════════════════════════════════════════
# MUX 서버 등록/해제
# ══════════════════════════════════════════════════════════════════════════════

def _register_with_mux(terminal_id: str, agent: str, pipe_name: str) -> bool:
    """vibe_mux 서버에 이 터미널을 등록합니다.

    [설계 의도] MUX 서버가 이 터미널의 존재를 알아야
    다른 에이전트가 send_text로 이 터미널에 텍스트를 보낼 수 있습니다.
    MUX 서버가 미실행이면 False를 반환하고, 에이전트 루프는 계속 실행됩니다
    (파이프 직접 연결도 가능하므로).
    """
    try:
        from vibe_mux import _send_to_mux
        response = _send_to_mux({
            'id': f'register-{terminal_id}',
            'method': 'terminal.register',
            'params': {
                'terminal_id': terminal_id,
                'agent': agent,
                'pipe': pipe_name,
            },
        })
        if response.get('ok'):
            print(f'[MUX-Agent {terminal_id}] MUX 서버에 등록 완료')
            return True
        else:
            print(f'[MUX-Agent {terminal_id}] MUX 등록 실패: {response.get("error")}')
            return False
    except Exception as e:
        print(f'[MUX-Agent {terminal_id}] MUX 서버 연결 실패 (독립 모드로 계속): {e}')
        return False


def _unregister_from_mux(terminal_id: str) -> None:
    """vibe_mux 서버에서 이 터미널을 해제합니다."""
    try:
        from vibe_mux import _send_to_mux
        _send_to_mux({
            'id': f'unregister-{terminal_id}',
            'method': 'terminal.unregister',
            'params': {'terminal_id': terminal_id},
        })
        print(f'[MUX-Agent {terminal_id}] MUX 서버에서 해제 완료')
    except Exception:
        pass  # 서버가 이미 종료된 경우 무시


# ══════════════════════════════════════════════════════════════════════════════
# Named Pipe 리스너 — 수신 루프
# ══════════════════════════════════════════════════════════════════════════════

def _pipe_listener_loop(terminal_id: str, agent: str):
    """Windows Named Pipe 서버 루프 — 이 터미널의 전용 파이프에서 명령을 수신합니다.

    [핵심 동작]
    1. \\.\pipe\vibe-mux-T{n} 파이프 생성
    2. 클라이언트(MUX 서버 또는 직접 연결) 대기
    3. JSON 명령 수신 → _process_command() 실행
    4. 결과를 응답으로 반환
    5. 루프 반복
    """
    global _running
    pipe_name = TERMINAL_PIPE_PATTERN.format(terminal_id=terminal_id)
    print(f'[MUX-Agent {terminal_id}] 파이프 리스너 시작: {pipe_name}')

    if os.name == 'nt':
        _pipe_listener_windows(terminal_id, agent, pipe_name)
    else:
        _pipe_listener_unix(terminal_id, agent, pipe_name)


def _pipe_listener_windows(terminal_id: str, agent: str, pipe_name: str):
    """Windows Named Pipe 서버 구현.

    [설계 의도] 각 연결마다 새 파이프 인스턴스를 생성하여
    동시에 여러 클라이언트가 명령을 보낼 수 있도록 합니다.
    """
    global _running
    import win32pipe  # type: ignore
    import win32file  # type: ignore
    import pywintypes  # type: ignore

    while _running:
        try:
            # Named Pipe 인스턴스 생성 (터미널 전용)
            pipe_handle = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                PIPE_BUFFER_SIZE,
                PIPE_BUFFER_SIZE,
                5000,   # 타임아웃 5초
                None,
            )

            # 클라이언트 연결 대기 (블로킹)
            win32pipe.ConnectNamedPipe(pipe_handle, None)

            # 요청 수신
            _, data = win32file.ReadFile(pipe_handle, PIPE_BUFFER_SIZE)
            command = json.loads(data.decode('utf-8'))

            # 명령 처리
            result = _process_command(terminal_id, agent, command)

            # 응답 전송
            response = json.dumps(result, ensure_ascii=False).encode('utf-8')
            win32file.WriteFile(pipe_handle, response)

            # 파이프 해제
            win32pipe.DisconnectNamedPipe(pipe_handle)
            win32file.CloseHandle(pipe_handle)

        except pywintypes.error as e:
            if not _running:
                break
            # ERROR_PIPE_NOT_CONNECTED (233) — 클라이언트가 이미 끊김, 무시
            if e.winerror != 233:
                print(f'[MUX-Agent {terminal_id}] 파이프 에러: {e}')
            time.sleep(0.5)
        except Exception as e:
            if not _running:
                break
            print(f'[MUX-Agent {terminal_id}] 처리 에러: {e}')
            time.sleep(0.5)


def _pipe_listener_unix(terminal_id: str, agent: str, pipe_name: str):
    """Unix Socket 리스너 (macOS/Linux 폴백)."""
    global _running
    import socket

    sock_path = f'/tmp/vibe-mux-{terminal_id}.sock'
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(3)
    server.settimeout(2.0)

    try:
        while _running:
            try:
                client, _ = server.accept()
                data = client.recv(PIPE_BUFFER_SIZE)
                if data:
                    command = json.loads(data.decode('utf-8'))
                    result = _process_command(terminal_id, agent, command)
                    client.sendall(json.dumps(result, ensure_ascii=False).encode('utf-8'))
                client.close()
            except socket.timeout:
                continue
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)


# ══════════════════════════════════════════════════════════════════════════════
# ITCP 리스너 — PostgreSQL LISTEN/NOTIFY 기반 수신
# ══════════════════════════════════════════════════════════════════════════════

def _itcp_listener_loop(terminal_id: str, agent: str):
    """PostgreSQL LISTEN 기반 ITCP 메시지 자동 수신 루프.

    [설계 의도] Named Pipe가 직접 연결이라면, ITCP는 PostgreSQL을 경유하는 간접 연결입니다.
    MUX 서버가 미실행이더라도 ITCP를 통해 명령을 받을 수 있습니다.
    기존 ITCP의 한계(다음 호출 시에만 수신)를 극복하여 실시간 수신을 구현합니다.
    """
    global _running
    print(f'[MUX-Agent {terminal_id}] ITCP 리스너 시작 (PostgreSQL LISTEN)')

    try:
        # psycopg2로 LISTEN 채널 구독
        import psycopg2  # type: ignore
        import select
        import itcp

        pg_port = os.environ.get('VIBE_PG_PORT', '5433')
        conn = psycopg2.connect(
            host='localhost',
            port=pg_port,
            dbname='postgres',
            user='postgres',
        )
        conn.autocommit = True

        cursor = conn.cursor()
        cursor.execute("LISTEN hive_messages;")
        print(f'[MUX-Agent {terminal_id}] LISTEN hive_messages')

        def _drain_unread() -> None:
            messages = itcp.receive(agent, mark_read=True, my_terminal_id=terminal_id)
            for message in messages:
                if message.get('channel') not in ('task', 'review'):
                    continue
                if message.get('msg_type') != 'request':
                    continue
                metadata = message.get('metadata') if isinstance(message.get('metadata'), dict) else {}
                command = {
                    'type': 'send_text',
                    'text': message.get('content', ''),
                    'from': message.get('from_agent', 'itcp'),
                    'metadata': metadata,
                    'ts': message.get('ts', datetime.now().isoformat()),
                }
                _process_command(terminal_id, agent, command)

        _drain_unread()

        while _running:
            # select()로 알림 대기 (2초 타임아웃)
            if select.select([conn], [], [], 2.0) == ([], [], []):
                continue  # 타임아웃 — 루프 반복

            conn.poll()
            while conn.notifies:
                conn.notifies.pop(0)
            _drain_unread()

        cursor.close()
        conn.close()

    except ImportError:
        print(f'[MUX-Agent {terminal_id}] psycopg2 미설치 — ITCP 리스너 비활성')
    except Exception as e:
        print(f'[MUX-Agent {terminal_id}] ITCP 리스너 에러: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# 명령 처리 — 수신한 명령을 실행
# ══════════════════════════════════════════════════════════════════════════════

def _process_command(terminal_id: str, agent: str, command: dict) -> dict:
    """수신한 명령을 처리합니다.

    [설계 의도] Named Pipe든 ITCP든, 모든 수신 경로가 이 함수로 합류합니다.
    - send_text: 텍스트를 cli_agent.run()으로 전달하여 실행
    - shutdown: 에이전트 루프 종료
    """
    global _running
    cmd_type = command.get('type', '')
    text = command.get('text', '')
    from_agent = command.get('from', 'unknown')
    metadata = command.get('metadata') if isinstance(command.get('metadata'), dict) else {}

    print(f'[MUX-Agent {terminal_id}] 명령 수신: type={cmd_type}, from={from_agent}, text={text[:50]}...')

    if cmd_type == 'shutdown':
        _running = False
        return {'ok': True, 'result': 'shutting_down'}

    if cmd_type == 'send_text' and text:
        return _execute_task(terminal_id, agent, text, from_agent, metadata)

    if cmd_type == 'send_key':
        # 특수 키는 현재 로그만 남김 (향후 확장)
        print(f'[MUX-Agent {terminal_id}] 특수 키 수신: {text}')
        return {'ok': True, 'result': 'key_received'}

    return {'ok': False, 'error': f'알 수 없는 명령 타입: {cmd_type}'}


def _execute_task(
    terminal_id: str,
    agent: str,
    task_text: str,
    from_agent: str,
    task_meta: dict | None = None,
) -> dict:
    """수신한 텍스트를 에이전트 CLI로 실행합니다.

    [핵심 동작 — cmux surface.send_text의 실제 실행부]
    1. 외부 콜백이 등록되어 있으면 콜백 호출 (cli_agent.run() 등)
    2. 콜백이 없으면 cli_agent를 직접 임포트하여 실행
    3. 실행 결과를 ITCP로 반환 (from_agent에게 결과 전달)
    """
    print(f'[MUX-Agent {terminal_id}] 작업 실행 시작: {task_text[:80]}...')

    try:
        # 1. 외부 콜백 사용 (cli_agent.py에서 등록한 경우)
        if _execute_callback:
            result = _execute_callback(task_text, agent)
        else:
            # 2. cli_agent 직접 임포트
            import cli_agent
            result = cli_agent.run(task_text, cli=agent, terminal_id=terminal_id)

        # 3. 실행 결과를 ITCP로 반환
        _report_result(terminal_id, agent, from_agent, task_text, result, task_meta or {})

        print(f'[MUX-Agent {terminal_id}] 작업 완료: status={result.get("status", "?")}')
        return {'ok': True, 'result': {
            'status': result.get('status', 'done'),
            'output_lines': len(result.get('output_lines', [])),
        }}

    except Exception as e:
        print(f'[MUX-Agent {terminal_id}] 실행 에러: {e}')
        return {'ok': False, 'error': str(e)}


def _report_result(
    terminal_id: str,
    agent: str,
    from_agent: str,
    task: str,
    result: dict,
    task_meta: dict,
) -> None:
    """실행 결과를 ITCP로 발신자에게 반환합니다.

    [설계 의도] cmux에서는 결과가 터미널 출력으로 보이지만,
    우리 시스템에서는 ITCP를 통해 발신자에게 구조화된 결과를 전달합니다.
    이를 통해 auto_dispatcher의 fan-in(결과 수집)이 자동으로 동작합니다.
    """
    output_summary = '\n'.join(result.get('output_lines', [])[-10:])  # 마지막 10줄
    reply_to = str(task_meta.get('reply_to') or from_agent or '').strip()
    task_id = str(task_meta.get('task_id') or '').strip()

    try:
        import itcp
        if reply_to and reply_to not in {'mux', 'dispatcher'}:
            itcp.send(
                from_terminal=agent,
                to_terminal=reply_to,
                content=json.dumps({
                    'type': 'task_result',
                    'task': task[:200],
                    'task_id': task_id,
                    'status': result.get('status', 'done'),
                    'output_summary': output_summary[:500],
                    'terminal': terminal_id,
                    'agent': agent,
                }, ensure_ascii=False),
                channel='task',
                msg_type='response',
                terminal_id=terminal_id,
                metadata=task_meta,
            )
    except Exception as e:
        print(f'[MUX-Agent {terminal_id}] ITCP 결과 반환 실패: {e}')

    # task_id가 있는 디스패치 작업만 dispatcher에 완료 보고
    if task_id:
        try:
            from auto_dispatcher import report_task_completion
            report_task_completion(
                task_id=task_id,
                author=agent,
                result_summary=output_summary[:500] or result.get('status', 'done'),
                request_verify=bool(task_meta.get('verifier')),
            )
        except Exception:
            pass  # auto_dispatcher가 없어도 무시


# ══════════════════════════════════════════════════════════════════════════════
# 공개 API — 외부에서 에이전트 루프를 시작/중지
# ══════════════════════════════════════════════════════════════════════════════

def start_mux_agent(
    terminal_id: str,
    agent: str,
    execute_callback: Optional[Callable] = None,
) -> None:
    """MUX 에이전트를 백그라운드 스레드로 시작합니다.

    [사용법]
    from vibe_mux_agent import start_mux_agent
    start_mux_agent('T2', 'gemini')  # T2 터미널에서 gemini 에이전트 루프 시작

    Args:
        terminal_id: 터미널 ID (T1, T2, T3 등)
        agent: 에이전트 이름 (claude, gemini, codex)
        execute_callback: 작업 실행 콜백 함수 (task_text, cli_name) → result_dict
                         미지정 시 cli_agent.run() 사용
    """
    global _running, _terminal_id, _agent_name, _pipe_thread, _itcp_thread, _execute_callback

    if _running:
        print(f'[MUX-Agent] 이미 실행 중: {_terminal_id}')
        return

    _running = True
    _terminal_id = terminal_id
    _agent_name = agent
    _execute_callback = execute_callback

    pipe_name = TERMINAL_PIPE_PATTERN.format(terminal_id=terminal_id)

    # MUX 서버에 등록
    _register_with_mux(terminal_id, agent, pipe_name)

    # Named Pipe 리스너 스레드 시작
    _pipe_thread = threading.Thread(
        target=_pipe_listener_loop,
        args=(terminal_id, agent),
        daemon=True,
        name=f'mux-pipe-{terminal_id}',
    )
    _pipe_thread.start()

    # ITCP 리스너 스레드 시작
    _itcp_thread = threading.Thread(
        target=_itcp_listener_loop,
        args=(terminal_id, agent),
        daemon=True,
        name=f'mux-itcp-{terminal_id}',
    )
    _itcp_thread.start()

    print(f'[MUX-Agent {terminal_id}] 에이전트 루프 시작 ({agent})')
    print(f'[MUX-Agent {terminal_id}]   - Named Pipe: {pipe_name}')
    print(f'[MUX-Agent {terminal_id}]   - ITCP: hive_messages')


def stop_mux_agent() -> None:
    """MUX 에이전트를 중지합니다."""
    global _running

    if not _running:
        return

    _running = False
    _unregister_from_mux(_terminal_id)
    print(f'[MUX-Agent {_terminal_id}] 에이전트 루프 중지')


# ══════════════════════════════════════════════════════════════════════════════
# 엔트리포인트 — 단독 실행 (테스트용)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('사용법: python vibe_mux_agent.py <terminal_id> <agent>')
        print('예시: python vibe_mux_agent.py T2 gemini')
        sys.exit(1)

    tid = sys.argv[1]
    agnt = sys.argv[2]

    start_mux_agent(tid, agnt)

    # 메인 스레드는 Ctrl+C까지 대기
    try:
        while _running:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_mux_agent()
        print('\n[MUX-Agent] 종료')
