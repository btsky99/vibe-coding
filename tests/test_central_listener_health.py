"""
FILE: tests/test_central_listener_health.py
DESCRIPTION: 🔴 리스너가 '조용한 단절'을 빠져나오는지 고정하는 회귀 테스트.
             SSH 터널 너머가 끊겨도 로컬 소켓은 established 로 남아 conn.closed 가 서지
             않는다. 그 상태에서 리스너가 재연결하지 않으면 살아 있는 것처럼 보이는 채로
             모든 알림을 놓친다 — NOTIFY 는 저장되지 않으므로 영구 유실이다.

             이 테스트가 없으면 결함이 조용해서 재발해도 아무도 모른다(2026-08-11 실제 사고:
             na2js 가 연결 13분 뒤 귀머거리가 되어 메시지 3건을 놓쳤고, 화면에는 정상으로 떴다).

REVISION HISTORY:
- 2026-08-11 Claude: 신규 — half-open 커넥션 재연결 회귀 고정.
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from src import central_listener as cl


class _DeadConn:
    """half-open 커넥션 — 닫히지 않았다고 주장하지만 쿼리는 실패한다."""
    closed = 0

    def cursor(self):
        raise OSError('연결이 끊겼다(터널 단절)')

    def close(self):
        self.closed = 1


class _LiveConn:
    closed = 0

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            return None

    def cursor(self):
        return self._Cur()

    def close(self):
        self.closed = 1


def test_alive_detects_half_open_connection():
    """[🔴 핵심] closed 플래그가 0 이어도 왕복이 실패하면 죽은 것으로 판정해야 한다."""
    dead = _DeadConn()
    assert dead.closed == 0, '전제: half-open 은 closed 가 서지 않는다'
    assert cl._alive(dead) is False, 'closed 플래그만 믿으면 조용한 단절을 못 벗어난다'


def test_alive_accepts_working_connection():
    """살아 있는 커넥션을 죽었다고 오판하면 재연결 폭풍이 된다."""
    assert cl._alive(_LiveConn()) is True


def test_loop_reconnects_on_silent_disconnect(monkeypatch):
    """타임아웃으로 깨어났는데 커넥션이 죽어 있으면 폐기하고 다시 연결한다.

    재연결 경로는 pending 을 세운다 — 끊겨 있는 동안 놓친 NOTIFY 를 조회로 만회하는
    유일한 길이다. 여기서 pending 이 서지 않으면 메시지가 영구 유실된다.
    """
    import threading

    conns = [_DeadConn(), _LiveConn()]
    opened = []

    def _fake_open(node):
        c = conns[len(opened)] if len(opened) < len(conns) else _LiveConn()
        opened.append(c)
        return c

    monkeypatch.setattr(cl, '_open_listen_conn', _fake_open)
    monkeypatch.setattr(cl, '_register_self', lambda: None)
    monkeypatch.setattr(cl, '_maybe_purge', lambda: None)

    stop = threading.Event()
    calls = {'n': 0}

    # select 는 항상 즉시 타임아웃(알림 없음) — '조용한 주기'를 재현한다.
    fake_select = type(sys)('select')
    def _sel(r, w, x, timeout):
        calls['n'] += 1
        if calls['n'] >= 3:
            stop.set()          # 무한 루프 방지 — 재연결을 확인할 만큼만 돈다
        return ([], [], [])
    fake_select.select = _sel
    monkeypatch.setitem(sys.modules, 'select', fake_select)

    # notifies 는 비어 있고 poll 은 아무것도 하지 않는다.
    for c in conns:
        c.notifies = []
        c.poll = lambda: None

    cl._loop('node-abc', stop)

    assert len(opened) >= 2, '죽은 커넥션을 폐기하고 재연결하지 않았다'
    assert conns[0].closed == 1, '죽은 커넥션을 닫지 않았다'
    assert cl.snapshot()['pending'] is True, \
        '재연결 후 pending 이 서지 않으면 끊긴 동안의 메시지를 영영 못 받는다'
