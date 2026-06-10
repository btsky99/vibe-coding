# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_incidents.py
# 📝 설명: 사고 장부(incident_ledger) — 고친 에러의 시그니처/근본원인/수정법 기록 +
#          재발 감지 검색 + 재발률 통계(북극성 지표). 자가 치유 2.0 ① (Task 9).
# 🕒 변경 이력:
# [2026-06-10] Claude — 신설 (brainstorm 승인안 ①)
#   - [WHY] 시그니처 정규화: 같은 버그가 다른 경로/줄번호/시각으로 나타나도
#     동일 사고로 묶기 위해 가변 토큰을 제거 후 해시. 과하게 지우면(숫자 전부 등)
#     다른 에러가 한 시그니처로 합쳐지므로 보수적으로만 제거한다.
#   - [제약] search_incidents는 훅(단명 프로세스)에서 호출 — 임베딩 모델 사용 금지.
#     정확 매칭 → pg_trgm 유사도 순. 벡터 검색은 서버 recall-smart 경로만.
#   - [불변식] recurrence_count는 "같은 시그니처가 다시 record됨" = 재발의 증거.
#     조회(search)는 절대 카운트를 올리지 않는다 — 재발률 지표 오염 방지.
# ────────────────────────────────────────────────────────────────────────────
import hashlib
import json
import re

from infra.project_context import assert_project_id
from src.pg_base import query_rows, execute, _sql_text

