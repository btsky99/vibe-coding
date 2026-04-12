"""
FILE: .ai_monitor/office_server.py
DESCRIPTION: 오피스 전용 HTTP 서버 — 별도 프로세스로 실행되어 클래식(server.py)과 격리된다.
             /api/office/* 는 직접 처리, 그 외 API는 클래식 서버로 투명 프록시한다.

REVISION HISTORY:
- 2026-04-12 Claude: 신규 생성 — 오피스/클래식 서버 프로세스 분리
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── 경로 설정 ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from api import office_api
from src.server_utils import find_free_port, cors_origin, send_json, handle_cors_preflight
from src.pg_store import ensure_schema

# ── 전역 설정 ─────────────────────────────────────────────────────────────
OFFICE_PORT = 0       # 실제 바인딩 포트 (시작 시 결정)
CLASSIC_PORT = 0      # 클래식 서버 포트 (--classic-port 인자)
DATA_DIR = BASE_DIR / 'data'

# 정적 파일 디렉터리
DIST_DIR = BASE_DIR / 'vibe-view' / 'dist'

# MIME 타입
_MIME = {
    '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript',
    '.css': 'text/css', '.json': 'application/json', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
    '.map': 'application/json', '.webp': 'image/webp',
}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ── 클래식 서버 프록시 ────────────────────────────────────────────────────

def _proxy_to_classic(handler: BaseHTTPRequestHandler, method: str = 'GET', body: bytes | None = None):
    """클래식 서버(server.py)로 요청을 투명 프록시한다."""
    target_url = f'http://127.0.0.1:{CLASSIC_PORT}{handler.path}'
    headers_dict = {}
    for key in ('Content-Type', 'Accept', 'Authorization'):
        val = handler.headers.get(key)
        if val:
            headers_dict[key] = val

    try:
        req = Request(target_url, data=body, headers=headers_dict, method=method)
        with urlopen(req, timeout=30) as resp:
            status = resp.status
            content_type = resp.headers.get('Content-Type', 'application/octet-stream')
            data = resp.read()

            handler.send_response(status)
            handler.send_header('Content-Type', content_type)
            handler.send_header('Access-Control-Allow-Origin',
                                cors_origin(handler.headers, OFFICE_PORT))
            handler.end_headers()
            handler.wfile.write(data)
    except URLError as e:
        handler.send_response(502)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.end_headers()
        handler.wfile.write(json.dumps({
            'error': f'클래식 서버 프록시 실패: {e}',
            'classic_port': CLASSIC_PORT,
        }, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.send_response(500)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.end_headers()
        handler.wfile.write(json.dumps({'error': str(e)}, ensure_ascii=False).encode('utf-8'))


def _proxy_sse_to_classic(handler: BaseHTTPRequestHandler):
    """클래식 서버의 SSE 스트림을 투명 프록시한다."""
    target_url = f'http://127.0.0.1:{CLASSIC_PORT}{handler.path}'
    try:
        req = Request(target_url, method='GET')
        resp = urlopen(req, timeout=300)

        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Connection', 'keep-alive')
        handler.send_header('Access-Control-Allow-Origin',
                            cors_origin(handler.headers, OFFICE_PORT))
        handler.end_headers()

        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            handler.wfile.write(chunk)
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    except Exception as e:
        print(f'[office_server] SSE 프록시 종료: {e}')


# ── 요청 핸들러 ───────────────────────────────────────────────────────────

class OfficeHandler(BaseHTTPRequestHandler):
    """오피스 전용 HTTP 핸들러.

    /api/office/* → office_api 직접 처리
    /api/* (그 외) → 클래식 서버 프록시
    / (정적 파일) → vibe-view/dist/ 서빙
    """

    def log_message(self, format, *args):
        """기본 로그 억제 — 필요 시 활성화."""
        pass

    def _cors_origin(self) -> str:
        return cors_origin(self.headers, OFFICE_PORT)

    def do_OPTIONS(self):
        handle_cors_preflight(self, OFFICE_PORT)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── 오피스 전용 API (직접 처리) ──
        if path.startswith('/api/office/'):
            if not office_api.handle_get(self, path, params, DATA_DIR=DATA_DIR):
                send_json(self, {'error': 'not found'}, status=404, port=OFFICE_PORT)
            return

        # ── SSE 스트림 → 클래식 프록시 ──
        if path == '/stream' or path.startswith('/api/events/'):
            _proxy_sse_to_classic(self)
            return

        # ── 기타 API → 클래식 서버 프록시 ──
        if path.startswith('/api/'):
            _proxy_to_classic(self, method='GET')
            return

        # ── 정적 파일 서빙 ──
        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 바디 읽기
        length = int(self.headers.get('Content-Length', '0') or 0)
        body = self.rfile.read(length) if length > 0 else None

        # ── 오피스 전용 API ──
        if path.startswith('/api/office/'):
            # body를 다시 읽을 수 있도록 rfile을 교체
            if body:
                self.rfile = io.BytesIO(body)
                self.headers['Content-Length'] = str(len(body))
            if not office_api.handle_post(self, path, DATA_DIR=DATA_DIR):
                send_json(self, {'error': 'not found'}, status=404, port=OFFICE_PORT)
            return

        # ── 기타 API → 클래식 프록시 ──
        _proxy_to_classic(self, method='POST', body=body)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get('Content-Length', '0') or 0)
        body = self.rfile.read(length) if length > 0 else None

        if path.startswith('/api/office/'):
            if body:
                self.rfile = io.BytesIO(body)
                self.headers['Content-Length'] = str(len(body))
            if not office_api.handle_put(self, path, DATA_DIR=DATA_DIR):
                send_json(self, {'error': 'not found'}, status=404, port=OFFICE_PORT)
            return

        _proxy_to_classic(self, method='PUT', body=body)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/office/'):
            if not office_api.handle_delete(self, path, DATA_DIR=DATA_DIR):
                send_json(self, {'error': 'not found'}, status=404, port=OFFICE_PORT)
            return

        length = int(self.headers.get('Content-Length', '0') or 0)
        body = self.rfile.read(length) if length > 0 else None
        _proxy_to_classic(self, method='DELETE', body=body)

    def _serve_static(self, path: str):
        """vibe-view/dist/ 정적 파일 서빙. SPA 폴백 포함."""
        if path == '/' or path == '':
            path = '/index.html'

        file_path = DIST_DIR / path.lstrip('/')
        # 보안: dist 밖으로 탈출 방지
        try:
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(DIST_DIR.resolve())):
                self.send_error(403)
                return
        except Exception:
            self.send_error(400)
            return

        if file_path.is_file():
            ext = file_path.suffix.lower()
            mime = _MIME.get(ext, 'application/octet-stream')
            try:
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                if ext in ('.js', '.css', '.woff2', '.ttf'):
                    self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
        else:
            # SPA 폴백 — index.html
            index = DIST_DIR / 'index.html'
            if index.is_file():
                data = index.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    global OFFICE_PORT, CLASSIC_PORT

    # CLI 인자 파싱
    import argparse
    parser = argparse.ArgumentParser(description='오피스 전용 HTTP 서버')
    parser.add_argument('--classic-port', type=int, required=True,
                        help='클래식 서버 포트 (프록시 대상)')
    parser.add_argument('--port-start', type=int, default=9010,
                        help='오피스 서버 포트 탐색 시작점 (기본 9010)')
    args = parser.parse_args()

    CLASSIC_PORT = args.classic_port

    # 포트 자동 탐색
    OFFICE_PORT = find_free_port(args.port_start, max_tries=20)

    # 오피스 API 초기화 (스키마 보장 + 기본 프로필)
    try:
        office_api.init_office(DATA_DIR)
    except Exception as e:
        print(f'[office_server] 오피스 초기화 실패 (서버는 시작): {e}')

    # 서버 시작
    server = ThreadedHTTPServer(('127.0.0.1', OFFICE_PORT), OfficeHandler)

    # ★ 포트 알림 — 부모 프로세스(server.py)가 이 줄을 읽어 포트를 확인한다
    print(f'PORT:{OFFICE_PORT}', flush=True)
    print(f'[office_server] 오피스 서버 시작: http://localhost:{OFFICE_PORT} (클래식 프록시 → :{CLASSIC_PORT})')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('[office_server] 종료 요청')
    finally:
        server.server_close()
        print('[office_server] 서버 종료 완료')


if __name__ == '__main__':
    main()
