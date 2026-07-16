# -*- coding: utf-8 -*-
"""
FILE: tests/test_self_heal_2.py
DESCRIPTION: 자가 치유 2.0 회귀 방지 테스트 — 회상 v2(pgvector) 그레이스풀
             디그레이드, 0.45 임계, 참조 피드백, recall_client 폴백 계약.
             DB 연결 함수는 라이브 PG가 있을 때만 실행 (skipif).

REVISION HISTORY:
- 2026-06-10 Claude: 최초 작성 — Phase ④ (Task 8)
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
sys.path.insert(0, str(_AI_MONITOR))


def _db_alive() -> bool:
    try:
        from src.pg_schema import ensure_schema
        return bool(ensure_schema())
    except Exception:
        return False


# ── 1. 그레이스풀 디그레이드 — vector 비활성 시 전 함수 no-op ────────────────

def test_vector_functions_silent_when_unavailable():
    import src.pg_vector_search as pv
    # [WHY] 외부 프로젝트 PC(확장 미설치)를 시뮬 — 어떤 함수도 예외/SQL 시도 금지
    with mock.patch.object(pv, '_VECTOR_READY', False):
        assert pv.vector_available() is False
        assert pv.pending_embedding_rows('zettel_notes') == []
        assert pv.upsert_embedding('zettel_notes', 'x', [0.1] * 384) is False
        assert pv.vector_search('zettel_notes', [0.1] * 384) == []
        pv.bump_reference('zettel_notes', ['x'])  # 예외 없이 무음


def test_vector_table_whitelist_blocks_unknown():
    import src.pg_vector_search as pv
    # [WHY] 테이블명 f-string 조립 — 화이트리스트 밖 입력은 인젝션 면역이어야 함
    with mock.patch.object(pv, '_VECTOR_READY', True):
        assert pv.vector_search("pg_logs; DROP TABLE x;--", [0.1] * 384) == []
        assert pv.pending_embedding_rows('없는테이블') == []
        assert pv.upsert_embedding('없는테이블', 1, [0.1] * 384) is False


def test_vec_literal_format():
    from src.pg_vector_search import _vec_literal
    lit = _vec_literal([0.1, -0.25, 1.0])
    assert lit.startswith("'[") and lit.endswith("]'::vector")
    assert "0.100000" in lit and "-0.250000" in lit


def test_cosine_similarity_pure():
    from src.pg_vector_search import cosine_similarity
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0]) == 0.0  # 차원 불일치 → 0


# ── 2. embed_service 계약 — 로드 트리거 금지 가드 ────────────────────────────

def test_is_loaded_does_not_trigger_load():
    import infra.embed_service as es
    # 모델 미로드(None) 상태에서 is_loaded는 False — 로드 시도 자체가 없어야 함
    with mock.patch.object(es, '_embedder', None):
        assert es.is_loaded() is False
        assert es.is_available() is True  # 아직 실패 마킹 아님
    with mock.patch.object(es, '_embedder', False):
        assert es.is_loaded() is False
        assert es.is_available() is False  # 로드 실패 마킹


def test_embed_dim_matches_vector_column():
    # [불변식] embed_service.EMBED_DIM ↔ pg_vector_search vector(384) 단일 진실
    from infra.embed_service import EMBED_DIM
    from src.pg_vector_search import _TABLES
    assert EMBED_DIM == 384
    assert set(_TABLES) == {'zettel_notes', 'hive_memory',
                            'agent_experience', 'incident_ledger'}


# ── 2.5. 사고 장부 — 시그니처 정규화 계약 ────────────────────────────────────

def test_signature_stable_across_paths_and_lines():
    # [핵심 계약] 경로/줄번호/주소/시각이 달라도 같은 에러 = 같은 시그니처
    from src.pg_incidents import normalize_signature
    a = normalize_signature(
        'File "D:\\vibe-coding\\server.py", line 1234\n'
        'psycopg2.OperationalError: connection refused 0xDEADBEEF 2026-06-10T21:00:00')
    b = normalize_signature(
        'File "C:\\other\\proj\\server.py", line 99\n'
        'psycopg2.OperationalError: connection refused 0x1234AB 2026-01-01T09:30:00')
    assert a == b


def test_signature_differs_for_different_errors():
    from src.pg_incidents import normalize_signature
    a = normalize_signature("ModuleNotFoundError: No module named 'infra'")
    b = normalize_signature('psycopg2.OperationalError: connection refused')
    assert a != b
    assert normalize_signature('') == ''


def test_incident_briefing_format():
    from src.pg_incidents import format_incident_briefing
    assert format_incident_briefing([]) == ''
    text = format_incident_briefing([{
        'match_score': 1.0, 'recurrence_count': 3,
        'error_text': 'E', 'root_cause': 'C', 'fix_description': 'F', 'fix_commit': 'abc',
    }])
    assert '동일' in text and '재발 2회' in text and '수정법: F' in text


# ── 3. recall_client 폴백 계약 ───────────────────────────────────────────────

def test_recall_client_empty_query_returns_empty():
    from src.recall_client import smart_recall_summary
    assert smart_recall_summary('') == ''
    assert smart_recall_summary('   ') == ''


def test_recall_client_falls_back_when_no_server():
    import src.recall_client as rc
    # 서버 포트 탐색 실패 시 v1 폴백이 호출되는지 — 네트워크 없이 검증
    with mock.patch.object(rc, '_find_active_server_port', return_value=None), \
         mock.patch.object(rc, '_fallback_summary', return_value='V1폴백') as fb:
        assert rc.smart_recall_summary('테스트 쿼리') == 'V1폴백'
        fb.assert_called_once()


def test_recall_client_uses_server_summary():
    import src.recall_client as rc

    class _FakeResp:
        def read(self):
            return ('{"status":"success","fallback":false,'
                    '"summary":"[회상 v2] 결과"}').encode('utf-8')
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with mock.patch.object(rc, '_find_active_server_port', return_value=9000), \
         mock.patch.object(rc._urllib_request, 'urlopen', return_value=_FakeResp()):
        assert rc.smart_recall_summary('쿼리') == '[회상 v2] 결과'


def test_recall_client_respects_no_match_signal():
    # fallback=false + 빈 summary = "관련 지식 없음" — v1 폴백으로 덮지 않는다
    # [WHY] 이게 핵심 계약: 무관 회상 노이즈를 v1이 다시 주입하면 0.45 임계가 무력화
    import src.recall_client as rc

    class _FakeResp:
        def read(self):
            return '{"status":"success","fallback":false,"summary":""}'.encode('utf-8')
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with mock.patch.object(rc, '_find_active_server_port', return_value=9000), \
         mock.patch.object(rc._urllib_request, 'urlopen', return_value=_FakeResp()), \
         mock.patch.object(rc, '_fallback_summary', return_value='V1') as fb:
        assert rc.smart_recall_summary('전혀 무관한 쿼리') == ''
        fb.assert_not_called()


# ── 4. 라이브 DB 통합 (PG 가동 시에만) ───────────────────────────────────────

@pytest.mark.skipif(not _db_alive(), reason="라이브 PostgreSQL 없음")
def test_live_vector_schema_and_threshold():
    from src.pg_vector_search import (
        ensure_vector_schema, vector_available, vector_search,
        upsert_embedding, bump_reference,
    )
    from src.pg_base import query_rows, execute
    if not ensure_vector_schema():
        pytest.skip("vector 확장 없음 — 디그레이드 경로는 위 단위 테스트가 커버")
    assert vector_available()

    # 테스트 행 심기 — 직교 벡터 2개로 임계 필터 검증
    # [2026-07-16] quality 필터(title+content ≥ 30자) 도입 — 픽스처가 통과하도록
    # 본문 확장 + 저정보 행(b)이 자기 임베딩으로도 차단되는 회귀 검증 추가 (A1).
    execute("DELETE FROM hive_memory WHERE key LIKE 'test:selfheal2:%';")
    execute("INSERT INTO hive_memory (key, title, content, project_id, created_at, updated_at) "
            "VALUES ('test:selfheal2:a', '테스트A', '임계 필터 검증용 본문 — 삼십자 이상을 채우는 설명 텍스트', 'test_proj', "
            "'2026-06-10T00:00:00', '2026-06-10T00:00:00');")
    execute("INSERT INTO hive_memory (key, title, content, project_id, created_at, updated_at) "
            "VALUES ('test:selfheal2:b', '짧음', '내용', 'test_proj', "
            "'2026-06-10T00:00:00', '2026-06-10T00:00:00');")
    base = [0.0] * 384
    near = list(base); near[0] = 1.0; near[1] = 0.1          # 쿼리와 거의 동일
    qvec = list(base); qvec[0] = 1.0
    ortho = list(base); ortho[383] = 1.0                      # 직교 — sim≈0
    assert upsert_embedding('hive_memory', 'test:selfheal2:a', near)
    assert upsert_embedding('hive_memory', 'test:selfheal2:b', near)

    hits = vector_search('hive_memory', qvec, project_id='test_proj', limit=5)
    assert any(h['key'] == 'test:selfheal2:a' for h in hits), "0.45 이상인데 누락"
    # 저정보 행은 유사도 만점이어도 차단 — 회상 노이즈 컷 (quality 필터)
    assert not any(h['key'] == 'test:selfheal2:b' for h in hits), "저정보 행이 quality 필터를 뚫음"

    misses = vector_search('hive_memory', ortho, project_id='test_proj', limit=5)
    assert not any(h['key'] == 'test:selfheal2:a' for h in misses), "임계 미달인데 주입"

    # 참조 피드백 — bump 후 ref_count 증가 확인
    before = query_rows("SELECT ref_count FROM hive_memory WHERE key='test:selfheal2:a';")
    bump_reference('hive_memory', ['test:selfheal2:a'])
    after = query_rows("SELECT ref_count FROM hive_memory WHERE key='test:selfheal2:a';")
    assert int(after[0]['ref_count']) == int(before[0]['ref_count']) + 1

    execute("DELETE FROM hive_memory WHERE key LIKE 'test:selfheal2:%';")


# ── 5. 1500줄 규칙 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel_path", [
    "src/pg_vector_search.py", "src/recall_client.py",
    "infra/embed_service.py", "infra/daemons.py", "api/memory_api.py",
])
def test_new_modules_under_1500_lines(rel_path):
    path = _AI_MONITOR / rel_path
    n_lines = len(path.read_text(encoding='utf-8').splitlines())
    assert n_lines <= 1500, f"{rel_path}: {n_lines}줄 — 1500줄 규칙 위반"
