"""
FILE: src/pg_central.py
DESCRIPTION: 중앙 PG(아픽스 서버) 커넥션 격리 모듈. config.json의 central_db 설정을 읽어
             SSH 터널 너머 원격 DB에 연결한다. 설정이 없거나 서버가 죽어 있으면 조용히
             None을 반환한다 — 이 모듈의 실패는 앱의 실패가 아니다.
             아픽스 서버(중앙 대화 PG) 1차 — Task 4.

REVISION HISTORY:
- 2026-08-08 Claude: 신규. 로컬 pg_base와 완전 분리 — 중앙 스키마가 로컬 DB를 오염시키던
                     경로 자체를 없애기 위해 pg_schema.py에 넣지 않았다.
"""
import threading
import time

# [🔴 왜 pg_schema.py가 아니라 여기인가] pg_schema.ensure_schema()는 모든 사용자의 로컬 DB에서
#   무조건 실행된다. 중앙 테이블 DDL을 거기에 넣으면 중앙 서버를 쓰지 않는 사람의 로컬 DB에도
#   agent_messages가 생긴다 — 쓰이지 않는 테이블이 생기는 정도가 아니라, 나중에 '중앙에서 받은
#   메시지'를 로컬 조회로 착각하는 버그의 온상이 된다. 스키마는 연결이 성립한 뒤에만 만든다.
#
# [🔴 pg_base의 재사용 범위] 커넥션 회복력 파라미터만 빌려온다. PG_DB/PG_PORT 등 로컬 전역은
#   절대 쓰지 않는다 — 중앙은 호스트·포트·DB가 전부 다르다.
# [과거사고 2026-07-20] 절전으로 죽은 소켓에서 recv()가 무한 블록 → 데몬 16시간 동결.
#   pg_base가 "두 경로에 동일 적용" 불변식을 걸어둔 값이며, 원격은 그 위험이 더 크다
#   (터널이 끊겨도 로컬 소켓은 established로 보인다). 단일 소스 유지 — 여기서 재정의 금지.
from src.pg_base import _CONN_RESILIENCE_KW
from src.node_identity import CONFIG_FILE, _read_config

_REQUIRED_KEYS = ('host', 'port', 'user', 'password', 'dbname')

# 연결 실패 후 재시도 간격(초). [WHY] 서버가 꺼져 있을 때 API 호출마다 5초 connect_timeout을
#   물면 UI가 통째로 느려진다. 실패를 기억해 그동안은 즉시 None을 돌려준다.
_RETRY_COOLDOWN_SEC = 30

_lock = threading.RLock()
_conn = None
_schema_ready = False
_last_fail_at = 0.0


def get_central_config(config_file=None) -> dict | None:
    """중앙 DB 설정을 반환한다. 미설정/불완전하면 None.

    [불변식] 예외를 던지지 않는다. 호출부는 None 하나만 처리하면 된다.
    [🔴 tunnel 하위 dict는 그대로 통과시킨다] tunnel_daemon.get_tunnel_config가 이 반환값에서
      cfg['tunnel']을 읽어 ssh 파라미터를 얻는다. 여기서 필수 키만 추려 버리면 터널 데몬이
      항상 '미설정'으로 판단해 조용히 잠든다 — 설정을 다 채운 사용자가 원인을 알 수 없는
      가장 나쁜 실패 모드다. 이 키는 psycopg2.connect에 넘기지 않으므로(아래 명시 인자)
      섞여 있어도 무해하다.
    """
    path = config_file or CONFIG_FILE
    raw = _read_config(path).get('central_db')
    if not isinstance(raw, dict):
        return None

    cfg = {}
    for key in _REQUIRED_KEYS:
        value = raw.get(key)
        if value is None or str(value).strip() == '':
            return None                      # 하나라도 비면 '미설정'으로 취급
        cfg[key] = str(value).strip()
    try:
        cfg['port'] = int(cfg['port'])
    except (TypeError, ValueError):
        return None
    if isinstance(raw.get('tunnel'), dict):
        cfg['tunnel'] = raw['tunnel']
    return cfg


