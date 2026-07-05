"""
FILE: api/static_api.py
DESCRIPTION: 정적 파일 서빙 + 도움말/이미지 라우트 3종 — GET /api/help, GET /api/image-file,
             그리고 do_GET 최후미 else 폴백(Vite dist SPA 서빙). server.py 인라인 블록을
             verbatim 이전(Phase 2 R4). 동작 완전 불변.

  [불변식/핵심] serve()는 do_GET의 "최후미 폴백"이다 — exact/prefix/legacy 어디에도 안 걸린
    모든 GET 요청이 여기로 온다. 절대 라우트 테이블(exact)에 등록하면 안 됨 — 등록하면 미매칭
    GET이 404가 되어 SPA 라우팅이 깨진다. server.py do_GET 맨 끝 else 자리에서만 호출한다.
  [경로 주입] static_dir(STATIC_DIR)·docs_dir·validate_file_path는 server.py 전역/함수라
    인자로 주입받는다. 특히 STATIC_DIR은 server.py에서 동적 폴백(alt_dist)으로 갱신될 수
    있으므로 wrapper가 호출 시점 최신값을 넘겨야 한다(late-binding).
  [help_doc docs 경로] 원본은 server.py의 Path(__file__).parent/'docs' = .ai_monitor/docs 를
    참조했다. 이 모듈의 __file__은 api/ 하위라 경로가 달라지므로 docs_dir를 반드시 주입받는다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py do_GET 정적서빙 else + /api/help + /api/image-file 3블록 분리(Phase 2 R4).
  전역(STATIC_DIR/docs_dir/_validate_file_path)은 참조 주입. serve는 do_GET 최후미 폴백 유지.
"""
from __future__ import annotations

import json
import mimetypes
from urllib.parse import parse_qs


def help_doc(h, pp, docs_dir) -> None:
    """GET /api/help — docs/help-{topic}.md 내용 반환(없으면 error JSON)."""
    h.send_response(200)
    h.send_header('Content-Type', 'application/json;charset=utf-8')
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    query = parse_qs(pp.query)
    topic = query.get('topic', [''])[0]
    help_file = docs_dir / f'help-{topic}.md'
    if help_file.exists():
        content = help_file.read_text(encoding='utf-8')
        h.wfile.write(json.dumps({"content": content}).encode('utf-8'))
    else:
        h.wfile.write(json.dumps({"error": "Help topic not found"}).encode('utf-8'))


def image_file(h, pp, validate_file_path) -> None:
    """GET /api/image-file — 검증된 경로의 이미지 바이너리 서빙(MIME 판별)."""
    query = parse_qs(pp.query)
    raw_path = query.get('path', [''])[0]
    try:
        target_path = validate_file_path(raw_path)
    except ValueError:
        h.send_response(403)
        h.send_header('Access-Control-Allow-Origin', h._cors_origin())
        h.end_headers()
        return
    IMAGE_MIME = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'bmp': 'image/bmp', 'ico': 'image/x-icon',
    }
    ext = str(target_path).rsplit('.', 1)[-1].lower() if '.' in str(target_path) else ''
    mime = IMAGE_MIME.get(ext, 'application/octet-stream')
    if not target_path.exists() or not target_path.is_file():
        h.send_response(404)
        h.end_headers()
        return
    h.send_response(200)
    h.send_header('Content-Type', mime)
    h.send_header('Access-Control-Allow-Origin', h._cors_origin())
    h.end_headers()
    with open(target_path, 'rb') as f:
        h.wfile.write(f.read())


def serve(h, path, static_dir) -> None:
    """do_GET 최후미 폴백 — Vite 빌드 결과물(SPA) 정적 서빙.

    [불변식] 테이블 등록 금지. 미매칭 GET 전부 여기로 폴백 → 없으면 index.html SPA fallback.
    [경로] path는 parsed_path.path(쿼리 제거 완료)를 받는다. 원본은 self.path(쿼리 포함)를
      받아 split('?')로 잘랐으나, parsed_path.path는 이미 쿼리가 없어 split이 무해(동작 동일).
    """
    # 정적 파일 서비스 로직 (Vite 빌드 결과물)
    # 요청 경로를 정리
    if path == '/':
        path = '/index.html'

    # /monitor → 에이전트 상황판 독립 페이지
    if path.rstrip('/') == '/monitor':
        path = '/monitor.html'

    # 쿼리스트링 제거
    path = path.split('?')[0]

    filepath = static_dir / path.lstrip('/')

    # 파일이 없으면 index.html로 Fallback (SPA 특성)
    if not filepath.exists() or not filepath.is_file():
        filepath = static_dir / 'index.html'

    if filepath.exists() and filepath.is_file():
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            h.send_response(200)
            mimetype, _ = mimetypes.guess_type(str(filepath))
            if filepath.suffix == '.js':
                mimetype = 'application/javascript'
            elif filepath.suffix == '.css':
                mimetype = 'text/css'
            elif filepath.suffix == '.svg':
                mimetype = 'image/svg+xml'
            h.send_header('Content-Type', mimetype or 'application/octet-stream')
            h.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            h.send_header('Pragma', 'no-cache')
            h.send_header('Expires', '0')
            h.end_headers()
            h.wfile.write(content)
        except Exception as e:
            h.send_response(500)
            h.end_headers()
            h.wfile.write(str(e).encode('utf-8'))
    else:
        h.send_response(404)
        h.end_headers()
        h.wfile.write(b"Not Found")
