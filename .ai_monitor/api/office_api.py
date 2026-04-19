"""
FILE: .ai_monitor/api/office_api.py
DESCRIPTION: 오피스 모드 전용 API — 프로필 중앙화(PostgreSQL SSOT) + 클래식과 네임스페이스 분리.
             모든 오피스 관련 요청(/api/office/*)을 단일 진입점에서 처리한다.

REVISION HISTORY:
- 2026-04-09 Claude: 초기 작성 — 프로필 CRUD + SSE + 에이전트/태스크 네임스페이스 분리
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from src.pg_store import (
    ensure_schema,
    seed_default_office_profile,
    list_office_profiles,
    get_office_profile,
    upsert_office_profile,
    delete_office_profile,
    get_active_office_profile_id,
    set_active_office_profile,
    _get_pg_conn,
    query_rows,
    execute,
    _sql_text,
)


# ── SSE 브로드캐스트 ──────────────────────────────────────────────────────
# 단일 LISTEN 스레드가 'office_profiles_changed' 채널을 구독하고
# 모든 연결된 SSE 클라이언트의 큐에 이벤트를 팬아웃한다.

_SSE_CLIENTS: set[queue.Queue] = set()
_SSE_LOCK = threading.Lock()
_LISTENER_STARTED = False
_LISTENER_LOCK = threading.Lock()


def _start_notify_listener():
    """PostgreSQL LISTEN 스레드 1회 기동. 이미 실행 중이면 무시."""
    global _LISTENER_STARTED
    with _LISTENER_LOCK:
        if _LISTENER_STARTED:
            return
        _LISTENER_STARTED = True

    def _loop():
        try:
            import select
            conn = _get_pg_conn()
            if conn is None:
                print('[office_api] LISTEN: PG 연결 없음 → 리스너 중단')
                return
            # psycopg2 autocommit 모드에서만 LISTEN이 즉시 작동
            try:
                conn.set_isolation_level(0)  # ISOLATION_LEVEL_AUTOCOMMIT
            except Exception as e:
                print(f'[office_api] autocommit 설정 실패: {e}')
            with conn.cursor() as cur:
                cur.execute("LISTEN office_profiles_changed;")
            print('[office_api] LISTEN office_profiles_changed 시작')
            while True:
                try:
                    if select.select([conn], [], [], 30) == ([], [], []):
                        # 타임아웃 — 연결 생존 확인 후 계속
                        continue
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        payload = notify.payload or '{}'
                        _broadcast(payload)
                except Exception as e:
                    print(f'[office_api] LISTEN 루프 예외: {e}')
                    time.sleep(2)
        except Exception as e:
            print(f'[office_api] LISTEN 리스너 초기화 실패: {e}')

    t = threading.Thread(target=_loop, daemon=True, name='office-listen')
    t.start()


def _broadcast(payload: str):
    """연결된 모든 SSE 큐에 이벤트 전파."""
    with _SSE_LOCK:
        dead = []
        for q in _SSE_CLIENTS:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
            except Exception as e:
                print(f'[office_api] SSE 브로드캐스트 실패: {e}')
                dead.append(q)
        for q in dead:
            _SSE_CLIENTS.discard(q)


# ── 공통 응답 유틸 ────────────────────────────────────────────────────────

def _send_json(handler, status: int, body: dict | list):
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(json.dumps(body, ensure_ascii=False).encode('utf-8'))


def _read_json_body(handler) -> dict:
    length = int(handler.headers.get('Content-Length', '0') or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode('utf-8'))
    except Exception as e:
        print(f'[office_api] JSON 파싱 실패: {e}')
        return {}


# ── 초기화 ───────────────────────────────────────────────────────────────

def init_office(DATA_DIR: Path):
    """서버 시작 시 1회 호출. 스키마 보장 + 기본 프로필 시드 + LISTEN 리스너 기동."""
    ensure_schema(DATA_DIR)
    seed_default_office_profile()
    _start_notify_listener()


# ── GET 핸들러 ───────────────────────────────────────────────────────────

_skills_cache: dict | None = None
_skills_cache_ts: float = 0


def _parse_skills() -> list[dict]:
    """Platform Phase 3 스캐너를 경유해 .claude/skills + .vibe/skills 병합 목록 반환.

    응답 포맷은 기존 오피스 채팅 UI와 호환:
    - userInvocable (camelCase)
    - description은 "Use when:" 이전까지만 (간결 표시)
    - 신규: origin ("claude" | "vibe") — UI 배지용

    결과를 5분간 캐시.
    """
    global _skills_cache, _skills_cache_ts
    now = time.time()
    if _skills_cache is not None and now - _skills_cache_ts < 300:
        return _skills_cache

    try:
        from api.vibe_skills_api import scan_project_skills
        project_root = Path(__file__).resolve().parent.parent.parent
        result = scan_project_skills(project_root)
        raw = result.get('skills', [])
    except Exception:
        raw = []

    skills: list[dict] = []
    for s in raw:
        name = str(s.get('name', '')).strip()
        if not name:
            continue
        desc = str(s.get('description', ''))
        use_when_idx = desc.find('Use when:')
        if use_when_idx > 0:
            desc = desc[:use_when_idx].strip()
        skills.append({
            'name': name,
            'description': desc,
            'userInvocable': bool(s.get('user_invocable', True)),
            'origin': s.get('origin', 'claude'),
        })

    _skills_cache = skills
    _skills_cache_ts = now
    return skills


def handle_get(handler, path: str, params: dict, DATA_DIR: Path) -> bool:
    ensure_schema(DATA_DIR)

    # 스킬 목록
    if path == '/api/office/skills':
        skills = _parse_skills()
        _send_json(handler, 200, {'skills': skills})
        return True

    # SSE 스트림 — 프로필 변경 실시간 통지
    if path == '/api/office/profiles/stream':
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Connection', 'keep-alive')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        _start_notify_listener()
        q: queue.Queue = queue.Queue(maxsize=100)
        with _SSE_LOCK:
            _SSE_CLIENTS.add(q)
        try:
            # 초기 핑 — 연결 확인용
            handler.wfile.write(b': connected\n\n')
            handler.wfile.flush()
            last_ping = time.time()
            while True:
                try:
                    payload = q.get(timeout=15)
                    handler.wfile.write(f'data: {payload}\n\n'.encode('utf-8'))
                    handler.wfile.flush()
                except queue.Empty:
                    # 15초마다 keepalive
                    handler.wfile.write(b': ping\n\n')
                    handler.wfile.flush()
                    last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print(f'[office_api] SSE 종료: {e}')
        finally:
            with _SSE_LOCK:
                _SSE_CLIENTS.discard(q)
        return True

    # 전체 목록 + 활성 ID
    if path == '/api/office/profiles':
        try:
            profiles = list_office_profiles()
            active_id = get_active_office_profile_id()
            _send_json(handler, 200, {
                'profiles': profiles,
                'activeProfileId': active_id,
            })
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 단일 조회
    if path.startswith('/api/office/profiles/') and path.count('/') == 4:
        profile_id = path.rsplit('/', 1)[1]
        try:
            profile = get_office_profile(profile_id)
            if profile is None:
                _send_json(handler, 404, {'error': 'not found'})
            else:
                _send_json(handler, 200, profile)
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 오피스 에이전트 하트비트 목록 (namespace='office' 필터)
    if path == '/api/office/agents/status':
        try:
            rows = query_rows(
                "SELECT agent_id, status, "
                "to_char(last_beat, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_beat, "
                "current_task, beat_count, config::text AS config "
                "FROM agent_heartbeats WHERE namespace = 'office' ORDER BY agent_id;"
            )
            _send_json(handler, 200, {'agents': rows})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 오피스 태스크 목록 (source='office' 필터)
    if path == '/api/office/tasks':
        try:
            rows = query_rows(
                "SELECT id, title, description, status, assigned_to, priority, "
                "kanban_status, role, claimed_by, updated_at, result "
                "FROM hive_tasks WHERE source = 'office' "
                "ORDER BY updated_at DESC LIMIT 200;"
            )
            _send_json(handler, 200, {'tasks': rows})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    return False


# ── POST 핸들러 ──────────────────────────────────────────────────────────

def handle_post(handler, path: str, DATA_DIR: Path) -> bool:
    ensure_schema(DATA_DIR)

    # 신규 프로필 생성
    if path == '/api/office/profiles':
        body = _read_json_body(handler)
        profile_id = (body.get('id') or '').strip()
        name = (body.get('name') or '').strip()
        data = body.get('data') or {}
        if not profile_id or not name:
            _send_json(handler, 400, {'error': 'id, name 필수'})
            return True
        try:
            ok = upsert_office_profile(profile_id, name, data, is_default=False)
            if ok:
                _send_json(handler, 201, {'id': profile_id, 'status': 'created'})
            else:
                _send_json(handler, 500, {'error': 'upsert 실패'})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 오피스 태스크 생성 — source='office' 자동 태깅
    if path == '/api/office/tasks':
        body = _read_json_body(handler)
        import uuid
        tid = body.get('id') or f"office-task-{uuid.uuid4().hex[:10]}"
        title = (body.get('title') or '').strip()
        desc = body.get('description') or ''
        assigned_to = body.get('assigned_to') or 'all'
        priority = body.get('priority') or 'medium'
        now_iso = time.strftime('%Y-%m-%dT%H:%M:%S')
        try:
            ok = execute(
                f"INSERT INTO hive_tasks (id, title, description, status, "
                f"assigned_to, priority, kanban_status, source, timestamp, updated_at) "
                f"VALUES ({_sql_text(tid)}, {_sql_text(title)}, {_sql_text(desc)}, "
                f"'pending', {_sql_text(assigned_to)}, {_sql_text(priority)}, "
                f"'todo', 'office', {_sql_text(now_iso)}, {_sql_text(now_iso)});"
            )
            if ok:
                _send_json(handler, 201, {'id': tid, 'status': 'created'})
            else:
                _send_json(handler, 500, {'error': 'insert 실패'})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 오피스 에이전트 하트비트 기록 — namespace='office' 고정
    if path == '/api/office/agents/heartbeat':
        body = _read_json_body(handler)
        agent_id = (body.get('agent_id') or '').strip()
        status = body.get('status') or 'idle'
        current_task = body.get('current_task')
        if not agent_id:
            _send_json(handler, 400, {'error': 'agent_id 필수'})
            return True
        task_val = _sql_text(current_task) if current_task else 'NULL'
        try:
            ok = execute(
                f"INSERT INTO agent_heartbeats "
                f"(agent_id, status, last_beat, current_task, beat_count, namespace) "
                f"VALUES ({_sql_text(agent_id)}, {_sql_text(status)}, now(), "
                f"{task_val}, 1, 'office') "
                f"ON CONFLICT (agent_id) DO UPDATE SET "
                f"status = EXCLUDED.status, last_beat = now(), "
                f"current_task = EXCLUDED.current_task, "
                f"beat_count = agent_heartbeats.beat_count + 1, "
                f"namespace = 'office';"
            )
            _send_json(handler, 200 if ok else 500, {'ok': ok})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    return False


# ── PUT 핸들러 ───────────────────────────────────────────────────────────

def handle_put(handler, path: str, DATA_DIR: Path) -> bool:
    ensure_schema(DATA_DIR)

    # 활성 프로필 변경
    if path.startswith('/api/office/profiles/active/'):
        profile_id = path.rsplit('/', 1)[1]
        try:
            existing = get_office_profile(profile_id)
            if existing is None:
                _send_json(handler, 404, {'error': 'profile not found'})
                return True
            ok = set_active_office_profile(profile_id)
            _send_json(handler, 200 if ok else 500, {'activeProfileId': profile_id})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    # 프로필 전체 대체
    if path.startswith('/api/office/profiles/') and path.count('/') == 4:
        profile_id = path.rsplit('/', 1)[1]
        body = _read_json_body(handler)
        name = (body.get('name') or '').strip()
        data = body.get('data') or {}
        if not name:
            _send_json(handler, 400, {'error': 'name 필수'})
            return True
        try:
            existing = get_office_profile(profile_id)
            is_default = bool(existing and existing.get('is_default'))
            ok = upsert_office_profile(profile_id, name, data, is_default=is_default)
            _send_json(handler, 200 if ok else 500, {'id': profile_id, 'status': 'updated'})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    return False


# ── DELETE 핸들러 ────────────────────────────────────────────────────────

def handle_delete(handler, path: str, DATA_DIR: Path) -> bool:
    ensure_schema(DATA_DIR)

    if path.startswith('/api/office/profiles/') and path.count('/') == 4:
        profile_id = path.rsplit('/', 1)[1]
        try:
            existing = get_office_profile(profile_id)
            if existing is None:
                _send_json(handler, 404, {'error': 'not found'})
                return True
            if existing.get('is_default'):
                _send_json(handler, 400, {'error': '기본 프로필은 삭제할 수 없습니다'})
                return True
            ok = delete_office_profile(profile_id)
            # 활성 프로필이 삭제된 경우 default로 폴백
            if ok and get_active_office_profile_id() == profile_id:
                set_active_office_profile('default')
            _send_json(handler, 200 if ok else 500, {'id': profile_id, 'status': 'deleted'})
        except Exception as e:
            _send_json(handler, 500, {'error': str(e)})
        return True

    return False
