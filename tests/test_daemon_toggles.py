"""
FILE: tests/test_daemon_toggles.py
DESCRIPTION: 데몬 on/off 토글 회귀 테스트 — 기본값 보존(전부 기동)과 선택적 비활성 동작 검증.

REVISION HISTORY:
- 2026-08-01 Claude: 신규 — 토글이 lan_bridge 하나뿐이라 안 쓰는 데몬도 무조건 뜨던 문제
                     (Codex 미사용 PC에서 codex_pg_watcher가 CPU 4.2시간 소비) 해소분 고정.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from infra import daemons


class _FakeEnv:
    """DaemonEnv 대역 — 토글 판정에 필요한 config_file만 있으면 된다."""

    def __init__(self, config_file: Path):
        self.config_file = config_file


def _capture(monkeypatch) -> list:
    """실제 데몬 대신 기동된 키를 수집. 스레드를 만들지 않아 테스트가 부작용 없이 끝난다."""
    started: list = []

    def fake_thread(target=None, args=(), name=None, daemon=None):
        class _T:
            def start(_self):
                started.append(name or getattr(target, '__name__', '?'))
        return _T()

    monkeypatch.setattr(threading, 'Thread', fake_thread)
    return started


def _write_cfg(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / 'config.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    return p


def test_default_starts_every_daemon(tmp_path, monkeypatch):
    """[불변식] 토글 도입이 기존 동작을 바꾸면 안 된다 — 설정이 없으면 전부 기동."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(tmp_path / 'nope.json'), {}, threading.Lock())
    assert len(started) == len(daemons.DAEMON_TOGGLES)


def test_config_disables_only_listed(tmp_path, monkeypatch):
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    cfg = _write_cfg(tmp_path, {'daemons': {'codex_watcher': False, 'telegram': False}})
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())

    assert 'CodexPGWatcher' not in started
    assert len(started) == len(daemons.DAEMON_TOGGLES) - 2
    # 끄지 않은 것은 그대로 떠야 한다 — 하나 껐다고 다른 게 죽으면 안 됨
    assert 'ZettelSync' in started and 'Heartbeat' in started


def test_true_value_keeps_daemon_on(tmp_path, monkeypatch):
    """명시적 true는 기동 — is False 판정이라 'true'/누락 모두 ON."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    cfg = _write_cfg(tmp_path, {'daemons': {'codex_watcher': True}})
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())
    assert 'CodexPGWatcher' in started


def test_env_var_disables(tmp_path, monkeypatch):
    """1회성/테스트용 환경변수 경로."""
    monkeypatch.setenv('VIBE_DISABLE_DAEMONS', 'heartbeat, zettel_sync')
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(tmp_path / 'nope.json'), {}, threading.Lock())
    assert 'Heartbeat' not in started
    assert 'ZettelSync' not in started
    assert len(started) == len(daemons.DAEMON_TOGGLES) - 2


def test_broken_config_starts_everything(tmp_path, monkeypatch):
    """[안전 실패 방향] 설정이 깨졌을 때 데몬이 조용히 죽으면 원인 추적이 불가능하다."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    bad = tmp_path / 'config.json'
    bad.write_text('{ 이건 JSON이 아님', encoding='utf-8')
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(bad), {}, threading.Lock())
    assert len(started) == len(daemons.DAEMON_TOGGLES)


def test_unknown_key_is_ignored_not_fatal(tmp_path, monkeypatch, capsys):
    """오타 키가 다른 데몬을 죽이거나 예외를 내면 안 된다 — 무시하고 경고만."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    cfg = _write_cfg(tmp_path, {'daemons': {'telegramm': False}})   # 오타
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())
    assert len(started) == len(daemons.DAEMON_TOGGLES)
    assert 'telegramm' in capsys.readouterr().out


def test_registry_keys_match_start_calls(tmp_path, monkeypatch):
    """레지스트리에만 있고 실제로는 안 쓰이는 키(또는 그 반대)를 막는다.

    [WHY] 키가 어긋나면 UI에서 끈 항목이 실제로는 안 꺼지는데, 사용자는 껐다고 믿는다.
    """
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    for key in daemons.DAEMON_TOGGLES:
        cfg = _write_cfg(tmp_path, {'daemons': {key: False}})
        started = _capture(monkeypatch)
        daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())
        assert len(started) == len(daemons.DAEMON_TOGGLES) - 1, f"키 '{key}'가 아무 데몬도 끄지 못함"
