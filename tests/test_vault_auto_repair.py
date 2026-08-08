"""
FILE: tests/test_vault_auto_repair.py
DESCRIPTION: 부팅 시 볼트 자가 복구(auto_repair / fix_vault_files huge_only)의 회귀 테스트.

             [WHY] 새 버전의 크기 가드는 '더 나빠지지 않게' 할 뿐, 구버전에서 이미 부푼
             볼트를 되돌리지 못한다. 다른 PC 사용자가 복구 스크립트를 손으로 돌릴 것을
             기대할 수 없어 부팅 경로에 자동 정리를 넣었다. 이 테스트는 그 정리가
             (1) 잔해를 실제로 걷어내고 (2) 정상 파일을 건드리지 않으며
             (3) 부팅 비용을 물지 않는지(내용을 읽지 않는지)를 지킨다.

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 자동 복구 도입과 함께 회귀 방지.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'scripts'))
sys.path.insert(0, str(BASE / '.ai_monitor'))

import fix_corrupted_titles as fix  # noqa: E402


@pytest.fixture()
def 볼트(tmp_path, monkeypatch):
    """가짜 볼트 하나만 복구 대상이 되게 고정한다 — 실제 볼트를 건드리면 안 된다."""
    v = tmp_path / 'vault'
    v.mkdir()
    monkeypatch.setattr(fix, 'vault_roots', lambda: [v])
    return v


def test_거대_잔해를_지운다(볼트):
    폭주 = 볼트 / 'vibe-1 폭주.md'
    폭주.write_text('---\ntitle: "' + '\\' * (fix.HUGE_NOTE_BYTES + 100) + '"\n---\n',
                    encoding='utf-8')

    fixed, deleted, freed = fix.fix_vault_files(apply=True, huge_only=True)

    assert deleted == 1
    assert not 폭주.exists(), '잔해가 남으면 동기화가 계속 그것을 읽는다'
    assert freed > fix.HUGE_NOTE_BYTES


def test_정상_노트는_건드리지_않는다(볼트):
    정상 = 볼트 / 'vibe-2 정상.md'
    원본 = '---\nzettel_id: "vibe-2"\ntitle: "📄 정상 노트"\n---\n\n# 정상 노트\n\n본문'
    정상.write_text(원본, encoding='utf-8')

    fix.fix_vault_files(apply=True, huge_only=True)

    assert 정상.exists()
    assert 정상.read_text(encoding='utf-8') == 원본


def test_huge_only는_파일_내용을_읽지_않는다(볼트, monkeypatch):
    """[부팅 비용] 전량 read_text는 정상 환경에서도 8.2초가 걸렸다(실측). 1.3초로 줄인 근거."""
    for i in range(5):
        (볼트 / f'vibe-{i} 정상.md').write_text(
            f'---\nzettel_id: "vibe-{i}"\ntitle: "정상"\n---\n본문', encoding='utf-8')

    읽힌: list[str] = []
    원본_read_text = Path.read_text
    monkeypatch.setattr(Path, 'read_text',
                        lambda self, *a, **kw: (읽힌.append(self.name),
                                                원본_read_text(self, *a, **kw))[1])

    fix.fix_vault_files(apply=True, huge_only=True)

    assert 읽힌 == [], f'huge_only인데 파일을 읽었다: {읽힌}'


def test_미리보기는_지우지_않는다(볼트):
    """apply=False가 실제로 파괴하지 않는지 — dry-run이 거짓말하면 신뢰가 무너진다."""
    폭주 = 볼트 / 'vibe-3 폭주.md'
    폭주.write_text('x' * (fix.HUGE_NOTE_BYTES + 50), encoding='utf-8')

    _, deleted, _ = fix.fix_vault_files(apply=False, huge_only=True)

    assert deleted == 1, '미리보기는 건수를 보고해야 한다'
    assert 폭주.exists(), '미리보기가 파일을 지우면 안 된다'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
