"""
FILE: tests/test_daemon_toggles.py
DESCRIPTION: 데몬 on/off 토글 회귀 테스트 — 기본값 보존(전부 기동)과 선택적 비활성 동작 검증.

REVISION HISTORY:
- 2026-08-04 Claude: popen 데몬이 상태판에서 항상 '꺼짐'으로 보이던 오탐 회귀 테스트 추가.
- 2026-08-14 Claude: Discord 채널 바인딩 테스트 제거 — 커넥터 계층 전면 철거.
- 2026-08-01 Claude: 신규 — 토글이 lan_bridge 하나뿐이라 안 쓰는 데몬도 무조건 뜨던 문제
                     (Codex 미사용 PC에서 codex_pg_watcher가 CPU 4.2시간 소비) 해소분 고정.
- 2026-08-01 Claude: daemon_status(UI 상태 조회) + 레지스트리 스레드명 일치 검증 추가.
                     스레드명이 어긋나면 UI가 살아있는 데몬을 "꺼짐"으로 표시한다.
"""

import json
import re
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
    cfg = _write_cfg(tmp_path, {'daemons': {'codex_watcher': False, 'heartbeat': False}})
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())

    assert 'CodexPGWatcher' not in started
    assert len(started) == len(daemons.DAEMON_TOGGLES) - 2
    # 끄지 않은 것은 그대로 떠야 한다 — 하나 껐다고 다른 게 죽으면 안 됨
    assert 'ZettelSync' in started and 'OrchestratorDaemon' in started


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
    cfg = _write_cfg(tmp_path, {'daemons': {'discordd': False}})   # 오타
    started = _capture(monkeypatch)
    daemons.start_all_daemons(_FakeEnv(cfg), {}, threading.Lock())
    assert len(started) == len(daemons.DAEMON_TOGGLES)
    assert 'discordd' in capsys.readouterr().out


def test_status_reflects_config_and_env(tmp_path, monkeypatch):
    """UI가 읽는 상태 — config OFF와 환경변수 OFF를 구분해서 내려줘야 한다.

    [WHY source 구분] 환경변수로 끈 것은 config를 켜도 안 뜬다. UI가 이를 모르면
    사용자는 토글을 켜고 재시작한 뒤 "왜 안 뜨지"를 무한 반복하게 된다.
    """
    monkeypatch.setenv('VIBE_DISABLE_DAEMONS', 'heartbeat')
    cfg = _write_cfg(tmp_path, {'daemons': {'orchestrator': False}})
    st = {d['key']: d for d in daemons.daemon_status(cfg)}

    assert st['orchestrator']['enabled'] is False and st['orchestrator']['source'] == 'config'
    assert st['heartbeat']['enabled'] is False and st['heartbeat']['source'] == 'env'
    assert st['zettel_sync']['enabled'] is True
    assert st['zettel_sync']['label']            # 라벨 없는 항목은 UI에서 빈 줄로 보인다
    assert len(st) == len(daemons.DAEMON_TOGGLES)


