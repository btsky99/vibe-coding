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
from infra.embed_service import EMBED_DIM, EMBED_MODEL_NAME, EMBED_SIGNATURE

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
        # [🔴 2026-08-14] 세션요약을 회상 대상에서 제외한다. 실측: 활성 노트 2583건 중
        #   1578건(61%)이 세션요약이었고, 내용이 "하 이제 설치되내 쩝" 같은 발화 로그라
        #   어떤 질문에도 0.45~0.50으로 걸려 회상 블록을 통째로 채웠다. 지식이 아니라
        #   대화 기록이다 — pg_logs에 이미 있고 회상으로 다시 볼 이유가 없다.
        # [WHY 삭제가 아니라 조회 차단] 오판이면 되돌려야 한다. 필터 한 줄을 빼면
        #   즉시 복구되지만 DELETE는 되돌릴 수 없다.
        'quality': ("length(coalesce(title,'') || coalesce(content,'')) >= 30 "
                    "AND coalesce(source_ref, '') <> 'session-summary'"),
        # [WHY min_sim 없음] 예전엔 여기에 0.58을 박아 호출자가 넘긴 0.45를 막았다.
        #   그 우회는 vector_search의 `max()`가 _FLOOR를 비교 대상에서 빠뜨린 버그
        #   때문이었고, 그 버그를 고친 지금은 _FLOOR가 모든 테이블에 강제된다.
        #   숫자를 두 곳에 두면 모델 교체 때 한쪽만 갱신돼 다시 어긋난다 — 단일 출처는
        #   _FLOOR다. 특정 테이블만 **더 엄하게** 걸 근거가 실측으로 생기면 그때 추가한다.
    },
    'hive_memory': {
        'pk': 'key',
        'text': "title || ' ' || LEFT(content, 400)",
        'ref': 'ref_count',
        # TEXT 컬럼 안전 캐스트 — 빈 문자열이면 NOW()로 간주(감쇠 0)
        'time': "CASE WHEN updated_at <> '' THEN updated_at::timestamptz ELSE NOW() END",
        'select': "key, title, LEFT(content, 200) AS content, author, project_id",
        'quality': "length(coalesce(title,'') || coalesce(content,'')) >= 30",
        # min_sim 없음 — zettel_notes와 같은 이유(_FLOOR 단일 출처).
    },
    'agent_experience': {
        'pk': 'id',
        'text': "description",
        'ref': 'ref_count',
        'time': "created_at",
        'select': "id, agent_id, task_type, domain, outcome, LEFT(description, 200) AS description",
        'quality': "length(coalesce(description,'')) >= 20",
        # [🔴 2026-08-08 실측] 이 테이블만 임계를 높인다. 내용이 **커밋 메시지**라
        #   "feat(zettel): 파일명 전체 한글화 — 노트 + 프로젝트 문서 그래프 뷰" 처럼
        #   일반 명사 나열이 많고, 그런 문장은 임베딩 공간의 중심 근처에 놓여
        #   아무 질의와도 0.6 안팎으로 매칭된다. 실제로 무관 질의 4건 중 3건의
        #   최고점이 전부 이 테이블에서 나왔다("영화 추천해줘" 0.632).
        #   0.66 = 그 노이즈 상한(0.632)과 진짜 관련 결과(0.688) 사이.
        # [대안을 버린 이유] 전역 임계를 0.65로 올리면 노이즈는 0이 되지만 관련 질의도
        #   5건 중 1건만 통과했다. 노이즈의 출처가 한 테이블에 몰려 있으므로
        #   그 테이블만 조이는 것이 손실이 훨씬 적다.
        'min_sim': 0.66,
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


def ensure_vector_schema(skip_signature_guard: bool = False) -> bool:
    """vector 확장 + embedding 컬럼 + 참조 컬럼을 보장한다. 실패 시 False(무음).

    [WHY] CREATE EXTENSION은 superuser 권한/확장 파일 필요 — 외부 프로젝트 PC의
    PG에는 없을 수 있다. 실패해도 회상 v1(ILIKE)이 100% 동작하므로 경고만 남긴다.
    """
    # [🔴 부트스트랩 데드락 방지] 서명 가드는 '무효 벡터로 검색하는 것'을 막으려는 장치다.
    #   그런데 그 무효 상태를 **해소하는 도구**(scripts/reembed_all.py)까지 막아버리면
    #   복구 경로가 사라진다. 재임베딩 도구만 이 가드를 건너뛴다 — 그 도구는 검색을
    #   하지 않고 쓰기만 하므로 오답이 나올 위험이 없다.
    global _VECTOR_READY
    if skip_signature_guard:
        execute_raw("CREATE EXTENSION IF NOT EXISTS vector;")
        return bool(query_rows("SELECT 1 AS ok FROM pg_extension WHERE extname = 'vector';"))
    if _VECTOR_READY is not None:
        return _VECTOR_READY

    execute_raw("CREATE EXTENSION IF NOT EXISTS vector;")
    probe = query_rows("SELECT 1 AS ok FROM pg_extension WHERE extname = 'vector';")
    if not probe:
        print("[pg_vector] vector 확장 없음 — 회상 v2 비활성 (ILIKE 폴백 유지)")
        _VECTOR_READY = False
        return False

    # 벡터 출처 불일치 감지 — 저장된 벡터가 '어느 공간에서 온 것'인지 대조한다.
    # [🔴🔴 과거사고 2026-08-14] 예전엔 **모델 이름만** 비교했다. 그런데 fastembed 0.8이
    #   같은 이름 모델의 풀링을 CLS→MEAN으로 바꿔버려, 이름은 그대로인 채 벡터 공간만
    #   통째로 갈아엎혔다. 이 가드는 통과했고 계측도 "커버리지 100% 🟢"를 찍었으며,
    #   실제로는 정답 노트가 452건 중 364위로 밀려 회상이 쓰레기만 반환하고 있었다.
    #   → 이름이 아니라 **서명(모델·차원·풀링·접두어 규약·라이브러리 버전)** 을 비교한다.
    # [불변식] 서명이 다르면 회상을 **끄는 게 맞다.** 무효 벡터로 검색하면 결과가 없는 게
    #   아니라 '그럴듯한 오답'이 나온다 — 침묵보다 나쁘다.
    meta = query_rows(
        "SELECT payload->>'signature' AS signature, payload->>'model' AS model, "
        "payload->>'dim' AS dim "
        "FROM hive_state WHERE state_key = 'embed_model' LIMIT 1;"
    )
    _db_sig = (meta[0].get('signature') if meta else None) or ''
    if _db_sig and _db_sig != EMBED_SIGNATURE:
        print(f"[pg_vector] 🔴 임베딩 서명 불일치 — 저장된 벡터가 다른 공간에서 왔습니다.\n"
              f"            DB  = {_db_sig}\n"
              f"            코드 = {EMBED_SIGNATURE}\n"
              f"            회상 v2 비활성. 복구: python scripts/reembed_all.py --run")
        _VECTOR_READY = False
        return False
    if not _db_sig and meta and meta[0].get('model') and meta[0]['model'] != EMBED_MODEL_NAME:
        # 서명 도입 이전(구버전 메타)과의 호환 — 이름만이라도 다르면 막는다.
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

    # [WHY DO NOTHING 유지] 여기서 자동 갱신하면 서명이 바뀔 때마다 조용히 덮어써서
    #   위의 불일치 가드가 영영 안 걸린다. 서명 갱신은 **재임베딩을 마친 쪽**만 한다
    #   (scripts/reembed_all.py) — "벡터가 새 공간으로 옮겨졌다"는 사실의 유일한 증거이므로
    #   벡터를 실제로 다시 만든 주체가 기록해야 한다.
    # [🔴 복구 안내는 실재해야 한다] 위 print의 명령줄은 **실행 가능한 정본**이어야 한다.
    #   2026-08-14 도입 시 없는 파일(`reembed.py --yes`)을 안내해, 가드에 걸린 사람이
    #   그대로 붙여넣으면 "그런 파일 없음"만 보게 돼 있었다. 스크립트명/플래그를 바꾸면
    #   이 문자열도 같이 바꾼다.
    execute_raw(
        "INSERT INTO hive_state (state_key, payload, updated_at) VALUES ('embed_model', "
        + _sql_text(f'{{"model": "{EMBED_MODEL_NAME}", "dim": {EMBED_DIM}, '
                    f'"signature": "{EMBED_SIGNATURE}"}}') + "::jsonb, "
        + _sql_text(_now_iso()) + ") ON CONFLICT (state_key) DO NOTHING;"
    )
    _VECTOR_READY = True
    print("[pg_vector] 회상 v2 스키마 준비 완료 (vector 확장 + embedding 컬럼)")
    return True


def _vec_literal(vec: list[float]) -> str:
    """float 리스트 → pgvector 리터럴. 소수 6자리 — 384차원 기준 SQL 길이 ~3KB."""
    return "'[" + ",".join(f"{float(x):.6f}" for x in vec) + "]'::vector"


def pending_embedding_rows(table: str, limit: int = 50) -> list[dict]:
    """백필 데몬용 — embedding IS NULL이고 **본문이 있는** 행의 (pk, text)를 반환.

    [🔴 과거사고 2026-08-14] 빈 본문 조건이 없어 백필과 재임베딩이 서로를 되돌렸다.
      scripts/reembed_all.py는 빈 행을 NULL로 비우고(placeholder 벡터가 아무 질의와도
      중간 매칭돼 회상 노이즈가 되므로), 백필은 NULL인 그 행을 골라 '(빈 내용)'으로
      다시 채웠다(NULL로 두면 매 주기 재선택되는 무한 루프를 피하려고). 두 정책이
      정면 충돌해 60초마다 왕복했고, 결국 노이즈 쪽이 이겼다.
    [불변식] 빈 본문은 **영구히 NULL**이다 — 검색에서 빠지는 게 옳다. 무한 루프는
      placeholder로 채워서가 아니라 여기서 **선택 자체를 막아** 끊는다. 그래야 두 목적
      (노이즈 차단 · 재선택 방지)이 동시에 성립한다.
    """
    if not vector_available() or table not in _TABLES:
        return []
    cfg = _TABLES[table]
    return query_rows(
        f"SELECT {cfg['pk']} AS pk, ({cfg['text']}) AS text FROM {table} "
        f"WHERE embedding IS NULL AND length(btrim(coalesce(({cfg['text']}), ''))) > 0 "
        f"LIMIT {int(limit)};"
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


# [불변식] 어떤 호출자도 이 아래로는 못 내린다. 기본 인자는 호출자가 덮어쓸 수 있지만
#   이 상수는 vector_search 안에서 강제되므로 우회 경로가 없다 — 위 과거사고의 재발 방지선.
#
# [🔴🔴 이 숫자는 모델에 종속된다 — 모델을 바꾸면 반드시 다시 잰다]
#   임계값은 '의미의 경계'가 아니라 **그 모델의 코사인 분포 위 좌표**다. 모델이 바뀌면
#   분포가 통째로 이동하므로 옛 숫자는 의미를 잃는다.
#     MiniLM 시절 : 관련/무관이 0.4~0.6에 퍼져 0.55가 실제로 경계 역할을 했다.
#     e5-small-ml : 0.8 근처 좁은 띠에 몰린다 — 0.55는 **아무것도 못 거른다.**
#   2026-08-14 실측(scripts/recall_quality.py, 지식 5169건):
#     관련 최저 0.860 / 무관 최고 0.847 → 간격 +0.013. 0.55로는 무관 질의 4건이
#     전부 회상됐다("오늘 점심 뭐 먹지"가 0.829로 통과).
#   0.85는 그 사이를 가르는 값이다.
#
# [🔴 이 값의 한계를 알고 쓸 것 — 표본 9건에 맞춘 숫자다]
#   관련 5·무관 4건으로 정한 값이라 **과적합이다.** 여유가 관련 +0.010 / 무관 -0.003
#   밖에 없어, 표본 밖 질의 하나로 뒤집힐 수 있다. 게다가 남은 오분류 1건은 임계로
#   풀 수 없는 종류였다 — "오늘 점심 뭐 먹지"가 'recipe'가 든 노트와 0.847로 붙었다.
#   어휘가 실제로 겹치므로 모델 판단이 틀린 게 아니다.
#   → 진짜 해법은 절대 임계가 아니라 **순위 기반 판정**이다(embed_service의 e5 주석과
#     같은 결론). 상위 후보 간 점수 차가 작으면 '변별 실패'로 보고 통째로 버리는 식.
#     그 구조 전환 전까지 이 상수는 **임시 방편**이다.
# [불변식] 오분류가 보여도 숫자를 감으로 흔들지 말 것. recall_quality.py로 **다시 재고**
#   위 실측 줄을 갱신한 뒤에만 바꾼다 — 근거 없는 조정이 0.45→0.55→0.66 6일 삽질의 형태였다.
_FLOOR = 0.85

# 랭킹 보정항 가중치. [불변식] (_REF_WEIGHT×ln(1+ref) + _AGE_WEIGHT)의 실질 크기는
#   관련/무관 유사도 간격(현 모델 기준 ≈0.04)보다 작아야 한다 — 크면 보정이 순위를
#   뒤집어 유사도 1위가 탈락한다(2026-08-15 사고: 0.1이었고 ref=82에서 +0.442였다).
#   ref=100에서도 가산은 0.018로, 간격의 절반 이하에 머문다.
_REF_WEIGHT = 0.004
_AGE_WEIGHT = 0.004


def vector_search(table: str, query_vec: list[float], project_id: str = '',
                  limit: int = 5, min_similarity: float = _FLOOR) -> list[dict]:
    """코사인 유사도 검색 + 랭킹.

    랭킹 = 유사도 + 0.004×ln(1+참조횟수) − 시간감쇠
    - 시간감쇠 = 0.004 × (1 − 0.5^(경과일/30)) : 30일에 −0.002, 포화 −0.004
    - min_similarity 미만은 제외 — 무관 회상 주입(소음)의 직접 차단선.

    [🔴🔴 계수 0.1 → 0.004 (2026-08-15 실측) — 보정항이 본항을 삼키고 있었다]
      e5 전환 후 코사인이 0.85~0.89의 **좁은 띠**에 몰렸다. 정답과 무관 항목의 간격이
      0.04뿐인데 참조 가산은 0.1×ln(1+82) = **+0.442** — 본항의 10배였다. 결과:
        질의 "데몬이 콘솔 창을 띄우지 않게" → 정답(daemons.py·_spawn_script, sim 0.887,
        유사도 1위)이 탈락하고 참조 82회짜리 무관 노트가 상위를 전부 차지.
      한 번 뜬 항목이 참조를 벌어 영원히 1등을 지키는 **부익부 루프**였고, 새로 쓴 지식은
      참조 0이라 구조적으로 절대 못 올라온다(코드주석 지식 452건의 참조 총합이 5회인 이유).
      가산 상한을 유사도 간격의 1/10 수준(≈0.018 @ ref=100)으로 낮춰 **순위는 유사도가
      정하고 보정은 동점을 가르는 데만** 쓰이게 한다.
    [불변식] 보정항(참조·시간)의 합은 관련/무관 유사도 간격보다 **작아야 한다.**
      모델을 바꾸면 간격이 달라지므로 `scripts/recall_quality.py --sweep`으로 간격을
      다시 재고 이 계수도 같이 조정할 것 — 0.004는 상수가 아니라 관측에 종속된 값이다.

    [🔴 임계 0.45 → 0.55(+테이블별) — 2026-08-08 실측 근거]
      0.45는 이 모델(paraphrase-multilingual-MiniLM)에서 사실상 무필터였다. 실측:
        관련 질의 최고 0.688 / 무관 질의("영화 추천해줘") 최고 0.632
      즉 아무 질문에나 커밋 메시지가 딸려 나와 매 프롬프트의 회상 블록을 채웠다.
      노이즈가 특정 테이블(agent_experience=커밋 메시지)에 몰려 있어 전역을 0.55로 두고
      그 테이블만 _TABLES['min_sim']=0.66으로 조인다. 전역 0.65 단일안은 노이즈를
      없애는 대신 관련 질의도 5건 중 1건만 남겨 손실이 너무 컸다.
    [의도적 트레이드오프] '놓침'은 생긴다. 그래도 노이즈보다 낫다 — 놓치면 아무것도
      안 뜨지만, 노이즈는 회상 자체의 신뢰를 무너뜨려 블록 전체를 무시하게 만든다.
    [재조정 방법] `python scripts/recall_quality.py --sweep` 로 관련/무관 간격을 다시
      재고 조정할 것. 데이터가 쌓이면 무관 상한이 달라진다 — 고정 상수가 아니라 관측 대상이다.
    """
    if not vector_available() or table not in _TABLES or not query_vec:
        return []
    cfg = _TABLES[table]
    # 테이블별 임계가 있으면 그쪽을 쓴다. 호출자가 명시적으로 더 높게 준 경우는 존중한다
    # (더 낮추는 것은 허용하지 않는다 — 노이즈 차단선을 우회로 뚫으면 안 된다).
    # [🔴 과거사고 2026-08-08~08-14] 이 가드에 구멍이 있었다. `max(호출자값, cfg)`만
    #   비교해서 **함수 기본값(_FLOOR)은 비교 대상이 아니었다.** api/memory_api가
    #   min_similarity=0.45를 명시로 넘기면 cfg에 min_sim이 없는 테이블
    #   (zettel_notes·hive_memory = 지식의 88%)은 0.45가 그대로 통과했다. 즉 2026-08-08의
    #   0.55 상향이 6일 동안 **가장 큰 두 테이블에서만 무효**였고, 아무도 몰랐다.
    #   바닥선을 셋 다 비교하도록 고친다 — 이제 어떤 호출자도 _FLOOR 아래로 못 내린다.
    min_similarity = max(float(min_similarity), float(cfg.get('min_sim', 0.0)), _FLOOR)
    proj_filter = f"AND project_id = {_sql_text(project_id)}" if project_id else ""
    # 저정보 행 차단(_TABLES.quality) — 회상 노이즈 컷 (2026-07-16)
    quality_filter = f"AND {cfg['quality']}" if cfg.get('quality') else ""
    qv = _vec_literal(query_vec)
    sql = f"""
        SELECT {cfg['select']},
               sim,
               (sim + {_REF_WEIGHT} * LN(1 + {cfg['ref']})
                    - {_AGE_WEIGHT} * (1 - POWER(0.5, age_days / 30.0))) AS score
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
