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
"""


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
