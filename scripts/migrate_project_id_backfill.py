"""
FILE: scripts/migrate_project_id_backfill.py
DESCRIPTION: Platform Phase 2 단계 3 — 미존재 컬럼 추가 후 데이터 backfill.

             스키마 업그레이드(ALTER TABLE ADD COLUMN)는 ensure_schema()가
             수행하며, 이 스크립트는 오직 기존 데이터를 정규 슬러그로
             backfill하는 역할만 한다.

             [대상 테이블] — .ai_monitor/src/pg_store.py의
             _layer1_project_id_tables와 동일
             - zettel_links, agent_experience, agent_heartbeats, agent_stats,
               active_session_context, hive_skill_chains, hive_state,
               office_profile_state, office_profiles, pg_messages, task_comments

             [사용법]
             python scripts/migrate_project_id_backfill.py          # 드라이런 (기본)
             python scripts/migrate_project_id_backfill.py --apply  # 실제 UPDATE 수행

REVISION HISTORY:
- 2026-04-19 Claude: 최초 작성 — Platform Phase 2 단계 3
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path


if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITOR_DIR = PROJECT_ROOT / ".ai_monitor"
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, execute, query_rows  # type: ignore


DATA_DIR = MONITOR_DIR / "data"
CANONICAL_SLUG = "D--vibe-coding"


LAYER1_TABLES = [
    "zettel_links",
    "agent_experience",
    "agent_heartbeats",
    "agent_stats",
    "active_session_context",
    "hive_skill_chains",
    "hive_state",
    "office_profile_state",
    "office_profiles",
    "pg_messages",
    "task_comments",
]


def _distribution(table: str) -> list[dict]:
    sql = (
        f"SELECT COALESCE(NULLIF(project_id, ''), '(empty/null)') AS pid, "
        f"COUNT(*) AS cnt FROM {table} "
        f"GROUP BY pid ORDER BY cnt DESC;"
    )
    return query_rows(sql)


def _print_table(table: str, rows: list[dict]) -> int:
    """분포 출력 + 변경 예정 건수 반환."""
    print(f"\n  [{table}]")
    if not rows:
        print("    (행 없음)")
        return 0
    total = 0
    to_change = 0
    for r in rows:
        pid = str(r.get("pid", ""))
        cnt = int(r.get("cnt", 0))
        total += cnt
        if pid == CANONICAL_SLUG:
            mark = "  "
        else:
            mark = "→ "
            to_change += cnt
        print(f"    {mark}{pid:<30} {cnt:>6}")
    print(f"    {'-' * 40}")
    print(f"    {'TOTAL':<30} {total:>6}  (변경 예정 {to_change}건)")
    return to_change


def _dryrun() -> int:
    print("=" * 60)
    print(" Platform Phase 2 단계 3 — project_id backfill")
    print(f" 정규 슬러그: {CANONICAL_SLUG!r}")
    print("=" * 60)

    total_changes = 0
    for tbl in LAYER1_TABLES:
        rows = _distribution(tbl)
        total_changes += _print_table(tbl, rows)

    print("\n" + "=" * 60)
    print(f" 변경 예정 총합: {total_changes}건")
    print("=" * 60)
    return total_changes


def _apply() -> None:
    print("\n[APPLY] UPDATE 실행...")
    for tbl in LAYER1_TABLES:
        sql = (
            f"UPDATE {tbl} SET project_id = '{CANONICAL_SLUG}' "
            f"WHERE COALESCE(project_id, '') <> '{CANONICAL_SLUG}';"
        )
        ok = execute(sql)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {tbl}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Platform Phase 2 단계 3 — project_id backfill",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 UPDATE 수행 (기본: 드라이런)",
    )
    args = parser.parse_args()

    # ensure_schema()가 ALTER TABLE ADD COLUMN IF NOT EXISTS를 자동 적용
    # — 이 스크립트 실행만으로 스키마도 함께 업그레이드됨.
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL 사용 불가. 서버가 실행 중이고 스키마가 초기화됐는지 확인.")
        sys.exit(1)

    print("[전] 현재 분포")
    total_changes = _dryrun()

    if not args.apply:
        print("\n드라이런 모드 — 변경 없음.")
        print("실제 적용은 --apply 추가.")
        return

    if total_changes == 0:
        print("\n변경할 건이 없음. 종료.")
        return

    _apply()

    print("\n[후] 재조회")
    _dryrun()


if __name__ == "__main__":
    main()
