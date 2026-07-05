"""
FILE: api/git_api.py
DESCRIPTION: /api/git/* 엔드포인트 핸들러 모듈.
             Git 저장소 상태 조회, 커밋 로그 조회, diff 확인,
             파일 롤백(git checkout) 기능을 제공합니다.
             server.py에서 분리하여 Git 관련 로직을 단일 파일로 관리합니다.

REVISION HISTORY:
- 2026-03-01 Claude: server.py에서 분리 — git API 핸들러 담당
- 2026-07-06 Claude: do_POST exact 인라인 rollback/diff를 rollback()/diff()로 verbatim 분리(R8).
  [주의] 아래 handle_post()의 rollback/diff 분기와 동작이 다르다(rollback 성공 message 없음,
  git_dir 키가 'path' vs 'repo'; diff는 body 미사용·쿼리스트링만). 원본 do_POST의 exact 인라인이
  prefix 위임(handle_post)보다 먼저 걸렸으므로 그 동작을 보존한다 — 두 경로 수렴은 R9 대상.
"""

import json
import re
import subprocess
import sys
from pathlib import Path


def handle_get(handler, path: str, params: dict, BASE_DIR: Path) -> bool:
    """GET 요청 처리 — /api/git/status, /api/git/log 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/git/status ──────────────────────────────────────────────────
    if path == '/api/git/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        # ?path= 쿼리 파라미터로 대상 저장소 경로 지정, 없으면 프로젝트 루트
        git_path = params.get('path', [''])[0].strip() or str(BASE_DIR.parent)
        try:
            # git status --porcelain=v1 -b: 머신 파싱용 간결 포맷
            # creationflags=0x08000000: CREATE_NO_WINDOW — 콘솔 창 방지
            result = subprocess.run(
                ['git', 'status', '--porcelain=v1', '-b'],
                cwd=git_path, capture_output=True, text=True, timeout=5, encoding='utf-8',
                creationflags=0x08000000
            )
            if result.returncode != 0:
                handler.wfile.write(json.dumps(
                    {'is_git_repo': False, 'error': result.stderr.strip()}
                ).encode('utf-8'))
                return True

            lines = result.stdout.splitlines()
            # 첫 줄: ## branch...origin/branch [ahead N] [behind N]
            branch_line = lines[0] if lines else ''
            branch = 'unknown'
            ahead  = 0
            behind = 0
            if branch_line.startswith('## '):
                branch_info = branch_line[3:]
                if branch_info.startswith('No commits yet on '):
                    branch = branch_info.split(' ')[-1]
                else:
                    branch = branch_info.split('...')[0].split(' ')[0]
                    ahead_m  = re.search(r'\[ahead (\d+)',  branch_info)
                    behind_m = re.search(r'behind (\d+)',   branch_info)
                    if ahead_m:  ahead  = int(ahead_m.group(1))
                    if behind_m: behind = int(behind_m.group(1))

            staged, unstaged, untracked, conflicts = [], [], [], []
            for line in lines[1:]:
                if len(line) < 2:
                    continue
                xy    = line[:2]
                fname = line[3:]
                if xy in ('UU', 'AA', 'DD', 'AU', 'UA', 'DU', 'UD'):
                    conflicts.append(fname)
                elif xy[0] != ' ' and xy[0] != '?':
                    staged.append(fname)
                if xy[1] == 'M' or xy[1] == 'D':
                    unstaged.append(fname)
                elif xy == '??':
                    untracked.append(fname)

            handler.wfile.write(json.dumps({
                'is_git_repo': True,
                'branch':      branch,
                'ahead':       ahead,
                'behind':      behind,
                'staged':      staged,
                'unstaged':    unstaged,
                'untracked':   untracked,
                'conflicts':   conflicts,
            }, ensure_ascii=False).encode('utf-8'))
        except subprocess.TimeoutExpired:
            handler.wfile.write(json.dumps({'is_git_repo': False, 'error': 'git timeout'}).encode('utf-8'))
        except FileNotFoundError:
            handler.wfile.write(json.dumps({'is_git_repo': False, 'error': 'git not found'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'is_git_repo': False, 'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/git/log ─────────────────────────────────────────────────────
    elif path == '/api/git/log':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        git_path = params.get('path', [''])[0].strip() or str(BASE_DIR.parent)
        n = min(int(params.get('n', ['10'])[0]), 50)  # 최대 50개 제한
        try:
            result = subprocess.run(
                ['git', 'log', f'--format=%h\x1f%s\x1f%an\x1f%ar', f'-n{n}'],
                cwd=git_path, capture_output=True, text=True, timeout=5, encoding='utf-8',
                creationflags=0x08000000
            )
            commits = []
            for line in result.stdout.strip().splitlines():
                parts = line.split('\x1f')
                if len(parts) == 4:
                    commits.append({'hash': parts[0], 'message': parts[1], 'author': parts[2], 'date': parts[3]})
            handler.wfile.write(json.dumps(commits, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            print(f"[git_api] git log 조회 실패: {e}")
            handler.wfile.write(json.dumps([]).encode('utf-8'))
        return True

    return False


def rollback(handler, BASE_DIR: Path) -> None:
    """POST /api/git/rollback — 특정 파일 변경 원상복구(git checkout -- 파일).
    [R8 verbatim] server.py do_POST exact 인라인 이전. body를 직접 소비(Content-Length 만큼).
    [주의] handle_post()의 rollback 분기와 다름 — git_dir는 'path' 키, 성공 응답에 message 없음.
      원본 exact 동작 보존(수렴은 R9). body 읽기는 try 내부(원본 위치 그대로).
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))
        file_path = data.get('file')
        git_dir = data.get('path', str(BASE_DIR.parent))

        if not file_path:
            handler.wfile.write(json.dumps({"status": "error", "message": "File path required"}).encode('utf-8'))
            return

        # git checkout -- "파일명" 실행
        result = subprocess.run(
            ['git', 'checkout', '--', file_path],
            cwd=git_dir, capture_output=True, text=True, timeout=10, encoding='utf-8',
            creationflags=0x08000000
        )

        if result.returncode == 0:
            handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
        else:
            handler.wfile.write(json.dumps({"status": "error", "message": result.stderr.strip()}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def diff(handler, params: dict, BASE_DIR: Path) -> None:
    """POST /api/git/diff — 파일 diff(쿼리스트링 기반, POST body 미사용).
    [R8 verbatim] server.py do_POST exact 인라인 이전. params=parse_qs(query).
    [주의] handle_post()의 diff 분기와 파라미터 추출 위치만 다름(헤더 전송 후 추출). 원본 exact 보존.
    """
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    target_file = params.get('path', [''])[0]
    git_dir = params.get('git_path', [str(BASE_DIR.parent)])[0]

    try:
        # git diff "파일명" 실행
        result = subprocess.run(
            ['git', 'diff', '--', target_file],
            cwd=git_dir, capture_output=True, text=True, timeout=5, encoding='utf-8',
            creationflags=0x08000000
        )
        handler.wfile.write(json.dumps({"diff": result.stdout}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))


def handle_post(handler, path: str, data: dict, BASE_DIR: Path) -> bool:
    """POST 요청 처리 — /api/git/rollback, /api/git/diff 담당.

    반환값: 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/git/rollback ────────────────────────────────────────────────
    if path == '/api/git/rollback':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            file_path = data.get('file')
            repo_path = data.get('repo', str(BASE_DIR.parent))
            if not file_path:
                handler.wfile.write(json.dumps({"status": "error", "message": "file 필드 필수"}).encode('utf-8'))
                return True
            result = subprocess.run(
                ['git', 'checkout', '--', file_path],
                cwd=repo_path, capture_output=True, text=True, timeout=10, encoding='utf-8',
                creationflags=0x08000000
            )
            if result.returncode == 0:
                handler.wfile.write(json.dumps({"status": "success", "message": f"{file_path} 복구 완료"}).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({"status": "error", "message": result.stderr.strip()}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    # ── /api/git/diff ────────────────────────────────────────────────────
    # 원본 server.py에서는 do_POST 아래에 있지만 쿼리스트링에서 파라미터를 읽음
    # (POST body 미사용) → params를 함께 전달받아 쿼리스트링 방식으로 처리
    elif path == '/api/git/diff':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            target_file = data.get('path', [''])[0] if isinstance(data, dict) and 'path' in data else ''
            git_dir     = data.get('git_path', [str(BASE_DIR.parent)])[0] if isinstance(data, dict) else str(BASE_DIR.parent)
            result = subprocess.run(
                ['git', 'diff', '--', target_file],
                cwd=git_dir, capture_output=True, text=True, timeout=5, encoding='utf-8',
                creationflags=0x08000000
            )
            handler.wfile.write(json.dumps({"diff": result.stdout}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        return True

    return False
