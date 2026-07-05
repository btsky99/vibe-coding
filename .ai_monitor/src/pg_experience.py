# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_experience.py
# 📝 설명: 에이전트 경험/성장(XP·레벨·스탯) + 유사 경험 회상 + pg_logs 활동 기록
#          (pg_store.py 분할 5/6)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
# ────────────────────────────────────────────────────────────────────────────
from infra.project_context import assert_project_id
from src.pg_base import _now_iso, _sql_text, execute, query_rows


# ── 에이전트 경험/성장 CRUD ──────────────────────────────────────────────────

# XP 가중치 — task_type별 기본 경험치
_XP_WEIGHTS: dict[str, int] = {
    'feat': 100, 'fix': 60, 'refactor': 40, 'docs': 20, 'test': 50,
    'build': 30, 'chore': 10,
}


def _calc_level(total_xp: int) -> int:
    """레벨 공식: level = floor(sqrt(total_xp / 100)), 최소 1"""
    import math
    return max(1, int(math.floor(math.sqrt(total_xp / 100))))


def record_experience(agent_id: str, task_type: str = 'feat',
                      domain: str = 'general', outcome: str = 'success',
                      duration_sec: int = 0, file_patterns: list | None = None,
                      session_id: str = '', description: str = '',
                      project_id: str = '') -> bool:
    """에이전트 경험 기록 + agent_stats 자동 갱신."""
    project_id = assert_project_id(project_id, 'record_experience')
    import json as _json
    xp = _XP_WEIGHTS.get(task_type, 30)
    if outcome == 'fail':
        xp = max(5, xp // 5)  # 실패해도 약간의 경험치
    elif outcome == 'partial':
        xp = xp // 2

    files_json = _json.dumps(file_patterns or [], ensure_ascii=False)

    # 경험 기록 삽입
    ok = execute(
        f"INSERT INTO agent_experience (agent_id, session_id, task_type, domain, "
        f"file_patterns, duration_sec, outcome, xp_earned, description, project_id) "
        f"VALUES ({_sql_text(agent_id)}, {_sql_text(session_id)}, {_sql_text(task_type)}, "
        f"{_sql_text(domain)}, {_sql_text(files_json)}::jsonb, {int(duration_sec)}, "
        f"{_sql_text(outcome)}, {xp}, {_sql_text(description)}, {_sql_text(project_id)});"
    )
    if not ok:
        return False

    # agent_stats 갱신 (UPSERT)
    _refresh_agent_stats(agent_id)
    return True


def _refresh_agent_stats(agent_id: str) -> bool:
    """agent_experience에서 집계하여 agent_stats를 갱신한다."""
    import json as _json

    # 총 XP, 작업 수 집계
    rows = query_rows(
        f"SELECT COALESCE(SUM(xp_earned), 0) AS total_xp, COUNT(*) AS task_count "
        f"FROM agent_experience WHERE agent_id = {_sql_text(agent_id)};"
    )
    if not rows:
        return False
    total_xp = int(rows[0].get('total_xp', 0))
    task_count = int(rows[0].get('task_count', 0))
    level = _calc_level(total_xp)

    # 도메인별 XP 집계 → skill_map
    domain_rows = query_rows(
        f"SELECT domain, SUM(xp_earned) AS domain_xp "
        f"FROM agent_experience WHERE agent_id = {_sql_text(agent_id)} "
        f"GROUP BY domain;"
    )
    skill_map = {r['domain']: int(r['domain_xp']) for r in domain_rows}

    # 연속 활동일 계산 (최근 연속 날짜)
    day_rows = query_rows(
        f"SELECT DISTINCT DATE(created_at) AS d FROM agent_experience "
        f"WHERE agent_id = {_sql_text(agent_id)} ORDER BY d DESC LIMIT 30;"
    )
    streak = 0
    if day_rows:
        from datetime import date, timedelta
        prev = date.today()
        for row in day_rows:
            d = row['d'] if isinstance(row['d'], date) else date.fromisoformat(str(row['d']))
            if (prev - d).days <= 1:
                streak += 1
                prev = d
            else:
                break

    skill_json = _json.dumps(skill_map, ensure_ascii=False)
    return execute(
        f"INSERT INTO agent_stats (agent_id, total_xp, level, task_count, skill_map, streak_days, last_active, updated_at) "
        f"VALUES ({_sql_text(agent_id)}, {total_xp}, {level}, {task_count}, "
        f"{_sql_text(skill_json)}::jsonb, {streak}, NOW(), NOW()) "
        f"ON CONFLICT (agent_id) DO UPDATE SET "
        f"total_xp = {total_xp}, level = {level}, task_count = {task_count}, "
        f"skill_map = {_sql_text(skill_json)}::jsonb, streak_days = {streak}, "
        f"last_active = NOW(), updated_at = NOW();"
    )


def get_agent_stats(agent_id: str | None = None) -> list[dict]:
    """에이전트 통계 조회. agent_id 없으면 전체 반환."""
    if agent_id:
        return query_rows(
            f"SELECT * FROM agent_stats WHERE agent_id = {_sql_text(agent_id)};"
        )
    return query_rows("SELECT * FROM agent_stats ORDER BY total_xp DESC;")


def get_experience_history(agent_id: str | None = None, limit: int = 20) -> list[dict]:
    """최근 경험 목록 조회."""
    where = f"WHERE agent_id = {_sql_text(agent_id)}" if agent_id else ""
    return query_rows(
        f"SELECT id, agent_id, session_id, task_type, domain, outcome, xp_earned, "
        f"description, duration_sec, created_at "
        f"FROM agent_experience {where} "
        f"ORDER BY created_at DESC LIMIT {int(limit)};"
    )


def recall_similar_experience(query: str, domain: str = '',
                              task_type: str = '', agent_id: str = '',
                              limit: int = 5) -> list[dict]:
    """현재 작업과 유사한 과거 경험을 검색한다.

    2단계 검색:
    1) 키워드 ILIKE 매칭 — 한글/영어 모두 정확하게 동작
    2) pg_trgm similarity — 퍼지 매칭 보조
    점수를 합산하여 가장 관련 높은 순서로 반환.
    """
    conditions = []
    if domain:
        conditions.append(f"domain = {_sql_text(domain)}")
    if task_type:
        conditions.append(f"task_type = {_sql_text(task_type)}")
    if agent_id:
        conditions.append(f"agent_id = {_sql_text(agent_id)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    safe_query = _sql_text(query)

    # 쿼리에서 키워드 추출 (2글자 이상 단어)
    import re
    keywords = [w for w in re.split(r'\s+', query.strip()) if len(w) >= 2]

    # 키워드 ILIKE 점수: 각 키워드 매칭마다 +0.3점
    keyword_score_parts = []
    for kw in keywords[:5]:  # 최대 5개 키워드
        safe_kw = _sql_text(f'%{kw}%')
        keyword_score_parts.append(f"CASE WHEN description ILIKE {safe_kw} THEN 0.3 ELSE 0.0 END")

    if keyword_score_parts:
        keyword_score = " + ".join(keyword_score_parts)
    else:
        keyword_score = "0.0"

    return query_rows(
        f"SELECT id, agent_id, task_type, domain, outcome, xp_earned, "
        f"description, duration_sec, file_patterns::text, created_at, "
        f"(similarity(description, {safe_query}) + {keyword_score}) AS sim_score "
        f"FROM agent_experience "
        f"{where} "
        f"ORDER BY sim_score DESC, created_at DESC "
        f"LIMIT {int(limit)};"
    )


def recall_context_summary(query: str, domain: str = '', limit: int = 5) -> str:
    """유사 경험을 사람이 읽을 수 있는 요약 텍스트로 반환한다.

    하네스 훅에서 컨텍스트에 주입할 때 사용.
    """
    results = recall_similar_experience(query, domain=domain, limit=limit)
    if not results:
        return ""

    # [자가치유 피드백 루프] v1 폴백 회상도 참조 카운트 증가 — recall-smart가 모델
    #   미로드로 fallback을 반환할 때 이 경로가 실행되므로, 여기서 bump 안 하면
    #   agent_experience.ref_count가 영영 0(계측 project_heal_metrics로 발견).
    try:
        from src.pg_vector_search import bump_reference
        _ids = [r.get('id') for r in results if r.get('id')]
        if _ids:
            bump_reference('agent_experience', _ids)
    except Exception:
        pass

    lines = [f"[경험 회상] '{query}'와 관련된 과거 작업 {len(results)}건:"]
    for i, r in enumerate(results, 1):
        outcome_icon = '✅' if r['outcome'] == 'success' else '❌' if r['outcome'] == 'fail' else '⚠️'
        lines.append(
            f"  {i}. [{r['task_type']}] {outcome_icon} {r['description'][:60]} "
            f"(+{r['xp_earned']}xp, {r['domain']}, by {r['agent_id']})"
        )
    return "\n".join(lines)

# ── pg_logs 활동 기록 ────────────────────────────────────────────────────────

def insert_pg_log(agent: str, task: str = '', status: str = 'success',
                  terminal_id: str = '', project_id: str = '',
                  metadata: dict | None = None) -> bool:
    """에이전트 활동을 pg_logs 테이블에 기록한다.

    서버 API 호출, heartbeat 갱신, 태스크 상태 변경 등
    모든 에이전트 활동의 영구 로그를 남긴다.
    """
    project_id = assert_project_id(project_id, 'insert_pg_log')
    import json as _json
    meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
    return execute(
        f"INSERT INTO pg_logs (agent, task, status, terminal_id, project_id, metadata) "
        f"VALUES ({_sql_text(agent)}, {_sql_text(task)}, {_sql_text(status)}, "
        f"{_sql_text(terminal_id)}, {_sql_text(project_id)}, "
        f"{_sql_text(meta_json)}::jsonb);"
    )
