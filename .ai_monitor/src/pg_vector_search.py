# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_vector_search.py
# 📝 설명: pgvector 기반 회상 v2 — embedding 컬럼 마이그레이션 + 코사인 검색 +
#          참조 피드백. 자가 치유 2.0의 기반 공사 (Task 2).
# 🕒 변경 이력:
# [2026-07-16] Claude — _TABLES에 quality 필터 추가 — 백필의 '(빈 내용)' placeholder
#   임베딩이 일반 쿼리와 0.5+ 매칭되던 회상 노이즈를 검색 시점에 차단 (A1)
# [2026-06-10] Claude — 신설 (brainstorm 승인안 ④)
#   - [불변식] 모든 함수는 vector 확장 미설치 DB에서 조용히 비활성(no-op/[]) —
#     기존 ILIKE 회상 경로를 절대 깨지 않는다 (그레이스풀 디그레이드).
#   - [제약] ensure_vector_schema()는 pg_schema.ensure_schema()의
#     _SCHEMA_READY=True 이후에만 호출할 것 — 그 전에 부르면 query_rows가
#     ensure_schema에 재진입해 _SCHEMA_LOCK(비재진입 Lock) 데드락.
#   - [WHY] 테이블/컬럼명은 _TABLES 화이트리스트로만 — f-string SQL 조립이라
#     외부 입력이 테이블명에 닿으면 인젝션. 호출자는 키만 넘긴다.
#   - [호환성 함정] hive_memory.updated_at은 TEXT(ISO 문자열) — timestamptz 캐스트를
#     CASE로 감싼다. 빈 문자열 캐스트는 SQL 에러.
# ────────────────────────────────────────────────────────────────────────────
import math

from src.pg_base import execute_raw, query_rows, _sql_text, _now_iso

# [WHY] 차원/모델은 embed_service와 단일 진실 — 직접 상수 복제 금지
from infra.embed_service import EMBED_DIM, EMBED_MODEL_NAME

# None=미확인, True/False=ensure_vector_schema 결과 캐시
_VECTOR_READY: bool | None = None

# 회상 대상 테이블 화이트리스트 — 테이블별 검색 설정
# ref: 참조 횟수 컬럼(피드백 루프), time: 시간감쇠 기준, text: 임베딩 원문
_TABLES = {
    # [2026-07-16] quality: 검색 시점 저정보 행 차단 — 백필이 빈 텍스트를 '(빈 내용)'
    # placeholder로 임베딩하는 구조(무한루프 방지) 때문에 저정보 레코드가 일반 쿼리와
    # 0.5+ 유사도로 매칭되던 회상 노이즈의 직접 수정. 데이터 마이그레이션 불필요.
    # incident_ledger는 필터 없음 — 사고는 짧아도 회상 가치가 높다.
    'zettel_notes': {
        'pk': 'id',
        'text': "title || ' ' || LEFT(content, 400)",
        'ref': 'access_count',
        'time': "updated_at",
        'select': "id, title, LEFT(content, 200) AS content, note_type, author, project_id",
        'quality': "length(coalesce(title,'') || coalesce(content,'')) >= 30",
    },
    'hive_memory': {
        'pk': 'key',
        'text': "title || ' ' || LEFT(content, 400)",
        'ref': 'ref_count',
        # TEXT 컬럼 안전 캐스트 — 빈 문자열이면 NOW()로 간주(감쇠 0)
        'time': "CASE WHEN updated_at <> '' THEN updated_at::timestamptz ELSE NOW() END",
        'select': "key, title, LEFT(content, 200) AS content, author, project_id",
        'quality': "length(coalesce(title,'') || coalesce(content,'')) >= 30",
    },
    'agent_experience': {
        'pk': 'id',
        'text': "description",
        'ref': 'ref_count',
        'time': "created_at",
        'select': "id, agent_id, task_type, domain, outcome, LEFT(description, 200) AS description",
        'quality': "length(coalesce(description,'')) >= 20",
    },
    # 사고 장부 — ref에 recurrence_count 사용: 재발 잦은 사고일수록 회상 우선순위 ↑
    # [주의] bump_reference를 이 테이블에 쓰면 재발 카운트가 오염됨 — 호출 금지
    # (memory_api recall-smart의 피드백 루프는 위 3개 테이블만 대상)
    'incident_ledger': {
        'pk': 'id',
        'text': "error_text || ' ' || root_cause",
        'ref': 'recurrence_count',
        'time': "last_seen_at",
        'select': ("id, error_signature, LEFT(error_text, 150) AS error_text, "
                   "root_cause, fix_description, fix_commit, recurrence_count, project_id"),
    },
}


