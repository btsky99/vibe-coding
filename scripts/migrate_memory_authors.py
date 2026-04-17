"""
FILE: scripts/migrate_memory_authors.py
DESCRIPTION: 하이브 메모리 author 컬럼 정규화 스크립트.

REVISION HISTORY:
- 2026-04-17 초판 — B.2 작성자 태그 강화에 따른 레거시 'agent'/'unknown' 값 정비.

기본 모드는 드라이런(통계만). `--apply` 지정 시 실제 UPDATE 수행.
- 'agent' → 'legacy' 로 리네임 (과거 기본값이었음을 표식)
- 'unknown' 은 그대로 유지 (정체 불명은 보존)
- --force-env 지정 시 HIVE_AGENT_ID 값으로 unknown/legacy 전체 덮어쓰기 (신중히)
"""

import argparse
import io
import os
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

from src.pg_store import ensure_schema, execute, query_rows, _sql_text  # type: ignore


DATA_DIR = MONITOR_DIR / "data"


def collect_stats() -> list[dict]:
    rows = query_rows(
        "SELECT author, COUNT(*) AS cnt FROM hive_memory GROUP BY author ORDER BY cnt DESC;"
    )
    return rows


def print_stats(rows: list[dict]) -> None:
    print("\n=== hive_memory author 분포 ===")
    total = 0
    for r in rows:
        cnt = int(r.get('cnt', 0))
        total += cnt
        print(f"  {r.get('author', '') or '(empty)':<30} {cnt:>6}")
    print(f"  {'-' * 38}")
    print(f"  {'TOTAL':<30} {total:>6}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="hive_memory author 정규화")
    parser.add_argument("--apply", action="store_true", help="실제 UPDATE 수행 (기본: 드라이런)")
    parser.add_argument("--force-env", action="store_true",
                        help="HIVE_AGENT_ID 값으로 unknown/legacy 덮어쓰기")
    args = parser.parse_args()

    if not ensure_schema(DATA_DIR):
        print("PostgreSQL 사용 불가.")
        sys.exit(1)

    print("[전] 현재 상태")
    print_stats(collect_stats())

    if not args.apply:
        print("드라이런 모드 — 변경 없음. 실제 적용은 --apply 추가.")
        return

    # 1) 'agent' → 'legacy' 리네임
    rename_sql = "UPDATE hive_memory SET author = 'legacy' WHERE LOWER(author) = 'agent';"
    execute(rename_sql)
    print("[OK] 'agent' → 'legacy' 리네임 완료")

    # 2) --force-env 지정 시 env 값으로 unknown/legacy 덮어쓰기
    if args.force_env:
        env_val = (os.environ.get('HIVE_AGENT_ID', '') or '').strip().lower()
        if not env_val:
            print("[SKIP] HIVE_AGENT_ID 환경변수 미설정 — 강제 덮어쓰기 건너뜀")
        else:
            sql = (
                f"UPDATE hive_memory SET author = {_sql_text(env_val)} "
                f"WHERE LOWER(author) IN ('unknown', 'legacy');"
            )
            execute(sql)
            print(f"[OK] unknown/legacy → '{env_val}' 덮어쓰기 완료")

    print("\n[후] 마이그레이션 결과")
    print_stats(collect_stats())


if __name__ == "__main__":
    main()
