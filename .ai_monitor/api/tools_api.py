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
# [2026-04-13] Claude: frozen(EXE) 모드에서 _PROJECT_ROOT가 EXE 설치 경로를 가리키던 버그 수정
#   - 기존: _PROJECT_ROOT = EXE 폴더 → .claude/, scripts/, CLAUDE.md 못 찾음 (11/23 도구만 감지)
#   - 수정: config.json의 last_path(사용자가 선택한 프로젝트 경로) 우선 사용
#   - server.py의 _current_project_root()와 동일한 로직 적용
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys._MEIPASS)
    # config.json에서 실제 프로젝트 경로 로드 (server.py _current_project_root() 동일 로직)
    _PROJECT_ROOT = Path(sys.executable).resolve().parent  # 폴백
    try:
        _cfg_path = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "config.json"
        if _cfg_path.exists():
            import json as _json_init
            _cfg = _json_init.loads(_cfg_path.read_text(encoding='utf-8'))
            _lp = _cfg.get('last_path', '')
            if _lp and Path(_lp).is_dir():
                _PROJECT_ROOT = Path(_lp)
    except Exception:
        pass  # config 로드 실패 시 EXE 경로 폴백
    _SCRIPTS_DIR = _PROJECT_ROOT / "scripts"  # 실제 프로젝트의 scripts/
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
        # Phase 2 정직성 — Claude만 활성, Codex는 수동 실행 시에만 참여.
        "experimental": True,
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
        # Phase 2 정직성 — 사용자 수동 실행 시만 참여. 자동 디스패처는 라벨링 유지.
        "experimental": True,
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
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
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
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Obsidian", "Obsidian.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Obsidian", "Obsidian.exe"),
            # Electron 앱 기본 user install 경로 (다른 PC에서 감지 안 되는 주요 원인)
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Obsidian", "Obsidian.exe"),
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


def _resolve_python() -> str:
    """EXE 모드에서도 실제 Python 인터프리터 경로를 반환한다.

    Why: frozen(EXE) 모드에서 sys.executable = vibe-coding.exe이므로
    Python -c 명령을 실행할 수 없다. 프로젝트 venv → 시스템 Python 순으로 탐색.
    """
    # 1) 프로젝트 venv
    for venv_python in [
        _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        _PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
        _BASE_DIR / "venv" / "Scripts" / "python.exe",
    ]:
        if venv_python.exists():
            return str(venv_python)
    # 2) 시스템 PATH
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return found
    # 3) 폴백
    return sys.executable


