"""
FILE: api/events_api.py
DESCRIPTION: SSE(text/event-stream) 실시간 스트리밍 핸들러 3종 — 사고과정/자율에이전트출력/FS변경.
             각 핸들러는 handler(SSEHandler)를 공유 클라이언트 집합에 등록하고 하트비트 루프를 돈다.
             브로드캐스트 워커(server.py의 _agent_broadcast_worker / FS·thought 브로드캐스트)가
             동일한 집합 객체로 팬아웃하므로, 집합/락은 server.py 전역을 참조로 주입받는다.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_GET 최상단 SSE 3블록 분리(라운드3). 공유 전역(집합/락/THOUGHT_LOGS)은
  참조 주입 — 브로드캐스트 측과 동일 객체 유지가 불변식(별도 사본이면 팬아웃이 끊김). 로직 원본 동일.
"""
from __future__ import annotations

import json
import time


def _sse_headers(handler) -> None:
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'keep-alive')
    handler.end_headers()


def stream_thoughts(handler, thought_logs, thought_clients, sse_lock) -> None:
    """GET /api/events/thoughts — 사고 과정 실시간 스트리밍.
    [불변식] thought_clients는 server.py 전역과 동일 객체여야 브로드캐스트가 이 연결에 닿음.
    """
    _sse_headers(handler)
    # 초기 데이터 전송 (메모리에 쌓인 로그)
    for log in thought_logs:
        handler.wfile.write(f"data: {json.dumps(log, ensure_ascii=False)}\n\n".encode('utf-8'))
        handler.wfile.flush()
    with sse_lock:
        thought_clients.add(handler)
    try:
        handler.connection.settimeout(None)  # 타임아웃 제거 — 하트비트로 연결 관리
        while True:
            time.sleep(30)
            handler.wfile.write(b": heartbeat\n\n")
            handler.wfile.flush()
    except Exception:
        pass  # 연결 끊김 — finally에서 정리
    finally:
        with sse_lock:
            thought_clients.discard(handler)


def stream_agent(handler, agent_clients, sse_lock) -> None:
    """GET /api/events/agent — 자율 에이전트 출력 실시간 스트리밍.
    [설계] 클라이언트별 전용 큐를 agent_clients(set)에 등록 → _agent_broadcast_worker가
      cli_agent 큐를 읽어 각 전용 큐로 팬아웃(다중 연결/재연결 시 이벤트 손실 없음).
      무제한 큐 — done 이벤트 드롭 방지.
    """
    _sse_headers(handler)
    from queue import Queue as _ClientQueue, Empty as _QEmpty
    client_q = _ClientQueue(maxsize=0)
    with sse_lock:
        agent_clients.add(client_q)
    try:
        handler.connection.settimeout(None)
        while True:
            try:
                msg = client_q.get(timeout=1.0)
                try:
                    handler.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
                    handler.wfile.flush()
                except Exception:
                    break  # 클라이언트 연결 끊김
            except _QEmpty:
                # 큐 비어있으면 하트비트 전송 (연결 유지)
                try:
                    handler.wfile.write(b": heartbeat\n\n")
                    handler.wfile.flush()
                except Exception:
                    break  # 클라이언트 연결 끊김
    except Exception:
        pass  # 연결 끊김
    finally:
        with sse_lock:
            agent_clients.discard(client_q)


def stream_fs(handler, fs_clients, sse_lock) -> None:
    """GET /api/events/fs — 파일 시스템 변경 이벤트 스트리밍.
    [불변식] fs_clients는 server.py 전역과 동일 객체 — FS 워치독이 이 집합으로 브로드캐스트.
    """
    _sse_headers(handler)
    with sse_lock:
        fs_clients.add(handler)
    try:
        handler.connection.settimeout(60.0)  # SSE 연결 타임아웃 완화(60초)
        while True:
            time.sleep(30)  # 하트비트 주기 30초
            handler.wfile.write(b": heartbeat\n\n")
            handler.wfile.flush()
    except Exception:
        pass  # 연결 끊김
    finally:
        with sse_lock:
            fs_clients.discard(handler)
