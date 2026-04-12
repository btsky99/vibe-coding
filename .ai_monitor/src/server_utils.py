"""
FILE: .ai_monitor/src/server_utils.py
DESCRIPTION: 서버 공통 유틸리티 — 포트 탐색, CORS, JSON 응답 헬퍼.
             server.py(클래식)와 office_server.py(오피스) 양쪽에서 재사용한다.

REVISION HISTORY:
- 2026-04-12 Claude: server.py에서 공통 로직 추출하여 신규 생성
"""

from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler


def find_free_port(start: int, max_tries: int = 20) -> int:
    """start부터 순차 스캔하여 바인딩 가능한 첫 번째 포트를 반환한다.

    실패 시 start를 그대로 반환 (서버 시작 시 OSError로 처리).
    """
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start


def cors_origin(headers, default_port: int) -> str:
    """CORS Origin — localhost/127.0.0.1만 허용. 그 외는 default_port 기반 Origin 반환."""
    origin = headers.get('Origin', '')
    if origin and any(origin.startswith(p) for p in (
        'http://localhost', 'http://127.0.0.1',
        'https://localhost', 'https://127.0.0.1',
    )):
        return origin
    return f'http://localhost:{default_port}'


def send_json(handler: BaseHTTPRequestHandler, data, status: int = 200, port: int = 0):
    """JSON 응답 + CORS 헤더를 한번에 전송한다."""
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', cors_origin(handler.headers, port))
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def handle_cors_preflight(handler: BaseHTTPRequestHandler, port: int = 0):
    """OPTIONS 프리플라이트 요청 처리."""
    handler.send_response(204)
    handler.send_header('Access-Control-Allow-Origin', cors_origin(handler.headers, port))
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    handler.send_header('Access-Control-Max-Age', '86400')
    handler.end_headers()
