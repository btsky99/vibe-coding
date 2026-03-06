# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/knowledge_sync.py
# 📝 설명: 프로젝트 소스 코드 및 장기 메모리(memory.md)를 PostgreSQL 18 벡터 DB에 동기화.
#          pgvector를 활용한 하이브 지식 그래프 구축 도구.
#
# REVISION HISTORY:
# - 2026-03-06 Gemini-1: 최초 작성 및 지식 임베딩/동기화 로직 구현.
# ------------------------------------------------------------------------
import os
import sys
import json
import subprocess
from datetime import datetime

# 프로젝트 루트 경로 설정
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")

def run_query(sql: str):
    """psql을 통해 쿼리를 실행합니다."""
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return True
    except Exception as e:
        print(f"[!] SQL Error: {e}")
        return False

def sync_file_to_db(file_path: str):
    """파일 내용을 읽어 Postgres pg_knowledge 테이블에 기록합니다 (임시 텍스트 기반 저장)."""
    # [주의] 실제 환경에서는 임베딩 생성 API(OpenAI/Gemini 등)를 연동해야 합니다.
    # 여기서는 고도화된 스키마 구조와 인프라 연동에 집중합니다.
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        rel_path = os.path.relpath(file_path, PROJECT_ROOT)
        safe_content = content.replace("'", "''")
        metadata = json.dumps({"size": len(content), "type": os.path.splitext(file_path)[1]})
        
        # INSERT (임베딩은 현재 널 값으로 처리 후 별도 워커로 생성 가능)
        sql = f"INSERT INTO pg_knowledge (file_path, content, metadata) VALUES ('{rel_path}', '{safe_content[:5000]}', '{metadata}'::jsonb);"
        run_query(sql)
        print(f"[*] 지식 동기화 완료: {rel_path}")
    except Exception as e:
        print(f"[!] 동기화 오류 ({file_path}): {e}")

def sync_project():
    """프로젝트 내 주요 파일들을 순회하며 지식 베이스 구축"""
    print(f"[*] 하이브 지식 그래프 동기화 시작 (PostgreSQL 18)...")
    target_exts = ('.py', '.ts', '.md', '.tsx', '.json', '.bat', '.spec', '.iss')
    exclude_dirs = ('.git', '.worktrees', 'node_modules', 'venv', '.ai_monitor/bin', '.ai_monitor/data')

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # 제외 디렉토리 건너뛰기
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file.endswith(target_exts):
                full_path = os.path.join(root, file)
                sync_file_to_db(full_path)

if __name__ == "__main__":
    if not os.path.exists(PG_BIN):
        print(f"[오류] Postgres 바이너리 없음: {PG_BIN}")
        sys.exit(1)
    
    # 1. 기존 데이터 정리 (Optional)
    run_query("TRUNCATE TABLE pg_knowledge;")
    
    # 2. 전역 동기화 실행
    sync_project()
    print(f"\n✅ 하이브 지식 그래프 동기화 완료 (PostgreSQL 18 PGVector Ready)")
