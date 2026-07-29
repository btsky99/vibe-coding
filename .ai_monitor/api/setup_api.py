"""
FILE: api/setup_api.py
DESCRIPTION: Setup Doctor API — 초기 설정 진단 상태를 대시보드에 제공.
             GET /api/setup/status → 5가지 항목의 진단 결과 반환.

REVISION HISTORY:
- 2026-07-29 Codex: Suppress duplicate installer windows without blocking later retries.
- 2026-07-29 Codex: Allow retries and always run the complete prerequisite-first AI chain.
- 2026-07-29 Codex: Run one sequential installer for every missing core AI dependency.
- 2026-07-28 Codex: Add first-run automatic installation for missing Node.js and AI CLIs.
- 2026-03-27 Claude: 최초 작성. setup_doctor.py 연동.
"""

import json
import sys
import threading
import time
from pathlib import Path

# setup_doctor 모듈 import를 위한 경로 설정
_BASE_DIR = Path(__file__).resolve().parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

_AUTO_INSTALL_LOCK = threading.Lock()
_AUTO_INSTALL_LAST_STARTED = 0.0
_AUTO_INSTALL_COOLDOWN_SECONDS = 120.0

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


def handle_post(handler, path: str, data: dict | None = None, **kwargs) -> bool:
    """누락된 핵심 실행 도구를 사용자 클릭 없이 설치한다.

    Node.js가 없으면 npm 기반 CLI보다 먼저 Node.js만 설치한다. Node 설치 후 다음 앱
    실행에서 CLI 설치가 자동으로 이어지므로 PATH 갱신 전 CLI 설치가 실패하지 않는다.
    """
    if path != "/api/setup/auto-install":
        return False

    from api import tools_api

    statuses = {
        item["id"]: item
        for item in tools_api._get_all_status()["tools"]
        if item["id"] in {"nodejs", "claude", "codex", "antigravity"}
    }
    targets = [
        tool_id
        for tool_id in ("nodejs", "claude", "codex", "antigravity")
        if not statuses.get(tool_id, {}).get("installed", False)
    ]

    global _AUTO_INSTALL_LAST_STARTED
    if not targets:
        result = {"status": "idle", "message": "필수 AI 도구가 이미 설치되어 있습니다."}
    else:
        with _AUTO_INSTALL_LOCK:
            now = time.monotonic()
            if now - _AUTO_INSTALL_LAST_STARTED < _AUTO_INSTALL_COOLDOWN_SECONDS:
                result = {
                    "status": "running",
                    "message": "필수 AI 도구 설치가 이미 진행 중입니다.",
                }
            else:
                result = tools_api.launch_ai_toolchain_installer()
                if result.get("status") == "success":
                    _AUTO_INSTALL_LAST_STARTED = now
    launched = targets if result.get("status") == "success" else []

    body = json.dumps({
        "status": "started" if launched else result.get("status", "error"),
        "launched": launched,
        "skipped": [],
        "message": result.get("message", ""),
    }, ensure_ascii=False).encode("utf-8")
    response_status = (
        202 if launched
        else (200 if result.get("status") in {"idle", "running"} else 500)
    )
    handler.send_response(response_status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True
