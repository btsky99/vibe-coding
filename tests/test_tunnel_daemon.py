"""
FILE: tests/test_tunnel_daemon.py
DESCRIPTION: 중앙 PG SSH 터널 데몬 회귀 테스트 — 게이트/ssh 옵션/우리터널 판정/고아 회수.
             실제 ssh를 띄우지 않고 프로세스 조회부만 대체해 판정 로직만 검증한다.

             [🔴 2026-08-09 이 파일이 통째로 죽어 있었다] 94bc9bf가 tunnel_daemon을
             재설계(live_tunnel_port/_SpawnLock/use_tunnel 폐기)하면서 테스트를 따라
             고치지 않아 15건이 AttributeError로 실패 중이었다. 빨간 스위트는 신호가
             아니라 잡음이 되어, 진짜 회귀가 들어와도 아무도 알아채지 못한다
             (feedback_observability_first). 현행 API 기준으로 재작성했다.

             [갱신 규칙] tunnel_daemon의 함수 이름을 바꿀 때 이 파일을 같이 고친다.
             고칠 수 없으면 그 변경은 아직 끝난 게 아니다.

REVISION HISTORY:
- 2026-08-09 Claude: 현행 API로 전면 재작성. 폐기된 설계(use_tunnel/기동 락) 테스트 제거,
                     대신 재설계가 실제로 막아낸 사고(남의 PG 오인)를 회귀로 고정.
- 2026-08-08 Claude: 신규 (아픽스 중앙 대화 PG Task 6, 7).
"""
import json
import socket
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from infra import tunnel_daemon as td  # noqa: E402

# central_db 필수 키가 하나라도 비면 get_central_config가 None을 준다 — 터널도 함께 잠든다.
_CENTRAL = {"host": "127.0.0.1", "port": 5440, "user": "hive",
            "password": "pw", "dbname": "hive_knowledge"}
_TUNNEL = {"ssh_host": "1.2.3.4", "ssh_user": "hive", "remote_port": 5432}


def _write_cfg(tmp_path: Path, central: dict | None) -> Path:
    path = tmp_path / "config.json"
    payload = {"last_path": "D:/x"}
    if central is not None:
        payload["central_db"] = central
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


def _state(tmp_path: Path, **over) -> None:
    td._write_state(tmp_path, {'pid': 4242, 'local_port': 5440, 'remote_port': 5432,
                               'ssh_host': '1.2.3.4', **over})


# ── 게이트 ──────────────────────────────────────────────────────────────────
def test_설정이_없으면_잠든다(tmp_path):
    assert td.get_tunnel_config(tmp_path / "없는파일.json") is None
    assert td.get_tunnel_config(_write_cfg(tmp_path, None)) is None


def test_tunnel_블록이_없으면_잠든다(tmp_path):
    """[WHY] 중앙 PG가 이미 도달 가능한 환경(같은 LAN/VPN/수동 터널)에서는 데몬이 불필요하다."""
    assert td.get_tunnel_config(_write_cfg(tmp_path, dict(_CENTRAL))) is None


def test_ssh_host가_비면_잠든다(tmp_path):
    cfg = _write_cfg(tmp_path, {**_CENTRAL, "tunnel": {"ssh_user": "hive"}})
    assert td.get_tunnel_config(cfg) is None


def test_중앙_자격증명이_불완전하면_터널도_잠든다(tmp_path):
    """[불변식] 터널만 뜨고 붙을 DB가 없으면 밖으로 나가는 연결만 남는다."""
    cfg = _write_cfg(tmp_path, {"host": "h", "port": 5440, "tunnel": dict(_TUNNEL)})
    assert td.get_tunnel_config(cfg) is None


def test_기본값이_채워진다(tmp_path):
    cfg = _write_cfg(tmp_path, {**_CENTRAL, "tunnel": {"ssh_host": "1.2.3.4"}})
    got = td.get_tunnel_config(cfg)
    assert got['ssh_user'] == 'root'
    assert got['remote_port'] == 5432


