"""
FILE: api/tools_api.py
DESCRIPTION: AI 도구 CLI 설치 관리 API.
             대시보드에서 gh CLI, Playwright CLI, Codex CLI 등
             필요한 개발 도구의 설치 상태를 확인하고 원클릭 설치를 제공한다.

             GET  /api/tools/status   — 전체 도구 설치 상태 목록 반환
             POST /api/tools/install  — 특정 도구 설치 실행 (새 콘솔 창)

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 ���성 — 도�� 설치 통합 API
- 2026-04-05 Claude Opus 4.6: psql, ruff, uv, pytest, pyinstaller 도구 추가 (Gemini 추천 반영)
- 2026-04-05 Claude Opus 4.6: 전체 도구 install_hint 추가 + Git, Python, TypeScript, Vite, ESLint, Tailwind CSS, Inno Setup, Pillow, Claude/Gemini/Node.js 자동 설치 지원
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── 경로 설정 ──────────────────────────────────────────────────────────
# [2026-04-10] Claude: frozen(EXE) 모드에서 경로 오계산 버그 수정
#   - Dev:    __file__ = .ai_monitor/api/tools_api.py → _BASE_DIR = .ai_monitor/, _PROJECT_ROOT = 프로젝트 루트
#   - Frozen: __file__ = MEIPASS/api/tools_api.py → _BASE_DIR = MEIPASS/, _PROJECT_ROOT = MEIPASS/ (scripts는 MEIPASS/scripts/)
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys._MEIPASS)
    _PROJECT_ROOT = Path(sys.executable).resolve().parent
    _SCRIPTS_DIR = _BASE_DIR / "scripts"  # MEIPASS/scripts/ (spec datas에 포함됨)
else:
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
        "install_hint": "winget install --id GitHub.cli",
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
        "install_hint": "pip install playwright && playwright install",
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
        "install_hint": "npm install -g @openai/codex",
        "category": "ai-agent",
    },
    {
        "id": "claude",
        "name": "Claude CLI",
        "description": "Anthropic Claude Code — AI 코딩 에이전트",
        "check_commands": [["claude", "--version"]],
        "check_paths": [],
        "install_script": "install_npm_tool.py",
        "install_args": ["--package", "@anthropic-ai/claude-code", "--name", "Claude CLI"],
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
        "install_script": "install_npm_tool.py",
        "install_args": ["--package", "@google/gemini-cli", "--name", "Gemini CLI"],
        "install_url": "https://github.com/google-gemini/gemini-cli",
        "install_hint": "npm install -g @google/gemini-cli",
        "category": "ai-agent",
    },
    {
        "id": "nodejs",
        "name": "Node.js / npm",
        "description": "JavaScript 런타임 — Codex, Gemini CLI 등의 사전 요구사항",
        "check_commands": [["node", "--version"]],
        "check_paths": [],
        "install_script": "install_nodejs.py",
        "install_url": "https://nodejs.org/",
        "install_hint": "winget install --id OpenJS.NodeJS.LTS",
        "category": "runtime",
    },
    # ── 데이터베이스 도구 ─────────────────────────────────────────────
    {
        "id": "psql",
        "name": "psql (PostgreSQL CLI)",
        "description": "PostgreSQL 직접 쿼리 및 디버깅 — 내장 PG 또는 시스템 PG 자동 감지",
        "check_commands": [["psql", "--version"]],
        "check_paths": [
            # 내장 포터블 PostgreSQL 경로 (개발/frozen 모드 공통 — _BASE_DIR 기준)
            str(_BASE_DIR / "bin" / "pgsql" / "bin" / "psql.exe"),
            # 시스템 PostgreSQL 기본 경로
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "PostgreSQL", "18", "bin", "psql.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "PostgreSQL", "17", "bin", "psql.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "PostgreSQL", "16", "bin", "psql.exe"),
        ],
        "install_script": "install_psql.py",
        "install_url": "https://www.postgresql.org/download/",
        "install_hint": "내장 PostgreSQL의 psql.exe를 사용자 PATH에 자동 등록합니다.",
        "category": "database",
    },
    # ── Python 개발 도구 (Gemini 추천) ────────────────────────────────
    {
        "id": "ruff",
        "name": "Ruff",
        "description": "Python 린팅 + 포맷팅 (Rust 기반, 초고속) — Gemini 추천",
        "check_commands": [["ruff", "--version"], [sys.executable, "-m", "ruff", "--version"]],
        "check_paths": [],
        "install_script": "install_dev_tools.py",
        "install_args": ["--tool", "ruff"],
        "install_url": "https://docs.astral.sh/ruff/",
        "install_hint": "pip install ruff",
        "category": "code-quality",
    },
    {
        "id": "uv",
        "name": "uv",
        "description": "초고속 Python 패키지 관리자 (pip 대체) — Gemini 추천",
        "check_commands": [["uv", "--version"]],
        "check_paths": [],
        "install_script": "install_dev_tools.py",
        "install_args": ["--tool", "uv"],
        "install_url": "https://docs.astral.sh/uv/",
        "install_hint": "pip install uv",
        "category": "package-manager",
    },
    {
        "id": "pytest",
        "name": "pytest",
        "description": "Python 단위 테스트 프레임워크 — Gemini 추천",
        "check_commands": [["pytest", "--version"], [sys.executable, "-m", "pytest", "--version"]],
        "check_paths": [],
        "install_script": "install_dev_tools.py",
        "install_args": ["--tool", "pytest"],
        "install_url": "https://docs.pytest.org/",
        "install_hint": "pip install pytest",
        "category": "testing",
    },
    {
        "id": "pyinstaller",
        "name": "PyInstaller",
        "description": "Python → Windows EXE 빌드 도구 — 릴리스 빌드용",
        "check_commands": [["pyinstaller", "--version"], [sys.executable, "-m", "PyInstaller", "--version"]],
        "check_paths": [],
        "install_script": "install_dev_tools.py",
        "install_args": ["--tool", "pyinstaller"],
        "install_url": "https://pyinstaller.org/",
        "install_hint": "pip install pyinstaller",
        "category": "build",
    },
    # ── 기본 런타임 / VCS ─────────────────────────────────────────────
    {
        "id": "git",
        "name": "Git",
        "description": "분산 버전 관리 시스템 — 모든 개발의 기반",
        "check_commands": [["git", "--version"]],
        "check_paths": [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Git", "cmd", "git.exe"),
        ],
        "install_script": "install_system_tool.py",
        "install_args": ["--tool", "git"],
        "install_url": "https://git-scm.com/",
        "install_hint": "winget install --id Git.Git",
        "category": "vcs",
    },
    {
        "id": "python",
        "name": "Python",
        "description": "Python 인터프리터 — 서버 및 스크립트 실행 런타임",
        "check_commands": [["python", "--version"]],
        "check_paths": [],
        "install_script": None,
        "install_url": "https://www.python.org/downloads/",
        "install_hint": "winget install --id Python.Python.3.13",
        "category": "runtime",
    },
    # ── 프론트엔드 빌드 도구 ──────────────────────────────────────────
    {
        "id": "typescript",
        "name": "TypeScript",
        "description": "JavaScript 타입 체크 — React 프론트엔드 필수",
        "check_commands": [["npx", "tsc", "--version"]],
        "check_paths": [],
        "install_script": "install_frontend_deps.py",
        "install_args": ["--tool", "typescript"],
        "install_url": "https://www.typescriptlang.org/",
        "install_hint": "cd .ai_monitor/vibe-view && npm install",
        "category": "frontend",
    },
    {
        "id": "vite",
        "name": "Vite",
        "description": "초고속 프론트엔드 빌드 번들러 — React 앱 빌드/개발 서버",
        "check_commands": [["npx", "vite", "--version"]],
        "check_paths": [],
        "install_script": "install_frontend_deps.py",
        "install_args": ["--tool", "vite"],
        "install_url": "https://vite.dev/",
        "install_hint": "cd .ai_monitor/vibe-view && npm install",
        "category": "frontend",
    },
    {
        "id": "eslint",
        "name": "ESLint",
        "description": "JavaScript/TypeScript 린팅 도구 — 코드 품질 유지",
        "check_commands": [["npx", "eslint", "--version"]],
        "check_paths": [],
        "install_script": "install_frontend_deps.py",
        "install_args": ["--tool", "eslint"],
        "install_url": "https://eslint.org/",
        "install_hint": "cd .ai_monitor/vibe-view && npm install",
        "category": "code-quality",
    },
    {
        "id": "tailwindcss",
        "name": "Tailwind CSS",
        "description": "유틸리티 기반 CSS 프레임워크 — 대시보드 다크 테마 UI",
        "check_commands": [["npx", "tailwindcss", "--help"]],
        "check_paths": [],
        "install_script": "install_frontend_deps.py",
        "install_args": ["--tool", "tailwindcss"],
        "install_url": "https://tailwindcss.com/",
        "install_hint": "cd .ai_monitor/vibe-view && npm install",
        "category": "frontend",
    },
    # ── Windows 빌드 도구 ─────────────────────────────────────────────
    {
        "id": "iscc",
        "name": "Inno Setup (ISCC)",
        "description": "Windows 인스톨러 빌드 도구 — EXE 설치 파일 생성",
        "check_commands": [["ISCC.exe", "/?"]],
        "check_paths": [
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Inno Setup 6", "ISCC.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Inno Setup 6", "ISCC.exe"),
        ],
        "install_script": "install_system_tool.py",
        "install_args": ["--tool", "iscc"],
        "install_url": "https://jrsoftware.org/isinfo.php",
        "install_hint": "winget install --id JRSoftware.InnoSetup",
        "category": "build",
    },
    # ── Python 추가 도구 ──────────────────────────────────────────────
    {
        "id": "pillow",
        "name": "Pillow",
        "description": "Python 이미지 처리 라이브러리 — 아이콘 PNG→ICO 변환 등",
        "check_commands": [[sys.executable, "-c", "import PIL; print(PIL.__version__)"]],
        "check_paths": [],
        "install_script": "install_dev_tools.py",
        "install_args": ["--tool", "pillow"],
        "install_url": "https://python-pillow.org/",
        "install_hint": "pip install Pillow",
        "category": "image",
    },
    # ── Zettelkasten 도구 ─────────────────────────────────────────────
    {
        "id": "obsidian",
        "name": "Obsidian",
        "description": "마크다운 지식 관리 앱 — Zettelkasten 그래프 뷰어 + 편집기",
        "check_commands": [["obsidian", "--version"]],
        "check_paths": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Obsidian", "Obsidian.exe"),
        ],
        "install_script": "install_system_tool.py",
        "install_args": ["--tool", "obsidian"],
        "install_url": "https://obsidian.md/",
        "install_hint": "winget install --id Obsidian.Obsidian",
        "category": "knowledge",
    },
    # ── 하네스 (Harness) — 프로젝트 품질 관리 ─────────────────────────
    {
        "id": "harness-hooks",
        "name": "Claude Code 훅",
        "description": "UserPromptSubmit/PreToolUse/PostToolUse/Stop 자동 트레이싱 훅 설정",
        "check_commands": [[
            sys.executable, "-c",
            "import json,pathlib,sys;"
            f"p=pathlib.Path(r'{_PROJECT_ROOT}') / '.claude' / 'settings.json';"
            "d=json.loads(p.read_text(encoding='utf-8'));"
            "h=d.get('hooks',{});"
            "n=sum(len(v) for v in h.values());"
            "print(f'v2 ({n} hooks)') if n>0 else sys.exit(1)",
        ]],
        "check_paths": [],
        "install_script": "install_harness.py",
        "install_args": ["--component", "hooks"],
        "install_url": "",
        "install_hint": "python scripts/install_harness.py --component hooks",
        "category": "harness",
    },
    {
        "id": "harness-rules",
        "name": "프로젝트 규칙 파일",
        "description": "CLAUDE.md + .claude/rules/ — AI 에이전트 행동 규칙 스캐폴딩",
        "check_commands": [[
            sys.executable, "-c",
            "import pathlib,sys;"
            f"r=pathlib.Path(r'{_PROJECT_ROOT}');"
            "has_claude=any((r/'CLAUDE.md').exists() for _ in [1]);"
            "has_rules=(r/'.claude'/'rules').is_dir();"
            "print('설정됨') if has_claude and has_rules else sys.exit(1)",
        ]],
        "check_paths": [],
        "install_script": "install_harness.py",
        "install_args": ["--component", "rules"],
        "install_url": "",
        "install_hint": "python scripts/install_harness.py --component rules",
        "category": "harness",
    },
    {
        "id": "harness-verify",
        "name": "하네스 검증 시스템",
        "description": "harness_verify.py — 프로젝트 구조/문서/파일 크기 자동 검증",
        "check_commands": [[
            sys.executable, "-c",
            "import pathlib,sys;"
            f"p=pathlib.Path(r'{_PROJECT_ROOT}') / 'scripts' / 'harness_verify.py';"
            "print('v2') if p.exists() else sys.exit(1)",
        ]],
        "check_paths": [],
        "install_script": "install_harness.py",
        "install_args": ["--component", "verify"],
        "install_url": "",
        "install_hint": "python scripts/install_harness.py --component verify",
        "category": "harness",
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
            resolved_cmd = list(cmd)
            exe_name = resolved_cmd[0]
            if not os.path.isabs(exe_name):
                candidates = [exe_name]
                if os.name == "nt" and "." not in Path(exe_name).name:
                    candidates.extend([f"{exe_name}.exe", f"{exe_name}.cmd", f"{exe_name}.bat"])

                for candidate in candidates:
                    found = shutil.which(candidate)
                    if found:
                        resolved_cmd[0] = found
                        break

            result = subprocess.run(
                resolved_cmd, capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                output = (result.stdout or result.stderr).strip()
                version = output.split("\n")[0] if output else ""
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
#  프로젝트 규칙 설정 프롬프트 템플릿
#  [2026-04-05 Claude] 각 AI 에이전트에게 보낼 프롬프트를 클립보드로 복사
# ═══════════════════════════════════════════════════════════════════════

RULE_SETUP_PROMPTS: list[dict[str, str]] = [
    {
        "id": "claude-rules",
        "agent": "Claude Code",
        "description": "CLAUDE.md + .claude/rules/ 자동 생성",
        "prompt": (
            "이 프로젝트를 분석하고 Claude Code용 규칙 파일을 생성해줘.\n\n"
            "【작업 순서】\n"
            "1. 프로젝트의 언어, 프레임워크, 빌드 도구, 디렉토리 구조를 파악\n"
            "2. CLAUDE.md를 50줄 이하로 간결하게 작성 (핵심 규칙 + 빌드 명령어만)\n"
            "3. .claude/rules/ 디렉토리에 상세 규칙을 분리:\n"
            "   - architecture.md — 아키텍처 개요, 주요 모듈, 데이터 흐름\n"
            "   - coding-style.md — 코딩 컨벤션, 네이밍, 포맷\n"
            "   - commit-rules.md — 커밋 메시지 형식\n"
            "4. 기존 README.md, package.json, pyproject.toml 등을 참고\n\n"
            "【원칙】\n"
            "- 한글로 작성\n"
            "- CLAUDE.md는 원칙만, 상세는 .claude/rules/로 분리\n"
            "- 프로젝트에 실제로 사용되는 기술만 포함 (추측 금지)"
        ),
    },
    {
        "id": "gemini-rules",
        "agent": "Gemini CLI",
        "description": "GEMINI.md 자동 생성",
        "prompt": (
            "이 프로젝트를 분석하고 Gemini CLI용 규칙 파일(GEMINI.md)을 생성해줘.\n\n"
            "【작업 순서】\n"
            "1. 프로젝트의 언어, 프레임워크, 빌드 도구, 디렉토리 구조를 파악\n"
            "2. GEMINI.md를 작성:\n"
            "   - 프로젝트 한 줄 소개\n"
            "   - 핵심 규칙 (코딩 스타일, 언어, DB 정책 등)\n"
            "   - 빌드 및 실행 명령어\n"
            "   - 아키텍처 개요\n"
            "3. 기존 README.md, package.json, pyproject.toml 등을 참고\n\n"
            "【원칙】\n"
            "- 한글로 작성\n"
            "- 100줄 이하로 간결하게\n"
            "- 프로젝트에 실제로 사용되는 기술만 포함 (추측 금지)"
        ),
    },
    {
        "id": "codex-rules",
        "agent": "Codex CLI",
        "description": "AGENTS.md 자동 생성",
        "prompt": (
            "이 프로젝트를 분석하고 Codex CLI용 규칙 파일(AGENTS.md)을 생성해줘.\n\n"
            "【작업 순서】\n"
            "1. 프로젝트의 언어, 프레임워크, 빌드 도구, 디렉토리 구조를 파악\n"
            "2. AGENTS.md를 작성:\n"
            "   - 프로젝트 한 줄 소개\n"
            "   - 핵심 규칙 (코딩 스타일, 언어, DB 정책 등)\n"
            "   - 빌드 및 실행 명령어\n"
            "   - 아키텍처 개요\n"
            "3. 기존 README.md, package.json, pyproject.toml 등을 참고\n\n"
            "【원칙】\n"
            "- 한글로 작성\n"
            "- 100줄 이하로 간결하게\n"
            "- 프로젝트에 실제로 사용되는 기술만 포함 (추측 금지)"
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════
#  HTTP 핸들러
# ═══════════════════════════════════════════════════════════════════════

def handle_get(handler, path: str, params: dict = None, **kwargs) -> bool:
    """GET /api/tools/status, /api/tools/rule-prompts — 도구 상태 및 규칙 프롬프트 조회.

    Returns: True if path handled, False otherwise.
    """
    if path == "/api/tools/rule-prompts":
        _json_response(handler, {"prompts": RULE_SETUP_PROMPTS})
        return True
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
        # install_args가 있으면 스크립트 뒤에 추가 (예: --tool ruff)
        cmd_parts = [python_cmd, str(script_path)]
        cmd_parts.extend(tool_def.get("install_args", []))
        install_cmd = subprocess.list2cmdline(cmd_parts)
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
