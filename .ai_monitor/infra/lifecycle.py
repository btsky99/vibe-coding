"""
FILE: infra/lifecycle.py
DESCRIPTION: 프로세스 라이프사이클 정리 함수 모음.
             서버 종료 시(atexit / SIGTERM / SIGBREAK) 자식 프로세스, PTY 서버,
             내장 PostgreSQL, PyInstaller 임시 디렉터리를 안전하게 정리합니다.
             server.py에서 분리되어 무상태 함수로 재구성됨 — 모든 외부 상태는
             명시적 인자로 주입받습니다.

REVISION HISTORY:
- 2026-04-20 Claude: server.py L4998~5176 분리 (Task 1.1)
                     원본 함수의 동작/주석 그대로 유지, 글로벌 의존성만 인자화
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def graceful_shutdown_pty_server(ws_port: int) -> None:
    """Node PTY 서버에 graceful shutdown 요청을 보냅니다.

    [2026-04-07] taskkill /F로 Node PTY 서버를 강제 종료하면 PTY가 생성한
    conhost.exe/cmd.exe 셸 프로세스가 고아가 되어 빈 터미널 창이 여러 개 나타나는
    치명적 UX 버그가 있었습니다.
    /api/pty/shutdown 엔드포인트를 먼저 호출하여 Node 측에서 모든 PTY 세션을
    정리(pty.kill())한 뒤 프로세스를 스스로 종료하도록 합니다.
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            f'http://127.0.0.1:{ws_port}/api/pty/shutdown',
            method='POST',
            data=b'{}',
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=2)
        # Node 프로세스가 자체 종료될 시간 확보 (300ms setTimeout + 여유)
        time.sleep(0.5)
        print("[cleanup] PTY 서버 graceful shutdown 완료")
    except Exception as e:
        print(f"[cleanup] PTY 서버 graceful shutdown 실패 (무시, 강제종료로 폴백): {e}")


def cleanup_child_procs(child_procs: list, ws_port: int) -> None:
    """child_procs 목록에 등록된 모든 서브프로세스를 강제 종료합니다.

    Windows 환경에서 부모 프로세스가 os._exit(0)으로 종료돼도
    자식 프로세스(hive_watchdog, telegram_bridge 등)는
    자동으로 죽지 않아 좀비로 남습니다.
    'taskkill /F /T /PID'로 프로세스 트리 전체를 강제 종료합니다.

    [2026-04-07] PTY 서버는 먼저 graceful shutdown → 나머지 프로세스 강제 종료.
    """
    # PTY 서버 graceful shutdown 먼저 시도 (고아 터미널 창 방지)
    graceful_shutdown_pty_server(ws_port)

    for proc in list(child_procs):
        if proc is None:
            continue
        try:
            if proc.poll() is not None:
                # 이미 종료된 프로세스는 건너뜀
                continue
            if os.name == 'nt':
                # /F: 강제, /T: 자식 트리 포함
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
            else:
                import signal as _sig
                try:
                    os.killpg(os.getpgid(proc.pid), _sig.SIGTERM)
                except Exception:
                    proc.kill()
            print(f"[cleanup] 자식 프로세스 종료: PID {proc.pid}")
        except Exception as e:
            print(f"[cleanup] 자식 프로세스 종료 실패 (PID {getattr(proc, 'pid', '?')}): {e}")
    child_procs.clear()


def cleanup_pyinstaller_temp() -> None:
    """PyInstaller EXE 종료 시 남은 _MEI* 임시 디렉터리를 정리합니다.
    자식 프로세스(node.exe 등)가 파일을 잡고 있으면 삭제 실패 → 다음 실행 시 Warning 팝업 발생.
    cleanup_child_procs() 호출 후 실행해야 파일 핸들이 해제된 상태에서 삭제 가능."""
    if not getattr(sys, 'frozen', False):
        return  # 개발 모드에서는 스킵
    try:
        import shutil
        # PyInstaller _MEIPASS: 현재 실행 중인 임시 디렉터리
        current_mei = getattr(sys, '_MEIPASS', '')
        runtime_dir = Path(current_mei).parent if current_mei else None
        if not runtime_dir or not runtime_dir.exists():
            return
        for item in runtime_dir.iterdir():
            if item.name.startswith('_MEI') and item.is_dir() and str(item) != current_mei:
                try:
                    shutil.rmtree(str(item), ignore_errors=True)
                    print(f"[cleanup] PyInstaller 임시 디렉터리 삭제: {item.name}")
                except Exception:
                    pass
    except Exception:
        pass


