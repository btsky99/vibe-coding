# ------------------------------------------------------------------------
# 📄 파일명: megaphone.py
# 📂 메인 문서 링크: docs/README.md
# 🔗 개별 상세 문서: docs/megaphone.py.md
# 📝 설명: 하이브 마인드의 다중 에이전트 간 소통을 위한 메가폰 스크립트.
#          다른 터미널 창의 PTY(명령 프롬프트)로 직접 명령어나 메시지를 쏴줍니다.
# ------------------------------------------------------------------------

import sys
import json
import urllib.request
import urllib.parse
import argparse

def send_command_to_terminal(target_slot, command):
    """지정된 터미널 슬롯으로 명령어를 전송합니다."""
    # 윈도우 한글 인코딩 깨짐 방지를 위해 CP949 터미널에서 실행될 것을 대비
    if isinstance(command, bytes):
        command = command.decode('utf-8', errors='replace')
        
    url = "http://localhost:8000/api/send-command"
    payload = {
        "target": str(target_slot),
        "command": command
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode('utf-8')
            res = json.loads(res_data)
            if res.get('status') == 'success':
                print(f"[메가폰 전송 성공] ➡️ Terminal {target_slot}: {command}")
            else:
                print(f"[메가폰 전송 실패] ❌ {res.get('message', 'Unknown Error')}")
    except Exception as e:
        print(f"[메가폰 통신 에러] ❌ 넥서스 뷰 서버에 연결할 수 없거나, 서버 내부 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="하이브 마인드 터미널 간 직접 통신 메가폰")
    parser.add_argument("--target", required=True, help="메시지를 보낼 타겟 터미널 번호 (예: 1, 2, 3)")
    parser.add_argument("--message", required=True, help="해당 터미널의 프롬프트에 자동으로 타이핑될 명령어/메시지")
    
    args = parser.parse_args()
    
    # 메시지를 대상 터미널에 전송
    send_command_to_terminal(args.target, args.message)