def test_로컬_포트는_central_db_port를_그대로_쓴다(tmp_path):
    """[불변식] 여기서 다른 포트를 고르면 pg_central이 터널을 못 찾는다 — 별도 조회 경로가 없다."""
    cfg = _write_cfg(tmp_path, {**_CENTRAL, "port": 5555, "tunnel": dict(_TUNNEL)})
    assert td.get_tunnel_config(cfg)['local_port'] == 5555


# ── ssh 커맨드 ──────────────────────────────────────────────────────────────
def test_ssh_명령에_안전_옵션이_있다():
    """[회귀] 빠지면 데몬이 조용히 망가진다 — ExitOnForwardFailure 없으면 포워딩이 죽은
    유령 터널, BatchMode 없으면 암호 프롬프트에서 영구 정지(윈도우 모드엔 입력할 콘솔도 없다)."""
    cmd = td._build_ssh_cmd({'ssh_host': 'h', 'ssh_user': 'u', 'key': '',
                             'local_port': 5440, 'remote_port': 5432})
    assert 'BatchMode=yes' in cmd
    assert 'ExitOnForwardFailure=yes' in cmd
    assert 'ServerAliveInterval=30' in cmd, '절전으로 죽은 소켓을 감지할 수단이 사라졌다'
    assert td._forward_spec(5440, 5432) in cmd
    assert cmd[-1] == 'u@h'


def test_키가_있을_때만_i_옵션을_붙인다():
    cmd = td._build_ssh_cmd({'ssh_host': 'h', 'ssh_user': 'u', 'key': 'C:/k/id_ed25519',
                             'local_port': 5440, 'remote_port': 5432})
    assert '-i' in cmd and 'C:/k/id_ed25519' in cmd


# ── 우리 터널 판정 (PID 재사용 방어) ────────────────────────────────────────
def test_명령줄이_일치해야_우리_터널이다(monkeypatch):
    """[🔴 PID 재사용 방어] PID만 믿고 kill하면 그 번호를 물려받은 무관한 프로세스를 죽인다."""
    monkeypatch.setattr(td, '_process_cmdline',
                        lambda pid: 'ssh -N -L 5440:127.0.0.1:5432 hive@1.2.3.4')
    assert td._is_our_tunnel(4242, 5440, 5432, '1.2.3.4') is True
    assert td._is_our_tunnel(4242, 9999, 5432, '1.2.3.4') is False, '포트가 달라도 우리 것이라 했다'
    assert td._is_our_tunnel(4242, 5440, 5432, '9.9.9.9') is False, '다른 서버인데 우리 것이라 했다'


def test_명령줄을_못_읽으면_우리것이_아니다(monkeypatch):
    """[🔴 보수적 판정] 남의 프로세스를 죽이는 것이 고아를 남기는 것보다 훨씬 나쁘다."""
    monkeypatch.setattr(td, '_process_cmdline', lambda pid: '')
    assert td._is_our_tunnel(4242, 5440, 5432, '1.2.3.4') is False


def test_pid가_0이면_판정하지_않는다():
    assert td._is_our_tunnel(0, 5440, 5432, '1.2.3.4') is False


# ── 고아 회수 ───────────────────────────────────────────────────────────────
@pytest.fixture
def kills(monkeypatch):
    killed = []
    monkeypatch.setattr(td, '_kill', lambda pid: killed.append(pid) or True)
    return killed


def test_상태파일이_없으면_아무것도_하지_않는다(tmp_path, kills):
    assert td.cleanup_orphan_tunnel(tmp_path) == 0
    assert kills == []


def test_우리것이면_회수한다(tmp_path, monkeypatch, kills):
    _state(tmp_path)
    monkeypatch.setattr(td, '_process_cmdline',
                        lambda pid: 'ssh -N -L 5440:127.0.0.1:5432 hive@1.2.3.4')
    assert td.cleanup_orphan_tunnel(tmp_path) == 1
    assert kills == [4242]
    assert td._read_state(tmp_path) == {}, '회수 후 좌표를 지우지 않았다'