def is_central_enabled(config_file=None) -> bool:
    """설정 존재 여부만 본다 — 연결을 시도하지 않는다.

    [WHY 연결과 분리] API가 'disabled' 플래그를 내려줄 때 매번 소켓을 여는 것은 낭비다.
      '설정은 있는데 서버가 죽음'과 '설정 자체가 없음'은 다른 상태이고, 프론트는 후자만
      조용히 숨기면 된다.
    """
    return get_central_config(config_file) is not None


def get_central_conn(config_file=None):
    """중앙 DB 커넥션 또는 None. 절대 예외를 던지지 않는다.

    [불변식] 설정 없음 → None. 설정이 틀림/서버 다운 → None. 이 함수가 raise 하면
      부팅 경로와 API 핸들러가 중앙 서버 상태에 인질로 잡힌다.
    [제약] autocommit=True로 고정한다. 대화 테이블은 append-only라 트랜잭션 경계가 필요 없고,
      Task 10의 LISTEN 스레드는 autocommit이 아니면 NOTIFY를 아예 못 받는다.
    """
    global _conn, _last_fail_at

    cfg = get_central_config(config_file)
    if cfg is None:
        return None

    with _lock:
        if _conn is not None:
            try:
                with _conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return _conn
            except Exception:
                _close_locked()

        # 최근 실패 직후면 소켓을 열지 않는다(위 쿨다운 주석).
        if _last_fail_at and (time.monotonic() - _last_fail_at) < _RETRY_COOLDOWN_SEC:
            return None

        try:
            import psycopg2
            conn = psycopg2.connect(
                host=cfg['host'], port=cfg['port'], user=cfg['user'],
                password=cfg['password'], dbname=cfg['dbname'],
                **_CONN_RESILIENCE_KW,
            )
            conn.autocommit = True
        except Exception:
            # [WHY 로그를 찍지 않는가] 서버가 꺼져 있는 것은 정상 상태다. 30초마다 콘솔에
            #   에러를 뱉으면 실제 사고가 묻힌다. 진단은 호출부(상태 API)가 한다.
            _last_fail_at = time.monotonic()
            _conn = None
            return None

        _last_fail_at = 0.0
        _conn = conn
        if not _ensure_schema_locked(conn):
            # DDL이 실패하면 이 커넥션으로는 아무것도 못 한다 — 반쯤 열린 상태를 남기지 않는다.
            _close_locked()
            _last_fail_at = time.monotonic()
            return None
        return _conn


# ── 중앙 스키마 ──────────────────────────────────────────────────────────────
# [불변식] agent_messages는 append-only — UPDATE/DELETE 경로를 만들지 않는다(보존 정리 제외).
#   읽음 상태는 message_cursors로 분리한다. 메시지 행을 갱신하면 여러 노드가 같은 행을 두고
#   경합하고, '누가 어디까지 읽었나'가 노드 수만큼 필요한데 행 하나에는 담기지 않는다.
# [불변식] created_at은 서버 now() — 각 PC의 시계를 믿지 않는다. 시계가 어긋난 PC 하나가
#   메시지 순서를 통째로 뒤섞는다.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id          BIGSERIAL PRIMARY KEY,
    from_node   TEXT        NOT NULL,
    from_agent  TEXT        NOT NULL,
    to_node     TEXT,
    to_agent    TEXT,
    content     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- to_node IS NULL = 브로드캐스트. 수신 조회는 항상 (대상, id > 커서) 형태라 복합 인덱스.
CREATE INDEX IF NOT EXISTS idx_agent_messages_to_id ON agent_messages (to_node, id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_created ON agent_messages (created_at);

CREATE TABLE IF NOT EXISTS message_cursors (
    node_id      TEXT        NOT NULL,
    agent_id     TEXT        NOT NULL DEFAULT '',
    last_seen_id BIGINT      NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, agent_id)
);

