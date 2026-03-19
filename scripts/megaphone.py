# -*- coding: utf-8 -*-
"""
FILE: scripts/megaphone.py
DESCRIPTION: 하이브 마인드 브로드캐스트 메시지 전송 유틸리티.

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import sys
import json
import urllib.request
import os

def broadcast(terminal_id, content):
    """ 디스코드 브릿지 API를 통해 메시지 전송 """
    url = "http://localhost:8008/send"
    data = json.dumps({
        "terminal_id": int(terminal_id),
        "content": content
    }).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=2) as resp:
            return True
    except Exception as e:
        # 브릿지가 안 켜져 있으면 조용히 실패
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    
    tid = sys.argv[1]
    msg = " ".join(sys.argv[2:])
    broadcast(tid, msg)
