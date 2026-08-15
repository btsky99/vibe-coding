"""
FILE: api/tools_api.py
DESCRIPTION: AI 도구 CLI 설치 관리 API.
             대시보드에서 gh CLI, Playwright CLI, Codex CLI 등
             필요한 개발 도구의 설치 상태를 확인하고 원클릭 설치를 제공한다.

             GET  /api/tools/status   — 전체 도구 설치 상태 목록 반환
             POST /api/tools/install  — 특정 도구 설치 실행 (새 콘솔 창)

REVISION HISTORY:
- 2026-08-14 Claude: launch_ai_toolchain_installer에 visible 인자 — 자동(사람이 안 누른)
                     경로는 콘솔 창 없이 로그 파일로만(절대 규칙 10).
- 2026-07-29 Codex: Replace Gemini compatibility with official Antigravity CLI.
- 2026-07-29 Codex: Add one sequential first-run installer for Node.js and all AI CLIs.
- 2026-07-28 Codex: Expose an installer launcher for first-run automatic dependency repair.
- 2026-07-28 Codex: Accept Gemini CLI as the Antigravity compatibility command.
- 2026-04-05 Claude Opus 4.6: 최초 ���성 — 도�� 설치 통합 API
- 2026-04-05 Claude Opus 4.6: psql, ruff, uv, pytest, pyinstaller 도구 추가 (Gemini 추천 반영)
- 2026-04-05 Claude Opus 4.6: 전체 도구 install_hint 추가 + Git, Python, TypeScript, Vite, ESLint, Tailwind CSS, Inno Setup, Pillow, Claude/Gemini/Node.js 자동 설치 지원
- 2026-06-21 Claude Opus 4.8: 세팅 프롬프트 ⑥ AI 에이전트 CLI 설치 추가 — TOOL_REGISTRY엔
  claude/codex/antigravity 설치가 있었으나 세팅 마법사 흐름(①~⑩)엔 누락돼 있어 보강
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from infra import env_path  # 설치 직후 PATH 재병합 — 재시작 없이 감지하기 위해 필수
from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
from infra import runtime  # 쓰기 가능한 데이터 디렉토리(설치 로그·마커) 단일 출처

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
        "id": "antigravity",
        "name": "Antigravity CLI",
        "description": "Google Antigravity AI 코딩 에이전트",
        "check_commands": [["agy", "--version"]],
        "check_paths": [],
        "install_script": "install_antigravity.py",
        "install_url": "https://antigravity.google/cli",
        "install_hint": "irm https://antigravity.google/cli/install.ps1 | iex",
        "category": "ai-agent",
        # Phase 2 정직성 — 사용자 수동 실행 시만 참여. 자동 디스패처는 라벨링 유지.
        "experimental": True,
    },
    {
        "id": "nodejs",
        "name": "Node.js / npm",
        "description": "JavaScript 런타임 — Codex, Antigravity CLI 등의 사전 요구사항",
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
    # ── Python 개발 도구 (Antigravity 추천) ────────────────────────────────
    {
        "id": "ruff",
        "name": "Ruff",
        "description": "Python 린팅 + 포맷팅 (Rust 기반, 초고속) — Antigravity 추천",
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
        "description": "Python 단위 테스트 프레임워크 — Antigravity 추천",
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
        # [2026-08-15] 기본 설치팩(core_ids)에 편입 — wiki/ 백과사전을 **사람이 읽는 창**.
        #   지식은 마크다운 파일이라 옵시디언 없이도 LLM 회상은 완전히 동작하지만
        #   (3층 구조의 ③은 선택), 사람 쪽 입구가 없으면 위키를 고칠 일이 없어져
        #   창고가 다시 로그 덤프로 썩는다.
        "id": "obsidian",
        "name": "Obsidian",
        "description": "지식 창고(wiki/)를 사람이 읽고 고치는 뷰어 — 마크다운 로컬 저장",
        # [🔴 규칙 10] check_commands 를 비운다. GUI(Electron) 앱은 --version 인자를
        #   무시하고 **창을 띄운다**. 도구 상태는 폴링으로 반복 조회되므로 그대로 두면
        #   사용자가 안 눌러도 창이 계속 뜬다. 경로 존재만으로 판정한다.
        "check_commands": [],
        "skip_version_probe": True,
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
    # [과거사고 2026-08-05] 설치 성공에도 '설치 필요'로 고착되던 원인 — 서버 프로세스 PATH가
    #   기동 시점 스냅샷이라 설치기가 새로 추가한 bin 디렉토리를 못 봤다. TTL 캐시가 있어
    #   도구 수만큼 불려도 레지스트리 읽기는 폴링당 1회로 수렴한다.
    env_path.refresh_path()

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

            result = proc.run(
                resolved_cmd, capture_output=True, text=True, timeout=10,
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
                # [🔴 규칙 10] GUI 앱은 --version 을 줘도 인자를 무시하고 **창을 띄운다**
                #   (Electron 계열이 특히). 상태 조회는 5초 폴링이라 그대로 두면 창이
                #   반복해서 뜬다 — 사용자가 안 누른 실행은 창을 만들지 않는다.
                #   존재 = 설치됨으로 판정하고 프로브를 건너뛴다.
                if tool.get("skip_version_probe"):
                    version = f"설치됨 ({Path(path).name})"
                    break
                try:
                    result = proc.run(
                        [path, "--version"], capture_output=True, text=True, timeout=10,
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


def launch_tool_installer(tool_id: str) -> dict[str, Any]:
    """등록된 도구 설치기를 새 콘솔에서 실행하고 구조화된 결과를 반환한다.

    Setup Doctor와 수동 설치 API가 같은 실행 경로를 사용해야 설치 명령, frozen 경로
    탐색, Python 선택 규칙이 서로 어긋나지 않는다.
    """
    tool_def = next((tool for tool in TOOL_REGISTRY if tool["id"] == tool_id), None)
    if not tool_def:
        return {"status": "error", "message": f"알 수 없는 도구: {tool_id}"}

    script_name = tool_def.get("install_script")
    if not script_name:
        return {
            "status": "manual",
            "message": f"{tool_def['name']}은(는) 수동 설치가 필요합니다.",
            "install_url": tool_def.get("install_url", ""),
            "install_hint": tool_def.get("install_hint", ""),
        }

    script_path = _find_install_script(script_name)
    if not script_path:
        return {
            "status": "error",
            "message": f"설치 스크립트를 찾을 수 없습니다: {script_name}",
        }

    try:
        # [불변식] 자식 콘솔은 이 프로세스 PATH를 상속 — spawn 전에 최신화(위 주석 참조).
        env_path.refresh_path(force=True)
        python_cmd = _get_python_cmd()
        cmd_parts = [python_cmd, str(script_path), *tool_def.get("install_args", [])]
        install_cmd = subprocess.list2cmdline(cmd_parts)
        tool_name = tool_def["name"]
        cmdline = (
            f"title Vibe Coding - {tool_name} Installer && "
            f"echo ============================================ && "
            f"echo   {tool_name} 자동 설치 중... && "
            f"echo ============================================ && echo. && "
            f"{install_cmd} && echo. && echo {tool_name} 설치 완료. || "
            f"echo. && echo {tool_name} 설치 실패. 위 로그를 확인하세요."
        )
        subprocess.Popen(
            ["cmd.exe", "/k", cmdline],
            cwd=str(_PROJECT_ROOT),
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        )
        return {
            "status": "success",
            "message": f"{tool_name} 자동 설치를 시작했습니다.",
            "tool": tool_id,
            "script": str(script_path),
            "python": python_cmd,
        }
    except Exception as exc:
        return {"status": "error", "message": f"설치 실행 실패: {exc}"}


def toolchain_install_log_path() -> Path:
    """무창(silent) 자동 설치의 출력이 쌓이는 로그 경로."""
    return runtime.app_data_dir() / "logs" / "ai_toolchain_install.log"


def launch_ai_toolchain_installer(visible: bool = True) -> dict[str, Any]:
    """Node.js와 세 AI CLI의 누락분을 순차 자동 설치한다.

    [규칙 10] visible=False는 **사용자가 안 누른** 자동 실행 경로다 — 콘솔 창을 만들지
      않고 로그 파일로만 남긴다. 자동 설치가 cmd 창을 띄우면 앱을 켤 때마다 포커스를
      빼앗겨 타이핑이 끊긴다(콘솔 깜빡임 사고 계열). 진행 상황은 배너가
      /api/setup/status를 3초 폴링해 보여주므로 창 없이도 사용자에게 보인다.
    [주의] visible=True(배너 버튼 클릭)는 사람이 결과를 보려고 누른 것이라 창을 그대로 연다.
    """
    script_path = _find_install_script("install_ai_toolchain.py")
    if not script_path:
        return {"status": "error", "message": "AI 도구 자동 설치 스크립트를 찾을 수 없습니다."}
    try:
        # [불변식] spawn 직전에 force refresh — 자식 콘솔은 이 프로세스의 PATH를 **상속**한다.
        #   서버가 낡은 PATH를 들고 있으면 자식도 낡은 PATH로 시작해 이미 깔린 도구를
        #   '미설치'로 오판하고 재설치를 돈다.
        env_path.refresh_path(force=True)
        runner = sys.executable if getattr(sys, "frozen", False) else _get_python_cmd()

        if not visible:
            log_path = toolchain_install_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a", encoding="utf-8", errors="replace")
            try:
                log_file.write(
                    f"\n===== 자동(무창) AI 도구 설치 시작 "
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} — runner={runner} =====\n"
                )
                log_file.flush()
                # [제약] proc.popen이 CREATE_NO_WINDOW를 넣는다 — 여기서 인라인 플래그 금지.
                #   자식이 다시 npm.cmd 등을 부르면 그 손자에는 상속되지 않으므로,
                #   install_ai_toolchain.py 쪽도 infra.proc를 써야 완전히 무창이다.
                proc.popen(
                    [runner, str(script_path)],
                    cwd=str(_PROJECT_ROOT),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                )
            finally:
                # 자식이 핸들을 dup했으므로 부모 사본은 닫는다(핸들 누수 방지).
                log_file.close()
            return {
                "status": "success",
                "mode": "silent",
                "log": str(log_path),
                "message": "필수 AI 도구를 백그라운드에서 설치 중입니다.",
            }

        install_cmd = subprocess.list2cmdline([runner, str(script_path)])
        cmdline = (
            "title Vibe Coding - AI Toolchain Auto Installer && "
            "echo Vibe Coding 필수 도구를 자동으로 확인하고 설치합니다. && echo. && "
            f"{install_cmd} && echo. && echo 전체 자동 설치가 완료되었습니다. || "
            "echo. && echo 일부 설치가 실패했습니다. 위 로그를 확인하세요."
        )
        subprocess.Popen(
            ["cmd.exe", "/k", cmdline],
            cwd=str(_PROJECT_ROOT),
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        )
        return {"status": "success", "mode": "console",
                "message": "필수 AI 도구 자동 설치를 시작했습니다."}
    except Exception as exc:
        return {"status": "error", "message": f"AI 도구 자동 설치 실행 실패: {exc}"}


# [중복통합 2026-07-18] _json_response는 api/_common.py로 통합 — 패스스루 재노출.
from api._common import json_response as _json_response


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
    # ── 6단계: AI 에이전트 CLI 설치 (Claude / Codex / Antigravity) ──────
    # [2026-06-21 Claude] TOOL_REGISTRY엔 claude/codex/antigravity 원클릭 설치가 있으나
    #   세팅 마법사 흐름엔 "AI CLI 깔아라" 단계가 없어 사용자가 ① dev-tools만 따라가면
    #   정작 에이전트 CLI는 안 깔리던 누락. 흐름 안에 명시.
    {
        "id": "ai-cli",
        "agent": "공통 (아무 에이전트)",
        "category": "setup",
        "description": "⑥ AI 에이전트 CLI 설치 — Claude Code / Codex / Antigravity(구 Gemini) CLI를 이 PC에 전역 설치",
        "prompt": (
            "【대상】이 PC 전역 (AI 에이전트 CLI는 npm -g 전역 설치 — 프로젝트가 아니라 PC 단위)\n\n"
            "이 PC에 AI 코딩 에이전트 CLI 3종을 설치해줘. 비이브 코딩 하이브는 이 CLI들이\n"
            "있어야 멀티 에이전트로 동작한다. (대시보드 상단 '도구 설치 상태' 그리드의\n"
            "원클릭 설치 버튼으로도 동일하게 깔 수 있다 — 그쪽이 편하면 그걸 써도 됨.)\n\n"
            "【사전 조건】\n"
            "- Node.js >= 20 + npm (세팅 ① 개발도구 단계에서 설치됨 — 없으면 먼저 깔 것)\n\n"
            "【설치 대상 (이미 깔린 건 건너뛰기 — `<cmd> --version`으로 먼저 확인)】\n"
            "  1) Claude Code  — npm install -g @anthropic-ai/claude-code\n"
            "       검증: claude --version / 인증: claude  (최초 실행 시 OAuth 로그인)\n"
            "  2) Codex CLI    — npm install -g @openai/codex\n"
            "       검증: codex --version / 인증: OpenAI API 키 또는 codex 로그인 절차\n"
            "  3) Antigravity  — irm https://antigravity.google/cli/install.ps1 | iex   (Windows)\n"
            "                     curl -fsSL https://antigravity.google/cli/install.sh | bash  (macOS/Linux)\n"
            "       검증: agy --version / 인증: agy  (최초 실행 시 OAuth 로그인)\n"
            "       🔴 주의: Antigravity는 npm 배포가 **없다**. `npm i -g @google/gemini-cli`는\n"
            "          `gemini` 명령만 만들고 `agy`는 안 생긴다(2026-08-05 npm view 실측).\n"
            "          구 Gemini CLI와 다른 별개 도구다 — 공식 인스톨러만 쓸 것.\n\n"
            "【설치 후】\n"
            "  - 각 CLI를 `--version`으로 ✅/❌ 요약\n"
            "  - 인증이 필요한 CLI는 사용자에게 로그인 명령을 안내 (자동 로그인 시도 금지)\n\n"
            "【원칙】\n"
            "- 이미 설치된 CLI는 재설치하지 않기 (버전만 확인)\n"
            "- 전역 설치(npm -g)라 관리자 권한이 필요할 수 있음 — 실패 시 권한 안내\n"
            "- Phase 2 정직성: 현재 자동 디스패처는 Claude만 활성. Codex/Antigravity는\n"
            "  사용자가 수동 실행할 때만 하이브에 참여한다 (설치는 해두되 기대치는 정직하게)"
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
    # ── 10단계: 상태줄 설치 (Claude Code 커스텀 상태줄 — PC 전역, 다른 PC 호환) ──────
    {
        "id": "statusline-install",
        "agent": "Claude Code",
        "category": "setup",
        "description": "⑩ 상태줄 설치 — 컨텍스트 사용량 히트맵 박스 그래프(녹→황→적) + 모델/토큰/세션 I/O를 이 PC의 Claude Code 상태줄에 등록",
        "prompt": (
            "【대상】이 PC의 사용자 전역 설정(~/.claude) — 프로젝트가 아니라 PC(터미널) 단위\n\n"
            "비이브 코딩 커스텀 상태줄을 이 PC에 깔아줘. 깔면 Claude Code 터미널에 컨텍스트\n"
            "사용량 히트맵 박스 그래프(⛶→⛁, 녹→노랑→빨강 그라데이션)와 모델·토큰·세션 I/O가\n"
            "표시돼. 개발버전이든 설치(EXE)버전이든 같은 ~/.claude를 읽어 둘 다 동일하게 보인다.\n\n"
            "【권장 — install_statusline.py 사용】\n"
            "수동으로 settings.json을 만지지 말고 비이브 코딩이 제공하는 스크립트를 호출해:\n"
            "  python <비이브-코딩>/scripts/install_statusline.py\n"
            "이 스크립트가 statusline.py를 ~/.claude로 복사 + settings.json의 statusLine 키를\n"
            "멱등 머지(백업 포함)한다. dry-run으로 선검증: `--dry-run`, 기존 다른 상태줄 교체: `--force`.\n"
            "※ --target 없음 — PC 전역 설치라 대상 프로젝트 경로가 필요 없다.\n\n"
            "【진입점 자동 탐색 우선순위】\n"
            "비이브 코딩 저장소 루트를 다음 순서로 찾아 그 안의 scripts/install_statusline.py 실행:\n"
            "  (a) 환경변수 VIBE_HOME — 비이브 코딩 루트 직접 지정\n"
            "  (b) PATH의 vibe-coding[.exe] 옆/부모/조부모에 scripts/ 있는지 확인\n"
            "  (c) 표준 설치 경로 후보: C:/Program Files/vibe-coding/,\n"
            "      %LOCALAPPDATA%/Programs/vibe-coding/, D:/vibe-coding/, C:/vibe-coding/\n"
            "  (d) 모두 실패 시 중단 — 사용자에게 VIBE_HOME 설정 안내 (추측 금지)\n\n"
            "【멱등/안전】\n"
            "  - statusline.py는 항상 저장소 버전으로 덮어씀(원본=저장소)\n"
            "  - settings.json statusLine: 없으면 추가, 우리 것이면 경로만 갱신,\n"
            "    다른 커스텀이면 보존(--force로만 교체) — 사용자 설정 유실 금지\n"
            "  - settings.json은 수정 전 .bak.YYYYMMDDHHmmss 백업\n\n"
            "【검증 보고】\n"
            "  - 사용한 vibe-coding 루트 (어떤 우선순위로 찾았는지)\n"
            "  - ~/.claude/statusline.py 복사 여부 + settings.json statusLine 설정 여부\n"
            "  - 다음 Claude Code 재시작(또는 다음 렌더)부터 상태줄이 표시된다는 안내\n\n"
            "【원칙】\n"
            "- 절대 경로를 직접 박지 말고 자동 탐색 결과 사용 (다른 PC 호환 — 바이브 코딩 본질)\n"
            "- 256색 터미널 전제(Claude Code 터미널 지원). ⛶/⛁ 글리프가 깨지면 폰트 문제 안내"
        ),
    },
    # ── 11단계: 지식 그래프 켜기 (프로젝트 단위 — 회상 품질의 마지막 축) ──────────
    # [WHY 이 항목이 필요한가 — 2026-08-11 실측]
    #   훅·로그·메모리는 이미 크로스 프로젝트로 돈다(pg_logs: vibe-coding 44931 / ons 5551,
    #   hive_memory: ons 97 · CipherTrader 36 · k-quant 14). 그런데 zettel_notes 는
    #   **vibe-coding 3346 / 나머지 전부 0** 이었다. 노트를 만드는 것은 훅이 아니라
    #   이 저장소 안의 스킬·스크립트라서, 다른 프로젝트에는 지식 그래프가 아예 생기지 않는다.
    #   즉 다른 프로젝트의 회상은 '경험+메모리'만으로 돌고 그래프 신호가 0이다.
    {
        "id": "knowledge-graph",
        "agent": "Claude Code",
        "category": "setup",
        "description": "⑪ 회상 품질 — 지식 그래프(노트+링크)를 이 프로젝트에도 쌓아 회상이 '말이 비슷한 것'을 넘어 '실제로 이어진 것'을 찾게 한다 ※실행 그래프(⑫)와 다름",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트에 **지식 그래프**를 켜줘. 목적은 하나다 — 다음 세션의 나(LLM)가\n"
            "같은 삽질을 반복하지 않는 것. 노트를 쌓는 게 목적이 아니라 **이어진 노트**를\n"
            "쌓는 게 목적이다.\n\n"
            "【⚠️ '그래프 엔지니어링'과 혼동하지 말 것】\n"
            "  이 항목은 **데이터 모델링**이다 — 무엇을 기억하고 어떻게 이어 두는가(회상 품질).\n"
            "  '그래프 엔지니어링'은 **실행 모델링**이다 — 누가 다음에 뛰는가(노드·엣지·\n"
            "  스테이트·컨디션). 그쪽은 ⑫가 다룬다. 이름이 비슷해 자주 뒤섞이는데,\n"
            "  푸는 문제가 전혀 다르므로 한 항목으로 합치지 말 것.\n\n"
            "【왜 필요한가 — 숫자로】\n"
            "회상은 임베딩 유사도로 돈다. 그런데 실측상 관련 질의 최고 0.688 / 무관 질의\n"
            "최고 0.632 로 간격이 0.056 밖에 안 된다 — 벡터만으로는 이미 한계다.\n"
            "링크는 '말이 비슷한가'가 아니라 '실제로 같이 다뤄졌나'를 담아서, 벡터와\n"
            "**독립적인 신호**가 된다. 고립된 노트는 이 신호에 기여가 0 이다.\n\n"
            "【0. 선행 확인 (없으면 여기서 멈추고 안내)】\n"
            "  - ④ 제텔카스텐 — 볼트 구조/템플릿. 그것은 '그릇'이고 이 항목은 '무엇을\n"
            "    언제 남기고 어떻게 잇는가'다. 그릇만 만들고 끝내면 노트는 안 쌓인다\n"
            "  - ⑤ hive-hooks 가 설치돼 있는가 (회상 주입 경로)\n"
            "  - ⑨ skills-install 로 /vibe-zettel 이 이 프로젝트에서 동작하는가\n"
            "  - 하나라도 없으면 그것부터 안내하고 중단 — 순서를 건너뛰면 노트를\n"
            "    만들어도 회상에 안 실린다\n\n"
            "【🔴 정본은 PostgreSQL 이다 — 볼트 파일이 아니다】\n"
            "  회상은 100% DB(zettel_notes + 임베딩) 경로로 돈다. 옵시디언 볼트는 사람이\n"
            "  들여다보기 위한 **미러**이고, 실측상 LLM 도 사람도 거의 읽지 않는다.\n"
            "  마크다운 파일만 만들고 DB 에 안 들어가면 **회상에 영원히 안 뜬다** —\n"
            "  '분명히 적어뒀는데 왜 기억을 못 하지'의 정체가 대부분 이것이다.\n"
            "  노트를 만들 때는 반드시 DB 에 들어가는 경로(/vibe-zettel · zettel 스크립트)를\n"
            "  쓰고, 파일을 직접 만드는 방식은 쓰지 말 것.\n\n"
            "【1. 소속 확인 — 남의 프로젝트를 오염시키지 않기】\n"
            "  이 프로젝트의 project_id 슬러그가 무엇으로 잡히는지 먼저 확인해 보고해라.\n"
            "  경로 기반 슬러그라 개발본/설치본이 어긋나면 지식이 두 곳으로 갈라진다.\n"
            "  다른 프로젝트 이름이 나오면 그대로 진행하지 말고 원인을 먼저 보고할 것.\n\n"
            "【2. 무엇을 노트로 남기는가 — 이게 핵심이다】\n"
            "  ✅ 남긴다 (코드를 읽어도 알 수 없는 것):\n"
            "     - 왜 이 방식을 택했나 (버린 대안과 그 이유)\n"
            "     - 제약·불변식 (호출 순서, 동시성 가정, 플랫폼 의존)\n"
            "     - 과거 사고와 그 원인 (증상이 아니라 원인)\n"
            "     - 외부 의존의 함정 (라이브러리·OS·CI가 조용히 다르게 도는 지점)\n"
            "  ❌ 남기지 않는다:\n"
            "     - 코드를 읽으면 그대로 나오는 설명 (파일 목록, 함수가 하는 일)\n"
            "     - 세션 요약 남발 — 전례가 있다. 요약이 지식의 65%를 차지해 회상이\n"
            "       쓰레기를 반환했고, 걷어내는 데 별도 작업이 필요했다\n"
            "     - 코드 자체 (git 이 정본이다. 지식 저장소에 코드를 복사하지 말 것)\n\n"
            "【3. 링크 규약 — 고립 노트를 만들지 않는다】\n"
            "  새 노트는 **기존 노트 최소 1개**와 [[노트이름]] 으로 잇는다.\n"
            "  이을 곳이 정말 없으면, 그건 '첫 노트'이거나 주제가 프로젝트와 무관하다는 신호다.\n"
            "  아직 없는 노트를 [[이름]] 으로 가리키는 것은 정상이다 — '나중에 쓸 것' 표시다.\n\n"
            "【4. 언제 쓰는가 — 습관으로 못 박기】\n"
            "  이 프로젝트의 규칙 파일(CLAUDE.md/AGENTS.md 등)에 다음을 추가해라:\n"
            "    - 에러를 고친 직후: 원인과 수정을 노트로 남기고 관련 노트에 잇는다\n"
            "    - 설계를 결정한 직후: 버린 대안을 함께 남긴다\n"
            "  규칙에 없으면 아무도 안 한다 — 이것이 '자동으로'의 실체다.\n\n"
            "【5. 검증 — 여기까지 해야 끝이다】\n"
            "  세팅했다고 끝내지 말고 **실제로 쌓이는지 숫자로** 확인해라:\n"
            "    - 시험 노트를 2개 만들고 서로 잇는다\n"
            "    - 이 프로젝트의 project_id 로 zettel_notes / zettel_links 행이\n"
            "      실제로 늘었는지 조회해 보고한다 (0 이면 세팅이 안 된 것이다)\n"
            "    - 그 노트가 회상으로 돌아오는지 관련 질의로 한 번 확인한다\n"
            "  🔴 이 프로젝트가 반복해서 밟은 함정이다 — 메커니즘이 맞아도 실사용이 0 인\n"
            "     채로 '작동 중'이라 착각한 전례가 여러 번 있다. 계측하지 않으면 모른다.\n\n"
            "【원칙】\n"
            "- 절대 경로를 직접 박지 말 것 (다른 PC·다른 프로젝트 호환)\n"
            "- 기존 규칙 파일을 덮지 말고 항목만 추가 (사용자 커스텀 유실 금지)\n"
            "- 노트 수를 목표로 삼지 말 것. 이어지지 않은 노트 100개보다 이어진 10개가 낫다"
        ),
    },
    # ── 12단계: 그래프 엔지니어링 (실행 모델링 — ⑪ 지식그래프와 다름) ──────────
    # [WHY 별도 항목인가] ⑪은 '무엇을 기억하나'(데이터), 이것은 '누가 다음에 뛰나'(실행)다.
    #   이름이 비슷해 실제로 한 번 뒤섞였다 — 출처 문서가 "GraphRAG와 혼동 금지"를
    #   명시적으로 경고할 만큼 흔한 혼동이라, 두 항목을 나란히 두되 각각에 경계를 적었다.
    # [근거] vibe-coding 자신에게 먼저 적용해 docs/AGENT_GRAPH.md 를 만든 뒤 이 프롬프트를
    #   썼다. 검증 안 된 방법론을 다른 프로젝트에 퍼뜨리지 않기 위한 순서였다.
    {
        "id": "graph-engineering",
        "agent": "Claude Code",
        "category": "setup",
        "description": "⑫ 실행 그래프 선언 — 코드 곳곳에 흩어진 '다음에 무엇이 뛰는가'를 한 곳에 모아 선언한다 (노드·엣지·스테이트·컨디션) ※회상용 지식그래프(⑪)와 다름",
        "prompt": (
            "【대상 프로젝트】{project_path}\n\n"
            "이 프로젝트의 **실행 그래프**를 선언해줘. 새 프레임워크를 도입하라는 게 아니다 —\n"
            "이미 돌고 있는 흐름의 **연결(엣지)이 코드에 흩어져 안 보이는 것**을 한 곳에 모으는\n"
            "일이다. 대부분의 프로젝트는 이미 암묵적 그래프다.\n\n"
            "【⚠️ 지식그래프와 혼동하지 말 것】\n"
            "  ⑪(지식 그래프)은 데이터 모델링 — 무엇을 기억하고 어떻게 이어 두는가.\n"
            "  이 항목은 실행 모델링 — **누가 다음에 뛰는가**. 푸는 문제가 다르다.\n\n"
            "【용어 4가지】\n"
            "  · 노드   = 일하는 단위 (함수·데몬·훅·API·스킬, 그리고 **사람의 확인 단계**)\n"
            "  · 엣지   = 앞 노드의 산출이 뒷 노드의 입력이 되는 길\n"
            "  · 스테이트 = 노드 사이에 전달되는 것 (DB 테이블·커서·설정·파일)\n"
            "  · 컨디션 = 어느 길로 갈지 정하는 규칙 (임계치·재시도 상한·승인 여부)\n\n"
            "【1. 원칙부터 점검 — 판단은 AI, 규칙은 코드, 중요·불가역은 사람】\n"
            "  이 프로젝트에서 다음이 지켜지는지 확인하고 어긋난 곳을 보고해라.\n"
            "    · 셀 수 있는 결정(한도·횟수·임계치)이 AI 판단에 맡겨져 있지 않은가\n"
            "      → 그런 곳은 코드로 내린다. AI가 필요 없는 곳에 AI를 쓰면 비용과\n"
            "        비결정성만 늘어난다\n"
            "    · 불가역한 실행(배포·삭제·외부 전송)에 사람 게이트가 있는가\n\n"
            "【2. 흐름 3~5개만 고른다 — 전부 그리지 말 것】\n"
            "  우선순위는 **사고가 났던 경로**다. 어디가 끊겼는지 몰라 추적에 시간이 든\n"
            "  경험이 있다면 그 흐름이 1순위다. 없으면 '실패하면 어떻게 되는지 설명하기\n"
            "  어려운' 흐름을 고른다.\n"
            "  🔴 전체를 그리려 하지 말 것 — 안 쓰이는 다이어그램은 곧 거짓말이 된다.\n\n"
            "【3. 각 흐름을 이렇게 적는다】\n"
            "  · 노드와 엣지를 화살표로 (텍스트면 충분하다. 그림 도구 불필요)\n"
            "  · 스테이트: 무엇이 노드 사이를 흐르는가\n"
            "  · 컨디션: 분기 기준과 임계치의 **실제 값**\n"
            "  · 🔴 **실패하면 어디로 가는가** — 이게 이 작업의 본체다.\n"
            "       '실패 시 어디로'가 안 적히면 그 배선은 아직 설계되지 않은 것이다.\n\n"
            "【4. 발견한 구멍을 보고해라 (고치는 건 그다음)】\n"
            "  선언하다 보면 다음이 드러난다. 찾으면 **고치기 전에 먼저 보고**해라:\n"
            "    · 주석·문서에만 있고 코드에 없는 방어 (\"~하면 재시도한다\"고 적혀 있는데\n"
            "      실제로는 안 하는 것). 흔하고, 조용해서 위험하다\n"
            "    · 감지만 하고 재시도도 중단도 없는 자리 (로그만 찍고 성공 처리)\n"
            "    · 실패를 삼키는 자리 (예외를 잡아 넘기거나 종료 코드를 덮는 곳)\n\n"
            "【5. 규칙 파일에 한 줄 박기】\n"
            "  이 프로젝트의 규칙 파일(CLAUDE.md/AGENTS.md 등)에 추가:\n"
            "    \"새 배선은 실행 그래프에 '실패하면 어디로'를 먼저 적고 코드를 맞춘다\"\n"
            "  규칙에 없으면 다음 세션은 안 한다.\n\n"
            "【6. 하지 말 것 — 오버엔지니어링 경계】\n"
            "  · 한두 번의 도구 호출로 끝나는 작업을 노드로 쪼개지 말 것\n"
            "  · 노드를 늘리면 디버깅 지점이 늘고 에이전트 수만큼 토큰이 녹는다\n"
            "  · LangGraph 등 프레임워크 도입은 **이 선언을 먼저 해보고** 판단한다.\n"
            "    선언만으로 구멍이 드러나면 그것으로 충분한 경우가 많다\n\n"
            "【검증 보고】\n"
            "  · 선언한 흐름 수와 각각의 노드 개수\n"
            "  · 발견한 구멍 목록 (특히 '주석에만 있는 방어')\n"
            "  · 규칙 파일에 추가한 내용\n\n"
            "【원칙】\n"
            "- 추측으로 그리지 말 것. 실제 코드·설정을 읽어 확인한 연결만 적는다\n"
            "- 그림의 아름다움이 목적이 아니다. '실패 시 어디로'가 없으면 그 줄은 가치가 없다"
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
        "id": "antigravity-rules",
        "agent": "Antigravity CLI",
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
