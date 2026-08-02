"""
FILE: infra/console_scan.py
DESCRIPTION: 화면에 떠 있는 콘솔 창(정체불명 검은 cmd 창)을 찾아 "누가 띄웠는지"를 판정한다.
  상태판 창(StatusBoard)과 tui.py가 같은 데이터를 쓴다. 조회 + 안전 종료 2가지 책임.

[WHY 이 모듈이 필요한가 — 사용자 고통]
  콘솔 창은 윈도우에서 프로세스에 귀속되므로 여러 창을 하나로 **합칠 수 없다**(병합 API 부재).
  실제 고통은 "합쳐지지 않음"이 아니라 "저 검은 창이 뭔지 몰라 닫으면 안 될 걸 닫는 것"이다.
  → 통합 대신 **식별**로 푼다. 창을 남의 것/내 것/슬롯 것으로 분류해 라벨을 붙인다.

[🔴 판정의 핵심 — conhost 부모 추적 + 창 가시성 2중 필터]
  콘솔 창을 가진 프로세스는 자식으로 conhost.exe를 갖는다. 그런데 conhost는 두 종류다:
    conhost.exe 0x4                            → 콘솔 할당됨
    conhost.exe --headless --width 98 ...      → ConPTY (node-pty 터미널 슬롯, 창 없음)

  [과거사고 2026-08-02 — conhost만으로는 부족했다] `--headless`만 걸렀더니 GoogleDriveFS,
  ollama, nssm 서비스(java) 같은 놈이 19건 중 절반을 차지했다. 이들은 콘솔을 할당받았지만
  창이 숨겨져 있거나 세션 0(서비스)이라 **화면에 보이지 않는다**. 사용자는 "안 보이는 창"을
  목록에서 보고 더 혼란스러워진다.
  → user32.EnumWindows로 실제 보이는 최상위 창의 PID를 모아 2중 필터한다. 윈도우 10+에서
    콘솔 창의 HWND는 conhost 프로세스가 소유하므로, conhost PID가 그 집합에 있어야만
    "화면에 실제로 떠 있는 검은 창"이다.

[과거사고 2026-08-02] pg_ctl이 남긴 창의 정체 추적에 이 방법이 쓰였다.
  윈도우 pg_ctl은 postgres를 직접 spawn하지 못하고 로그 리다이렉션 때문에 항상
  `cmd /C "postgres.exe ... >> pg.log 2>&1"`를 한 겹 씌운다. 그 cmd는 DB가 사는 내내
  남으므로 검은 창이 계속 떠 있다. 우리 앱의 PG도 구조는 같지만 infra/proc.py가
  CREATE_NO_WINDOW를 넣어 창이 안 뜬다 — 즉 창이 보이면 proc.py를 안 거친 외부 실행이다.

[제약] 윈도우 전용. conhost는 win32에만 존재하므로 다른 플랫폼은 빈 목록을 돌려준다
  (에러가 아니라 "해당 없음"). 맥 이전 시 이 모듈은 no-op이 된다.

[제약] psutil을 쓰지 않는다 — 이 프로젝트는 stdlib만으로 어느 인터프리터에서든 돌아야 한다
  (설치본 번들 파이썬/scoop 3.14 등). 대신 PowerShell CIM 1회 호출로 스냅샷을 뜬다.

[성능] CIM 스냅샷 1회가 ~700ms다. 상태판이 5초 폴링하므로 TTL 캐시로 중복 호출을 막는다.

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 정체불명 콘솔 창 식별(상태판 독립 창 기능).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

IS_WINDOWS = sys.platform == 'win32'

# [WHY 캐시] 상태판 5초 + tui.py 5초가 동시에 붙으면 CIM 호출이 초당 2회가 된다.
#   스냅샷 자체가 ~700ms라 그대로 두면 폴링이 CPU를 계속 물어뜯는다.
_CACHE_TTL = 3.0
_cache_lock = threading.Lock()
_cache: dict = {'at': 0.0, 'procs': {}}

# CIM 스냅샷 — CreationDate는 DateTime 객체라 JSON에서 /Date(…)/로 뭉개진다.
# 종료 전 재검증에 쓸 값이므로 비교 가능한 고정폭 문자열로 미리 변환한다.
_PS_SNAPSHOT = (
    "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,"
    "CommandLine,ExecutablePath,"
    "@{n='Created';e={ if ($_.CreationDate) { $_.CreationDate.ToString('yyyyMMddHHmmss') } else { '' } }}"
    " | ConvertTo-Json -Compress -Depth 2"
)


def _run_powershell(script: str, timeout: float = 20.0) -> str:
    """PowerShell을 콘솔 없이 실행하고 stdout을 돌려준다.

    [제약] -NoProfile 필수 — 사용자 프로필에 Write-Host가 있으면 JSON 앞에 섞여 파싱이 깨진다.
    [제약] 출력 인코딩을 UTF-8로 고정 — 한글 경로가 섞인 CommandLine이 CP949로 나오면 깨진다.
    """
    res = proc.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=timeout,
    )
    return res.stdout or ''


def _as_list(parsed) -> list:
    """ConvertTo-Json은 결과가 1건이면 배열이 아닌 단일 객체를 준다 — 항상 리스트로 정규화."""
    if parsed is None:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def snapshot(force: bool = False) -> dict[int, dict]:
    """{pid: 프로세스레코드} 스냅샷. TTL 안이면 캐시를 재사용한다."""
    if not IS_WINDOWS:
        return {}
    now = time.time()
    with _cache_lock:
        if not force and (now - _cache['at']) < _CACHE_TTL and _cache['procs']:
            return _cache['procs']
    try:
        raw = _run_powershell(_PS_SNAPSHOT)
        rows = _as_list(json.loads(raw)) if raw.strip() else []
    except Exception:
        # 스냅샷 실패는 기능 정지가 아니라 "이번 회차 정보 없음" — 이전 캐시를 그대로 쓴다.
        return _cache['procs']

    procs: dict[int, dict] = {}
    for r in rows:
        try:
            pid = int(r.get('ProcessId') or 0)
        except (TypeError, ValueError):
            continue
        if not pid:
            continue
        procs[pid] = {
            'pid': pid,
            'ppid': int(r.get('ParentProcessId') or 0),
            'name': r.get('Name') or '',
            'cmdline': (r.get('CommandLine') or '').strip(),
            'exe': r.get('ExecutablePath') or '',
            'created': r.get('Created') or '',
        }
    with _cache_lock:
        _cache['at'] = now
        _cache['procs'] = procs
    return procs


def _ancestors(pid: int, procs: dict[int, dict], limit: int = 24) -> list[int]:
    """pid에서 부모를 따라 올라간 조상 PID 목록.

    [제약] limit로 끊는다 — PID 재사용으로 부모 체인에 사이클이 생길 수 있고(죽은 부모의
    PID를 새 프로세스가 물려받으면 A→B→A), 그러면 무한 루프가 된다.
    """
    out: list[int] = []
    seen = {pid}
    cur = procs.get(pid, {}).get('ppid', 0)
    while cur and cur not in seen and len(out) < limit:
        out.append(cur)
        seen.add(cur)
        cur = procs.get(cur, {}).get('ppid', 0)
    return out


def _pty_server_pids(procs: dict[int, dict]) -> set[int]:
    """터미널 슬롯을 굴리는 node PTY 서버 PID들.

    [WHY 스캔으로 찾는가] server.py의 _pty_server_state는 main() 지역 변수라 라우트에서
      못 본다. 커맨드라인으로 찾으면 전역 노출 없이도 되고, 앱이 여러 개 떠 있어도
      각자의 PTY 서버가 전부 잡힌다(슬롯 소속 판정은 어느 인스턴스든 'slot'이면 충분).
    """
    return {
        p['pid'] for p in procs.values()
        if p['name'].lower() == 'node.exe' and 'pty-server.js' in p['cmdline']
    }


def visible_windows() -> dict[int, str]:
    """{PID: 창 제목} — 화면에 실제로 보이는 최상위 창을 가진 프로세스.

    [WHY ctypes] 창 가시성은 WMI로 알 수 없다(Win32_Process에 창 정보가 없음).
      user32 EnumWindows는 stdlib ctypes만으로 되고 수 ms면 끝나므로 psutil도 불필요하다.

    [🔴 과거사고 2026-08-02 — argtypes 누락] argtypes를 지정하지 않으면 ctypes가 HWND를
      기본 c_int(32비트)로 넘겨 64비트 창 핸들 상위 비트가 잘린다. 그러면 모든 호출이
      조용히 실패해 결과가 **0건**이 된다(에러도 안 난다). 아래 시그니처 선언은 필수다.

    [🔴 콘솔 창의 소유자는 conhost가 아니다] 실측: cmd.exe(PID 18520)가 띄운 콘솔 창의
      GetWindowThreadProcessId는 conhost가 아니라 cmd.exe 자신을 반환한다. 윈도우가 콘솔
      창을 소유 프로세스에 매핑해 주기 때문 — 그래서 필터는 conhost PID가 아니라
      **콘솔 소유 프로세스 PID**로 걸어야 한다.

    [제약] IsWindowVisible만으로는 0×0 유령 창까지 잡힌다. 콘솔 창은 반드시 제목이 있으므로
      제목 길이도 함께 본다(제목 없는 창은 대부분 메시지 전용 숨김 창).
    """
    if not IS_WINDOWS:
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        found: dict[int, str] = {}

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                # 한 프로세스가 창을 여러 개 가지면 첫 번째(보통 주 창) 제목을 쓴다.
                found.setdefault(int(pid.value), buf.value)
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return found
    except Exception:
        # 가시성 조회 실패 시 빈 dict → caller가 필터를 건너뛴다(목록이 통째로 비는 것 방지).
        return {}


def _console_owners(procs: dict[int, dict], visible: dict[int, str]) -> dict[int, str]:
    """{콘솔 창 소유 프로세스 PID: 창 제목} — 화면에 실제로 떠 있는 콘솔만.

    [🔴 과거사고 2026-08-02 — conhost 부모만 보면 놓친다] 스크린샷의 pg_ctl 창이 그 예다.
      conhost(22600)의 부모는 pg_ctl.exe(34196)인데 pg_ctl은 start 직후 **죽는다**.
      살아남아 창을 붙들고 있는 건 pg_ctl이 띄운 형제 cmd.exe(18520)로, conhost의
      자식도 부모도 아니다(콘솔을 상속했을 뿐). "conhost의 부모" 기준으로는 이 창이
      통째로 목록에서 사라진다 — 정작 사용자가 정체를 궁금해한 바로 그 창인데.

    [판정 방향을 뒤집는다] 보이는 창 목록에서 출발해, 그 프로세스의 혈통(자신 + 조상)이
      어떤 conhost의 부모와 겹치면 콘솔 창으로 본다. 죽은 조상 PID도 자식의 ppid에는
      남아 있어 형제 관계까지 잡힌다.

    [필터] conhost 커맨드라인에 '--headless'가 있으면 ConPTY(터미널 슬롯)라 화면에 창이 없다.
    [폴백] visible이 비어 있으면(가시성 조회 실패) 예전 방식대로 conhost 부모를 그대로 쓴다 —
      노이즈가 섞여도 목록이 통째로 비는 것보단 낫다.
    """
    console_parents = {
        p['ppid'] for p in procs.values()
        if p['name'].lower() == 'conhost.exe'
        and '--headless' not in p['cmdline']
        and p['ppid']
    }
    if not visible:
        return {pid: '' for pid in console_parents if pid in procs}

    owners: dict[int, str] = {}
    for pid, title in visible.items():
        if pid not in procs:
            continue
        lineage = {pid} | set(_ancestors(pid, procs))
        if lineage & console_parents:
            owners[pid] = title
    return owners


def _app_roots() -> list[str]:
    """이 앱(바이브 코딩)의 설치/소스 루트 경로들 — 소속 판정의 2차 근거.

    [WHY 조상 추적만으로 부족한가] 데몬은 앱이 띄우지만, 앱이 여러 개 떠 있거나(개발본 +
      설치본) 중간 부모가 먼저 죽으면 조상 체인이 끊겨 자기 데몬이 foreign으로 오판된다
      (실측 2026-08-02: venv\\Scripts\\python.exe 데몬 4개가 전부 foreign으로 잡힘).
      실행 파일 경로가 앱 트리 안이면 인스턴스와 무관하게 우리 것이다.
    """
    roots: list[str] = []
    try:
        # infra/console_scan.py → .ai_monitor → 프로젝트 루트
        roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        roots.append(os.path.dirname(roots[0]))
    except Exception:
        pass
    if getattr(sys, 'frozen', False):
        try:
            roots.append(os.path.dirname(os.path.abspath(sys.executable)))
        except Exception:
            pass
    return [os.path.normcase(r) for r in roots if r]


# 콘솔 창의 껍데기로만 쓰이는 실행 파일 — 이것들은 "정체"가 아니라 래퍼다.
_WRAPPER_EXES = {'cmd.exe', 'conhost.exe', 'powershell.exe', 'pwsh.exe', 'sh.exe', 'env.exe'}


def _describe(rec: dict) -> str:
    """명령줄에서 사람이 알아볼 한 줄 설명을 뽑는다.

    [WHY] 원본 명령줄은 리다이렉션·따옴표·환경변수 설정으로 뒤덮여 있어(pg_ctl이 씌운
      `cmd /C "... < nul >> log 2>&1"`이 대표적) 그대로 보여주면 여전히 "이게 뭐야"다.
      래퍼를 걷어낸 실제 실행 대상만 집어낸다.

    [제약] 인터프리터(python/node)는 실행 파일만으론 정체를 모른다 — 실측에서
      `python.exe`만 3건이 나와 구분이 불가능했다. 뒤따르는 스크립트 인자까지 붙여야
      `python.exe train_monitor.py`처럼 무엇을 돌리는지 드러난다.
    """
    cmd = (rec['cmdline'] or '').strip()
    tokens = [t for t in cmd.replace('"', ' ').split() if t]

    target = ''
    for i, token in enumerate(tokens):
        low = token.lower()
        if not low.endswith('.exe'):
            continue
        if os.path.basename(low) in _WRAPPER_EXES:
            continue
        target = token
        # 인터프리터면 뒤에 오는 첫 스크립트 인자까지 붙여 정체를 드러낸다.
        for nxt in tokens[i + 1:]:
            nl = nxt.lower()
            if nl.endswith(('.py', '.js', '.ps1', '.cmd', '.bat', '.sh')):
                target = f'{os.path.basename(token)} {os.path.basename(nxt)}'
                break
            if nl.startswith('-'):
                continue
            break
        break

    if not target:
        # 래퍼밖에 없으면 원본 명령줄을 보여준다 — 짧게 잘라도 리다이렉션 앞부분에
        # 대개 실행 대상이 들어 있다.
        target = cmd or rec['exe'] or rec['name']
    return target[:200]


def scan(server_pid: int | None = None) -> list[dict]:
    """화면에 떠 있는 콘솔 창 목록 + 소속 판정.

    소속 3분류:
      owned   — 이 앱(어느 인스턴스든)이 띄운 것. 앱 동작에 필요하므로 종료 버튼을 주지 않는다.
      slot    — 터미널 슬롯(node pty-server)의 자손. 에이전트가 실행한 것.
      foreign — 그 외. 다른 앱/프로젝트가 띄운 것.

    [🔴 판정 순서 불변식] 내서버자손 → slot → 앱경로 → foreign.
      slot을 앱경로보다 **먼저** 봐야 한다. 역순이면 슬롯의 에이전트가 이 저장소 안의
      스크립트를 실행했을 때(예: python scripts/tui.py) 앱 소유로 잡혀 종료 버튼이
      사라진다 — 정작 사용자가 닫고 싶은 건 그 창이다.

    [불변식] 반환 항목의 (pid, created, exe)는 kill()의 재검증 키다. 프론트는 이 3개를
      그대로 되돌려줘야 하며, 하나라도 빠지면 종료가 거부된다(PID 재사용 오폭 차단).
    """
    if not IS_WINDOWS:
        return []
    procs = snapshot()
    if not procs:
        return []

    me = server_pid or os.getpid()
    pty_pids = _pty_server_pids(procs)
    owners = _console_owners(procs, visible_windows())
    app_roots = _app_roots()

    out: list[dict] = []
    for pid, window_title in owners.items():
        rec = procs.get(pid)
        if not rec:
            continue
        chain = _ancestors(pid, procs)
        lineage = [pid] + chain
        exe_nc = os.path.normcase(rec['exe'] or '')

        if me in lineage:
            owner, label = 'owned', '바이브 코딩'
        elif pty_pids & set(lineage):
            owner, label = 'slot', '터미널 슬롯'
        elif exe_nc and any(exe_nc.startswith(r) for r in app_roots):
            owner, label = 'owned', '바이브 코딩 (다른 인스턴스)'
        else:
            owner, label = 'foreign', '이 앱과 무관'

        out.append({
            'pid': pid,
            # [UX 핵심] 창 제목은 사용자가 화면에서 보는 그 문자열이다. 목록과 실제 창을
            #   1:1로 대조하는 유일한 단서라 반드시 내려보낸다.
            'title': window_title,
            'name': rec['name'],
            'exe': rec['exe'],
            'created': rec['created'],
            'cmdline': rec['cmdline'],
            'summary': _describe(rec),
            'owner': owner,
            'label': label,
            # 조상 이름 체인 — "누가 띄웠나"를 사용자가 눈으로 따라갈 수 있게 한다.
            'ancestry': [procs[a]['name'] for a in chain[:5] if a in procs],
        })

    # owned를 먼저(닫으면 안 되는 것부터) → foreign 순. 같은 등급은 PID 순으로 안정 정렬.
    rank = {'owned': 0, 'slot': 1, 'foreign': 2}
    out.sort(key=lambda x: (rank.get(x['owner'], 9), x['pid']))
    return out


def kill(pid: int, created: str, exe: str, allow_owned: bool = False) -> dict:
    """콘솔 창 프로세스를 트리째 종료한다. 3중 재검증 통과 시에만 실행.

    [🔴 블로커 대응 — PID 재사용 오폭] 목록 조회 시점과 클릭 시점 사이에 프로세스가 죽고
      같은 PID를 다른 프로세스가 물려받을 수 있다. 그대로 kill하면 무고한 프로세스를 죽인다.
      → (pid, created, exe)가 **전부** 일치할 때만 진행한다. created는 초 단위 생성 시각이라
      PID가 재사용돼도 값이 달라진다.

    [WHY 트리 종료(/T)] 콘솔 창의 주인은 보통 cmd.exe 껍데기이고 실제 작업은 자식이다
      (pg_ctl이 씌운 cmd → postgres). cmd만 죽이면 창은 사라져도 자식이 고아로 살아남는다.

    [불변식] owner=='owned'는 호출부에서 애초에 버튼을 그리지 않지만, API를 직접 때리는
      경로를 막기 위해 allow_owned 없이는 서버에서도 거부한다(2중 방어).
    """
    if not IS_WINDOWS:
        return {'ok': False, 'reason': 'unsupported', 'message': '윈도우 전용 기능이야.'}

    procs = snapshot(force=True)
    rec = procs.get(int(pid))
    if not rec:
        return {'ok': False, 'reason': 'gone', 'message': '이미 종료된 프로세스야. 목록을 새로고침할게.'}

    if rec['created'] != (created or '') or rec['exe'] != (exe or ''):
        # 여기 걸리면 PID가 재사용된 것 — 절대 죽이지 않는다.
        return {'ok': False, 'reason': 'mismatch',
                'message': 'PID가 다른 프로세스에 재사용됐어. 안전을 위해 종료하지 않았어.'}

    if not allow_owned:
        me = os.getpid()
        if me in [int(pid)] + _ancestors(int(pid), procs):
            return {'ok': False, 'reason': 'protected',
                    'message': '바이브 코딩이 쓰는 프로세스라 종료할 수 없어.'}

    try:
        res = proc.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=10)
        ok = res.returncode == 0
        with _cache_lock:
            _cache['at'] = 0.0  # 다음 조회가 새 스냅샷을 뜨도록 캐시 무효화
        return {
            'ok': ok,
            'reason': 'killed' if ok else 'failed',
            'message': (res.stdout or res.stderr or '').strip()[:300],
        }
    except Exception as e:
        return {'ok': False, 'reason': 'error', 'message': str(e)}
