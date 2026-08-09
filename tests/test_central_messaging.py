"""
FILE: tests/test_central_messaging.py
DESCRIPTION: 중앙 대화(agent_messages) 송수신 규약의 회귀 테스트 — 중앙 서버 없이 검증한다.

             [WHY 가짜 커넥션인가] 실제 왕복은 tests/test_central_e2e.py가 중앙 서버가
             있을 때만 수행한다. 여기서는 서버 없이도 항상 도는 규약을 지킨다:
             자기 메시지 에코 차단, 커서 전진, 발신 상한, 미설정 시 무동작.
             CI와 다른 사용자 환경에는 중앙 서버가 없으므로 이쪽이 기본 방어선이다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — Phase 10 Task 8 규약 고정.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from src import pg_central  # noqa: E402


class FakeCursor:
    """호출된 SQL을 기록하는 최소 커서. fetch 결과는 테스트가 주입한다."""

    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.owner.calls.append((' '.join(sql.split()), params))
        self.rowcount = 1

    def fetchone(self):
        return self.owner.one

    def fetchall(self):
        return self.owner.many

    @property
    def description(self):
        return [(c,) for c in ('id', 'from_node', 'from_agent', 'to_node',
                               'to_agent', 'content', 'created_at')]


class FakeConn:
    def __init__(self, one=None, many=()):
        self.calls: list = []
        self.one = one
        self.many = list(many)

    def cursor(self):
        return FakeCursor(self)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    pg_central._send_times.clear()
    monkeypatch.setattr('src.node_identity.get_node_id', lambda *a, **k: 'nodeA' * 8)
    yield


def test_중앙_미설정이면_아무것도_하지_않는다(monkeypatch):
    """[게이트] 중앙을 쓰지 않는 사용자에게 이 기능은 존재하지 않아야 한다."""
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: None)

    assert pg_central.send_message('안녕') is None
    assert pg_central.fetch_new() == []
    assert pg_central.ack_upto(5) is False
    assert pg_central.purge_old() == 0


def test_발신은_서버_시각을_쓴다(monkeypatch):
    """[불변식] created_at을 클라이언트가 넣으면 시계 어긋난 PC 하나가 순서를 뒤섞는다."""
    conn = FakeConn(one=(42,))
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    assert pg_central.send_message('안녕', to_node='nodeB') == 42

    sql, params = conn.calls[0]
    assert 'INSERT INTO agent_messages' in sql
    assert 'created_at' not in sql, 'created_at을 직접 넣으면 안 된다 (서버 DEFAULT now())'
    assert '안녕' in params


def test_빈_내용은_보내지_않는다(monkeypatch):
    conn = FakeConn(one=(1,))
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    assert pg_central.send_message('   ') is None
    assert conn.calls == []


def test_발신_상한을_넘기면_건너뛴다(monkeypatch):
    """[WHY] 에이전트가 루프에 빠지면 1코어 서버가 무너지고 다른 노드 대화까지 막힌다."""
    conn = FakeConn(one=(1,))
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    sent = sum(1 for _ in range(pg_central._SEND_LIMIT_PER_MIN + 10)
               if pg_central.send_message('x') is not None)
    assert sent == pg_central._SEND_LIMIT_PER_MIN


def test_수신은_자기_메시지를_제외한다(monkeypatch):
    """[불변식] 브로드캐스트는 자신에게도 매칭된다 — 거르지 않으면 무한 루프."""
    conn = FakeConn(many=[])
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    pg_central.fetch_new()

    select_sql = [s for s, _ in conn.calls if 'FROM agent_messages' in s][0]
    assert 'from_node <> %s' in select_sql, '자기 노드 제외 조건이 빠졌다'


def test_수신하면_커서가_마지막_id로_전진한다(monkeypatch):
    conn = FakeConn(one=(0,), many=[
        (7, 'nodeB', 'claude:T1', None, None, '첫', None),
        (9, 'nodeB', 'claude:T1', None, None, '둘', None),
    ])
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    rows = pg_central.fetch_new()

    assert [r['id'] for r in rows] == [7, 9]
    upsert = [(s, p) for s, p in conn.calls if 'INSERT INTO message_cursors' in s]
    assert upsert, '커서 갱신이 일어나지 않았다'
    assert 9 in upsert[0][1], '커서는 마지막 id로 전진해야 한다'


def test_advance_False면_커서를_건드리지_않는다(monkeypatch):
    """처리 실패를 되돌려야 하는 호출부를 위한 경로."""
    conn = FakeConn(one=(0,), many=[(7, 'nodeB', 'c', None, None, 'x', None)])
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    pg_central.fetch_new(advance=False)

    assert not [s for s, _ in conn.calls if 'INSERT INTO message_cursors' in s]


def test_커서는_뒤로_가지_않는다(monkeypatch):
    """[WHY GREATEST] 늦게 도착한 낮은 id의 ack가 커서를 되돌리면 처리한 메시지를 다시 받는다."""
    conn = FakeConn()
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: conn)

    pg_central.ack_upto(3)

    sql, _ = conn.calls[0]
    assert 'GREATEST' in sql


def test_스키마에_NOTIFY_트리거가_있다():
    """[WHY] 폴링만 하면 지연이 주기만큼 생기고, 주기를 줄이면 1코어 서버에 빈 쿼리가 쏟아진다."""
    sql = pg_central._SCHEMA_SQL
    assert 'pg_notify' in sql
    assert 'trg_agent_message' in sql
    assert pg_central.NOTIFY_CHANNEL == 'agent_msg'


def test_알림_payload에_본문을_싣지_않는다():
    """[제약] NOTIFY payload는 8000바이트 상한이고, 대기 중인 모든 커넥션에 흘러간다."""
    sql = pg_central._SCHEMA_SQL
    notify_line = [ln for ln in sql.splitlines() if 'pg_notify' in ln][0]
    assert 'NEW.content' not in notify_line, '본문을 payload에 실으면 안 된다'
    assert 'to_node' in notify_line


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
