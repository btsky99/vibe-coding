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
