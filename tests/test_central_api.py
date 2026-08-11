"""
FILE: tests/test_central_api.py
DESCRIPTION: 중앙 대화 HTTP 라우트(Task 26)와 실시간 수신 신호기(Task 27)의 규약 회귀 —
             중앙 서버 없이 항상 도는 방어선.

             [WHY 서버 없이 도는 테스트가 먼저인가] CI와 다른 사용자 환경에는 중앙 서버가
             없다. 실왕복은 tests/test_central_e2e.py가 서버가 있을 때만 한다. 여기서
             고정하는 것은 '서버가 없어도 앱이 멀쩡한가'와 '신호를 잃지 않는가' 두 가지다.

REVISION HISTORY:
- 2026-08-09 Claude: 신규. Task 26/27이 테스트 없이 커밋 대기 중이던 구멍을 메움.
                     특히 poll의 신호 소비/복원은 유실 경로라 단위로 고정해야 한다.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from api import central_api  # noqa: E402
from src import central_listener, pg_central  # noqa: E402


class FakeHandler:
    """json_response/read_body가 요구하는 최소 인터페이스만 흉내낸다."""

    def __init__(self, body: dict | None = None):
        self.status = None
        self.headers = {}
        self._chunks: list[bytes] = []
        self._body = json.dumps(body or {}, ensure_ascii=False).encode('utf-8')
        self.rfile = self
        self.wfile = self
        self.headers = {'Content-Length': str(len(self._body))}

    # --- BaseHTTPRequestHandler 흉내 ---
    def _cors_origin(self):
        return '*'

    def send_response(self, status):
        self.status = status

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def write(self, data):
        self._chunks.append(data)

    def read(self, n):
        return self._body[:n]

    @property
    def json(self) -> dict:
        return json.loads(b''.join(self._chunks).decode('utf-8'))


def _pp(query: str = ''):
    return urlparse(f'/api/central/x?{query}')


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """[제약] 리스너 _state는 모듈 전역이라 테스트 간 누수가 생긴다 — 매번 초기화."""
    pg_central._send_times.clear()
    with central_listener._lock:
        central_listener._state.update(running=False, mode='off', pending=False,
                                       last_signal_at=0.0, last_error='')
    monkeypatch.setattr('src.node_identity.get_node_id', lambda *a, **k: 'nodeA')
    yield


# ── 무동작 회귀 (중앙 미설정) ────────────────────────────────────────────────
# [🔴 이 그룹이 깨지면 중앙 기능을 더 얹지 않는다] 중앙을 안 쓰는 사용자에게 500이 가면
#   프론트가 에러 배지를 띄운다 — '안 쓰는 기능'과 '고장'은 다른 상태다.

def _disable(monkeypatch):
    monkeypatch.setattr(pg_central, 'is_central_enabled', lambda *a, **k: False)
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: None)


def test_미설정_status는_200에_enabled_False(monkeypatch):
    _disable(monkeypatch)
    h = FakeHandler()
    central_api.status(h, _pp())
    assert h.status == 200
    assert h.json['enabled'] is False
    assert h.json['connected'] is False


def test_미설정_status는_enabled와_connected를_분리한다(monkeypatch):
    """[불변식] 합치면 '설정 안 함'과 '서버 죽음'이 같은 회색으로 그려져 장애가 묻힌다."""
    monkeypatch.setattr(pg_central, 'is_central_enabled', lambda *a, **k: True)
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: None)
    h = FakeHandler()
    central_api.status(h, _pp())
    assert h.json['enabled'] is True and h.json['connected'] is False


@pytest.mark.parametrize('route', ['messages', 'poll'])
def test_미설정_조회는_200에_빈_목록(monkeypatch, route):
    _disable(monkeypatch)
    h = FakeHandler()
    getattr(central_api, route)(h, _pp())
    assert h.status == 200
    assert h.json['messages'] == [] and h.json['count'] == 0


def test_미설정_발신은_500이_아니라_ok_False(monkeypatch):
    """요청 자체는 정상이다 — 중앙이 없을 뿐. 4xx/5xx로 답하면 프론트가 고장으로 표시한다."""
    _disable(monkeypatch)
    monkeypatch.setattr(pg_central, 'send_message', lambda *a, **k: None)
    h = FakeHandler({'content': '안녕'})
    central_api.send(h, _pp())
    assert h.status == 200
    assert h.json['ok'] is False and h.json['id'] is None


# ── 입력 검증 ────────────────────────────────────────────────────────────────

def test_빈_내용_발신은_400(monkeypatch):
    h = FakeHandler({'content': '   '})
    central_api.send(h, _pp())
    assert h.status == 400


def test_ack에_message_id가_없으면_400():
    h = FakeHandler({})
    central_api.ack(h, _pp())
    assert h.status == 400


def test_limit은_상한을_넘지_않는다():
    """[WHY] 오래 꺼져 있던 노드가 켜지면 밀린 메시지가 한꺼번에 온다."""
    assert central_api._limit(_pp('limit=99999')) == central_api._MAX_LIMIT
    assert central_api._limit(_pp('limit=0')) == 1
    assert central_api._limit(_pp('limit=이상한값')) == 50


# ── poll 신호 규약 (유실 경로) ───────────────────────────────────────────────

def test_신호가_없으면_원격을_조회하지_않는다(monkeypatch):
    """[WHY] 매 폴링마다 터널 왕복을 하면 NOTIFY를 도입한 이유가 사라진다."""
    monkeypatch.setattr(pg_central, 'is_central_enabled', lambda *a, **k: True)
    called = []
    monkeypatch.setattr(pg_central, 'fetch_new', lambda **k: called.append(k) or [])

    h = FakeHandler()
    central_api.poll(h, _pp('agent=claude:T1'))

    assert called == [], '신호가 없는데 원격을 조회했다'
    assert h.json['signalled'] is False


def test_신호가_있으면_한_번_조회한다(monkeypatch):
    monkeypatch.setattr(pg_central, 'is_central_enabled', lambda *a, **k: True)
    monkeypatch.setattr(pg_central, 'fetch_new',
                        lambda **k: [{'id': 3, 'content': '안녕'}])
    central_listener.raise_pending()

    h = FakeHandler()
    central_api.poll(h, _pp('agent=claude:T1'))

    assert h.json['count'] == 1 and h.json['signalled'] is True
    assert central_listener.snapshot()['pending'] is False, '신호를 내리지 않았다'


def test_조회_불가면_신호를_되돌린다(monkeypatch):
    """[🔴 유실 방지] NOTIFY는 저장되지 않는다 — 신호만 소비하고 못 받아오면 그 메시지는
    다음 NOTIFY까지 잠든다. 헛조회는 손해가 없지만 유실은 있다."""
    monkeypatch.setattr(pg_central, 'is_central_enabled', lambda *a, **k: True)
    monkeypatch.setattr(pg_central, 'fetch_new', lambda **k: [])
    monkeypatch.setattr(pg_central, 'get_central_conn', lambda *a, **k: None)
    central_listener.raise_pending()

    central_api.poll(FakeHandler(), _pp())

    assert central_listener.snapshot()['pending'] is True, '신호가 사라졌다'


def test_consume_pending는_읽고_즉시_내린다():
    """test-and-clear가 아니면 그 사이 도착한 NOTIFY가 함께 지워진다."""
    central_listener.raise_pending()
    assert central_listener.consume_pending() is True
    assert central_listener.consume_pending() is False


# ── 리스너 기동 규약 ─────────────────────────────────────────────────────────

def test_미설정이면_리스너가_기동하지_않는다(monkeypatch):
    monkeypatch.setattr(central_listener, 'is_central_enabled', lambda *a, **k: False)
    assert central_listener.start() is False
    central_listener.run_forever()          # 예외 없이 즉시 반환해야 한다
    assert central_listener.snapshot()['running'] is False


def test_run_forever는_호출_스레드에서_돈다(monkeypatch):
    """[🔴 daemons.py 불변식] 안에서 스레드를 만들면 등록된 이름의 스레드가 즉시 죽어
    daemon_status()가 **살아 있는 데몬을 죽었다고 표시**한다."""
    monkeypatch.setattr(central_listener, 'is_central_enabled', lambda *a, **k: True)
    seen = {}
    monkeypatch.setattr(central_listener, '_loop',
                        lambda node, stop: seen.update(name=threading.current_thread().name))

    central_listener.run_forever()

    assert seen.get('name') == threading.current_thread().name


def test_이미_돌고_있으면_중복_기동하지_않는다(monkeypatch):
    monkeypatch.setattr(central_listener, 'is_central_enabled', lambda *a, **k: True)
    with central_listener._lock:
        central_listener._state['running'] = True
    assert central_listener.start() is False


def test_브로드캐스트_payload는_모든_노드가_받는다():
    """[제약] payload는 to_node 하나뿐 — 빈 문자열이 브로드캐스트다(스키마 트리거 coalesce)."""
    assert central_listener._relevant('', 'nodeA') is True
    assert central_listener._relevant('nodeA', 'nodeA') is True
    assert central_listener._relevant('nodeB', 'nodeA') is False


# ── 🔴 설계 고정 사항 ────────────────────────────────────────────────────────

def test_중앙_라우트에_원격_실행이_없다():
    """[🔴 변경 금지] 중앙 DB는 여러 PC의 공용 접점이다. 실행 엔드포인트가 하나라도 생기면
    중앙 계정 하나가 전 노드 RCE 권한이 된다. 실행이 필요하면 LAN 브리지의 3중 게이트를 쓴다.
    """
    public = {n for n in dir(central_api) if not n.startswith('_')}
    금지 = {'exec', 'run', 'command', 'shell', 'launch', 'spawn', 'eval'}
    assert not (public & 금지), f'중앙 API에 실행 계열 함수가 생겼다: {public & 금지}'

    source = (BASE / '.ai_monitor' / 'server.py').read_text(encoding='utf-8')
    routes = {ln.split("'")[1] for ln in source.splitlines()
              if "'/api/central/" in ln and ':' in ln}
    # [허용 목록] 라우트를 늘릴 때는 반드시 여기에 명시적으로 추가한다 — 이 테스트의 목적은
    #   '실행 통로가 몰래 생기는 것'을 막는 것이지 라우트 추가 자체를 막는 것이 아니다.
    #   nodes: uuid→번호/이름 명부 조회(읽기 전용, Phase 11 Task 35).
    #   allow-node: **이 PC의** 주입 허용 설정에 번호 하나를 더한다(2026-08-12).
    #     실행 통로가 아니다 — 중앙에서 부를 수 없고(로컬 전용), 하는 일은 config 쓰기다.
    #     오히려 이것이 없으면 사용자가 config.json 을 손으로 고쳐야 하고, 실제로 그러다
    #     BOM 하나로 노드를 통째로 잃었다(na2js). 게이트를 여는 판단은 여전히 사람이 한다.
    assert routes == {'/api/central/status', '/api/central/messages',
                      '/api/central/poll', '/api/central/send',
                      '/api/central/ack', '/api/central/nodes',
                      '/api/central/allow-node'}, f'중앙 라우트가 늘었다: {routes}'


def test_미수신_집계는_수신_조건과_같아야_한다():
    """[제약] 어긋나면 '안 읽음 3'인데 조회하면 0건인 상태가 된다.

    [WHY 리터럴 대조를 그만뒀나] 수신자 조건이 _to_agent_clause 로 빠지면서(Phase 11)
      두 함수 본문에서 리터럴이 사라졌다. 리터럴을 찾는 검사는 **불변식이 더 튼튼해진
      리팩터링을 실패로 신고**한다. 지금 검사해야 할 것은 '같은 문자열을 두 번 썼는가'가
      아니라 '조건을 만드는 곳이 하나인가'다 — 그래서 헬퍼 경유를 본다.
    """
    import inspect
    # 조건 생성이 한 곳(_to_agent_clause)에 있고, 그 안에 실제 조건이 들어 있어야 한다.
    helper = ' '.join(inspect.getsource(pg_central._to_agent_clause).split())
    assert "to_agent IS NULL OR to_agent = '' OR to_agent = %s" in helper

    # 두 함수는 자기 손으로 조건을 쓰지 않고 헬퍼를 부른다(복붙 재발 방지).
    공통 = ('from_node <> %s', 'to_node IS NULL OR to_node = %s')
    for 이름 in ('fetch_new', 'pending_count'):
        src = ' '.join(inspect.getsource(getattr(pg_central, 이름)).split())
        assert '_to_agent_clause(agent_id)' in src, f'{이름}이 헬퍼를 안 쓴다'
        assert 'agent_sql' in src and 'agent_params' in src, f'{이름}이 헬퍼 결과를 안 붙인다'
        assert "to_agent = '' OR" not in src, f'{이름}에 조건이 복붙돼 있다'
        for c in 공통:
            assert c in src, f'조건 불일치: {이름} — {c}'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
