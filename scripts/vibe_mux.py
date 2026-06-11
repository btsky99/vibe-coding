# -*- coding: utf-8 -*-
"""
FILE: scripts/vibe_mux.py
DESCRIPTION: cmux-style 터미널 멀티플렉서 — Windows Named Pipe 기반 에이전트 간 텍스트 직접 주입.

    [핵심 설계 원칙 — cmux surface.send_text 모방]
    cmux는 Unix Socket(/tmp/cmux.sock)으로 터미널 간 텍스트를 주입하지만,
    Windows에서는 Named Pipe(\\.\pipe\vibe-mux)를 사용하여 동일한 기능을 구현합니다.

    [아키텍처]
    vibe_mux.py (이 파일) = 중앙 MUX 서버 + CLI
      ├── Named Pipe 서버: \\.\pipe\vibe-mux (제어 채널)
      ├── 터미널 레지스트리: 어떤 에이전트가 어떤 파이프에 연결되어 있는지 추적
      └── JSON 프로토콜: cmux 호환 메서드명 사용

    vibe_mux_agent.py (별도 파일) = 터미널별 수신/실행 루프
      ├── 각 터미널이 \\.\pipe\vibe-mux-T{n} 파이프 생성
      ├── MUX 서버에 자동 등록
      └── 수신한 텍스트를 cli_agent.run()으로 자동 실행

    [프로토콜 — cmux JSON 호환]
    요청: {"id":"req-1", "method":"surface.send_text", "params":{"terminal":"T2", "text":"분석해줘"}}
    응답: {"id":"req-1", "ok":true, "result":{...}}

    [지원 메서드]
    - terminal.register   : 터미널 등록 (에이전트 루프가 호출)
    - terminal.unregister : 터미널 등록 해제
    - terminal.list       : 활성 터미널 목록 조회
    - surface.send_text   : 터미널에 텍스트 전송 (핵심!)
    - surface.send_key    : 터미널에 특수 키 전송 (enter, tab 등)
    - system.ping         : MUX 서버 응답 확인

    [CLI 사용법]
    python scripts/vibe_mux.py server                          # MUX 서버 시작
    python scripts/vibe_mux.py send-text T2 "보안 점검해줘"     # T2에 텍스트 전송
    python scripts/vibe_mux.py send-key T2 enter               # T2에 Enter 키 전송
    python scripts/vibe_mux.py list                            # 활성 터미널 목록
    python scripts/vibe_mux.py ping                            # 서버 상태 확인

REVISION HISTORY:
- 2026-03-18 Claude: 최초 구현 — cmux-style Named Pipe MUX 서버 + CLI (P6 Task 32)
  - Windows Named Pipe 기반 JSON-RPC 서버
  - 터미널 레지스트리 (register/unregister/list)
  - surface.send_text/send_key로 에이전트 간 텍스트 직접 주입
  - CLI 모드: send-text, send-key, list, ping 서브커맨드
"""

from __future__ import annotations

import json
import os
import sys
import time
import struct
import threading
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# ── Named Pipe 설정 ─────────────────────────────────────────────────────────
# 제어 파이프: MUX 서버가 리스닝하는 메인 파이프
MUX_PIPE_NAME = r'\\.\pipe\vibe-mux'
# 터미널별 파이프 패턴: 각 에이전트가 자신의 파이프를 생성
TERMINAL_PIPE_PATTERN = r'\\.\pipe\vibe-mux-{terminal_id}'

# 파이프 버퍼 크기
PIPE_BUFFER_SIZE = 65536
# 클라이언트 연결 타임아웃 (ms)
PIPE_CONNECT_TIMEOUT = 5000

# ── 터미널 레지스트리 ────────────────────────────────────────────────────────
# {terminal_id: {"agent": "claude"|"gemini"|"codex", "pipe": pipe_name, "registered_at": ..., "status": "active"}}
_terminal_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# MUX 서버 — Named Pipe JSON-RPC 서버
# ══════════════════════════════════════════════════════════════════════════════

