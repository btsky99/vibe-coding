"""
FILE: tests/test_central_inject_remote.py
DESCRIPTION: 🔴 원격 주입 4중 게이트 회귀 테스트. 주입은 bypass 권한 CLI에 대한 사실상의
             명령 실행이라, 게이트가 하나라도 헐거워지면 중앙 DB 계정이 남의 PC를
             조종하는 통로가 된다. '열려 있는지'가 아니라 '막혀 있는지'를 고정한다.

             기본값이 꺼짐이라는 것도 함께 고정한다 — 설정을 안 한 사용자에게
             원격 주입이 켜져 있으면 그것만으로 사고다.

REVISION HISTORY:
- 2026-08-11 Claude: 신규 — 원격 주입이 금지에서 게이트로 바뀌며 신설.
"""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from src import central_inject as ci


@pytest.fixture
def cfg(tmp_path):
    return tmp_path / "config.json"


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ── 게이트 ① 토글 ───────────────────────────────────────────────────────────
def test_gate_off_by_default(cfg):
    """[🔴 핵심] 설정이 없으면 꺼져 있어야 한다."""
    _write(cfg, {})
    assert ci.remote_gate(cfg) == (False, set())


def test_gate_off_when_enabled_but_no_allow_list(cfg):
    """enabled 만 켜고 허용 목록이 비면 꺼진 것과 같다.

    '켰는데 왜 안 되지'가 '아무나 들어옴'보다 안전한 실패다.
    """
    _write(cfg, {"central_remote_inject": {"enabled": True}})
    assert ci.remote_gate(cfg) == (False, set())

    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": []}})
    assert ci.remote_gate(cfg) == (False, set())


def test_gate_on_with_allow_list(cfg):
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    assert ci.remote_gate(cfg) == (True, {3})


def test_bad_entries_do_not_void_whole_list(cfg):
    """오타 한 줄이 목록 전체를 무효로 만들지 않는다(그러나 오타 항목은 버린다)."""
    _write(cfg, {"central_remote_inject": {"enabled": True,
                                           "allow_nodes": [3, "x", None, "5"]}})
    on, allowed = ci.remote_gate(cfg)
    assert on and allowed == {3, 5}


# ── 게이트 ②③ 발신 노드 / 수신 슬롯 ────────────────────────────────────────
def test_disabled_gate_blocks_delivery(cfg):
    _write(cfg, {})
    ok, why = ci.deliver_remote({"from_node": "n1", "to_agent": "claude:T2",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert (ok, why) == (False, "remote_disabled")


def test_broadcast_is_never_injected(cfg):
    """[🔴 핵심] 받는 사람을 안 정한 말은 꽂지 않는다.

    브로드캐스트를 주입하면 노드 하나가 모든 슬롯을 조종하게 된다.
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    ok, why = ci.deliver_remote({"from_node": "n1", "to_agent": "",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert (ok, why) == (False, "broadcast_not_injected")


def test_unlisted_node_is_blocked(cfg, monkeypatch):
    """허용 목록에 없는 노드는 슬롯이 살아 있어도 막힌다."""
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 7)
    monkeypatch.setattr(ci, "_find_slot_session", lambda url, slot: "proj")

    ok, why = ci.deliver_remote({"from_node": "n7", "to_agent": "claude:T2",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert ok is False and "node_not_allowed" in why


def test_seq_lookup_failure_blocks(cfg, monkeypatch):
    """[🔴 핵심] 명부 조회가 실패하면 막는 쪽으로 넘어진다.

    조회 실패를 '일단 허용'으로 처리하면 게이트가 네트워크 상태에 따라 열린다.
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 0)
    monkeypatch.setattr(ci, "_find_slot_session", lambda url, slot: "proj")

    ok, why = ci.deliver_remote({"from_node": "n?", "to_agent": "claude:T2",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert ok is False and "node_not_allowed" in why


# ── 왕복 성립 조건 ──────────────────────────────────────────────────────────
def test_sender_without_slot_is_not_injected(cfg, monkeypatch):
    """[🔴 핵심] 답장 주소를 만들 수 없는 메시지는 꽂지 않는다.

    주입문은 "답장: central_say.py {발신자주소}"를 함께 싣는다. 발신자 슬롯을 모르면
    그 주소가 깨져 상대가 답하려다 실패한다 — 답할 수 없는 말은 상대 슬롯의 컨텍스트만
    축내고 대화는 안 된다.
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 3)
    monkeypatch.setattr(ci, "_find_slot_session", lambda url, slot: "proj")

    ok, why = ci.deliver_remote({"from_node": "n3", "from_agent": "claude",
                                 "to_agent": "claude:T2", "content": "hi"},
                                "http://127.0.0.1:1", cfg)
    assert (ok, why) == (False, "sender_slot_unknown")


def test_reply_address_points_back_to_sender(cfg, monkeypatch):
    """주입문의 답장 주소가 '발신노드-발신슬롯'이어야 왕복이 닫힌다.

    이 주소가 틀리면 상대는 받기만 하고 답을 못 보낸다(단방향으로 퇴화).
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 3)
    monkeypatch.setattr(ci, "_find_slot_session", lambda url, slot: "proj")
    ci._recent.clear()

    sent = {}

    def _fake_urlopen(req, timeout=None):
        sent['body'] = req.data.decode('utf-8')

        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R()

    monkeypatch.setattr(ci.urllib.request, "urlopen", _fake_urlopen)

    ok, _ = ci.deliver_remote({"from_node": "n3", "from_agent": "claude:T1",
                               "to_agent": "claude:T2", "content": "안녕"},
                              "http://127.0.0.1:1", cfg)
    assert ok is True
    body = json.loads(sent['body'])['text']
    assert "아픽스 3-1" in body, "발신자 주소가 주입문에 없다"
    assert "central_say.py 3-1" in body, "답장 주소가 발신자를 가리키지 않는다"
    ci._recent.clear()


# ── 게이트 ④ 상한 ───────────────────────────────────────────────────────────
def test_remote_rate_limit_is_separate_from_local():
    """원격 폭주가 로컬 대화 몫을 굶기지 않는다 — 창 키가 분리돼 있다."""
    ci._recent.clear()
    for _ in range(ci._MAX_REMOTE_PER_WINDOW):
        assert ci._rate_ok("remote:T2@p", limit=ci._MAX_REMOTE_PER_WINDOW) is True
    assert ci._rate_ok("remote:T2@p", limit=ci._MAX_REMOTE_PER_WINDOW) is False
    # 같은 슬롯의 로컬 창은 아직 멀쩡하다
    assert ci._rate_ok("T2@p") is True
    ci._recent.clear()


def test_remote_limit_is_stricter_than_local():
    """원격은 남의 PC에서 도는 실행이라 로컬보다 보수적이어야 한다."""
    assert ci._MAX_REMOTE_PER_WINDOW < ci._MAX_PER_WINDOW
