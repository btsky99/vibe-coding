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
    try:
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (ConnectionError, BrokenPipeError):
        # [과거사고 2026-08-01] 클라이언트(WebView UI)가 응답을 기다리다 fetch를 취소하면
        #   여기 write가 ConnectionAbortedError(WinError 10053)로 터진다. 이건 정상 상황인데,
        #   예외가 핸들러 밖으로 나가면 BaseHTTPRequestHandler가 스택 전체를 stderr에 찍는다.
        #   UI 렌더러가 메모리 압박으로 느려질수록 취소가 늘어 → 48시간에 traceback 7,200건,
        #   server.log 61MB → 로그 쓰기 I/O가 서버를 더 느리게 만드는 악순환이 됐다.
        # [WHY 흡수] 상대가 이미 끊은 소켓이라 재시도/에러응답 모두 불가능. 호출자가 할 수 있는
        #   일이 없으므로 조용히 종료한다. ConnectionError 계열만 좁게 잡아 진짜 버그(직렬화
        #   실패 등)는 그대로 올라가게 둔다.
        pass


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
