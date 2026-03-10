import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import delete_task, list_tasks, save_task, update_task


DEFAULT_PORTS = [8005, 8000]


def api_get(path: str, port: int) -> dict | list | None:
    try:
        with urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=3) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None


def api_post(path: str, body: dict, port: int) -> dict | None:
    try:
        payload = json.dumps(body).encode('utf-8')
        request = urllib.request.Request(
            f'http://localhost:{port}{path}',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None


def find_port() -> int | None:
    for port in DEFAULT_PORTS:
        if api_get('/api/tasks', port) is not None:
            return port
    return None


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
            task = result['task']
            print(f"[OK] ID={task['id']}: {task['title']} -> {task['assigned_to']} [{task['priority']}]")
            return

    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    task = {
        'id': str(int(time.time() * 1000)),
        'timestamp': now,
        'updated_at': now,
        'status': 'pending',
        'kanban_status': 'todo',
        'tags': [],
        **body,
    }
    save_task(task)
    print(f"[OK] ID={task['id']}: {task['title']}")


def cmd_update_status(task_id: str, status: str, port: int | None) -> None:
    if port:
        result = api_post('/api/tasks/update', {'id': task_id, 'status': status}, port)
        if result and result.get('status') == 'success':
            task = result.get('task') or {}
            print(f"[OK] {status}: {task.get('title', task_id)}")
            return
    task = update_task(task_id, {'status': status})
    if not task:
        print(f"[FAIL] task not found: {task_id}", file=sys.stderr)
        return
    print(f"[OK] {status}: {task['title']}")


def cmd_list(args: argparse.Namespace, port: int | None) -> None:
    status_filter = getattr(args, 'status', 'all') or 'all'
    tasks = api_get('/api/tasks', port) if port else None
    if tasks is None:
        tasks = list_tasks()
    if status_filter != 'all':
        tasks = [task for task in tasks if task.get('status') == status_filter]
    if not tasks:
        print('no tasks')
        return
    for task in tasks:
        print(
            f"[{task.get('status', '?')}] "
            f"[{task.get('priority', '?')}] "
            f"{task.get('id')} {task.get('title', '')} -> {task.get('assigned_to', 'all')}"
        )


def cmd_delete(task_id: str, port: int | None) -> None:
    if port:
        result = api_post('/api/tasks/delete', {'id': task_id}, port)
        if result and result.get('status') == 'success':
            print(f"[OK] deleted: {task_id}")
            return
    if delete_task(task_id):
        print(f"[OK] deleted: {task_id}")
    else:
        print(f"[FAIL] task not found: {task_id}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Task CLI')
    sub = parser.add_subparsers(dest='command')

    create_parser = sub.add_parser('create')
    create_parser.add_argument('title')
    create_parser.add_argument('--desc', default='')
    create_parser.add_argument('--to', default='all')
    create_parser.add_argument('--priority', default='medium', choices=['high', 'medium', 'low'])
    create_parser.add_argument('--by', default='agent')

    start_parser = sub.add_parser('start')
    start_parser.add_argument('id')

    done_parser = sub.add_parser('done')
    done_parser.add_argument('id')

    list_parser = sub.add_parser('list')
    list_parser.add_argument('--status', default='all', choices=['all', 'pending', 'in_progress', 'done'])

    delete_parser = sub.add_parser('delete')
    delete_parser.add_argument('id')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    port = find_port()
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
