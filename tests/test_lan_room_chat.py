"""
FILE: tests/test_lan_room_chat.py
DESCRIPTION: LAN 그룹방 회귀 테스트 — scope가 토큰 서명에 묶이는지, 1:1 하위호환이 보존되는지,
             팬아웃이 오프라인 피어 때문에 전체 실패하지 않는지 검증.

REVISION HISTORY:
- 2026-07-30 Claude: 신규 — 3대 이상에서 1:1 창만 있던 제약을 푼 그룹방(중앙 릴레이 없는 팬아웃).
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))


def _load_bridge():
    """lan_bridge는 스크립트(패키지 아님)라 파일 경로로 로드한다 — daemons가 subprocess로 띄우는 구조."""
    spec = importlib.util.spec_from_file_location(
        'lan_bridge_mod', _PROJECT_ROOT / '.ai_monitor' / 'lan_bridge.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def bridge():
    return _load_bridge()


# ── 서명 ────────────────────────────────────────────────────────────────────

def test_peer_scope_hash_stays_backward_compatible(bridge):
    """[호환] 1:1 해시는 기존 sha256(content)를 그대로 유지 — 구버전 피어와 채팅이 깨지면 안 된다."""
    assert bridge._chat_body_hash('안녕', 'peer') == hashlib.sha256('안녕'.encode()).hexdigest()


def test_room_scope_is_bound_to_signature(bridge):
    """[보안] scope 바꿔치기(room↔peer)는 해시가 달라져 토큰 무효가 되어야 한다."""
    assert bridge._chat_body_hash('안녕', 'room') != bridge._chat_body_hash('안녕', 'peer')
    # 내용이 달라도 당연히 달라야 함
    assert bridge._chat_body_hash('안녕', 'room') != bridge._chat_body_hash('반가워', 'room')


def test_unknown_scope_falls_back_to_peer(bridge):
    """알 수 없는 scope는 1:1로 취급 — 신규 값이 조용히 room 권한을 얻으면 안 된다."""
    assert bridge._chat_body_hash('x', 'weird') == bridge._chat_body_hash('x', 'peer')


# ── 팬아웃 ──────────────────────────────────────────────────────────────────

class _FakePeers:
    def __init__(self, peers):
        self._peers = peers
        self.self_id = 'me'

    def list_peers(self):
        return self._peers

    def is_trusted(self, pid):
        return any(p['peer_id'] == pid for p in self._peers)


def test_broadcast_requires_paired_peers(bridge, monkeypatch):
    monkeypatch.setitem(bridge.STATE, 'peers', _FakePeers([]))
    r = bridge.broadcast_chat('안녕')
    assert r['ok'] is False
    assert '페어링' in r['error']


def test_broadcast_fans_out_to_all_peers(bridge, monkeypatch):
    """3대 구성: 나 + B + C → 한 번 보내면 두 피어 모두에게 room scope로 전송된다."""
    monkeypatch.setitem(bridge.STATE, 'peers', _FakePeers([
        {'peer_id': 'B', 'name': 'pc-b'}, {'peer_id': 'C', 'name': 'pc-c'}]))
    calls = []
    monkeypatch.setattr(bridge, 'send_chat',
                        lambda pid, content, scope='peer': calls.append((pid, scope)) or {'ok': True})

    r = bridge.broadcast_chat('전원 안녕')

    assert r['ok'] is True
    assert sorted(c[0] for c in calls) == ['B', 'C']
    assert {c[1] for c in calls} == {'room'}, 'room scope로 보내지 않으면 수신측이 1:1로 저장한다'
    assert r['failed'] == []


def test_offline_peer_does_not_fail_whole_room(bridge, monkeypatch):
    """[불변식] 한 대가 꺼져 있어도 나머지에게는 도달해야 한다 — 아니면 방이 사실상 죽는다."""
    monkeypatch.setitem(bridge.STATE, 'peers', _FakePeers([
        {'peer_id': 'B', 'name': 'pc-b'}, {'peer_id': 'C', 'name': 'pc-c'}]))
    monkeypatch.setattr(bridge, 'send_chat',
                        lambda pid, content, scope='peer':
                        {'ok': False, 'error': '상대가 오프라인'} if pid == 'C' else {'ok': True})

    r = bridge.broadcast_chat('전원 안녕')

    assert r['ok'] is True, '일부 실패로 전체를 실패시키면 안 된다'
    assert [s['peer_id'] for s in r['sent']] == ['B']
    assert [f['peer_id'] for f in r['failed']] == ['C']


# ── 저장 스코프 분리 ────────────────────────────────────────────────────────

def test_drain_routes_room_and_peer_messages_separately(monkeypatch):
    """[핵심] room 메시지는 to_peer='*', 1:1은 to_peer=self_id로 저장돼야 한다.

    섞이면 ① 방에 안 보이거나 ② 1:1 창에 남의 방 메시지가 노출된다(오피스/클래식 분리 원칙과 동일).
    """
    import api.lan_api as lan_api
    saved = []
    monkeypatch.setattr(lan_api, '_proxy', lambda dd, method, path, body=None: {
        'messages': [
            {'from_peer': 'B', 'content': '방에 안녕', 'scope': 'room'},
            {'from_peer': 'C', 'content': '너한테만', 'scope': 'peer'},
            {'from_peer': 'D', 'content': '스코프 없음(구버전)'},
        ]})
    monkeypatch.setattr(lan_api, 'save_lan_message',
                        lambda f, t, c, p: saved.append((f, t, c)) or True)

    lan_api._drain_chat_inbox(Path('.'), 'me', 'proj')

    assert ('B', lan_api.ROOM_ID, '방에 안녕') in saved
    assert ('C', 'me', '너한테만') in saved
    # 구버전(scope 필드 없음)은 1:1로 — 방으로 잘못 올리면 사생활 노출
    assert ('D', 'me', '스코프 없음(구버전)') in saved