def _handle_request(request: dict) -> dict:
    """JSON-RPC 요청을 처리하고 응답을 반환합니다.

    [설계 의도] cmux 소켓 API와 동일한 method/params 구조를 사용하여
    향후 cmux와의 호환성을 유지합니다.
    """
    req_id = request.get('id', 'unknown')
    method = request.get('method', '')
    params = request.get('params', {})

    try:
        if method == 'terminal.register':
            return _handle_register(req_id, params)
        elif method == 'terminal.unregister':
            return _handle_unregister(req_id, params)
        elif method == 'terminal.list':
            return _handle_list(req_id, params)
        elif method == 'surface.send_text':
            return _handle_send_text(req_id, params)
        elif method == 'surface.send_key':
            return _handle_send_key(req_id, params)
        elif method == 'system.ping':
            return {'id': req_id, 'ok': True, 'result': {'pong': True, 'ts': datetime.now().isoformat()}}
        else:
            return {'id': req_id, 'ok': False, 'error': f'알 수 없는 메서드: {method}'}
    except Exception as e:
        return {'id': req_id, 'ok': False, 'error': str(e)}


def _handle_register(req_id: str, params: dict) -> dict:
    """터미널을 MUX에 등록합니다.

    [설계 의도] 각 에이전트 터미널이 시작 시 자신을 등록하면,
    다른 에이전트가 send_text로 이 터미널에 텍스트를 주입할 수 있게 됩니다.
    """
    terminal_id = params.get('terminal_id', '')
    agent = params.get('agent', 'unknown')
    pipe_name = params.get('pipe', TERMINAL_PIPE_PATTERN.format(terminal_id=terminal_id))

    if not terminal_id:
        return {'id': req_id, 'ok': False, 'error': 'terminal_id 필수'}

    with _registry_lock:
        _terminal_registry[terminal_id] = {
            'agent': agent,
            'pipe': pipe_name,
            'registered_at': datetime.now().isoformat(),
            'status': 'active',
            'last_activity': datetime.now().isoformat(),
        }

    print(f'[MUX] 터미널 등록: {terminal_id} ({agent}) → {pipe_name}')
    return {'id': req_id, 'ok': True, 'result': {'terminal_id': terminal_id, 'registered': True}}


def _handle_unregister(req_id: str, params: dict) -> dict:
    """터미널 등록을 해제합니다."""
    terminal_id = params.get('terminal_id', '')
    with _registry_lock:
        removed = _terminal_registry.pop(terminal_id, None)

    if removed:
        print(f'[MUX] 터미널 해제: {terminal_id}')
        return {'id': req_id, 'ok': True, 'result': {'terminal_id': terminal_id, 'unregistered': True}}
    return {'id': req_id, 'ok': False, 'error': f'터미널 미등록: {terminal_id}'}


def _handle_list(req_id: str, params: dict) -> dict:
    """활성 터미널 목록을 반환합니다."""
    with _registry_lock:
        terminals = dict(_terminal_registry)
    return {'id': req_id, 'ok': True, 'result': {'terminals': terminals, 'count': len(terminals)}}


def _handle_send_text(req_id: str, params: dict) -> dict:
    """지정된 터미널에 텍스트를 전송합니다.

    [핵심 기능 — cmux surface.send_text 모방]
    이 함수가 vibe_mux의 존재 이유입니다.
    Named Pipe를 통해 대상 터미널의 에이전트 루프에 텍스트를 직접 전달합니다.
    에이전트 루프(vibe_mux_agent.py)는 이 텍스트를 받아 cli_agent.run()으로 실행합니다.
    """
    terminal_id = params.get('terminal', '')
    text = params.get('text', '')
    from_agent = params.get('from', 'mux')
    metadata = params.get('metadata', {})

    if not terminal_id or not text:
        return {'id': req_id, 'ok': False, 'error': 'terminal과 text 파라미터 필수'}

    # 레지스트리에서 대상 터미널의 파이프 이름 조회
    with _registry_lock:
        entry = _terminal_registry.get(terminal_id)

    if not entry:
        return {'id': req_id, 'ok': False, 'error': f'터미널 미등록: {terminal_id}. 활성 터미널: {list(_terminal_registry.keys())}'}

    target_pipe = entry['pipe']

    # Named Pipe를 통해 텍스트 전송
    try:
        result = _send_to_pipe(target_pipe, {
            'type': 'send_text',
            'text': text,
            'from': from_agent,
            'metadata': metadata if isinstance(metadata, dict) else {},
            'ts': datetime.now().isoformat(),
        })

        # 마지막 활동 시간 업데이트
        with _registry_lock:
            if terminal_id in _terminal_registry:
                _terminal_registry[terminal_id]['last_activity'] = datetime.now().isoformat()

        return {'id': req_id, 'ok': True, 'result': {'terminal': terminal_id, 'sent': True, 'text_length': len(text)}}
    except Exception as e:
        # 파이프 연결 실패 시 터미널을 비활성으로 표시
        with _registry_lock:
            if terminal_id in _terminal_registry:
                _terminal_registry[terminal_id]['status'] = 'unreachable'
        return {'id': req_id, 'ok': False, 'error': f'파이프 전송 실패 ({terminal_id}): {e}'}


