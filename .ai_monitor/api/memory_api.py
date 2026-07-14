"""
FILE: api/memory_api.py
DESCRIPTION: Postgres-first memory API handlers. recall-smart(임베딩 통합 회상) 포함.

REVISION HISTORY:
- 2026-06-10 Claude: POST /api/memory/recall-smart 추가 — 자가 치유 2.0 ④ (Task 4)
- 2026-07-06 Claude: GET /api/memory/db-info 분리(Phase 2 R8). query_rows/PG_PORT/PG_PROJECT_DB는
  server.py 전역이라 wrapper가 호출 시점 주입(포트/DB 폴백 반영). handle_get 오버로드 대신 전용 함수.
"""

import json
import time
from pathlib import Path

from src.pg_store import (
    ensure_schema,
    list_memory,
    set_memory,
    delete_memory,
    migrate_legacy_data,
    promote_to_zettel,
    insert_pg_log,
)


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, PROJECT_ID: str, PROJECT_ROOT: Path,
               __version__: str) -> bool:
    if path == '/api/memory':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        q = params.get('q', [''])[0].strip()
        top_k = int(params.get('top', ['20'])[0])
        show_all = params.get('all', ['false'])[0].lower() == 'true'
        author = params.get('author', [''])[0].strip()
        include_zettel = params.get('include_zettel', ['false'])[0].lower() == 'true'
        project_id = '' if show_all else PROJECT_ID
        try:
            ensure_schema(DATA_DIR)
            entries = list_memory(
                q=q, top_k=top_k, project_id=project_id, show_all=show_all,
                author=author, include_zettel=include_zettel,
            )
            handler.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    if path == '/api/project-info':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({
            'project_id': PROJECT_ID,
            'project_name': PROJECT_ROOT.name,
            'project_root': str(PROJECT_ROOT).replace('\\', '/'),
            'version': __version__,
        }, ensure_ascii=False).encode('utf-8'))
        return True

    return False


