"""
FILE: tests/test_node_identity.py
DESCRIPTION: 노드 정체성 회귀 테스트 — ID 영속성, 라벨 독립성, node_ref 왕복, 손상 복구.

REVISION HISTORY:
- 2026-08-09 Claude: node_seq 회귀 4건 추가 — 호스트명 자동 배정이 조용히 0을 반환하면
                     대화 화면에서 발신자가 전부 '미지'가 된다 (Phase 11 Task 32).
- 2026-08-08 Claude: 신규 (아픽스 중앙 대화 PG Task 3).
"""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from src import node_identity as ni


@pytest.fixture
def cfg(tmp_path):
    """캐시가 테스트 간에 새지 않도록 매번 리셋 — 모듈 전역 캐시가 있는 모듈이다."""
    ni.reset_cache()
    yield tmp_path / "config.json"
    ni.reset_cache()


def test_id_is_stable_across_calls_and_restarts(cfg):
    first = ni.get_node_id(cfg)
    assert ni.get_node_id(cfg) == first          # 같은 프로세스 내 재호출
    ni.reset_cache()                              # 재시작 흉내 — 파일에서 다시 읽는다
    assert ni.get_node_id(cfg) == first
    assert json.loads(cfg.read_text(encoding='utf-8'))['node_id'] == first


def test_label_change_does_not_touch_id(cfg):
    node_id = ni.get_node_id(cfg)
    ni.set_node_label("거실PC", cfg)
    assert ni.get_node_label(cfg) == "거실PC"
    ni.reset_cache()
    assert ni.get_node_id(cfg) == node_id


def test_existing_config_keys_are_preserved(cfg):
    """[회귀] node_id 발급이 config.json의 다른 설정을 날려먹으면 앱 전체가 초기화된다."""
    cfg.write_text(json.dumps({"last_path": "D:/vibe-coding", "lan_bridge_enabled": True}),
                   encoding='utf-8')
    ni.get_node_id(cfg)
    saved = json.loads(cfg.read_text(encoding='utf-8'))
    assert saved["last_path"] == "D:/vibe-coding"
    assert saved["lan_bridge_enabled"] is True


def test_corrupted_id_is_reissued(cfg):
    cfg.write_text(json.dumps({"node_id": "not-a-uuid"}), encoding='utf-8')
    reissued = ni.get_node_id(cfg)
    assert reissued != "not-a-uuid"
    assert ni._NODE_ID_RE.fullmatch(reissued)


def test_broken_json_does_not_raise(cfg):
    """config.json이 깨져도 정체성 조회가 부팅을 죽이면 안 된다."""
    cfg.write_text("{ 이건 JSON이 아니다", encoding='utf-8')
    assert ni._NODE_ID_RE.fullmatch(ni.get_node_id(cfg))


def test_node_ref_roundtrip(cfg):
    node_id = ni.get_node_id(cfg)
    ref = ni.node_ref("claude:T1", cfg)
    assert ref == f"{node_id}/claude:T1"
    assert ni.parse_node_ref(ref) == (node_id, "claude:T1")
    assert ni.is_local_ref(ref, cfg) is True


def test_parse_tolerates_unwrapped_legacy_value():
    """감싸지 않은 로컬 식별자가 섞여 들어와도 예외 없이 다뤄져야 한다."""
    assert ni.parse_node_ref("claude:T1") == ("", "claude:T1")
    assert ni.parse_node_ref("") == ("", "")
    assert ni.parse_node_ref(None) == ("", "")


def test_foreign_node_ref_is_not_local(cfg):
    ni.get_node_id(cfg)
    other = "0" * 32
    assert ni.is_local_ref(f"{other}/claude:T3", cfg) is False


# ── node_seq (Phase 11 Task 32) ─────────────────────────────────────────────


def test_seq_from_hostname_without_config(cfg, monkeypatch):
    """지정된 3대는 아무 설정 없이도 자기 번호를 알아야 한다 — 사람에게 묻지 않는 게 요구사항."""
    monkeypatch.setattr(ni, "_default_label", lambda: "NA2JS")   # 대소문자 무관
    assert ni.get_node_seq(cfg) == 3
    # 매핑으로 결정되면 config에 굳는다 — 이후 호스트명이 바뀌어도 번호가 안 흔들려야 한다.
    assert json.loads(cfg.read_text(encoding="utf-8"))["node_seq"] == 3


def test_saved_seq_wins_over_hostname(cfg, monkeypatch):
    """config가 정본 — 호스트명을 바꿔도 이미 정해진 번호를 덮지 않는다."""
    ni.set_node_seq(7, cfg)
    monkeypatch.setattr(ni, "_default_label", lambda: "yjscom")   # 매핑상 1
    assert ni.get_node_seq(cfg) == 7


def test_unknown_host_returns_zero(cfg, monkeypatch):
    """네 번째 PC는 0(미지)이어야 한다. 1을 기본값으로 주면 새 PC가 메인 PC를 사칭한다."""
    monkeypatch.setattr(ni, "_default_label", lambda: "some-new-pc")
    assert ni.get_node_seq(cfg) == 0
    assert not cfg.exists() or "node_seq" not in json.loads(cfg.read_text(encoding="utf-8"))


def test_seq_out_of_range_is_rejected(cfg):
    assert ni.set_node_seq(0, cfg) is False
    assert ni.set_node_seq(100, cfg) is False
    assert ni.set_node_seq("abc", cfg) is False
    assert ni.set_node_seq(42, cfg) is True


def test_seq_does_not_touch_node_id(cfg, monkeypatch):
    """[불변식] 번호는 표시용 별명이다 — 외래키인 node_id를 흔들면 중앙 참조가 깨진다."""
    monkeypatch.setattr(ni, "_default_label", lambda: "yjscom")
    node_id = ni.get_node_id(cfg)
    ni.set_node_seq(9, cfg)
    assert ni.get_node_id(cfg) == node_id
