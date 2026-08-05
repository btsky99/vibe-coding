"""
FILE: api/install_api.py
DESCRIPTION: 다른 프로젝트에 Vibe Coding 스킬셋(.gemini/scripts/*.md)을 복사 설치하는 라우트 핸들러.
             대상에 PROJECT_MAP.md가 없으면 파일 구조를 분석해 자동 생성하고, 하이브 워치독 동작을
             위해 대상의 .ai_monitor/data DB 스키마를 초기화한다. server.py do_GET에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_GET '/api/install-skills' 163줄 블록 분리(라운드2).
  ensure_schema/base_dir/scripts_dir는 순환 import 회피 위해 파라미터로 주입. 로직 원본 그대로.
- 2026-07-06 Claude: Phase 2 R2 — 도구 설치 라우트 6종 이전(tool-status/install-tool-status/
  install-*-cli/register-codex-to-ai + POST install-playwright-cli/run-script). server.py 전역
  헬퍼(_tool_status/_get_npm_executable/_current_project_root 등)는 순환 import 회피 위해 전부
  파라미터 주입. 각 라우트 본문 verbatim 이전(동작 불변).
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지


def install_skills(handler, base_dir: Path, scripts_dir, ensure_schema) -> None:
    """GET /api/install-skills?path=<대상> — 스킬셋 복사 + PROJECT_MAP 보장 + DB 초기화.
    [배포 범용화] scripts_dir가 None(번들에 scripts 없음)이면 scripts 복사 skip.
    [과거사고] exe 번들에 PROJECT_MAP.md 부재 시 대상 프로젝트 '빨간불' → 없으면 구조 분석 자동 생성.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    query = parse_qs(handler.path.split('?', 1)[1] if '?' in handler.path else '')
    target_path = query.get('path', [''])[0]

    result = {"status": "error", "message": "Invalid path"}
    if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
        try:
            source_base = base_dir.parent

            # .gemini 복사
            antigravity_src = source_base / ".gemini"
            if antigravity_src.exists():
                shutil.copytree(antigravity_src, Path(target_path) / ".gemini", dirs_exist_ok=True)

            # scripts 복사 — 배포 범용화: scripts_dir이 None이면 skip
            if scripts_dir and scripts_dir.exists():
                shutil.copytree(scripts_dir, Path(target_path) / "scripts", dirs_exist_ok=True)

            # GEMINI.md 복사
            antigravity_md_src = source_base / "GEMINI.md"
            if antigravity_md_src.exists():
                shutil.copy(antigravity_md_src, Path(target_path) / "GEMINI.md")

            # CLAUDE.md 복사
            claude_md_src = source_base / "CLAUDE.md"
            if claude_md_src.exists():
                shutil.copy(claude_md_src, Path(target_path) / "CLAUDE.md")

            # RULES.md 복사 (누락 방지)
            rules_md_src = source_base / "RULES.md"
            if rules_md_src.exists():
                shutil.copy(rules_md_src, Path(target_path) / "RULES.md")

            # PROJECT_MAP.md 복사 — 소스에 없으면 파일 구조 자동 분석으로 생성
            # [배포 버전] exe 번들에 PROJECT_MAP.md가 없을 때 빨간불 방지
            project_map_dst = Path(target_path) / "PROJECT_MAP.md"
            project_map_src = source_base / "PROJECT_MAP.md"
            if project_map_src.exists():
                shutil.copy(project_map_src, project_map_dst)
            elif not project_map_dst.exists():
                # 실제 프로젝트 파일 구조를 분석하여 PROJECT_MAP.md 자동 생성 (LLM 없이)
                proj_name = Path(target_path).name
                proj_root = Path(target_path)

                IGNORE_DIRS = {
                    '.git', '.ai_monitor', 'node_modules', '__pycache__',
                    '.venv', 'venv', '.ruff_cache', 'dist', 'build',
                    '.cache', '.tox', 'coverage', '.pytest_cache',
                }
                IGNORE_EXTS = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal',
                               '.log', '.tmp', '.exe', '.dll', '.so'}

                # 기술 스택 감지 (특정 파일 존재 여부로 판단)
                tech_hints = []
                if (proj_root / 'package.json').exists():
                    try:
                        pkg = json.loads((proj_root / 'package.json').read_text(encoding='utf-8'))
                        deps = list((pkg.get('dependencies', {}) or {}).keys())
                        if 'react' in deps: tech_hints.append('React')
                        if 'vue' in deps: tech_hints.append('Vue')
                        if 'next' in deps: tech_hints.append('Next.js')
                        if 'vite' in deps or 'vite' in str(pkg.get('devDependencies', {})): tech_hints.append('Vite')
                        if 'typescript' in str(pkg.get('devDependencies', {})): tech_hints.append('TypeScript')
                    except Exception:
                        pass  # package.json 파싱 실패 허용
                    if not tech_hints: tech_hints.append('Node.js')
                if (proj_root / 'requirements.txt').exists() or (proj_root / 'pyproject.toml').exists():
                    tech_hints.append('Python')
                if (proj_root / 'Cargo.toml').exists(): tech_hints.append('Rust')
                if (proj_root / 'go.mod').exists(): tech_hints.append('Go')
                if (proj_root / '.claude').is_dir(): tech_hints.append('Claude Code')
                if (proj_root / '.gemini').is_dir(): tech_hints.append('Gemini')

                # 파일 역할 추론 (파일명 패턴 → 설명)
                FILE_ROLES = {
                    'server.py': 'HTTP/WebSocket 서버 진입점',
                    'main.py': '메인 진입점',
                    'app.py': '앱 진입점',
                    'index.ts': '메인 진입점',
                    'index.js': '메인 진입점',
                    'App.tsx': 'React 루트 컴포넌트',
                    'App.vue': 'Vue 루트 컴포넌트',
                    'package.json': 'Node.js 패키지 설정',
                    'requirements.txt': 'Python 패키지 목록',
                    'pyproject.toml': 'Python 프로젝트 설정',
                    'Cargo.toml': 'Rust 패키지 설정',
                    'go.mod': 'Go 모듈 설정',
                    'CLAUDE.md': 'Claude AI 지침',
                    'GEMINI.md': 'Gemini AI 지침',
                    'RULES.md': 'AI 에이전트 공통 규칙',
                    '.env': '환경 변수 (민감 정보 포함)',
                    'docker-compose.yml': 'Docker Compose 설정',
                    'Dockerfile': 'Docker 빌드 설정',
                }

                structure_lines = []
                key_files = []

                def _scan_dir(path: Path, depth: int, prefix: str = '') -> None:
                    if depth > 2: return
                    try:
                        items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                    except PermissionError:
                        return
                    for item in items:
                        if item.name.startswith('.') and item.name not in ('.claude', '.gemini'):
                            continue
                        if item.is_dir() and item.name in IGNORE_DIRS:
                            continue
                        if item.is_file() and item.suffix in IGNORE_EXTS:
                            continue
                        rel = f"{prefix}{'📁 ' if item.is_dir() else '📄 '}{item.name}"
                        role = FILE_ROLES.get(item.name, '')
                        structure_lines.append(f"- {rel}" + (f" — {role}" if role else ''))
                        if item.is_file() and role:
                            key_files.append((str(item.relative_to(proj_root)), role))
                        if item.is_dir() and depth < 2:
                            _scan_dir(item, depth + 1, prefix + '  ')

                _scan_dir(proj_root, 1)

                tech_str = ' + '.join(tech_hints) if tech_hints else '미확인'
                now_str = datetime.now().strftime('%Y-%m-%d')
                map_content = (
                    f"# 📁 {proj_name} — PROJECT MAP\n\n"
                    f"> **자동 생성:** {now_str} (Vibe Coding 스킬 복구)\n"
                    f"> 이 파일은 프로젝트 파일 구조를 분석하여 자동으로 생성되었습니다.\n"
                    f"> 내용을 검토하고 필요한 부분을 보완해주세요.\n\n"
                    f"## 기술 스택\n\n"
                    f"- **감지된 기술:** {tech_str}\n\n"
                    f"## 프로젝트 구조\n\n"
                    + ('\n'.join(structure_lines[:60]) or '- (파일 없음)')
                    + '\n\n'
                    + (
                        "## 핵심 파일\n\n"
                        + '\n'.join(f"- `{f}` — {r}" for f, r in key_files[:20])
                        + '\n'
                        if key_files else
                        "## 핵심 파일\n\n- (자동 감지 없음 — 직접 기록해주세요)\n"
                    )
                )
                project_map_dst.write_text(map_content, encoding='utf-8')

            # 대상 프로젝트의 .ai_monitor/data 폴더와 DB 초기화
            # — 스킬 설치 후 하이브 워치독이 정상 동작하려면 DB가 있어야 함
            target_data = Path(target_path) / ".ai_monitor" / "data"
            target_data.mkdir(parents=True, exist_ok=True)
            ensure_schema(target_data)

            result = {"status": "success", "message": f"Skills installed to {target_path}"}
        except Exception as e:
            result = {"status": "error", "message": str(e)}

    handler.wfile.write(json.dumps(result).encode('utf-8'))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 R2 — 도구 설치 라우트 이전 (server.py do_GET/do_POST → 여기로)
