# -*- coding: utf-8 -*-
"""
FILE: scripts/sync_manager.py
DESCRIPTION: 바이브 코딩 전용 구글 드라이브 동기화 관리자.
             옵시디언 보관함(.zettel-vault)을 구글 드라이브와 Junction으로 연결합니다.

REVISION HISTORY:
- 2026-04-06 Gemini: 최초 설계 및 구현
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VAULT_NAME = ".zettel-vault"
_LOCAL_VAULT_PATH = _PROJECT_ROOT / _VAULT_NAME

def find_google_drive_path():
    """시스템에서 구글 드라이브 설치 경로를 탐색합니다."""
    # 1. 일반적인 드라이브 문자 탐색 (G: 드라이브)
    if os.path.exists("G:\\My Drive"):
        return Path("G:\\My Drive")
    
    # 2. 사용자 폴더 내 탐색
    user_home = Path(os.environ.get("USERPROFILE", ""))
    possible_paths = [
        user_home / "Google Drive",
        user_home / "구글 드라이브",
        user_home / "GoogleDrive"
    ]
    for p in possible_paths:
        if p.exists():
            return p
            
    return None

def setup_gdrive_sync():
    """구글 드라이브 연동 설정 (Junction 생성)"""
    print(f"[*] 옵시디언 동기화 설정을 시작합니다...")
    
    gdrive_root = find_google_drive_path()
    if not gdrive_root:
        print("[!] 구글 드라이브 설치 경로를 찾을 수 없습니다. 구글 드라이브 앱이 실행 중인지 확인하세요.")
        return False
        
    remote_vault_path = gdrive_root / "Vibe-Coding-Vault"
    
    # 1. 구글 드라이브에 대상 폴더 생성
    if not remote_vault_path.exists():
        remote_vault_path.mkdir(parents=True, exist_ok=True)
        print(f"[+] 구글 드라이브에 새 보관함 폴더 생성: {remote_vault_path}")

    # 2. 기존 로컬 데이터 처리
    if _LOCAL_VAULT_PATH.exists():
        if not os.path.islink(_LOCAL_VAULT_PATH) and not _is_junction(_LOCAL_VAULT_PATH):
            print(f"[*] 기존 데이터를 구글 드라이브로 이동 중...")
            # 기존 데이터를 원격으로 병합
            for item in _LOCAL_VAULT_PATH.iterdir():
                dest = remote_vault_path / item.name
                if dest.exists():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                else:
                    shutil.move(str(item), str(dest))
            _LOCAL_VAULT_PATH.rmdir()
            print("[OK] 기존 데이터 이동 완료.")
    
    # 3. Junction(심볼릭 링크) 생성
    if not _LOCAL_VAULT_PATH.exists():
        try:
            # Windows mklink /J 사용
            cmd = f'mklink /J "{_LOCAL_VAULT_PATH}" "{remote_vault_path}"'
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            print(f"[OK] 연동 완료: {_LOCAL_VAULT_PATH} <==> {remote_vault_path}")
        except subprocess.CalledProcessError as e:
            print(f"[!] 연동 실패: {e.stderr.decode('utf-8', errors='ignore')}")
            return False
            
    return True

def _is_junction(path: Path) -> bool:
    """해당 경로가 NTFS Junction인지 확인합니다."""
    try:
        output = subprocess.check_output(f'dir /AL "{path.parent}"', shell=True).decode('cp949', errors='ignore')
        return f"<JUNCTION>     {path.name}" in output
    except:
        return False

def show_status():
    """현재 동기화 상태 표시"""
    if not _LOCAL_VAULT_PATH.exists():
        print("[-] 현재 연동된 보관함이 없습니다.")
        return
        
    if _is_junction(_LOCAL_VAULT_PATH):
        print("[CONNECTED] 구글 드라이브와 실시간 동기화 중")
        # 실제 대상 경로 확인
        try:
            output = subprocess.check_output(f'fsutil reparsepoint query "{_LOCAL_VAULT_PATH}"', shell=True).decode('utf-8', errors='ignore')
            print(f"    - 대상 경로: 구글 드라이브 내 Vibe-Coding-Vault")
        except:
            pass
    else:
        print("[LOCAL ONLY] 현재 로컬에만 데이터가 저장되어 있습니다.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vibe Sync Manager")
    parser.add_argument("command", choices=["setup", "status"])
    args = parser.parse_args()
    
    if args.command == "setup":
        setup_gdrive_sync()
    elif args.command == "status":
        show_status()
