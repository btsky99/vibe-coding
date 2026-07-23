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

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
# [주의] pty_server_state['proc']는 dict 키라 모듈 proc과 무관. 단, 지역변수/파라미터로
#   proc을 쓰던 함수(start_node_pty_server, _kill_pty_proc)는 child로 rename해 충돌 회피.


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
    try:
        # CommandLine + ProcessId를 함께 조회하여 포트 기반 필터링
        result = proc.run(
            ['wmic', 'process', 'where',
             "CommandLine like '%pty-server.js%' and Name='node.exe'",
             'get', 'ProcessId,CommandLine', '/FORMAT:LIST'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=5
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
                            ppid_res = proc.run(
                                ['wmic', 'process', 'where',
                                 f'ProcessId={target_pid}',
                                 'get', 'ParentProcessId', '/FORMAT:LIST'],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=3
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
                            proc.run(
                                ['taskkill', '/F', '/T', '/PID', str(target_pid)],
                                capture_output=True, timeout=5
                            )
                            print(f"[PTY Cleanup] 좀비 PTY 서버(PID {target_pid}) 정리 완료")
                        except Exception:
                            pass
                _current_pid = None
                _current_cmdline = ""
    except Exception as e:
        print(f"[PTY Cleanup] 좀비 정리 실패 (무시): {e}")


def kill_runtime_mei_orphans(runtime_dir, exclude_mei: str = '',
                             only_orphans: bool = False) -> list:
    """고정 runtime_tmpdir(%APPDATA%\\VibeCoding\\runtime) 하위 _MEI* 추출 폴더에서
    실행 중인 node.exe(PTY 서버 등)를 강제 종료하고, 종료한 PID 목록을 반환한다.

    [WHY / 과거사고 v3.7.244] onefile 부트로더는 Python 코드보다 **먼저** python DLL을
    로드한다. 업데이트 시 updater.apply_update_from_temp의 os._exit(0)가 atexit 정리를
    통째로 건너뛰어, 이전 인스턴스의 node PTY 서버가 좀비로 남아 자기 _MEI\\pty-server를
    잠근다. 다음(새 EXE) 부팅의 부트로더가 잠긴 잔여 _MEI와 충돌 → python DLL 부분 추출 →
    "Failed to load Python DLL. LoadLibrary: 지정된 모듈을 찾을 수 없습니다" 부팅 실패 +
    "Failed to remove temporary directory" 경고. 부트로더 단계라 앱 내부 정리로는 못 막으므로,
    **이전 프로세스(updater 또는 정상 종료 경로)가 새 EXE 기동 전에 반드시 호출**해야 한다.

    [제약/불변식] node.exe의 ExecutablePath가 runtime_dir 하위인 것만 대상 → 개발 인스턴스
    (node가 프로젝트 node_modules/pty-server에서 실행)나 무관한 node는 절대 건드리지 않음.
    exclude_mei가 주어지면 그 _MEI(현재 실행 인스턴스) 소속 node는 보호.

    [only_orphans 모드 — 다중 인스턴스 보호] True면 node의 **부모(vibe-coding.exe)가
    살아있는 경우 보호**하고, 부모가 죽은 진짜 좀비만 죽인다. 정상 종료/시작 경로에서 사용 —
    동시에 켜둔 다른 설치 인스턴스의 살아있는 PTY 서버를 몰살하던 v3.7.122 사고 재발 방지.
    False(업데이터)면 install 전체를 교체 중이므로 부모 생사 무관하게 모두 정리(자기 것 포함).

    [플랫폼] wmic 의존(기존 kill_orphan_pty_servers와 동일 패턴). Win11 24H2+에서 wmic가
    제거되면 이 함수는 조용히 no-op(전체 try/except) — 그 경우 CIM(Get-CimInstance Win32_Process)
    전환 필요. 실패해도 기존 동작보다 나빠지지 않음(정리를 안 할 뿐).
    """
    # [보존] subprocess.call(아래 taskkill)은 헬퍼 미제공이라 미변환 → _no_window 유지 필수.
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    rd = str(runtime_dir).replace('/', '\\').rstrip('\\').lower()
    if not rd:
        return []
    killed = []
    try:
        # 1) only_orphans면 '살아있는 vibe-coding.exe PID 집합'을 먼저 수집(부모 생존 판정용)
        live_parents = set()
        if only_orphans:
            try:
                pres = proc.run(
                    ['wmic', 'process', 'where',
                     "name like 'vibe-coding%'", 'get', 'ProcessId', '/FORMAT:LIST'],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=5,
                )
                for line in pres.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('ProcessId='):
                        v = line[len('ProcessId='):].strip()
                        if v.isdigit():
                            live_parents.add(v)
            except Exception:
                # 부모 목록 수집 실패 시 안전 우선 — 아무도 안 죽임(보호)
                return []

        # 2) runtime 하위 node.exe 를 ExecutablePath + ParentProcessId 로 조회
        res = proc.run(
            ['wmic', 'process', 'where', "name='node.exe'",
             'get', 'ProcessId,ParentProcessId,ExecutablePath', '/FORMAT:LIST'],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=5,
        )
        _pid = None
        _ppid = None
        _path = ''
        # /FORMAT:LIST는 필드=값 줄을 (빈 줄 구분) 나열 — ProcessId를 쌍 완성 신호로 사용
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith('ExecutablePath='):
                _path = line[len('ExecutablePath='):]
            elif line.startswith('ParentProcessId='):
                _ppid = line[len('ParentProcessId='):].strip()
            elif line.startswith('ProcessId='):
                _pid = line[len('ProcessId='):].strip()
                if _pid.isdigit() and _path:
                    p = _path.replace('/', '\\').lower()
                    under = p.startswith(rd)
                    excluded = bool(exclude_mei) and exclude_mei.lower() in p
                    # only_orphans: 부모가 살아있는 vibe-coding이면 보호(진짜 좀비만 kill)
                    protected_parent = only_orphans and _ppid in live_parents
                    if under and not excluded and not protected_parent:
                        try:
                            subprocess.call(
                                ['taskkill', '/F', '/T', '/PID', _pid],
                                creationflags=_no_window, timeout=5,
                            )
                            killed.append(_pid)
                        except Exception:
                            pass
                _pid = None
                _ppid = None
                _path = ''
        if killed:
            print(f"[cleanup] runtime _MEI 좀비 node 종료: {killed}")
    except Exception as e:
        print(f"[cleanup] runtime _MEI 좀비 정리 실패 (무시): {e}")
    return killed


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
    try:
        check = proc.run(
            ['node', '-e', "require('node-pty')"],
            cwd=str(pty_server_dir),
            capture_output=True, text=True, timeout=10,
        )
        if check.returncode == 0:
            return  # 네이티브 모듈이 현재 Node에서 정상 로드됨
    except Exception:
        pass  # 검증 실패 → 재빌드 필요

    print("[*] PTY 서버 네이티브 모듈 빌드 중... (최초 1회, 1~2분 소요)")
    try:
        # shell=True: Windows에서 npm은 npm.cmd이므로 shell 경유 필요
        result = proc.run(
            'npm install',
            cwd=str(pty_server_dir), shell=True,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=300,  # 5분 타임아웃
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

    # 번들된 node 경로 — CI에서 같은 Node 버전으로 빌드된 런타임 (ABI 호환 보장).
    # [플랫폼] 파일명이 Windows는 node.exe, macOS/Linux는 node. 하드코딩하면 맥에서
    # 번들 런타임을 못 찾아 시스템 node로 폴백하는데, node-pty는 네이티브 모듈이라
    # ABI가 어긋나면 터미널이 통째로 죽는다.
    bundled_node = pty_server_dir / ('node.exe' if os.name == 'nt' else 'node')

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
        # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 충돌 회피.
        #   pty_server_state['proc']는 dict 키라 그대로 유지(외부 계약).
        child = proc.popen(
            cmd,
            env=pty_env,
            cwd=str(pty_server_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        child_procs.append(child)
        pty_server_state['proc'] = child
        print(f"[*] Node PTY Server started (PID {child.pid}) on port {ws_port}")

        # PTY 서버 stdout을 백그라운드로 읽어서 로그 출력
        def _read_pty_stdout():
            try:
                for line in child.stdout:
                    line = line.strip()
                    if line:
                        print(f"[node-pty] {line}")
            except Exception:
                pass
        threading.Thread(target=_read_pty_stdout, daemon=True).start()
        return child

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


def prepare_pty_async(pty_server_state: dict, base_dir) -> threading.Event:
    """PTY 준비(좀비 정리 + node_modules 빌드)를 백그라운드로 시작하고 완료 Event 반환.

    [WHY] PG 시작과 병렬로 돌려 부팅 체감 지연을 줄이는 최적화(v3.7.179) — caller는
      이 Event를 3단계에서 wait 한 뒤 PTY 서버를 띄운다. 반환된 Event 계약을 지켜야
      PG-PTY 병렬성이 보존된다.
    """
    done = threading.Event()

    def _prepare():
        try:
            kill_orphan_pty_servers(pty_server_state)
            ensure_pty_node_modules(base_dir)
        except Exception as e:
            print(f"[!] PTY 병렬 준비 오류: {e}")
        done.set()

    threading.Thread(target=_prepare, daemon=True).start()
    return done


def start_pty_server_and_watchdog(pty_server_state: dict, base_dir, ws_port: int,
                                  http_port: int, project_root, child_procs: list,
                                  prep_done: threading.Event) -> None:
    """PTY 준비 완료를 기다린 뒤 PTY 서버를 띄우고 헬스체크 워치독을 시작한다.

    server.py main() 내부 nested 래퍼(_pty_health_check/_kill_pty_proc/_pty_watchdog_loop)를
    이관 — WS_PORT/_child_procs 캡처를 ws_port/child_procs 인자로 치환(R19).
    [불변식] pty_server_state(가변 dict)는 start와 watchdog이 동일 객체를 공유해야
      프로세스 사망 감지가 성립 — 재생성 금지, caller 주입 dict를 그대로 변형한다.
    """
    prep_done.wait(timeout=30)
    start_node_pty_server(base_dir, ws_port, http_port, project_root,
                          child_procs, pty_server_state)

    def _health_check() -> bool:
        """PTY 서버 /health 엔드포인트에 GET 요청 — 2초 내 응답하면 True."""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{ws_port}/health")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get('status') == 'ok'
        except Exception:
            return False

    def _kill_pty_proc(child):
        """행 상태 PTY 프로세스를 강제 종료합니다 (taskkill /T 로 프로세스 트리 전체).
        [파라미터 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼) 참조를 파라미터가 가리지 않게."""
        if child is None:
            return
        try:
            pid = child.pid
            # Windows: 프로세스 트리 전체 강제 종료
            proc.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True
            )
            print(f"[PTY Watchdog] 행 상태 PTY 서버(PID {pid}) 강제 종료 완료")
        except Exception as e:
            print(f"[PTY Watchdog] PTY 프로세스 종료 실패: {e}")
        # child_procs 목록에서 제거 (중복 kill 방지)
        try:
            child_procs.remove(child)
        except ValueError:
            pass

    def _watchdog():
        pty_watchdog_loop(
            pty_server_state, _health_check, _kill_pty_proc,
            lambda: kill_orphan_pty_servers(pty_server_state),
            lambda: start_node_pty_server(base_dir, ws_port, http_port,
                                          project_root, child_procs, pty_server_state))

    threading.Thread(target=_watchdog, daemon=True, name='PTY-Watchdog').start()