def vector_available() -> bool:
    """vector 확장 사용 가능 여부 — ensure_vector_schema 결과 캐시 조회."""
    return _VECTOR_READY is True


def reset_vector_cache() -> None:
    """프로젝트 DB 전환(set_project_db) 후 재확인용 — pg_schema.reset_schema_cache와 짝."""
    global _VECTOR_READY
    _VECTOR_READY = None


def ensure_vector_schema() -> bool:
    """vector 확장 + embedding 컬럼 + 참조 컬럼을 보장한다. 실패 시 False(무음).

    [WHY] CREATE EXTENSION은 superuser 권한/확장 파일 필요 — 외부 프로젝트 PC의
    PG에는 없을 수 있다. 실패해도 회상 v1(ILIKE)이 100% 동작하므로 경고만 남긴다.
    """
    global _VECTOR_READY
    if _VECTOR_READY is not None:
        return _VECTOR_READY

    execute_raw("CREATE EXTENSION IF NOT EXISTS vector;")
    probe = query_rows("SELECT 1 AS ok FROM pg_extension WHERE extname = 'vector';")
    if not probe:
        print("[pg_vector] vector 확장 없음 — 회상 v2 비활성 (ILIKE 폴백 유지)")
        _VECTOR_READY = False
        return False

    # 모델 차원 불일치 감지 — 모델 교체 시 컬럼 재생성이 필요하므로 메타로 고정
    meta = query_rows(
        "SELECT payload->>'model' AS model, payload->>'dim' AS dim "
        "FROM hive_state WHERE state_key = 'embed_model' LIMIT 1;"
    )
    if meta and meta[0].get('model') and meta[0]['model'] != EMBED_MODEL_NAME:
        print(f"[pg_vector] 임베딩 모델 불일치: DB={meta[0]['model']} ≠ 코드={EMBED_MODEL_NAME} "
              "— 재임베딩 필요. 회상 v2 비활성.")
        _VECTOR_READY = False
        return False

    ok = True
    for table in _TABLES:
        ok &= execute_raw(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embedding vector({EMBED_DIM});"
        )
    # 참조 피드백 컬럼 — zettel_notes는 access_count 기존 보유, 나머지 2개만 추가
    for table in ('hive_memory', 'agent_experience'):
        ok &= execute_raw(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS ref_count INT NOT NULL DEFAULT 0;"
        )
    if not ok:
        _VECTOR_READY = False
        return False

    execute_raw(
        "INSERT INTO hive_state (state_key, payload, updated_at) VALUES ('embed_model', "
        + _sql_text(f'{{"model": "{EMBED_MODEL_NAME}", "dim": {EMBED_DIM}}}') + "::jsonb, "
        + _sql_text(_now_iso()) + ") ON CONFLICT (state_key) DO NOTHING;"
    )
    _VECTOR_READY = True
    print("[pg_vector] 회상 v2 스키마 준비 완료 (vector 확장 + embedding 컬럼)")
    return True


def _vec_literal(vec: list[float]) -> str:
    """float 리스트 → pgvector 리터럴. 소수 6자리 — 384차원 기준 SQL 길이 ~3KB."""
    return "'[" + ",".join(f"{float(x):.6f}" for x in vec) + "]'::vector"


