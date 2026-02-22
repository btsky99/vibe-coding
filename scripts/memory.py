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
import os
import time
import sqlite3

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
            timestamp TEXT NOT NULL, updated_at TEXT NOT NULL
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
    if port:
        result = api_post('/api/memory/set', body, port)
        if result and result.get('status') == 'success':
            print(f"[OK] 메모리 저장: [{args.key}] by {body['author']}")
            return

    # 폴백: SQLite 직접 쓰기
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    with _open_db() as conn:
        existing = conn.execute('SELECT timestamp FROM memory WHERE key=?', (args.key,)).fetchone()
        ts = existing['timestamp'] if existing else now
        conn.execute(
            'INSERT OR REPLACE INTO memory (key,id,title,content,tags,author,timestamp,updated_at) VALUES (?,?,?,?,?,?,?,?)',
            (args.key, str(int(time.time() * 1000)), body['title'], body['content'],
             json.dumps(body['tags'], ensure_ascii=False), body['author'], ts, now)
        )
    print(f"[OK] 메모리 직접 저장: [{args.key}]")


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


# ─── 진입점 ──────────────────────────────────────────────────────────────────

def main():
    import urllib.parse  # cmd_get에서 사용

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
        import urllib.parse
        cmd_get(args, port)
    elif args.command == 'list':
        cmd_list(args, port)
    elif args.command == 'delete':
        cmd_delete(args, port)


if __name__ == '__main__':
    main()
