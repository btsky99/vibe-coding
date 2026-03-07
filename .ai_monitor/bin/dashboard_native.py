# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/bin/dashboard_native.py
DESCRIPTION: pywebview 기반 윈도우 네이티브 웹 대시보드.
             로컬 웹 UI를 네이티브 데스크톱 창에 임베드하고,
             8개의 터미널 슬롯을 격자형으로 배치해 각 터미널의 에이전트를 직접 제어합니다.

REVISION HISTORY:
- 2026-03-07 Gemini: 최초 구현 (Windows Native Web 전환)
"""

import os
import sys
import json
import threading
import time
import webview
from pathlib import Path
from urllib import request as urllib_request

# 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
HTML_PATH = BASE_DIR / "src" / "native_dashboard.html"
SERVER_URL = "http://localhost:8005"

class DashboardAPI:
    def run_agent(self, terminal_id, task, mode):
        """JS에서 호출되는 에이전트 실행 함수"""
        print(f"[*] Native Request: {terminal_id} | {mode} | {task}")
        
        # 서버 API 호출
        url = f"{SERVER_URL}/api/agent/run"
        payload = json.dumps({
            "task": task,
            "cli": mode if mode != 'auto' else 'auto',
            "terminal_id": terminal_id
        }).encode('utf-8')
        
        try:
            req = urllib_request.Request(
                url, data=payload, 
                headers={'Content-Type': 'application/json'}, 
                method='POST'
            )
            with urllib_request.urlopen(req) as resp:
                print(f"[+] API Response: {resp.status}")
        except Exception as e:
            print(f"[!] API Error: {e}")

def poll_status(window):
    """서버에서 상태를 폴링하여 UI에 업데이트"""
    while True:
        try:
            # 1. 에이전트 라이브 상태 확인
            with urllib_request.urlopen(f"{SERVER_URL}/api/hive/health") as resp:
                # 간단한 헬스체크 예시
                pass
            
            # TODO: 실제 에이전트 상태(agent_live.jsonl) 연동 필요
            # window.evaluate_js(f"dashboard.setStatus('T1', 'claude', 'active')")
            
        except:
            pass
        time.sleep(2)

if __name__ == '__main__':
    api = DashboardAPI()
    
    # 윈도우 생성
    window = webview.create_window(
        'Vibe Coding - Native Desktop Dashboard',
        str(HTML_PATH),
        js_api=api,
        width=1600,
        height=900,
        background_color='#1e1e1e'
    )
    
    # 상태 업데이트 스레드
    # threading.Thread(target=poll_status, args=(window,), daemon=True).start()
    
    webview.start(debug=True)
