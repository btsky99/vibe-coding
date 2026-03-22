"""
FILE: api/files_api.py
DESCRIPTION: /api/files, /api/read-file, /api/save-file, /api/file-rename,
             /api/files/create, /api/files/delete 엔드포인트 핸들러 모듈.
             파일 시스템 탐색, 파일 읽기/쓰기/이름변경/생성/삭제 기능을 제공합니다.
             server.py에서 분리하여 파일 관련 로직을 단일 파일로 관리합니다.

REVISION HISTORY:
- 2026-03-22 Claude: server.py에서 분리 — files API 핸들러 담당
"""

import json
import os
import shutil
from pathlib import Path
from urllib.parse import parse_qs


def handle_get(handler, path: str, params: dict, *,
               PROJECT_ROOT: Path, validate_file_path) -> bool:
    """GET 요청 처리 — /api/files, /api/read-file 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/files ─────────────────────────────────────────────────────
    # [수정] Windows 경로(드라이브 루트 등) 처리 및 응답 안정성 강화.
    # 1. 경로 구분자 표준화 및 드라이브 루트(/) 유효성 보정.
    # 2. 예외 발생 시 빈 배열([])을 안전하게 반환하여 연결 끊김 방지.
    if path == '/api/files':
        query = params
        target_path = query.get('path', [''])[0].replace('\\', '/')

        # [핵심] 경로가 비어있을 경우 기본값으로 PROJECT_ROOT(문자열) 사용
        if not target_path:
            target_path = str(PROJECT_ROOT).replace('\\', '/')

        # 드라이브 루트(예: D:) 처리 보정
        if target_path and len(target_path) == 2 and target_path[1] == ':':
            target_path += '/'

        items = []
        try:
            # 실제 경로 존재 여부 및 디렉터리 여부 재검증
            p = Path(target_path)
            if p.exists() and p.is_dir():
                for entry in os.scandir(target_path):
                    # 숨김 항목 필터링 (주요 설정 파일 제외)
                    if not entry.name.startswith('.') or entry.name in ('.claude', '.ai_monitor', '.gemini', '.github', '.gitignore', '.env'):
                        items.append({
                            "name": entry.name,
                            "path": entry.path.replace('\\', '/'),
                            "isDir": entry.is_dir()
                        })
        except Exception as e:
            # 권한 문제 등으로 인한 실패 시 로그 기록 후 빈 목록 반환 (서버 중단 방지)
            print(f"[ERROR] /api/files failed for {target_path}: {e}")

        # 폴더 우선 정렬
        try:
            items.sort(key=lambda x: (not x['isDir'], x['name'].lower()))
        except Exception as e:
            print(f"[ERROR] /api/files 정렬 실패: {e}")

        body = json.dumps(items).encode('utf-8')
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True

    # ── /api/read-file ─────────────────────────────────────────────────
    elif path == '/api/read-file':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        query = params
        raw_path = query.get('path', [''])[0]

        # 경로 순회 방지 — resolve() 후 프로젝트 루트 하위인지 검증
        try:
            target_path = validate_file_path(raw_path)
        except ValueError as e:
            handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return True

        if not target_path.exists() or not target_path.is_file():
            handler.wfile.write(json.dumps({"error": "File not found or invalid path"}).encode('utf-8'))
            return True

        try:
            # Try reading as UTF-8
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()
            handler.wfile.write(json.dumps({"content": content}).encode('utf-8'))
        except UnicodeDecodeError:
            handler.wfile.write(json.dumps({"error": "Binary file cannot be displayed."}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict, *,
                validate_file_path) -> bool:
    """POST 요청 처리 — /api/save-file, /api/file-rename, /api/files/create, /api/files/delete 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/save-file ─────────────────────────────────────────────────
    # [파일 저장] 프론트엔드 VibeEditor/App.tsx 에서 POST로 호출
    if path == '/api/save-file':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            raw_path = data.get('path')
            content = data.get('content', '')

            # 경로 순회 방지 — resolve() 후 허용된 디렉터리 하위인지 검증
            target_path = validate_file_path(raw_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"💾 [File Saved] {target_path}")
            handler.wfile.write(json.dumps({"status": "success", "path": str(target_path)}).encode('utf-8'))
        except ValueError as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except Exception as e:
            print(f"❌ [Save Error] {e}")
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    # ── /api/file-rename ───────────────────────────────────────────────
    # [이름 변경] src -> dest — 경로 순회 방지 적용
    elif path == '/api/file-rename':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            src = validate_file_path(data.get('src', ''))
            dest = validate_file_path(data.get('dest', ''))
            os.rename(src, dest)
            handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
        except ValueError as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    # ── /api/files/create ──────────────────────────────────────────────
    # [생성] path, is_dir — 경로 순회 방지 적용
    elif path == '/api/files/create':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            p = validate_file_path(data.get('path', ''))
            is_dir = data.get('is_dir', False)

            if is_dir:
                p.mkdir(parents=True, exist_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")

            handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
        except ValueError as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    # ── /api/files/delete ──────────────────────────────────────────────
    # [삭제] path — 경로 순회 방지 적용
    elif path == '/api/files/delete':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            target_path = validate_file_path(data.get('path', ''))

            if not target_path.exists():
                handler.wfile.write(json.dumps({"status": "error", "message": "Path not found"}).encode('utf-8'))
                return True

            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                os.remove(target_path)

            handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
        except ValueError as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    return False
