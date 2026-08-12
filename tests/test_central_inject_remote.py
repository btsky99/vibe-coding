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


def _swallow_urlopen(captured: dict | None = None):
    """PTY write 를 실제로 보내지 않고 삼키는 urlopen 대역.

    [WHY 필요한가] deliver_remote 의 마지막 단계는 실제 HTTP POST 다. 대역이 없으면
    테스트가 '연결 거부'로 실패하는데, 그 실패는 게이트 판정과 구별되지 않아
    "막혔다"와 "PTY 서버가 없다"가 같은 모습이 된다.
    """
    def _fake(req, timeout=None):
        if captured is not None:
            captured['body'] = req.data.decode('utf-8')

        class _R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R()
    return _fake


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


def test_broadcast_goes_to_one_slot_only(cfg, monkeypatch):
    """[🔴 핵심] 받는 슬롯을 안 정한 말은 **대표 슬롯 하나**에만 꽂힌다.

    금지 대상은 '슬롯 미지정'이 아니라 '전 슬롯 동시 도달'이다. 옛 구현은 이 둘을
    뭉개 브로드캐스트를 통째로 버렸고, 그 결과 사람이 창에 그냥 한 줄 쓰면 **어느
    CLI도 그 말을 못 봤다** — 화면엔 뜨는데 상대 클로드는 침묵하니 사용자에게는
    '읽고 무시한다'로 보였다(2026-08-11 na2js 왕복 실패의 절반).
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 3)
    seen = {}

    def _find(url, slot):
        seen['slot'] = slot
        return "proj"

    monkeypatch.setattr(ci, "_find_slot_session", _find)
    monkeypatch.setattr(ci.urllib.request, "urlopen", _swallow_urlopen())
    ci._recent.clear()

    ok, why = ci.deliver_remote({"from_node": "n3", "from_agent": "claude:T1",
                                 "to_agent": "", "content": "hi"},
                                "http://127.0.0.1:1", cfg)
    assert ok is True, why
    assert seen['slot'] == 1, '브로드캐스트는 대표 슬롯(기본 T1) 한 곳에만 가야 한다'
    ci._recent.clear()


def test_broadcast_slot_zero_restores_old_behaviour(cfg):
    """0으로 두면 옛 동작(미주입)으로 되돌아간다 — 판단을 바꾸고 싶은 사용자용 탈출구."""
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3],
                                           "broadcast_slot": 0}})
    ok, why = ci.deliver_remote({"from_node": "n1", "to_agent": "",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert (ok, why) == (False, "broadcast_not_injected")


def test_broadcast_slot_defaults_to_one(cfg):
    """미설정·오타 모두 T1. [WHY] 오타 하나로 조용히 '아무도 못 들음'이 되면
    증상이 옛 버그와 똑같아져 원인을 다시 못 찾는다."""
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    assert ci.broadcast_slot(cfg) == 1
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3],
                                           "broadcast_slot": "이상한값"}})
    assert ci.broadcast_slot(cfg) == 1


def test_explicit_but_unreadable_slot_is_not_guessed(cfg):
    """슬롯을 적었는데 못 읽으면 대표 슬롯으로 떠넘기지 않는다 —
    남이 지정한 수신자를 추측으로 바꾸면 엉뚱한 슬롯이 남의 말을 받는다."""
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    ok, why = ci.deliver_remote({"from_node": "n1", "to_agent": "discord:bot",
                                 "content": "hi"}, "http://127.0.0.1:1", cfg)
    assert (ok, why) == (False, "no_slot")


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
def test_sender_without_slot_still_gets_injected(cfg, monkeypatch):
    """[🔴 핵심] 발신 슬롯을 몰라도 꽂는다 — 답장 주소는 노드 번호로 충분하다.

    옛 구현은 발신 슬롯이 없으면 '답장 주소를 못 만든다'며 주입을 거부했다. 그런데
    central_say.py `_resolve` 는 슬롯 없는 노드 주소('3')를 **처음부터 받았다** —
    거부할 이유가 없었고, 그 오판으로 `from_agent` 를 안 실은 발신(스크립트·외부
    커넥터·서버 기본값 'claude')이 전부 조용히 버려졌다.
    """
    _write(cfg, {"central_remote_inject": {"enabled": True, "allow_nodes": [3]}})
    monkeypatch.setattr(ci, "seq_of", lambda node_id, config_file=None: 3)
    monkeypatch.setattr(ci, "_find_slot_session", lambda url, slot: "proj")
    sent = {}
    monkeypatch.setattr(ci.urllib.request, "urlopen", _swallow_urlopen(sent))
    ci._recent.clear()

    ok, why = ci.deliver_remote({"from_node": "n3", "from_agent": "claude",
                                 "to_agent": "claude:T2", "content": "hi"},
                                "http://127.0.0.1:1", cfg)
    assert ok is True, why
    body = json.loads(sent['body'])['text']
    assert "central_say.py 3 " in body, '노드 단위 답장 주소가 실려야 왕복이 닫힌다'
    ci._recent.clear()


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
