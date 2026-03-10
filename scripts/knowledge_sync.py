# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/knowledge_sync.py
# 📑 설명: memory.md의 장기 기억을 PostgreSQL pg_thoughts 테이블로 동기화.
#          지식 그래프 시각화를 위한 데이터 계보(Lineage)를 형성합니다.
#
# 🕒 변경 이력 (History):
# [2026-03-10] Gemini: 최초 생성 및 동기화 로직 구현 (Task 17)
# ------------------------------------------------------------------------
import os
import re
import json
import subprocess
import sys
from pathlib import Path

# 윈도우 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_MD = PROJECT_ROOT / "memory.md"
PG_BIN = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
PG_PORT = 5433

def run_sql(sql: str):
    """임시 파일을 생성하여 SQL 실행 (인코딩 오류 방지 및 순수 값 추출)"""
    if not PG_BIN.exists():
        print(f"❌ psql.exe를 찾을 수 없음: {PG_BIN}")
        return None
    
    tmp_file = Path("tmp_sync.sql")
    try:
        # UTF-8로 파일 저장
        tmp_file.write_text(sql, encoding='utf-8')
        
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # -t (tuples only), -A (no align) 옵션 추가
        res = subprocess.run(
            [str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", "-t", "-A", "-f", str(tmp_file)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        
        if tmp_file.exists():
            tmp_file.unlink()
            
        if res.returncode != 0:
            print(f"❌ SQL 오류: {res.stderr}")
            return None
        return res.stdout.strip()
    except Exception as e:
        if tmp_file.exists(): tmp_file.unlink()
        print(f"❌ 실행 에러: {e}")
        return None

def parse_memory():
    """memory.md 파싱하여 결정 사항 및 관계 추출"""
    if not MEMORY_MD.exists():
        return [], []
    
    content = MEMORY_MD.read_text(encoding='utf-8')
    
    # 1. 핵심 결정 사항 추출 (Section 2)
    decisions = []
    dec_section = re.search(r"## 🏗️ 2\. 핵심 아키텍처 및 결정 사항.*?(?=##|$)", content, re.S)
    if dec_section:
        items = re.findall(r"- \*\*([^*]+)\*\*: ([^\n]+)", dec_section.group(0))
        for title, desc in items:
            decisions.append({
                "title": title.strip(),
                "description": desc.strip()
            })
            
    # 2. 지식 관계 추출 (Section 4)
    relations = []
    rel_section = re.search(r"## 🔗 4\. 지식 간의 관계.*?(?=\n---|$)", content, re.S)
    if rel_section:
        # 형식: `A` → `B` (관계 설명)
        links = re.findall(r"- `([^`]+)` → `([^`]+)`\s*(?:\(([^)]+)\))?", rel_section.group(0))
        for src, dest, reason in links:
            relations.append({
                "source": src.strip(),
                "target": dest.strip(),
                "reason": reason.strip() if reason else "의존성"
            })
            
    return decisions, relations

def sync():
    print(f"📂 {MEMORY_MD.name} 분석 중...")
    decisions, relations = parse_memory()
    
    if not decisions:
        print("⚠️ 추출된 결정 사항이 없습니다.")
        return

    print(f"🧠 {len(decisions)}개의 결정 사항 동기화 중...")
    
    # 제목 -> ID 매핑 (관계 설정을 위함)
    title_to_id = {}
    
    for dec in decisions:
        title = dec['title']
        desc = dec['description']
        thought_json = json.dumps({
            "type": "decision",
            "title": title,
            "content": desc
        }, ensure_ascii=False).replace("'", "''")
        
        # Upsert 로직 (제목 기준)
        # 먼저 존재하는지 확인
        safe_title = title.replace("'", "''")
        check_sql = f"SELECT id FROM pg_thoughts WHERE skill = 'architecture' AND thought->>'title' = '{safe_title}'"
        res = run_sql(check_sql)
        
        if res and res.strip().isdigit():
            tid = int(res.strip())
            update_sql = f"UPDATE pg_thoughts SET thought = '{thought_json}'::jsonb WHERE id = {tid}"
            run_sql(update_sql)
            title_to_id[title] = tid
        else:
            insert_sql = f"INSERT INTO pg_thoughts (agent, skill, thought, project_id) VALUES ('Gemini', 'architecture', '{thought_json}'::jsonb, 'vibe-coding') RETURNING id"
            res = run_sql(insert_sql)
            if res and res.strip().isdigit():
                title_to_id[title] = int(res.strip())

    print(f"🔗 {len(relations)}개의 관계망(Edge) 설정 중...")
    for rel in relations:
        src = rel['source']
        target = rel['target']
        
        src_id = None
        target_id = None
        
        # 정확한 매칭 시도
        for title, tid in title_to_id.items():
            if src == title: src_id = tid
            if target == title: target_id = tid
            
        if src_id and target_id:
            # target의 parent를 source로 설정
            link_sql = f"UPDATE pg_thoughts SET parent_id = {src_id} WHERE id = {target_id}"
            run_sql(link_sql)
            print(f"  ✅ [{src}] (ID:{src_id}) -> [{target}] (ID:{target_id}) 연결 완료")
        else:
            print(f"  ⚠️ 연결 실패: [{src}]({src_id}) -> [{target}]({target_id})")

    print("\n✨ 하이브 지능 동기화 완료.")

if __name__ == "__main__":
    sync()
