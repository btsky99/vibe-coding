"""
FILE: src/heal_metrics.py
DESCRIPTION: 자가치유 계측 단일 소스 — 4장치(회상v2/사고장부/체크포인트/교훈)가 실제로 삽질을
             줄이는지 재는 지표를 DB에서 계산한다. CLI(heal_report.py)·API(heal_api.py)·패널이
             모두 이 함수를 호출한다(중복 금지). 읽기 전용 — 어떤 테이블도 수정하지 않는다.

  [이중계측 원칙] 장치마다 '성과 지표'와 '기록 성실도(입력 커버리지)'를 함께 낸다.
    예: 사고 재발률 0%라도 표본 15건이면 verdict='🟡 표본 부족'(성공 아님) — 이게 계측의 존재 이유.

REVISION HISTORY:
- 2026-07-05 Claude: 신규 — 자가치유 계측 Task 1. 스키마 실검증 반영
  (참조 카운트 컬럼: zettel=access_count / hive_memory·agent_experience=ref_count 로 분기).
  query_rows가 파라미터 바인딩 미지원 → project_id는 작은따옴표 이스케이프 후 인라인.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime

from src.pg_base import query_rows

# 표본 충분 임계값 — 이보다 적으면 성과 지표(재발률 등)를 '판단 보류'로 처리.
_MIN_SAMPLE_INCIDENTS = 30


def _pid_and(project_id: str) -> str:
    """project_id 필터를 ' AND project_id = ...' 조각으로. 빈 값이면 빈 문자열(전체 집계).
    [보안] query_rows가 파라미터 바인딩을 지원하지 않으므로 작은따옴표 이스케이프로 주입 방어.
      project_id는 내부 슬러그(영숫자/하이픈)라 위험은 낮으나 방어를 명시한다.
    """
    if not project_id:
        return ""
    safe = str(project_id).replace("'", "''")
    return f" AND project_id = '{safe}'"


def _one(sql: str) -> dict:
    rows = query_rows(sql)
    return rows[0] if rows else {}


def _recall_metrics(project_id: str) -> dict:
    """회상 v2: 지식 테이블별 임베딩 커버리지 + 참조율(access_count/ref_count).
    [불변식] 참조 컬럼명이 테이블마다 다름 — zettel=access_count, 나머지=ref_count.
    """
    pid = _pid_and(project_id)
    specs = [
        # (표시명, 테이블, 참조컬럼, 추가필터)
        ("zettel_notes", "zettel_notes", "access_count", " AND archived = false"),
        ("hive_memory", "hive_memory", "ref_count", ""),
        ("agent_experience", "agent_experience", "ref_count", ""),
    ]
    tables = {}
    tot = emb = refd = refsum = 0
    for name, tbl, refcol, extra in specs:
        r = _one(
            f"SELECT count(*) AS total, "
            f"count(*) FILTER (WHERE embedding IS NOT NULL) AS emb, "
            f"count(*) FILTER (WHERE {refcol} > 0) AS refd, "
            f"coalesce(sum({refcol}), 0) AS refsum "
            f"FROM {tbl} WHERE 1=1{extra}{pid}"
        )
        t = int(r.get("total", 0) or 0)
        e = int(r.get("emb", 0) or 0)
        rd = int(r.get("refd", 0) or 0)
        rs = int(r.get("refsum", 0) or 0)
        tables[name] = {
            "total": t, "embedded": e,
            "embed_pct": round(100 * e / t, 1) if t else 0.0,
            "referenced": rd, "ref_sum": rs,
            "ref_pct": round(100 * rd / t, 1) if t else 0.0,
        }
        tot += t; emb += e; refd += rd; refsum += rs
    embed_cov = round(100 * emb / tot, 1) if tot else 0.0
    ref_ratio = round(100 * refd / tot, 1) if tot else 0.0
    # verdict: 임베딩 커버리지(성과 전제) + 참조율(실효성) 이중 판정
    if embed_cov < 60 or ref_ratio < 5:
        verdict = "🔴"
    elif embed_cov < 80 or ref_ratio < 20:
        verdict = "🟡"
    else:
        verdict = "🟢"
    return {
        "tables": tables,
        "total_knowledge": tot, "embed_coverage_pct": embed_cov,
        "referenced_pct": ref_ratio, "ref_sum": refsum,
        "verdict": verdict,
        "note": "참조율=access_count/ref_count>0 비율. 낮으면 '쌓기만 하고 안 쓰임' 사각지대.",
    }


def _incident_metrics(project_id: str) -> dict:
    """사고 장부: 재발률(북극성) + 표본 충분도(이중계측)."""
    pid = _pid_and(project_id)
    r = _one(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE recurrence_count > 1) AS recurred, "
        "coalesce(sum(GREATEST(recurrence_count - 1, 0)), 0) AS recur_events "
        f"FROM incident_ledger WHERE 1=1{pid}"
    )
    total = int(r.get("total", 0) or 0)
    recurred = int(r.get("recurred", 0) or 0)
    recur_events = int(r.get("recur_events", 0) or 0)
    rate = round(100 * recurred / total, 1) if total else 0.0
    sample_ok = total >= _MIN_SAMPLE_INCIDENTS
    weekly = query_rows(
        "SELECT to_char(date_trunc('week', created_at), 'YYYY-MM-DD') AS week, "
        "count(*) AS n, count(*) FILTER (WHERE recurrence_count > 1) AS recur "
        f"FROM incident_ledger WHERE created_at >= now() - interval '8 weeks'{pid} "
        "GROUP BY 1 ORDER BY 1 DESC"
    )
    if not sample_ok:
        verdict = "🟡"  # 표본 부족 — 재발률 판단 보류
    elif rate > 20:
        verdict = "🔴"
    else:
        verdict = "🟢"
    return {
        "total": total, "recurred": recurred, "recur_events": recur_events,
        "recurrence_rate_pct": rate, "sample_ok": sample_ok,
        "min_sample": _MIN_SAMPLE_INCIDENTS,
        "weekly": [{"week": w.get("week"), "n": int(w.get("n", 0) or 0),
                    "recur": int(w.get("recur", 0) or 0)} for w in weekly],
        "verdict": verdict,
        "note": ("표본 부족 — 재발률 0%가 성공인지 미측정인지 불명. 사고 기록을 더 쌓아야 판단 가능."
                 if not sample_ok else "재발률=재발사고/전체. 북극성 지표(낮을수록 삽질 감소)."),
    }


def _checkpoint_metrics(project_id: str) -> dict:
    """체크포인트: 세션 연속성 인프라 활성도(기록 성실도 위주)."""
    pid = _pid_and(project_id)
    r = _one(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE updated_at >= now() - interval '7 days') AS recent7, "
        "count(DISTINCT agent_id) AS agents "
        f"FROM active_session_context WHERE 1=1{pid}"
    )
    total = int(r.get("total", 0) or 0)
    recent7 = int(r.get("recent7", 0) or 0)
    agents = int(r.get("agents", 0) or 0)
    verdict = "🟢" if recent7 > 0 else ("🟡" if total > 0 else "🔴")
    return {
        "total": total, "recent_7d": recent7, "distinct_agents": agents,
        "verdict": verdict,
        "note": "체크포인트=intent/decisions/next_step 저장. 최근 7일 0건이면 이어받기 인프라 유휴.",
    }


def _lesson_metrics() -> dict:
    """교훈 증류: lessons.md 승인 항목 수(파일 파싱 — DB 아님).
    [설계] 승인 게이트라 lesson.py approve로만 추가됨. 마지막 '---' 이후 항목 라인 카운트.
    """
    approved = 0
    path = None
    for cand in (Path(__file__).resolve().parents[2] / ".claude" / "rules" / "lessons.md",):
        if cand.exists():
            path = cand
            break
    if path:
        text = path.read_text(encoding="utf-8")
        # 마지막 '---' 구분선 이후를 교훈 본문으로 간주 (상단은 헤더/운영규칙/HTML주석)
        tail = text.rsplit("\n---", 1)[-1]
        for line in tail.splitlines():
            s = line.strip()
            if s.startswith("### ") or s.startswith("- ") or (s[:2].rstrip(".").isdigit() if s else False):
                approved += 1
    verdict = "🔴" if approved == 0 else ("🟡" if approved < 3 else "🟢")
    return {
        "approved": approved, "source": str(path) if path else "(없음)",
        "verdict": verdict,
        "note": "교훈 증류 산출물. 0건이면 propose→approve 파이프가 아직 결과를 못 냄.",
    }


def compute_heal_metrics(project_id: str = "") -> dict:
    """자가치유 4장치 계측 — 단일 진실원. 읽기 전용.
    project_id='' 이면 전체(모든 프로젝트) 집계, 지정 시 해당 프로젝트로 필터.
    """
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_id": project_id or "(전체)",
        "recall": _recall_metrics(project_id),
        "incidents": _incident_metrics(project_id),
        "checkpoints": _checkpoint_metrics(project_id),
        "lessons": _lesson_metrics(),
    }
