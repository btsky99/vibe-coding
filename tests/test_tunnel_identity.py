"""
FILE: tests/test_tunnel_identity.py
DESCRIPTION: 하트비트의 역터널 식별자(_tunnel_identity) 회귀 테스트 — 래퍼가 둘 이상일 때
             알파벳 순 첫 파일을 말없이 채택하던 오보고 경로를 고정한다.

[🔴 이 테스트가 지키는 것 — 진단이 두 번 엉뚱한 PC 를 가리켰다]
  옛 구현은 `sorted(glob('tunnel-*.cmd'))` 의 첫 파일을 채택했다. 다른 PC 설정을 복사해 온
  래퍼가 남아 있으면 알파벳 순으로 그쪽이 이긴다(`cipher` < `na2js`). 그래서 na2js 가
  자기를 'cipher/22001' 이라고 보고했고, 상태판·진단이 두 번 엉뚱한 기계를 가리켰다
  (2026-08-11). 실측으로 확인된 실제 배정은 na2js=22002 였다.

  틀린 식별자는 없는 것보다 나쁘다 — 없으면 '모른다'로 보이지만, 틀리면 '안다'고 믿고
  엉뚱한 곳을 판다. 그래서 모호하면 이름·포트를 비우고 후보만 싣는다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import apix_push  # noqa: E402


def _wrapper(root: Path, name: str, port: int) -> None:
    """Setup-RemoteNode.ps1 이 만드는 래퍼의 최소 형태."""
    root.mkdir(parents=True, exist_ok=True)
    (root / f'tunnel-{name}.cmd').write_text(
        '@echo off\n:loop\n'
        f'ssh -N -T -o ExitOnForwardFailure=yes -i "key" -R {port}:localhost:22 tunnel@vps\n'
        'timeout /t 15 /nobreak >NUL\ngoto loop\n',
        encoding='utf-8')


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """LOCALAPPDATA 와 홈을 모두 tmp 로 돌려 실제 PC 설정을 읽지 않게 한다.
    [제약] _tunnel_identity 는 홈(~/.vibe-remote)도 본다 — 한쪽만 막으면 개발 PC 의
    진짜 래퍼가 섞여 테스트가 기계마다 다른 결과를 낸다."""
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path / 'home'))
    return tmp_path / 'local' / 'vibe-remote'


def test_래퍼가_없으면_빈값(fake_root):
    assert apix_push._tunnel_identity() == {}


def test_래퍼가_하나면_그대로_보고한다(fake_root):
    _wrapper(fake_root, 'na2js', 22002)
    assert apix_push._tunnel_identity() == {'node_name': 'na2js', 'tunnel_port': 22002}


def test_래퍼가_둘이면_이름을_고르지_않는다(fake_root):
    """옛 구현은 여기서 알파벳 순으로 'cipher' 를 채택해 오보고했다."""
    _wrapper(fake_root, 'cipher', 22001)
    _wrapper(fake_root, 'na2js', 22002)

    got = apix_push._tunnel_identity()
    assert 'node_name' not in got, '모호할 때 이름을 단정하면 진단이 오염된다'
    assert 'tunnel_port' not in got
    assert {(c['node_name'], c['tunnel_port']) for c in got['tunnel_conflict']} == {
        ('cipher', 22001), ('na2js', 22002)}


def test_두_루트에_같은_이름은_충돌이_아니다(fake_root, tmp_path):
    """윈도우 LOCALAPPDATA 와 홈 양쪽에 같은 노드의 래퍼가 있는 경우 —
    같은 노드의 중복일 뿐이라 식별을 포기하면 오히려 정보를 잃는다."""
    _wrapper(fake_root, 'na2js', 22002)
    _wrapper(tmp_path / 'home' / '.vibe-remote', 'na2js', 22002)

    assert apix_push._tunnel_identity() == {'node_name': 'na2js', 'tunnel_port': 22002}


def test_R_옵션이_없는_래퍼는_후보가_아니다(fake_root):
    """포트를 못 읽는 래퍼까지 후보로 세면, 무해한 잔재 하나로 멀쩡한 노드가
    영구 '모호' 상태가 된다."""
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / 'tunnel-broken.cmd').write_text('@echo off\nrem 포트 지정 없음\n', encoding='utf-8')
    _wrapper(fake_root, 'na2js', 22002)

    assert apix_push._tunnel_identity() == {'node_name': 'na2js', 'tunnel_port': 22002}
