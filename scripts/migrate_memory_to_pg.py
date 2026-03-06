"""
FILE: scripts/migrate_memory_to_pg.py
DESCRIPTION: 기존 SQLite 데이터를 PostgreSQL 18로 안전하게 이관 (임시 SQL 파일 방식).

REVISION HISTORY:
- 2026-03-06 Gemini: 이스케이프 및 인코딩 문제 해결을 위해 임시 파일 기반 벌크 인서트 방식으로 개선.
"""

import sqlite3
import subprocess
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SQLITE_DB = PROJECT_ROOT / ".ai_monitor" / "data" / "shared_memory.db"
PSQL_EXE = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
TEMP_SQL = PROJECT_ROOT / ".ai_monitor" / "data" / "migrate_temp.sql"
PORT = 5433

def migrate():
    if not SQLITE_DB.exists():
        print("❌ SQLite DB 없음")
        return

    print("🔄 데이터 추출 및 SQL 파일 생성 중...")
    
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM memory").fetchall()
    
    sql_commands = [
        "SET client_encoding = 'UTF8';",
        "BEGIN;"
    ]
    
    for row in rows:
        # SQL 이스케이프 (따옴표 처리)
        def esc(val):
            if val is None: return "NULL"
            return "'" + str(val).replace("'", "''") + "'"

        tags = row['tags'] if row['tags'] else '[]'
        
        cmd = f"""
        INSERT INTO hive_memory (key, title, content, tags, author, project, updated_at)
        VALUES ({esc(row['key'])}, {esc(row['title'])}, {esc(row['content'])}, {esc(tags)}::jsonb, {esc(row['author'])}, {esc(row['project'])}, {esc(row['updated_at'])})
        ON CONFLICT (key) DO UPDATE SET
            content = EXCLUDED.content,
            updated_at = EXCLUDED.updated_at;
        """
        sql_commands.append(cmd)
    
    sql_commands.append("COMMIT;")
    
    # UTF-8로 SQL 파일 저장
    with open(TEMP_SQL, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_commands))
    
    print(f"🚀 psql -f 를 통한 벌크 이관 시작 (Port: {PORT})...")
    try:
        # psql 실행 시 환경변수로 UTF-8 강제
        env = os.environ.copy()
        env["PGCLIENTENCODING"] = "UTF8"
        
        result = subprocess.run([
            str(PSQL_EXE), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-f", str(TEMP_SQL)
        ], env=env, capture_output=True, text=True, encoding="utf-8")
        
        if result.returncode == 0:
            print(f"✅ 총 {len(rows)}개의 기억 항목 이관 성공!")
        else:
            print(f"❌ 이관 실패: {result.stderr}")
            
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    finally:
        if TEMP_SQL.exists():
            os.remove(TEMP_SQL)
    
    conn.close()

if __name__ == "__main__":
    migrate()
