"""
FILE: api/tools_api.py
DESCRIPTION: AI 도구 CLI 설치 관리 API.
             대시보드에서 gh CLI, Playwright CLI, Codex CLI 등
             필요한 개발 도구의 설치 상태를 확인하고 원클릭 설치를 제공한다.

             GET  /api/tools/status   — 전체 도구 설치 상태 목록 반환
             POST /api/tools/install  — 특정 도구 설치 실행 (새 콘솔 창)

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — 도구 설치 통합 API
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── 경로 설정 ──────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent.parent  # .ai_monitor/
_PROJECT_ROOT = _BASE_DIR.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"


# ═══════════════════════════════════════════════════════════════════════
#  도구 레지스트리 — 새 도구 추가 시 여기에 항목 추가
# ═══════════════════════════════════════════════════════════════════════

# 각 도구 정의: 검출 방법, 설치 스크립트, 설명 등
TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "gh",
        "name": "GitHub CLI",
        "description": "GitHub 저장소 관리, PR, 이슈, 인증 등을 터미널에서 수행",
        "check_commands": [["gh", "--version"]],
        "check_paths": [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "GitHub CLI", "gh.exe"),
        ],
        "install_script": "install_gh_cli.py",
        "install_url": "https://cli.github.com/",
        "category": "git",
    },
    {
        "id": "playwright",
        "name": "Playwright CLI",
        "description": "브라우저 자동화 및 E2E 테스트 도구 (Chromium/Firefox/WebKit)",
        "check_commands": [
            [sys.executable, "-m", "playwright", "--version"],
            ["playwright", "--version"],
        ],
        "check_paths": [],
        "install_script": "install_playwright_cli.py",
        "install_url": "https://playwright.dev/python/",
        "category": "testing",
    },
    {
        "id": "codex",
        "name": "Codex CLI",
        "description": "OpenAI Codex 기반 AI 코딩 에이전트 (npm 패키지)",
        "check_commands": [["codex", "--version"], ["npx", "codex", "--version"]],
        "check_paths": [],
        "install_script": "install_codex.py",
        "install_url": "https://github.com/openai/codex",
        "category": "ai-agent",
    },
    {
        "id": "claude",
        "name": "Claude CLI",
        "description": "Anthropic Claude Code — AI 코딩 에이전트",
        "check_commands": [["claude", "--version"]],
        "check_paths": [],
        "install_script": None,  # npm install -g @anthropic-ai/claude-code
        "install_url": "https://docs.anthropic.com/en/docs/claude-code",
        "install_hint": "npm install -g @anthropic-ai/claude-code",
        "category": "ai-agent",
    },
    {
        "id": "gemini",
        "name": "Gemini CLI",
        "description": "Google Gemini AI 코딩 에이전트",
        "check_commands": [["gemini", "--version"]],
        "check_paths": [],
        "install_script": None,  # npm install -g @anthropic-ai/claude-code
        "install_url": "https://github.com/google-gemini/gemini-cli",
        "install_hint": "npm install -g @anthropic-ai/gemini-cli",
        "category": "ai-agent",
    },
    {
        "id": "nodejs",
        "name": "Node.js / npm",
        "description": "JavaScript 런타임 — Codex, Gemini CLI 등의 사전 요구사항",
        "check_commands": [["node", "--version"]],
        "check_paths": [],
        "install_script": None,
        "install_url": "https://nodejs.org/",
        "install_hint": "https://nodejs.org 에서 LTS 버전 다운로드",
        "category": "runtime",
    },
]


def _check_tool_installed(tool: dict) -> dict:
    """단일 도구의 설치 상태를 확인하여 결과 딕셔너리 반환.

    Why: 명령 실행과 경로 확인을 모두 시도하여 다양한 설치 방식을 지원.
    """
    version = None

    # 1) 명령어 실행으로 확인
    for cmd in tool.get("check_commands", []):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                version = result.stdout.strip().split("\n")[0]
                break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    # 2) 알려진 설치 경로 확인 (PATH에 없는 경우 대비)
    if not version:
        for path in tool.get("check_paths", []):
            if os.path.exists(path):
                try:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip().split("\n")[0]
                        break
                except (subprocess.TimeoutExpired, OSError):
                    continue

    return {
        "id": tool["id"],
        "name": tool["name"],
        "description": tool["description"],
        "installed": version is not None,
        "version": version,
        "install_script": tool.get("install_script"),
        "install_url": tool.get("install_url", ""),
        "install_hint": tool.get("install_hint", ""),
        "category": tool.get("category", ""),
        "can_auto_install": tool.get("install_script") is not None,
    }


def _get_all_status() -> dict:
    """모든 등록된 도구의 설치 상태를 반환."""
    tools = [_check_tool_installed(t) for t in TOOL_REGISTRY]

    installed_count = sum(1 for t in tools if t["installed"])
    total_count = len(tools)

    return {
        "tools": tools,
        "summary": {
            "installed": installed_count,
            "total": total_count,
            "all_ready": installed_count == total_count,
        },
    }


def _find_install_script(script_name: str) -> Path | None:
    """설치 스크립트를 여러 후보 경로에서 검색."""
    candidates = [
        _SCRIPTS_DIR / script_name,
        _PROJECT_ROOT / "scripts" / script_name,
        _BASE_DIR.parent / "scripts" / script_name,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _get_python_cmd() -> str:
    """사용 가능한 Python 인터프리터 경로 반환."""
    # 프로젝트 venv 우선
    for venv_python in [
        _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        _PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
        _BASE_DIR / "venv" / "Scripts" / "python.exe",
    ]:
        if venv_python.exists():
            return str(venv_python)
    return sys.executable


def _json_response(handler, data: Any, status: int = 200) -> None:
    """JSON 응답을 전송하는 헬퍼."""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json;charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


# ═══════════════════════════════════════════════════════════════════════
#  HTTP 핸들러
# ═══════════════════════════════════════════════════════════════════════

def handle_get(handler, path: str, params: dict = None, **kwargs) -> bool:
    """GET /api/tools/status — 전체 도구 설치 상태 조회.

    Returns: True if path handled, False otherwise.
    """
    if path == "/api/tools/status":
        try:
            result = _get_all_status()
            _json_response(handler, result)
        except Exception as e:
            _json_response(handler, {"error": str(e)}, status=500)
        return True
    return False


def handle_post(handler, path: str, data: dict, **kwargs) -> bool:
    """POST /api/tools/install — 특정 도구의 설치 스크립트를 새 콘솔에서 실행.

    요청 본문:
        {"tool": "gh"}          — 도구 ID
        {"tool": "playwright"}  — Playwright 설치

    Why: 설치 과정이 길고 사용자 상호작용(인증 등)이 필요할 수 있으므로
    별도 콘솔 창에서 실행하여 대시보드 서버를 블로킹하지 않는다.
    """
    if path != "/api/tools/install":
        return False

    tool_id = data.get("tool", "").strip()
    if not tool_id:
        _json_response(handler, {"status": "error", "message": "tool ID가 필요합니다"}, 400)
        return True

    # 레지스트리에서 도구 찾기
    tool_def = next((t for t in TOOL_REGISTRY if t["id"] == tool_id), None)
    if not tool_def:
        _json_response(handler, {
            "status": "error",
            "message": f"알 수 없는 도구: {tool_id}",
        }, 404)
        return True

    script_name = tool_def.get("install_script")
    if not script_name:
        # 자동 설치 스크립트가 없는 경우 — 수동 설치 안내
        _json_response(handler, {
            "status": "manual",
            "message": f"{tool_def['name']}은(는) 수동 설치가 필요합니다",
            "install_url": tool_def.get("install_url", ""),
            "install_hint": tool_def.get("install_hint", ""),
        })
        return True

    # 설치 스크립트 경로 확인
    script_path = _find_install_script(script_name)
    if not script_path:
        _json_response(handler, {
            "status": "error",
            "message": f"설치 스크립트를 찾을 수 없습니다: {script_name}",
        }, 404)
        return True

    # 새 콘솔 창에서 설치 스크립트 실행
    try:
        python_cmd = _get_python_cmd()
        install_cmd = subprocess.list2cmdline([python_cmd, str(script_path)])
        tool_name = tool_def["name"]

        cmdline = (
            f"title Vibe Coding - {tool_name} Installer && "
            f"echo ============================================ && "
            f"echo   {tool_name} 설치 중... && "
            f"echo ============================================ && "
            f"echo. && "
            f"{install_cmd} && "
            f"echo. && echo {tool_name} 설치가 완료되었습니다. 이 창을 닫아도 됩니다. || "
            f"echo. && echo {tool_name} 설치에 실패했습니다. 위 로그를 확인하세요."
        )

        create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
        subprocess.Popen(
            ["cmd.exe", "/k", cmdline],
            cwd=str(_PROJECT_ROOT),
            close_fds=True,
            creationflags=create_new_console,
        )

        _json_response(handler, {
            "status": "success",
            "message": f"{tool_name} 설치가 시작되었습니다. 콘솔 창을 확인하세요.",
            "tool": tool_id,
            "script": str(script_path),
            "python": python_cmd,
        })
    except Exception as e:
        _json_response(handler, {
            "status": "error",
            "message": f"설치 실행 실패: {e}",
        }, 500)

    return True
