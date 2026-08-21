"""
FILE: scripts/log_health.py
DESCRIPTION: 작업 기록(pg_logs)이 살아 있는지 **독립 기준으로** 재는 계기판.
             git 커밋 수를 자로 써서 「일이 없었던 날」과 「기록이 샌 날」을 가른다.
             읽기 전용 — DB 에 아무것도 쓰지 않는다.

REVISION HISTORY:
- 2026-08-21 Claude: 신설. 로깅이 2026-08-18~21 나흘간 통째로 죽어 있었는데
  아무도 몰랐다(4df3c5f). 원인은 폴백이 한글을 CP949 로 넘긴 것이었고,
  실패는 1,878번 기록됐는데 **이유는 0번** 기록됐다. 고친 것으로 끝내면
  같은 계열의 다음 사고를 또 넉 달 뒤에 안다 — 그래서 재는 자리를 만든다.
"""

# [WHY 이 스크립트가 필요한가]
#   기록 수만 세면 「그날 일이 없었다」와 「기록이 샜다」가 똑같아 보인다.
#   그래서 **훅과 무관하게 남는 것**을 자로 써야 한다. git 커밋이 그것이다.
#   훅은 커밋마다 `[커밋 시작]` 을 남기게 돼 있다(hive_hook.py:831).
#   🔴 다만 이 자는 완벽하지 않다 — 앱 자체 git 기능(api/git_api.py)이나
#   다른 세션으로 커밋하면 훅을 안 거쳐 기록이 안 남는다. 실제로 2026-08-15 가
#   그런 날로 보인다(커밋 31건 · [커밋 시작] 1건, docs/HANDOFF.md 3장).
#   그래서 이 스크립트는 **판정하지 않고 눈에 띄게만 한다.**
#
# [불변식] 읽기 전용. SELECT 와 git log 만 쓴다. 여기서 DB 를 고치면
#   "재는 장치가 재는 대상을 바꾸는" 꼴이 된다.
#
# [제약] 훅에서 부르지 마라. 이 스크립트는 stdout 에 표를 찍는다 —
#   훅 경로에서 stdout/stderr 는 양쪽 다 막혀 있다(hive_bridge._diag docstring).
#   사람이 부르거나, 데몬이 부르고 결과를 파일로 받는 용도다.

import os
import sys
import subprocess
from datetime import date, timedelta

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# [WHY 재구현하지 않고 빌려 쓰나] psql 을 부르는 올바른 방법(stdin 으로 UTF-8,
#   PGCLIENTENCODING=UTF8)이 이미 hive_bridge._run_psql 에 있다. 여기서 다시
#   짜면 **바로 그 한글 사고를 이 파일에서 되풀이한다.** 한 자리에 둔다.
import hive_bridge as _hb

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # 규칙 10 — 창을 띄우지 않는다


def _git_commits_by_day(root: str, days: int) -> dict:
    """날짜(MM-DD) → 그날 커밋 수. git 이 없거나 실패하면 빈 dict."""
    try:
        res = subprocess.run(
            ['git', '-C', root, 'log', f'--since={days} days ago',
             '--pretty=%ad', '--date=format:%m-%d'],
            capture_output=True, timeout=30, creationflags=_NO_WINDOW,
        )
        if res.returncode != 0:
            return {}
        out = (res.stdout or b'').decode('utf-8', 'replace')
    except Exception:
        return {}
    counts: dict = {}
    for line in out.splitlines():
        d = line.strip()
        if d:
            counts[d] = counts.get(d, 0) + 1
    return counts


