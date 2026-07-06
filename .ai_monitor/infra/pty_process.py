"""
FILE: infra/pty_process.py
DESCRIPTION: Node.js PTY 서버 프로세스 관리 함수 모음.
             좀비 PTY 정리, node-pty 네이티브 모듈 빌드 검증, PTY 서버 기동,
             헬스체크 워치독 루프를 담당한다. server.py main() 내부 nested 클로저에서
             top-level 무상태 함수로 승격됨 — 캡처하던 외부 상태(BASE_DIR/WS_PORT/
             HTTP_PORT/PROJECT_ROOT/_child_procs/_pty_server_state 등)를 모두 명시적
             인자로 주입받는다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py main() 내부 PTY 관리 nested 클로저 5개를 분리
                     (Phase 2 Task 11 / R10). 로직·주석 verbatim 유지, 시그니처만
                     파라미터 주입형으로 전환. _pty_server_state(가변 dict)는 워치독과
                     start가 동일 dict를 공유해야 하므로 재생성 금지 — 반드시 caller가
                     주입한 동일 객체를 그대로 변형(mutate)한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request


def get_node_pty_sessions(rest_url: str | None) -> dict:
    """Node PTY 서버에서 세션 정보를 REST로 조회합니다.

    [주의] rest_url은 call-time에 caller(server.py 모듈 전역 _NODE_PTY_REST_URL)가
    넘긴 값을 그대로 사용한다 — 원본이 모듈 전역을 호출 시점에 읽던 의미를 보존.
    """
    if not rest_url:
        return {}
    try:
        req = urllib.request.Request(f"{rest_url}/api/pty/sessions")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return {}


def kill_orphan_pty_servers(pty_server_state: dict) -> None:
    """시작 전 **자기 포트의** 좀비 PTY 서버 프로세스만 정리합니다.
    [수정 2026-03-25 v3.7.122] 기존: 모든 pty-server.js를 무차별 kill → 다른 인스턴스
    (개발용/설치버전)의 PTY 서버까지 죽여서 터미널 전부 사망하는 버그.
    수정: WMIC CommandLine에서 PTY_PORT 환경변수를 확인하여 자기 WS 포트와
    동일한 PTY 서버만 정리. 다른 인스턴스의 PTY 서버는 건드리지 않음."""
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        # CommandLine + ProcessId를 함께 조회하여 포트 기반 필터링
        result = subprocess.run(
            ['wmic', 'process', 'where',
             "CommandLine like '%pty-server.js%' and Name='node.exe'",
             'get', 'ProcessId,CommandLine', '/FORMAT:LIST'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', creationflags=_no_window, timeout=5
        )
        # /FORMAT:LIST 출력: CommandLine=... \n ProcessId=... 쌍으로 파싱
        _current_pid = None
        _current_cmdline = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("CommandLine="):
                _current_cmdline = line[len("CommandLine="):]
            elif line.startswith("ProcessId="):
                _current_pid = line[len("ProcessId="):].strip()
                # 쌍이 완성됨 — 자기 포트인지 확인 후 kill
                if _current_pid and _current_pid.isdigit():
                    # PTY_PORT=<WS_PORT> 환경변수가 커맨드라인에 직접 나타나지 않으므로
                    # 자기 인스턴스의 PTY 서버 PID와 비교하여 남의 것은 보호
                    _my_pty_pid = (pty_server_state.get('proc').pid
                                   if pty_server_state.get('proc') and
                                   pty_server_state['proc'].poll() is None
                                   else None)
                    target_pid = int(_current_pid)
                    if _my_pty_pid and target_pid == _my_pty_pid:
                        # 자기 PTY 서버 — kill 대상
                        pass
                    elif _my_pty_pid and target_pid != _my_pty_pid:
                        # 다른 인스턴스의 PTY — 보호
                        print(f"[PTY Cleanup] PID {target_pid}는 다른 인스턴스 소유 → 보호 (자기 PID: {_my_pty_pid})")
                        _current_pid = None
                        _current_cmdline = ""
                        continue
                    # _my_pty_pid가 None인 경우(최초 시작): 부모 프로세스 확인
                    elif _my_pty_pid is None:
                        # 부모 PID를 확인하여 자기 자식인지 판별
                        try:
                            ppid_res = subprocess.run(
                                ['wmic', 'process', 'where',
                                 f'ProcessId={target_pid}',
                                 'get', 'ParentProcessId', '/FORMAT:LIST'],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', creationflags=_no_window, timeout=3
                            )
                            for ppid_line in ppid_res.stdout.splitlines():
                                ppid_line = ppid_line.strip()
                                if ppid_line.startswith("ParentProcessId="):
                                    parent_pid = int(ppid_line.split("=")[1].strip())
                                    if parent_pid != os.getpid():
                                        # 부모가 다른 프로세스 → 다른 인스턴스 소유
                                        print(f"[PTY Cleanup] PID {target_pid}(부모: {parent_pid})는 "
                                              f"다른 인스턴스 소유 → 보호 (자기 PID: {os.getpid()})")
                                        target_pid = None
                                        break
                        except Exception:
                            # 부모 확인 실패 시 안전하게 건너뜀 (다른 인스턴스 보호 우선)
                            print(f"[PTY Cleanup] PID {_current_pid} 부모 확인 실패 → 보호 (안전 우선)")
                            target_pid = None

                    if target_pid is not None:
                        try:
                            subprocess.run(
                                ['taskkill', '/F', '/T', '/PID', str(target_pid)],
                                capture_output=True, creationflags=_no_window, timeout=5
                            )
                            print(f"[PTY Cleanup] 좀비 PTY 서버(PID {target_pid}) 정리 완료")
                        except Exception:
                            pass
                _current_pid = None
                _current_cmdline = ""
    except Exception as e:
        print(f"[PTY Cleanup] 좀비 정리 실패 (무시): {e}")


def ensure_pty_node_modules(base_dir) -> None:
    """PTY 서버의 node_modules가 현재 PC에서 유효한지 확인하고, 필요하면 npm rebuild를 실행합니다.
    node-pty는 C++ 네이티브 모듈이라 빌드한 PC의 Node ABI 버전에 종속됩니다.
    pip install로 다른 PC에 설치하면 pty.node 파일이 존재하더라도 Node 버전이 달라
    로드 실패하므로, 실제로 require('node-pty')가 성공하는지 검증해야 합니다.
    """
    pty_server_dir = base_dir / 'pty-server'
    if not (pty_server_dir / 'package.json').exists():
        return  # pty-server 자체가 없으면 스킵

    # npm / node가 설치되어 있는지 확인
    import shutil as _shutil
    if not _shutil.which('node') or not _shutil.which('npm'):
        print("[!] Node.js가 설치되지 않았습니다. 터미널 기능을 위해 Node.js를 설치하세요.")
        return

    # node-pty 네이티브 모듈이 현재 Node.js에서 실제로 로드 가능한지 검증
    # 파일 존재만 확인하면 안 됨: pip install로 복사된 바이너리는 빌드 PC의 Node ABI라 호환 안 됨
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        check = subprocess.run(
            ['node', '-e', "require('node-pty')"],
            cwd=str(pty_server_dir),
            capture_output=True, text=True, timeout=10,
            creationflags=_no_window,
        )
        if check.returncode == 0:
            return  # 네이티브 모듈이 현재 Node에서 정상 로드됨
    except Exception:
        pass  # 검증 실패 → 재빌드 필요

    print("[*] PTY 서버 네이티브 모듈 빌드 중... (최초 1회, 1~2분 소요)")
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        # shell=True: Windows에서 npm은 npm.cmd이므로 shell 경유 필요
        result = subprocess.run(
            'npm install',
            cwd=str(pty_server_dir), shell=True,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=300,  # 5분 타임아웃
            creationflags=_no_window,
        )
        if result.returncode == 0:
            print("[*] PTY 서버 네이티브 모듈 빌드 완료!")
        else:
            print(f"[!] npm install 실패 (코드 {result.returncode}): {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("[!] npm install 타임아웃 (5분 초과)")
    except Exception as e:
        print(f"[!] npm install 실행 오류: {e}")


def start_node_pty_server(base_dir, ws_port, http_port, project_root,
                          child_procs, pty_server_state):
    """PTY 서버를 시작하고 프로세스 핸들을 반환합니다.

    [불변식] pty_server_state는 caller가 주입한 동일 dict를 그대로 변형한다 —
    워치독(pty_watchdog_loop)이 동일 객체의 ['proc']를 읽어 프로세스 사망을
    감지하므로, 여기서 새 dict를 만들면 워치독이 죽은 proc을 못 잡는다.
    """
    ensure_pty_node_modules(base_dir)  # 네이티브 모듈 빌드 확인/실행
    pty_server_dir = base_dir / 'pty-server'
    pty_server_exe = pty_server_dir / 'pty-server.exe'
    pty_server_js = pty_server_dir / 'pty-server.js'

    pty_env = os.environ.copy()
    pty_env['PTY_PORT'] = str(ws_port)
    pty_env['HTTP_PORT'] = str(http_port)
    pty_env['PROJECT_ROOT'] = str(project_root)

    # 번들된 node.exe 경로 — CI에서 같은 Node 버전으로 빌드된 런타임 (ABI 호환 보장)
    bundled_node = pty_server_dir / 'node.exe'

    if pty_server_exe.exists():
        # 배포 모드: pkg로 빌드된 단독 실행 파일
        cmd = [str(pty_server_exe)]
    elif pty_server_js.exists() and bundled_node.exists():
        # 배포 모드: 번들된 Node.js 런타임으로 실행 (네이티브 모듈 ABI 호환)
        cmd = [str(bundled_node), str(pty_server_js)]
    elif pty_server_js.exists():
        # 개발 모드: 시스템 Node.js로 직접 실행
        cmd = ['node', str(pty_server_js)]
    else:
        print("[!] PTY 서버 파일을 찾을 수 없습니다. 터미널 기능이 비활성화됩니다.")
        return None

    try:
        proc = subprocess.Popen(
            cmd,
            env=pty_env,
            cwd=str(pty_server_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        child_procs.append(proc)
        pty_server_state['proc'] = proc
        print(f"[*] Node PTY Server started (PID {proc.pid}) on port {ws_port}")

        # PTY 서버 stdout을 백그라운드로 읽어서 로그 출력
        def _read_pty_stdout():
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        print(f"[node-pty] {line}")
            except Exception:
                pass
        threading.Thread(target=_read_pty_stdout, daemon=True).start()
        return proc

    except FileNotFoundError:
        print("[!] Node.js가 설치되지 않았습니다. 터미널 기능이 비활성화됩니다.")
        return None
    except Exception as e:
        print(f"[!] Node PTY Server 시작 실패: {e}")
        return None


def pty_watchdog_loop(pty_server_state, health_check, kill_pty_proc,
                      kill_orphan, start_server):
    """30초 간격으로 PTY 서버 헬스체크 — 3회 연속 실패 시 자동 재시작.

    전략:
    - 30초마다 /health 호출
    - 3회 연속 실패(90초 무응답) → 프로세스 강제 종료 + 재시작
    - 재시작 후 10초 대기 (기동 시간 확보)
    - 재시작 5회 연속 실패 시 간격을 60초로 늘려 리소스 낭비 방지

    [주입] health_check/kill_pty_proc는 server.py main()의 나머지 nested 클로저
    (_pty_health_check/_kill_pty_proc, WS_PORT/_child_procs 캡처)이며 콜러블로 주입.
    kill_orphan/start_server는 본 모듈의 동일 상태(pty_server_state)를 공유하도록
    바인딩된 래퍼가 주입된다.
    """
    consecutive_fails = 0
    restart_fails = 0
    MAX_FAIL_BEFORE_RESTART = 3
    MAX_RESTART_FAILS = 5

    # 최초 기동 대기 — PTY 서버가 포트 바인딩할 시간 확보
    time.sleep(5)

    while True:
        interval = 60 if restart_fails >= MAX_RESTART_FAILS else 30

        # 1) 프로세스 자체가 죽었는지 확인
        proc_dead = (pty_server_state['proc'] is not None and
                     pty_server_state['proc'].poll() is not None)

        # 2) 헬스체크
        if proc_dead:
            healthy = False
        else:
            healthy = health_check()

        if healthy:
            consecutive_fails = 0
            restart_fails = 0  # 정상 응답 → 재시작 실패 카운터 리셋
        else:
            consecutive_fails += 1
            reason = "프로세스 종료됨" if proc_dead else "헬스체크 타임아웃"
            print(f"[PTY Watchdog] {reason} ({consecutive_fails}/{MAX_FAIL_BEFORE_RESTART})")

            if consecutive_fails >= MAX_FAIL_BEFORE_RESTART:
                print(f"[PTY Watchdog] {MAX_FAIL_BEFORE_RESTART}회 연속 실패 → PTY 서버 자동 재시작")
                kill_pty_proc(pty_server_state['proc'])
                kill_orphan()  # 좀비 PTY도 정리하여 포트 충돌 방지
                new_proc = start_server()
                if new_proc:
                    consecutive_fails = 0
                    restart_fails = 0
                    time.sleep(10)  # 기동 대기
                    continue
                else:
                    restart_fails += 1
                    print(f"[PTY Watchdog] 재시작 실패 ({restart_fails}/{MAX_RESTART_FAILS})")

        time.sleep(interval)
