"""
FILE: api/memory_api.py
DESCRIPTION: /api/memory, /api/memory/set, /api/memory/delete,
             /api/project-info 엔드포인트 핸들러 모듈.
             SQLite 기반의 공유 메모리(shared_memory.db) CRUD 와
             벡터 임베딩 의미 검색 로직을 담당합니다.
             server.py에서 메모리 관련 API를 분리하여 응집도를 높입니다.

REVISION HISTORY:
- 2026-03-01 Claude: server.py에서 분리 — memory/project-info API 핸들러 담당
"""

import json
import time
from pathlib import Path


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, PROJECT_ID: str, PROJECT_ROOT: Path,
               _memory_conn, _embed, _cosine_sim,
               __version__: str) -> bool:
    """GET 요청 처리 — /api/memory, /api/project-info 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/memory ───────────────────────────────────────────────────────
    if path == '/api/memory':
        # 공유 메모리 조회 — 임베딩 의미 검색 우선, 폴백 키워드 LIKE
        # ?q=검색어  ?top=N(기본20)  ?threshold=0.5  ?all=true(전체 프로젝트)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        q         = params.get('q',         [''])[0].strip()
        top_k     = int(params.get('top',   ['20'])[0])
        threshold = float(params.get('threshold', ['0.45'])[0])
        show_all  = params.get('all', ['false'])[0].lower() == 'true'
        # 프로젝트 필터: all=true가 아니면 현재 프로젝트만 표시
        proj_filter = '' if show_all else PROJECT_ID
        try:
            with _memory_conn() as conn:
                if q:
                    q_emb = _embed(q)
                    if q_emb:
                        # ── 임베딩 의미 검색 ──────────────────────────────
                        if proj_filter:
                            all_rows = conn.execute(
                                'SELECT * FROM memory WHERE project=? ORDER BY updated_at DESC',
                                (proj_filter,)
                            ).fetchall()
                        else:
                            all_rows = conn.execute(
                                'SELECT * FROM memory ORDER BY updated_at DESC'
                            ).fetchall()
                        scored = []
                        for row in all_rows:
                            r_emb = row['embedding']
                            if r_emb:
                                score = _cosine_sim(q_emb, r_emb)
                                if score >= threshold:
                                    scored.append((dict(row), score))
                            else:
                                # 임베딩 없는 항목은 키워드 폴백
                                if any(q.lower() in str(row[f]).lower()
                                       for f in ('key', 'title', 'content', 'tags')):
                                    scored.append((dict(row), 0.0))
                        scored.sort(key=lambda x: -x[1])
                        rows_data = [r for r, _ in scored[:top_k]]
                        # 유사도 점수를 결과에 포함
                        for (r, s), rd in zip(scored[:top_k], rows_data):
                            rd['_score'] = round(s, 4)
                    else:
                        # 임베딩 모델 미로드 → 키워드 폴백
                        pattern = f'%{q}%'
                        if proj_filter:
                            rows_raw = conn.execute(
                                'SELECT * FROM memory WHERE project=? AND '
                                '(key LIKE ? OR title LIKE ? OR content LIKE ? OR tags LIKE ?) '
                                'ORDER BY updated_at DESC LIMIT ?',
                                (proj_filter, pattern, pattern, pattern, pattern, top_k)
                            ).fetchall()
                        else:
                            rows_raw = conn.execute(
                                'SELECT * FROM memory WHERE key LIKE ? OR title LIKE ? '
                                'OR content LIKE ? OR tags LIKE ? ORDER BY updated_at DESC LIMIT ?',
                                (pattern, pattern, pattern, pattern, top_k)
                            ).fetchall()
                        rows_data = [dict(r) for r in rows_raw]
                else:
                    if proj_filter:
                        rows_raw = conn.execute(
                            'SELECT * FROM memory WHERE project=? ORDER BY updated_at DESC LIMIT ?',
                            (proj_filter, top_k)
                        ).fetchall()
                    else:
                        rows_raw = conn.execute(
                            'SELECT * FROM memory ORDER BY updated_at DESC LIMIT ?', (top_k,)
                        ).fetchall()
                    rows_data = [dict(r) for r in rows_raw]

            entries = []
            for entry in rows_data:
                entry['tags'] = json.loads(entry.get('tags', '[]'))
                entry.pop('embedding', None)  # bytes는 JSON 직렬화 불가 — 제거
                entries.append(entry)
            handler.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/project-info ────────────────────────────────────────────────
    elif path == '/api/project-info':
        # 현재 서버가 서비스하는 프로젝트 정보 반환
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        handler.wfile.write(json.dumps({
            'project_id':   PROJECT_ID,
            'project_name': PROJECT_ROOT.name,
            'project_root': str(PROJECT_ROOT).replace('\\', '/'),
            'version':      __version__,
        }, ensure_ascii=False).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, PROJECT_ID: str,
                _memory_conn, _embed) -> bool:
    """POST 요청 처리 — /api/memory/set, /api/memory/delete 담당.

    반환값: 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/memory/set ───────────────────────────────────────────────────
    if path == '/api/memory/set':
        # 공유 메모리 항목 저장/갱신 — key 기준 UPSERT (SQLite INSERT OR REPLACE)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            key     = str(data.get('key', '')).strip()[:200]
            content = str(data.get('content', '')).strip()
            if not key or not content:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key와 content는 필수입니다'}
                ).encode('utf-8'))
                return True

            now     = time.strftime('%Y-%m-%dT%H:%M:%S')
            title   = str(data.get('title', key)).strip()[:300]
            project = str(data.get('project', PROJECT_ID)).strip() or PROJECT_ID
            entry = {
                'key':        key,
                'id':         str(int(time.time() * 1000)),
                'title':      title,
                'content':    content,
                'tags':       json.dumps(data.get('tags', []), ensure_ascii=False),
                'author':     str(data.get('author', 'unknown')),
                'timestamp':  now,
                'updated_at': now,
                'project':    project,
            }

            # 임베딩 생성 — 동기 처리 (보통 0.05초 이내, 의미 검색 품질 향상)
            emb = _embed(f"{title}\n{content}")

            with _memory_conn() as conn:
                # 기존 항목이면 timestamp(최초 생성 시각)는 유지, updated_at만 갱신
                existing = conn.execute('SELECT timestamp FROM memory WHERE key=?', (key,)).fetchone()
                if existing:
                    entry['timestamp'] = existing['timestamp']
                conn.execute(
                    'INSERT OR REPLACE INTO memory '
                    '(key,id,title,content,tags,author,timestamp,updated_at,project,embedding) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (entry['key'], entry['id'], entry['title'], entry['content'],
                     entry['tags'], entry['author'], entry['timestamp'], entry['updated_at'],
                     entry['project'], emb)
                )

            entry['tags'] = json.loads(entry['tags'])
            handler.wfile.write(json.dumps(
                {'status': 'success', 'entry': entry}, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/memory/delete ────────────────────────────────────────────────
    elif path == '/api/memory/delete':
        # 공유 메모리 항목 삭제 (key 기준)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()
            with _memory_conn() as conn:
                conn.execute('DELETE FROM memory WHERE key=?', (key,))
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
