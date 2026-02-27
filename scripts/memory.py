"""
에이전트 간 공유 메모리 헬퍼 스크립트 (SQLite 백엔드)
------------------------------------------------------
사용법:
  python scripts/memory.py set   <key> <content> [--title <제목>] [--tags <태그1,태그2>] [--by <작성자>]
  python scripts/memory.py get   <key>
  python scripts/memory.py list  [--q <검색어>]
  python scripts/memory.py delete <key>

예시:
  python scripts/memory.py set db_schema "users(id,name,email), posts(id,user_id,title,body)" --tags db,schema --by claude
  python scripts/memory.py set auth_method "JWT Bearer 토큰 사용. 헤더: Authorization: Bearer <token>" --by gemini
  python scripts/memory.py get db_schema
  python scripts/memory.py list --q schema
  python scripts/memory.py delete old_key

서버가 꺼져 있으면 SQLite 파일에 직접 읽기/쓰기합니다.
"""

import sys
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
import os
import time
import sqlite3
import os

# Windows 터미널(CP949 등)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 벡터 메모리 모듈 선택적 임포트 (없으면 SQLite 폴백 사용)
try:
    from vector_memory import VectorMemory
    VECTOR_AVAILABLE = True
except ImportError:
    VECTOR_AVAILABLE = False

DEFAULT_PORTS = [8005, 8000]


# ─── API 헬퍼 ────────────────────────────────────────────────────────────────

