#!/usr/bin/env python3
"""
FILE: scripts/apix_sources.py
DESCRIPTION: 아픽스 콘솔로 올릴 **로컬 데이터 수집기**. 이 PC 안의 프로젝트를 찾아
             태스크(hive_tasks) · 커밋(git) · 체크포인트 · 사고(incident_ledger)를
             '마지막 전송 이후 변경분'만 뽑아낸다. 전송은 하지 않는다.

             [WHY apix_push.py 와 나누나] 한쪽은 '무엇을 보낼까'(로컬 PG·git 의존),
             다른 쪽은 '어떻게 보낼까'(HTTP·토큰·커서)다. 섞어 두면 전송 실패를
             디버깅할 때 DB 스키마까지 같이 읽어야 하고, 반대로 수집 로직을 고칠 때
             토큰 경로를 건드릴 위험이 생긴다.

             [🔴 불변식 — 이 모듈은 절대 예외를 밖으로 내보내지 않는다]
             관제 수집이 실패해도 로컬 앱은 아무 영향이 없어야 한다. 못 읽은 소스는
             빈 리스트로 접고 넘어간다. 여기서 raise 하면 스케줄러 로그만 붉어진다.

             [불변식] project_key 는 **GitHub 리포 이름**이다. 콘솔의
             collector/seed_projects.py 가 같은 규칙으로 프로젝트를 미리 등록해 두므로,
             폴더명을 쓰면 같은 프로젝트가 두 줄로 갈라진다. remote URL 의 basename 을
             1순위로 쓰고, 리모트가 없을 때만 폴더명으로 떨어진다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — 계획 Phase 7 Task 14(작업 데이터 push).
- 2026-08-09 Claude: 리뷰 — 상한 절단이 '오래된 구간'을 삼키던 유실 2건 수정
                     (커밋: 최신부터 자름 / 태스크: 경계 초 잘림).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '.ai_monitor'))
sys.path.insert(0, str(_ROOT / 'scripts'))

MAX_PROJECTS = 20
MAX_TASKS = 100          # 1회 전송 상한. 콘솔 서버가 1코어라 한 번에 밀어붙이지 않는다.
MAX_COMMITS = 20         # 1회 전송 상한
SCAN_COMMITS = 500       # 조회 창 — 상한보다 넓게 봐야 '오래된 쪽 잘림'을 감지·보존한다
MAX_EVENTS_EACH = 20
BOOTSTRAP_HOURS = 24     # 커서가 없을 때 되짚는 범위 — 첫 실행에 수천 건을 쏟지 않기 위함
BOOTSTRAP_COMMITS = 3

# 태스크로 취급하지 않을 상태(콘솔의 open_tasks 계산과 짝) — 참고용 상수는 두지 않는다.
# 열림/닫힘 판정은 콘솔 db.list_projects 가 하고, 노드는 상태 문자열을 그대로 올린다.


# ── 공통 ────────────────────────────────────────────────────────────────────

def _iso(dt) -> str:
    """timestamptz · naive datetime · 문자열을 전부 ISO 문자열로 평탄화.

    [WHY 서버로 문자열을 보내나] 콘솔은 occurred_at 을 `::timestamptz` 로 캐스팅한다.
      숫자 epoch 를 보내면 캐스팅이 실패해 그 이벤트만 조용히 사라진다.
    """
    if isinstance(dt, str):
        return dt
    try:
        return dt.isoformat()
    except Exception:                                   # noqa: BLE001
        return ''


def _bootstrap_since() -> str:
    return (datetime.now(timezone.utc).astimezone()
            - timedelta(hours=BOOTSTRAP_HOURS)).isoformat(timespec='seconds')


def _git(path: Path, *args: str, timeout: int = 8) -> str:
    """[제약] 실패를 예외가 아니라 빈 문자열로 돌려준다. git 이 없는 노드
    (CipherTrader 학습 PC 처럼)에서도 나머지 수집은 계속돼야 한다."""
    try:
        r = subprocess.run(['git', '-C', str(path), *args],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout)
        return r.stdout if r.returncode == 0 else ''
    except Exception:                                   # noqa: BLE001
        return ''


def _git_ok(path: Path, *args: str) -> bool:
    """종료 코드만 본다.

    [WHY 따로 두나] `_git` 은 실패도 빈 문자열, '출력 없는 성공'도 빈 문자열이라
      둘을 구분할 수 없다. `cat-file -e` 처럼 성공 시 아무것도 안 찍는 명령은
      반드시 종료 코드로 판정해야 한다 — 아래 commit_events 의 사고가 그 예다.
    """
    try:
        r = subprocess.run(['git', '-C', str(path), *args],
                           capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:                                   # noqa: BLE001
        return False


def project_key(path: Path) -> str:
    url = _git(path, 'config', '--get', 'remote.origin.url').strip()
    if url:
        name = url.rstrip('/').rsplit('/', 1)[-1]
        if name.endswith('.git'):
            name = name[:-4]
        if name:
            return name
    return path.name


def _db_for(path: Path) -> str:
    """경로 → 프로젝트 DB 이름.

    [🔴 함정] resolve_project_db 는 VIBE_PG_DB 환경변수를 최우선으로 본다. 앱 안에서
      실행되면 그 값이 이미 잡혀 있어서, 여러 프로젝트를 순회해도 전부 **같은 DB**로
      접힌다(= 다른 프로젝트 태스크가 이 프로젝트 것으로 둔갑). 순회 중에는 env 를
      잠시 걷어내고 경로만으로 계산한다.
    """
    from pg_project import resolve_project_db          # 변환 규칙의 단일 원천

    old = os.environ.pop('VIBE_PG_DB', None)
    try:
        return resolve_project_db(path)
    finally:
        if old is not None:
            os.environ['VIBE_PG_DB'] = old


def discover() -> list[dict]:
    """관제 대상 프로젝트 목록 — {key, path, db}.

    세 곳을 합친다:
      ① `~/.apix/projects` (한 줄에 경로 하나) — 노드별 수동 지정. 가장 강하다.
      ② `.ai_monitor/config.json` 의 projects — 앱에 등록된 프로젝트
      ③ 이 저장소의 형제 디렉터리 중 git 리포 — 등록 전 프로젝트도 잡기 위함

    [WHY ③ 까지 훑나] 이 PC 에는 앱에 등록되지 않은 리포(ons·k-quant)가 있다.
      config 만 믿으면 콘솔에서 그 프로젝트들이 '없는 것'처럼 보인다 —
      조용한 프로젝트와 없는 프로젝트를 구분하는 게 관제판의 존재 이유다.
    """
    seen: dict[str, Path] = {}

    def add(p) -> None:
        try:
            path = Path(p).resolve()
        except Exception:                               # noqa: BLE001
            return
        if not path.is_dir() or not (path / '.git').exists():
            return
        seen.setdefault(str(path).lower(), path)

    try:
        for line in (Path.home() / '.apix' / 'projects').read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.startswith('#'):
                add(line.strip())
    except Exception:                                   # noqa: BLE001
        pass

    try:
        cfg = json.loads((_ROOT / '.ai_monitor' / 'config.json').read_text(encoding='utf-8'))
        for p in (cfg.get('projects') or {}).values():
            add(p)
    except Exception:                                   # noqa: BLE001
        pass

    try:
        for child in _ROOT.parent.iterdir():
            add(child)
    except Exception:                                   # noqa: BLE001
        pass

    add(_ROOT)

    # [🔴 key 중복 제거] 이 PC 에는 같은 리포의 사본·worktree 가 섞여 있다
    #   (`vibe-coding-auto` = 자율 데몬 worktree, `ons_build2` = 빌드 사본).
    #   전부 같은 remote 를 가리키므로 project_key 가 겹치는데, 그대로 두면 사본의
    #   뒤처진 HEAD 가 '이 프로젝트의 마지막 커밋'을 덮어써 화면이 과거로 되감긴다.
    #   먼저 발견된 경로(수동 지정 > config 등록 > 형제 스캔)를 정본으로 삼는다.
    out: list[dict] = []
    used: set[str] = set()
    for path in seen.values():
        key = project_key(path)
        if key in used:
            continue
        used.add(key)
        out.append({'key': key, 'path': path, 'db': _db_for(path)})
        if len(out) >= MAX_PROJECTS:
            break
    return out


# ── 로컬 PG 조회 ────────────────────────────────────────────────────────────

def _rows(db: str, sql: str, params: tuple) -> list[tuple]:
    """[WHY pg_base 를 재사용하나] 커넥션 keepalive 옵션(2026-07-20 죽은-소켓 hang
    사고 대응)이 거기 들어 있다. 여기서 psycopg2.connect 를 직접 부르면 그 방어가
    빠진 채로 5분마다 도는 스케줄 작업이 매달릴 수 있다.

    [제약] DB 가 없는 프로젝트(ons·k-quant 처럼 vibe DB 를 안 쓰는 리포)는 연결
      자체가 실패한다 — 그건 오류가 아니라 정상이므로 빈 리스트로 돌려준다.
    """
    conn = None
    try:
        from src import pg_base
        conn = pg_base.get_pool_conn(db)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:                                   # noqa: BLE001
        return []
    finally:
        if conn is not None:
            try:
                from src import pg_base
                pg_base.return_pool_conn(conn, db)
            except Exception:                           # noqa: BLE001
                pass


def tasks(proj: dict, since: str) -> tuple[list[dict], str]:
    """hive_tasks 증분. 반환: (전송할 태스크, 새 커서).

    [불변식] 커서는 updated_at(TEXT, ISO) 문자열 비교다. ISO 는 사전순=시간순이라
      캐스팅 없이 안전하고, 인덱스(idx_hive_tasks_updated)를 그대로 탄다.
    """
    cur = since or _bootstrap_since()
    rows = _rows(proj['db'], """
        SELECT id, title, status, updated_at
        FROM hive_tasks
        WHERE updated_at > %s
        ORDER BY updated_at ASC
        LIMIT %s
    """, (cur, MAX_TASKS))

    # [🔴 유실 방지] updated_at 은 '초' 해상도 TEXT 이고 조건은 strict `>`. 상한에 걸린
    #   상태로 경계 초를 잘라 커서를 그 초까지 밀면, 같은 초를 공유하는 나머지 태스크가
    #   영영 조회되지 않는다 — 일괄 UPDATE 한 번이면 수백 건이 같은 초를 갖는다.
    #   상한에 닿았을 때는 마지막 초 묶음을 통째로 다음 주기로 미룬다.
    #   (전부 같은 초라 미룰 게 없으면 그대로 보낸다 — 안 그러면 영원히 같은 100건 반복)
    if len(rows) >= MAX_TASKS:
        edge = str(rows[-1][3])
        trimmed = [r for r in rows if str(r[3]) != edge]
        if trimmed:
            rows = trimmed

    out = []
    for tid, title, status, updated in rows:
        out.append({'id': str(tid), 'project': proj['key'],
                    'title': (title or '')[:200], 'status': status or ''})
        if updated and str(updated) > cur:
            cur = str(updated)
    return out, cur


def commit_events(proj: dict, last_sha: str) -> tuple[list[dict], str]:
    """마지막으로 올린 커밋 이후의 커밋들.

    [WHY sha 커서인가] 시각 기준으로 자르면 rebase·cherry-pick 으로 과거 시각을 단
    커밋이 영영 누락된다. sha 범위(`last..HEAD`)는 그래프를 따라가므로 그런 구멍이 없다.

    [🔴 2026-08-09 사고] 처음에는 `last..HEAD` 의 출력이 비면 '커서 sha 가 없는
      리포'로 보고 최근 3개를 다시 잡았다. 그런데 **새 커밋이 없을 때도 출력은 똑같이
      비어 있다** — 정상 상태를 오류로 오인해 매 주기 같은 커밋을 영원히 재전송했다.
      서버 dedup_key 가 흡수해 화면은 멀쩡했고, 증상은 '조용한 낭비'뿐이라 드러나지
      않았다. 커서 유효성은 결과가 아니라 **sha 존재 여부**로 판정한다.
    """
    if last_sha and not _git_ok(proj['path'], 'cat-file', '-e', f'{last_sha}^{{commit}}'):
        last_sha = ''                                   # 리포 교체·히스토리 재작성 → 부트스트랩
    fmt = '--pretty=format:%H\x1f%aI\x1f%s'
    if last_sha:
        raw = _git(proj['path'], 'log', f'--max-count={SCAN_COMMITS}', fmt, f'{last_sha}..HEAD')
    else:
        raw = _git(proj['path'], 'log', f'-n{BOOTSTRAP_COMMITS}', fmt)

    lines = [ln for ln in raw.splitlines() if ln.strip()]

    # [🔴 유실 방지] git log 는 최신부터 준다. 여기에 그대로 상한을 걸면 잘려 나가는 쪽은
    #   **가장 오래된 구간**인데, 커서는 최신 sha 로 전진하므로 그 구간은 다시는 조회되지
    #   않는다(노드가 며칠 꺼졌다 켜지면 실제로 발생 — 5분 주기에선 안 드러난다).
    #   오래된 쪽부터 MAX_COMMITS 개만 보내고 커서도 딱 거기까지만 민다. 남은 건 다음 주기.
    lines.reverse()                                     # 최신→오래된  ⇒  오래된→최신
    lines = lines[:MAX_COMMITS]

    events, head = [], last_sha
    for line in lines:
        parts = line.split('\x1f')
        if len(parts) < 3:
            continue
        sha, when, subject = parts[0], parts[1], parts[2]
        head = sha                                      # 오래된→최신 순 ⇒ 마지막이 최신
        events.append({
            'kind': 'commit', 'project': proj['key'],
            'title': subject[:200], 'body': sha[:12],
            'occurred_at': when,
            'dedup_key': f'commit:{proj["key"]}:{sha[:12]}',
        })
    return events, (head or last_sha)


def checkpoint_events(proj: dict, since: str) -> tuple[list[dict], str]:
    """의도 단위 체크포인트 — '지금 무슨 생각으로 뭘 하고 있는가'.

    [WHY intent 가 빈 행은 버리나] active_session_context 는 훅이 매 프롬프트마다
      갱신해서 대부분의 행에 intent 가 없다. 그걸 다 올리면 콘솔이 빈 줄로 뒤덮여
      정작 의미 있는 체크포인트가 묻힌다.

    [불변식] 같은 행이 갱신되면 **새 사건**이다(dedup_key 에 updated_at 을 넣는다).
      id 만으로 접으면 의도가 바뀌어도 최초 1회만 보이고 그 뒤 변화가 사라진다.
    """
    cur = since or _bootstrap_since()
    rows = _rows(proj['db'], """
        SELECT id, terminal_id, intent, next_step, updated_at
        FROM active_session_context
        WHERE intent <> '' AND updated_at > %s::timestamptz
        ORDER BY updated_at ASC
        LIMIT %s
    """, (cur, MAX_EVENTS_EACH))
    out = []
    for cid, term, intent, nxt, updated in rows:
        stamp = _iso(updated)
        out.append({
            'kind': 'checkpoint', 'project': proj['key'],
            'title': f'[{term}] {intent}'[:200],
            'body': (f'다음: {nxt}' if nxt else ''),
            'occurred_at': stamp,
            'dedup_key': f'ckpt:{proj["key"]}:{cid}:{stamp}',
        })
        if stamp > cur:
            cur = stamp
    return out, cur


def incident_events(proj: dict, last_id: int) -> tuple[list[dict], int]:
    """사고 장부 — 무엇이 터졌고 어떻게 고쳤나.

    [WHY id 커서인가] incident_ledger 는 재발 시 last_seen_at 만 갱신되고 행은 그대로다.
      시각 커서를 쓰면 같은 사고가 재발할 때마다 새 이벤트로 다시 올라와 화면이 겹친다.
      '새로 기록된 사고'만 사건이므로 id 단조 증가가 정확한 기준이다.
    """
    cur = int(last_id or 0)
    rows = _rows(proj['db'], """
        SELECT id, error_text, root_cause, fix_description, created_at
        FROM incident_ledger
        WHERE id > %s
        ORDER BY id ASC
        LIMIT %s
    """, (cur, MAX_EVENTS_EACH))
    out = []
    for iid, err, cause, fix, created in rows:
        out.append({
            'kind': 'incident', 'project': proj['key'],
            'title': (err or '(내용 없음)').strip().splitlines()[0][:200],
            'body': f'원인: {cause or "-"}\n수정: {fix or "-"}'[:1000],
            'occurred_at': _iso(created),
            'dedup_key': f'incident:{proj["key"]}:{iid}',
        })
        cur = max(cur, int(iid))
    return out, cur


if __name__ == '__main__':
    # 수동 점검용 — 무엇이 잡히는지 눈으로 본다. 전송은 apix_push.py 가 한다.
    for p in discover():
        t, _ = tasks(p, '')
        c, _ = commit_events(p, '')
        k, _ = checkpoint_events(p, '')
        i, _ = incident_events(p, 0)
        print(f'{p["key"]:<14} db={p["db"]:<24} tasks={len(t):<4} '
              f'commits={len(c):<3} ckpt={len(k):<3} incidents={len(i)}')
