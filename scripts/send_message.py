# -*- coding: utf-8 -*-
"""
에이전트 간 메시지 채널 헬퍼 스크립트
---------------------------------------
사용법:
  python scripts/send_message.py <from> <to> <type> <content>
"""

import sys
import json
import urllib.request
import urllib.error
import os
import time

# 서버 포트 자동 감지 (개발: 8000, 배포: 8005)
DEFAULT_PORTS = [8005, 8000]

def send_message(from_agent: str, to_agent: str, msg_type: str, content: str, port: int = None) -> bool:
    ports_to_try = [port] if port else DEFAULT_PORTS
    payload = json.dumps({
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
    }).encode('utf-8')

    for p in ports_to_try:
        try:
            req = urllib.request.Request(
                f'http://localhost:{p}/api/message',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                if result.get('status') == 'success':
                    return True
        except:
            continue

    # Fallback: 직접 파일 기록
    return _fallback_write(from_agent, to_agent, msg_type, content)

def _fallback_write(from_agent: str, to_agent: str, msg_type: str, content: str) -> bool:
    project_root = os.getcwd()
    data_dir = os.path.join(project_root, '.ai_monitor', 'data')
    os.makedirs(data_dir, exist_ok=True)
    messages_file = os.path.join(data_dir, 'messages.jsonl')

    msg = {
        'id': str(int(time.time() * 1000)),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'from': from_agent,
        'to': to_agent,
        'type': msg_type,
        'content': content,
        'read': False,
    }

    try:
        with open(messages_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        return True
    except:
        return False

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) < 4:
        sys.exit(1)

    from_a, to_a, m_type, *content_parts = args
    content_str = ' '.join(content_parts)
    send_message(from_a, to_a, m_type, content_str)