def _handle_send_key(req_id: str, params: dict) -> dict:
    """지정된 터미널에 특수 키를 전송합니다.

    [설계 의도] cmux의 surface.send_key 모방.
    enter, tab, escape 등의 특수 키를 전송할 수 있습니다.
    """
    terminal_id = params.get('terminal', '')
    key = params.get('key', '')

    # 특수 키 → 이스케이프 시퀀스 매핑
    key_map = {
        'enter': '\n',
        'tab': '\t',
        'escape': '\x1b',
        'backspace': '\x08',
        'delete': '\x7f',
        'up': '\x1b[A',
        'down': '\x1b[B',
        'left': '\x1b[D',
        'right': '\x1b[C',
    }

    if key not in key_map:
        return {'id': req_id, 'ok': False, 'error': f'지원하지 않는 키: {key}. 지원: {list(key_map.keys())}'}

    # send_text와 동일한 경로로 전달
    return _handle_send_text(req_id, {'terminal': terminal_id, 'text': key_map[key]})


# ══════════════════════════════════════════════════════════════════════════════
# Named Pipe I/O — Windows 네이티브 파이프 통신
# ══════════════════════════════════════════════════════════════════════════════

def _send_to_pipe(pipe_name: str, message: dict) -> dict:
    """Named Pipe에 JSON 메시지를 전송하고 응답을 받습니다.

    [설계 의도] Windows Named Pipe 클라이언트.
    대상 터미널의 파이프에 연결 → JSON 전송 → 응답 수신 → 연결 해제.
    타임아웃 5초 내에 응답이 없으면 예외 발생.
    """
    if os.name == 'nt':
        import win32file  # type: ignore
        import win32pipe  # type: ignore
        import pywintypes  # type: ignore

        try:
            # Named Pipe 클라이언트 연결
            handle = win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,     # 공유 모드 없음
                None,  # 보안 속성 기본
                win32file.OPEN_EXISTING,
                0,     # 플래그 없음
                None,  # 템플릿 없음
            )

            # 메시지 전송
            data = json.dumps(message, ensure_ascii=False).encode('utf-8')
            win32file.WriteFile(handle, data)

            # 응답 수신
            _, response_data = win32file.ReadFile(handle, PIPE_BUFFER_SIZE)
            win32file.CloseHandle(handle)

            return json.loads(response_data.decode('utf-8'))

        except pywintypes.error as e:
            raise ConnectionError(f'Named Pipe 연결 실패 ({pipe_name}): {e}')
    else:
        # Linux/Mac: Unix Domain Socket 폴백
        # cmux와 동일한 방식 (향후 macOS 지원용)
        import socket
        sock_path = pipe_name.replace(r'\\.\pipe\\', '/tmp/').replace('\\', '/')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect(sock_path)
            data = json.dumps(message, ensure_ascii=False).encode('utf-8') + b'\n'
            sock.sendall(data)
            response = sock.recv(PIPE_BUFFER_SIZE)
            return json.loads(response.decode('utf-8'))
        finally:
            sock.close()


def _send_to_mux(request: dict) -> dict:
    """MUX 서버(제어 파이프)에 요청을 전송합니다.

    [설계 의도] CLI에서 MUX 서버에 명령을 보내는 클라이언트 함수.
    """
    return _send_to_pipe(MUX_PIPE_NAME, request)


# ══════════════════════════════════════════════════════════════════════════════
# MUX 서버 메인 루프
# ══════════════════════════════════════════════════════════════════════════════

def run_server():
    """MUX Named Pipe 서버를 시작합니다.

    [설계 의도] 메인 파이프(\\.\pipe\vibe-mux)에서 클라이언트 연결을 대기하고,
    JSON 요청을 수신하여 _handle_request()로 처리합니다.
    각 클라이언트 연결은 별도 스레드에서 처리하여 동시 요청을 지원합니다.
    """
    print(f'[MUX] vibe-mux 서버 시작 — pipe: {MUX_PIPE_NAME}')
    print(f'[MUX] cmux-style 터미널 멀티플렉서 (Windows Named Pipe)')
    print(f'[MUX] 대기 중...')

    if os.name == 'nt':
        _run_server_windows()
    else:
        _run_server_unix()


