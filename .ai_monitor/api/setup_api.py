"""
FILE: api/setup_api.py
DESCRIPTION: Setup Doctor API — 초기 설정 진단 상태를 대시보드에 제공.
             GET /api/setup/status → 5가지 항목의 진단 결과 반환.

REVISION HISTORY:
- 2026-08-14 Claude: 자동 설치를 무창 + 총 3회 상한으로 제한 — 도구 하나가 계속 안 잡히면
                     앱을 켤 때마다 설치 콘솔이 뜨고 npm이 다시 돌던 문제. 수동(manual)은 무제한.
- 2026-07-29 Codex: Expose per-tool installation state for the first-run progress UI.
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

# [WHY 상한] 쿨다운은 **프로세스 메모리**에만 있어 앱을 껐다 켜면 0으로 돌아간다. 그래서
#   도구 하나가 끝내 안 잡히는 PC(예: agy 미설치를 사용자가 원함)에서는 실행할 때마다
#   설치가 다시 돌았다 — 예전엔 그때마다 cmd 창까지 떴다. 시도 횟수를 디스크에 남겨
#   '설치는 됐는데 계속 다시 뜬다'를 끊는다. 사용자가 배너 버튼을 누르는 수동 경로는
#   이 상한을 받지 않는다(사람이 원해서 누른 것).
_AUTO_INSTALL_MAX_ATTEMPTS = 3


def _auto_install_state_path():
    from infra import runtime
    return runtime.app_data_dir() / "setup_auto_install.json"


def _read_auto_install_attempts() -> int:
    """지금까지의 자동(비클릭) 설치 시도 횟수. 파일이 깨졌으면 0으로 본다."""
    try:
        raw = json.loads(_auto_install_state_path().read_text(encoding="utf-8"))
        return int(raw.get("attempts", 0))
    except Exception:
        return 0


def _record_auto_install_attempt(targets: list[str]) -> None:
    """시도 횟수를 증가시켜 다음 실행에서도 보이게 한다(실패해도 앱 동작엔 영향 없음)."""
    path = _auto_install_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "attempts": _read_auto_install_attempts() + 1,
            "last_targets": targets,
            "last_started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 기록 실패는 치명적이지 않다 — 최악이라도 예전과 같은 동작(재시도)

def handle_get(handler, path: str, params: dict = None, **kwargs):
    """GET /api/setup/status 핸들러.

    setup_doctor.run_all()을 실행하여 진단 결과를 JSON으로 반환한다.
    """
    if path == '/api/setup/status':
        try:
            from setup_doctor import run_all
            from api import tools_api

            result = run_all()
            # [2026-08-15] obsidian 편입 — 지식 창고(wiki/)를 사람이 읽는 창이라
            #   CLI·DB 와 같은 기본 설치팩으로 취급한다(사용자 결정).
            core_ids = ("nodejs", "claude", "codex", "antigravity", "obsidian")
            tool_status = {
                item["id"]: {
                    "id": item["id"],
                    "name": item["name"],
                    "installed": item["installed"],
                    "version": item.get("version"),
                }
                for item in tools_api._get_all_status()["tools"]
                if item["id"] in core_ids
            }
            result["toolchain"] = [
                tool_status.get(tool_id, {
                    "id": tool_id,
                    "name": tool_id,
                    "installed": False,
                    "version": None,
                })
                for tool_id in core_ids
            ]
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
    """누락된 핵심 실행 도구를 설치한다.

    Node.js가 없으면 npm 기반 CLI보다 먼저 Node.js만 설치한다. Node 설치 후 다음 앱
    실행에서 CLI 설치가 자동으로 이어지므로 PATH 갱신 전 CLI 설치가 실패하지 않는다.

    [경로 2종] body의 manual=true는 배너 버튼 클릭(사람) — 콘솔 창을 열고 횟수 제한 없음.
      manual 없음은 배너가 앱 시작 시 자동으로 부르는 경로 — 무창이고 총 3회까지만.
      이 구분이 없으면 도구 하나가 안 잡히는 PC에서 실행할 때마다 설치 창이 떴다.
    """
    if path != "/api/setup/auto-install":
        return False

    from api import tools_api

    manual = bool((data or {}).get("manual"))

    statuses = {
        item["id"]: item
        for item in tools_api._get_all_status()["tools"]
        if item["id"] in {"nodejs", "claude", "codex", "antigravity", "obsidian"}
    }
    targets = [
        tool_id
        for tool_id in ("nodejs", "claude", "codex", "antigravity", "obsidian")
        if not statuses.get(tool_id, {}).get("installed", False)
    ]

    global _AUTO_INSTALL_LAST_STARTED
    attempts = 0 if manual else _read_auto_install_attempts()
    if not targets:
        result = {"status": "idle", "message": "필수 AI 도구가 이미 설치되어 있습니다."}
    elif attempts >= _AUTO_INSTALL_MAX_ATTEMPTS:
        result = {
            "status": "exhausted",
            "message": (
                f"자동 설치를 {attempts}회 시도했지만 {', '.join(targets)}이(가) 계속 감지되지 "
                "않습니다. 더 이상 자동으로 실행하지 않습니다 — 배너의 설치 버튼을 눌러주세요."
            ),
        }
    else:
        with _AUTO_INSTALL_LOCK:
            now = time.monotonic()
            if now - _AUTO_INSTALL_LAST_STARTED < _AUTO_INSTALL_COOLDOWN_SECONDS:
                result = {
                    "status": "running",
                    "message": "필수 AI 도구 설치가 이미 진행 중입니다.",
                }
            else:
                result = tools_api.launch_ai_toolchain_installer(visible=manual)
                if result.get("status") == "success":
                    _AUTO_INSTALL_LAST_STARTED = now
                    if not manual:
                        _record_auto_install_attempt(targets)
    launched = targets if result.get("status") == "success" else []

    body = json.dumps({
        "status": "started" if launched else result.get("status", "error"),
        "launched": launched,
        "skipped": [] if launched else targets,
        "attempts": attempts + (1 if launched and not manual else 0),
        "max_attempts": _AUTO_INSTALL_MAX_ATTEMPTS,
        "message": result.get("message", ""),
    }, ensure_ascii=False).encode("utf-8")
    response_status = (
        202 if launched
        else (200 if result.get("status") in {"idle", "running", "exhausted"} else 500)
    )
    handler.send_response(response_status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True
