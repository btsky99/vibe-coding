"""
FILE: api/heal_api.py
DESCRIPTION: 자가치유 계측 API — GET /api/heal/metrics. src.heal_metrics.compute_heal_metrics를
             호출해 4장치 지표 JSON을 반환한다. 계산 로직 없음(단일 소스 = heal_metrics). 읽기 전용.

REVISION HISTORY:
- 2026-07-05 Claude: 신규 — 자가치유 계측 Task 3. server.py do_GET에서 위임.
"""
from __future__ import annotations

import json


def handle_get(handler, project_id: str = "") -> None:
    """GET /api/heal/metrics — 자가치유 4장치 계측 JSON.
    [제약] 계산은 heal_metrics 단일 소스 위임. 오류 시 500 + error 필드(무음 실패 방지).
    """
    try:
        from src.heal_metrics import compute_heal_metrics
        payload = compute_heal_metrics(project_id)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status = 200
    except Exception as e:
        body = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
        status = 500
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json;charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(body)
