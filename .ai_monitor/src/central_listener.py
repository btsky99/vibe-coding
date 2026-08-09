"""
FILE: src/central_listener.py
DESCRIPTION: 중앙 대화(agent_messages) 실시간 수신 신호기 — Task 27.
             전용 커넥션으로 PG `agent_msg` 채널을 LISTEN 하고, 내 노드 앞으로 온
             메시지가 생기면 '대기 중' 플래그만 세운다. 메시지 본문을 여기서 꺼내지
             않는다 — 커서 전진은 실제 소비자(central_api.fetch)만 한다.
             LISTEN을 못 세우면 주기 폴링으로 강등해 기능을 잃지 않는다.

REVISION HISTORY:
- 2026-08-09 Claude: Task 31 — purge_old 주기 배선. 보존 정책이 코드에만 있고 아무도
                     부르지 않아 사실상 무기한 보관이던 구멍을 이 루프에 얹어 막음.
- 2026-08-09 Claude: 신규. Task 27 — 폴링 지연/부하 문제를 NOTIFY로 해소하되,
                     '신호만 받고 조회는 소비자가' 구조로 메시지 유실 경로를 차단.
"""
from __future__ import annotations

import threading
import time

from src.pg_central import NOTIFY_CHANNEL, get_central_config, is_central_enabled
from src.pg_base import _CONN_RESILIENCE_KW

# LISTEN이 살아 있어도 select에 거는 상한. [WHY] 절전/터널 단절 후의 half-open 소켓은
#   closed 플래그가 서지 않아 select가 영원히 안 깨어난다(heartbeat_daemon 15시간 동결 전례).
#   상한을 걸면 최소 이 주기로 루프에 복귀해 커넥션을 재평가한다.
_SELECT_CAP_SEC = 60.0

# LISTEN 강등 시 폴링 주기. [WHY 60초인가] 강등 상태는 '느려도 동작'이 목표다.
#   더 짧게 잡으면 터널이 끊긴 동안 1코어 서버에 빈 쿼리를 쏟는다.
_DEGRADED_POLL_SEC = 60.0

# 커넥션 재수립 백오프 상한. 서버가 꺼져 있는 것은 정상 상태이므로 조용히 물러난다.
_BACKOFF_MAX_SEC = 120.0

# 보존 정리 주기(Task 31). [WHY 24시간인가] 삭제 대상은 30일 경과분이라 하루 늦어도
#   무해하고, 1코어 서버에 DELETE를 자주 물릴 이유가 없다.
_PURGE_INTERVAL_SEC = 24 * 3600.0
_last_purge_at = 0.0

_lock = threading.Lock()
_thread: threading.Thread | None = None

# [불변식] _state는 _lock 아래에서만 쓴다. 읽기는 snapshot()이 락을 잡고 복사한다.
_state = {
    'running': False,
    'mode': 'off',          # off | listen | degraded
    'pending': False,       # 새 메시지가 있을 수 있다 — 소비자가 조회하면 내린다
    'last_signal_at': 0.0,  # NOTIFY 또는 강등 폴링 틱 시각(epoch)
    'last_error': '',
}


def _mark(mode: str | None = None, pending: bool | None = None,
          error: str | None = None) -> None:
    with _lock:
        if mode is not None:
            _state['mode'] = mode
        if pending is not None:
            _state['pending'] = pending
            if pending:
                _state['last_signal_at'] = time.time()
        if error is not None:
            _state['last_error'] = error


def snapshot() -> dict:
    """현재 리스너 상태 사본. API가 그대로 내려보낸다."""
    with _lock:
        return dict(_state)


def consume_pending() -> bool:
    """대기 플래그를 읽고 내린다(test-and-clear).

    [WHY 원자적으로 내리는가] 소비자가 '읽고 나서 따로 내리면' 그 사이 도착한 NOTIFY가
      함께 지워져 메시지가 다음 신호까지 잠든다. 여기서 내리고, 조회 실패 시 호출부가
      다시 세우는(`raise_pending`) 방향이 안전하다 — 헛조회는 손해가 없지만 유실은 있다.
    """
    with _lock:
        was = _state['pending']
        _state['pending'] = False
        return was


def raise_pending() -> None:
    """조회 실패 등으로 소비를 되돌릴 때 사용. 신호를 다시 세운다."""
    _mark(pending=True)


def _open_listen_conn(node: str):
    """LISTEN 전용 커넥션. 실패 시 None.

    [🔴 왜 pg_central의 공유 커넥션을 쓰지 않는가] LISTEN은 세션에 붙는다. 공유 커넥션은
      실패 시 _close_locked()로 교체되는데, 그때 구독이 소리 없이 사라진다. 남은 스레드는
      '듣고 있다'고 믿으며 영원히 아무것도 받지 못한다 — 가장 진단하기 나쁜 실패 모드다.
    """
    cfg = get_central_config()
    if cfg is None:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=cfg['host'], port=cfg['port'], user=cfg['user'],
            password=cfg['password'], dbname=cfg['dbname'],
            **_CONN_RESILIENCE_KW,
        )
        conn.autocommit = True   # [제약] autocommit이 아니면 NOTIFY가 도착하지 않는다
        with conn.cursor() as cur:
            cur.execute(f'LISTEN {NOTIFY_CHANNEL};')
        return conn
    except Exception as exc:
        _mark(error=str(exc)[:200])
        return None