def api_get(path: str, port: int):
    try:
        with urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=3) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def api_post(path: str, body: dict, port: int):
    try:
        payload = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(
            f'http://localhost:{port}{path}',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def find_port():
    for p in DEFAULT_PORTS:
        if api_get('/api/memory', p) is not None:
            return p
    return None


# ─── SQLite 직접 접근 (폴백) ─────────────────────────────────────────────────

def _db_path() -> str:
    # PyInstaller 배포 버전(frozen) 체크
    if getattr(sys, 'frozen', False):
        if os.name == 'nt':
            data_dir = os.path.join(os.getenv('APPDATA'), "VibeCoding")
        else:
            data_dir = os.path.join(os.path.expanduser("~"), ".vibe-coding")
        return os.path.join(data_dir, "shared_memory.db")
    
    # 개발 모드
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    return os.path.join(project_root, '.ai_monitor', 'data', 'shared_memory.db')


def _open_db() -> sqlite3.Connection:
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY, id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]', author TEXT NOT NULL DEFAULT 'unknown',
            timestamp TEXT NOT NULL, updated_at TEXT NOT NULL,
            embedding BLOB, project TEXT NOT NULL DEFAULT ''
        )
    ''')
    conn.commit()
    return conn


# ─── 명령어 구현 ─────────────────────────────────────────────────────────────

def cmd_set(args: argparse.Namespace, port) -> None:
    body = {
        'key':     args.key,
        'content': args.content,
        'title':   getattr(args, 'title', '') or args.key,
        'tags':    [t.strip() for t in (getattr(args, 'tags', '') or '').split(',') if t.strip()],
        'author':  getattr(args, 'by', 'agent') or 'agent',
    }
    
    # ─── Vector DB 저장 (신규) ───
    if VECTOR_AVAILABLE:
        try:
            vm = VectorMemory()
            vm.add_memory(body['key'], body['content'], body)
            print(f"[VECTOR] 시맨틱 임베딩 저장 완료: [{args.key}]")
        except Exception as e:
            print(f"[VECTOR-WARN] 벡터 저장 실패: {e}")

    if port:
        result = api_post('/api/memory/set', body, port)
        if result and result.get('status') == 'success':
            print(f"[OK] 메모리 저장: [{args.key}] by {body['author']}")
            return

    # 폴백: SQLite 직접 쓰기
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    
    # 프로젝트 ID 생성 (server.py와 동일 로직)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    project_id = project_root.replace('\\', '/').replace(':', '').replace('/', '--').lstrip('-') or 'default'

    with _open_db() as conn:
        existing = conn.execute('SELECT timestamp FROM memory WHERE key=?', (args.key,)).fetchone()
        ts = existing['timestamp'] if existing else now
        conn.execute(
            'INSERT OR REPLACE INTO memory (key,id,title,content,tags,author,timestamp,updated_at,project) VALUES (?,?,?,?,?,?,?,?,?)',
            (args.key, str(int(time.time() * 1000)), body['title'], body['content'],
             json.dumps(body['tags'], ensure_ascii=False), body['author'], ts, now, project_id)
        )
    print(f"[OK] 메모리 직접 저장: [{args.key}] (Project: {project_id})")


def cmd_get(args: argparse.Namespace, port) -> None:
    if port:
        entries = api_get(f'/api/memory?q={urllib.parse.quote(args.key)}', port)
        if entries:
            for e in entries:
                if e['key'] == args.key:
                    _print_entry(e)
                    return
    # 폴백
    with _open_db() as conn:
        row = conn.execute('SELECT * FROM memory WHERE key=?', (args.key,)).fetchone()
    if row:
        entry = dict(row)
        entry['tags'] = json.loads(entry.get('tags', '[]'))
        _print_entry(entry)
    else:
        print(f"[없음] key='{args.key}' 를 찾을 수 없습니다.")


def cmd_list(args: argparse.Namespace, port) -> None:
    q = getattr(args, 'q', '') or ''
    if port:
        url = f'/api/memory?q={urllib.parse.quote(q)}' if q else '/api/memory'
        entries = api_get(url, port)
    else:
        with _open_db() as conn:
            if q:
                p = f'%{q}%'
                rows = conn.execute(
                    'SELECT * FROM memory WHERE key LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY updated_at DESC',
                    (p, p, p)
                ).fetchall()
            else:
                rows = conn.execute('SELECT * FROM memory ORDER BY updated_at DESC').fetchall()
        entries = []
        for row in rows:
            e = dict(row)
            e['tags'] = json.loads(e.get('tags', '[]'))
            entries.append(e)

    if not entries:
        print("저장된 메모리 없음")
        return
    for e in entries:
        tags_str = ' '.join(f'#{t}' for t in e.get('tags', []))
        print(f"🧠 [{e['key']}]  by {e['author']}  {tags_str}")
        preview = e['content'][:80].replace('\n', ' ')
        print(f"   {preview}{'...' if len(e['content']) > 80 else ''}")
        print(f"   🕐 {e['updated_at']}")


def cmd_delete(args: argparse.Namespace, port) -> None:
    if port:
        result = api_post('/api/memory/delete', {'key': args.key}, port)
        if result and result.get('status') == 'success':
            print(f"[OK] 메모리 삭제: [{args.key}]")
            return
    with _open_db() as conn:
        conn.execute('DELETE FROM memory WHERE key=?', (args.key,))
    print(f"[OK] 메모리 직접 삭제: [{args.key}]")


def _print_entry(e: dict) -> None:
    print(f"🧠 키:     {e['key']}")
    print(f"   제목:   {e.get('title', '')}")
    print(f"   작성자: {e.get('author', '')}  |  수정: {e.get('updated_at', '')}")
    print(f"   태그:   {' '.join('#'+t for t in e.get('tags', []))}")
    print(f"   내용:\n{e['content']}")


# ─── 역방향 동기화: shared_memory.db → MEMORY.md ─────────────────────────────

def _claude_memory_file():
    """
    현재 프로젝트의 Claude Code auto-memory MEMORY.md 경로 계산.
    Claude Code 프로젝트 인코딩: D:\\vibe-coding → D--vibe-coding
    """
    from pathlib import Path
    script_dir = Path(os.path.abspath(__file__)).parent
    project_root = script_dir.parent
    # 드라이브 + 경로 구분자를 '--' 로 변환 (Claude Code 동일 방식)
    project_id = (
        str(project_root)
        .replace('\\', '/')
        .replace(':', '')
        .replace('/', '--')
        .lstrip('-')
    )
    return Path.home() / '.claude' / 'projects' / project_id / 'memory' / 'MEMORY.md'


def _write_hive_section(memory_file, entries: list) -> None:
    """
    MEMORY.md 내 '## 하이브 공유 메모리' 섹션을 entries 로 교체/추가한다.
    기존 섹션이 있으면 덮어쓰고, 없으면 파일 끝에 추가한다.
    """
    HEADER = '## 하이브 공유 메모리 (자동 동기화)'
    lines = [
        HEADER,
        f'_업데이트: {time.strftime("%Y-%m-%d %H:%M:%S")} | {len(entries)}개 항목_\n',
    ]
    for e in entries[:15]:
        tags_str = ' '.join(f'#{t}' for t in e.get('tags', []))
        preview = e['content'][:90].replace('\n', ' ')
        if len(e['content']) > 90:
            preview += '...'
        lines.append(f"- **[{e['key']}]** `{e.get('author', '?')}` {tags_str}")
        lines.append(f"  {preview}")

    new_section = '\n'.join(lines) + '\n'
    content = memory_file.read_text(encoding='utf-8', errors='replace')

    if HEADER in content:
        # 기존 섹션을 찾아 교체
        start = content.index(HEADER)
        nxt = content.find('\n## ', start + len(HEADER))
        if nxt == -1:
            content = content[:start].rstrip() + '\n\n' + new_section
        else:
            content = content[:start].rstrip() + '\n\n' + new_section + '\n' + content[nxt + 1:]
    else:
        content = content.rstrip() + '\n\n' + new_section

    memory_file.write_text(content, encoding='utf-8')


def cmd_sync(args: argparse.Namespace, port) -> None:
    """
    shared_memory.db → MEMORY.md 역방향 동기화.
    Claude Code 자신의 메모리 파일에서 온 항목(claude:T*)은 제외하고,
    Gemini·사용자·외부 에이전트 항목만 MEMORY.md 하이브 섹션에 기록한다.
    """
    # 1) 공유 메모리 읽기
    entries = []
    if port:
        data = api_get('/api/memory', port)
        if data:
            # claude:T* 키는 Claude Code 메모리 파일이 DB로 들어온 것 — 역동기화 불필요
            entries = [e for e in data if not e.get('key', '').startswith('claude:T')]

    if not entries:
        # 폴백: SQLite 직접 읽기
        with _open_db() as conn:
            rows = conn.execute(
                "SELECT key,title,content,author,tags,updated_at "
                "FROM memory "
                "WHERE key NOT LIKE 'claude:T%' "
                "ORDER BY updated_at DESC LIMIT 20"
            ).fetchall()
        for row in rows:
            e = dict(row)
            e['tags'] = json.loads(e.get('tags', '[]'))
            entries.append(e)

    memory_file = _claude_memory_file()
    if not memory_file.exists():
        print(f"[WARN] MEMORY.md 없음: {memory_file}")
        return

    if not entries:
        print("[INFO] 동기화할 외부 에이전트 항목 없음")
        return

    _write_hive_section(memory_file, entries)
    print(f"[OK] MEMORY.md 하이브 섹션 동기화 — {min(len(entries), 15)}개 항목 반영")


# ─── 진입점 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='공유 메모리 CLI 헬퍼 (SQLite)')
    sub = parser.add_subparsers(dest='command')

    p_set = sub.add_parser('set', help='메모리 저장/갱신')
    p_set.add_argument('key', help='식별 키 (예: db_schema)')
    p_set.add_argument('content', help='저장할 내용')
    p_set.add_argument('--title', default='', help='사람이 읽기 쉬운 제목')
    p_set.add_argument('--tags', default='', help='쉼표로 구분한 태그')
    p_set.add_argument('--by', default='agent', help='작성자 (claude/gemini/user/agent)')

    p_get = sub.add_parser('get', help='특정 키 조회')
    p_get.add_argument('key')

    p_list = sub.add_parser('list', help='전체 목록 / 검색')
    p_list.add_argument('--q', default='', help='검색어')

    p_del = sub.add_parser('delete', help='항목 삭제')
    p_del.add_argument('key')

    sub.add_parser('sync', help='shared_memory.db → MEMORY.md 역방향 동기화')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    port = find_port()
    if not port:
        print("[INFO] 서버 미실행 — SQLite 직접 접근 모드")

    if args.command == 'set':
        cmd_set(args, port)
    elif args.command == 'get':
        cmd_get(args, port)
    elif args.command == 'list':
        cmd_list(args, port)
    elif args.command == 'delete':
        cmd_delete(args, port)
    elif args.command == 'sync':
        cmd_sync(args, port)


if __name__ == '__main__':
    main()
