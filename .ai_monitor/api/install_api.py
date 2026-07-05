"""
FILE: api/install_api.py
DESCRIPTION: 다른 프로젝트에 Vibe Coding 스킬셋(.gemini/scripts/*.md)을 복사 설치하는 라우트 핸들러.
             대상에 PROJECT_MAP.md가 없으면 파일 구조를 분석해 자동 생성하고, 하이브 워치독 동작을
             위해 대상의 .ai_monitor/data DB 스키마를 초기화한다. server.py do_GET에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_GET '/api/install-skills' 163줄 블록 분리(라운드2).
  ensure_schema/base_dir/scripts_dir는 순환 import 회피 위해 파라미터로 주입. 로직 원본 그대로.
"""
from __future__ import annotations

import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs


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
