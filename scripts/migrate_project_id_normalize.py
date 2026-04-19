"""
FILE: scripts/migrate_project_id_normalize.py
DESCRIPTION: Platform Phase 2 — 단계 1. project / project_id 값 정규화.
             컬럼 구조는 건드리지 않고 "값만" 정규 슬러그로 통일한다.
             단계 2(RENAME), 단계 3(ADD COLUMN)은 별도 스크립트로 진행.

             [정책]
             - 정규 슬러그: 'D--vibe-coding' (기존 pg_logs 주류 값)
             - 현재 DB는 이 단일 리포에서만 활성이므로, 이 리포 이외의
               오염 값/임시 값/빈 값은 모두 정규 슬러그로 통합한다.
             - 멀티 프로젝트 활성화(Phase 2 이후)부터는 이 스크립트 금지.

             [대상 테이블] (단계 2 RENAME 이후 컬럼명은 전부 project_id)
             - hive_memory.project_id     (오염 값 매핑 — 완료)
             - zettel_notes.project_id    ('vibe-coding' → 'D--vibe-coding' — 완료)
             - hive_sessions.project_id   ('hive','test_proj' → 'D--vibe-coding' — 완료)
             - pg_logs.project_id         (empty 341건 backfill — 완료)
             - hive_tasks.project_id      (empty 1,145건 backfill — 완료)

             [사용법]
             python scripts/migrate_project_id_normalize.py          # 드라이런 (기본)
             python scripts/migrate_project_id_normalize.py --apply  # 실제 UPDATE 수행

REVISION HISTORY:
- 2026-04-19 Claude: 최초 작성 — Platform Phase 2 단계 1
- 2026-04-19 Claude: 단계 2 RENAME 완료 반영 — TARGETS 컬럼명을 project_id로 갱신
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


# (테이블, 컬럼, 설명) — 단계 2 RENAME 이후 모든 컬럼이 project_id
TARGETS: list[tuple[str, str, str]] = [
    ("hive_memory",   "project_id", "지식 메모리"),
    ("zettel_notes",  "project_id", "제텔카스텐 노트"),
    ("hive_sessions", "project_id", "세션 컨텍스트"),
    ("pg_logs",       "project_id", "활동 로그"),
    ("hive_tasks",    "project_id", "태스크 큐"),
]


def _current_distribution(table: str, column: str) -> list[dict]:
    """해당 테이블/컬럼의 현재 분포를 반환.
    empty 문자열과 NULL을 '(empty/null)'로 합친다.
    """
    sql = (
        f"SELECT COALESCE(NULLIF({column}, ''), '(empty/null)') AS pid, "
        f"COUNT(*) AS cnt FROM {table} "
        f"GROUP BY pid ORDER BY cnt DESC;"
    )
    return query_rows(sql)


def _print_distribution(table: str, column: str, rows: list[dict]) -> int:
    """분포 출력 + 변경 예정 건수 반환."""
    print(f"\n  [{table}.{column}]")
    total = 0
    to_change = 0
    for r in rows:
        pid = str(r.get("pid", ""))
        cnt = int(r.get("cnt", 0))
        total += cnt
        mark = "  " if pid == CANONICAL_SLUG else "→ "
        if pid != CANONICAL_SLUG:
            to_change += cnt
        print(f"    {mark}{pid:<30} {cnt:>6}")
    print(f"    {'-' * 40}")
    print(f"    {'TOTAL':<30} {total:>6}  (변경 예정 {to_change}건)")
    return to_change


def _dryrun() -> int:
    """현재 상태 출력 + 변경 예정 총합 반환."""
    print("=" * 60)
    print(" Platform Phase 2 단계 1 — project_id 값 정규화")
    print(f" 정규 슬러그: {CANONICAL_SLUG!r}")
    print("=" * 60)

    total_changes = 0
    for table, column, desc in TARGETS:
        rows = _current_distribution(table, column)
        changes = _print_distribution(table, column, rows)
        total_changes += changes

    print("\n" + "=" * 60)
    print(f" 변경 예정 총합: {total_changes}건")
    print("=" * 60)
    return total_changes


def _apply() -> None:
    """정규 슬러그가 아닌 모든 값을 CANONICAL_SLUG로 통일.
    empty/NULL도 포함 (NULLIF 없이 직접 비교).
    """
    print("\n[APPLY] UPDATE 실행...")
    for table, column, desc in TARGETS:
        # 안전: 현재 값이 정규 슬러그가 아니면 모두 덮어쓰기
        # NULL도 함께 처리 (COALESCE로 '' 취급 후 비교)
        sql = (
            f"UPDATE {table} SET {column} = '{CANONICAL_SLUG}' "
            f"WHERE COALESCE({column}, '') <> '{CANONICAL_SLUG}';"
        )
        ok = execute(sql)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {table}.{column}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Platform Phase 2 단계 1 — project_id 값 정규화",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 UPDATE 수행 (기본: 드라이런)",
    )
    args = parser.parse_args()

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
