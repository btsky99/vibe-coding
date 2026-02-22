# ------------------------------------------------------------------------
# 📄 파일명: megaphone.py
# 📂 메인 문서 링크: docs/README.md
# 🔗 개별 상세 문서: docs/megaphone.py.md
# 📝 설명: 하이브 마인드의 다중 에이전트 간 소통을 위한 메가폰 스크립트.
#          다른 터미널 창의 PTY(명령 프롬프트)로 직접 명령어나 메시지를 쏴줍니다.
# ------------------------------------------------------------------------

import sys
import os
import json
import urllib.request
import urllib.parse
import argparse
import subprocess
from datetime import datetime

def log_to_hive(agent_name, task_summary):
    """hive_bridge.py를 호출하여 하이브에 로그를 남깁니다."""
    try:
        script_path = os.path.join(os.path.dirname(__file__), "hive_bridge.py")
        subprocess.run([sys.executable, script_path, agent_name, task_summary], check=True)
    except Exception as e:
        print(f"[하이브 로깅 실패] {e}")

def send_command_to_terminal(target_slot, command, agent_name=None, is_delegation=False):
    """지정된 터미널 슬롯으로 명령어를 전송합니다."""
    # 윈도우 한글 인코딩 깨짐 방지를 위해 CP949 터미널에서 실행될 것을 대비
    if isinstance(command, bytes):
        command = command.decode('utf-8', errors='replace')
        
    # 위임(Delegation)인 경우 메시지 포맷팅
    if is_delegation:
        from_agent = agent_name or "Unknown Agent"
        # 메시지 끝에 확실히 개행 문자를 추가하여 자동 입력되게 함
        delegation_msg = f"\n[📢 DELEGATION FROM {from_agent}]\n>>> {command}\n\n(위 업무를 분석하고 수행해 주세요)\n"
        final_msg = delegation_msg
    else:
        # 일반 명령어의 경우 끝에 \n을 붙여 자동 실행 유도
        final_msg = command if command.endswith('\n') else command + '\n'

    url = "http://localhost:8000/api/send-command"
    payload = {
        "target": str(target_slot),
        "command": final_msg
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode('utf-8')
            res = json.loads(res_data)
            if res.get('status') == 'success':
                print(f"[메가폰 전송 성공] ➡️ Terminal {target_slot}: {command}")
                # 하이브에 활동 기록
                status_msg = f"DELEGATE TO Terminal {target_slot}: {command}" if is_delegation else f"Sent message to Terminal {target_slot}: {command}"
                log_to_hive(agent_name or "Gemini-1", status_msg)
            else:
                print(f"[메가폰 전송 실패] ❌ {res.get('message', 'Unknown Error')}")
    except Exception as e:
        print(f"[메가폰 통신 에러] ❌ 넥서스 뷰 서버에 연결할 수 없거나, 서버 내부 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="하이브 마인드 터미널 간 직접 통신 메가폰")
    parser.add_argument("--target", required=True, help="메시지를 보낼 타겟 터미널 번호 (예: 1, 2, 3)")
    parser.add_argument("--message", required=True, help="해당 터미널의 프롬프트에 자동으로 타이핑될 명령어/메시지")
    parser.add_argument("--agent", default="Gemini-1", help="발신 에이전트 이름")
    parser.add_argument("--delegate", action="store_true", help="업무 위임 모드로 전송 (안내 문구 포함)")
    
    args = parser.parse_args()
    
    # 메시지를 대상 터미널에 전송
    send_command_to_terminal(args.target, args.message, args.agent, args.delegate)