def _run_server_windows():
    """Windows Named Pipe 서버 루프.

    [설계 의도] win32pipe로 Named Pipe 인스턴스를 생성하고,
    ConnectNamedPipe로 클라이언트 연결을 대기합니다.
    연결마다 새 스레드를 생성하여 요청을 처리합니다.
    처리 완료 후 새 파이프 인스턴스를 생성하여 다음 연결을 대기합니다.
    """
    import win32pipe  # type: ignore
    import win32file  # type: ignore
    import pywintypes  # type: ignore

    while True:
        try:
            # Named Pipe 인스턴스 생성
            pipe_handle = win32pipe.CreateNamedPipe(
                MUX_PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                PIPE_BUFFER_SIZE,
                PIPE_BUFFER_SIZE,
                PIPE_CONNECT_TIMEOUT,
                None,  # 보안 속성 기본
            )

            # 클라이언트 연결 대기 (블로킹)
            win32pipe.ConnectNamedPipe(pipe_handle, None)

            # 별도 스레드에서 요청 처리
            t = threading.Thread(
                target=_handle_pipe_client_windows,
                args=(pipe_handle,),
                daemon=True,
            )
            t.start()

        except pywintypes.error as e:
            print(f'[MUX] 파이프 에러: {e}')
            time.sleep(1)
        except KeyboardInterrupt:
            print(f'\n[MUX] 서버 종료')
            break


def _handle_pipe_client_windows(pipe_handle):
    """Windows Named Pipe 클라이언트 요청을 처리합니다.

    [설계 의도] 파이프에서 JSON 데이터를 읽고, _handle_request()로 처리한 뒤,
    응답을 파이프에 쓰고 연결을 닫습니다.
    """
    import win32file  # type: ignore
    import win32pipe  # type: ignore

    try:
        # 요청 데이터 수신
        _, data = win32file.ReadFile(pipe_handle, PIPE_BUFFER_SIZE)
        request = json.loads(data.decode('utf-8'))

        # 요청 처리
        response = _handle_request(request)

        # 응답 전송
        response_data = json.dumps(response, ensure_ascii=False).encode('utf-8')
        win32file.WriteFile(pipe_handle, response_data)

    except Exception as e:
        print(f'[MUX] 클라이언트 처리 에러: {e}')
    finally:
        # 파이프 연결 해제 + 핸들 닫기
        try:
            win32pipe.DisconnectNamedPipe(pipe_handle)
            win32file.CloseHandle(pipe_handle)
        except Exception:
            pass