# [WHY] server.py 1500줄 초과 분할. 각 함수는 원본 인라인 블록을 verbatim 이전 —
#   동작 완전 불변. server.py 전역 헬퍼(_tool_status/_get_npm_executable 등)는
#   순환 import 회피 위해 호출부(server.py wrapper)에서 파라미터로 주입한다.
# ─────────────────────────────────────────────────────────────────────────────


def tool_status(handler, parsed_path, tool_status_fn) -> None:
    """GET /api/tool-status?name=<tool> — 단일 도구 설치/버전 상태.
    [주입] tool_status_fn = server._tool_status (도구명 → 상태 dict)."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    query = parse_qs(parsed_path.query)
    tool_name = (query.get('name') or [''])[0].strip().lower()
    handler.wfile.write(json.dumps(tool_status_fn(tool_name), ensure_ascii=False).encode('utf-8'))


def install_tool_status(handler, parsed_path, get_tool_install_state_fn) -> None:
    """GET /api/install-tool-status?name=<tool> — 설치 진행 상태 조회.
    [주입] get_tool_install_state_fn = server._get_tool_install_state."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    query = parse_qs(parsed_path.query)
    tool_name = (query.get('name') or [''])[0].strip().lower()
    handler.wfile.write(json.dumps(get_tool_install_state_fn(tool_name), ensure_ascii=False).encode('utf-8'))


