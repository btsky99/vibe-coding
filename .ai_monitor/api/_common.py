# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: api/_common.py
# 📝 설명: API 핸들러 공용 헬퍼. 8개 도메인 모듈에 복붙돼 있던 _json_response(8중복)와
#          _read_body(4중복)를 단일 출처로 통합한다. 각 모듈은
#          `from api._common import json_response as _json_response` 로 재노출해
#          기존 호출부(_json_response/_read_body)를 그대로 유지한다.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-07-18] Claude: 중복 헬퍼 통합 신설.
#   - [WHY] 사본이 미묘하게 달라(experience/vibe/zettel/codegraph만 default=str,
#     tools_api만 Content-Length) 유지보수 시 한쪽만 고치는 사고 위험. 상위집합으로 통합.
#   - [호환성] default=str은 원래 TypeError로 죽던 datetime 등 입력에만 관여 →
#     정상 호출은 결과 동일. Content-Length 명시도 HTTP 정확성 개선이라 회귀 없음.
#   - [불변식] handler는 _cors_origin()을 제공하는 BaseHTTPRequestHandler 파생 전제.
# ------------------------------------------------------------------------
"""
import json


def json_response(handler, data, status: int = 200) -> None:
    """JSON 응답 공통 헬퍼 — ensure_ascii=False(한글 보존) + default=str(datetime 등 방어).

    [WHY] Content-Length를 명시해 HTTP keep-alive에서 응답 경계가 모호해지지 않게 한다.
    """
    body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler) -> dict:
    """POST/DELETE 요청 본문(JSON)을 파싱해 dict 반환. 실패 시 {}.

    [WHY] pty_api 사본만 malformed JSON에서 예외를 던져 미처리 시 500 위험 →
    방어형(예외 삼키고 {})으로 통일. 정상 본문은 결과 동일.
    """
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length > 0:
            raw = handler.rfile.read(content_length).decode('utf-8')
            return json.loads(raw)
    except Exception:
        pass
    return {}
