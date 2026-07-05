"""
FILE: api/screenshot_api.py
DESCRIPTION: 스크린샷 멀티모달 분석 API — POST /api/screenshot/analyze.
             base64 이미지를 scripts/screenshot_analyzer.py의 Vision 파이프라인으로 넘겨
             버그 후보를 감지하고 태스크로 등록한다. server.py do_POST 인라인 블록을 분리(Phase 2 R8).

REVISION HISTORY:
- 2026-07-06 Claude: server.py do_POST '/api/screenshot/analyze' 인라인 블록 verbatim 분리(R8).
  SCRIPTS_DIR(설치본은 None)/PROJECT_ID는 파라미터 주입. 동적 import(screenshot_analyzer)는
  sys.path 삽입 후 수행 — SCRIPTS_DIR가 None이면(설치본) 분석 불가 응답을 반환한다.
"""
from __future__ import annotations

import json
import sys


def analyze(handler, SCRIPTS_DIR, PROJECT_ID) -> None:
    """POST /api/screenshot/analyze — 멀티모달 버그 감지.

    [제약] SCRIPTS_DIR는 개발 실행 시에만 존재(설치본은 None) — None이면 기능 불가 응답.
      screenshot_analyzer는 scripts/에만 있으므로 sys.path에 넣고 동적 import 한다.
    [원본보존] 모든 실패는 200 + {'error': ...}로 반환(프론트가 에러 문자열을 표시).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))
        image_b64 = data.get('image', '')
        if not image_b64:
            handler.wfile.write(json.dumps({'error': 'image (base64) is required'}).encode('utf-8'))
        elif not SCRIPTS_DIR:
            handler.wfile.write(json.dumps({'error': '설치 버전에서는 스크린샷 분석 기능을 사용할 수 없습니다'}).encode('utf-8'))
        else:
            scripts_dir = str(SCRIPTS_DIR)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from screenshot_analyzer import analyze_and_create_tasks
            result = analyze_and_create_tasks(image_b64, project_id=PROJECT_ID)
            handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
