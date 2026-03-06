# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/auto_release.py
# 📝 설명: 하이브 마인드 자율 배포(Autonomous Release) 엔진.
#          프로젝트 구성을 감지하여 빌드 및 인스톨러 생성을 자동화합니다.
#
# REVISION HISTORY:
# - 2026-03-06 Gemini-1: 최초 작성 및 자율 빌드/배포 로직 구현.
# ------------------------------------------------------------------------
import os
import sys
import subprocess
import time
import json
from datetime import datetime

# 하이브 브릿지 로드
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
try:
    sys.path.append(PROJECT_ROOT)
    import scripts.hive_bridge as hive_bridge
except ImportError:
    hive_bridge = None

def log(msg, status="success"):
    print(f"[{status.upper()}] {msg}")
    if hive_bridge:
        hive_bridge.log_task("auto_release", msg, "RELEASE", status)

def run_cmd(cmd_list, desc):
    log(f"{desc} 시작...")
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            cmd_list, capture_output=True, text=True, encoding='utf-8', 
            errors='replace', creationflags=_no_window
        )
        if res.returncode == 0:
            log(f"{desc} 성공!")
            return True
        else:
            log(f"{desc} 실패: {res.stderr[:200]}", "error")
            return False
    except Exception as e:
        log(f"{desc} 오류 발생: {e}", "error")
        return False

def auto_release():
    log("🚀 자율 배포 시퀀스 가동 (Smart Builder v1.0)")
    
    # 1. 버전 업데이트 (auto_version.py 연동)
    v_script = os.path.join(PROJECT_ROOT, "scripts", "auto_version.py")
    if os.path.exists(v_script):
        if not run_cmd([sys.executable, v_script], "버전 자동 업데이트"):
            return

    # 2. PyInstaller 빌드 (vibe-coding.spec 탐지)
    spec_file = os.path.join(PROJECT_ROOT, "vibe-coding.spec")
    if os.path.exists(spec_file):
        if not run_cmd(["pyinstaller", spec_file, "--noconfirm"], "PyInstaller 빌드"):
            return

    # 3. Inno Setup 인스톨러 빌드 (vibe-coding-setup.iss 탐지)
    iss_file = os.path.join(PROJECT_ROOT, "vibe-coding-setup.iss")
    if os.name == 'nt' and os.path.exists(iss_file):
        iscc = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if os.path.exists(iscc):
            run_cmd([iscc, iss_file], "Inno Setup 인스톨러 빌드")
        else:
            log("ISCC.exe를 찾을 수 없어 인스톨러 빌드는 건너뜁니다.", "warning")

    log("✅ 자율 배포 시퀀스 완료!", "success")

if __name__ == "__main__":
    auto_release()