def _logs_by_day(days: int) -> dict:
    """날짜(MM-DD) → (전체 기록 수, `[커밋 시작]` 수). 조회 실패면 빈 dict."""
    # [함정] 여기서 파이썬 % 서식을 쓰면 안 된다 — SQL 의 LIKE 와일드카드 '%' 와
    #   충돌해 ValueError 가 난다(2026-08-21 실측). 값은 문자열로 이어 붙인다.
    #   days 는 위에서 정수로 강제되므로 주입 위험은 없다.
    sql = (
        "SELECT to_char(created_at,'MM-DD') d, COUNT(*), "
        "COUNT(*) FILTER (WHERE task LIKE '[커밋 시작]%') "
        "FROM pg_logs WHERE created_at >= CURRENT_DATE - INTERVAL '"
        + str(int(days)) + " days' GROUP BY 1 ORDER BY 1;"
    )
    raw = _hb._run_psql(sql)
    if not raw or raw == 'OK':
        return {}
    rows: dict = {}
    for line in raw.splitlines():
        # psql 기본 출력은 ' 08-14 | 1139 | 9' 꼴. 구분자 개수로 데이터 줄만 고른다.
        parts = [p.strip() for p in line.split('|')]
        if len(parts) != 3:
            continue
        try:
            rows[parts[0]] = (int(parts[1]), int(parts[2]))
        except ValueError:
            continue  # 머리글·구분선·'(N개 행)' 꼬리
    return rows


def report(days: int = 14) -> int:
    """표를 찍고 **의심스러운 날의 수**를 반환한다.

    [WHY 종료코드로 판정하지 않나] 이 자는 오탐이 난다(위 주석 참고).
    자동화가 이 값으로 무언가를 막으면 그 오탐이 작업을 막는다 —
    이 저장소는 이미 그 계열의 사고를 두 번 밟았다(94f466d, 71ca8eb).
    그래서 **세기만 하고 막지 않는다.**
    """
    root = os.path.dirname(_SCRIPT_DIR)
    commits = _git_commits_by_day(root, days)
    logs = _logs_by_day(days)

    if not logs:
        print('[!] pg_logs 를 못 읽었다 — PostgreSQL 이 꺼져 있거나 psql 호출이 실패했다.')
        print('    진단 로그를 봐라: .ai_monitor/hive_bridge.log')
        return 0

    today = date.today()
    order = [(today - timedelta(days=i)).strftime('%m-%d') for i in range(days, -1, -1)]

    print('날짜   | git 커밋 | 전체 기록 | [커밋 시작] | 비고')
    print('-------+----------+-----------+-------------+---------------------------')
    suspect = 0
    for d in order:
        c = commits.get(d, 0)
        total, cstart = logs.get(d, (0, 0))
        note = ''
        # 🔴 제일 중요한 신호 — 일한 흔적(커밋)은 있는데 기록이 통째로 없는 날.
        #    2026-08-18~21 이 정확히 이 모양이었다.
        if c > 0 and total == 0:
            note = '🔴 일한 흔적은 있는데 기록이 0건'
            suspect += 1
        elif c > 0 and cstart == 0:
            note = '⚠ 커밋 기록만 빠졌다'
            suspect += 1
        print(f'{d}  | {c:8d} | {total:9d} | {cstart:11d} | {note}')

    print()
    if suspect:
        print(f'[!] 살펴볼 날 {suspect}건. 🔴 이것만으로 고장이라고 단정하지 마라 —')
        print('    앱 자체 git 기능이나 다른 세션으로 커밋하면 훅을 안 거쳐 정상적으로도 이렇게 보인다.')
        print('    다음에 볼 곳: .ai_monitor/hive_bridge.log 의 [ERROR] 줄과 그 사유.')
    else:
        print('[o] 커밋이 있는 날은 모두 기록이 남아 있다.')
    return suspect


if __name__ == '__main__':
    # [제약] 한국어 윈도우 콘솔은 cp949 라 이모지·일부 글자에서 print 가 죽는다.
    #   같은 사고를 hook_bridge._notify 에서 이미 밟았다(502ea41). 출력을 UTF-8 로 고정한다.
    # [함정] sys.stdout 을 TextIOWrapper 로 **갈아끼우면 안 된다** — 옛 stdout 이
    #   회수되면서 밑의 버퍼를 닫아 'I/O operation on closed file' 로 죽는다
    #   (2026-08-21 실측). reconfigure 는 같은 객체를 고쳐 그 문제가 없다.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    _days = 14
    if len(sys.argv) > 1:
        try:
            _days = max(1, min(90, int(sys.argv[1])))
        except ValueError:
            pass
    report(_days)
