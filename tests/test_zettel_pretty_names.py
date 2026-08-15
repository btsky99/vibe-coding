"""
FILE: tests/test_zettel_pretty_names.py
DESCRIPTION: 볼트 파일명 규칙 회귀 테스트 — note_id 접두 제거 이후의 이름 짓기가
             '읽히는 이름'과 '겹치지 않는 이름'을 동시에 지키는지 검증한다.

             [WHY] 파일명은 옵시디언에서 정렬·검색·[[링크]]의 키다. 규칙이 조용히 어긋나면
             볼트 전체가 개명되며 GDrive 재업로드까지 번진다 — 실패가 비싸므로 못으로 박는다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 파일명에서 note_id 접두 제거와 함께 회귀 방지.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import zettel_sync  # noqa: E402


def _name(note_id: str, title: str) -> str:
    """레지스트리 없이(=충돌 정보 없이) 개별 계산. 링크 렌더링이 타는 경로와 같다."""
    zettel_sync._NAME_REGISTRY = {}
    return zettel_sync._safe_filename(note_id, title)


def test_파일명에_note_id_접두가_남지_않는다():
    """[핵심] 해시 접두가 남으면 이름순 정렬이 사실상 무작위가 된다 — 목록에서 고를 수 없다."""
    이름 = _name('w-ff6eb8de6f7b', '📖 API 계층 · server.py · do_GET')

    assert not 이름.startswith('w-')
    assert 'ff6eb8de6f7b' not in 이름
    assert 이름 == '📖 API 계층 · server.py · do_GET'


def test_의미없는_분류_조각은_지운다():
    """생성기가 분류를 못 정했을 때 채우는 '그 밖'은 정보가 0이라 이름만 길게 만든다."""
    assert _name('w-1', '📖 테스트 · 그 밖 · test_a.py · 모듈 상단') == '📖 테스트 · test_a.py · 모듈 상단'


def test_꼬리에_반복되는_이름을_지운다():
    """`X.ts — 분류 — X` 꼴의 마지막 조각은 앞에 이미 있는 말이다(이모지가 붙어도 같다)."""
    assert _name('vibe-1', '📄 useVoice.ts — React 컴포넌트/모듈 — useVoice') \
        == '📄 useVoice.ts · React 컴포넌트 · 모듈'


def test_숫자_사이_콜론은_구분자가_아니다():
    """[과거사고 2026-08-15] 콜론을 전부 구분자로 바꿨더니 `20:14`가 `20 · 14`로 쪼개져 시각이 증발했다."""
    assert _name('vibe-2', '세션 요약: 2026-06-11 20:14') == '세션 요약 · 2026-06-11 20-14'


def test_절단은_낱말_경계에서_일어난다():
    """[과거사고] 고정 길이 절단이 `_header_descriptio`처럼 식별자를 반토막 내 검색이 안 걸렸다."""
    긴제목 = '📖 아주 긴 주제 ' + ' '.join(f'낱말{i}' for i in range(40))

    이름 = _name('vibe-3', 긴제목)

    assert len(이름) <= zettel_sync.MAX_FILENAME_CHARS + 1  # '…' 한 글자
    assert 이름.endswith('…')
    assert not 이름.rstrip('…').endswith('낱'), '낱말 중간에서 잘리면 안 된다'


def test_경로_트래버설은_이름에_살아남지_않는다():
    """[보안] 파일명은 vault 밖을 가리킬 수 없어야 한다 — 상위 경로 기호가 통째로 사라져야 한다."""
    이름 = _name('vibe-4', '제목에 ../../etc/passwd 시도')

    assert '..' not in 이름
    assert '/' not in 이름 and '\\' not in 이름


def test_제목이_비면_id로_되돌아간다():
    """빈 제목까지 예쁘게 만들 수는 없다 — 겹치지 않는 이름이 우선이다."""
    assert _name('vibe-5', '') == 'vibe-5'
    assert _name('vibe-6', '그 밖') == 'vibe-6'


def test_같은_제목은_전원_꼬리표를_받는다():
    """[불변식] 한 명만 깨끗한 이름을 가지면 나중에 승자가 바뀌며 두 파일이 동시에 개명된다."""
    notes = [
        {'id': 'w-aaaa1111', 'title': '📖 같은 제목'},
        {'id': 'w-bbbb2222', 'title': '📖 같은 제목'},
        {'id': 'w-cccc3333', 'title': '📖 다른 제목'},
    ]

    reg = zettel_sync.build_name_registry(notes)

    assert reg['w-cccc3333'] == '📖 다른 제목', '겹치지 않으면 꼬리표가 없어야 한다'
    assert reg['w-aaaa1111'] != reg['w-bbbb2222']
    assert reg['w-aaaa1111'].startswith('📖 같은 제목 (')
    assert reg['w-bbbb2222'].startswith('📖 같은 제목 (')


def test_같은_입력이면_항상_같은_이름():
    """[불변식] 이름이 실행마다 흔들리면 매 사이클 볼트 전체가 삭제·재생성된다(GDrive 재업로드)."""
    notes = [{'id': f'w-{i:04x}', 'title': '📖 겹치는 제목'} for i in range(5)]

    첫번째 = zettel_sync.build_name_registry(notes)
    두번째 = zettel_sync.build_name_registry(list(reversed(notes)))

    assert 첫번째 == 두번째, '입력 순서가 달라도 결과는 같아야 한다'
    assert len(set(첫번째.values())) == len(notes), '이름이 겹치면 한쪽 노트가 조용히 사라진다'
