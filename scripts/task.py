"""
에이전트 간 공유 태스크 보드 헬퍼 스크립트
-------------------------------------------
사용법:
  python scripts/task.py create <title> [--desc <설명>] [--to <담당자>] [--priority <우선순위>]
  python scripts/task.py start  <task_id>
  python scripts/task.py done   <task_id>
  python scripts/task.py list   [--status <상태>]
  python scripts/task.py delete <task_id>

예시:
  python scripts/task.py create "API 엔드포인트 구현" --to claude --priority high
  python scripts/task.py create "UI 리팩토링" --to gemini --desc "버튼 컴포넌트 정리"
  python scripts/task.py start  1706000000001
  python scripts/task.py done   1706000000001
  python scripts/task.py list   --status pending
  python scripts/task.py delete 1706000000001

담당자 (--to): claude / gemini / all (기본값: all)
우선순위 (--priority): high / medium / low (기본값: medium)
상태 (--status): pending / in_progress / done / all (기본값: all)
"""

import sys
import json
import argparse
import urllib.request
import urllib.error
import os
import time

DEFAULT_PORTS = [8005, 8000]


def api_get(path: str, port: int) -> dict | list | None:
    """GET 요청 헬퍼"""
    try:
        with urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=3) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def api_post(path: str, body: dict, port: int) -> dict | None:
    """POST 요청 헬퍼"""
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


def find_port() -> int | None:
    """실행 중인 서버 포트 자동 감지"""
    for p in DEFAULT_PORTS:
        result = api_get('/api/tasks', p)
        if result is not None:
            return p
    return None


def fallback_tasks_file() -> str:
    """서버 미실행 시 tasks.json 직접 경로 반환"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    return os.path.join(project_root, '.ai_monitor', 'data', 'tasks.json')


def load_tasks_direct() -> list:
    """파일에서 직접 작업 목록 읽기 (폴백)"""
    path = fallback_tasks_file()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_tasks_direct(tasks: list) -> None:
    """파일에 직접 작업 목록 저장 (폴백)"""
    path = fallback_tasks_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


# ─── 명령어 구현 ─────────────────────────────────────────────────────────────

def cmd_create(args: argparse.Namespace, port: int | None) -> None:
    body = {
        'title': args.title,
        'description': getattr(args, 'desc', '') or '',
        'assigned_to': getattr(args, 'to', 'all') or 'all',
        'priority': getattr(args, 'priority', 'medium') or 'medium',
        'created_by': getattr(args, 'by', 'agent') or 'agent',
    }
    if port:
        result = api_post('/api/tasks', body, port)
        if result and result.get('status') == 'success':
            t = result['task']
            print(f"[OK] 작업 생성 완료 ID={t['id']}: {t['title']} → {t['assigned_to']} [{t['priority']}]")
            return

    # 폴백: 직접 파일 수정
    tasks = load_tasks_direct()
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    task = {
        'id': str(int(time.time() * 1000)),
        'timestamp': now,
        'updated_at': now,
        **body,
        'status': 'pending',
    }
    tasks.append(task)
    save_tasks_direct(tasks)
    print(f"[OK] 작업 파일 직접 생성 ID={task['id']}: {task['title']}")


def cmd_update_status(task_id: str, status: str, port: int | None) -> None:
    if port:
        result = api_post('/api/tasks/update', {'id': task_id, 'status': status}, port)
        if result and result.get('status') == 'success':
            t = result.get('task') or {}
            print(f"[OK] 작업 상태 변경 → {status}: {t.get('title', task_id)}")
            return

    # 폴백
    tasks = load_tasks_direct()
    for t in tasks:
        if t['id'] == task_id:
            t['status'] = status
            t['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            save_tasks_direct(tasks)
            print(f"[OK] 작업 상태 변경 (직접) → {status}: {t['title']}")
            return
    print(f"[FAIL] ID={task_id} 작업을 찾을 수 없습니다.", file=sys.stderr)


def cmd_list(args: argparse.Namespace, port: int | None) -> None:
    status_filter = getattr(args, 'status', 'all') or 'all'
    tasks = api_get('/api/tasks', port) if port else None
    if tasks is None:
        tasks = load_tasks_direct()

    if status_filter != 'all':
        tasks = [t for t in tasks if t['status'] == status_filter]

    if not tasks:
        print("작업 없음")
        return

    status_icon = {'pending': '⏳', 'in_progress': '🔄', 'done': '✅'}
    priority_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
    for t in tasks:
        si = status_icon.get(t['status'], '?')
        pi = priority_icon.get(t['priority'], '·')
        print(f"{si} {pi} [{t['id']}] {t['title']}  → {t['assigned_to']}  ({t['status']})")


def cmd_delete(task_id: str, port: int | None) -> None:
    if port:
        result = api_post('/api/tasks/delete', {'id': task_id}, port)
        if result and result.get('status') == 'success':
            print(f"[OK] 작업 삭제 완료: ID={task_id}")
            return

    # 폴백
    tasks = load_tasks_direct()
    before = len(tasks)
    tasks = [t for t in tasks if t['id'] != task_id]
    if len(tasks) < before:
        save_tasks_direct(tasks)
        print(f"[OK] 작업 삭제 (직접): ID={task_id}")
    else:
        print(f"[FAIL] ID={task_id} 작업을 찾을 수 없습니다.", file=sys.stderr)


# ─── 진입점 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='태스크 보드 CLI 헬퍼')
    sub = parser.add_subparsers(dest='command')

    # create
    p_create = sub.add_parser('create', help='새 작업 생성')
    p_create.add_argument('title', help='작업 제목')
    p_create.add_argument('--desc', default='', help='상세 설명')
    p_create.add_argument('--to', default='all', help='담당 에이전트 (claude/gemini/all)')
    p_create.add_argument('--priority', default='medium', choices=['high', 'medium', 'low'])
    p_create.add_argument('--by', default='agent', help='생성자')

    # start
    p_start = sub.add_parser('start', help='작업 시작 (pending → in_progress)')
    p_start.add_argument('id', help='작업 ID')

    # done
    p_done = sub.add_parser('done', help='작업 완료 (→ done)')
    p_done.add_argument('id', help='작업 ID')

    # list
    p_list = sub.add_parser('list', help='작업 목록 조회')
    p_list.add_argument('--status', default='all', choices=['all', 'pending', 'in_progress', 'done'])

    # delete
    p_del = sub.add_parser('delete', help='작업 삭제')
    p_del.add_argument('id', help='작업 ID')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    port = find_port()
    if not port:
        print("[INFO] 서버 미실행 — 파일 직접 접근 모드")

    if args.command == 'create':
        cmd_create(args, port)
    elif args.command == 'start':
        cmd_update_status(args.id, 'in_progress', port)
    elif args.command == 'done':
        cmd_update_status(args.id, 'done', port)
    elif args.command == 'list':
        cmd_list(args, port)
    elif args.command == 'delete':
        cmd_delete(args.id, port)


if __name__ == '__main__':
    main()