-- [WHY 트리거인가] 수신 측이 폴링만 하면 지연이 주기만큼 생기고, 주기를 줄이면
--   1코어 서버에 빈 쿼리가 쏟아진다. NOTIFY는 INSERT한 쪽이 비용을 내고 수신 측은
--   대기만 하므로, 노드가 늘어도 서버 부하가 늘지 않는다.
-- [제약] payload는 대상 노드 하나뿐이다. 메시지 본문을 실으면 8000바이트 상한에 걸리고
--   (초과 시 NOTIFY 자체가 실패해 조용히 알림이 끊긴다), 무엇보다 대기 중인 모든
--   커넥션에 내용이 흘러간다. 수신자는 신호만 받고 본인 몫을 직접 조회한다.
CREATE OR REPLACE FUNCTION notify_agent_message() RETURNS trigger AS $fn$
BEGIN
    PERFORM pg_notify('agent_msg', coalesce(NEW.to_node, ''));
    RETURN NEW;
END $fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_message ON agent_messages;
CREATE TRIGGER trg_agent_message AFTER INSERT ON agent_messages
    FOR EACH ROW EXECUTE FUNCTION notify_agent_message();
"""

NOTIFY_CHANNEL = 'agent_msg'

# 노드당 분당 발신 상한. [WHY] 에이전트가 루프에 빠져 INSERT를 쏟으면 1코어 서버가
#   그대로 무너지고, 그 사이 다른 노드의 대화까지 막힌다. 사람이 치는 대화는 분당 수 건이라
#   이 값에 걸리지 않는다 — 걸린다면 그건 사고다.
_SEND_LIMIT_PER_MIN = 60

# 보존 기간. [불변식 예외] agent_messages는 append-only지만 무한 증가는 1코어/1.9GB
#   서버에서 감당할 수 없다. 오래된 행 삭제만 유일한 DELETE 경로로 허용한다.
_RETENTION_DAYS = 30


def _ensure_schema_locked(conn) -> bool:
    """[제약] _lock 보유 상태에서만 호출. 프로세스당 1회만 DDL을 돌린다."""
    global _schema_ready
    if _schema_ready:
        return True
    try:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
        _schema_ready = True
        return True
    except Exception:
        return False


# ── 대화 ─────────────────────────────────────────────────────────────────────
_send_times: list = []


def _rate_limited() -> bool:
    """최근 1분 발신량이 상한을 넘었는가. [제약] 프로세스 단위 — 서버 강제가 아니다."""
    now = time.monotonic()
    _send_times[:] = [t for t in _send_times if now - t < 60]
    if len(_send_times) >= _SEND_LIMIT_PER_MIN:
        return True
    _send_times.append(now)
    return False


def send_message(content: str, to_node: str = '', to_agent: str = '',
                 from_agent: str = '', config_file=None) -> int | None:
    """중앙에 메시지를 남긴다. 메시지 id 또는 None(중앙 미설정/실패/과속).

    to_node가 비면 브로드캐스트다(모든 노드가 받는다).
    [불변식] created_at은 서버 now()를 쓴다 — 인자로 받지 않는다. 시계가 어긋난 PC
      하나가 전체 대화 순서를 뒤섞는 것을 막는다.
    [제약] 예외를 던지지 않는다. 대화 실패가 호출부를 죽이면 안 된다.
    """
    if not content or not str(content).strip():
        return None
    if _rate_limited():
        print(f'[central] 발신 상한({_SEND_LIMIT_PER_MIN}/분) 초과 — 건너뜀')
        return None

    conn = get_central_conn(config_file)
    if conn is None:
        return None

    try:
        from src.node_identity import get_node_id
        node = get_node_id(config_file)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_messages (from_node, from_agent, to_node, to_agent, content)"
                " VALUES (%s, %s, NULLIF(%s,''), NULLIF(%s,''), %s) RETURNING id",
                (node, from_agent or 'claude', to_node, to_agent, str(content)),
            )
            return int(cur.fetchone()[0])
    except Exception as exc:
        print(f'[central] 발신 실패: {exc}')
        return None


def fetch_new(agent_id: str = '', limit: int = 50, advance: bool = True,
              config_file=None) -> list[dict]:
    """이 노드 앞으로 온 새 메시지를 가져온다. 중앙 미설정/실패면 빈 목록.

    [불변식] 자기 노드가 보낸 것은 제외한다 — 브로드캐스트는 자신에게도 매칭되므로
      거르지 않으면 보낸 메시지를 즉시 되받아 무한 루프가 된다.
    [WHY 커서인가] 읽음 표시를 메시지 행에 쓰면 여러 노드가 같은 행을 두고 경합하고,
      '누가 어디까지 읽었나'는 노드 수만큼 필요한데 행 하나에는 담기지 않는다.
    [제약] advance=True는 조회와 동시에 커서를 민다 — 호출부가 처리에 실패하면 그
      메시지는 다시 오지 않는다. 처리 실패를 되돌려야 하는 호출부는 advance=False로
      받고 성공 후 ack_upto()를 부른다.
    """
    conn = get_central_conn(config_file)
    if conn is None:
        return []

    try:
        from src.node_identity import get_node_id
        node = get_node_id(config_file)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_seen_id FROM message_cursors WHERE node_id=%s AND agent_id=%s",
                (node, agent_id),
            )
            row = cur.fetchone()
            cursor = int(row[0]) if row else 0

            cur.execute(
                "SELECT id, from_node, from_agent, to_node, to_agent, content, created_at"
                "  FROM agent_messages"
                " WHERE id > %s AND from_node <> %s"
                "   AND (to_node IS NULL OR to_node = %s)"
                "   AND (to_agent IS NULL OR to_agent = '' OR to_agent = %s)"
                " ORDER BY id LIMIT %s",
                (cursor, node, node, agent_id, int(limit)),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if rows and advance:
            ack_upto(rows[-1]['id'], agent_id, config_file=config_file)
        return rows
    except Exception as exc:
        print(f'[central] 수신 실패: {exc}')
        return []


def ack_upto(message_id: int, agent_id: str = '', config_file=None) -> bool:
    """커서를 message_id까지 민다. 되돌아가지 않는다(GREATEST)."""
    conn = get_central_conn(config_file)
    if conn is None:
        return False
    try:
        from src.node_identity import get_node_id
        node = get_node_id(config_file)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO message_cursors (node_id, agent_id, last_seen_id)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (node_id, agent_id) DO UPDATE"
                "   SET last_seen_id = GREATEST(message_cursors.last_seen_id, EXCLUDED.last_seen_id),"
                "       updated_at = now()",
                (node, agent_id, int(message_id)),
            )
        return True
    except Exception as exc:
        print(f'[central] 커서 갱신 실패: {exc}')
        return False


def purge_old(days: int = _RETENTION_DAYS, config_file=None) -> int:
    """보존 기간이 지난 메시지를 지운다. 삭제 건수(실패 시 0).

    [제약] append-only 원칙의 유일한 예외다. 1코어/1.9GB 서버에서 무한 증가는
      감당되지 않는다. 커서는 id 기준이라 오래된 행이 사라져도 어긋나지 않는다.
    """
    conn = get_central_conn(config_file)
    if conn is None:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_messages"
                        " WHERE created_at < now() - make_interval(days => %s)", (int(days),))
            return cur.rowcount or 0
    except Exception as exc:
        print(f'[central] 보존 정리 실패: {exc}')
        return 0


def _close_locked() -> None:
    """[제약] _lock 보유 상태에서만 호출."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def close_central() -> None:
    """앱 종료/설정 변경 시 커넥션을 버린다. 스키마 플래그는 유지 — DDL은 멱등이지만
    재연결마다 다시 돌릴 이유가 없다."""
    with _lock:
        _close_locked()


def reset_state() -> None:
    """테스트 전용 — 커넥션·쿨다운·스키마 플래그를 초기화한다."""
    global _schema_ready, _last_fail_at
    with _lock:
        _close_locked()
        _schema_ready = False
        _last_fail_at = 0.0