def pending_embedding_rows(table: str, limit: int = 50) -> list[dict]:
    """백필 데몬용 — embedding IS NULL인 행의 (pk, text)를 반환."""
    if not vector_available() or table not in _TABLES:
        return []
    cfg = _TABLES[table]
    return query_rows(
        f"SELECT {cfg['pk']} AS pk, ({cfg['text']}) AS text FROM {table} "
        f"WHERE embedding IS NULL LIMIT {int(limit)};"
    )


def upsert_embedding(table: str, pk_value, vec: list[float]) -> bool:
    """단일 행 embedding 갱신 — 백필 데몬/신규 INSERT 직후 호출."""
    if not vector_available() or table not in _TABLES or not vec:
        return False
    cfg = _TABLES[table]
    return execute_raw(
        f"UPDATE {table} SET embedding = {_vec_literal(vec)} "
        f"WHERE {cfg['pk']} = {_sql_text(pk_value)};"
    )


def vector_search(table: str, query_vec: list[float], project_id: str = '',
                  limit: int = 5, min_similarity: float = 0.45) -> list[dict]:
    """코사인 유사도 검색 + 랭킹.

    랭킹 = 유사도 + 0.1×ln(1+참조횟수) − 시간감쇠
    - 시간감쇠 = 0.1 × (1 − 0.5^(경과일/30)) : 30일에 −0.05, 포화 −0.1
      [WHY] 오래된 지식을 죽이지 않되(상한 0.1) 최신 지식에 가산점.
    - min_similarity 미만은 제외 — 무관 회상 주입(소음)의 직접 차단선.
      임계 0.45는 brainstorm 승인값 (memory.md §3.5).
    """
    if not vector_available() or table not in _TABLES or not query_vec:
        return []
    cfg = _TABLES[table]
    proj_filter = f"AND project_id = {_sql_text(project_id)}" if project_id else ""
    # 저정보 행 차단(_TABLES.quality) — 회상 노이즈 컷 (2026-07-16)
    quality_filter = f"AND {cfg['quality']}" if cfg.get('quality') else ""
    qv = _vec_literal(query_vec)
    sql = f"""
        SELECT {cfg['select']},
               sim,
               (sim + 0.1 * LN(1 + {cfg['ref']})
                    - 0.1 * (1 - POWER(0.5, age_days / 30.0))) AS score
        FROM (
            SELECT *,
                   (1 - (embedding <=> {qv})) AS sim,
                   GREATEST(0.0, EXTRACT(EPOCH FROM (NOW() - ({cfg['time']}))) / 86400.0) AS age_days
            FROM {table}
            WHERE embedding IS NOT NULL {proj_filter} {quality_filter}
        ) ranked
        WHERE sim >= {float(min_similarity)}
        ORDER BY score DESC
        LIMIT {int(limit)};
    """
    return query_rows(sql)


def bump_reference(table: str, pk_values: list) -> None:
    """회상으로 반환된 항목의 참조 카운트 증가 — 피드백 루프의 쓰기 절반.

    [WHY] 참조될수록 랭킹 가산 → 유용한 지식이 강해지고, 참조 0회가 지속되는
    노트는 정제(zettel refine) 대상으로 자연 강등된다.
    """
    if not vector_available() or table not in _TABLES or not pk_values:
        return
    cfg = _TABLES[table]
    in_list = ", ".join(_sql_text(v) for v in pk_values)
    execute_raw(
        f"UPDATE {table} SET {cfg['ref']} = {cfg['ref']} + 1 "
        f"WHERE {cfg['pk']} IN ({in_list});"
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """파이썬 측 코사인 유사도 — DB 미경유 비교용(테스트/사고 장부 후보 비교)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 1e-10 and nb > 1e-10 else 0.0
