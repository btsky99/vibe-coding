"""
FILE: api/message_api.py
DESCRIPTION: 에이전트 간 메시지 전송 API — 메시지를 DB(send_message)에 저장하고, 수신 대상
             에이전트의 PTY 세션에 HTTP로 주입(Node PTY REST)하며, session_logs에 알림 기록한다.
             server.py do_POST '/api/message'에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_POST '/api/message' 89줄 분리(long-tail 라운드). 로직 원본 동일
  (verbatim). WS_PORT는 런타임 재설정 전역, send_message는 db_helper 경로 2갈래라 파라미터 주입.
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path


def handle_send(handler, ws_port: int, base_dir: Path, send_message) -> None:
    """POST /api/message — {from,to,type,content} 저장 + 대상 PTY 주입 + 로그.
    [제약] to가 ceo/all/broadcast/''가 아니면 Node PTY REST(/api/pty/sessions→write)로 주입.
      CEO(사람)는 PTY 없어 스킵. WS_PORT는 호출 시점 값(런타임 슬롯 기반 재설정).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))

        # 메시지 객체 생성 (ID: 밀리초 타임스탬프)
        msg = {
            'id': str(int(time.time() * 1000)),
            'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S"),
            'from': str(data.get('from', 'unknown')),
            'to': str(data.get('to', 'all')),
            'type': str(data.get('type', 'info')),
            'content': str(data.get('content', '')),
            'read': False,
        }

        # DB에 삽입
        send_message(msg['id'], msg['from'], msg['to'], msg['type'], msg['content'])

        content_to_send = msg['content']

        # PTY inject: to 대상 터미널에 메시지 전달. CEO(사람)는 PTY 없어 스킵.
        _to = msg['to'].lower()
        if _to not in ('ceo', 'all', 'broadcast', ''):
            try:
                import urllib.request as _ureq
                # /api/pty/sessions → {"T1": {"agent":"claude","running":true,...}, ...}
                _sessions_url = f'http://127.0.0.1:{ws_port}/api/pty/sessions'
                with _ureq.urlopen(_sessions_url, timeout=2) as _r:
                    _sessions = json.loads(_r.read().decode())
                for _slot_id, _sess in (_sessions.items() if isinstance(_sessions, dict) else []):
                    _agent = str(_sess.get('agent', '')).lower()
                    _slot_name = str(_sess.get('slot_name', '')).lower()
                    if not _sess.get('running', False):
                        continue
                    if _to in _agent or _agent.startswith(_to) or _to in _slot_name:
                        _write_url = f'http://127.0.0.1:{ws_port}/api/pty/write/{_slot_id}'
                        _payload = json.dumps({'text': content_to_send}).encode()
                        _req = _ureq.Request(
                            _write_url, data=_payload,
                            headers={'Content-Type': 'application/json'}, method='POST',
                        )
                        _ureq.urlopen(_req, timeout=2)
                        print(f'[msg→PTY] {msg["from"]} → {_slot_id}({_agent}) : {content_to_send[:40]}')
                        break
            except Exception as _e:
                print(f'[msg inject error] to={_to} err={_e}')

        # session_logs 테이블에도 알림 기록 (로그 뷰/SSE 반영)
        try:
            sys.path.append(str(base_dir))
            from src.secure import mask_sensitive_data
            from src.db_helper import insert_log
            safe_content = mask_sensitive_data(msg['content'])
            insert_log(
                session_id=f"msg_{int(time.time())}",
                terminal_id="MSG_CHANNEL", agent=msg['from'],
                trigger_msg=f"[메시지→{msg['to']}] {safe_content[:100]}",
                project_id="hive", status="success",
            )
        except Exception as e:
            print(f"Error logging message to session_logs: {e}")

        handler.wfile.write(json.dumps({'status': 'success', 'msg': msg}, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
