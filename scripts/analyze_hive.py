# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/analyze_hive.py
# 📝 설명: PostgreSQL 18 기반 하이브 마인드 고도화 분석 도구.
#          에이전트들의 작업 패턴, 사고 연쇄, 협업 효율성을 정밀 분석합니다.
# ------------------------------------------------------------------------
import os
import sys
import subprocess
import json
from datetime import datetime

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")

def run_query(sql: str):
    """psql을 통해 쿼리를 실행하고 결과를 반환합니다."""
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql, "--csv"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return res.stdout.strip()
    except Exception as e:
        return f"Error: {e}"

def print_report():
    print("\n" + "="*60)
    print(f"📊 하이브 마인드 고도화 분석 보고서 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("="*60)

    # 1. 에이전트별 작업 기여도
    print("\n[1] 에이전트별 작업 기여도 (최근 24시간)")
    sql_contrib = "SELECT agent, COUNT(*) as count FROM pg_logs WHERE ts > NOW() - INTERVAL '24 hours' GROUP BY agent ORDER BY count DESC;"
    print(run_query(sql_contrib))

    # 2. 최근 주요 사고 과정 (Thought Stream)
    print("\n[2] 최근 주요 사고 과정 (Thought Stream)")
    sql_thoughts = "SELECT agent, skill, thought->>'text' as thought_text FROM pg_thoughts ORDER BY ts DESC LIMIT 5;"
    print(run_query(sql_thoughts))

    # 3. 에이전트 간 메시지 통계
    print("\n[3] 에이전트 간 메시지 교환 통계")
    sql_msg = "SELECT from_agent, to_agent, COUNT(*) as count FROM pg_messages GROUP BY from_agent, to_agent ORDER BY count DESC;"
    print(run_query(sql_msg))

    # 4. 시스템 상태 요약
    print("\n[4] PostgreSQL 18 인프라 상태")
    sql_version = "SELECT version();"
    print(run_query(sql_version))
    
    print("\n" + "="*60)
    print("💡 팁: 'pg_thoughts'의 JSONB 데이터를 활용하여 사고 연쇄 분석이 가능합니다.")
    print("="*60)

if __name__ == "__main__":
    if not os.path.exists(PG_BIN):
        print(f"[오류] PostgreSQL 바이너리를 찾을 수 없습니다: {PG_BIN}")
        sys.exit(1)
    print_report()