# 정규화 패턴 — 순서 중요: 타임스탬프를 숫자 일반화보다 먼저 처리
_NORM_PATTERNS = [
    (re.compile(r'\x1b\[[0-9;]*m'), ''),                                  # ANSI 색상
    (re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.\d+:Z]*'), '<TS>'),  # ISO 시각
    (re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'), '<UUID>'),
    (re.compile(r'0x[0-9a-fA-F]+'), '<ADDR>'),                            # 메모리 주소
    (re.compile(r'[A-Za-z]:[\\/][^\s:"\',)\]]+'), '<PATH>'),              # Windows 경로
    (re.compile(r'(?<![\w.])/[\w.\-]+(?:/[\w.\-]+)+'), '<PATH>'),         # Unix 경로
    (re.compile(r'\bline \d+\b'), 'line <N>'),                            # 줄 번호
    (re.compile(r':\d+(?=[\s:,)\]]|$)'), ':<N>'),                         # :포트/:줄번호
    (re.compile(r'\b\d{4,}\b'), '<N>'),                                   # 4자리+ 숫자 (PID 등)
    (re.compile(r'\s+'), ' '),                                            # 공백 정규화
]


def normalize_signature(error_text: str) -> str:
    """에러 텍스트 → 안정 시그니처 해시(16자). 빈 입력은 빈 문자열."""
    text = (error_text or '').strip()
    if not text:
        return ''
    for pattern, repl in _NORM_PATTERNS:
        text = pattern.sub(repl, text)
    # [WHY] 앞 1000자만 — Traceback 머리(원인 체인)가 변별력의 대부분.
    # 꼬리는 재시도 로그 등 가변 노이즈가 섞이는 경우가 많다.
    text = text.strip()[:1000].lower()
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def record_incident(error_text: str, root_cause: str, fix_description: str,
                    fix_commit: str = '', files: list | None = None,
                    project_id: str = '') -> dict:
    """수정 완료된 사고를 장부에 기록. 동일 시그니처면 재발 카운트 증가 + 수정법 갱신.

    호출 시점: 에러를 '고친 직후' (vibe-debug 마지막 단계 / incident.py record).
    반환: {'signature', 'recurrence_count', 'recurred'(bool)}
    """
    project_id = assert_project_id(project_id, 'record_incident')
    sig = normalize_signature(error_text)
    if not sig:
        return {}
    files_json = _sql_text(json.dumps(files or [], ensure_ascii=False)) + '::jsonb'
    # [WHY] COALESCE(NULLIF(...)) — 재기록 시 빈 값으로 기존 원인/수정법을 덮지 않음
    ok = execute(f"""
        INSERT INTO incident_ledger
            (project_id, error_signature, error_text, root_cause,
             fix_description, fix_commit, files)
        VALUES ({_sql_text(project_id)}, {_sql_text(sig)},
                {_sql_text(error_text[:2000])}, {_sql_text(root_cause[:1000])},
                {_sql_text(fix_description[:1000])}, {_sql_text(fix_commit[:100])},
                {files_json})
        ON CONFLICT (project_id, error_signature) DO UPDATE SET
            recurrence_count = incident_ledger.recurrence_count + 1,
            last_seen_at = NOW(),
            root_cause = COALESCE(NULLIF(EXCLUDED.root_cause, ''), incident_ledger.root_cause),
            fix_description = COALESCE(NULLIF(EXCLUDED.fix_description, ''), incident_ledger.fix_description),
            fix_commit = COALESCE(NULLIF(EXCLUDED.fix_commit, ''), incident_ledger.fix_commit),
            embedding = NULL;
    """)
    # embedding=NULL 리셋 — 수정법이 갱신됐으니 백필 데몬이 재임베딩
    if not ok:
        return {}
    rows = query_rows(
        f"SELECT recurrence_count FROM incident_ledger "
        f"WHERE project_id = {_sql_text(project_id)} AND error_signature = {_sql_text(sig)};"
    )
    count = int(rows[0]['recurrence_count']) if rows else 1
    return {'signature': sig, 'recurrence_count': count, 'recurred': count > 1}


def search_incidents(error_text: str, project_id: str = '', limit: int = 3) -> list[dict]:
    """에러 텍스트로 과거 사고 검색 — ① 시그니처 정확 매칭 ② trgm 유사도 폴백.

    [제약] 조회 전용 — recurrence_count 불변 (불변식 참고).
    """
    sig = normalize_signature(error_text)
    if not sig:
        return []
    proj_filter = f"AND project_id = {_sql_text(project_id)}" if project_id else ""
    exact = query_rows(f"""
        SELECT id, error_signature, LEFT(error_text, 150) AS error_text,
               root_cause, fix_description, fix_commit, files,
               recurrence_count, last_seen_at, 1.0 AS match_score
        FROM incident_ledger
        WHERE error_signature = {_sql_text(sig)} {proj_filter}
        LIMIT {int(limit)};
    """)
    if exact:
        return exact
    # trgm 유사도 폴백 — 시그니처가 다르게 떨어진 변종 사고 (임계 0.3 = pg_trgm 관례)
    sample = _sql_text((error_text or '')[:500])
    return query_rows(f"""
        SELECT id, error_signature, LEFT(error_text, 150) AS error_text,
               root_cause, fix_description, fix_commit, files,
               recurrence_count, last_seen_at,
               similarity(LEFT(error_text, 500), {sample}) AS match_score
        FROM incident_ledger
        WHERE similarity(LEFT(error_text, 500), {sample}) > 0.3 {proj_filter}
        ORDER BY match_score DESC
        LIMIT {int(limit)};
    """)


def incident_stats(project_id: str = '', weeks: int = 8) -> dict:
    """북극성 지표 — 동일 에러 시그니처 재발률 + 주별 추이 + 최다 재발 Top5.

    재발률 = 재발 사고(recurrence_count > 1) / 전체 사고.
    이 숫자가 떨어지면 '고친 게 다시 안 터진다' = 삽질 감소의 객관적 증거.
    """
    proj_filter = f"WHERE project_id = {_sql_text(project_id)}" if project_id else ""
    totals = query_rows(f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE recurrence_count > 1) AS recurred,
               COALESCE(SUM(recurrence_count) - COUNT(*), 0) AS total_recurrences
        FROM incident_ledger {proj_filter};
    """)
    weekly = query_rows(f"""
        SELECT date_trunc('week', last_seen_at)::date AS week,
               COUNT(*) AS incidents,
               COUNT(*) FILTER (WHERE recurrence_count > 1) AS recurred
        FROM incident_ledger {proj_filter}
        GROUP BY week ORDER BY week DESC LIMIT {int(weeks)};
    """)
    top = query_rows(f"""
        SELECT error_signature, LEFT(error_text, 100) AS error_text,
               recurrence_count, root_cause
        FROM incident_ledger {proj_filter}
        ORDER BY recurrence_count DESC, last_seen_at DESC LIMIT 5;
    """)
    t = totals[0] if totals else {}
    total = int(t.get('total') or 0)
    recurred = int(t.get('recurred') or 0)
    return {
        'total_incidents': total,
        'recurred_incidents': recurred,
        'recurrence_rate': round(recurred / total, 3) if total else 0.0,
        'total_recurrences': int(t.get('total_recurrences') or 0),
        'weekly': weekly,
        'top_recurring': top,
    }


def format_incident_briefing(incidents: list[dict]) -> str:
    """검색 결과 → 훅 주입 텍스트. 빈 리스트면 빈 문자열(주입 생략)."""
    if not incidents:
        return ''
    lines = [f"⚡ [사고 장부] 과거 동일/유사 사고 {len(incidents)}건 — 같은 삽질 금지:"]
    for inc in incidents:
        score = float(inc.get('match_score') or 0)
        kind = '동일' if score >= 0.999 else f'유사 {score:.2f}'
        # recurrence_count=1은 최초 수정(재발 0회) — count-1이 실제 재발 횟수
        recurred = max(0, int(inc.get('recurrence_count', 1)) - 1)
        tag = f'{kind}|재발 {recurred}회' if recurred else kind
        lines.append(f"  [{tag}] {inc.get('error_text', '')}")
        if inc.get('root_cause'):
            lines.append(f"    원인: {inc['root_cause'][:150]}")
        if inc.get('fix_description'):
            lines.append(f"    수정법: {inc['fix_description'][:150]}")
        if inc.get('fix_commit'):
            lines.append(f"    커밋: {inc['fix_commit']}")
    return '\n'.join(lines)
