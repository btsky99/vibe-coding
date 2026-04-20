"""
FILE: infra/fs_watcher.py
DESCRIPTION: 파일 시스템 실시간 감시(watchdog) + cli_agent 출력 브로드캐스트 워커.
             FSChangeHandler가 watchdog 이벤트를 받아 SSE 클라이언트(FS_CLIENTS)
             에게 fan-out하고, agent_broadcast_worker가 cli_agent의 출력 큐를
             읽어 자율 에이전트 SSE 클라이언트(AGENT_CLIENTS)에게 분배합니다.

REVISION HISTORY:
- 2026-04-20 Claude: server.py L854~929 분리 (Task 3.1)
                     SSE 글로벌 상태(FS_CLIENTS/AGENT_CLIENTS/_SSE_LOCK)는 인자로 주입
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    Observer = None  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


def agent_broadcast_worker(agent_clients: set, sse_lock: threading.Lock, scripts_dir: str | None = None) -> None:
    """cli_agent._output_queue를 읽어 모든 연결된 SSE 클라이언트에게 팬아웃합니다.

    단일 생산자(cli_agent) → 다중 소비자(SSE 클라이언트) 패턴 구현.
    cli_agent가 Queue에 이벤트를 넣으면 이 워커가 즉시 모든 클라이언트 큐에 복사합니다.
    """
    from queue import Empty as _Empty
    if scripts_dir is None:
        scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import cli_agent as _ca
    except ImportError:
        return  # cli_agent 미설치 시 종료

    while True:
        try:
            msg = _ca._output_queue.get(timeout=1.0)
            # 연결된 모든 클라이언트 큐에 동일 메시지 복사 전송
            with sse_lock:
                cq_snapshot = list(agent_clients)
            for cq in cq_snapshot:
                try:
                    cq.put_nowait(msg)
                except Exception:
                    pass  # 클라이언트 큐 가득 참 등 무시
        except _Empty:
            pass  # 1초 타임아웃 — 정상, 계속 대기
        except Exception:
            pass  # 기타 오류 무시 후 재시도


class FSChangeHandler(FileSystemEventHandler):
    """파일 시스템 변경 이벤트를 감지하여 SSE 클라이언트들에게 알립니다."""

    def __init__(self, fs_clients: set, sse_lock: threading.Lock, data_dir: Path):
        super().__init__()
        self._fs_clients = fs_clients
        self._sse_lock = sse_lock
        self._data_dir_str = str(data_dir).replace('\\', '/') if data_dir else ''

    def on_any_event(self, event):
        if event.is_directory:
            return
        # 노이즈가 심한 파일/폴더는 제외 (시스템 레벨 필터링이 안 될 경우 대비)
        path = event.src_path.replace('\\', '/')
        if any(x in path for x in ['.git', '.ai_monitor/data', '__pycache__', '.ruff_cache',
                                    '.ico', '.png', '.jpg', '.tmp', 'node_modules', 'dist', 'build',
                                    '.db-wal', '.db-shm']):  # SQLite WAL/SHM 파일 제외
            return
        if self._data_dir_str and path.startswith(self._data_dir_str):
            return  # DATA_DIR 하위 파일 전체 제외 (DB, 로그 등 런타임 데이터)

        # 브로드캐스트 메시지 생성
        msg_obj = {'type': 'fs_change', 'path': path, 'event': event.event_type}
        msg = f"data: {json.dumps(msg_obj, ensure_ascii=False)}\n\n"

        # 연결된 모든 클라이언트에게 전송 (비정상 연결 조기 제거)
        disconnected = []
        with self._sse_lock:
            clients_snapshot = list(self._fs_clients)
        for client in clients_snapshot:
            try:
                client.connection.settimeout(1.0)
                client.wfile.write(msg.encode('utf-8'))
                client.wfile.flush()
            except Exception:
                disconnected.append(client)  # SSE FS 클라이언트 연결 끊김
        if disconnected:
            with self._sse_lock:
                for d in disconnected:
                    self._fs_clients.discard(d)


def start_fs_watcher(root_path, fs_clients: set, sse_lock: threading.Lock, data_dir: Path):
    if Observer is None:
        print("[!] watchdog 라이브러리가 없어 실시간 파일 감시를 시작할 수 없습니다.")
        return None
    handler = FSChangeHandler(fs_clients, sse_lock, data_dir)
    observer = Observer()
    observer.schedule(handler, str(root_path), recursive=True)
    observer.start()
    print(f"[*] File System Watcher started on {root_path}")
    return observer
