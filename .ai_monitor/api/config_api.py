"""
FILE: api/config_api.py
DESCRIPTION: 앱 설정 갱신 API — config.json에 부분 업데이트(merge)하고, last_path 변경 시
             projects.json MRU에도 동기화한다(재시작 후 PROJECT_ROOT 정확 설정). server.py 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_POST '/api/config/update' 39줄 분리(long-tail 라운드).
  CONFIG_FILE/PROJECTS_FILE(Path 전역)는 파라미터 주입. 로직 원본 동일.
- 2026-07-06 Claude: GET '/api/config' 인라인 분리(Phase 2 R8). vault_dir/project_unresolved/
  active_project_id는 호출 시점 전역값을 wrapper가 late-binding으로 주입(런타임 mutation 반영).
"""
from __future__ import annotations

import json
from pathlib import Path


def handle_get(handler, config_file: Path, global_vault_dir,
               project_unresolved: bool, active_project_id: str) -> None:
    """GET /api/config — config.json 로드 + 활성 프로젝트 컨텍스트 주입.
    [과거사고 방지] project_unresolved=True면 UI가 '프로젝트 폴더 선택'을 유도(설치본 빈 패널 사고).
      이 두 값은 런타임에 갱신되는 전역이라 wrapper가 호출 시점 값을 주입해야 한다(디폴트 바인딩 금지).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    config = {}
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            pass
    config.setdefault('vault_dir', str(global_vault_dir))
    config['project_unresolved'] = project_unresolved
    config['active_project_id'] = active_project_id
    handler.wfile.write(json.dumps(config).encode('utf-8'))


def handle_update(handler, config_file: Path, projects_file: Path) -> None:
    """POST /api/config/update — {키:값} 부분 병합 저장.
    [과거사고 방지] last_path 변경 시 projects.json MRU도 동기화 — 배포 버전에서 프로젝트
      전환 후 재시작해도 올바른 PROJECT_ROOT 사용(설치본 빈 패널 사고 계열).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))
        config = {}
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception:
                pass
        config.update(data)
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # last_path 변경 시 projects.json MRU 동기화 (다음 서버 시작 PROJECT_ROOT 정확화)
        if 'last_path' in data and data['last_path']:
            try:
                _lp = str(data['last_path']).replace('\\', '/')
                _projs = []
                if projects_file.exists():
                    _projs = json.loads(projects_file.read_text(encoding='utf-8'))
                if _lp in _projs:
                    _projs.remove(_lp)
                _projs.insert(0, _lp)  # 가장 최근 경로를 0번으로
                projects_file.write_text(
                    json.dumps(_projs[:20], ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass

        handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
