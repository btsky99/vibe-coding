"""
FILE: tests/test_installed_script_runner.py
DESCRIPTION: 설치본(frozen EXE)에서 데몬 .py를 띄울 실행기 선택 회귀 테스트.
             Python 미설치 PC에서 LAN 브리지가 조용히 안 뜨던 결함(2026-08-14)을 고정한다.

REVISION HISTORY:
- 2026-08-14 Claude: 신규 — "개발에선 되는데 설치본에선 안 됨"의 원인이었던
  python_runner_cmds 폴백('python')을 다시 쓰지 못하게 막는다.
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from infra import daemons, runtime  # noqa: E402


def test_frozen_uses_app_exe_as_runner(tmp_path, monkeypatch):
    """[핵심] frozen이면 앱 EXE 자신이 실행기 — PATH의 python에 의존하면 안 된다.

    설치본 PC에는 Python이 없는 게 정상이다. 옛 코드는 python_runner_cmds()의
    마지막 폴백 'python'을 그대로 Popen에 넘겨 FileNotFoundError로 죽었다.
    """
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Programs\VibeCoding\vibe-coding.exe')
    assert runtime.script_runner_cmd(tmp_path, tmp_path) == \
        r'C:\Programs\VibeCoding\vibe-coding.exe'


def test_dev_uses_real_interpreter(tmp_path, monkeypatch):
    """개발 모드는 기존 동작 유지 — 후보 목록의 첫 인터프리터."""
    monkeypatch.delattr(sys, 'frozen', raising=False)
    monkeypatch.setattr(runtime, 'python_runner_cmds', lambda b, p: [r'X:\venv\python.exe'])
    assert runtime.script_runner_cmd(tmp_path, tmp_path) == r'X:\venv\python.exe'


class _Env:
    """DaemonEnv 대역 — run_lan_bridge가 실제로 만지는 필드만."""

    def __init__(self, base: Path, data: Path, cfg: Path):
        self.base_dir = base
        self.data_dir = data
        self.config_file = cfg
        self.project_root = base
        self.scripts_dir = base / 'scripts'
        self.child_procs = []


def _env(tmp_path: Path, enabled: bool) -> _Env:
    base = tmp_path / 'app'
    base.mkdir()
    (base / 'lan_bridge.py').write_text('# stub', encoding='utf-8')
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"lan_bridge_enabled": %s}' % ('true' if enabled else 'false'),
                   encoding='utf-8')
    return _Env(base, tmp_path, cfg)


def test_lan_bridge_spawns_with_selected_runner(tmp_path, monkeypatch):
    """토글이 켜져 있으면 script_runner_cmd가 고른 실행기로 브리지를 띄운다."""
    calls = []

    def fake_popen(argv, **kw):
        calls.append(argv)
        class _P:
            def poll(self):
                return None
        return _P()

    monkeypatch.setattr(daemons.proc, 'popen', fake_popen)
    monkeypatch.setattr(daemons.runtime, 'script_runner_cmd', lambda b, p: 'RUNNER')
    daemons.run_lan_bridge(_env(tmp_path, True))

    assert len(calls) == 1
    assert calls[0][0] == 'RUNNER'
    assert calls[0][1].endswith('lan_bridge.py')


def test_lan_bridge_off_does_not_spawn(tmp_path, monkeypatch):
    """[불변식] 0.0.0.0 노출이라 명시적 opt-in 없이는 절대 안 뜬다."""
    calls = []
    monkeypatch.setattr(daemons.proc, 'popen', lambda argv, **kw: calls.append(argv))
    daemons.run_lan_bridge(_env(tmp_path, False))
    assert calls == []


def test_spawn_failure_is_logged_not_silent(tmp_path, monkeypatch, capsys):
    """[과거사고] 실행기가 없으면 스레드가 통째로 사라져 흔적이 0이었다 —
    사용자에겐 '토글을 켰는데 아무 일도 안 일어남'으로만 보였다."""
    def boom(argv, **kw):
        raise FileNotFoundError(2, 'The system cannot find the file specified')

    monkeypatch.setattr(daemons.proc, 'popen', boom)
    monkeypatch.setattr(daemons.runtime, 'script_runner_cmd', lambda b, p: 'python')
    daemons.run_lan_bridge(_env(tmp_path, True))          # 예외가 밖으로 새면 실패
    assert 'lan_bridge' in capsys.readouterr().out


def test_shortcut_admin_flag_patch(tmp_path):
    """.lnk 관리자 권한 비트(LinkFlags bit13 = 바이트 0x15의 0x20)를 켜고 멱등."""
    if sys.platform != 'win32':
        pytest.skip('Windows 전용 .lnk 포맷')
    sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))
    from create_shortcut import set_run_as_admin

    lnk = tmp_path / 'x.lnk'
    lnk.write_bytes(bytes(0x100))                          # 헤더 크기 이상의 더미
    assert set_run_as_admin(lnk) is True
    assert lnk.read_bytes()[0x15] & 0x20
    assert set_run_as_admin(lnk) is True                   # 두 번 걸어도 그대로
    assert lnk.read_bytes()[0x15] & 0x20

    short = tmp_path / 'short.lnk'
    short.write_bytes(b'\x00\x00')                         # 헤더보다 짧으면 건드리지 않음
    assert set_run_as_admin(short) is False
