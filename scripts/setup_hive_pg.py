"""
FILE: scripts/setup_hive_pg.py
DESCRIPTION: 하이브 마인드 전용 포터블 PostgreSQL 18 + pgvector 설치 및 초기화 스크립트.
             사용자가 제공한 PG18용 벡터 라이브러리를 우선적으로 적용함.

REVISION HISTORY:
- 2026-03-06 Gemini: PG 16에서 PG 18로 업그레이드 로직 구현. 사용자 제공 벡터 파일(v0.8.2-pg18) 연동.
"""

import os
import sys
import zipfile
import urllib.request
import subprocess
import time
from pathlib import Path

# 설정 (PostgreSQL 18 최신 버전 시도)
PG_VERSION = "18.0-1" 
PG_URL = f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-windows-x64-binaries.zip"
# PG 18이 아직 공식 바이너리로 안풀렸을 경우를 대비한 17 폴백
PG_ALT_URL = "https://get.enterprisedb.com/postgresql/postgresql-17.2-1-windows-x64-binaries.zip"

# 사용자 제공 벡터 파일명
USER_VECTOR_FILE = "vector.v0.8.2-pg18.zip"

PROJECT_ROOT = Path(__file__).parent.parent
BIN_DIR = PROJECT_ROOT / ".ai_monitor" / "bin"
PG_DIR = BIN_DIR / "pgsql"
DATA_DIR = PG_DIR / "data"

def download_file(url, dest):
    print(f"📥 다운로드 시도: {url}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response, open(dest, 'wb') as out_file:
            out_file.write(response.read())
        print(f"✅ 완료: {dest}")
        return True
    except Exception as e:
        print(f"⚠️ 다운로드 실패: {e}")
        return False

def setup():
    # 0. 기존 엔진 정리 (버전 업그레이드를 위해)
    if PG_DIR.exists():
        print("🧹 기존 PostgreSQL 엔진 정리 중 (최신 버전 업그레이드)...")
        import shutil
        try:
            # DB 중지 시도 (pg_manager.py 활용)
            subprocess.run(["python", str(PROJECT_ROOT / "scripts" / "pg_manager.py"), "stop"], capture_output=True)
        except: pass
        time.sleep(2)
        # 폴더 강제 삭제
        shutil.rmtree(PG_DIR, ignore_errors=True)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    PG_DIR.mkdir(parents=True, exist_ok=True)

    pg_zip = BIN_DIR / "pgsql.zip"

    # 1. PostgreSQL 엔진 다운로드 (18 우선, 실패 시 17)
    if not (PG_DIR / "bin" / "postgres.exe").exists():
        success = download_file(PG_URL, pg_zip)
        if not success:
            print("🔄 PG 18 바이너리가 아직 공개되지 않았습니다. 최신 안정 버전인 PG 17로 진행합니다.")
            download_file(PG_ALT_URL, pg_zip)
            
        print("📦 PostgreSQL 엔진 압축 해제 중...")
        with zipfile.ZipFile(pg_zip, 'r') as zip_ref:
            # EDB zip은 내부에 'pgsql' 폴더가 있음
            zip_ref.extractall(BIN_DIR)
        if pg_zip.exists(): pg_zip.unlink()

    # 2. 사용자 제공 pgvector 파일 배치 (vector.v0.8.2-pg18.zip)
    user_vector_zip = BIN_DIR / USER_VECTOR_FILE
    if user_vector_zip.exists():
        print(f"🚀 사용자 제공 {USER_VECTOR_FILE} 파일 배치 중 (v18 호환)...")
        with zipfile.ZipFile(user_vector_zip, 'r') as zip_ref:
            temp_vector = BIN_DIR / "temp_vector"
            zip_ref.extractall(temp_vector)
            
            # bin, lib 폴더 내 dll 배치
            for sub in ["lib", "bin"]:
                src = temp_vector / sub / "vector.dll"
                if src.exists():
                    dest = PG_DIR / sub / "vector.dll"
                    (PG_DIR / sub).mkdir(parents=True, exist_ok=True)
                    os.replace(src, dest)
            
            # extension 파일들 배치
            ext_src = temp_vector / "share" / "extension"
            ext_dest = PG_DIR / "share" / "extension"
            ext_dest.mkdir(parents=True, exist_ok=True)
            if ext_src.exists():
                for f in ext_src.glob("*"):
                    os.replace(f, ext_dest / f.name)
            
            import shutil
            if temp_vector.exists(): shutil.rmtree(temp_vector)
        print("✅ 최신 pgvector 배치 완료.")
    else:
        print(f"⚠️ {USER_VECTOR_FILE} 파일을 찾을 수 없어 기본 모드로 진행합니다.")

    # 3. 데이터베이스 초기화 및 포트 설정
    if not (DATA_DIR / "PG_VERSION").exists():
        print("🚀 최신 엔진으로 데이터베이스 초기화 중 (initdb)...")
        initdb_exe = PG_DIR / "bin" / "initdb.exe"
        try:
            subprocess.run([
                str(initdb_exe), "-D", str(DATA_DIR), "-U", "postgres", "-A", "trust", "--encoding=UTF8"
            ], check=True)
            
            # 포트 5433 설정
            conf_file = DATA_DIR / "postgresql.conf"
            if conf_file.exists():
                with open(conf_file, "r", encoding="utf-8") as f:
                    content = f.read()
                content = content.replace("#port = 5432", "port = 5433")
                with open(conf_file, "w", encoding="utf-8") as f:
                    f.write(content)
                print("✅ 포트 설정 완료: 5433")
            print("✅ DB 초기화 성공.")
        except Exception as e:
            print(f"❌ DB 초기화 실패: {e}")
            return

    print("\n🎉 PostgreSQL 최신 엔진 업그레이드 및 설정 완료!")
    print(f"현재 경로: {PG_DIR}")
    print("가동 명령어: python scripts/pg_manager.py start")

if __name__ == "__main__":
    setup()
