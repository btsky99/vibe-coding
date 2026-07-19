"""
FILE: api/office_proxy_api.py
DESCRIPTION: 오피스 서버(office_server.py) 프로세스 관리 + HTTP 프록시.
             메인 server.py가 /api/office/* 요청을 받으면 별도 프로세스로 띄운
             오피스 서버로 투명 프록시한다. 오피스 서버 미가동 시 office_api를
             직접 호출하는 폴백 경로 포함. 프로세스 크래시 감지 시 최대 3회 자동 재시작.

REVISION HISTORY:
- 2026-04-20 Claude: server.py L4685~4857 분리 (Task 4.1)
                     OfficeServerState로 모듈 글로벌 캡슐화 + 단일 진입점화
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, parse_qs

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# server.py가 setup() 호출로 office_api 핸들러를 주입한다.
# 직접 import하면 순환 참조 가능 + 일부 API 모듈은 server.py에서 lazy import됨.
_office_api = None


class OfficeServerState:
    """오피스 서버 프로세스/포트 상태 컨테이너."""

    def __init__(
        self,
        *,
        base_dir: Path,
        data_dir: Path,
        http_port_getter: Callable[[], int],
        child_procs: list,
        python_cmd_getter: Callable[[], list[str]],
    ) -> None:
        self.base_dir = base_dir
        self.data_dir = data_dir
        self.http_port_getter = http_port_getter
        self.child_procs = child_procs
        self.python_cmd_getter = python_cmd_getter
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.monitor_running: bool = False

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)


def setup(office_api_module) -> None:
    """server.py에서 office_api 모듈을 주입한다 (폴백 경로용)."""
    global _office_api
    _office_api = office_api_module


def proxy_to_office_server(
    state: OfficeServerState,
    handler,
    method: str = 'GET',
    body: bytes | None = None,
) -> None:
    """오피스 서버로 요청을 투명 프록시한다.

    [2026-04-13] server.py에서 office_api를 직접 호출하던 폴백 코드를 제거하고
    오피스 서버로 프록시하는 방식으로 전환. 중복 코드 제거 + 단일 책임.
    """
    if not state.port:
        # 폴백: 오피스 서버 없으면 office_api를 직접 호출
        parsed = urlparse(handler.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if method == 'GET':
                if _office_api.handle_get(handler, path, params, state.data_dir):
                    return
            elif method == 'POST':
                if _office_api.handle_post(handler, path, state.data_dir):
                    return
            elif method == 'PUT':
                if _office_api.handle_put(handler, path, state.data_dir):
                    return
            elif method == 'DELETE':
                if _office_api.handle_delete(handler, path, state.data_dir):
                    return
        except Exception as e:
            handler.send_response(500)
            handler.send_header('Content-Type', 'application/json;charset=utf-8')
            handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
            handler.end_headers()
            handler.wfile.write(json.dumps({'error': str(e)}, ensure_ascii=False).encode('utf-8'))
            return
        handler.send_response(404)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(b'{"error":"not found"}')
        return

    import urllib.request
    import urllib.error
    target = f'http://127.0.0.1:{state.port}{handler.path}'
    headers = {}
    for key in ('Content-Type', 'Accept', 'Authorization'):
        val = handler.headers.get(key)
        if val:
            headers[key] = val
    try:
        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            ct = resp.headers.get('Content-Type', 'application/octet-stream')
            data = resp.read()
            handler.send_response(resp.status)
            handler.send_header('Content-Type', ct)
            handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
            handler.end_headers()
            handler.wfile.write(data)
    except urllib.error.URLError as e:
        handler.send_response(502)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps(
            {'error': f'office server proxy failed: {e}'},
            ensure_ascii=False,
        ).encode('utf-8'))
    except Exception as e:
        handler.send_response(500)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.end_headers()
        handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))


def launch_office_server(state: OfficeServerState) -> int:
    """office_server.py를 서브프로세스로 시작하고 실제 바인딩 포트를 반환한다.

    stdout 첫 줄에서 'PORT:<N>' 형식으로 포트를 읽는다.
    """
    # 기존 프로세스가 살아있으면 종료 + child_procs에서 제거
    if state.proc:
        try:
            state.child_procs.remove(state.proc)
        except ValueError:
            pass
        if state.proc.poll() is None:
            try:
                state.proc.terminate()
                state.proc.wait(timeout=3)
            except Exception:
                try:
                    state.proc.kill()
                except Exception:
                    pass

    python_cmds = state.python_cmd_getter()
    if not python_cmds:
        raise RuntimeError('Python 인터프리터를 찾을 수 없음')

    office_script = state.base_dir / 'office_server.py'
    state.proc = proc.popen(
        [python_cmds[0], str(office_script),
         '--classic-port', str(state.http_port_getter()),
         '--port-start', '9010'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    state.child_procs.append(state.proc)

    # stdout에서 PORT:<N> 읽기 (최대 5초 대기)
    deadline = time.time() + 5
    while time.time() < deadline:
        line = state.proc.stdout.readline()
        if not line:
            if state.proc.poll() is not None:
                stderr_out = state.proc.stderr.read().decode('utf-8', errors='replace')
                raise RuntimeError(f'오피스 서버 시작 실패: {stderr_out[:500]}')
            time.sleep(0.1)
            continue
        decoded = line.decode('utf-8', errors='replace').strip()
        if decoded.startswith('PORT:'):
            state.port = int(decoded.split(':')[1])
            print(f'[server] 오피스 서버 시작됨: 포트 {state.port}, PID {state.proc.pid}')
            # 남은 stdout을 비동기로 소비 (파이프 막힘 방지)
            threading.Thread(
                target=lambda p: [p.stdout.read() for _ in [None]],
                args=(state.proc,), daemon=True,
            ).start()
            start_office_monitor(state)
            return state.port
        print(f'[office_server] {decoded}')

    raise RuntimeError('오피스 서버 포트 응답 타임아웃 (5초)')


def restart_office_server(state: OfficeServerState) -> int:
    """오피스 서버를 재시작하고 새 포트를 반환한다."""
    return launch_office_server(state)


def start_office_monitor(state: OfficeServerState) -> None:
    """오피스 서버 프로세스 모니터링 스레드. 크래시 감지 시 자동 재시작 (최대 3회)."""
    if state.monitor_running:
        return
    state.monitor_running = True

    def _monitor():
        restart_count = 0
        max_restarts = 3
        while state.monitor_running:
            time.sleep(5)
            if state.proc and state.proc.poll() is not None:
                exit_code = state.proc.returncode
                print(f'[server] ⚠️ 오피스 서버 크래시 감지 (exit={exit_code}), 재시작 {restart_count + 1}/{max_restarts}')
                if restart_count >= max_restarts:
                    print('[server] 오피스 서버 최대 재시작 횟수 초과 — 모니터링 중단')
                    break
                try:
                    restart_office_server(state)
                    restart_count += 1
                    print(f'[server] 오피스 서버 재시작 성공 (포트 {state.port})')
                except Exception as e:
                    print(f'[server] 오피스 서버 재시작 실패: {e}')
                    restart_count += 1
        state.monitor_running = False

    threading.Thread(target=_monitor, daemon=True, name='OfficeMonitor').start()
