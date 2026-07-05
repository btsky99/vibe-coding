"""
FILE: api/locks_api.py
DESCRIPTION: 파일 락 API — 에이전트 간 동시 편집 충돌 방지. locks.json에 {파일: 소유에이전트}를
             기록하고 lock/unlock 시 하이브 로그에 남긴다. server.py do_POST에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_POST '/api/locks' 블록 분리(long-tail 라운드). 로직 원본 동일.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def handle_lock(handler, locks_file: Path) -> None:
    """POST /api/locks — {file, agent, action='lock'|'unlock'}. lock 충돌 시 conflict 반환.
    [불변식] 다른 에이전트가 소유한 파일 lock 요청은 conflict(덮어쓰기 금지).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))

        file_path = data.get('file')
        agent = data.get('agent', 'Unknown')
        action = data.get('action', 'lock')  # 'lock' or 'unlock'

        with open(locks_file, 'r', encoding='utf-8') as f:
            locks = json.load(f)

        log_msg = None
        if action == 'lock':
            if file_path in locks and locks[file_path] != agent:
                handler.wfile.write(json.dumps(
                    {"status": "conflict", "owner": locks[file_path]}).encode('utf-8'))
                return
            locks[file_path] = agent
            log_msg = f"Locked file: {file_path}"
        elif action == 'unlock':
            if file_path in locks:
                del locks[file_path]
                log_msg = f"Unlocked file: {file_path}"

        with open(locks_file, 'w', encoding='utf-8') as f:
            json.dump(locks, f, ensure_ascii=False, indent=2)

        # 하이브 로그에 기록 (민감정보 마스킹)
        if log_msg:
            try:
                from src.secure import mask_sensitive_data
                from src.db_helper import insert_log
                insert_log(
                    session_id=f"lock_{int(time.time())}_{agent}",
                    terminal_id="LOCK_API", agent=agent,
                    trigger_msg=mask_sensitive_data(log_msg),
                    project_id="hive", status="success",
                )
            except Exception as e:
                print(f"Error logging lock to session_logs: {e}")

        handler.wfile.write(json.dumps({"status": "success", "locks": locks}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
