"""
FILE: api/dispatcher_api.py
DESCRIPTION: /api/dispatcher/* 엔드포인트 핸들러 모듈.
             에이전트별 태스크 적합도 점수 조회, 현재 분배 현황, 디스패치 히스토리,
             태스크 자동 분배, 병렬 팬아웃, 크로스 검증 기능을 제공합니다.
             server.py에서 분리하여 디스패처 관련 로직을 단일 파일로 관리합니다.

REVISION HISTORY:
- 2026-03-22 Claude: server.py에서 분리 — dispatcher API 핸들러 담당
"""

import json
import sys
import urllib.parse


def handle_get(handler, path: str, params: dict, *,
               SCRIPTS_DIR, list_tasks, current_project_id: str) -> bool:
    """GET 요청 처리 — /api/dispatcher/score, /api/dispatcher/status, /api/dispatcher/history 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/dispatcher/score ──────────────────────────────────────────
    # 디스패처 — 에이전트별 태스크 적합도 점수 조회
    # [쿼리 파라미터] desc: 태스크 설명, type: 태스크 유형(선택)
    if path == '/api/dispatcher/score':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            qs = urllib.parse.parse_qs(params) if isinstance(params, str) else params
            desc = qs.get('desc', [''])[0] if isinstance(qs.get('desc'), list) else qs.get('desc', '')
            task_type = qs.get('type', [None])[0] if isinstance(qs.get('type'), list) else qs.get('type')

            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 디스패처 기능을 사용할 수 없습니다')
            sys.path.insert(0, str(SCRIPTS_DIR))
            import auto_dispatcher as _ad
            if not task_type:
                task_type = _ad.detect_task_type(desc)
            scores = {name: _ad.score_agent(name, task_type) for name in _ad.AGENT_CAPABILITIES}
            best = _ad.select_best_agent(task_type)
            handler.wfile.write(json.dumps({
                'task_type': task_type,
                'description': desc,
                'scores': scores,
                'best_agent': best,
                'capabilities': {
                    name: cap['strengths']
                    for name, cap in _ad.AGENT_CAPABILITIES.items()
                },
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/dispatcher/status ─────────────────────────────────────────
    # 디스패처 — 현재 분배 현황 조회
    elif path == '/api/dispatcher/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 디스패처 기능을 사용할 수 없습니다')
            sys.path.insert(0, str(SCRIPTS_DIR))
            import auto_dispatcher as _ad2
            stat = _ad2.status()
            handler.wfile.write(json.dumps(stat, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/dispatcher/history ────────────────────────────────────────
    # [2026-03-19 추가] 디스패치 히스토리 조회
    # [설계 의도] 대시보드 "최근 디스패치" 패널이 hive_tasks에서 디스패치 레코드를
    # 조회할 수 있도록 전용 엔드포인트를 제공합니다.
    # hive_tasks 테이블에서 created_by='dispatcher' 이고 tags에 'dispatch'가 포함된
    # 레코드를 최신순으로 반환합니다.
    elif path == '/api/dispatcher/history':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            tasks = list_tasks(project_id=current_project_id)
            # 디스패치 태스크만 필터링 (created_by='dispatcher' 또는 tags에 'dispatch' 포함)
            dispatch_tasks = [
                t for t in tasks
                if t.get('created_by') == 'dispatcher'
                or 'dispatch' in (t.get('tags') or [])
            ]
            # DispatcherPanel.tsx의 DispatchResult 인터페이스에 맞춰 변환
            history = []
            for t in dispatch_tasks[:30]:  # 최근 30개만
                history.append({
                    'task_id': t.get('id', ''),
                    'assigned_to': t.get('assigned_to', ''),
                    'task_type': t.get('role', '') or (t.get('tags', [''])[1] if len(t.get('tags', [])) > 1 else ''),
                    'score': t.get('scores', {}).get(t.get('assigned_to', ''), 0) if isinstance(t.get('scores'), dict) else 0,
                    'verifier': t.get('verifier', None),
                    'status': t.get('status', 'dispatched'),
                    'scores': t.get('scores', {}),
                    'description': t.get('description', ''),
                    'dispatched_at': t.get('timestamp', ''),
                })
            handler.wfile.write(json.dumps(history, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            print(f"[PG ERROR] /api/dispatcher/history: {e}")
            handler.wfile.write(json.dumps([], ensure_ascii=False).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict, *,
                SCRIPTS_DIR) -> bool:
    """POST 요청 처리 — /api/dispatcher/dispatch, fan-out, verify 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/dispatcher/dispatch ───────────────────────────────────────
    # 디스패처 — 태스크를 최적 에이전트에 자동 분배 (POST)
    # [Body] {"description": "...", "type": "bug_fix", "to": "claude", "priority": "high"}
    if path == '/api/dispatcher/dispatch':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 디스패처 기능을 사용할 수 없습니다')
            sys.path.insert(0, str(SCRIPTS_DIR))
            import auto_dispatcher as _ad3
            result = _ad3.dispatch(
                description=data.get('description', ''),
                task_type=data.get('type'),
                assigned_to=data.get('to'),
                priority=data.get('priority', 'medium'),
                require_verification=data.get('verify', True),
            )
            handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/dispatcher/fan-out ────────────────────────────────────────
    # 디스패처 — 여러 태스크 병렬 분배 (POST)
    # [Body] {"tasks": ["태스크1", "태스크2", ...], "type": "auto"}
    elif path == '/api/dispatcher/fan-out':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 디스패처 기능을 사용할 수 없습니다')
            sys.path.insert(0, str(SCRIPTS_DIR))
            import auto_dispatcher as _ad4
            tasks = data.get('tasks', [])
            results = _ad4.fan_out(*tasks, task_type=data.get('type'))
            handler.wfile.write(json.dumps(results, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/dispatcher/verify ─────────────────────────────────────────
    # 디스패처 — 크로스 검증 요청 (POST)
    # [Body] {"task_id": "TASK-...", "summary": "...", "author": "claude"}
    elif path == '/api/dispatcher/verify':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 디스패처 기능을 사용할 수 없습니다')
            sys.path.insert(0, str(SCRIPTS_DIR))
            import auto_dispatcher as _ad5
            result = _ad5.request_verification(
                task_id=data.get('task_id', ''),
                result_summary=data.get('summary', ''),
                author=data.get('author', 'unknown'),
            )
            handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    return False
