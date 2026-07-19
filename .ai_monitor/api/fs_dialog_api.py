"""
FILE: api/fs_dialog_api.py
DESCRIPTION: 파일시스템 다이얼로그 / 탐색 라우트 모음 — server.py do_GET/do_POST에서 추출(Phase 2 R1).
             폴더 선택 다이얼로그(tkinter 서브프로세스), 드라이브 스캔, 디렉터리 목록,
             외부 앱(브라우저) 열기. 모두 OS 레벨 부수효과가 있어 한 도메인으로 묶음.

  [WHY] server.py 1500줄 감축을 위한 도메인 단위 분리. 동작 완전 불변(verbatim 이전).
  [제약] 서버 전역 헬퍼(_open_folder_dialog_subprocess)와 CONFIG_FILE 경로는 server.py 소유라
    호출 인자로 주입받는다(late-binding). 모듈이 server 전역을 직접 import하면 순환 의존 위험.
  [불변식] h(SSEHandler)의 _cors_origin()/send_response()/wfile은 핸들러 메서드로 그대로 사용.

REVISION HISTORY:
- 2026-07-05 Claude: 신규 — server.py에서 browse-folder/drives/dirs/select-folder/open-external 5종 추출.
"""
import os
import json
import string
import webbrowser
from urllib.parse import urlparse


def handle_get(h, path, query, *, open_folder_dialog, open_file_dialog=None):
    """GET 파일시스템 라우트 4종 디스패치.

    - open_folder_dialog: server._open_folder_dialog_subprocess (호출 시점 주입)
    - open_file_dialog: server._open_file_dialog_subprocess (LAN 파일전송 '찾아보기')
    - query: parse_qs 결과 dict (dirs에서만 사용)
    """
    if path == '/api/browse-folder':
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        try:
            selected_path = open_folder_dialog()
            h.wfile.write(json.dumps({"path": selected_path}).encode('utf-8'))
        except Exception as e:
            h.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    elif path == '/api/browse-file':
        # [WHY] LAN 파일전송은 파일 1개 경로가 필요 — 폴더 다이얼로그와 별도.
        #   open_file_dialog 미주입(구버전 호출) 시 500 대신 빈 경로로 안전 폴백.
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        try:
            selected_path = open_file_dialog() if open_file_dialog else ''
            h.wfile.write(json.dumps({"path": selected_path}).encode('utf-8'))
        except Exception as e:
            h.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    elif path == '/api/drives':
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        drives = []
        if os.name == 'nt':
            for letter in string.ascii_uppercase:
                drive = f"{letter}:/"  # 경로 일관성: 항상 포워드 슬래시 사용 (2026-02-27)
                if os.path.exists(drive):
                    drives.append(drive)
        else:
            drives = ['/']
        h.wfile.write(json.dumps(drives).encode('utf-8'))
    elif path == '/api/dirs':
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        target_path = query.get('path', [''])[0]
        dirs = []
        if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
            try:
                for entry in os.scandir(target_path):
                    # .으로 시작하는 숨김 폴더 중 주요 설정 폴더는 허용
                    if entry.is_dir() and (not entry.name.startswith('.') or entry.name in ('.claude', '.ai_monitor', '.gemini', '.github')):
                        dirs.append({"name": entry.name, "path": entry.path.replace('\\', '/')})
            except Exception as e:
                print(f"[FILE ERROR] /api/dirs scandir: {e}")
        dirs.sort(key=lambda x: x['name'].lower())
        try:
            h.wfile.write(json.dumps(dirs).encode('utf-8'))
            h.wfile.flush()
        except Exception as _e:
            print(f'[/api/dirs write ERROR] {_e}', flush=True)


def handle_post(h, path, *, open_folder_dialog, config_file):
    """POST 파일시스템 라우트 2종 디스패치.

    - open_folder_dialog: server._open_folder_dialog_subprocess (호출 시점 주입)
    - config_file: server.CONFIG_FILE (Path) — select-folder가 last_path 저장에 사용
    """
    if path == '/api/open-external':
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        try:
            content_length = int(h.headers.get('Content-Length', 0))
            payload = {}
            if content_length > 0:
                body = h.rfile.read(content_length).decode('utf-8')
                payload = json.loads(body or '{}')

            url = str(payload.get('url', '')).strip()
            parsed_url = urlparse(url)
            if not url or parsed_url.scheme not in ('http', 'https'):
                raise ValueError('Only http/https URLs can be opened externally')

            opened = webbrowser.open(url)
            h.wfile.write(json.dumps({
                "status": "ok",
                "opened": bool(opened),
                "url": url,
            }).encode('utf-8'))
        except Exception as e:
            h.wfile.write(json.dumps({
                "status": "error",
                "message": str(e),
            }).encode('utf-8'))
    elif path == '/api/select-folder':
        # 폴더 선택 다이얼로그 — tkinter 별도 프로세스 방식
        # pywebview의 create_file_dialog()는 GUI 스레드 제한으로 HTTP 핸들러에서 호출 불가
        # 독립 Python 프로세스로 tkinter를 실행하여 안정적으로 동작
        h.send_response(200)
        h.send_header('Content-Type', 'application/json;charset=utf-8')
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        try:
            selected = open_folder_dialog()
            if selected:
                # 선택된 경로를 설정에도 즉시 저장
                config = {}
                if config_file.exists():
                    try:
                        with open(config_file, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                    except: pass
                config['last_path'] = selected
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                h.wfile.write(json.dumps({"status": "success", "path": selected}).encode('utf-8'))
            else:
                h.wfile.write(json.dumps({"status": "cancelled"}).encode('utf-8'))
        except Exception as e:
            h.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
