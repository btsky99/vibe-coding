"""
FILE: .ai_monitor/infra/project_context.py
DESCRIPTION: Platform Phase 2-3 — 활성 프로젝트 컨텍스트 Resolver.
             config.json의 last_path를 기반으로 현재 활성 프로젝트의
             경로/ID를 반환하는 단일 진입점.
             서버·API 모듈·테스트 어디서든 동일 결과를 보장한다.

             [헬퍼 시그니처]
             - current_project_root(default_root, config_file) -> Path
             - current_project_id(default_root, config_file) -> str
             - assert_project_id(project_id, op) -> str  # dev 모드 경고
             - slugify(root) -> str  # 슬러그 변환 단일 구현

             [컨텍스트 미지정 경고]
             - VIBE_DEV_MODE=1 환경변수에서 빈 project_id로 쓰기 시
               stderr에 경고와 호출 스택을 남긴다. 프로덕션은 무동작.

             [가드 사용 예시 — Phase 2-4 패턴]
                 from infra.project_context import assert_project_id

                 def save_task(task: dict, project_id: str = '') -> dict | None:
                     project_id = assert_project_id(project_id, 'save_task')
                     # ... INSERT/UPDATE with project_id

REVISION HISTORY:
- 2026-04-30 Claude: 최초 작성 — Platform Phase 2-3
- 2026-05-02 Claude: Phase 2-4 가드 사용 예시 헤더 추가
- 2026-07-06 Claude: server.py frozen PROJECT_ROOT 해석 3함수 흡수 (Phase 2 Task 13 / R15)
                     find_project_root_marker / resolve_frozen_project_root /
                     persist_active_project_context. [불변식] persist는 server.py 소유 전역
                     PROJECT_CONTEXT_UNRESOLVED를 직접 못 세우므로 bool(unresolved)만 반환 —
                     세팅은 caller(server.py) 책임.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def slugify(root: Path) -> str:
    """경로 → project_id 슬러그 (예: D:/vibe-coding → D--vibe-coding)."""
    return str(root).replace('\\', '/').replace(':', '').replace('/', '--').lstrip('-')


def current_project_root(default_root: Path, config_file: Path) -> Path:
    """현재 활성 프로젝트 루트 반환.

    config.json의 last_path가 유효한 디렉토리면 우선,
    그렇지 않으면 default_root(서버 시작 시 결정된 PROJECT_ROOT) 사용.
    """
    try:
        if config_file.exists():
            cfg = json.loads(config_file.read_text(encoding='utf-8'))
            lp = cfg.get('last_path', '')
            if lp and Path(lp).is_dir():
                return Path(lp)
    except Exception as e:
        print(f"[project_context] config 로드 실패: {e}", file=sys.stderr)
    return default_root


def current_project_id(default_root: Path, config_file: Path) -> str:
    """현재 활성 project_id 슬러그 반환."""
    return slugify(current_project_root(default_root, config_file))


def assert_project_id(project_id: str, op: str = 'write') -> str:
    """쓰기 진입점에서 빈 project_id가 들어오면 dev 모드에서만 경고.

    VIBE_DEV_MODE=1일 때만 stderr에 경고 + 호출 스택을 남긴다.
    프로덕션에선 인자 그대로 반환 (무동작).
    """
    if not project_id and os.environ.get('VIBE_DEV_MODE', '').strip() in ('1', 'true', 'on'):
        print(
            f"[project_context] WARN: empty project_id at {op} — caller stack:",
            file=sys.stderr,
        )
        traceback.print_stack(file=sys.stderr)
    return project_id


def find_project_root_marker(start: Path) -> Path | None:
    """start와 상위 디렉토리에서 .git/CLAUDE.md/GEMINI.md 마커 탐색.
    찾으면 마커가 있는 디렉토리, 없으면 None.
    """
    try:
        cur = start.resolve()
    except Exception:
        return None
    for _ in range(10):
        if any((cur / m).exists() for m in ('.git', 'CLAUDE.md', 'GEMINI.md')):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_frozen_project_root(exe_parent: Path) -> Path:
    """[회귀 수정] 설치 EXE의 PROJECT_ROOT 결정.
    1) cwd 마커 탐색 → 사용자가 프로젝트 폴더에서 실행한 경우
    2) exe_parent 마커 탐색 → 설치 폴더에 마커가 있는 경우(거의 없음)
    3) %APPDATA%\\VibeCoding\\config.json.last_path
    4) %APPDATA%\\VibeCoding\\projects.json[0]
    5) 최종 폴백: exe_parent (잘못된 PROJECT_ID 발생 가능)
    """
    found = find_project_root_marker(Path.cwd())
    if found is not None:
        return found
    found = find_project_root_marker(exe_parent)
    if found is not None:
        return found
    if os.name == 'nt':
        _appdata = Path(os.getenv('APPDATA', '')) / 'VibeCoding'
    else:
        _appdata = Path.home() / '.vibe-coding'
    try:
        cfg_file = _appdata / 'config.json'
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
            lp = cfg.get('last_path', '')
            if lp and Path(lp).is_dir():
                return Path(lp)
    except Exception:
        pass
    try:
        projs_file = _appdata / 'projects.json'
        if projs_file.exists():
            saved = json.loads(projs_file.read_text(encoding='utf-8'))
            if isinstance(saved, list) and saved:
                first = Path(str(saved[0]).replace('/', os.sep))
                if first.is_dir():
                    return first
    except Exception:
        pass
    return exe_parent


def persist_active_project_context(
    project_root: Path, config_file: Path, projects_file: Path
) -> bool:
    """frozen 모드에서 해석된 project_root를 last_path/projects.json에 고정한다.

    [반환] unresolved 플래그(bool). 마커를 못 찾으면 True(=미해석, UI가 프로젝트 선택 유도).
           server.py 소유 전역 PROJECT_CONTEXT_UNRESOLVED를 여기서 직접 못 세우므로
           bool만 돌려주고 세팅은 caller가 한다.
    """
    if find_project_root_marker(project_root) is None:
        print(
            f"[project_context] WARN: 활성 프로젝트 미해석 — PROJECT_ROOT={project_root} (마커 없음). "
            "대시보드에서 프로젝트 폴더를 선택해야 하이브/제텔/태스크가 채워집니다.",
            file=sys.stderr,
        )
        return True
    try:
        cfg = {}
        if config_file.exists():
            cfg = json.loads(config_file.read_text(encoding='utf-8'))
        lp = cfg.get('last_path', '')
        # last_path가 비었거나 더 이상 존재하지 않는 경로면 현재 실제 project_root로 고정
        if not (lp and Path(lp).is_dir()):
            _norm = str(project_root).replace('\\', '/')
            cfg['last_path'] = _norm
            config_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            _projs = []
            try:
                if projects_file.exists():
                    _projs = json.loads(projects_file.read_text(encoding='utf-8'))
            except Exception:
                _projs = []
            if _norm in _projs:
                _projs.remove(_norm)
            _projs.insert(0, _norm)
            projects_file.write_text(json.dumps(_projs[:20], ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"[project_context] 활성 프로젝트 자동 고정: {_norm}", file=sys.stderr)
    except Exception as _e:
        print(f"[project_context] last_path 고정 실패: {_e}", file=sys.stderr)
    return False
