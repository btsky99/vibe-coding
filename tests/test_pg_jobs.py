"""
FILE: tests/test_pg_jobs.py
DESCRIPTION: 일감 저장소 회귀 테스트 — Phase 12 Task 48·49.
             중앙 DB 가 없는 환경(CI)에서도 돌아야 하므로 연결 불가면 스킵한다.

[🔴 이 테스트가 지키는 것]
  ① 상태 전이는 **반드시** 이력에 남는다 — 코드가 아니라 DB 트리거가 보장하므로,
     트리거를 실수로 지우면 여기서 걸린다. 현재 상태만 남고 이력이 비면
     "어디서 틀어졌나"를 영영 못 본다(2026-08-12 사용자 요구).
  ② 같은 일감을 두 노드가 집을 수 없다 — 집으면 같은 지시가 두 번 실행된다.
  ③ 이벤트가 달린 일감은 삭제되지 않는다 — "기록은 지우지 않는다"를 스키마가 강제.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from src import pg_jobs  # noqa: E402

NODE = 'test-node-' + 'f' * 20


@pytest.fixture(scope='module')
def conn():
    """중앙 DB 가 없으면 스킵. [WHY 스킵인가] 중앙 서버는 개발 PC 밖에서는 없는 것이
    정상이다 — 없다고 실패로 처리하면 CI 가 항상 빨갛고, 그러면 아무도 안 본다."""
    c = pg_jobs.conn_or_none()
    if c is None:
        pytest.skip('중앙 DB 미연결 — 이 테스트는 연결된 환경에서만 의미가 있다')
    return c


@pytest.fixture(autouse=True)
def _cleanup(conn):
    """테스트가 만든 행만 지운다. [제약] 이벤트를 먼저 지워야 한다 — FK 에 CASCADE 가
    없어서(의도된 설계) 반대 순서로는 삭제가 거부된다."""
    yield
    with conn.cursor() as cur:
        cur.execute('DELETE FROM apix_job_events WHERE job_id IN'
                    ' (SELECT id FROM apix_jobs WHERE target_node=%s)', (NODE,))
        cur.execute('DELETE FROM apix_jobs WHERE target_node=%s', (NODE,))


def test_발주하면_생성_이벤트가_남는다(conn):
    jid = pg_jobs.create_job(NODE, '테스트 지시', project='t')
    assert jid > 0
    kinds = [e['kind'] for e in pg_jobs.list_events(jid)]
    assert kinds == ['created'], '생성 자체가 이력에 없으면 시작점을 못 찾는다'


def test_상태전이가_전부_이력에_남는다(conn):
    """[🔴 핵심] 트리거가 보장한다 — 코드 경로를 우회해도 남아야 한다."""
    jid = pg_jobs.create_job(NODE, '전이 테스트')
    pg_jobs.claim_job(NODE)                       # queued → running
    pg_jobs.report_job(jid, git_after='abc')      # running → review
    pg_jobs.set_verify(jid, {'ok': True})         # review → decide
    pg_jobs.decide_job(jid, approve=True)         # decide → done

    details = [e['detail'] for e in pg_jobs.list_events(jid) if e['kind'] == 'status']
    assert details == ['queued -> running', 'running -> review',
                       'review -> decide', 'decide -> done']


def test_트리거를_우회해도_이력이_남는다(conn):
    """코드를 안 거치고 SQL 로 직접 바꿔도 기록된다 — 규율이 아니라 구조여야 한다."""
    jid = pg_jobs.create_job(NODE, '우회 테스트')
    with conn.cursor() as cur:
        cur.execute("UPDATE apix_jobs SET status='rejected' WHERE id=%s", (jid,))
    assert any(e['detail'] == 'queued -> rejected' for e in pg_jobs.list_events(jid))


def test_같은_일감을_둘이_집지_못한다(conn):
    """[🔴 핵심] 두 번 집히면 같은 지시가 두 번 실행된다 — 되돌릴 수 없는 작업이면 피해가 남는다."""
    jid = pg_jobs.create_job(NODE, '중복 체크아웃')
    first = pg_jobs.claim_job(NODE)
    second = pg_jobs.claim_job(NODE)
    assert first and first['id'] == jid
    assert second is None, '이미 running 인 일감이 또 집혔다'


def test_이벤트가_있으면_일감을_지울_수_없다(conn):
    """[🔴 핵심] '기록은 지우지 않는다'를 주석이 아니라 스키마가 강제한다."""
    import psycopg2

    jid = pg_jobs.create_job(NODE, '삭제 방어')
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with conn.cursor() as cur:
            cur.execute('DELETE FROM apix_jobs WHERE id=%s', (jid,))


def test_알_수_없는_상태는_거부된다(conn):
    """오타 상태가 들어가면 아무 코드도 처리하지 않아 job 이 영원히 고인다."""
    import psycopg2

    jid = pg_jobs.create_job(NODE, '상태 오타')
    with pytest.raises(psycopg2.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute("UPDATE apix_jobs SET status='reviewing' WHERE id=%s", (jid,))


def test_재시도는_횟수를_올리고_다시_큐로(conn):
    jid = pg_jobs.create_job(NODE, '재시도')
    pg_jobs.claim_job(NODE)
    pg_jobs.decide_job(jid, approve=False, reason='테스트 실패')
    pg_jobs.requeue_job(jid, reason='수정 후 재시도')

    job = pg_jobs.get_job(jid)
    assert job['status'] == 'queued' and job['retry_count'] == 1
    kinds = [e['kind'] for e in pg_jobs.list_events(jid)]
    assert 'decision' in kinds and 'requeue' in kinds, '사유가 없으면 재발을 못 막는다'


def test_빈_지시는_발주되지_않는다(conn):
    assert pg_jobs.create_job(NODE, '   ') == 0
    assert pg_jobs.create_job('', '내용') == 0
