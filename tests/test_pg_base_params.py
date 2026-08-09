"""
FILE: tests/test_pg_base_params.py
DESCRIPTION: query_rows/execute의 파라미터 바인딩 계약 회귀 테스트 — %s가 서버로 새어나가지 않는지 고정.

             [WHY 시그니처를 테스트하는가] 이 사고는 SQL이 틀려서가 아니라 인자 자리가
             밀려서 났다. 튜플이 timeout에 바인딩되면 psycopg2는 보간을 건너뛰고 %s를
             그대로 보내는데, 호출부는 except가 빈 리스트를 삼켜 '데이터 없음'으로 읽었다.
             값 검증만 하는 테스트로는 절대 안 잡히므로 인자 순서 자체를 못으로 박는다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — 리사이클 GUARD 무력화 사고(recycled_at 2668건 중 0건) 재발 방지.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from src import pg_base  # noqa: E402


class _Cur:
    """cur.execute가 실제로 받은 (sql, params)를 그대로 보관하는 최소 커서."""

    def __init__(self, box):
        self.box = box

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.box.append((sql, params))

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, box):
        self.box = box

    def cursor(self, **kw):
        return _Cur(self.box)


def _patch(monkeypatch, box):
    monkeypatch.setattr(pg_base, '_HAS_PSYCOPG2', True)
    monkeypatch.setattr(pg_base, '_get_pg_conn', lambda: _Conn(box))
    import src.pg_schema as pg_schema
    monkeypatch.setattr(pg_schema, 'ensure_schema', lambda *a, **k: True)


def test_params_is_second_positional_argument():
    """[불변식] params가 2번째, timeout이 3번째. 순서가 바뀌면 사고가 그대로 재현된다."""
    for fn in (pg_base.query_rows, pg_base.execute):
        names = list(inspect.signature(fn).parameters)
        assert names[:3] == ['sql', 'params', 'timeout'], f'{fn.__name__} 인자 순서 변경됨: {names}'


def test_query_rows_forwards_params_to_driver(monkeypatch):
    box = []
    _patch(monkeypatch, box)
    pg_base.query_rows('SELECT 1 WHERE a = %s AND b = %s', ('x', 'y'))
    assert box, 'cur.execute가 호출되지 않았다'
    assert box[0][1] == ('x', 'y'), '파라미터가 드라이버까지 전달되지 않음 — %s가 그대로 나간다'


def test_execute_forwards_params_to_driver(monkeypatch):
    box = []
    _patch(monkeypatch, box)
    pg_base.execute('UPDATE t SET a = %s WHERE id = %s', ('v', 3))
    assert box and box[0][1] == ('v', 3)


def test_no_params_still_passes_none(monkeypatch):
    """파라미터 없는 기존 호출은 그대로 동작해야 한다(대부분의 호출부가 이 경로)."""
    box = []
    _patch(monkeypatch, box)
    pg_base.query_rows('SELECT 1')
    assert box[0][1] is None


def test_psql_fallback_refuses_params_instead_of_leaking(monkeypatch):
    """[제약] psql 폴백은 %s를 모른다. 문자열로 끼워 넣지 말고 명시적으로 포기한다."""
    monkeypatch.setattr(pg_base, '_HAS_PSYCOPG2', False)
    import src.pg_schema as pg_schema
    monkeypatch.setattr(pg_schema, 'ensure_schema', lambda *a, **k: True)

    def _boom(*a, **k):
        raise AssertionError('파라미터 쿼리가 psql로 새어나갔다')

    monkeypatch.setattr(pg_base, '_run_psql', _boom)
    assert pg_base.query_rows('SELECT %s', ('a',)) == []
    assert pg_base.execute('UPDATE t SET a = %s', ('a',)) is False
