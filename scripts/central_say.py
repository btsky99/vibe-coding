"""
FILE: scripts/central_say.py
DESCRIPTION: 슬롯 CLI가 아픽스 중앙 대화(서로 대화)에 답하는 수단.
             `python scripts/central_say.py 1-1 "답할 내용"` 한 줄로 발신한다.
             central_inject가 주입하는 안내문이 가리키는 스크립트 — 이름/인자를 바꾸면
             주입문(src/central_inject._format)도 같이 바꿔야 왕복이 끊기지 않는다.

[🔴 왜 pg_central.send_message를 직접 부르지 않는가]
  직접 부르면 DB에는 남지만 상대 슬롯 CLI에 주입되지 않는다 — 주입은 서버의
  /api/central/send 핸들러에 걸려 있기 때문이다. DB에만 남으면 상대는 화면을 봐야만
  알 수 있어 자동 왕복이 거기서 끝난다. 반드시 서버 경유로 보낸다.

[제약] 서버가 꺼져 있으면 보내지 않고 실패를 알린다. 조용히 DB 직접 쓰기로 폴백하면
  '보냈다는데 상대가 못 받는' 상태가 되어 원인 추적이 어려워진다.

REVISION HISTORY:
- 2026-08-09 Claude: 신규. 중앙 버스 슬롯 멘션의 양방향화(1-1 ↔ 1-2).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '.ai_monitor'))


def _server_base() -> str:
    from src.server_locator import find_server_port
    port = find_server_port() or 0
    return f'http://127.0.0.1:{port}' if port else ''


def _self_agent() -> str:
    """이 CLI가 몇 번 슬롯인지. TERMINAL_ID가 'T2'/'2' 어느 쪽이어도 받는다.

    [제약] 알 수 없으면 'claude'로 보낸다 — 슬롯을 못 붙이는 것이, 남의 슬롯 번호를
      추측해 사칭하는 것보다 낫다.
    """
    raw = os.environ.get('TERMINAL_ID', '') or os.environ.get('VIBE_TERMINAL_ID', '')
    m = re.search(r'T?(\d+)', str(raw))
    return f'claude:T{m.group(1)}' if m else 'claude'


def _resolve(addr: str) -> tuple[str, str, str]:
    """'1-2' / '@1-2' / '1' → (to_node, to_agent, 표기). 노드만 주면 그 노드 전체."""
    from src import pg_central
    token = str(addr or '').strip().lstrip('@')
    m = re.match(r'^(?:아픽스)?\s*(\d+)(?:-(\d+))?$', token)
    if not m:
        return '', '', token
    seq, slot = int(m.group(1)), m.group(2)
    node_id = ''
    for ref in pg_central.list_node_refs():
        if int(ref.get('node_seq') or 0) == seq:
            node_id = str(ref.get('node_id') or '')
            break
    return node_id, (f'claude:T{slot}' if slot else ''), token


def main() -> int:
    args = [a for a in sys.argv[1:] if a.strip()]
    if len(args) < 2:
        print('사용법: python scripts/central_say.py <주소: 1-1> "보낼 내용"')
        return 2

    addr, content = args[0], ' '.join(args[1:])
    to_node, to_agent, shown = _resolve(addr)
    if not to_node:
        print(f'[실패] 주소 "{shown}"에 해당하는 노드를 명부에서 못 찾음')
        return 1

    base = _server_base()
    if not base:
        print('[실패] 로컬 서버를 찾지 못함 — 앱이 떠 있어야 상대 슬롯에 전달된다')
        return 1

    payload = json.dumps({
        'content': content, 'to_node': to_node,
        'to_agent': to_agent, 'from_agent': _self_agent(),
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f'{base}/api/central/send', data=payload,
                                 headers={'Content-Type': 'application/json'},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f'[실패] 발신 오류: {e}')
        return 1

    if not res.get('ok'):
        print(f'[실패] {res.get("error")}')
        return 1
    # delivered는 상대 슬롯 CLI 주입 결과 — 'ok'가 아니면 화면에만 남았다는 뜻이다.
    print(f'[전송] → 아픽스 {shown} (id={res.get("id")}, 주입={res.get("delivered")})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
