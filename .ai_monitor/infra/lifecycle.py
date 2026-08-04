"""
FILE: infra/lifecycle.py
DESCRIPTION: 프로세스 라이프사이클 정리 함수 모음.
             서버 종료 시(atexit / SIGTERM / SIGBREAK) 자식 프로세스, PTY 서버,
             내장 PostgreSQL, PyInstaller 임시 디렉터리를 안전하게 정리합니다.
             server.py에서 분리되어 무상태 함수로 재구성됨 — 모든 외부 상태는
             명시적 인자로 주입받습니다.

REVISION HISTORY:
- 2026-07-09 Claude: heal_broken_mei_at_startup 추가 (v3.7.248) — 종료에만 있던 _MEI 정리를
  부팅 시점에도 걸어, 업데이트/크래시로 남은 깨진 _MEI + 좀비 node 누적을 자가치유.
- 2026-04-20 Claude: server.py L4998~5176 분리 (Task 1.1)
                     원본 함수의 동작/주석 그대로 유지, 글로벌 의존성만 인자화
- 2026-07-06 Claude: 서버 시작 프리로드/복구 2함수 흡수 (Phase 2 Task 13 / R15)
                     load_task_logs_into_thoughts / restore_agent_status_from_db.
                     [제약] early_data_dir는 반드시 caller(server.py) 기준 ./data 경로를
                     주입 — 여기서 __file__로 계산하면 infra/ 경로로 오염됨.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
# [주의] cleanup_child_procs의 for proc 루프는 이 모듈 proc을 지역 shadow하나,
#   그 함수는 subprocess.call만 쓰고 헬퍼를 안 써서 무해(call은 헬퍼 미제공 → 미변환).


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
    자식 프로세스(hive_watchdog 등)는
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
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
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
        # [v3.7.244 사고] stale _MEI를 잠근 좀비 node(PTY 서버)를 먼저 죽여야 rmtree가 실제로 성공.
        # ignore_errors=True rmtree만으로는 잠긴 폴더가 부분 상태로 남아 다음 부팅의 DLL 추출과
        # 충돌한다. 현재 인스턴스 _MEI 소속 node는 보호(exclude).
        try:
            from infra.pty_process import kill_runtime_mei_orphans
            # only_orphans=True: 부모(vibe-coding.exe)가 죽은 진짜 좀비만 정리 →
            # 동시 실행 중인 다른 설치 인스턴스의 살아있는 PTY 서버는 보호.
            kill_runtime_mei_orphans(runtime_dir, exclude_mei=Path(current_mei).name,
                                     only_orphans=True)
        except Exception:
            pass
        for item in runtime_dir.iterdir():
            if item.name.startswith('_MEI') and item.is_dir() and str(item) != current_mei:
                try:
                    shutil.rmtree(str(item), ignore_errors=True)
                    print(f"[cleanup] PyInstaller 임시 디렉터리 삭제: {item.name}")
                except Exception:
                    pass
    except Exception:
        pass


def heal_broken_mei_at_startup() -> None:
    """부팅 초기에 runtime 하위의 '깨진 _MEI'(python DLL 누락) + 그걸 잠근 고아 node를
    선제 청소한다. 종료(atexit)에만 있던 정리를 시작 시점에도 걸어 누적 자가치유.

    [WHY / v3.7.248] cleanup_pyinstaller_temp는 '정상 종료' 때만 돈다 → 업데이트 인수인계나
    크래시로 남은 깨진 _MEI + 좀비 node가 다음 부팅에서 청소되지 않고 누적, "Failed to remove
    temporary directory" 경고와 다음 업데이트의 DLL 추출 충돌을 반복 유발했다. 시작 시점에 한 번
    치유한다. onefile 부트로더는 Python보다 먼저라 '이번 부팅'의 추출 실패는 못 막지만(그건
    updater의 _update.bat 청소가 담당), 누적 잔여물 제거로 재발 확률을 크게 낮춘다.

    [안전/불변식] 현재 실행 인스턴스의 _MEI(_MEIPASS)와 python*.dll이 존재하는 정상 _MEI는
    절대 삭제하지 않는다 — 동시 실행 중인 다른 설치 인스턴스(항상 DLL 보유)를 보호. node kill도
    only_orphans=True(부모 죽은 좀비만)로 살아있는 형제 인스턴스의 PTY 서버를 지킨다.
    """
    if not getattr(sys, 'frozen', False):
        return  # 개발 모드에는 runtime _MEI 자체가 없음
    try:
        import shutil
        current_mei = getattr(sys, '_MEIPASS', '')
        runtime_dir = Path(current_mei).parent if current_mei else None
        if not runtime_dir or not runtime_dir.exists():
            return
        # 1) 깨진 _MEI를 잠근 고아 node 먼저 종료(락 해제) — 살아있는 형제 인스턴스는 보호.
        try:
            from infra.pty_process import kill_runtime_mei_orphans
            kill_runtime_mei_orphans(runtime_dir, exclude_mei=Path(current_mei).name,
                                     only_orphans=True)
        except Exception:
            pass
        # 2) python*.dll 없는 '깨진 _MEI'만 삭제. 정상(DLL 존재) 폴더/현재 폴더는 건드리지 않음.
        for item in runtime_dir.iterdir():
            if not (item.name.startswith('_MEI') and item.is_dir()):
                continue
            if str(item) == current_mei:
                continue
            try:
                has_dll = any(item.glob('python*.dll'))
            except Exception:
                has_dll = True  # 판별 실패 시 보수적으로 보존
            if has_dll:
                continue
            try:
                shutil.rmtree(str(item), ignore_errors=True)
                print(f"[startup-heal] 깨진 PyInstaller 임시 폴더 제거: {item.name}")
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
        proc.run(
            [str(pg_ctl_bin), "stop", "-D", str(pg_data_dir), "-m", "fast"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=10
        )
        print("[PG] PostgreSQL 정상 종료 완료")
    except subprocess.TimeoutExpired:
        # 강제 종료
        try:
            proc.run(
                [str(pg_ctl_bin), "stop", "-D", str(pg_data_dir), "-m", "immediate"],
                capture_output=True, timeout=5
            )
            print("[PG] PostgreSQL 강제 종료 완료")
        except Exception:
            pass
    except Exception as e:
        print(f"[PG] PostgreSQL 종료 실패: {e}")


def load_task_logs_into_thoughts(thought_logs: list, early_data_dir: Path) -> None:
    """서버 시작 시 task_logs.jsonl의 최근 20개 항목을 thought_logs에 미리 로드합니다.
    이렇게 해야 클라이언트 접속 즉시 과거 작업 내역이 사고 패널에 표시됩니다.

    [경로 주의] early_data_dir는 caller(server.py) 기준 ./data 경로를 그대로 받는다.
    원본은 이 함수가 서버 코드 상단(DATA_DIR 미정의 시점)에서 호출돼 __file__로 직접
    경로를 계산했으나, infra로 분리되면서 __file__는 infra/ 경로가 되므로 반드시 주입.
    """
    log_path = early_data_dir / 'task_logs.jsonl'
    if not log_path.exists():
        return
    try:
        lines = [l.strip() for l in log_path.read_text(encoding='utf-8').splitlines() if l.strip()]
        recent = lines[-20:] # 최근 20개만 로드
        for line in recent:
            try:
                obj = json.loads(line)
                thought_logs.append({
                    'agent':     obj.get('agent', 'System'),
                    'thought':   obj.get('task', ''),
                    'tool':      None,
                    'timestamp': obj.get('timestamp', ''),
                    'level':     'info',
                })
            except Exception as e:
                pass  # 개별 task_log 항목 파싱 실패 허용
        print(f"[*] ThoughtTrace: {len(recent)}개 task_logs 항목 사전 로드 완료")
    except Exception as e:
        print(f"[!] ThoughtTrace 사전 로드 실패: {e}")


def restore_agent_status_from_db(agent_status: dict, agent_status_lock, list_agent_status) -> None:
    """서버 시작 시 PostgreSQL agent_heartbeats에서 에이전트 상태를 복구한다.

    재시작해도 이전 에이전트 상태를 유지하여 대시보드가 즉시 현황을 보여준다.
    5분 이상 heartbeat가 없으면 offline으로 표시한다.

    [불변식] agent_status(가변 dict)·락·list_agent_status는 server.py와 동일 identity로
    주입받아 그대로 변형한다 — 사본을 만들면 대시보드가 조용히 빈 값을 표시한다.
    """
    try:
        rows = list_agent_status()
        if not rows:
            return
        now_ts = time.time()
        with agent_status_lock:
            for row in rows:
                agent_id = row.get('agent_id', '')
                if not agent_id:
                    continue
                # last_beat ISO 문자열 → timestamp 변환
                last_beat_str = row.get('last_beat', '')
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_beat_str)
                    last_seen_ts = dt.timestamp()
                except Exception:
                    last_seen_ts = now_ts - 600  # 파싱 실패 시 10분 전으로 설정
                # 5분 이상 지났으면 offline
                age_sec = now_ts - last_seen_ts
                if age_sec > 300:
                    status = 'offline'
                else:
                    status = row.get('status', 'idle')
                agent_status[agent_id] = {
                    'status': status,
                    'task': row.get('current_task'),
                    'last_seen': last_seen_ts,
                    'beat_count': row.get('beat_count', 0),
                }
        print(f"[*] 에이전트 상태 복구 완료: {len(rows)}개 에이전트 (DB → 메모리)")
    except Exception as e:
        print(f"[!] 에이전트 상태 복구 실패 (무시): {e}")