def db_info(handler, DATA_DIR: Path, PG_PORT, PG_PROJECT_DB, query_rows) -> None:
    """GET /api/memory/db-info — 공유 메모리 DB 경로 + hive_memory 항목 수 반환.
    [WHY] 배포/개발 버전이 어떤 DB를 바라보는지 UI에서 확인(슬러그 불일치 빈 패널 진단용).
    [불변식] query_rows/PG_PORT/PG_PROJECT_DB는 server.py 전역 — 동적 포트/DB 폴백 후 최신값을
      봐야 하므로 wrapper가 호출 시점에 주입한다(디폴트 인자 바인딩 금지).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        ensure_schema(DATA_DIR)
        rows = query_rows("SELECT COUNT(*) AS count FROM hive_memory;")
        count = int(rows[0].get('count', 0)) if rows else 0
        handler.wfile.write(json.dumps({
            'db_path': f'postgres://localhost:{PG_PORT}/{PG_PROJECT_DB}',
            'is_local': False,
            'backend': 'postgres',
            'count': count,
        }, ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({'error': str(e), 'count': 0}).encode('utf-8'))


def _format_recall_summary(query: str, items: list[dict]) -> str:
    """회상 결과 → 에이전트 컨텍스트 주입용 텍스트. 빈 결과면 빈 문자열(주입 생략).

    [WHY] 0.45 임계를 넘은 것만 도착하므로 '관련 없음' 표시가 따로 없다 —
    빈 문자열이 곧 '주입할 가치 없음' 신호 (기존 노이즈 주입 문제의 해결점).
    """
    if not items:
        return ''
    icons = {'zettel': '🧠', 'memory': '💾', 'experience': '🏃'}
    lines = [f"[회상 v2] '{query[:50]}' 관련 지식 {len(items)}건 (유사도 0.45+):"]
    for it in items:
        icon = icons.get(it.get('kind', ''), '•')
        sim = float(it.get('sim') or 0)
        if it.get('kind') == 'experience':
            head = f"[{it.get('task_type', '?')}/{it.get('outcome', '?')}] {it.get('description', '')}"
        else:
            head = f"{it.get('title', '')} — {str(it.get('content', '')).replace(chr(10), ' ')}"
        lines.append(f"  {icon} [{sim:.2f}] {head[:120]}")
    return '\n'.join(lines)


def _recall_fallback_summary(query: str, limit: int) -> str:
    """회상 v1(ILIKE) 폴백 — vector 비활성/모델 미로드 시에도 회상은 계속된다."""
    parts = []
    try:
        from src.pg_store import recall_context_summary, recall_knowledge_summary
        s1 = recall_context_summary(query, limit=min(limit, 3))
        if s1:
            parts.append(s1)
        s2 = recall_knowledge_summary(query, limit=min(limit, 3))
        if s2:
            parts.append(s2)
    except Exception:
        pass
    return '\n'.join(parts)


def _log_recall_event(status: str, items: int, project_id: str, reason: str = '') -> None:
    """[계측 #1] recall-smart 결과를 pg_logs에 기록 — 회상 실발화율/적중률 산출용.

    status='hit'(warm 벡터 회상이 실제 발화) / 'fallback'(미warm·임베딩 실패·오류로 폴백).
    [WHY] 회상 '메커니즘 정상'과 '실제 발화'는 다르다 — 서버 모델이 미warm이면 항상 fallback이라
      실효 0인데도 '작동 중'처럼 보인다([[lessons.md]] 2026-07-14, [[project_heal_metrics]]).
      heal_metrics가 이 로그로 최근 실발화율(hit/total)과 적중률(items>0)을 계측한다.
    [불변식] 훅 지연 금지 — 응답 전송 '후' 호출 + try/except로 어떤 실패도 삼킨다.
    """
    try:
        insert_pg_log(agent='recall', status=status,
                      task=f"items={items} {reason}".strip(),
                      project_id=project_id,
                      metadata={'items': items, 'reason': reason})
    except Exception:
        pass


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, PROJECT_ID: str) -> bool:
    if path == '/api/memory/set':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()[:200]
            content = str(data.get('content', '')).strip()
            if not key or not content:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key and content are required'}
                ).encode('utf-8'))
                return True

            now = time.strftime('%Y-%m-%dT%H:%M:%S')
            title = str(data.get('title', key)).strip()[:300]
            project_id = str(data.get('project_id', PROJECT_ID)).strip() or PROJECT_ID
            tags = data.get('tags', [])
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]

            ensure_schema(DATA_DIR)
            # author 미지정 시 None 전달 — pg_store._resolve_author()가 env 우선 처리
            author_raw = data.get('author')
            saved = set_memory(
                key=key,
                content=content,
                title=title,
                tags=tags if isinstance(tags, list) else [],
                author=str(author_raw) if author_raw else None,
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            handler.wfile.write(json.dumps(
                {'status': 'success', 'entry': saved or {}}, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/delete':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            delete_memory(str(data.get('key', '')).strip())
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/promote':
        # C.3 — hive_memory 항목을 zettel_notes로 승격. 원본은 유지.
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()
            note_type = str(data.get('note_type', '')).strip()
            if not key:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key is required'}
                ).encode('utf-8'))
                return True
            ensure_schema(DATA_DIR)
            note = promote_to_zettel(key, note_type=note_type)
            if not note:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': f'not found: {key}'},
                    ensure_ascii=False,
                ).encode('utf-8'))
                return True
            handler.wfile.write(json.dumps(
                {'status': 'success', 'note': {
                    'id': note.get('id'),
                    'note_type': note.get('note_type'),
                    'title': note.get('title'),
                }, 'message': f'"{key}" 승격 완료 (zettel {note.get("id")})'},
                ensure_ascii=False,
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/share':
        # 크로스 프로젝트 지식 공유 — 현재 프로젝트 메모리를 글로벌로 승격
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()
            if not key:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key is required'}
                ).encode('utf-8'))
                return True

            from src.pg_store import get_memory
            ensure_schema(DATA_DIR)
            entry = get_memory(key)
            if not entry:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'Memory entry not found'}
                ).encode('utf-8'))
                return True

            # project_id를 __global__로 변경하여 모든 프로젝트에서 접근 가능하게 함
            saved = set_memory(
                key=key,
                content=entry.get('content', ''),
                title=entry.get('title', key),
                tags=entry.get('tags', []),
                author=entry.get('author', 'unknown'),
                project_id='__global__',
                updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
            )
            handler.wfile.write(json.dumps(
                {'status': 'success', 'entry': saved or {}, 'message': f'"{key}" 글로벌 공유 완료'},
                ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/recall-smart':
        # ── [자가 치유 2.0 ④] 임베딩 기반 통합 회상 ─────────────────────────
        # [WHY] 훅(단명 프로세스)은 모델을 못 들고 있으므로 warm 모델을 가진
        # 서버가 회상을 대행한다. 호출자: src/recall_client.py (hive_hook 경유).
        # [불변식] 어떤 실패에서도 200 + fallback 응답 — 훅 지연/중단 금지.
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            query = str(data.get('query', '')).strip()
            limit = max(1, min(int(data.get('limit', 5) or 5), 20))
            if not query:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'query is required'}
                ).encode('utf-8'))
                return True

            ensure_schema(DATA_DIR)
            from infra.embed_service import is_loaded, embed_floats, warm_async
            from src.pg_vector_search import (
                vector_available, vector_search, bump_reference,
            )

            # [제약] is_loaded 가드 — 모델 미로드 상태에서 embed_floats를 부르면
            # 첫 로드(다운로드 포함)가 핸들러를 수십 초 블로킹. 로드 전엔 v1 폴백.
            # [닭-달걀 해소] 미로드면 백그라운드 워밍을 트리거 — 이번 요청은 폴백이지만
            #   다음 요청부터 벡터 회상 활성. 백필 데몬이 죽은/미기동 환경 자가 회복
            #   (계측 project_heal_metrics로 발견: recall 경로가 모델을 영영 안 올림).
            if not (vector_available() and is_loaded()):
                if vector_available():
                    warm_async()
                handler.wfile.write(json.dumps(
                    {'status': 'success', 'fallback': True, 'items': [],
                     'summary': _recall_fallback_summary(query, limit)},
                    ensure_ascii=False,
                ).encode('utf-8'))
                _log_recall_event('fallback', 0, PROJECT_ID,
                                  'not_warm' if vector_available() else 'no_vector')
                return True

            vec = embed_floats(query)
            if not vec:
                handler.wfile.write(json.dumps(
                    {'status': 'success', 'fallback': True, 'items': [],
                     'summary': _recall_fallback_summary(query, limit)},
                    ensure_ascii=False,
                ).encode('utf-8'))
                _log_recall_event('fallback', 0, PROJECT_ID, 'embed_fail')
                return True

            # 3개 지식원 통합 검색 → 점수순 병합. 임계 0.45는 vector_search 기본값.
            kind_tables = [
                ('zettel', 'zettel_notes'),
                ('memory', 'hive_memory'),
                ('experience', 'agent_experience'),
            ]
            merged = []
            for kind, table in kind_tables:
                for row in vector_search(table, vec, project_id=PROJECT_ID, limit=limit):
                    row['kind'] = kind
                    row['sim'] = float(row.get('sim') or 0)
                    row['score'] = float(row.get('score') or 0)
                    merged.append(row)
            merged.sort(key=lambda r: r['score'], reverse=True)
            merged = merged[:limit]

            # 참조 피드백 — 반환된 항목만 카운트 증가 (회상→사용 가정)
            for kind, table in kind_tables:
                pks = [r.get('id') or r.get('key') for r in merged if r['kind'] == kind]
                pks = [p for p in pks if p]
                if pks:
                    bump_reference(table, pks)

            handler.wfile.write(json.dumps(
                {'status': 'success', 'fallback': False, 'items': merged,
                 'summary': _format_recall_summary(query, merged)},
                ensure_ascii=False, default=str,
            ).encode('utf-8'))
            _log_recall_event('hit', len(merged), PROJECT_ID)
        except Exception as e:
            # 실패도 폴백 신호로 — 훅이 v1 경로로 즉시 전환
            handler.wfile.write(json.dumps(
                {'status': 'success', 'fallback': True, 'items': [],
                 'summary': '', 'message': str(e)},
            ).encode('utf-8'))
            _log_recall_event('fallback', 0, PROJECT_ID, 'error')
        return True

    if path == '/api/memory/sync':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            migrate_legacy_data(DATA_DIR)
            handler.wfile.write(json.dumps(
                {'status': 'ok', 'message': 'legacy memory migrated to PostgreSQL', 'merged': 0, 'skipped': 0},
                ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
