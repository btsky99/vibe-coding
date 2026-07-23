# -*- coding: utf-8 -*-
"""
FILE: scripts/auto_metrics.py
DESCRIPTION: 자율 heartbeat 데몬(claude-auto) 실효 계측 리포트 — 채택률/blocked율/게이트 차단/자가발굴 비율을
             집계해 'P2 기능을 얹을 가치가 있는가'를 데이터로 판정한다. 순수 읽기(psql+git), DB/데몬 무변경.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — 관찰+계측 우선(lessons '작동 가정 말고 계측'+궁극목표 '삽질 감소') 방향으로 P2 전 실측 도구.
"""
# [WHY] 새 계측 컬럼을 안 만든다 — 데몬이 이미 pg_logs(status·metadata.task_id·commits)와
# hive_tasks(status·result·source)에 충분히 남기므로 집계 리포트만 붙이면 된다.
# [불변식] 자율이 실제 처리한 태스크 식별 = pg_logs(agent='claude-auto').metadata->>'task_id' 집합.
#   created_by/source만으로는 '큐에서 집어 처리한 남의 태스크'를 놓친다.
# [제약] '[게이트 차단]' 문구는 heartbeat_daemon.py에만 존재 → result LIKE로 자율 게이트만 정확히 걸린다.
import os
import sys
import tempfile
import subprocess
from datetime import datetime

try:
    from pg_project import resolve_project_db
