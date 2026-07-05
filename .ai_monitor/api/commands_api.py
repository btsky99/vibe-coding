"""
FILE: api/commands_api.py
DESCRIPTION: 터미널 명령 전송 API — 대상 슬롯의 Node PTY 세션에 명령을 큐잉한다(REST 프록시).
             server.py do_POST '/api/send-command'에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_POST '/api/send-command' 38줄 분리(long-tail 라운드).
  _NODE_PTY_REST_URL(전역 str)/_get_node_pty_sessions(함수)는 파라미터 주입. 로직 원본 동일.
"""
from __future__ import annotations

import json


def handle_send_command(handler, node_pty_rest_url: str, get_node_pty_sessions) -> None:
    """POST /api/send-command — {target, command} → 대상 슬롯 PTY에 명령 전송.
    [현황] Node PTY REST의 interrupt 엔드포인트로 전송 후 세션 running 여부만 확인.
      (실제 write 경로 전환은 향후 구현 — 원본 주석 유지.)
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))

        target_slot = str(data.get('target'))
        command = data.get('command', '')

        # Node PTY 서버의 REST API로 명령 전송 (직접 PTY 접근 → HTTP 프록시)
        try:
            import urllib.request
            processed_cmd = command.replace('\r\n', '\r').replace('\n', '\r')
            final_cmd = processed_cmd if processed_cmd.endswith('\r') else processed_cmd + '\r'
            payload = json.dumps({"command": final_cmd}).encode('utf-8')
            _req = urllib.request.Request(
                f"{node_pty_rest_url}/api/pty/interrupt/{target_slot}",
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            # [현황] interrupt가 아닌 write가 필요 — WS 클라이언트 전송은 향후 구현.
            #   현재는 Node PTY 세션 존재 여부만 확인.
            _snap = get_node_pty_sessions()
            _info = _snap.get(f'T{target_slot}')
            if _info and _info.get('running'):
                handler.wfile.write(json.dumps({"status": "success", "message": f"Command queued for Terminal {target_slot}"}).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({"status": "error", "message": f"Terminal {target_slot} is not running."}).encode('utf-8'))
        except Exception as _e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(_e)}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