def test_남의_프로세스는_죽이지_않고_기록만_버린다(tmp_path, monkeypatch, kills):
    """[🔴 자기 것만 죽인다] 다른 인스턴스/사용자의 ssh를 죽이면 그쪽 작업이 통째로 끊긴다."""
    _state(tmp_path)
    monkeypatch.setattr(td, '_process_cmdline', lambda pid: 'notepad.exe 메모.txt')
    assert td.cleanup_orphan_tunnel(tmp_path) == 0
    assert kills == []
    assert td._read_state(tmp_path) == {}, '남의 것이면 좌표는 버려 새로 띄우게 해야 한다'


def test_확인_불가면_죽이지_않는다(tmp_path, monkeypatch, kills):
    """cmdline 조회가 실패하는 환경(wmic 부재 등)에서도 남의 것을 죽이면 안 된다."""
    _state(tmp_path)
    monkeypatch.setattr(td, '_process_cmdline', lambda pid: '')
    assert td.cleanup_orphan_tunnel(tmp_path) == 0
    assert kills == []


# ── 재사용 판정 (2026-08-09 실측 사고 회귀) ─────────────────────────────────
def test_PG처럼_답해도_우리_기록이_없으면_살아있다고_보지_않는다(tmp_path, monkeypatch):
    """[🔴 2026-08-09 실제 사고] 초판은 포트가 PG처럼 답하면 '이미 터널이 있다'고 판단했다.
    그 포트에 있던 것은 다른 프로젝트의 로컬 PostgreSQL이었고, 결과는 남의 PG에 hive 계정으로
    붙어 인증 실패 → 사용자에게는 '중앙 기능이 그냥 안 켜짐'으로만 보였다. 추적 거의 불가능.
    """
    monkeypatch.setattr(td, '_port_speaks_postgres', lambda *a, **k: True)
    cfg = {'local_port': 5440, 'remote_port': 5432, 'ssh_host': '1.2.3.4'}
    assert td._our_tunnel_is_alive(tmp_path, cfg) is False


def test_포트가_다르면_우리_터널이_아니다(tmp_path, monkeypatch):
    _state(tmp_path, local_port=9999)
    monkeypatch.setattr(td, '_process_cmdline',
                        lambda pid: 'ssh -N -L 9999:127.0.0.1:5432 hive@1.2.3.4')
    monkeypatch.setattr(td, '_port_speaks_postgres', lambda *a, **k: True)
    cfg = {'local_port': 5440, 'remote_port': 5432, 'ssh_host': '1.2.3.4'}
    assert td._our_tunnel_is_alive(tmp_path, cfg) is False


def test_남의_포트가_열려있으면_ssh를_띄우지_않는다(tmp_path, monkeypatch):
    """[불변식] 포트 주인이 누구든 죽이지 않는다 — 경고만 남기고 물러난다."""
    monkeypatch.setattr(td, '_our_tunnel_is_alive', lambda *a, **k: False)
    monkeypatch.setattr(td, '_port_is_open', lambda *a, **k: True)
    monkeypatch.setattr(td, '_port_speaks_postgres', lambda *a, **k: True)

    def _boom(*a, **k):
        raise AssertionError('남의 포트가 열려 있는데 ssh를 띄웠다')
    monkeypatch.setattr(td.proc, 'popen', _boom)

    cfg = {'local_port': 5440, 'remote_port': 5432, 'ssh_host': '1.2.3.4',
           'ssh_user': 'hive', 'key': ''}
    assert td.ensure_tunnel(tmp_path, cfg) is None


# ── 포트 탐침 ───────────────────────────────────────────────────────────────
def test_열린_포트와_닫힌_포트를_구분한다():
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert td._port_is_open(port) is True
        # 그냥 TCP 리스너일 뿐 PG가 아니다 — 이 구분이 위 사고 방어의 핵심이다.
        assert td._port_speaks_postgres(port) is False
    finally:
        srv.close()
    assert td._port_is_open(port) is False


# ── 데몬 게이트 ─────────────────────────────────────────────────────────────
def test_미설정이면_데몬이_즉시_반환한다(tmp_path):
    """[불변식] 중앙을 쓰지 않는 사용자에게 스레드조차 남기지 않는다."""
    class _Env:
        data_dir = tmp_path
        config_file = tmp_path / '없는파일.json'

    td.run_tunnel_daemon(_Env())        # 예외 없이 즉시 반환


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
