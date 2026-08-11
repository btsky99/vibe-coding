"""
FILE: tests/test_config_self_heal.py
DESCRIPTION: config.json 자가복구 회귀 테스트 — 읽기 실패가 '설정 없음'으로 둔갑해
             파일을 덮어쓰던 파괴 경로와, 게이트를 API로 여는 경로를 고정한다.

[🔴 이 테스트가 지키는 것 — 실제로 노드 하나를 잃었다]
  2026-08-11 na2js: 사용자가 PowerShell 한 줄로 config.json 을 고쳤는데 PS 5.1 이 BOM 을
  붙였다. 앱은 utf-8 로 읽다 파싱에 실패했고, 그 실패를 '{} = 설정 없음'으로 삼킨 뒤
  새 uuid 를 담아 **파일을 통째로 덮어썼다**. central_db·node_seq 가 그 순간 소멸했고
  노드는 중앙에서 미아가 됐다. 복구 불가는 '못 읽음'이 아니라 '덮어씀'에서 왔다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from src import node_identity  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    node_identity.reset_cache()
    yield
    node_identity.reset_cache()


def _write(path: Path, data: dict, bom: bool = False) -> None:
    text = json.dumps(data, ensure_ascii=False)
    path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8'))


# ── BOM ─────────────────────────────────────────────────────────────────────

def test_bom이_붙어도_설정을_읽는다(tmp_path):
    """PS 5.1 `Set-Content -Encoding utf8`, 메모장 등이 붙이는 BOM."""
    cfg = tmp_path / 'config.json'
    _write(cfg, {'node_id': 'a' * 32, 'central_db': {'host': '127.0.0.1'}}, bom=True)

    data, status = node_identity._load_config(cfg)
    assert status == 'ok'
    assert data['central_db']['host'] == '127.0.0.1'


def test_bom_설정으로_기동해도_node_id가_유지된다(tmp_path):
    """옛 코드는 여기서 새 uuid 를 발급하고 파일을 덮어썼다."""
    cfg = tmp_path / 'config.json'
    _write(cfg, {'node_id': 'b' * 32, 'central_db': {'host': 'x'}}, bom=True)

    assert node_identity.get_node_id(cfg) == 'b' * 32
    assert json.loads(cfg.read_text(encoding='utf-8-sig'))['central_db'] == {'host': 'x'}


# ── 손상 ────────────────────────────────────────────────────────────────────

def test_깨진_설정을_덮어쓰지_않는다(tmp_path):
    """백업이 없으면 원본을 보존만 하고 파일에 쓰지 않는다."""
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"central_db": {"host": "x"', encoding='utf-8')   # 잘린 JSON

    nid = node_identity.get_node_id(cfg)

    assert len(nid) == 32
    assert not cfg.exists(), '깨진 파일 자리에 새 설정을 쓰면 안 된다'
    kept = list(tmp_path.glob('config.json.corrupt-*'))
    assert len(kept) == 1, '원본 바이트는 반드시 보존한다'


def test_깨지면_마지막_정상본에서_되살린다(tmp_path):
    cfg = tmp_path / 'config.json'
    node_identity._write_config(cfg, {'node_id': 'c' * 32, 'central_db': {'host': 'keep'}})
    assert (tmp_path / 'config.json.bak').exists(), '정상 저장은 백업을 남긴다'

    cfg.write_text('!!! 깨짐 !!!', encoding='utf-8')

    data, status = node_identity._load_config(cfg)
    assert status == 'restored'
    assert data['central_db']['host'] == 'keep'
    assert json.loads(cfg.read_text(encoding='utf-8'))['central_db']['host'] == 'keep'


def test_복구가_백업을_덮어쓰지_않는다(tmp_path):
    """복구 직후 .bak 을 갱신하면 다음 사고 때 되돌릴 곳이 사라진다."""
    cfg = tmp_path / 'config.json'
    node_identity._write_config(cfg, {'node_id': 'd' * 32, 'v': 1})
    before = (tmp_path / 'config.json.bak').read_text(encoding='utf-8')

    cfg.write_text('깨짐', encoding='utf-8')
    node_identity._load_config(cfg)

    assert (tmp_path / 'config.json.bak').read_text(encoding='utf-8') == before


def test_빈_파일은_없는_것과_같다(tmp_path):
    cfg = tmp_path / 'config.json'
    cfg.write_text('   ', encoding='utf-8')

    data, status = node_identity._load_config(cfg)
    assert (data, status) == ({}, 'missing')

    nid = node_identity.get_node_id(cfg)
    assert json.loads(cfg.read_text(encoding='utf-8'))['node_id'] == nid


# ── 게이트 (스크립트 없이 열기) ─────────────────────────────────────────────

def test_허용은_더하기만_한다(tmp_path):
    """목록을 교체하면 다른 노드의 허용이 조용히 취소된다."""
    from src import central_inject

    cfg = tmp_path / 'config.json'
    node_identity._write_config(
        cfg, {'node_id': 'e' * 32,
              'central_remote_inject': {'enabled': True, 'allow_nodes': [1]}})

    ok, why = central_inject.allow_node(3, config_file=cfg)
    assert (ok, why) == (True, '')

    saved = json.loads(cfg.read_text(encoding='utf-8'))['central_remote_inject']
    assert saved == {'enabled': True, 'allow_nodes': [1, 3]}


def test_허용이_다른_키를_보존한다(tmp_path):
    from src import central_inject

    cfg = tmp_path / 'config.json'
    node_identity._write_config(cfg, {'node_id': 'f' * 32, 'central_db': {'host': 'keep'},
                                      'node_seq': 3})

    assert central_inject.allow_node(1, config_file=cfg)[0]

    saved = json.loads(cfg.read_text(encoding='utf-8'))
    assert saved['central_db'] == {'host': 'keep'}
    assert saved['node_seq'] == 3


@pytest.mark.parametrize('seq', [0, -1, None, 'abc'])
def test_모르는_노드는_허용하지_않는다(tmp_path, seq):
    """seq=0 은 '명부에 없음'이다. 허용하면 알 수 없는 발신자 전부를 허용하는 셈."""
    from src import central_inject

    cfg = tmp_path / 'config.json'
    node_identity._write_config(cfg, {'node_id': 'a' * 32})

    ok, why = central_inject.allow_node(seq, config_file=cfg)
    assert not ok and why in ('unknown_node', 'invalid_seq')
    assert 'central_remote_inject' not in json.loads(cfg.read_text(encoding='utf-8'))


def test_읽지_못한_설정에는_쓰지_않는다(tmp_path):
    """깨진 파일에 게이트만 써 넣으면 나머지 키가 전부 사라진다."""
    from src import central_inject

    cfg = tmp_path / 'config.json'
    cfg.write_text('{깨짐', encoding='utf-8')

    ok, why = central_inject.allow_node(3, config_file=cfg)
    assert (ok, why) == (False, 'config_unreadable')