def handle_install_cli(handler, path, get_npm_executable_fn) -> None:
    """GET /api/install-{gemini-cli,claude-code,codex-cli} — 별도 cmd 창에서 npm install -g 실행.
    [복합조건 잔류] 라우트 매칭(path in 튜플 3종)은 server.py legacy elif에 남고 본문만 여기로 이전
    (R9에서 복합조건 wrapper 테이블화 예정). [주입] get_npm_executable_fn = server._get_npm_executable.
    [제약] Windows 전용 — `start cmd.exe /k`로 사용자가 진행 상황을 눈으로 확인."""
    # 터미널 창을 띄워서 npm install -g 실행 — 사용자가 진행 상황을 직접 확인
    # 🔴 [불변식] 여기는 **npm 배포가 있는 도구만** 등록한다. Antigravity(`agy`)는 npm
    #   배포가 없어 공식 인스톨러 전용이며 /api/install-antigravity(=install_antigravity)로
    #   따로 처리한다. 과거 @google/gemini-cli를 Antigravity로 오등록해 영구 실패했다.
    _install_map = {
        '/api/install-gemini-cli': ('gemini', '@google/gemini-cli', 'Gemini CLI'),
        '/api/install-claude-code': ('claude', '@anthropic-ai/claude-code', 'Claude Code'),
        '/api/install-codex-cli': ('codex', '@openai/codex', 'Codex CLI'),
    }
    _tool_key, _pkg, _display = _install_map[path]
    try:
        _npm = get_npm_executable_fn()
        if not _npm:
            raise FileNotFoundError('npm 실행 파일을 찾을 수 없습니다. Node.js가 설치되어 있는지 확인하세요.')
        _title = f"[{_display} 설치]"
        _cmd = (
            f'start "{_title}" cmd.exe /k "'
            f'title {_title} && '
            f'echo ========================================= && '
            f'echo   {_display} 설치를 시작합니다... && '
            f'echo ========================================= && '
            f'echo. && '
            f'"{_npm}" install -g {_pkg} && '
            f'echo. && echo ✅ {_display} 설치가 완료되었습니다! || '
            f'echo. && echo ❌ {_display} 설치에 실패했습니다."'
        )
        subprocess.Popen(_cmd, shell=True)
        result = {'status': 'success', 'message': f'{_display} 설치 터미널이 열렸습니다.'}
    except Exception as exc:
        result = {'status': 'error', 'message': str(exc)}
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def install_antigravity(handler) -> None:
    """GET /api/install-antigravity — Antigravity CLI(`agy`)를 공식 인스톨러로 설치.

    [WHY 별도 라우트] handle_install_cli는 `npm install -g` 전용이다. Antigravity는 npm
      배포가 없어(2026-08-05 npm view 실측: @google/gemini-cli의 bin은 `gemini` 하나뿐)
      그 경로로 흘리면 엉뚱한 패키지를 깔고 `agy`가 없어 영구 실패한다.
    [불변식] 설치 실행은 tools_api.launch_tool_installer가 유일 경로 — frozen 경로 탐색과
      Python 선택 규칙이 한 곳에만 있어야 개발/EXE 모드가 어긋나지 않는다.
    """
    from api import tools_api
    result = tools_api.launch_tool_installer('antigravity')
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def register_codex_to_ai(handler, python_runner_cmds_fn, base_dir: Path, project_root: Path) -> None:
    """GET /api/register-codex-to-ai — codex_wrapper.py --install로 MCP 서버 등록.
    [주입] python_runner_cmds_fn=server._python_runner_cmds, base_dir=server.BASE_DIR,
    project_root=server.PROJECT_ROOT. [제약] input='all\\n'으로 모든 대상(Antigravity/Claude Desktop)에 등록."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        python_cmds = python_runner_cmds_fn()
        wrapper_script = str(base_dir / 'bin' / 'codex_wrapper.py')
        last_error = ''
        for python_cmd in python_cmds:
            # [WHY] 사용자 눈에 안 보이는 백그라운드 등록 호출 — proc.run이 콘솔 숨김 주입.
            # 지역변수명은 completed로 — 모듈 proc(래퍼) 및 dict result와 충돌 방지.
            completed = proc.run(
                [python_cmd, wrapper_script, '--install'],
                input='all\n',
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(project_root),
            )
            output = completed.stdout.strip() or completed.stderr.strip()
            if completed.returncode == 0:
                result = {"status": "success", "message": f"Antigravity CLI & Claude Desktop에 vibe-coding MCP 등록 완료!\n{output}"}
                break
            last_error = output or f"등록 실패 (exit code {completed.returncode})"
        else:
            result = {"status": "error", "message": last_error or "사용 가능한 Python 실행기를 찾지 못했습니다."}
    except subprocess.TimeoutExpired:
        result = {"status": "error", "message": "등록 시간 초과 (30초)"}
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def install_playwright_cli(handler, current_project_root_fn, resolve_script_fn,
                           project_python_runner_cmds_fn) -> None:
    """POST /api/install-playwright-cli — 대상 프로젝트에서 Playwright + Chromium 설치(새 콘솔 창).
    [주입] current_project_root_fn=server._current_project_root,
    resolve_script_fn=server._resolve_playwright_install_script,
    project_python_runner_cmds_fn=server._project_python_runner_cmds.
    [제약] project_path body로 대상 override 가능 — 없으면 활성 프로젝트 루트 사용."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        payload = {}
        if content_length > 0:
            payload = json.loads(handler.rfile.read(content_length).decode('utf-8') or '{}')

        project_root = current_project_root_fn()
        requested_root = str(payload.get('project_path', '')).strip()
        if requested_root:
            requested_path = Path(requested_root).expanduser()
            if requested_path.is_dir():
                project_root = requested_path.resolve()

        script_path = resolve_script_fn()
        if not script_path:
            raise RuntimeError('install_playwright_cli.py not found')

        python_cmd = project_python_runner_cmds_fn(project_root)[0]
        install_cmd = subprocess.list2cmdline([python_cmd, str(script_path)])
        cmdline = (
            'title Vibe Coding - Playwright Installer && '
            'echo Working directory: %CD% && '
            'echo. && '
            'echo Installing Playwright CLI and Chromium browser... && '
            f'{install_cmd} && '
            'echo. && echo Playwright installation completed. You can close this window. || '
            'echo. && echo Playwright installation failed. Review the log above before closing this window.'
        )
        create_new_console = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x00000010)
        subprocess.Popen(
            ['cmd.exe', '/k', cmdline],
            cwd=str(project_root),
            close_fds=True,
            creationflags=create_new_console,
        )
        handler.wfile.write(json.dumps({
            "status": "success",
            "message": f"Playwright installation started for {project_root}. A console window was opened so you can inspect the result.",
            "project_path": str(project_root),
            "python": python_cmd,
        }, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({
            "status": "error",
            "message": str(e),
        }, ensure_ascii=False).encode('utf-8'))


def run_script(handler, current_project_root_fn) -> None:
    """POST /api/run-script — 화이트리스트 하네스 스크립트 실행(harness_verify/session_init/harness_init).
    [주입] current_project_root_fn=server._current_project_root.
    [제약] EXE(frozen) 모드 or script=None이면 실행 대신 Claude Code 프롬프트 안내(status=prompt).
    개발 모드에서만 실제 subprocess 실행. 화이트리스트 밖 script는 ValueError."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        payload = json.loads(handler.rfile.read(content_length).decode('utf-8') or '{}') if content_length > 0 else {}
        script_name = payload.get('script', '')
        # 허용된 스크립트 목록 및 Claude Code 프롬프트 매핑
        _ALLOWED_SCRIPTS = {
            'harness_verify': {
                'script': 'scripts/harness_verify.py',
                'args': ['--json'],
                'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 다음을 입력하세요:\n\npython scripts/harness_verify.py --json',
            },
            'session_init': {
                'script': 'scripts/session_init.py',
                'args': ['--agent', 'claude'],
                'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 다음을 입력하세요:\n\npython scripts/session_init.py --agent claude',
            },
            'harness_init': {
                'script': None,
                'prompt': '해당 프로젝트 폴더에서 Claude Code를 실행한 뒤 /vibe-harness-init 명령을 입력하세요.',
            },
        }
        if script_name not in _ALLOWED_SCRIPTS:
            raise ValueError(f'허용되지 않은 스크립트: {script_name}')
        info = _ALLOWED_SCRIPTS[script_name]
        script_rel = info['script']
        # EXE(설치) 모드: 스크립트 실행 대신 Claude Code 프롬프트 안내
        if getattr(sys, 'frozen', False) or script_rel is None:
            handler.wfile.write(json.dumps({
                "status": "prompt",
                "output": info['prompt'],
            }, ensure_ascii=False).encode('utf-8'))
        else:
            # 개발 모드: 직접 스크립트 실행
            project_root = current_project_root_fn()
            script_path = project_root / script_rel
            if not script_path.exists():
                raise FileNotFoundError(f'{script_rel} not found')
            result = proc.run(
                [sys.executable, str(script_path)] + info.get('args', []),
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=15, cwd=str(project_root),
            )
            handler.wfile.write(json.dumps({
                "status": "ok" if result.returncode == 0 else "fail",
                "output": result.stdout[:2000],
                "error": result.stderr[:500] if result.returncode != 0 else "",
            }, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({
            "status": "error",
            "message": str(e),
        }, ensure_ascii=False).encode('utf-8'))
