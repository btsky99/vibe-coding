"""
FILE: scripts/tui.py
DESCRIPTION: 터미널용 텍스트 대시보드 — GUI 없이 하이브 상태(프로젝트/쿼터/터미널/태스크)를 본다.
  SSH로 붙은 원격 노드에서도 그대로 돌아가는 것이 목적이다.

[WHY GUI가 있는데 TUI인가]
  대시보드는 PyWebView 네이티브 창이라 SSH 세션에는 뜨지 않는다(원격 노드에 데스크톱이 없거나
  다른 세션이라 화면이 안 나온다). 상주 노드 상태를 어디서든 보려면 텍스트 경로가 필요하다.

[제약] 표준 라이브러리만 쓴다.
  설치본(번들 파이썬)·scoop 파이썬 3.14 등 어느 인터프리터로 실행될지 모른다.
  외부 패키지를 쓰면 "그 기기에선 안 돌아가는" 도구가 된다. curses도 쓰지 않는다(윈도우 미탑재).

[🔴 포트 함정] 9000번대에는 여러 프로젝트의 서버가 동시에 뜬다(실측: 9000=ons, 다른 포트=vibe-coding).
  '첫 응답 포트'를 쓰면 남의 프로젝트 DB를 읽어 엉뚱한 태스크를 보여준다.
  server_locator.find_server_port(slug)로 자기 프로젝트만 채택한다 — 이 대조 로직은
  src/server_locator.py가 단독 소유하므로 여기서 재구현하지 않는다.

REVISION HISTORY:
- 2026-08-03 Codex: provider별 작업 크기 권고와 판단 이유 표시
- 2026-08-02 Claude: 원격 노드(생존/접속) + 떠 있는 콘솔 창 섹션 추가.
  섹션 헤더/전각 폭 계산을 도입해 한글 줄이 구분선과 어긋나던 것을 정리.
  두 섹션은 /api/nodes/* 의존 — 구버전 서버에 붙으면 조용히 생략된다.
- 2026-07-29 Claude: 최초 작성 — 레노버(APIS) 상주 노드를 터미널에서 보기 위한 TUI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request as _req
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_AI_MONITOR = os.path.join(os.path.dirname(_HERE), '.ai_monitor')
if _AI_MONITOR not in sys.path:
    sys.path.insert(0, _AI_MONITOR)

try:
    from src.server_locator import find_server_port, slug_for_cwd
except Exception:  # 설치본 등 경로가 다른 환경 — 포트를 직접 받도록 안내
    find_server_port = None  # type: ignore
    slug_for_cwd = None      # type: ignore

# ── ANSI ────────────────────────────────────────────────────────────────────
R = '\x1b[0m'
B = '\x1b[1m'
DIM = '\x1b[2m'
CYAN = '\x1b[36m'
GREEN = '\x1b[32m'
YEL = '\x1b[33m'
RED = '\x1b[31m'
GRAY = '\x1b[90m'


def _enable_vt() -> None:
    """윈도우 콘솔에서 ANSI 이스케이프를 켠다.

    [제약] Windows Terminal은 기본으로 켜져 있으나 conhost(구 콘솔)는 꺼져 있어
    이 호출이 없으면 화면이 이스케이프 문자로 도배된다. 실패해도 진행한다(색만 빠짐).
    """
    # [🔴 원격 SSH 한글 깨짐] 윈도우 cmd의 기본 출력 코드페이지가 CP949라
    #   UTF-8 한글이 그대로 나가면 모지바케가 된다(SSH로 붙었을 때 실측).
    #   이 도구는 원격에서 읽는 것이 주 용도라 출력 인코딩을 항상 UTF-8로 고정한다.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    except Exception:
        pass
    if os.name != 'nt':
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k.SetConsoleOutputCP(65001)               # UTF-8 코드페이지
    except Exception:
        pass


def _get(port: int, path: str, timeout: float = 3.0):
    try:
        with _req.urlopen(f'http://127.0.0.1:{port}{path}', timeout=timeout) as f:
            return json.loads(f.read().decode('utf-8'))
    except Exception:
        return None


def _bar(pct: float, width: int = 18) -> str:
    """사용률 막대 — 색으로 위험도를 즉시 읽게 한다(녹→황→적)."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * pct / 100.0))
    color = GREEN if pct < 60 else (YEL if pct < 85 else RED)
    return f'{color}{"█" * filled}{GRAY}{"░" * (width - filled)}{R}'