def _run_server_unix():
    """Unix Domain Socket 서버 루프 (macOS/Linux 폴백).

    [설계 의도] macOS에서는 cmux와 동일한 Unix Socket 방식을 사용합니다.
    """
    import socket

    sock_path = '/tmp/vibe-mux.sock'
    # 기존 소켓 파일 제거
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(5)
    print(f'[MUX] Unix Socket 서버: {sock_path}')

    try:
        while True:
            client, _ = server.accept()
            t = threading.Thread(target=_handle_socket_client, args=(client,), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print(f'\n[MUX] 서버 종료')
    finally:
        server.close()
        os.unlink(sock_path)


def _handle_socket_client(client):
    """Unix Socket 클라이언트 처리."""
    import socket
    try:
        data = client.recv(PIPE_BUFFER_SIZE)
        if data:
            request = json.loads(data.decode('utf-8'))
            response = _handle_request(request)
            client.sendall(json.dumps(response, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        print(f'[MUX] 소켓 클라이언트 에러: {e}')
    finally:
        client.close()


# ══════════════════════════════════════════════════════════════════════════════
# CLI 인터페이스 — cmux 호환 서브커맨드
# ══════════════════════════════════════════════════════════════════════════════

def cli_send_text(terminal: str, text: str) -> None:
    """터미널에 텍스트를 전송합니다 (cmux send-text 호환)."""
    response = _send_to_mux({
        'id': f'cli-{int(time.time())}',
        'method': 'surface.send_text',
        'params': {'terminal': terminal, 'text': text},
    })
    if response.get('ok'):
        print(f'[MUX] ✓ {terminal}에 텍스트 전송 완료 ({len(text)}자)')
    else:
        print(f'[MUX] ✗ 전송 실패: {response.get("error", "알 수 없는 오류")}')


def cli_send_key(terminal: str, key: str) -> None:
    """터미널에 특수 키를 전송합니다."""
    response = _send_to_mux({
        'id': f'cli-{int(time.time())}',
        'method': 'surface.send_key',
        'params': {'terminal': terminal, 'key': key},
    })
    if response.get('ok'):
        print(f'[MUX] ✓ {terminal}에 [{key}] 키 전송 완료')
    else:
        print(f'[MUX] ✗ 키 전송 실패: {response.get("error", "알 수 없는 오류")}')


def cli_list() -> None:
    """활성 터미널 목록을 출력합니다."""
    response = _send_to_mux({
        'id': f'cli-{int(time.time())}',
        'method': 'terminal.list',
        'params': {},
    })
    if response.get('ok'):
        terminals = response['result']['terminals']
        count = response['result']['count']
        print(f'[MUX] 활성 터미널: {count}개')
        if terminals:
            print(f'{"ID":<8} {"에이전트":<10} {"상태":<12} {"등록 시각":<20} {"파이프"}')
            print('─' * 80)
            for tid, info in terminals.items():
                print(f'{tid:<8} {info["agent"]:<10} {info["status"]:<12} {info["registered_at"]:<20} {info["pipe"]}')
        else:
            print('  (등록된 터미널 없음)')
    else:
        print(f'[MUX] ✗ 목록 조회 실패: {response.get("error", "MUX 서버 미실행?")}')


def cli_ping() -> None:
    """MUX 서버 상태를 확인합니다."""
    try:
        response = _send_to_mux({
            'id': f'cli-{int(time.time())}',
            'method': 'system.ping',
            'params': {},
        })
        if response.get('ok'):
            print(f'[MUX] ✓ 서버 응답 OK — {response["result"]["ts"]}')
        else:
            print(f'[MUX] ✗ 서버 응답 이상: {response}')
    except Exception as e:
        print(f'[MUX] ✗ 서버 연결 실패: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# 헬퍼 함수 — 외부 모듈에서 사용
# ══════════════════════════════════════════════════════════════════════════════

def send_text(
    terminal: str,
    text: str,
    *,
    from_agent: str = 'mux',
    metadata: dict | None = None,
) -> dict:
    """프로그래매틱 API: 터미널에 텍스트 전송.

    [설계 의도] 외부 모듈에서 임포트하여 사용하는 프로그래매틱 진입점.
    MUX 서버를 경유하여 대상 터미널에 텍스트를 주입합니다.
    MUX 서버가 미실행이면 ConnectionError를 발생시킵니다.
    """
    return _send_to_mux({
        'id': f'api-{int(time.time())}',
        'method': 'surface.send_text',
        'params': {
            'terminal': terminal,
            'text': text,
            'from': from_agent,
            'metadata': metadata or {},
        },
    })


def list_terminals() -> dict:
    """프로그래매틱 API: 활성 터미널 목록 조회."""
    return _send_to_mux({
        'id': f'api-{int(time.time())}',
        'method': 'terminal.list',
        'params': {},
    })


def is_server_running() -> bool:
    """MUX 서버가 실행 중인지 확인합니다."""
    try:
        response = _send_to_mux({
            'id': 'health',
            'method': 'system.ping',
            'params': {},
        })
        return response.get('ok', False)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 엔트리포인트
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='vibe-mux: cmux-style 터미널 멀티플렉서 (Windows Named Pipe)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python vibe_mux.py server                       # MUX 서버 시작
  python vibe_mux.py send-text T2 "보안 점검해줘"  # T2에 텍스트 전송
  python vibe_mux.py send-key T2 enter            # T2에 Enter 키 전송
  python vibe_mux.py list                         # 활성 터미널 목록
  python vibe_mux.py ping                         # 서버 상태 확인
        """,
    )
    sub = parser.add_subparsers(dest='command')

    # server
    sub.add_parser('server', help='MUX 서버 시작')

    # send-text
    p_send = sub.add_parser('send-text', help='터미널에 텍스트 전송')
    p_send.add_argument('terminal', help='대상 터미널 ID (T1, T2, T3 등)')
    p_send.add_argument('text', help='전송할 텍스트')

    # send-key
    p_key = sub.add_parser('send-key', help='터미널에 특수 키 전송')
    p_key.add_argument('terminal', help='대상 터미널 ID')
    p_key.add_argument('key', help='키 이름 (enter, tab, escape, up, down, left, right)')

    # list
    sub.add_parser('list', help='활성 터미널 목록')

    # ping
    sub.add_parser('ping', help='MUX 서버 상태 확인')

    args = parser.parse_args()

    if args.command == 'server':
        run_server()
    elif args.command == 'send-text':
        cli_send_text(args.terminal, args.text)
    elif args.command == 'send-key':
        cli_send_key(args.terminal, args.key)
    elif args.command == 'list':
        cli_list()
    elif args.command == 'ping':
        cli_ping()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