def test_status_running_uses_registry_thread_name(tmp_path, monkeypatch):
    """running 판정이 실제 스레드명과 맞물리는지 — 레지스트리 오타를 잡는 유일한 지점."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)

    started = threading.Event()
    t = threading.Thread(target=started.wait, name=daemons.DAEMON_TOGGLES['zettel_sync']['thread'],
                         daemon=True)
    t.start()
    try:
        st = {d['key']: d for d in daemons.daemon_status(tmp_path / 'nope.json')}
        assert st['zettel_sync']['running'] is True
        assert st['commit_watcher']['running'] is False
    finally:
        started.set()
        t.join(timeout=2)


def test_status_running_detects_popen_child_without_thread(tmp_path, monkeypatch):
    """[과거사고 2026-08-04] popen 데몬은 자식을 띄우고 스레드가 끝난다.

    스레드명만 보면 watchdog/lan_bridge/discord_*/orchestrator가 프로세스는 살아있는데
    상태판에서 전부 '꺼짐'으로 보인다. 실제로 이 오탐 때문에 Discord 게이트웨이가
    안 뜬 줄 알고 엉뚱한 곳을 디버깅했다.
    """
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    monkeypatch.setattr(daemons, '_DAEMON_CHILDREN', {})

    env = _FakeEnv(tmp_path / 'nope.json')
    env.child_procs = []
    child = _FakeChild()
    daemons._track_child('lan_bridge', env, child)

    st = {d['key']: d for d in daemons.daemon_status(env.config_file)}
    assert st['lan_bridge']['running'] is True
    # [불변식] 표시용 레지스트리가 종료 책임을 가져가면 안 된다 — cleanup 대상에도 남아야 함
    assert env.child_procs == [child]

    child.terminate()          # 자식이 죽으면 즉시 '꺼짐'으로 돌아와야 한다
    st = {d['key']: d for d in daemons.daemon_status(env.config_file)}
    assert st['lan_bridge']['running'] is False


def test_status_running_ignores_other_daemons_children(tmp_path, monkeypatch):
    """키가 섞이면 한 데몬의 자식 때문에 다른 데몬이 살아있는 것처럼 보인다."""
    monkeypatch.delenv('VIBE_DISABLE_DAEMONS', raising=False)
    monkeypatch.setattr(daemons, '_DAEMON_CHILDREN', {})

    env = _FakeEnv(tmp_path / 'nope.json')
    env.child_procs = []
    daemons._track_child('watchdog', env, _FakeChild())

    st = {d['key']: d for d in daemons.daemon_status(env.config_file)}
    assert st['watchdog']['running'] is True
    assert st['orchestrator']['running'] is False


def test_track_child_keys_are_registry_keys():
    """오타 키로 등록하면 그 데몬은 영원히 '꺼짐' — 레지스트리에 없는 키를 막는다."""
    source = (_PROJECT_ROOT / '.ai_monitor' / 'infra' / 'daemons.py').read_text(encoding='utf-8')
    used = set(re.findall(r"_track_child\('([a-z_]+)'", source))
    assert used, "_track_child 호출이 하나도 없다 — 리팩터링으로 유실됐는지 확인"
    assert used <= set(daemons.DAEMON_TOGGLES), f"레지스트리에 없는 키: {used - set(daemons.DAEMON_TOGGLES)}"


def test_thread_names_are_unique():
    """스레드명이 겹치면 한 데몬을 끄고도 다른 데몬 때문에 계속 '실행 중'으로 보인다."""
    names = [m['thread'] for m in daemons.DAEMON_TOGGLES.values()]
    assert len(names) == len(set(names))


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


# ── Codex 워처 온디맨드(lazy) ────────────────────────────────────────────────
# [WHY] 부팅 시 무조건 띄워 5초 폴링하던 것을 "Codex 쓸 때만" 기동으로 바꿨다.
#   회귀하면 Codex 미사용 PC에서 CPU 4.2시간이 다시 새어나간다.

class _FakeChild:
    def __init__(self):
        self.terminated = False
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = 0


class _SupEnv:
    def __init__(self, tmp_path: Path):
        self.scripts_dir = tmp_path / 'scripts'
        self.scripts_dir.mkdir(exist_ok=True)
        (self.scripts_dir / 'codex_pg_watcher.py').write_text('# stub', encoding='utf-8')
        self.base_dir = tmp_path
        self.project_root = tmp_path
        self.child_procs = []


class _StopLoop(Exception):
    """감독 루프는 무한 루프라 sleep에서 탈출시켜 N회만 돌린다."""


def _run_supervisor(monkeypatch, env, codex_home: Path, rounds: int):
    spawned = []
    monkeypatch.setattr(daemons.runtime, 'python_runner_cmds', lambda *a, **k: ['python'])
    monkeypatch.setattr(daemons.proc, 'popen',
                        lambda *a, **k: (spawned.append(a), _FakeChild())[1])
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    calls = {'n': 0}

    def fake_sleep(_s):
        calls['n'] += 1
        if calls['n'] >= rounds:
            raise _StopLoop
    monkeypatch.setattr(daemons.time, 'sleep', fake_sleep)
    with pytest.raises(_StopLoop):
        daemons.run_codex_pg_watcher(env)
    return spawned


def test_codex_watcher_not_started_when_idle(tmp_path, monkeypatch):
    """Codex 흔적이 없으면 워처를 아예 안 띄운다 — 이것이 CPU 절감의 핵심."""
    home = tmp_path / '.codex'
    home.mkdir()
    env = _SupEnv(tmp_path)
    spawned = _run_supervisor(monkeypatch, env, home, rounds=1)
    assert spawned == []
    assert env.child_procs == []


def test_codex_watcher_starts_on_recent_activity(tmp_path, monkeypatch):
    """히스토리가 방금 갱신됐으면 자동 기동."""
    home = tmp_path / '.codex'
    home.mkdir()
    (home / 'history.jsonl').write_text('{}', encoding='utf-8')   # mtime=now
    env = _SupEnv(tmp_path)
    spawned = _run_supervisor(monkeypatch, env, home, rounds=1)
    assert len(spawned) == 1
    assert len(env.child_procs) == 1


def test_codex_watcher_stops_when_activity_goes_stale(tmp_path, monkeypatch):
    """활동이 끊기면 내려서 메모리까지 회수하고, child_procs에서도 빠져야 한다.

    [WHY 리스트 제거까지 검증] 남겨두면 종료 시 cleanup_child_procs가 죽은 핸들을 kill한다.
    """
    home = tmp_path / '.codex'
    home.mkdir()
    hist = home / 'history.jsonl'
    hist.write_text('{}', encoding='utf-8')
    env = _SupEnv(tmp_path)

    real_time = daemons.time.time
    state = {'shift': 0}
    monkeypatch.setattr(daemons.time, 'time', lambda: real_time() + state['shift'])

    spawned = []
    child_box = []
    monkeypatch.setattr(daemons.runtime, 'python_runner_cmds', lambda *a, **k: ['python'])

    def fake_popen(*a, **k):
        spawned.append(a)
        c = _FakeChild()
        child_box.append(c)
        return c
    monkeypatch.setattr(daemons.proc, 'popen', fake_popen)
    monkeypatch.setenv('CODEX_HOME', str(home))

    calls = {'n': 0}

    def fake_sleep(_s):
        calls['n'] += 1
        state['shift'] = daemons._CODEX_ACTIVE_WINDOW_SEC + 60   # 2회차엔 유휴로 판정
        if calls['n'] >= 2:
            raise _StopLoop
    monkeypatch.setattr(daemons.time, 'sleep', fake_sleep)

    with pytest.raises(_StopLoop):
        daemons.run_codex_pg_watcher(env)

    assert len(spawned) == 1, "1회차에 기동돼야 함"
    assert child_box[0].terminated is True, "유휴 전환 시 종료돼야 함"
    assert env.child_procs == [], "child_procs에서도 제거돼야 함"


def test_codex_last_activity_missing_home(tmp_path):
    assert daemons._codex_last_activity(tmp_path / 'nope') == 0.0
