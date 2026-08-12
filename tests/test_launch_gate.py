"""
FILE: tests/test_launch_gate.py
DESCRIPTION: 기동 게이트 회귀 테스트 — Phase 12 Task 50.
             '떠 있는 CLI 에 말 걸기(주입)'와 '없던 프로세스를 만들기(기동)'는 권한이
             다르다. 이 테스트는 둘이 섞이지 않는 것과, 화이트리스트가 문자열 눈속임에
             뚫리지 않는 것을 고정한다.

[🔴 왜 이 게이트가 필요한가]
  central_api.py 헤더의 경고 — "중앙 DB 계정 하나가 모든 노드에 대한 원격 코드 실행
  권한이 된다" — 가 현실이 되는 지점이 바로 기동이다. 주입은 이미 게이트가 있지만,
  기동은 작업 폴더까지 정하므로 한 단계 더 잠근다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from src import central_inject as ci  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    return tmp_path / 'config.json'


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


# ── 기본 잠김 ────────────────────────────────────────────────────────────────

def test_기본은_꺼져있다(cfg, tmp_path):
    _write(cfg, {})
    assert ci.launch_gate(cfg) == (False, [])
    assert ci.launch_allowed(str(tmp_path), cfg) == (False, 'launch_disabled')


def test_폴더목록이_비면_꺼진_것과_같다(cfg, tmp_path):
    _write(cfg, {'central_remote_launch': {'enabled': True, 'allow_dirs': []}})
    assert ci.launch_allowed(str(tmp_path), cfg) == (False, 'launch_disabled')


def test_주입허용이_기동허용을_뜻하지_않는다(cfg, tmp_path):
    """[🔴 핵심] 대화를 열어준 것만으로 임의 폴더 실행이 열리면 안 된다."""
    _write(cfg, {'central_remote_inject': {'enabled': True, 'allow_nodes': [3]}})
    assert ci.remote_gate(cfg)[0] is True
    assert ci.launch_allowed(str(tmp_path), cfg)[1] == 'launch_disabled'


# ── 화이트리스트 판정 ────────────────────────────────────────────────────────

def test_허용폴더와_그_하위는_통과한다(cfg, tmp_path):
    root = tmp_path / 'repo'
    sub = root / 'pkg' / 'inner'
    sub.mkdir(parents=True)
    _write(cfg, {'central_remote_launch': {'enabled': True, 'allow_dirs': [str(root)]}})

    assert ci.launch_allowed(str(root), cfg) == (True, '')
    assert ci.launch_allowed(str(sub), cfg) == (True, ''), '하위에서 못 돌면 쓸모가 없다'


def test_허용목록_밖은_승인대기(cfg, tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    _write(cfg, {'central_remote_launch': {'enabled': True,
                                           'allow_dirs': [str(tmp_path / 'a')]}})
    ok, why = ci.launch_allowed(str(tmp_path / 'b'), cfg)
    assert (ok, why) == (False, 'needs_approval'), '버튼으로 풀 수 있는 상태여야 한다'


def test_상위로_거슬러_올라가면_막힌다(cfg, tmp_path):
    """[🔴 핵심] `허용폴더/../다른곳` 이 문자열 비교를 통과하면 게이트가 뚫린다."""
    root = tmp_path / 'repo'
    other = tmp_path / 'secret'
    root.mkdir()
    other.mkdir()
    _write(cfg, {'central_remote_launch': {'enabled': True, 'allow_dirs': [str(root)]}})

    sneaky = str(root / '..' / 'secret')
    assert ci.launch_allowed(sneaky, cfg)[0] is False


def test_빈_경로는_거부(cfg, tmp_path):
    _write(cfg, {'central_remote_launch': {'enabled': True,
                                           'allow_dirs': [str(tmp_path)]}})
    assert ci.launch_allowed('', cfg) == (False, 'bad_work_dir')


# ── 허용 추가 ────────────────────────────────────────────────────────────────

def test_허용은_더하기만_한다(cfg, tmp_path):
    """[🔴 핵심] 교체하면 다른 프로젝트의 허용이 조용히 취소된다."""
    first = tmp_path / 'one'
    second = tmp_path / 'two'
    first.mkdir()
    second.mkdir()
    _write(cfg, {'central_remote_launch': {'enabled': True, 'allow_dirs': [str(first)]}})

    ok, _ = ci.allow_launch_dir(str(second), cfg)
    assert ok
    assert ci.launch_allowed(str(first), cfg)[0] is True, '기존 허용이 사라졌다'
    assert ci.launch_allowed(str(second), cfg)[0] is True


def test_같은_폴더를_두번_넣어도_중복되지_않는다(cfg, tmp_path):
    _write(cfg, {})
    ci.allow_launch_dir(str(tmp_path), cfg)
    ci.allow_launch_dir(str(tmp_path), cfg)
    assert len(ci.launch_gate(cfg)[1]) == 1


def test_없는_폴더는_허용하지_않는다(cfg, tmp_path):
    """오타 경로를 허용해두면 나중에 그 이름의 폴더가 생기는 순간 열린다."""
    _write(cfg, {})
    ok, why = ci.allow_launch_dir(str(tmp_path / '없는폴더'), cfg)
    assert (ok, why) == (False, 'not_a_directory')


def test_다른_설정을_보존한다(cfg, tmp_path):
    _write(cfg, {'node_id': 'a' * 32, 'central_db': {'host': 'x'}})
    ci.allow_launch_dir(str(tmp_path), cfg)
    saved = json.loads(cfg.read_text(encoding='utf-8-sig'))
    assert saved['central_db'] == {'host': 'x'} and saved['node_id'] == 'a' * 32