def _ago(iso: str) -> str:
    """ISO 시각 → '3분 전' 형태. 파싱 실패하면 원문 앞부분을 그대로 준다."""
    if not iso:
        return ''
    try:
        s = iso.replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # [🔴 naive는 UTC가 아니라 로컬이다] 서버가 datetime.now()로 찍은 값이라
            # tz가 없다. UTC로 가정하면 KST(+9) 기준으로 9시간 미래가 되어
            # '-32207초 전' 같은 음수 경과시간이 나온다(실측).
            # naive.astimezone()은 시스템 로컬 시각으로 해석해 tz를 붙인다(3.6+).
            dt = dt.astimezone()
        delta = (datetime.now(timezone.utc) - dt).total_seconds()
        if delta < 60:
            return f'{int(delta)}초 전'
        if delta < 3600:
            return f'{int(delta // 60)}분 전'
        if delta < 86400:
            return f'{int(delta // 3600)}시간 전'
        return f'{int(delta // 86400)}일 전'
    except Exception:
        return iso[:16]


def _ago_sec(sec) -> str:
    """서버가 계산해준 '나이(초)' → '3분 전'.

    [WHY 서버 계산값을 쓰는가] 이 PC 시계가 어긋나면 절대시각 비교(_ago)는 몇 시간씩
      틀린다. 관제·상태판 모두 나이를 서버에서 계산해 내려주므로 그대로 표시만 한다.
    """
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ''
    if sec < 60:
        return f'{sec}초 전'
    if sec < 3600:
        return f'{sec // 60}분 전'
    if sec < 86400:
        return f'{sec // 3600}시간 전'
    return f'{sec // 86400}일 전'


def _width(s: str) -> int:
    """한글 등 전각 문자를 2칸으로 세는 표시 폭.

    [WHY] len()으로 자르면 한글이 섞인 줄에서 실제 화면 폭이 최대 2배가 되어
    구분선과 어긋난다(원격 SSH 터미널에서 특히 지저분해진다).
    """
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in s)


def _clip(s: str, n: int) -> str:
    """표시 폭 기준으로 자른다 — 전각 문자를 1칸으로 세면 줄이 밀린다."""
    s = ' '.join(str(s).split())
    if _width(s) <= n:
        return s
    out, acc = '', 0
    for ch in s:
        w = _width(ch)
        if acc + w > n - 1:
            return out + '…'
        out += ch
        acc += w
    return out


def _section(title: str, width: int, note: str = '') -> str:
    """섹션 헤더 — 제목을 선 안에 넣어 블록 경계를 눈으로 잡게 한다.

    `── 플랜 사용률 ──────────────────────  (부가정보)`
    """
    label = f' {title} '
    tail = f' {note}' if note else ''
    pad = max(0, width - 2 - _width(label) - _width(tail))
    return f'{GRAY}──{R}{B}{label}{R}{GRAY}{"─" * pad}{tail}{R}'


# ── 섹션 렌더 ───────────────────────────────────────────────────────────────
# [제약] 아래 두 섹션은 /api/nodes/* 를 쓴다. 구버전 서버(라우트 없음)에 붙으면 _get이
#   None을 주므로 섹션을 통째로 생략한다 — 원격 노드의 서버가 항상 최신이라는 보장이 없다.
def _render_nodes(port: int, width: int) -> list[str]:
    """원격 노드 — 생존(하트비트)/접속(역터널). 상태판 창과 같은 데이터."""
    data = _get(port, '/api/nodes/remote')
    if not data:
        return []
    hosts = data.get('hosts') or []
    if not hosts:
        return []
    # [🔴 생존과 접속을 합치지 말 것] alive=하트비트 / reachable=역터널. 조치가 정반대라
    #   한 값으로 뭉개면 "터널만 죽음"과 "앱이 죽음"을 구분할 수 없다(nodes_api 헤더 참조).
    #   세 값이다 — True/False/None(판정 불가). None을 False로 세지 않는다.
    alive_n = sum(1 for h in hosts if h.get('alive') is True)
    out = [_section('원격 노드', width, f'{alive_n}/{len(hosts)} 살아있음')]
    for h in hosts[:8]:
        alive, reach = h.get('alive'), h.get('reachable')
        dot = (f'{GREEN}●{R}' if alive is True
               else f'{GRAY}○{R}' if alive is False else f'{DIM}◌{R}')
        who = f"{h.get('user') or ''}@{h.get('hostName') or ''}".strip('@')
        age = h.get('heartbeatAge')
        life = ('살아있음' if alive is True else '끊김' if alive is False else '생존?')
        if age is not None:
            life += f' {_ago_sec(age)}'
        link = ('조종가능' if reach is True else '터널끊김' if reach is False else '터널없음')
        color = '' if alive is True else GRAY
        out.append(f'   {dot} {color}{_clip(h.get("alias") or "?", 14):<14}{R} '
                   f'{DIM}{_clip(who, 22):<22}{R} {color}{life:<14}{R}{DIM}{link}{R}')
    srv = data.get('server') or {}
    if not srv.get('available', True):
        out.append(f'{GRAY}   (아픽스 서버에 못 물어봐 판정 생략 — 노드가 죽은 게 아님){R}')
    elif not srv.get('heartbeatAvailable', True):
        out.append(f'{GRAY}   (관제 DB를 못 읽어 생존 판정만 생략 — 터널 표시는 유효){R}')
    out.append('')
    return out