def _relevant(payload: str, node: str) -> bool:
    """이 노드가 반응해야 할 알림인가.

    [제약] payload는 to_node 하나뿐이다(스키마 트리거 참조). 빈 문자열은 브로드캐스트라
      모든 노드가 받는다. 자기 발신분 필터는 여기서 못 한다 — payload에 from_node가 없다.
      대신 fetch_new가 from_node로 거른다(무한 루프 방지 불변식은 그쪽이 소유).
    """
    return payload == '' or payload == node


def _maybe_purge() -> None:
    """하루 한 번 보존 기간 지난 중앙 메시지를 지운다 — Task 31.

    [🔴 왜 여기인가] purge_old는 Task 25에 구현돼 있었지만 호출자가 없어 '30일 보존'이
      문서상의 약속일 뿐이었다. 별도 데몬을 세우지 않은 이유는 이 루프가 이미 최소
      _SELECT_CAP_SEC 주기로 깨어나고, **LISTEN이 살아 있는 경로에서만** 호출되므로
      '연결 확인'을 공짜로 얻기 때문이다. 스레드 하나를 아끼는 것보다, 터널이 죽은 동안
      원격 DELETE를 시도하지 않는다는 보장이 크다.
    [제약] 호출 지점은 커넥션이 성립한 뒤여야 한다. 강등(degraded) 경로에서 부르면
      매 폴링 틱마다 연결 재시도 비용을 문다.
    [불변식] 여러 노드가 같은 중앙 DB에 붙어 각자 이 정리를 돈다 — DELETE는 멱등이라
      중복 실행은 무해하다. '누가 청소 담당인가'를 정하는 조율 장치를 두지 않는 이유다.
    [제약] 실패해도 다음 주기까지 재시도하지 않는다(시각을 미리 찍는다). 보존 정리는
      늦어도 되는 작업이고, 실패를 즉시 되풀이하면 죽은 서버에 매 틱 DELETE를 던진다.
    """
    global _last_purge_at
    now = time.time()
    if now - _last_purge_at < _PURGE_INTERVAL_SEC:
        return
    _last_purge_at = now
    try:
        from src.pg_central import purge_old
        removed = purge_old()
        if removed:
            print(f'[central] 보존 정리 — 오래된 메시지 {removed}건 삭제')
    except Exception as exc:
        _mark(error=f'purge: {str(exc)[:180]}')


def _loop(node: str, stop: threading.Event) -> None:
    import select

    conn = None
    backoff = 1.0
    while not stop.is_set():
        if conn is None or getattr(conn, 'closed', 0):
            conn = _open_listen_conn(node)
            if conn is None:
                # 강등: 신호를 못 받으니 주기적으로 '있을지도 모른다'고 세운다.
                # 기능이 멈추는 것보다 느린 편이 낫다.
                _mark(mode='degraded', pending=True)
                stop.wait(min(backoff, _DEGRADED_POLL_SEC))
                backoff = min(backoff * 2, _BACKOFF_MAX_SEC)
                continue
            backoff = 1.0
            _mark(mode='listen', error='')
            # [WHY 재연결 직후 한 번 세우는가] 끊겨 있던 동안 도착한 메시지는 NOTIFY를
            #   놓쳤다. NOTIFY는 저장되지 않으므로 재구독만으로는 영원히 못 받는다.
            _mark(pending=True)

        try:
            _maybe_purge()          # 연결이 성립한 경로에서만 (Task 31)
            select.select([conn], [], [], _SELECT_CAP_SEC)
            conn.poll()
            hit = False
            while conn.notifies:
                note = conn.notifies.pop(0)
                if _relevant(getattr(note, 'payload', '') or '', node):
                    hit = True
            if hit:
                _mark(pending=True)
        except Exception as exc:
            _mark(error=str(exc)[:200])
            try:
                conn.close()
            except Exception:
                pass
            conn = None

    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    _mark(mode='off')
    with _lock:
        _state['running'] = False


_stop = threading.Event()


def _claim() -> str | None:
    """중복 기동을 막고 노드 id를 돌려준다. 이미 돌고 있거나 미설정이면 None."""
    if not is_central_enabled():
        return None
    with _lock:
        if _state['running']:
            return None
        _state['running'] = True
    _stop.clear()
    from src.node_identity import get_node_id
    return get_node_id()


def run_forever() -> None:
    """데몬 레지스트리 진입점 — **호출한 스레드에서** 루프를 돈다.

    [🔴 왜 여기서 스레드를 만들지 않는가] start_all_daemons가 DAEMON_TOGGLES의 이름으로
      스레드를 만들어 이 함수를 태운다. 안에서 또 스레드를 띄우면 등록된 이름의 스레드는
      즉시 죽고, daemon_status()가 threading.enumerate()로 찾지 못해 **살아 있는 데몬을
      죽었다고 표시**한다(daemons.py 불변식).
    """
    node = _claim()
    if node is None:
        return
    _loop(node, _stop)


def start() -> bool:
    """리스너를 별도 데몬 스레드로 기동(테스트·스크립트용). 성공하면 True.

    [제약] 서버 부팅 경로는 이 함수를 쓰지 않는다 — run_forever를 쓴다(위 이유).
    """
    global _thread
    node = _claim()
    if node is None:
        return False
    _thread = threading.Thread(target=_loop, args=(node, _stop),
                               daemon=True, name='central-listen')
    _thread.start()
    return True


def stop() -> None:
    """리스너 종료 요청. 스레드가 select 상한 내에 빠져나온다."""
    _stop.set()
