"""
FILE: tests/test_zettel_size_guard.py
DESCRIPTION: 제텔 동기화의 '비정상 크기' 방어선 회귀 테스트.
             제목 길이 상한(export)과 노트 파일 크기 상한(import)이 실제로 폭주를 끊는지 검증한다.

             [🔴 사고 2026-08-08] YAML 이스케이프 왕복 버그로 제목이 115MB, 볼트가 3.2GB까지
             자랐고 동기화 데몬이 server.py CPU의 93%를 태웠다. 왕복 로직은 고쳤지만,
             '폭주를 조기에 끊는 방어선'이 없으면 같은 종류의 결함이 또 느려짐으로 번진다.
             이 테스트는 그 방어선이 살아 있는지를 지킨다.

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 크기 가드 도입과 함께 회귀 방지.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import zettel_sync  # noqa: E402


def test_긴_제목은_상한으로_잘린다():
    """[방어선 1] export가 폭주한 제목을 그대로 파일에 쓰면 다음 import가 되읽어 폭주가 유지된다."""
    폭주 = '\\' * 200_000
    note = {'id': 'vibe-1', 'title': f'정상머리{폭주}', 'note_type': 'permanent'}

    fm = zettel_sync._format_frontmatter(note)

    title_line = next(ln for ln in fm.split('\n') if ln.startswith('title:'))
    # 이스케이프로 길이가 늘어나므로 원문 상한의 2배 + 따옴표/키를 넉넉히 잡아 비교한다.
    assert len(title_line) < zettel_sync.MAX_TITLE_CHARS * 2 + 50
    assert '정상머리' in title_line, '앞부분(의미 있는 원문)은 보존되어야 한다'


def test_정상_제목은_건드리지_않는다():
    """가드가 평상시 데이터를 훼손하지 않는지 — 과잉 방어는 그 자체가 사고다."""
    title = '📄 server.py — 중앙 오케스트레이터'
    note = {'id': 'vibe-2', 'title': title, 'note_type': 'permanent'}

    fm = zettel_sync._format_frontmatter(note)

    assert f'title: "{title}"' in fm


def test_거대_파일은_읽지_않고_건너뛴다(tmp_path, capsys):
    """[방어선 2] 핵심은 '읽기 전에' 걸러내는 것 — read_text 자체가 사고 비용(228MB=9.2초)이다."""
    vault = tmp_path / 'vault'
    vault.mkdir()

    거대 = vault / 'vibe-999 폭주노트.md'
    거대.write_text('---\nzettel_id: "vibe-999"\ntitle: "'
                    + 'x' * (zettel_sync.MAX_NOTE_FILE_BYTES + 1000) + '"\n---\n본문',
                    encoding='utf-8')

    읽힌_파일: list[str] = []
    원본_read_text = Path.read_text

    def 감시(self, *a, **kw):
        읽힌_파일.append(self.name)
        return 원본_read_text(self, *a, **kw)

    # DB 접근은 이 테스트의 관심사가 아니다 — 파일 순회 단계만 본다.
    Path.read_text = 감시
    try:
        zettel_sync.ensure_schema = lambda *a, **kw: None
        zettel_sync.list_notes = lambda *a, **kw: []
        zettel_sync.import_from_vault(vault, project_id='')
    except Exception:
        pass  # DB 계층에서 멎어도 '읽었는가'는 이미 판정 가능하다
    finally:
        Path.read_text = 원본_read_text

    assert 거대.name not in 읽힌_파일, '크기 상한을 넘는 파일을 read_text 하면 방어선이 무의미하다'


def test_고아정리도_거대파일을_읽지_않는다(tmp_path):
    """_cleanup_stale_note_files도 같은 순회를 돌기 때문에 여기만 빠져도 CPU는 그대로 탄다."""
    vault = tmp_path / 'vault'
    vault.mkdir()
    거대 = vault / 'vibe-998 폭주.md'
    거대.write_text('---\nzettel_id: "vibe-998"\n---\n'
                    + 'y' * (zettel_sync.MAX_NOTE_FILE_BYTES + 500), encoding='utf-8')

    읽힌: list[str] = []
    원본 = Path.read_text

    def 감시(self, *a, **kw):
        읽힌.append(self.name)
        return 원본(self, *a, **kw)

    Path.read_text = 감시
    try:
        zettel_sync._cleanup_stale_note_files(vault, [], project_id='')
    finally:
        Path.read_text = 원본

    assert 거대.name not in 읽힌


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
