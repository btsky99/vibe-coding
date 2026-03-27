"""
FILE: api/setup_api.py
DESCRIPTION: Setup Doctor API — 초기 설정 진단 상태를 대시보드에 제공.
             GET /api/setup/status → 5가지 항목의 진단 결과 반환.

REVISION HISTORY:
- 2026-03-27 Claude: 최초 작성. setup_doctor.py 연동.
"""

import json
import sys
from pathlib import Path

# setup_doctor 모듈 import를 위한 경로 설정
_BASE_DIR = Path(__file__).resolve().parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))


def handle_get(handler, path: str, params: dict = None, **kwargs):
    """GET /api/setup/status 핸들러.

    setup_doctor.run_all()을 실행하여 진단 결과를 JSON으로 반환한다.
    """
    if path == '/api/setup/status':
        try:
            from setup_doctor import run_all
            result = run_all()
            body = json.dumps(result, ensure_ascii=False).encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/json; charset=utf-8')
            handler.send_header('Content-Length', str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
        except Exception as e:
            error_body = json.dumps({
                "ready": False,
                "error": str(e),
                "checks": {}
            }).encode('utf-8')
            handler.send_response(500)
            handler.send_header('Content-Type', 'application/json; charset=utf-8')
            handler.send_header('Content-Length', str(len(error_body)))
            handler.end_headers()
            handler.wfile.write(error_body)
    else:
        handler.send_response(404)
        handler.end_headers()
