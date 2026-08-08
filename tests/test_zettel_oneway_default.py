"""
FILE: tests/test_zettel_oneway_default.py
DESCRIPTION: 제텔 동기화가 기본 단방향(PG→Vault)인지 지키는 회귀 테스트.

             [WHY 이걸 테스트하나] 볼트→DB 되읽기 경로에서만 사고가 3건 났다
             (핑퐁 c7a42f2 / 이스케이프 누적 f500109 / 폭주 c93061f).
             실측상 얻는 것은 0이었다 — author='obsidian' 노트 0건, 회상은 전부 PG 경로.
             기본값이 조용히 True로 돌아가면 같은 사고가 재발하므로 여기서 고정한다.

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 단방향 기본값 고정.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'scripts'))

import zettel_sync  # noqa: E402


def test_watch_and_sync_기본값이_단방향이다():
    """호출부가 인자를 빼먹어도 되읽기가 켜지지 않아야 한다."""
    sig = inspect.signature(zettel_sync.watch_and_sync)
    assert sig.parameters['bidirectional'].default is False


def test_단방향이면_import를_호출하지_않는다(monkeypatch):
    """[핵심] bidirectional=False에서 import_from_vault가 한 번도 불리면 안 된다."""
    호출: list[str] = []

    monkeypatch.setattr(zettel_sync, 'import_from_vault',
                        lambda *a, **kw: 호출.append('import'))

    def 가짜_export(*a, **kw):
        호출.append('export')
        raise KeyboardInterrupt  # 무한 루프를 1회에서 끊는다

    monkeypatch.setattr(zettel_sync, 'export_to_vault', 가짜_export)

    with pytest.raises(KeyboardInterrupt):
        zettel_sync.watch_and_sync(Path('.'), project_id='p', interval=0,
                                   bidirectional=False)

    assert 호출 == ['export'], f'단방향인데 되읽기가 돌았다: {호출}'


def test_데몬이_설정없이_단방향으로_붙는다():
    """daemons.py가 bidirectional=True를 하드코딩으로 되돌리지 않았는지 본다.

    [제약] 데몬 본문은 서버 환경(env) 없이는 실행할 수 없어 소스 텍스트로 검증한다.
      느슨하지만, 하드코딩 회귀는 이 방식으로도 확실히 잡힌다.
    """
    src = (BASE / '.ai_monitor' / 'infra' / 'daemons.py').read_text(encoding='utf-8')
    assert 'bidirectional=True' not in src, \
        'daemons.py가 되읽기를 하드코딩으로 켜고 있다 — 설정 토글을 거쳐야 한다'
    assert 'zettel_bidirectional' in src, '되켤 수 있는 설정 키가 남아 있어야 한다'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