def _render_consoles(port: int, width: int) -> list[str]:
    """떠 있는 콘솔 창 — 정체 식별. 창을 합칠 수 없으니 누가 띄웠는지를 보여준다."""
    data = _get(port, '/api/nodes/consoles')
    if not data or not data.get('supported'):
        return []
    items = data.get('consoles') or []
    counts = data.get('counts') or {}
    note = f"앱 {counts.get('owned', 0)} · 슬롯 {counts.get('slot', 0)} · 외부 {counts.get('foreign', 0)}"
    out = [_section('떠 있는 콘솔 창', width, note)]
    if not items:
        out.append(f'{GRAY}   (떠 있는 콘솔 창 없음){R}')
        out.append('')
        return out
    # owned=닫으면 안 됨(녹색) / slot=에이전트 것(황) / foreign=남의 것(회색)
    marks = {'owned': f'{GREEN}●{R}', 'slot': f'{YEL}●{R}', 'foreign': f'{GRAY}○{R}'}
    for c in items[:10]:
        out.append(f'   {marks.get(c.get("owner"), "○")} '
                   f'{_clip(c.get("title") or c.get("name") or "", 40):<40} '
                   f'{DIM}{_clip(c.get("label") or "", 18)}{R}')
        out.append(f'     {GRAY}{_clip(c.get("summary") or "", width - 8)}{R}')
    out.append('')
    return out


