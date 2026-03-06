# -*- coding: utf-8 -*-
import os
import time
import json
import subprocess
import sys

# 설정
MSG_FILE = r"D:\vibe-coding\.ai_monitor\data\messages.jsonl"
MEGAPHONE = r"D:\vibe-coding\scripts\megaphone.py"

def get_gemini_response(prompt):
    """ Gemini CLI를 호출하여 답변을 생성 """
    try:
        # gemini "질문" 명령 실행
        # (현재 환경에 gemini CLI가 설치되어 있다고 가정)
        result = subprocess.run(
            ['gemini', prompt],
            capture_output=True,
            text=True,
            encoding='utf-8',
            shell=True
        )
        return result.stdout.strip()
    except Exception as e:
        return f"에러 발생: {str(e)}"

def main():
    print("🦊 Gemini Autonomous Watchdog 가동 시작...")
    
    if not os.path.exists(MSG_FILE):
        open(MSG_FILE, 'w').close()

    # 파일 끝으로 이동
    with open(MSG_FILE, 'r', encoding='utf-8') as f:
        f.seek(0, os.SEEK_END)
        last_pos = f.tell()

    while True:
        try:
            curr_size = os.path.getsize(MSG_FILE)
            if curr_size > last_pos:
                with open(MSG_FILE, 'r', encoding='utf-8') as f:
                    f.seek(last_pos)
                    lines = f.readlines()
                    for line in lines:
                        if not line.strip(): continue
                        data = json.loads(line)
                        
                        # 나(gemini)에게 온 메시지이고, 내가 보낸 게 아닐 때
                        if data.get('to') == 'gemini' and not data.get('from').startswith('gemini'):
                            content = data.get('content', '')
                            # 터미널 ID 추출
                            tid = 1
                            if "[Terminal " in content:
                                try: tid = int(content.split("[Terminal ")[1].split("]")[0])
                                except: pass
                            
                            actual_prompt = content.split("] ", 1)[-1] if "]" in content else content
                            
                            print(f"📥 명령 감지 (T{tid}): {actual_prompt}")
                            
                            # 1. Gemini에게 물어보기
                            response = get_gemini_response(actual_prompt)
                            
                            # 2. 결과가 있으면 디스코드로 쏘기
                            if response:
                                print(f"📤 답변 생성 완료. 디스코드로 전송 중...")
                                subprocess.run(['python', MEGAPHONE, str(tid), f"🤖 **GEMINI:** {response}"], shell=True)
                    
                    last_pos = f.tell()
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    main()