def cleanup_postgres(
    pg_ctl_bin: Path,
    pg_data_dir: Path,
    pg_port: int,
    pg_pool: list,
    pg_pool_lock,
) -> None:
    """내장 PostgreSQL 인스턴스를 pg_ctl stop으로 정상 종료합니다.

    [2026-04-06] 프로그램 종료 후 PG가 좀비로 남아 다음 실행 시 pgdata 락 충돌로
    서버가 시작 불가했던 버그 수정. atexit + 시그널 핸들러에서 호출.
    [2026-04-07] 다른 인스턴스(개발용/설치용)가 PG를 공유 사용 중이면 종료 스킵.
    """
    if not pg_ctl_bin.exists():
        return
    if not pg_data_dir.exists():
        return
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

    # ── 자기 인스턴스의 커넥션 풀 먼저 정리 ──
    # 풀에 남은 연결이 pg_stat_activity에 잡혀 "다른 인스턴스 있음"으로 오판 방지
    try:
        with pg_pool_lock:
            for conn, _db in pg_pool:
                try:
                    conn.close()
                except Exception:
                    pass
            pg_pool.clear()
    except Exception:
        pass

    # ── 다른 인스턴스가 PG를 사용 중인지 확인 (공유 PG 보호) ──
    # 개발 버전과 설치 버전이 동일 pgdata(%APPDATA%\VibeCoding\pgdata)를 공유하므로,
    # 한쪽이 종료할 때 다른 쪽의 DB 연결이 끊기는 치명적 버그 방지.
    try:
        import psycopg2 as _pg2
        _chk_conn = _pg2.connect(host='127.0.0.1', port=int(pg_port),
                                 user='postgres', dbname='postgres')
        _chk_conn.autocommit = True
        _cur = _chk_conn.cursor()
        # 자기 백엔드를 제외한 클라이언트 연결 수 확인 (다른 인스턴스의 커넥션 풀 포함)
        # backend_type='client backend' 필터로 autovacuum 등 PG 내부 워커 제외
        _cur.execute("SELECT count(*) FROM pg_stat_activity "
                     "WHERE pid != pg_backend_pid() "
                     "AND backend_type = 'client backend'")
        _total = _cur.fetchone()[0]
        _cur.close()
        _chk_conn.close()
        if _total > 0:
            print(f"[PG] 다른 연결 {_total}개 존재 → PG 종료 스킵 (개발/설치 버전 공유 보호)")
            return
    except Exception:
        pass  # psycopg2 없거나 연결 실패 → PG가 이미 죽었거나 외부 PG → 종료 시도

    try:
        # fast 모드: 클라이언트 연결 즉시 끊고 종료 (smart보다 빠름)
        subprocess.run(
            [str(pg_ctl_bin), "stop", "-D", str(pg_data_dir), "-m", "fast"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window, timeout=10
        )
        print("[PG] PostgreSQL 정상 종료 완료")
    except subprocess.TimeoutExpired:
        # 강제 종료
        try:
            subprocess.run(
                [str(pg_ctl_bin), "stop", "-D", str(pg_data_dir), "-m", "immediate"],
                capture_output=True, creationflags=_no_window, timeout=5
            )
            print("[PG] PostgreSQL 강제 종료 완료")
        except Exception:
            pass
    except Exception as e:
        print(f"[PG] PostgreSQL 종료 실패: {e}")
