"""
FILE: src/pg_jobs.py
DESCRIPTION: 아픽스 일감(job) 저장소 — Phase 12 Task 48·49.
             비서가 발주한 일감을 다른 노드가 집어가 실행하고, 결과가 여기에 남는다.
             카드 화면은 이 표를 그리는 것일 뿐 — 정본은 항상 이쪽이다.

[🔴 왜 hive_tasks 가 아니라 새 표인가]
  hive_tasks 는 **로컬 DB**의 태스크 큐다. 일감은 여러 PC 가 공유해야 하므로 중앙 DB 에
  있어야 한다. 로컬 표를 원격에서 읽게 만들면 노드마다 다른 진실을 보게 된다.

[🔴 기록은 지우지 않는다 — 사용자 요구(2026-08-12)]
  "완전 사라지면 안 되지. 기록이 남아야 너나 나나 어디서 뭐가 잘못되는지 볼 수 있지."
  그래서 이 모듈에는 **purge/delete 경로를 만들지 않는다**. 중앙 대화(agent_messages)는
  30일 정리가 걸려 있지만 일감은 정책이 다르다 — 몇 달 뒤 "그때 왜 이렇게 했지"가
  필요한 순간이 정확히 그때다.
  apix_job_events 의 외래키에 ON DELETE CASCADE 를 **일부러 넣지 않았다**. 이벤트가 남아
  있으면 job 삭제가 DB 레벨에서 실패한다 — 주석이 아니라 스키마로 강제한다.
  (주석이 "재평가한다"고 선언해놓고 코드엔 없던 전례가 있다 — 2026-08-11 리스너 사고)

[🔴 상태 전이는 반드시 이벤트를 남긴다]
  현재 상태만 보면 "어디서 틀어졌나"를 못 본다. 오늘도 na2js 는 현재 상태만으로는
  'listener: running'(정상)이었고, 커서의 **시각 흔적** 덕분에 23시간 정지를 잡았다.
  transition() 을 거치지 않는 status UPDATE 를 만들지 말 것.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성 — Phase 12 Task 48(스키마).
"""
from __future__ import annotations

import json
import threading

from src.pg_central import get_central_conn

# [제약] 프로세스당 1회만 DDL. pg_central._ensure_schema_locked 와 같은 방식이되,
#   플래그는 분리한다 — 중앙 대화 스키마가 준비됐다고 일감 스키마도 준비된 것은 아니다.
_lock = threading.RLock()
_schema_ready = False

# 상태 집합. [WHY CHECK 제약을 거는가] 오타로 'reviewing' 같은 값이 들어가면 아무 코드도
#   그것을 처리하지 않아 job 이 영원히 고인다. 조용한 실패가 이 프로젝트의 주적이라,
#   DB 가 즉시 거부하게 만든다. 새 상태를 추가하려면 여기와 CHECK 를 같이 고쳐야 한다.
STATUSES = ('queued', 'running', 'review', 'decide', 'done', 'rejected')

