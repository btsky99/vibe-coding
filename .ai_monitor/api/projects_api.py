"""
FILE: api/projects_api.py
DESCRIPTION: 최근 프로젝트 목록 API — projects.json에 최근 연 프로젝트 경로를 MRU(최대 20개)로
             관리한다. GET=목록 반환, POST=경로 추가(최상단). server.py do_GET/do_POST에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py '/api/projects' GET/POST 블록 분리(long-tail 라운드). 로직 원본 동일.
- 2026-07-22 Claude: 맥 포팅 — GET에서 타 OS 절대경로(맥의 'D:/..' 상대해석) 항목을 최근
  목록에서 필터. Windows 세션 커밋 projects.json의 죽은 경로가 드롭다운에 뜨던 문제.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load(projects_file: Path) -> list:
    if projects_file.exists():
        try:
            with open(projects_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def handle_get(handler, projects_file: Path) -> None:
    """GET /api/projects — 최근 프로젝트 경로 목록 반환.

    [맥포팅 2026-07-22] 타 OS 절대경로(맥에서의 'D:/..')는 POSIX에서 상대경로로 풀려
      존재하지 않는 폴더를 가리키므로 최근 목록에서 제외한다 — 파일탐색기 드롭다운에 죽은
      Windows 경로가 뜨는 것 방지. is_absolute()가 이 머신 기준 유효성의 최소 필터.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    projects = [p for p in _load(projects_file)
                if isinstance(p, str) and Path(p).is_absolute()]
    handler.wfile.write(json.dumps(projects).encode('utf-8'))


def handle_post(handler, projects_file: Path) -> None:
    """POST /api/projects — {path} 를 MRU 최상단에 추가(중복 제거, 최대 20개)."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        data = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])).decode('utf-8'))
        new_path = data.get('path', '').strip().replace('\\', '/')
        if not new_path:
            handler.wfile.write(json.dumps({"error": "Invalid path"}).encode('utf-8'))
            return

        # [맥포팅 2026-07-22] 저장 시 타 OS 절대경로(맥의 'D:/..')를 영구 제거 — 이걸 안 걸면
        #   POST 응답이 stale Windows 경로를 되돌려줘 프론트 드롭다운에 다시 뜬다(GET 필터만으론 부족).
        projects = [p for p in _load(projects_file)
                    if isinstance(p, str) and Path(p).is_absolute()]
        if new_path in projects:
            projects.remove(new_path)
        projects.insert(0, new_path)   # 최신 프로젝트를 위로
        projects = projects[:20]       # 최대 20개
        with open(projects_file, 'w', encoding='utf-8') as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)

        handler.wfile.write(json.dumps({"status": "success", "projects": projects}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
