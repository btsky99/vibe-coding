"""
FILE: src/central_listener.py
DESCRIPTION: 중앙 대화(agent_messages) 실시간 수신 신호기 — Task 27.
             전용 커넥션으로 PG `agent_msg` 채널을 LISTEN 하고, 내 노드 앞으로 온
             메시지가 생기면 '대기 중' 플래그만 세운다. 메시지 본문을 여기서 꺼내지
             않는다 — 커서 전진은 실제 소비자(central_api.fetch)만 한다.
             LISTEN을 못 세우면 주기 폴링으로 강등해 기능을 잃지 않는다.

REVISION HISTORY:
- 2026-08-09 Claude: Phase 11 Task 36 — LISTEN 성립 직후 노드 명부 등록. 부팅 시점에
                     하면 터널이 아직 안 열려 실패한다.
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


def _deliver() -> None:
    """새 메시지를 슬롯 CLI에 배달한다(서버가 직접).

    [🔴 왜 리스너가 부르는가 — 배달이 화면에 인질로 잡혀 있었다]
      옛 구조는 주입을 프론트의 poll 에 얹었다. 그래서 React 훅이 안 돌면 그 PC 는
      아무 말도 못 받는다. 실측(2026-08-12 na2js): 앱·터널·리스너·게이트가 전부 정상인데
      UI 가 poll 을 부르지 않아 23시간 동안 배달 0건, 미수신 1건이 그대로 대기했다.
      사람에게는 '상대 클로드가 무시한다'로만 보인다.
    [불변식] 화면의 커서를 건드리지 않는다 — 배달기는 _INJECT_CURSOR 를 쓴다.
      그래서 서버가 먼저 배달해도 화면은 같은 메시지를 그대로 받아 그린다.
    [제약] pending 플래그는 여기서 소비하지 않는다. 그건 화면 몫이고, 하나를 둘이
      나눠 가지면 둘 중 하나가 신호를 잃는다.
    """
    try:
        from src import central_inject
        central_inject.deliver_pending()
    except Exception as exc:            # 배달 실패가 수신 신호 자체를 죽이면 안 된다
        _mark(error=f'배달: {str(exc)[:180]}')


def _register_self() -> None:
    """이 PC를 중앙 명부에 올린다 — 화면이 uuid 대신 '아픽스 3-1 (na2js)'을 그리는 근거.

    [제약] 실패(번호 미설정·번호 충돌·연결 끊김)를 예외로 올리지 않는다. 명부는 표시
      편의이지 대화의 전제조건이 아니다 — 여기서 터지면 LISTEN 루프가 통째로 죽는다.
    [WHY 충돌을 error로 남기나] 두 PC가 같은 번호를 들면 화면에서 한 대가 다른 대를
      사칭하게 된다. 조용히 넘기면 원인을 못 찾으므로 상태 스냅샷에 드러낸다.
    """
    try:
        from src.pg_central import register_node_ref
        ok, why = register_node_ref()
        if not ok and why and why != 'node_seq 미설정':
            _mark(error=f'명부: {why[:180]}')
    except Exception as exc:
        _mark(error=f'명부: {str(exc)[:180]}')


def _alive(conn) -> bool:
    """실제 왕복으로 커넥션 생존을 확인한다. LISTEN 커넥션에 써도 안전하다(autocommit).

    [🔴 왜 closed 플래그로는 부족한가] SSH 터널 너머가 끊겨도 **로컬 소켓은 established로
      남는다** — ssh 프로세스가 이쪽 끝을 붙잡고 있어 TCP keepalive 조차 응답한다.
      그래서 conn.closed 는 0 이고 select 는 얌전히 타임아웃만 하며, 리스너는 살아 있는
      것처럼 보이는 채로 **아무 알림도 못 받는 귀머거리**가 된다.
    [과거사고 2026-08-11] na2js 가 연결 13분 뒤 이 상태가 됐다. 명부 등록까지 성공해
      화면에는 'listen'(정상)으로 떴지만 그 뒤 도착한 메시지 3건을 전부 놓쳤다.
      NOTIFY 는 저장되지 않으므로 놓친 신호는 재연결 없이는 영영 오지 않는다.
    [WHY 이 패턴인가] pg_base._get_pg_conn 이 로컬 커넥션에 이미 쓰는 방식이다
      (매 사용 전 SELECT 1). 원격은 half-open 위험이 더 큰데 리스너만 빠져 있었다.
    """
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        return True
    except Exception:
        return False


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
            # [WHY 여기서 명부를 올리나] 연결이 성립한 직후가 유일하게 확실한 시점이다.
            #   부팅 시점에 하면 터널이 아직 안 열려 실패하고, 주기 작업으로 만들면 안 바뀌는
            #   값을 계속 쓰게 된다. 라벨/번호를 바꾼 뒤 재연결하면 자연히 갱신된다.
            #   실패해도 대화는 정상 동작한다 — 화면이 uuid 앞자리로 폴백할 뿐이다.
            _register_self()
            # 끊겨 있던 동안 도착한 것들도 지금 배달한다 — NOTIFY 는 저장되지 않으므로
            # 재구독만으로는 영영 안 온다(위 pending 재설정과 같은 이유).
            _deliver()

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
                _deliver()          # 화면을 기다리지 않고 서버가 직접 배달한다
            elif not _alive(conn):
                # [🔴 여기가 _SELECT_CAP_SEC 주석이 약속한 '재평가'다] 상한을 걸어 루프로
                #   돌아오기만 하고 아무것도 확인하지 않으면 재평가가 아니다 — 조용한
                #   단절을 영원히 못 벗어난다(위 _alive 의 과거사고 참조).
                #   알림을 받고 깨어난 경우(hit)에는 방금 서버와 통했으므로 확인하지 않는다:
                #   확인 비용은 60초에 한 번, 그것도 조용한 주기에만 든다.
                _mark(error='LISTEN 커넥션 무응답 — 재연결한다')
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                # 재연결 경로(위)가 pending 을 세운다 → 끊겨 있는 동안 놓친 NOTIFY 를
                # 조회 한 번으로 만회한다. 이 복구가 없으면 메시지가 영구 유실된다.
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