NOTIFY_CHANNEL = 'apix_job'

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS apix_jobs (
    id           BIGSERIAL   PRIMARY KEY,
    project      TEXT        NOT NULL DEFAULT '',
    origin_node  TEXT        NOT NULL DEFAULT '',
    target_node  TEXT        NOT NULL,
    target_slot  INT         NOT NULL DEFAULT 0,
    work_dir     TEXT        NOT NULL DEFAULT '',
    instruction  TEXT        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','review','decide','done','rejected')),
    git_before   TEXT        NOT NULL DEFAULT '',
    git_after    TEXT        NOT NULL DEFAULT '',
    diff_stat    JSONB,
    self_report  TEXT        NOT NULL DEFAULT '',
    verify_json  JSONB,
    retry_count  INT         NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 노드가 자기 몫을 집어갈 때 쓰는 조회 형태 그대로.
CREATE INDEX IF NOT EXISTS idx_apix_jobs_claim ON apix_jobs (target_node, status, id);
-- 화면이 '결정 대기'와 '최근 이력'을 각각 뽑을 때.
CREATE INDEX IF NOT EXISTS idx_apix_jobs_status ON apix_jobs (status, updated_at DESC);

-- [🔴 ON DELETE CASCADE 를 넣지 않는다] 이벤트가 남아 있으면 job 삭제가 실패한다.
--   "기록은 지우지 않는다"를 주석이 아니라 스키마로 강제하기 위한 것이다.
CREATE TABLE IF NOT EXISTS apix_job_events (
    id     BIGSERIAL   PRIMARY KEY,
    job_id BIGINT      NOT NULL REFERENCES apix_jobs (id),
    at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind   TEXT        NOT NULL,
    detail TEXT        NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_apix_job_events_job ON apix_job_events (job_id, id);

-- [WHY 트리거인가] 노드가 폴링하면 지연이 주기만큼 생기고, 주기를 줄이면 1코어 서버에
--   빈 쿼리가 쏟아진다. agent_messages 와 같은 이유·같은 방식이다.
-- [제약] payload 는 대상 노드 하나뿐 — 본문을 실으면 8000바이트 상한에 걸려 NOTIFY 가
--   통째로 실패하고, 그 실패는 '알림이 조용히 끊김'으로만 보인다.
-- [WHY INSERT 만이 아니라 UPDATE 도 보는가] 반려 후 재시도는 기존 행을 queued 로
--   되돌린다. INSERT 만 걸면 재시도가 아무에게도 안 알려져 job 이 그대로 고인다.
CREATE OR REPLACE FUNCTION notify_apix_job() RETURNS trigger AS $fn$
BEGIN
    IF NEW.status = 'queued' THEN
        PERFORM pg_notify('apix_job', NEW.target_node);
    END IF;
    RETURN NEW;
END $fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apix_job ON apix_jobs;
CREATE TRIGGER trg_apix_job AFTER INSERT OR UPDATE OF status ON apix_jobs
    FOR EACH ROW EXECUTE FUNCTION notify_apix_job();

-- [🔴 전이 기록을 코드가 아니라 DB 가 남긴다]
--   중앙 커넥션은 autocommit 이라 '상태 UPDATE' 와 '이벤트 INSERT' 를 코드로 나눠 쓰면
--   두 문장 사이에서 죽었을 때 **전이만 남고 기록이 빈다**. 그러면 "어디서 틀어졌나"를
--   보려고 만든 표에 정작 그 순간이 없다.
--   트리거는 UPDATE 와 같은 암묵 트랜잭션 안에서 돌아 원자적이고, 무엇보다 **어떤 코드
--   경로로 status 를 바꿔도 우회할 수 없다.** 규율을 주석으로 적어두면 지켜지지 않는다는
--   것을 오늘(2026-08-12) 하루 종일 확인했다.
-- [제약] 트리거는 '왜' 를 모른다 — 사유가 있는 이벤트는 add_event() 로 따로 덧붙인다.
--   즉 전이 사실은 DB 가 보장하고, 맥락은 코드가 보탠다.
CREATE OR REPLACE FUNCTION log_apix_job_status() RETURNS trigger AS $fn$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO apix_job_events (job_id, kind, detail)
        VALUES (NEW.id, 'created', NEW.status);
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO apix_job_events (job_id, kind, detail)
        VALUES (NEW.id, 'status', OLD.status || ' -> ' || NEW.status);
    END IF;
    RETURN NEW;
END $fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apix_job_log ON apix_jobs;
CREATE TRIGGER trg_apix_job_log AFTER INSERT OR UPDATE OF status ON apix_jobs
    FOR EACH ROW EXECUTE FUNCTION log_apix_job_status();
"""


def conn_or_none(config_file=None):
    """스키마가 준비된 중앙 커넥션. 중앙 미설정/연결 실패면 None.

    [🔴 왜 pg_central 의 커넥션을 빌려 쓰는가] 커넥션 관리에는 사고로 얻은 규칙이 쌓여
      있다 — 절전으로 죽은 소켓의 무한 recv(2026-07-20 데몬 16시간 동결), 터널 너머가
      끊겨도 established 로 남는 half-open(2026-08-11). 여기서 다시 구현하면 그 규칙이
      한쪽에만 적용된 채 갈라진다. 연결은 한 곳, 스키마만 각자.
    """
    global _schema_ready
    conn = get_central_conn(config_file)
    if conn is None:
        return None
    with _lock:
        if _schema_ready:
            return conn
        try:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
            _schema_ready = True
            return conn
        except Exception as exc:      # noqa: BLE001
            # DDL 실패를 삼키고 커넥션을 돌려주면 이후 모든 쿼리가 'relation does not
            # exist' 로 죽는다 — 원인에서 먼 지점에서 터지므로 여기서 끊는다.
            print(f'[jobs] 스키마 준비 실패: {exc}')
            return None


def ensure(config_file=None) -> bool:
    """스키마 준비 여부만 확인하고 싶을 때(설치·진단용)."""
    return conn_or_none(config_file) is not None


def reset_state() -> None:
    """테스트용 — 다음 호출에서 DDL 을 다시 돌린다."""
    global _schema_ready
    with _lock:
        _schema_ready = False


def _json(value):
    """JSONB 컬럼에 넣을 값. None 은 그대로 둔다(빈 dict 와 '값 없음'은 다르다)."""
    return json.dumps(value, ensure_ascii=False) if value is not None else None


_COLS = ('id', 'project', 'origin_node', 'target_node', 'target_slot', 'work_dir',
         'instruction', 'status', 'git_before', 'git_after', 'diff_stat',
         'self_report', 'verify_json', 'retry_count', 'created_at', 'updated_at')
_SELECT = 'SELECT ' + ', '.join(_COLS) + ' FROM apix_jobs'


def _row(cur) -> dict | None:
    r = cur.fetchone()
    return dict(zip(_COLS, r)) if r else None


# ── 발주 ─────────────────────────────────────────────────────────────────────


def create_job(target_node: str, instruction: str, project: str = '',
               target_slot: int = 0, work_dir: str = '', origin_node: str = '',
               config_file=None) -> int:
    """일감을 발주한다. 실패하면 0.

    [제약] target_node 는 uuid 다(명부의 node_id). 화면에 보이는 번호(3)를 그대로 넣으면
      아무 노드도 자기 것으로 못 알아본다 — 번호→uuid 변환은 호출부 몫이다.
    [WHY work_dir 을 job 이 들고 있나] 기동 게이트가 '이 폴더에서 CLI 를 띄워도 되는가'를
      검사하는 근거다. 실행 시점에 노드가 정하게 두면 게이트가 검사할 대상이 사라진다.
    """
    conn = conn_or_none(config_file)
    if conn is None or not str(target_node or '').strip() or not str(instruction or '').strip():
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO apix_jobs (project, origin_node, target_node, target_slot,'
                ' work_dir, instruction) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                (project, origin_node, target_node, int(target_slot or 0),
                 work_dir, instruction))
            return int(cur.fetchone()[0])
    except Exception as exc:                                   # noqa: BLE001
        print(f'[jobs] 발주 실패: {exc}')
        return 0


# ── 노드 쪽 ──────────────────────────────────────────────────────────────────


def claim_job(node_id: str, config_file=None) -> dict | None:
    """이 노드 앞으로 온 일감 하나를 원자적으로 집어 running 으로 바꾼다. 없으면 None.

    [🔴 왜 SELECT 후 UPDATE 가 아닌가] 두 문장으로 나누면 노드가 재시작 직후 두 번
      조회하거나 리스너와 폴백이 겹칠 때 **같은 job 을 둘이 집는다.** 그러면 같은 지시가
      두 번 실행되고, 되돌릴 수 없는 작업이면 피해가 남는다.
      `FOR UPDATE SKIP LOCKED` 는 잠긴 행을 건너뛰므로 경쟁하는 소비자끼리 서로를
      막지도 않는다(hive_tasks 원자적 체크아웃과 같은 규약).
    [불변식] 상태 전이 기록은 트리거가 남긴다 — 여기서 이벤트를 또 넣지 않는다(중복).
    """
    conn = conn_or_none(config_file)
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE apix_jobs SET status=%s, updated_at=now() WHERE id = ('
                '  SELECT id FROM apix_jobs WHERE target_node=%s AND status=%s'
                '  ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED'
                ') RETURNING ' + ', '.join(_COLS),
                ('running', node_id, 'queued'))
            return _row(cur)
    except Exception as exc:                                   # noqa: BLE001
        print(f'[jobs] 체크아웃 실패: {exc}')
        return None


def start_work(job_id: int, git_before: str, config_file=None) -> bool:
    """실행 직전의 커밋 해시를 박아둔다 — 나중 diff 의 기준점.

    [WHY 시작 시점에 찍나] 끝난 뒤에 '몇 개 고쳤냐'고 물으면 그건 자기신고다.
      시작점을 남겨두면 `git_before..HEAD` 로 **저장소에서 직접** 읽을 수 있다.
    """
    return _set(job_id, {'git_before': git_before}, config_file)


def report_job(job_id: int, git_after: str = '', diff_stat: dict | None = None,
               self_report: str = '', config_file=None) -> bool:
    """작업 종료 보고 → review. self_report 는 **표시용 라벨일 뿐** 판정 근거가 아니다."""
    return _set(job_id, {'status': 'review', 'git_after': git_after,
                         'diff_stat': _json(diff_stat), 'self_report': self_report},
                config_file)


# ── 검수·결정 ────────────────────────────────────────────────────────────────


def set_verify(job_id: int, verify: dict, config_file=None) -> bool:
    """검수 결과를 붙이고 사용자 결정 대기(decide)로 올린다."""
    return _set(job_id, {'status': 'decide', 'verify_json': _json(verify)}, config_file)


def decide_job(job_id: int, approve: bool, reason: str = '', config_file=None) -> bool:
    """사용자 결정. 승인 → done, 반려 → rejected.

    [제약] 사유는 이벤트로 남긴다 — 상태 컬럼에는 '왜' 가 안 들어가고, 그 '왜' 가
      나중에 같은 실수를 막는 유일한 재료다.
    """
    ok = _set(job_id, {'status': 'done' if approve else 'rejected'}, config_file)
    if ok and reason:
        add_event(job_id, 'decision', reason, config_file)
    return ok


def requeue_job(job_id: int, reason: str = '', config_file=None) -> bool:
    """반려된 일감을 다시 큐에 넣는다(재시도 횟수 +1).

    [제약] 상한 검사는 호출부(job_runner) 몫이다 — 여기서 막으면 '왜 안 도는지'가
      DB 안에 숨는다. 상한 초과는 이벤트로 드러나야 한다.
    """
    ok = _set(job_id, {'status': 'queued', 'retry_count_inc': True}, config_file)
    if ok and reason:
        add_event(job_id, 'requeue', reason, config_file)
    return ok


def _set(job_id: int, fields: dict, config_file=None) -> bool:
    """공통 UPDATE. updated_at 은 항상 갱신한다 — '언제 멈췄나'가 TTL 판정의 근거다."""
    conn = conn_or_none(config_file)
    if conn is None or not fields:
        return False
    sets, params = [], []
    for key, val in fields.items():
        if key == 'retry_count_inc':
            sets.append('retry_count = retry_count + 1')
            continue
        sets.append(f'{key} = %s')
        params.append(val)
    sets.append('updated_at = now()')
    params.append(int(job_id))
    try:
        with conn.cursor() as cur:
            cur.execute(f'UPDATE apix_jobs SET {", ".join(sets)} WHERE id = %s', params)
            return cur.rowcount > 0
    except Exception as exc:                                   # noqa: BLE001
        print(f'[jobs] 갱신 실패(job {job_id}): {exc}')
        return False


# ── 이벤트·조회 ──────────────────────────────────────────────────────────────


def add_event(job_id: int, kind: str, detail: str = '', config_file=None) -> bool:
    """전이 외의 맥락을 덧붙인다(검수 결과, 반려 사유, 기동 실패 등).

    [제약] 상태 전이 자체는 트리거가 남기므로 여기서 또 남기지 말 것 — 이력이 두 줄씩
      쌓이면 "몇 번 시도했나"를 셀 수 없게 된다.
    """
    conn = conn_or_none(config_file)
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO apix_job_events (job_id, kind, detail)'
                        ' VALUES (%s,%s,%s)', (int(job_id), kind, str(detail)[:2000]))
        return True
    except Exception as exc:                                   # noqa: BLE001
        print(f'[jobs] 이벤트 기록 실패(job {job_id}): {exc}')
        return False


def get_job(job_id: int, config_file=None) -> dict | None:
    conn = conn_or_none(config_file)
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(_SELECT + ' WHERE id = %s', (int(job_id),))
        return _row(cur)


def list_jobs(status: str = '', limit: int = 50, config_file=None) -> list[dict]:
    """상태별 목록. status 를 비우면 전체를 최신순으로.

    [WHY 전체도 돌려주나] 화면이 '결정 대기'와 '최근 이력'을 둘 다 그린다 —
      끝난 일감을 못 보면 "어디서 뭐가 잘못됐는지"를 볼 수 없다(사용자 요구).
    """
    conn = conn_or_none(config_file)
    if conn is None:
        return []
    sql = _SELECT + (' WHERE status = %s' if status else '')
    params = ((status,) if status else ()) + (int(limit),)
    with conn.cursor() as cur:
        cur.execute(sql + ' ORDER BY updated_at DESC LIMIT %s', params)
        cols = _COLS
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_events(job_id: int, config_file=None) -> list[dict]:
    """그 일감에 무슨 일이 있었는지 시간순. '어디서 틀어졌나'를 보는 창구."""
    conn = conn_or_none(config_file)
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute('SELECT id, at, kind, detail FROM apix_job_events'
                    ' WHERE job_id = %s ORDER BY id', (int(job_id),))
        return [dict(zip(('id', 'at', 'kind', 'detail'), r)) for r in cur.fetchall()]


def stale_running(ttl_sec: int, config_file=None) -> list[dict]:
    """TTL 을 넘긴 running 일감. [WHY 필요한가] 비서나 노드가 죽으면 job 이 running 에
    영원히 고이고, 그 노드는 다음 일감을 못 집는다 — 조용한 정지의 전형이다."""
    conn = conn_or_none(config_file)
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute(_SELECT + " WHERE status='running'"
                    ' AND updated_at < now() - (%s || \' seconds\')::interval',
                    (int(ttl_sec),))
        return [dict(zip(_COLS, r)) for r in cur.fetchall()]