def _check_tool_installed(tool: dict) -> dict:
    """단일 도구의 설치 상태를 확인하여 결과 딕셔너리 반환.

    Why: 명령 실행과 경로 확인을 모두 시도하여 다양한 설치 방식을 지원.
    """
    version = None
    real_python = _resolve_python()

    # npx 계열 도구는 node_modules가 있는 디렉토리에서 실행해야 함
    _npx_cwd = str(_BASE_DIR / "vibe-view") if (_BASE_DIR / "vibe-view" / "node_modules").is_dir() else None

    # 1) 명령어 실행으로 확인
    for cmd in tool.get("check_commands", []):
        try:
            resolved_cmd = list(cmd)

            # [EXE 호환] sys.executable 자리에 실제 Python 경로 대입
            if resolved_cmd[0] == sys.executable and getattr(sys, 'frozen', False):
                resolved_cmd[0] = real_python

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

            # npx 명령은 vibe-view 디렉토리에서 실행
            cwd = _npx_cwd if (exe_name == "npx" and _npx_cwd) else None

            result = subprocess.run(
                resolved_cmd, capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                cwd=cwd,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                output = (result.stdout or result.stderr).strip()
                version = output.split("\n")[0] if output else ""
                break
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
            continue

    # 2) 알려진 설치 경로 확인 (PATH에 없는 경우 대비)
    if not version:
        for path in tool.get("check_paths", []):
            if os.path.exists(path):
                try:
                    result = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        encoding="utf-8", errors="replace",
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip().split("\n")[0]
                        break
                except (subprocess.TimeoutExpired, OSError):
                    pass
                # --version 실패해도 파일이 존재하면 설치된 것으로 처리
                # (ISCC.exe 등 --version을 지원하지 않는 도구 대응)
                if not version:
                    version = f"설치됨 ({Path(path).name})"
                    break

    # 3) Windows 레지스트리에서 설치 경로 동적 검색 (하드코딩 경로 의존 제거)
    if not version and os.name == "nt":
        tool_name = tool.get("name", "")
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            subkey = winreg.OpenKey(key, subkey_name)
                            try:
                                display, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                if tool_name.lower() in display.lower():
                                    # DisplayIcon에서 exe 경로 추출
                                    try:
                                        icon, _ = winreg.QueryValueEx(subkey, "DisplayIcon")
                                        exe_path = icon.split(",")[0].strip('"')
                                        if os.path.exists(exe_path):
                                            version = f"설치됨 ({Path(exe_path).name})"
                                    except (OSError, ValueError):
                                        pass
                                    # InstallLocation 폴백
                                    if not version:
                                        try:
                                            loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                            if loc and os.path.isdir(loc):
                                                version = f"설치됨 ({loc})"
                                        except (OSError, ValueError):
                                            pass
                            except OSError:
                                pass
                            finally:
                                winreg.CloseKey(subkey)
                            if version:
                                break
                            i += 1
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except OSError:
                    pass
                if version:
                    break
        except ImportError:
            pass

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
        # Phase 2 정직성 라벨 — UI가 "실험적" 배지를 표시하기 위해 전달.
        "experimental": bool(tool.get("experimental", False)),
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
    # frozen 모드: MEIPASS/scripts/ 도 탐색 (spec에 포함된 경우)
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys._MEIPASS) / "scripts" / script_name)
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
    # ── 1단계: 개발 도구 설치 (기반) ──────────────────────────────────
    {
        "id": "dev-tools",
        "agent": "공통 (아무 에이전트)",
        "category": "setup",
        "description": "① 개발 도구 일괄 설치 — pip/npm/winget 기반",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트의 개발 환경을 세팅해줘.\n\n"
            "【작업 순서】\n"
            "1. 프로젝트의 언어, 프레임워크를 파악 (package.json, pyproject.toml, go.mod 등)\n"
            "2. 필요한 런타임/도구 확인:\n"
            "   - Python >= 3.11 + pip\n"
            "   - Node.js >= 20 + npm\n"
            "   - Git + GitHub CLI (gh)\n"
            "3. 누락된 도구를 설치:\n"
            "   - Windows: winget install 사용\n"
            "   - 이미 설치된 도구는 건너뛰기\n"
            "4. 프로젝트 의존성 설치:\n"
            "   - Python: pip install -e . 또는 pip install -r requirements.txt\n"
            "   - Node.js: npm install (package.json이 있는 디렉토리에서)\n"
            "5. 설치 결과를 도구별로 ✅/❌ 요약\n\n"
            "【원칙】\n"
            "- 이미 설치된 도구는 재설치하지 않기\n"
            "- 설치 실패 시 수동 설치 URL 안내\n"
            "- 글로벌 설치와 프로젝트 로컬 설치 구분"
        ),
    },
    # ── 2단계: DB + 하이브 마인드 ─────────────────────────────────────
    {
        "id": "db-hive",
        "agent": "공통 (아무 에이전트)",
        "category": "setup",
        "description": "② DB + 하이브 마인드 — PostgreSQL 스키마 초기화",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트용 PostgreSQL DB와 하이브 마인드를 세팅해줘.\n\n"
            "【사전 조건】\n"
            "- PostgreSQL 18이 포트 5433에서 실행 중 (비이브 코딩 내장 포터블)\n"
            "- psql 명령어 사용 가능\n\n"
            "【작업 순서】\n"
            "1. 프로젝트 이름으로 DB 생성 (이미 있으면 건너뛰기):\n"
            "   CREATE DATABASE ai_monitor_<프로젝트폴더명>;\n"
            "2. 필수 테이블 스키마 초기화:\n"
            "   - pg_logs — 에이전트 활동 로그\n"
            "   - hive_tasks — 태스크 큐 (원자적 체크아웃)\n"
            "   - agent_heartbeats — 에이전트 상태 추적\n"
            "   - hive_memory — 공유 지식 기반\n"
            "   - task_comments — 에이전트 간 소통\n"
            "   - zettel_notes — 제텔카스텐 노트\n"
            "3. NOTIFY/LISTEN 채널 확인 (하이브 통신용)\n"
            "4. 연결 테스트: SELECT count(*) FROM pg_logs;\n\n"
            "【원칙】\n"
            "- 기존 데이터 절대 삭제 금지 (CREATE IF NOT EXISTS)\n"
            "- 포트 5433 고정 (기본 5432 아님 주의)\n"
            "- 스키마는 {project_path}/scripts/init_schema.sql 참고"
        ),
    },
    # ── 3단계: 하네스 엔지니어링 ──────────────────────────────────────
    {
        "id": "harness",
        "agent": "Claude Code",
        "category": "setup",
        "description": "③ 하네스 훅 설정 — .claude/settings.json + 검증 스크립트",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트에 비이브 코딩 하네스를 세팅해줘.\n\n"
            "【하네스란?】\n"
            "Claude Code가 매 프롬프트 제출 시 자동으로 실행하는 검증 시스템.\n"
            "품질 게이트 역할 — 규칙 위반, 보안 취약점, 코드 품질을 자동 체크.\n\n"
            "【작업 순서】\n"
            "1. .claude/settings.json 생성/수정:\n"
            "   hooks > UserPromptSubmit에 harness_v2.py 등록\n"
            "   ```json\n"
            '   {"hooks": {"UserPromptSubmit": [{\n'
            '     "type": "command",\n'
            '     "command": "python scripts/harness_v2.py \\"$PROMPT\\""\n'
            "   }]}}\n"
            "   ```\n"
            "2. scripts/harness_v2.py 존재 확인 (없으면 생성):\n"
            "   - 프로젝트 규칙 파일 로드 (CLAUDE.md, RULES.md)\n"
            "   - 표준 헤더 검증\n"
            "   - 커밋 메시지 형식 검증\n"
            "   - 보안 기본 체크 (하드코딩 시크릿 등)\n"
            "3. scripts/experience.py — 작업 완료 시 XP 기록\n"
            "4. 하네스 테스트: 간단한 프롬프트로 훅 동작 확인\n\n"
            "【원칙】\n"
            "- 하네스는 경고만 (블로킹 금지) — 개발 흐름 방해 최소화\n"
            "- 기존 settings.json이 있으면 hooks만 추가 (덮어쓰기 금지)\n"
            "- 검증 실패 시 구체적 수정 가이드 출력"
        ),
    },
    # ── 4단계: 옵시디언 제텔카스텐 ────────────────────────────────────
    {
        "id": "zettelkasten",
        "agent": "공통 (아무 에이전트)",
        "category": "setup",
        "description": "④ 옵시디언 제텔카스텐 — 지식 관리 vault 연결",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트에 옵시디언 제텔카스텐 지식 관리를 세팅해줘.\n\n"
            "【제텔카스텐이란?】\n"
            "에이전트가 작업하면서 배운 지식을 노트로 저장하고,\n"
            "노트 간 링크로 지식 그래프를 형성하는 시스템.\n\n"
            "【작업 순서】\n"
            "1. 옵시디언 vault 경로 확인/설정:\n"
            "   - 기본 위치: {project_path}/zettel/ 또는 사용자 지정 경로\n"
            "   - .obsidian/ 디렉토리 존재 확인\n"
            "2. vault 기본 구조 생성:\n"
            "   - 0-inbox/ — 새 노트 (fleeting notes)\n"
            "   - 1-permanent/ — 정제된 영구 노트\n"
            "   - 2-index/ — 주제별 인덱스 (MOC)\n"
            "   - templates/ — 노트 템플릿\n"
            "3. 노트 템플릿 생성:\n"
            "   - fleeting.md — 빠른 메모 (ID, 태그, 본문)\n"
            "   - permanent.md — 영구 노트 (ID, 링크, 출처, 본문)\n"
            "4. DB 연결 확인: zettel_notes 테이블 존재 여부\n"
            "5. scripts/zettel.py 동작 테스트:\n"
            "   python scripts/zettel.py capture \"테스트 노트\"\n\n"
            "【원칙】\n"
            "- 기존 vault가 있으면 구조만 보강 (덮어쓰기 금지)\n"
            "- 옵시디언 미설치여도 vault 구조는 생성 (텍스트 파일이니까)\n"
            "- 노트 ID는 Zettelkasten 표준: YYYYMMDDHHmmss"
        ),
    },
    # ── 5단계: 하이브 훅 설치 (외부 프로젝트 → vibe-coding 연결) ──────
    {
        "id": "hive-hooks",
        "agent": "Claude Code",
        "category": "setup",
        "description": "⑤ 하이브 훅 설치 — 이 프로젝트의 작업이 비이브 코딩 하이브 DB/옵시디언에 자동 기록되도록 연결",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트(외부 프로젝트일 수 있음)의 .claude/settings.local.json에\n"
            "비이브 코딩 하이브 마인드 훅을 등록해줘. 이 훅이 있어야 본 프로젝트에서\n"
            "Claude Code로 한 작업이 PostgreSQL 하이브 DB와 옵시디언 제텔카스텐에\n"
            "자동 저장돼. (없으면 작업 흔적이 어디에도 안 남아.)\n\n"
            "【권장 — install_hive_hooks.py 사용】\n"
            "수동으로 hooks 키를 만지지 말고 비이브 코딩이 제공하는 스크립트를 호출해:\n"
            "  python <비이브-코딩>/scripts/install_hive_hooks.py --target {project_path}\n"
            "이 스크립트가 아래의 자동 탐색 + 멱등 머지 + 백업을 전부 수행해. dry-run으로\n"
            "선검증 후 실행: `--dry-run` 플래그 추가.\n\n"
            "【진입점 자동 탐색 우선순위】\n"
            "스크립트는 다음 순서로 hook 진입점을 찾는다 (실제 파일 존재 여부로 판단):\n"
            "  (a) 환경변수 VIBE_HIVE_HOOK — 다음 셋 중 하나를 받음\n"
            "      • scripts/hive_hook.py 파일 직접 지정 (PY 형식)\n"
            "      • scripts/ 디렉토리 지정 (PY 형식)\n"
            "      • vibe-coding.exe 파일 지정 (EXE 형식, 설치 EXE 단독 PC)\n"
            "  (b) PATH의 vibe-coding[.exe] 옆/부모의 scripts/hive_hook.py (PY 형식)\n"
            "  (c) PATH의 vibe-coding[.exe] 자체 (EXE 형식 — scripts/ 미동봉 시 폴백)\n"
            "  (d) 표준 설치 경로 후보 순회:\n"
            "      [PY] C:/Program Files/vibe-coding/scripts/hive_hook.py\n"
            "      [PY] %LOCALAPPDATA%/Programs/vibe-coding/scripts/hive_hook.py\n"
            "      [PY] D:/vibe-coding/scripts/hive_hook.py\n"
            "      [EXE] C:/Program Files/VibeCoding/vibe-coding.exe\n"
            "      [EXE] %LOCALAPPDATA%/Programs/VibeCoding/vibe-coding.exe\n"
            "  (e) 모두 실패 시 중단 — 사용자에게 VIBE_HIVE_HOOK 설정 안내 (추측 금지)\n\n"
            "【등록 명령 형식】\n"
            "  • PY 형식  : `python \"<scripts>/hive_hook.py\"`\n"
            "  • EXE 형식 : `\"<vibe-coding.exe>\" hook`\n"
            "  설치 EXE는 `hook` 서브커맨드로 hive_hook.main()을 즉시 디스패치한다\n"
            "  (서버 부트 없이 stdin JSON만 처리 — startup 비용 수십 ms).\n\n"
            "【등록 이벤트 (4개)】\n"
            "  - UserPromptSubmit  : hook 진입점 (PY 형식이면 hook_bridge.py도 함께)\n"
            "  - PreToolUse        : matcher \"Edit|Write|Bash\"\n"
            "  - PostToolUse       : matcher \"Edit|Write|Bash|NotebookEdit\"\n"
            "  - Stop              : hook 진입점 (PY 형식이면 claude_hook.py stop도 함께)\n\n"
            "【검증 보고】\n"
            "  - 사용한 진입점 (PY/EXE + 경로 + 어떤 우선순위로 찾았는지)\n"
            "  - 등록된 이벤트 4개 체크리스트 ✅/❌\n"
            "  - 다음 Claude Code 재시작부터 적용된다는 안내\n\n"
            "【원칙】\n"
            "- 절대 경로를 직접 박지 말고 자동 탐색 결과를 사용 (다른 PC 호환)\n"
            "- 기존 hooks 키가 있으면 머지만 (다른 hook 절대 삭제 금지)\n"
            "- 백업 없이 수정 금지 (`settings.local.json.bak.YYYYMMDDHHmmss`)\n"
            "- 멱등성: 같은 진입점을 가리키는 명령은 따옴표/슬래시 차이를 무시하고 중복 제거\n"
            "- 설치 EXE 단독 PC: scripts/ 폴더가 외부에 없어도 `vibe-coding.exe hook`만으로 작동"
        ),
    },
    # ── 9단계: 스킬/Subagent 설치 (외부 프로젝트에 vibe-* 슬래시 명령 + subagent 복사) ──────
    {
        "id": "skills-install",
        "agent": "Claude Code",
        "category": "setup",
        "description": "⑨ 스킬/Subagent 설치 — vibe-* 슬래시 명령(brainstorm/write-plan/code-review 등)과 code-reviewer/security-auditor/debugger subagent를 이 프로젝트에 복사",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트(외부 프로젝트일 수 있음)의 .claude/skills/와 .claude/agents/에\n"
            "비이브 코딩이 제공하는 12개 스킬과 3개 subagent를 복사해줘. 이게 있어야\n"
            "외부 프로젝트에서도 `/vibe-brainstorm`, `/vibe-code-review` 같은 slash 명령이\n"
            "동작하고 code-reviewer/security-auditor/debugger 위임이 작동한다.\n\n"
            "【권장 — install_skills.py 사용】\n"
            "수동으로 파일을 옮기지 말고 비이브 코딩이 제공하는 스크립트를 호출해:\n"
            "  python <비이브-코딩>/scripts/install_skills.py --target {project_path}\n"
            "이 스크립트가 자동 탐색 + 멱등 비교 + 백업 + 복사를 전부 수행한다.\n"
            "dry-run으로 선검증 후 실행: `--dry-run` 플래그 추가.\n\n"
            "【진입점 자동 탐색 우선순위】\n"
            "스크립트는 다음 순서로 비이브 코딩 저장소 루트를 찾는다 (.claude/skills/ +\n"
            ".claude/agents/ 둘 다 있어야 OK):\n"
            "  (a) 환경변수 VIBE_HOME — 비이브 코딩 루트 디렉토리 직접 지정\n"
            "  (b) PATH의 vibe-coding[.exe] 옆/부모/조부모에 .claude/ 있는지 확인\n"
            "  (c) 표준 설치 경로 후보 순회:\n"
            "      C:/Program Files/vibe-coding/\n"
            "      %LOCALAPPDATA%/Programs/vibe-coding/\n"
            "      D:/vibe-coding/\n"
            "      C:/vibe-coding/\n"
            "  (d) 모두 실패 시 중단 — 사용자에게 VIBE_HOME 설정 안내 (추측 금지)\n\n"
            "【복사 정책】\n"
            "  - 멱등성: 대상이 이미 최신이면 SKIP (filecmp.dircmp 재귀 비교)\n"
            "  - 다른 내용이 있으면 백업 후 덮어쓰기 (.bak.YYYYMMDDHHmmss 디렉토리)\n"
            "  - 자기 자신을 자기 자신에 설치 시도하면 no-op (저장소 본인이 대상)\n\n"
            "【검증 보고】\n"
            "  - 사용한 vibe-coding 루트 (어떤 우선순위로 찾았는지)\n"
            "  - 복사된 항목 수 (skills 12개 + agents 3개 기준)\n"
            "  - 백업 폴더명 (있으면)\n"
            "  - 다음 Claude Code 재시작부터 /vibe-* 명령이 동작한다는 안내\n\n"
            "【원칙】\n"
            "- 절대 경로를 직접 박지 말고 자동 탐색 결과 사용 (다른 PC 호환)\n"
            "- 기존 사용자 커스텀이 있을 수 있으니 백업 없이 덮어쓰기 금지\n"
            "- 멱등성: 매번 실행해도 변경 없으면 백업 안 만든다 (디스크 절약)\n"
            "- ⑤ hive-hooks와 짝 — 메모리 인프라 + 슬래시 명령이 함께 있어야 외부 프로젝트에서\n"
            "  '바이브 코딩처럼' 작업 가능"
        ),
    },
    # ── 규칙 파일 생성 (기존) ─────────────────────────────────────────
    {
        "id": "claude-rules",
        "agent": "Claude Code",
        "category": "rules",
        "description": "CLAUDE.md + .claude/rules/ 자동 생성",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
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
        "category": "rules",
        "description": "GEMINI.md 자동 생성",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
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
        "category": "rules",
        "description": "AGENTS.md 자동 생성",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
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
        # {project_path} 플레이스홀더를 실제 프로젝트 경로로 치환
        project_path = str(_PROJECT_ROOT)
        prompts = []
        for p in RULE_SETUP_PROMPTS:
            resolved = {**p, "prompt": p["prompt"].replace("{project_path}", project_path)}
            prompts.append(resolved)
        _json_response(handler, {"prompts": prompts})
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