# ── 렌더 ────────────────────────────────────────────────────────────────────
def render(port: int, width: int = 76, expect_slug: str = '') -> str:
    out: list[str] = []
    info = _get(port, '/api/project-info') or {}
    name = info.get('project_name') or '?'
    ver = info.get('version') or '?'
    root = info.get('project_root') or ''

    out.append(f'{B}{CYAN}  VIBE{R} {B}{name}{R} {DIM}v{ver}{R}{GRAY} · :{port}{R}')
    out.append(f'{GRAY}  {_clip(root, width - 4)}{R}')
    # [🔴 오접속 경고] 9000번대에 여러 프로젝트 서버가 떠 있어 폴백이 남의 서버를 잡을 수 있다.
    #   조용히 남의 태스크를 보여주면 "왜 내 작업이 안 보이지"로 헤매므로 명시한다.
    actual = str(info.get('project_id') or '')
    if expect_slug and actual and actual != expect_slug:
        out.append(f'{YEL}  ⚠ 다른 프로젝트 서버야 (기대 {expect_slug} / 실제 {actual}){R}')
        out.append(f'{GRAY}    이 폴더의 앱을 켜거나 --port 로 직접 지정해줘.{R}')
    out.append('')

    # ── 쿼터 ────────────────────────────────────────────────────────────────
    quota = _get(port, '/api/agent-quota') or {}
    out.append(_section('플랜 사용률', width))
    shown = False
    for cli in ('claude', 'codex'):
        q = quota.get(cli) or {}
        if not q.get('available'):
            continue
        shown = True
        plan = q.get('plan') or ''
        parts = []
        for key, label in (('five_hour', '5시간'), ('seven_day', '7일')):
            w = q.get(key) or {}
            if w and w.get('utilization') is not None:
                pct = float(w['utilization'])
                parts.append(f'{label} {_bar(pct)} {pct:5.1f}%')
        head = f'   {cli:<7}{DIM}{_clip(plan, 10):<11}{R}'
        if parts:
            out.append(head + parts[0])
            for extra in parts[1:]:
                out.append(' ' * len(f'   {cli:<7}{_clip(plan, 10):<11}') + extra)
        else:
            out.append(head + f'{GRAY}(창 정보 없음){R}')
        advice = q.get('advice') or {}
        if advice.get('action'):
            out.append(f"{YEL}     ↳ {_clip(str(advice['action']), width - 8)}{R}")
            if advice.get('reason'):
                out.append(f"{GRAY}       {_clip(str(advice['reason']), width - 10)}{R}")
    if not shown:
        out.append(f'{GRAY}   (사용 가능한 쿼터 정보 없음){R}')
    out.append('')

    # ── 터미널 세션 ─────────────────────────────────────────────────────────
    sess = _get(port, '/api/pty/sessions/summary') or {}
    total = sum((v or {}).get('total', 0) for v in sess.values()) if isinstance(sess, dict) else 0
    out.append(_section('터미널 세션', width, f'{total}개'))
    if isinstance(sess, dict) and sess:
        for slug, v in list(sess.items())[:6]:
            v = v or {}
            out.append(f'   {GREEN}●{R} {_clip(slug, 34):<34} '
                       f'{DIM}에이전트 {v.get("agent_count", 0)} / 전체 {v.get("total", 0)}{R}')
    else:
        out.append(f'{GRAY}   (열린 세션 없음){R}')
    out.append('')

    out.extend(_render_nodes(port, width))
    out.extend(_render_consoles(port, width))

    # ── 최근 태스크 ─────────────────────────────────────────────────────────
    tasks = _get(port, '/api/tasks')
    out.append(_section('최근 활동', width))
    if isinstance(tasks, list) and tasks:
        for t in tasks[:8]:
            when = _ago(t.get('updated_at') or t.get('timestamp') or '')
            out.append(f'   {DIM}{when:>8}{R}  {_clip(t.get("title") or "", width - 16)}')
    else:
        out.append(f'{GRAY}   (기록 없음){R}')

    out.append('')
    out.append(f'{GRAY}  Ctrl+C 종료{R}')
    return '\n'.join(out)


def resolve_port(explicit: int | None) -> tuple[int | None, str]:
    """(포트, 기대 슬러그)를 돌려준다. 기대 슬러그는 오접속 경고 표시에 쓴다."""
    slug = ''
    if slug_for_cwd is not None:
        try:
            slug = slug_for_cwd() or ''  # type: ignore[misc]
        except Exception:
            slug = ''
    if explicit:
        return explicit, slug
    env = os.getenv('VIBE_SERVER_PORT')
    if env and env.isdigit():
        return int(env), slug
    if find_server_port is None:
        return None, slug
    # [🔴 슬러그 대조 필수] 인자 없이 부르면 '첫 응답 포트'라 남의 프로젝트에 붙는다.
    port = find_server_port(slug) if slug else None
    if port is None:
        # 슬러그 산출 실패/미매칭 — 첫 응답으로 폴백한다. 화면 상단에 경고가 뜨므로
        # 사용자가 엉뚱한 서버임을 바로 알아챈다(조용한 오접속 방지).
        port = find_server_port()
    return port, slug


def main() -> int:
    ap = argparse.ArgumentParser(description='바이브 코딩 터미널 대시보드')
    ap.add_argument('--port', type=int, default=None, help='서버 포트 직접 지정')
    ap.add_argument('--interval', type=float, default=5.0, help='새로고침 주기(초)')
    ap.add_argument('--once', action='store_true', help='한 번만 출력하고 종료')
    args = ap.parse_args()

    _enable_vt()

    port, expect_slug = resolve_port(args.port)
    if not port:
        print(f'{RED}[중단] 응답하는 바이브 서버를 찾지 못했어.{R}')
        print(f'{GRAY}  앱을 켜거나 --port 로 직접 지정해줘.{R}')
        return 1

    if args.once:
        print(render(port, expect_slug=expect_slug))
        return 0

    try:
        while True:
            # [WHY 전체 지우기] 부분 갱신은 폭이 다른 원격 터미널에서 잔상이 남는다.
            sys.stdout.write('\x1b[2J\x1b[H')
            sys.stdout.write(render(port, expect_slug=expect_slug))
            sys.stdout.write('\n')
            sys.stdout.flush()
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        sys.stdout.write('\n')
        return 0


if __name__ == '__main__':
    sys.exit(main())
