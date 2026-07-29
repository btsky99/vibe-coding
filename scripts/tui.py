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


def _clip(s: str, n: int) -> str:
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + '…'


# ── 렌더 ────────────────────────────────────────────────────────────────────
def render(port: int, width: int = 76, expect_slug: str = '') -> str:
    out: list[str] = []
    line = '─' * width

    info = _get(port, '/api/project-info') or {}
    name = info.get('project_name') or '?'
    ver = info.get('version') or '?'
    root = info.get('project_root') or ''

    out.append(f'{B}{CYAN}  VIBE TUI{R}  {B}{name}{R} {DIM}v{ver}  :{port}{R}')
    out.append(f'{GRAY}  {_clip(root, width - 4)}{R}')
    # [🔴 오접속 경고] 9000번대에 여러 프로젝트 서버가 떠 있어 폴백이 남의 서버를 잡을 수 있다.
    #   조용히 남의 태스크를 보여주면 "왜 내 작업이 안 보이지"로 헤매므로 명시한다.
    actual = str(info.get('project_id') or '')
    if expect_slug and actual and actual != expect_slug:
        out.append(f'{YEL}  ⚠ 다른 프로젝트 서버야 (기대 {expect_slug} / 실제 {actual}){R}')
        out.append(f'{GRAY}    이 폴더의 앱을 켜거나 --port 로 직접 지정해줘.{R}')
    out.append(f'{GRAY}{line}{R}')

    # ── 쿼터 ────────────────────────────────────────────────────────────────
    quota = _get(port, '/api/agent-quota') or {}
    out.append(f'{B}  플랜 사용률{R}')
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
    if not shown:
        out.append(f'{GRAY}   (사용 가능한 쿼터 정보 없음){R}')
    out.append(f'{GRAY}{line}{R}')

    # ── 터미널 세션 ─────────────────────────────────────────────────────────
    sess = _get(port, '/api/pty/sessions/summary') or {}
    total = sum((v or {}).get('total', 0) for v in sess.values()) if isinstance(sess, dict) else 0
    out.append(f'{B}  터미널 세션{R} {DIM}({total}개){R}')
    if isinstance(sess, dict) and sess:
        for slug, v in list(sess.items())[:6]:
            v = v or {}
            out.append(f'   {GREEN}●{R} {_clip(slug, 34):<34} '
                       f'{DIM}에이전트 {v.get("agent_count", 0)} / 전체 {v.get("total", 0)}{R}')
    else:
        out.append(f'{GRAY}   (열린 세션 없음){R}')
    out.append(f'{GRAY}{line}{R}')

    # ── 최근 태스크 ─────────────────────────────────────────────────────────
    tasks = _get(port, '/api/tasks')
    out.append(f'{B}  최근 활동{R}')
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
