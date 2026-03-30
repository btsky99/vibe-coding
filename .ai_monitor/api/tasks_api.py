"""
FILE: api/tasks_api.py
DESCRIPTION: /api/tasks/* 및 /api/task-logs 엔드포인트 핸들러 모듈.
             공유 작업 큐 전체 목록, 칸반 보드, 태스크 로그 조회(GET),
             새 작업 생성, 상태 업데이트, 삭제, Claim(POST) 기능을 제공합니다.
             Paperclip 스타일 코멘트/체크아웃/에이전트 상태 API 포함.
             server.py에서 분리하여 태스크 관련 로직을 단일 파일로 관리합니다.

REVISION HISTORY:
- 2026-03-30 Claude: 하트비트/체크아웃/코멘트 엔드포인트 추가 (Paperclip 전환)
- 2026-03-22 Claude: server.py에서 분리 — tasks API 핸들러 담당
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs


def handle_get(handler, path: str, params: dict, *,
               DATA_DIR: Path, list_tasks, current_project_id: str,
               list_task_comments=None, list_agent_status=None) -> bool:
    """GET 요청 처리 — /api/tasks, /api/tasks/kanban, /api/task-logs 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/tasks ─────────────────────────────────────────────────────
    # 공유 작업 큐 전체 목록 반환 — 현재 프로젝트 태스크만
    if path == '/api/tasks':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            tasks = list_tasks(project_id=current_project_id)
        except Exception as e:
            print(f"[PG ERROR] /api/tasks list_tasks: {e}")
            tasks = []
        handler.wfile.write(json.dumps(tasks, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/tasks/kanban ──────────────────────────────────────────────
    # 칸반 보드 데이터 — 태스크를 5컬럼으로 그룹화하여 반환
    # kanban_status 필드 우선, 없으면 status에서 매핑 (pending→todo 하위 호환)
    elif path == '/api/tasks/kanban':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            tasks = list_tasks(project_id=current_project_id)
        except Exception as e:
            print(f"[PG ERROR] /api/tasks/kanban list_tasks: {e}")
            tasks = []
        columns: dict = {'todo': [], 'claimed': [], 'in_progress': [], 'review': [], 'done': []}
        for t in tasks:
            # kanban_status 우선 적용, 없으면 status 필드에서 변환
            st = t.get('kanban_status') or t.get('status', 'todo')
            if st == 'pending':
                st = 'todo'
            if st in columns:
                columns[st].append(t)
            else:
                columns['todo'].append(t)
        total = len(tasks)
        done_cnt = len(columns['done'])
        active = total - done_cnt
        rate = round(done_cnt / total * 100) if total > 0 else 0
        result = {**columns, 'stats': {'total': total, 'active': active, 'done': done_cnt, 'rate': rate}}
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/task-logs ─────────────────────────────────────────────────
    # task_logs.jsonl에서 최근 로그 반환 — 모니터링 뷰 직접 폴링용
    # ?agent=claude  ?terminal_id=T1  ?limit=20
    # SSE 스트림과 달리 JSONL 파일을 직접 읽어 즉시 반환합니다.
    elif path == '/api/task-logs':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        qs = params
        _agent_f  = qs.get('agent',       [''])[0].lower()
        _tid_f    = qs.get('terminal_id', [''])[0].upper()
        _limit    = int(qs.get('limit',   ['20'])[0])
        _log_file = DATA_DIR / 'task_logs.jsonl'
        _results: list = []
        if _log_file.exists():
            _lines = _log_file.read_text(encoding='utf-8').strip().splitlines()
            for _ln in reversed(_lines[-500:]):
                try:
                    _entry = json.loads(_ln)
                    # 에이전트 필터 (대소문자 무시)
                    if _agent_f and _entry.get('agent', '').lower() != _agent_f:
                        continue
                    # 터미널 ID 필터 (T1/1 모두 허용)
                    if _tid_f:
                        _raw_tid = _entry.get('terminal_id', '')
                        _norm = f'T{_raw_tid}' if _raw_tid.isdigit() else _raw_tid.upper()
                        if _norm != _tid_f and _raw_tid.upper() != _tid_f:
                            continue
                    _results.append(_entry)
                    if len(_results) >= _limit:
                        break
                except Exception:
                    pass  # JSONL 개별 행 파싱 실패 허용
        # 시간순으로 정렬하여 반환 (최신 순 → 오래된 순)
        handler.wfile.write(json.dumps(_results, ensure_ascii=False).encode('utf-8'))
        return True

    # ── GET /api/tasks/<id>/comments ──────────────────────────────────
    # 태스크 코멘트 조회 — Paperclip 스타일 비동기 통신
    m = re.match(r'^/api/tasks/([^/]+)/comments$', path)
    if m and list_task_comments:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        task_id = m.group(1)
        try:
            comments = list_task_comments(task_id)
        except Exception as e:
            print(f"[PG ERROR] /api/tasks/comments: {e}")
            comments = []
        handler.wfile.write(json.dumps(comments, ensure_ascii=False).encode('utf-8'))
        return True

    # ── GET /api/agents/status ────────────────────────────────────────
    # 전체 에이전트 하트비트 상태 조회
    if path == '/api/agents/status' and list_agent_status:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            agents = list_agent_status()
        except Exception as e:
            print(f"[PG ERROR] /api/agents/status: {e}")
            agents = []
        handler.wfile.write(json.dumps(agents, ensure_ascii=False).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict, *,
                SESSIONS_FILE: Path, save_task, update_task, delete_task,
                current_project_id: str, PROJECT_ID: str,
                add_task_comment=None, atomic_checkout=None,
                release_checkout=None, trigger_agent=None) -> bool:
    """POST 요청 처리 — /api/tasks 생성, /api/tasks/update, delete, claim 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── POST /api/tasks ────────────────────────────────────────────────
    # 새 작업 생성 — hive_tasks 테이블에 추가
    if path == '/api/tasks':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            now = time.strftime('%Y-%m-%dT%H:%M:%S')
            # tags 필드 — 리스트 타입 검증 (문자열이면 쉼표 분리)
            raw_tags = data.get('tags', [])
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
            task = {
                'id': str(int(time.time() * 1000)),
                'timestamp': now,
                'updated_at': now,
                'title': str(data.get('title', '제목 없음')),
                'description': str(data.get('description', '')),
                'status': 'pending',
                'assigned_to': str(data.get('assigned_to', 'all')),
                'priority': str(data.get('priority', 'medium')),
                'created_by': str(data.get('created_by', 'user')),
                # ── 칸반 확장 필드 ──
                'kanban_status': str(data.get('kanban_status', 'todo')),
                'role': str(data.get('role', '')),
                'claimed_by': str(data.get('claimed_by', '')),
                'tags': raw_tags,
            }
            save_task(task, project_id=PROJECT_ID)

            # SSE 로그에도 반영 (태스크 보드 알림)
            try:
                log_entry = {
                    'timestamp': now,
                    'agent': task['created_by'],
                    'terminal_id': 'TASK_BOARD',
                    'project': 'hive',
                    'status': 'success',
                    'trigger': f"[새 작업] {task['title']} → {task['assigned_to']}",
                    'ts_start': now,
                }
                with open(SESSIONS_FILE, 'a', encoding='utf-8') as lf:
                    lf.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            except Exception:
                pass

            handler.wfile.write(json.dumps({'status': 'success', 'task': task}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/tasks/update ─────────────────────────────────────────
    # 기존 작업 상태/담당자 등 업데이트
    elif path == '/api/tasks/update':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            task_id = str(data.get('id', ''))
            updates = {}
            for key in ('status', 'assigned_to', 'priority', 'title',
                        'description', 'kanban_status', 'role', 'claimed_by'):
                if key in data:
                    updates[key] = str(data[key])
            if 'tags' in data:
                raw_tags = data['tags']
                if isinstance(raw_tags, str):
                    raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
                updates['tags'] = list(raw_tags) if isinstance(raw_tags, list) else []
            updates['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            updated_task = update_task(task_id, updates)

            handler.wfile.write(json.dumps({'status': 'success', 'task': updated_task}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/tasks/delete ─────────────────────────────────────────
    # 작업 삭제 (id 기준 필터링)
    elif path == '/api/tasks/delete':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            task_id = str(data.get('id', ''))
            delete_task(task_id)

            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/tasks/claim ──────────────────────────────────────────
    # 터미널이 태스크를 Claim — kanban_status=claimed, claimed_by=terminal_id로 업데이트
    elif path == '/api/tasks/claim':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            task_id = str(data.get('id', ''))
            terminal_id = str(data.get('terminal_id', ''))
            claimed_task = update_task(task_id, {
                'kanban_status': 'claimed',
                'claimed_by': terminal_id,
                'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
            handler.wfile.write(json.dumps({'status': 'success', 'task': claimed_task}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/tasks/<id>/comments ─────────────────────────────────
    # 태스크에 코멘트 추가 — Paperclip 스타일 비동기 통신
    m = re.match(r'^/api/tasks/([^/]+)/comments$', path)
    if m and add_task_comment:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            task_id = m.group(1)
            author = str(data.get('author', 'user'))
            content = str(data.get('content', ''))
            add_task_comment(task_id, author, content)
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/tasks/<id>/checkout ─────────────────────────────────
    # 원자적 태스크 체크아웃
    m = re.match(r'^/api/tasks/([^/]+)/checkout$', path)
    if m and atomic_checkout:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            task_id = m.group(1)
            agent_id = str(data.get('agent_id', ''))
            result = atomic_checkout(agent_id, task_id)
            if result:
                handler.wfile.write(json.dumps({'status': 'success', 'task': result}, ensure_ascii=False).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({'status': 'conflict', 'message': '이미 체크아웃된 태스크입니다'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── POST /api/agents/<id>/trigger ─────────────────────────────────
    # 수동 하트비트 트리거 — NOTIFY로 에이전트 깨우기
    m = re.match(r'^/api/agents/([^/]+)/trigger$', path)
    if m and trigger_agent:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            agent_id = m.group(1)
            ok = trigger_agent(agent_id)
            handler.wfile.write(json.dumps({
                'status': 'success' if ok else 'error',
                'message': f'{agent_id} 트리거 전송' if ok else 'NOTIFY 전송 실패'
            }).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
