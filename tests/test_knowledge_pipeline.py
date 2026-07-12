# -*- coding: utf-8 -*-
"""
FILE: tests/test_knowledge_pipeline.py
DESCRIPTION: 지식 노트 파이프라인 재설계 회귀 테스트 — 세션요약 노이즈 차단 + 파일지식 1급화 +
             GDrive 크로스공유 필터의 순수 함수 계약을 상시 게이트한다. (2026-07-12 재설계)

             [테스트 전략] DB 연결 없이 순수 함수만 검증 —
             - _auto_promote_where_clause: 세션요약 배제절 포함(문자열 계약).
             - _read_file_description: 헤더 DESCRIPTION 파싱 + 무헤더 폴백(격리 fs).
             - _extract_commit_why: 3섹션 본문 추출 + 제목만이면 빈 문자열.
             - _is_gdrive_worthy: 커밋덤프 제외, 카드/지도/지식/구조 유지(격리 fs).

REVISION HISTORY:
- 2026-07-12 Claude: 최초 작성 — 지식 파이프라인 재설계(4대 태스크) 계약 고정.
"""

import sys
from pathlib import Path

import pytest  # noqa: F401

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
_SCRIPTS = _PROJECT_ROOT / "scripts"
sys.path.insert(0, str(_AI_MONITOR))
sys.path.insert(0, str(_AI_MONITOR / "src"))
sys.path.insert(0, str(_SCRIPTS))


# ═══════════════════════════════════════════════════════════════════════════
# T1 — 세션요약 승격 차단 (WHERE 절 계약)
# ═══════════════════════════════════════════════════════════════════════════

def test_auto_promote_excludes_session_summaries():
    """[T1] fleeting→permanent 승격 WHERE 절이 세션요약/머지를 명시 배제해야 한다."""
    import pg_memory
    clause = pg_memory._auto_promote_where_clause()
    assert "source_ref IS DISTINCT FROM 'session-summary'" in clause
    assert "세션 요약%" in clause
    assert "Merge %" in clause


# ═══════════════════════════════════════════════════════════════════════════
# T3 — 파일 헤더 DESCRIPTION 파싱
# ═══════════════════════════════════════════════════════════════════════════

def test_read_file_description_from_header(tmp_path):
    """[T3] 표준 헤더 DESCRIPTION을 실제로 읽어 첫 문장을 반환한다."""
    import zettel_capture as z
    f = tmp_path / "sample.py"
    f.write_text('"""\nFILE: sample.py\nDESCRIPTION: 샘플 모듈 역할 설명. 두번째 문장.\n\nREVISION HISTORY:\n"""\n',
                 encoding='utf-8')
    desc = z._read_file_description(str(f))
    assert desc.startswith('샘플 모듈 역할 설명')
    assert '두번째 문장' not in desc  # 첫 문장만


def test_read_file_description_fallback(tmp_path):
    """[T3] 헤더 없는 파일 → _guess_file_role 폴백(예외 없이 문자열 반환)."""
    import zettel_capture as z
    f = tmp_path / "plain.py"
    f.write_text("x = 1\n", encoding='utf-8')
    desc = z._read_file_description(str(f))
    assert isinstance(desc, str) and desc  # 폴백 문자열
    # 없는 파일도 폴백
    assert z._read_file_description(str(tmp_path / "nope.py"))


# ═══════════════════════════════════════════════════════════════════════════
# T4 — 커밋 본문에서 '무엇을/왜' 추출
# ═══════════════════════════════════════════════════════════════════════════

def test_extract_commit_why_from_body():
    """[T4] '## 변경 이유' 다음 줄을 추출(같은 줄의 '(Why)' 접미 오추출 금지)."""
    import zettel_capture as z
    msg = "fix: x\n\n## 변경 이유 (Why)\n근본 원인 한 줄\n\n## 변경 내용 (What)\n- 파일"
    assert z._extract_commit_why(msg) == "근본 원인 한 줄"


def test_extract_commit_why_empty_when_title_only():
    """[T4] 3섹션 본문이 없으면 빈 문자열(호출부가 제목만 사용)."""
    import zettel_capture as z
    assert z._extract_commit_why("chore: bump version") == ""


# ═══════════════════════════════════════════════════════════════════════════
# T7 — GDrive 크로스공유 노이즈 필터
# ═══════════════════════════════════════════════════════════════════════════

def _make_note(vault: Path, folder: str, name: str, source_ref: str):
    (vault / folder).mkdir(parents=True, exist_ok=True)
    (vault / folder / name).write_text(
        f"---\nsource_ref: {source_ref}\n---\n# {name}", encoding='utf-8')
    return vault / folder / name


def test_gdrive_filter_excludes_commit_dumps(tmp_path):
    """[T7] 커밋덤프(git-commit:*)만 제외, 카드/지도/결정/구조는 유지."""
    import zettel_sync as zs
    v = tmp_path / "vault"
    commit = _make_note(v, "영구지식", "c.md", "git-commit:fix")
    card = _make_note(v, "영구지식", "r.md", "file-role:server.py")
    pmap = _make_note(v, "영구지식", "m.md", "project-map")
    know = _make_note(v, "영구지식", "k.md", "decision")
    doc = v / "_project" / "CLAUDE.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# doc", encoding='utf-8')

    assert zs._is_gdrive_worthy(commit, v) is False
    assert zs._is_gdrive_worthy(card, v) is True
    assert zs._is_gdrive_worthy(pmap, v) is True
    assert zs._is_gdrive_worthy(know, v) is True
    assert zs._is_gdrive_worthy(doc, v) is True  # 구조/문서는 항상 복사


# ═══════════════════════════════════════════════════════════════════════════
# 크로스-PC 양방향 — 시그니처/계약 회귀 (라이브 통합은 별도 검증됨)
# ═══════════════════════════════════════════════════════════════════════════

def test_watch_and_sync_accepts_include_archived():
    """[양방향] watch_and_sync가 include_archived를 받아야 한다 —
    GDrive 루프와 로컬 루프의 아카이브 표현을 일치시켜 _보관 파일 핑퐁을 막는 핵심 계약."""
    import inspect
    import zettel_sync as zs
    sig = inspect.signature(zs.watch_and_sync)
    assert 'include_archived' in sig.parameters


def test_mirror_vault_accepts_note_filter():
    """[GDrive 정제] mirror_vault가 note_filter를 받아야 커밋덤프 노이즈를 허브에서 뺄 수 있다."""
    import inspect
    import zettel_sync as zs
    assert 'note_filter' in inspect.signature(zs.mirror_vault).parameters
