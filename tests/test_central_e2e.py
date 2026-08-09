"""
FILE: tests/test_central_e2e.py
DESCRIPTION: 중앙 대화 실왕복 E2E (Task 28) — 중앙 서버가 실제로 붙을 때만 돈다.
             INSERT → NOTIFY → 리스너 신호 → 조회 → 커서 전진의 전 구간을 한 번에 확인한다.

             [WHY 별도 파일인가] CI와 다른 사용자 환경에는 중앙 서버가 없다. 서버 없이도
             도는 규약은 test_central_messaging.py / test_central_api.py가 맡고,
             이 파일은 '진짜로 도착하는가'만 본다. 섞으면 서버 없는 곳에서 전부 빨개진다.

             [🔴 실 데이터 격리] 테스트는 전용 노드명/에이전트명만 쓴다.
               - to_agent = 'pytest-e2e'  → 커서가 message_cursors의 별도 행에 생겨
                 실제 에이전트(claude:T1 등)의 읽음 위치를 밀지 않는다. 이게 없으면
                 테스트가 진짜 미수신 메시지를 '읽음' 처리해 영구히 삼킨다.
               - from_node = 'pytest-e2e-node' → 실 노드가 보낸 대화와 섞이지 않는다.
             [🔴 DELETE 예외] agent_messages는 append-only가 불변식이지만, 테스트가 남긴
               행은 다른 노드의 대화창에 잡음으로 뜬다. 자기가 넣은 표식 행만 지운다.

REVISION HISTORY:
- 2026-08-09 Claude: 신규. Task 28 — 계획서가 요구한 실왕복 검증.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from src import central_listener, pg_central  # noqa: E402
from src.node_identity import get_node_id  # noqa: E402

_TEST_AGENT = 'pytest-e2e'
_TEST_NODE = 'pytest-e2e-node'

# NOTIFY 도착 대기 상한. [WHY 넉넉한가] 경로가 SSH 터널이라 왕복이 로컬보다 느리고,
#   리스너가 select 상한(60초) 안에서 깨어나는 것과는 별개로 첫 구독이 서는 데 시간이 든다.
_WAIT_SEC = 25.0


def _conn_or_skip():
    conn = pg_central.get_central_conn()
    if conn is None:
        pytest.skip('중앙 서버 미설정 또는 미연결 — E2E 건너뜀')
    return conn


def _wait(pred, timeout: float = _WAIT_SEC) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def central():
    """연결 + 리스너 기동. 종료 시 테스트가 남긴 행과 커서를 모두 회수한다."""
    conn = _conn_or_skip()
    pg_central._send_times.clear()
    central_listener.stop()                 # 앞선 테스트/앱이 띄운 루프가 있으면 정리
    with central_listener._lock:
        central_listener._state.update(running=False, pending=False, mode='off')

    assert central_listener.start() is True, '리스너 기동 실패'
    assert _wait(lambda: central_listener.snapshot()['mode'] == 'listen'), \
        f"LISTEN 수립 실패: {central_listener.snapshot()['last_error']}"
    central_listener.consume_pending()      # 재구독 직후의 초기 신호를 비운다

    try:
        yield conn
    finally:
        central_listener.stop()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_messages WHERE from_node = %s", (_TEST_NODE,))
                cur.execute("DELETE FROM agent_messages WHERE from_node = %s AND to_agent = %s",
                            (get_node_id(), _TEST_AGENT))
                cur.execute("DELETE FROM message_cursors WHERE agent_id = %s", (_TEST_AGENT,))
        except Exception as exc:            # 정리 실패가 테스트 결과를 뒤집지는 않게 한다
            print(f'[e2e] 정리 실패(수동 확인 필요): {exc}')


def _inject(conn, content: str, to_node: str | None = None) -> int:
    """다른 노드가 보낸 것처럼 직접 INSERT — send_message는 항상 내 노드로 찍힌다."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_messages (from_node, from_agent, to_node, to_agent, content)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (_TEST_NODE, 'pytest', to_node if to_node is not None else get_node_id(),
             _TEST_AGENT, content),
        )
        return int(cur.fetchone()[0])


def test_왕복_INSERT가_NOTIFY로_신호를_세우고_조회로_이어진다(central):
    """Task 28 본체 — 신호기(27) → 라우트 조회(26) → 커서(25) 전 구간."""
    표식 = f'e2e-{uuid.uuid4().hex[:8]}'
    mid = _inject(central, f'왕복 검증 {표식}')

    assert _wait(lambda: central_listener.snapshot()['pending']), \
        'NOTIFY가 도착하지 않았다 (트리거 또는 LISTEN 구독 확인)'

    assert central_listener.consume_pending() is True
    rows = pg_central.fetch_new(agent_id=_TEST_AGENT, limit=50)
    assert any(r['id'] == mid and 표식 in r['content'] for r in rows), \
        f'주입한 메시지가 조회되지 않았다 (id={mid})'


def test_커서가_전진해_같은_메시지를_두_번_주지_않는다(central):
    """[불변식] 커서가 안 밀리면 같은 메시지를 무한 재수신한다."""
    mid = _inject(central, f'커서 검증 {uuid.uuid4().hex[:8]}')
    assert _wait(lambda: central_listener.snapshot()['pending'])

    first = pg_central.fetch_new(agent_id=_TEST_AGENT, limit=50)
    assert any(r['id'] == mid for r in first)

    second = pg_central.fetch_new(agent_id=_TEST_AGENT, limit=50)
    assert not any(r['id'] == mid for r in second), '커서가 전진하지 않았다'


def test_자기가_보낸_메시지는_되받지_않는다(central):
    """[불변식] 브로드캐스트는 자신에게도 매칭된다 — 거르지 않으면 무한 루프가 된다."""
    표식 = f'에코 {uuid.uuid4().hex[:8]}'
    mid = pg_central.send_message(표식, to_agent=_TEST_AGENT)
    assert mid is not None, '발신 실패'

    time.sleep(1.0)                          # NOTIFY가 돌아올 시간을 준다
    rows = pg_central.fetch_new(agent_id=_TEST_AGENT, limit=50)
    assert not any(r['id'] == mid for r in rows), '자기 발신분을 되받았다'

    보임 = pg_central.list_recent(limit=100)
    assert any(r['id'] == mid for r in 보임), '대화창(list_recent)에는 내 말도 보여야 한다'


def test_다른_노드_앞_메시지는_신호를_세우지_않는다(central):
    """[제약] payload는 to_node 하나 — 남의 것에 깨어나면 터널 왕복만 늘어난다."""
    central_listener.consume_pending()
    _inject(central, '남의 메시지', to_node='someone-else-node')

    time.sleep(2.0)
    assert central_listener.snapshot()['pending'] is False, \
        '다른 노드 앞 메시지에 신호가 섰다'


def test_list_recent는_커서를_밀지_않는다(central):
    """[WHY] 패널을 열어보기만 해도 커서가 밀리면 아무도 처리 안 한 메시지가 사라진다."""
    mid = _inject(central, f'조회 전용 {uuid.uuid4().hex[:8]}')
    assert _wait(lambda: central_listener.snapshot()['pending'])

    pg_central.list_recent(limit=100)
    rows = pg_central.fetch_new(agent_id=_TEST_AGENT, limit=50)
    assert any(r['id'] == mid for r in rows), 'list_recent가 커서를 밀어버렸다'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v', '-s']))
