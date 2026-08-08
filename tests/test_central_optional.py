"""
FILE: tests/test_central_optional.py
DESCRIPTION: 🔴 중앙 서버를 쓰지 않는 사용자에게 아무 변화가 없음을 고정하는 회귀 테스트.
             Phase 3의 통과 조건 — 이게 깨지면 중앙 기능을 더 얹지 않는다.

REVISION HISTORY:
- 2026-08-08 Claude: 신규 (아픽스 중앙 대화 PG Task 5).
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
sys.path.insert(0, str(_AI_MONITOR))

# 중앙 테이블 이름 — 로컬 어디에도 나타나면 안 되는 문자열.
_CENTRAL_TABLES = ("agent_messages", "message_cursors")

# 로컬 스키마/부팅 경로 파일. 여기에 중앙 DDL이 스며들면 설정 없는 사용자의 로컬 DB가 오염된다.
_LOCAL_SCHEMA_FILES = (
    _AI_MONITOR / "src" / "pg_schema.py",
    _AI_MONITOR / "src" / "pg_base.py",
    _AI_MONITOR / "src" / "pg_store.py",
)


@pytest.mark.parametrize("path", _LOCAL_SCHEMA_FILES, ids=lambda p: p.name)
def test_local_schema_never_mentions_central_tables(path):
    """[🔴 불변식] 중앙 스키마는 pg_central.py 안에서, 연결 성립 후에만 만들어진다.

    pg_schema.ensure_schema()는 모든 사용자의 로컬 DB에서 무조건 돈다 —
    여기에 중앙 DDL이 한 줄이라도 들어가면 중앙을 안 쓰는 사람의 DB에도 테이블이 생긴다.
    """
    source = path.read_text(encoding='utf-8')
    for table in _CENTRAL_TABLES:
        assert table not in source, f"{path.name}에 중앙 테이블 '{table}' 언급이 있다"


def test_boot_modules_do_not_import_pg_central():
    """부팅 경로가 중앙 모듈에 의존하기 시작하면 '서버가 꺼져도 앱은 멀쩡하다'가 깨진다.

    [갱신 시점] Task 9(API 라우트)/Task 10(LISTEN)에서 중앙을 붙일 때, 그 지점이
    부팅 경로가 아니라 요청/데몬 경로임을 확인하고 이 목록을 조정할 것.
    """
    for name in ("server.py", "infra/app_boot.py", "infra/daemons.py", "src/pg_schema.py"):
        path = _AI_MONITOR / name
        if not path.exists():
            continue
        source = path.read_text(encoding='utf-8')
        assert "pg_central" not in source, f"{name}이 pg_central을 임포트한다"


def test_importing_pg_central_opens_no_socket(monkeypatch):
    """import 부작용으로 연결을 맺으면 안 된다 — 부팅이 서버 응답 시간에 묶인다."""
    import psycopg2

    def _boom(*a, **kw):
        raise AssertionError("import 시점에 connect가 호출됐다")

    monkeypatch.setattr(psycopg2, "connect", _boom)
    for mod in ("src.pg_central", "src.node_identity"):
        sys.modules.pop(mod, None)
    import src.pg_central  # noqa: F401


def test_local_db_has_no_central_tables():
    """살아있는 로컬 DB에 중앙 테이블이 실제로 없는지 확인한다.

    [🔴 함정] query_rows는 예외를 삼키고 빈 목록을 돌려준다 — PG가 꺼져 있으면
      "중앙 테이블 0건"으로 보여 무조건 통과한다. 그래서 먼저 알려진 테이블(pg_logs)이
      보이는지 양성 대조를 하고, 안 보이면 판정하지 않고 skip 한다.
    """
    from src.pg_base import query_rows

    control = query_rows(
        "SELECT 1 AS ok FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='pg_logs'"
    )
    if not control:
        pytest.skip("로컬 PostgreSQL 미가동 — 양성 대조 실패로 판정 불가")

    names = "', '".join(_CENTRAL_TABLES)
    rows = query_rows(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='public' AND table_name IN ('{names}')"
    )
    assert rows == [], f"로컬 DB에 중앙 테이블이 생겼다: {rows}"


def test_disabled_central_yields_no_connection(tmp_path):
    """설정이 없는 상태 = 기존 사용자의 상태. 여기서 중앙은 완전히 침묵해야 한다."""
    from src import pg_central as pc

    pc.reset_state()
    try:
        empty = tmp_path / "config.json"
        empty.write_text('{"last_path": "D:/vibe-coding"}', encoding='utf-8')
        assert pc.is_central_enabled(empty) is False
        assert pc.get_central_conn(empty) is None
        assert pc._schema_ready is False
    finally:
        pc.reset_state()
