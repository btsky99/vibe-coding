"""
FILE: api/message_api.py
DESCRIPTION: 에이전트 간 메시지 전송 API — 메시지를 DB(send_message)에 저장하고, 수신 대상
             에이전트의 PTY 세션에 HTTP로 주입(Node PTY REST)하며, session_logs에 알림 기록한다.
             server.py do_POST '/api/message'에서 위임.

REVISION HISTORY:
- 2026-08-09 Claude: 터미널 이름 라우팅의 정본을 config.json(slot_names)으로 이전
                     (Phase 11 Task 37). pty-server 값은 연결 시점 스냅샷이라 이름을 바꾼
                     뒤 재연결 전까지 옛 이름으로 배달되던 문제.
- 2026-07-05 Claude: server.py do_POST '/api/message' 89줄 분리(long-tail 라운드). 로직 원본 동일
  (verbatim). WS_PORT는 런타임 재설정 전역, send_message는 db_helper 경로 2갈래라 파라미터 주입.
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path


def _load_slot_names() -> dict:
    """config.json의 slot_names{터미널ID: 이름}. 실패하면 빈 dict.

    [제약] 예외를 삼킨다 — 이름 조회 실패로 메시지 배달 자체가 죽으면 안 된다.
      빈 dict면 호출부가 pty 값으로 폴백하므로 동작은 이전과 같아진다.
    """
    try:
        from src.pg_base import DATA_DIR
        cfg = json.loads((DATA_DIR / 'config.json').read_text(encoding='utf-8'))
        names = cfg.get('slot_names')
        return names if isinstance(names, dict) else {}
    except Exception:
        return {}


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
                _cfg_names = _load_slot_names()
                for _slot_id, _sess in (_sessions.items() if isinstance(_sessions, dict) else []):
                    _agent = str(_sess.get('agent', '')).lower()
                    # [🔴 이름의 정본은 config.json 하나다] pty-server가 들고 있는 slot_name은
                    #   연결 시점에 전달된 값이라, 사용자가 이름을 바꾼 뒤 재연결하기 전까지
                    #   옛 이름으로 라우팅된다. config를 먼저 보고 없을 때만 폴백한다.
                    _term = str(_slot_id).split('@')[0]
                    _slot_name = (str(_cfg_names.get(_term, '')).lower()
                                  or str(_sess.get('slot_name', '')).lower())
                    if not _sess.get('running', False):
                        continue
                    if _to in _agent or _agent.startswith(_to) or (_slot_name and _to in _slot_name):
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