except ImportError:
    from scripts.pg_project import resolve_project_db

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")
PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')
PG_DB = resolve_project_db(PROJECT_ROOT)
AGENT_ID = 'claude-auto'          # heartbeat_daemon.AGENT_ID 와 동일해야 함
AUTO_BRANCH_PREFIX = 'auto/task-'  # heartbeat_daemon 이 태스크마다 만드는 격리 브랜치

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _run_query(sql: str) -> list[list[str]]:
    """psql --csv 실행 → 헤더 제외한 행 리스트(각 행은 컬럼 문자열 리스트). 실패 시 빈 리스트.

    [과거사고 2026-07-19] 한글 리터럴('%게이트 차단%')을 psql -c argv로 넘기면 Windows가
    인자를 cp949로 인코딩 → 서버 UTF8과 불일치로 'invalid byte sequence 0xb0' 쿼리 전체 실패.
    argv 경로는 msvcrt ANSI 변환을 못 피하므로, SQL을 UTF-8 임시파일에 쓰고 -f + PGCLIENTENCODING=UTF8
    로 실행한다. -f 파일은 client_encoding대로 읽히므로 진짜 UTF-8 바이트가 정상 해석된다.
    """
    env = {**os.environ, 'PGCLIENTENCODING': 'UTF8'}
    path = None
    try:
        # delete=False + 즉시 close: Windows는 열린 파일을 다른 프로세스(psql)가 못 여는 경우가 있음.
        with tempfile.NamedTemporaryFile('w', suffix='.sql', encoding='utf-8',
                                         delete=False) as fh:
            fh.write(sql)
            path = fh.name
        res = subprocess.run(
            [PG_BIN, "-p", str(PG_PORT), "-U", "postgres", "-d", PG_DB, "-f", path, "--csv"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_NO_WINDOW, env=env,
        )
        lines = [ln for ln in res.stdout.strip().splitlines() if ln]
        if len(lines) <= 1:
            return []
        # [주의] CSV 값에 콤마가 없다는 전제 — 집계 쿼리는 숫자/짧은 라벨만 SELECT 하므로 안전.
        return [ln.split(',') for ln in lines[1:]]
    except Exception:
        return []
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _git(args: list[str]) -> str:
    """git 서브프로세스 stdout. 실패해도 리포트는 계속되도록 예외를 삼킨다."""
    try:
        res = subprocess.run(
            ["git", "-C", PROJECT_ROOT, *args],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_NO_WINDOW,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def _pct(n: int, total: int) -> str:
    return f"{(100.0 * n / total):.0f}%" if total else "—"


def _cycle_results(days: int) -> dict:
    """pg_logs 기준 자율 사이클 결과 — success(done)/error(blocked·fail) 분포. 신뢰 소스."""
    rows = _run_query(
        f"SELECT status, COUNT(*) FROM pg_logs "
        f"WHERE agent = '{AGENT_ID}' AND ts > NOW() - INTERVAL '{days} days' "
        f"GROUP BY status;"
    )
    return {r[0]: int(r[1]) for r in rows if len(r) >= 2}


def _task_outcomes(days: int) -> dict:
    """자율이 실제 처리한 hive_tasks(=pg_logs metadata.task_id로 조인)의 상태/사유 분포.

    [WHY] created_by='claude-auto'만 보면 자가발굴만 잡히고 큐에서 집은 태스크를 누락한다.
    pg_logs가 매 사이클 metadata에 task_id를 남기므로 그 집합이 '자율이 손댄 것'의 정답이다.
    """
    rows = _run_query(
        f"WITH auto_tasks AS ("
        f"  SELECT DISTINCT (metadata->>'task_id') AS tid FROM pg_logs "
        f"  WHERE agent = '{AGENT_ID}' AND ts > NOW() - INTERVAL '{days} days' "
        f"    AND metadata->>'task_id' IS NOT NULL AND metadata->>'task_id' <> '' "
        f") "
        f"SELECT t.status, COUNT(*) AS n, "
        f"  COUNT(*) FILTER (WHERE t.result LIKE '%게이트 차단%') AS gate, "
        f"  COUNT(*) FILTER (WHERE t.source = 'self') AS self_found "
        f"FROM hive_tasks t JOIN auto_tasks a ON t.id::text = a.tid "
        f"GROUP BY t.status ORDER BY n DESC;"
    )
    out = {'by_status': {}, 'gate_blocked': 0, 'self_found': 0, 'total': 0}
    for r in rows:
        if len(r) < 4:
            continue
        status, n, gate, self_n = r[0], int(r[1]), int(r[2]), int(r[3])
        out['by_status'][status] = n
        out['gate_blocked'] += gate
        out['self_found'] += self_n
        out['total'] += n
    return out


def _adoption() -> dict:
    """채택률 = auto/task-* 격리 브랜치 중 main 에 머지된 비율. ⭐ 궁극목표(삽질 감소) 판정선.

    [WHY] done/blocked는 데몬 자체 판정일 뿐 — 사람이 그 결과물을 실제로 채택(머지)했는지가
    '자율이 진짜 쓸모 있나'의 최종 답이다. git 머지 여부만이 이를 증명한다.
    """
    all_branches = [b.strip() for b in _git(
        ["for-each-ref", "--format=%(refname:short)", f"refs/heads/{AUTO_BRANCH_PREFIX}*"]
    ).splitlines() if b.strip()]
    if not all_branches:
        return {'total': 0, 'merged': 0, 'open': 0, 'open_list': []}
    merged = set(b.strip() for b in _git(
        ["branch", "--merged", "main", "--format=%(refname:short)"]
    ).splitlines() if b.strip())
    merged_autos = [b for b in all_branches if b in merged]
    open_autos = [b for b in all_branches if b not in merged]
    return {'total': len(all_branches), 'merged': len(merged_autos),
            'open': len(open_autos), 'open_list': open_autos}


def print_report(days: int = 7) -> None:
    print("\n" + "=" * 60)
    print(f"🤖 자율 오토 데몬 실효 계측 ({AGENT_ID}) — 최근 {days}일")
    print(f"   생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | DB: {PG_DB}")
    print("=" * 60)

    # [1] 사이클 결과 (pg_logs 신뢰 소스)
    cyc = _cycle_results(days)
    done = cyc.get('success', 0)
    fail = sum(v for k, v in cyc.items() if k != 'success')
    total_cyc = done + fail
    print(f"\n[1] 실행 사이클: 총 {total_cyc}건")
    print(f"    ✅ 완주(done)   {done:>3}  ({_pct(done, total_cyc)})")
    print(f"    ❌ 차단·실패     {fail:>3}  ({_pct(fail, total_cyc)})")
    if cyc and total_cyc == 0:
        print("    (아직 자율 사이클 로그 없음 — 데몬을 켜고 며칠 관찰 필요)")

    # [2] 처리 태스크 상세 (hive_tasks 조인)
    t = _task_outcomes(days)
    print(f"\n[2] 처리 태스크: 총 {t['total']}건 (pg_logs task_id ⨝ hive_tasks)")
    for status, n in t['by_status'].items():
        print(f"    · {status:<10} {n:>3}  ({_pct(n, t['total'])})")
    print(f"    🛡️ 게이트 차단   {t['gate_blocked']:>3}  ← P0 게이트가 실제로 막은 산출물")
    print(f"    🔍 자가발굴(self) {t['self_found']:>3}  ({_pct(t['self_found'], t['total'])}) — 스스로 찾은 일")

    # [3] 채택률 (git 머지) — 핵심 지표
    a = _adoption()
    print(f"\n[3] ⭐ 채택률: auto/task-* {a['total']}개 중 main 머지 {a['merged']}개  ({_pct(a['merged'], a['total'])})")
    if a['open']:
        preview = ', '.join(a['open_list'][:6]) + (f" 외 {a['open'] - 6}개" if a['open'] > 6 else '')
        print(f"    ⏳ 미머지 {a['open']}개: {preview}")
    if a['total'] == 0:
        print("    (auto/task-* 브랜치 없음 — 아직 자율 작업 산출물 없음)")

    # [해석 가이드] 다음 세션 LLM이 P2 결정에 쓰도록 판정 기준을 남긴다.
    print("\n[판정 가이드]")
    print("    · 채택률 높음  → 자율이 쓸모 있음 → P2(테스트 게이트/머지 자동화)로 확장 정당")
    print("    · 게이트 차단↑ → P0 안전장치가 값을 함 (없었으면 오염 커밋)")
    print("    · 완주 낮음·차단↑ → 프롬프트/발굴 소스 품질 문제 → 확장보다 튜닝 우선")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    if not os.path.exists(PG_BIN):
        print(f"[오류] PostgreSQL 바이너리를 찾을 수 없습니다: {PG_BIN}")
        sys.exit(1)
    _days = 7
    if len(sys.argv) > 1:
        try:
            _days = int(sys.argv[1])
        except ValueError:
            print(f"[경고] 일수 인자 무시 (정수 아님): {sys.argv[1]}")
    print_report(_days)
