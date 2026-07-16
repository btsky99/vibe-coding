"""
FILE: infra/instance_lock.py
DESCRIPTION: 단일 인스턴스 락 획득 + HTTP/WS 서버 포트 확정 로직.
             server.py main() 부팅 시퀀스에서 top-level 함수로 승격됨.
             락은 실행 환경(개발/frozen/smoke)별로 시드를 분리해 동시 기동을
             허용하고, 이미 실행 중이면 기존 창을 Win32 API로 포커스한 뒤
             os._exit(0)으로 새 인스턴스를 즉시 종료한다.

REVISION HISTORY:
- 2026-07-16 Claude: smoke 락 시드에 PID 추가 — 좀비 EXE의 고정 락 포트 영구 점유로
                     후속 smoke 전멸하는 사고 재발 방지 (사용자 싱글턴 의미 불변).
- 2026-07-08 Claude: server.py main() L1697~1779 인스턴스 락 + 포트 확정 블록 분리
                     (Phase 3 R17-2). 로직·주석 verbatim 유지.
                     [불변식] resolve_server_ports가 반환한 (http, ws)를 caller가
                     반드시 모듈 전역 HTTP_PORT/WS_PORT에 재대입해야 한다 — 모듈 스코프
                     소비자(_p_dashboard_launch/_cors_origin/fs_watcher/cleanup 등)가
                     stale 9000/9001을 참조하는 R14 이중전역 버그 재발 방지.
                     [제약] find_free_port는 caller(src.server_utils)가 주입 — infra가
                     server_utils를 역참조하면 import 사이클 위험.
"""
from __future__ import annotations

import hashlib
import os
import socket
import sys
from pathlib import Path


def acquire_single_instance_lock(project_root: Path) -> socket.socket:
    """단일 인스턴스 락을 획득해 락 소켓을 반환한다.

    이미 실행 중이면 기존 창을 포커스하고 os._exit(0)으로 즉시 종료(반환하지 않음).
    반환된 소켓은 caller가 종료 시점에 close() 해야 한다(락 해제).
    """
    # ── 단일 인스턴스 락 (최우선 — ensure_postgres_running 이전) ───────────────
    # [v3.7.179] 단일 인스턴스 전면 전환 — _MAX_INSTANCES 4→1.
    # 더블클릭으로 2개 창이 뜨고, 하나를 닫으면 터미널이 죽는 치명적 UX 버그 해결.
    # 이미 실행 중이면 기존 창을 Win32 API로 포커스하고 새 인스턴스는 즉시 종료.
    # 같은 PROJECT_ROOT라도 개발 모드/설치 EXE/smoke test가 동시에 떠야 하므로
    # 락 시드를 실행 환경별로 분리한다 (v3.7.225)
    _lock_seed = str(project_root)
    if getattr(sys, 'frozen', False):
        _lock_seed = f"{_lock_seed}::frozen"
    if os.environ.get('VIBE_SMOKE_TEST', '').strip() in ('1', 'true', 'on'):
        # [과거사고 2026-07-16] smoke 시드가 고정이라 커널 좀비化된 smoke EXE 1개가
        # 락 포트를 영구 점유 → 이후 모든 smoke가 "이미 실행 중" exit 0으로 오판.
        # smoke는 일회성+포트 자동 스캔(9100~)이라 상호 배제 자체가 불필요 — PID를
        # 섞어 실행마다 고유 락으로 만들어 좀비 내성 확보 (사용자 싱글턴 의미는 불변).
        _lock_seed = f"{_lock_seed}::smoke::{os.getpid()}"
    _proj_hash    = int(hashlib.md5(_lock_seed.encode()).hexdigest()[:4], 16)
    _LOCK_PORT    = 19001 + (_proj_hash % 480)
    _proj_id      = f"{_proj_hash:04x}"

    _lock_sock = None
    try:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _sock.bind(('127.0.0.1', _LOCK_PORT))
        _lock_sock = _sock
    except OSError:
        # 이미 실행 중 — 기존 창을 포커스하고 종료
        print(f"[*] 이미 실행 중인 인스턴스 감지 (락 포트 {_LOCK_PORT})")
        if os.name == 'nt':
            try:
                import ctypes
                _win_title = f"바이브 코딩 [{project_root.name}]"
                _hwnd = ctypes.windll.user32.FindWindowW(None, _win_title)
                if _hwnd:
                    ctypes.windll.user32.ShowWindow(_hwnd, 9)        # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(_hwnd)
                    print(f"[*] 기존 창 포커스 완료: {_win_title}")
                else:
                    print(f"[*] 기존 창을 찾을 수 없습니다 (아직 로딩 중일 수 있음)")
            except Exception as e:
                print(f"[!] 창 포커스 실패: {e}")
        os._exit(0)

    # 좀비 소켓 대비: 락 획득 실패 후 프로세스가 실제로 없으면 강제 회수
    # (위에서 이미 성공했으므로 여기는 도달하지 않음 — 안전장치)

    print(f"[*] 인스턴스 락 확보 (포트 {_LOCK_PORT})")
    return _lock_sock


def resolve_server_ports(find_free_port) -> tuple[int, int]:
    """HTTP/WS 서버 포트를 확정해 (http_port, ws_port)를 반환한다.

    find_free_port: 빈 포트 탐색 함수 (caller가 src.server_utils에서 주입).
    """
    # ── 포트 확정: HTTP 9000, WS 9001 고정 + 충돌 시 대체 탐색 ─────────────────
    # VIBE_PORT_BASE 환경변수가 있으면 해당 포트부터 시작 (smoke test 격리용)
    # 단일 인스턴스이므로 슬롯 기반 분배 불필요. 고정 포트 우선 시도.
    _preferred_http = int(os.environ.get('VIBE_PORT_BASE', '9000'))
    _http_ok = False
    try:
        _test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _test_sock.bind(('127.0.0.1', _preferred_http))
        _test_sock.close()
        _http_ok = True
    except OSError:
        _http_ok = False

    if _http_ok:
        http_port = _preferred_http
    else:
        http_port = find_free_port(9010, max_tries=40)
        print(f"[!] 포트 {_preferred_http} 사용 중 → 대체 포트 {http_port} 사용")

    _preferred_ws = http_port + 1
    _ws_ok = False
    try:
        _test_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _test_sock2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _test_sock2.bind(('127.0.0.1', _preferred_ws))
        _test_sock2.close()
        _ws_ok = True
    except OSError:
        _ws_ok = False

    if _ws_ok:
        ws_port = _preferred_ws
    else:
        ws_port = find_free_port(_preferred_ws + 1, max_tries=40)
        print(f"[!] WS 포트 {_preferred_ws} 사용 중 → 대체 포트 {ws_port} 사용")

    print(f"[*] 서버 포트 확정 — HTTP:{http_port}, WS:{ws_port}")
    return http_port, ws_port
