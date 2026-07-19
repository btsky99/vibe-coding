"""
FILE: infra/tool_install.py
DESCRIPTION: CLI 도구(Antigravity/Claude Code/Codex) 설치 상태 + 백그라운드 npm
             install 상태 머신. 로컬 PATH에서 실행 파일 탐지, 버전 조회,
             npm 실행 파일 해석, 설치 상태 스냅샷 관리, 설치 프로세스
             기동 + 출력 파이프 감시까지 한 묶음으로 제공합니다.

             외부 공개 API (server.py 호출부가 의존하는 것만):
               - tool_status(name)           : 설치 여부 + 경로 + 버전
               - get_npm_executable()        : 플랫폼별 npm 실행 파일 경로
               - get_tool_install_state(n)   : 설치 진행 스냅샷
               - start_tool_install(name)    : npm install -g 백그라운드 기동

REVISION HISTORY:
- 2026-04-21 Claude: server.py L1084~1338 분리 (Task 7.1)
                     글로벌 상태 dict(_tool_install_state, _tool_install_lock)
                     은 모듈 내부로 캡슐화
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지


# ── 지원 도구 메타 ──────────────────────────────────────────────────────────
TOOL_INSTALL_TARGETS: dict[str, dict] = {
    'antigravity': {
        'package': '@google/gemini-cli',
        'display': 'Antigravity CLI',
        'command': 'antigravity',
    },
    'claude': {
        'package': '@anthropic-ai/claude-code',
        'display': 'Claude Code',
        'command': 'claude',
    },
    'codex': {
        'package': '@openai/codex',
        'display': 'Codex CLI',
        'command': 'codex',
    },
}


# ── 내부 상태 (잠금 보호) ────────────────────────────────────────────────────
_lock = threading.Lock()
_state: dict[str, dict] = {}


# ── CLI 상태 조회 ────────────────────────────────────────────────────────────
def tool_status(name: str) -> dict:
    """Return local CLI installation status for a supported tool."""
    if not name:
        return {"installed": False, "path": "", "version": ""}

    candidates = [name]
    if os.name == 'nt':
        path_name = Path(name).name
        if '.' not in path_name:
            candidates.extend([f'{name}.exe', f'{name}.cmd', f'{name}.bat'])
        else:
            candidates.append(f'{name}.cmd')

    exe_path = ''
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            exe_path = found
            break

    if not exe_path:
        return {"installed": False, "path": "", "version": ""}

    version = ''
    try:
        # [지역변수 rename] proc→completed: 모듈 proc(콘솔숨김 헬퍼)와 충돌 회피
        completed = proc.run(
            [exe_path, '--version'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
        )
        output = (completed.stdout or completed.stderr or '').strip()
        version = output.splitlines()[0] if output else ''
    except Exception:
        version = ''

    return {"installed": True, "path": exe_path, "version": version}


def get_npm_executable() -> str:
    """Resolve npm executable with Windows-first lookup for background installs."""
    candidates = ['npm']
    if os.name == 'nt':
        candidates = ['npm.cmd', 'npm.exe', 'npm']

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return ''


# ── 설치 상태 머신 ─────────────────────────────────────────────────────────
def _now() -> str:
    """Return a compact local timestamp for tool install progress snapshots."""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())


def _default_state(name: str) -> dict:
    """Return the default install state payload for a supported tool."""
    tool_meta = TOOL_INSTALL_TARGETS.get(name, {})
    return {
        'tool': name,
        'display': tool_meta.get('display', name),
        'status': 'idle',
        'message': '',
        'last_line': '',
        'logs': [],
        'started_at': '',
        'finished_at': '',
        'pid': None,
        'exit_code': None,
    }


def get_tool_install_state(name: str) -> dict:
    """Return a thread-safe snapshot of the current install state."""
    base = _default_state(name)
    with _lock:
        current = _state.get(name, {})
        snapshot = dict(base)
        snapshot.update(current)
        logs = snapshot.get('logs') or []
        snapshot['logs'] = list(logs[-20:])
        return snapshot


def _set_state(name: str, **updates) -> dict:
    """Update a tool install snapshot and return the merged state."""
    with _lock:
        current = _state.get(name, _default_state(name))
        next_state = dict(current)
        next_state.update(updates)
        logs = next_state.get('logs') or []
        next_state['logs'] = list(logs[-20:])
        _state[name] = next_state
        return dict(next_state)


def _watch_install(name: str, proc: subprocess.Popen, command_name: str, display_name: str) -> None:
    """Capture npm install output so the UI can poll live progress lines."""
    logs: list[str] = []
    last_line = ''

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = (raw_line or '').strip()
                if not line:
                    continue
                last_line = line
                logs.append(line)
                _set_state(name, last_line=line, logs=logs)

        exit_code = proc.wait()
        tool_info = tool_status(command_name)
        installed = bool(tool_info.get('installed'))

        if exit_code == 0 and installed:
            message = f'{display_name} installation completed.'
            status = 'completed'
        else:
            fallback = last_line or f'npm exited with code {exit_code}.'
            message = f'{display_name} installation failed: {fallback}'
            status = 'failed'

        _set_state(
            name,
            status=status,
            message=message,
            last_line=last_line,
            logs=logs,
            finished_at=_now(),
            exit_code=exit_code,
            pid=None,
        )
    except Exception as exc:
        failure_line = str(exc)
        if failure_line:
            logs.append(failure_line)
        _set_state(
            name,
            status='failed',
            message=f'{display_name} installation failed: {failure_line or "unknown error"}',
            last_line=failure_line,
            logs=logs,
            finished_at=_now(),
            pid=None,
        )


def start_tool_install(name: str) -> dict:
    """Start a background npm install and expose pollable progress for the UI."""
    tool_meta = TOOL_INSTALL_TARGETS.get(name)
    if not tool_meta:
        return {'status': 'error', 'message': f'Unsupported tool: {name}'}

    current = get_tool_install_state(name)
    if current.get('status') == 'running':
        return {
            'status': 'success',
            'message': f'{tool_meta["display"]} installation is already running.',
            'install': current,
        }

    npm_exe = get_npm_executable()
    if not npm_exe:
        failed = _set_state(
            name,
            status='failed',
            message='npm executable was not found.',
            last_line='npm executable was not found.',
            logs=['npm executable was not found.'],
            finished_at=_now(),
            pid=None,
            exit_code=None,
        )
        return {'status': 'error', 'message': failed['message'], 'install': failed}

    display_name = tool_meta['display']
    package_name = tool_meta['package']
    command_name = tool_meta['command']

    try:
        # [지역변수 rename] proc→child: 모듈 proc(콘솔숨김 헬퍼)와 충돌 회피
        child = proc.popen(
            [npm_exe, 'install', '-g', package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
    except Exception as exc:
        failed = _set_state(
            name,
            status='failed',
            message=f'Could not start {display_name} installation: {exc}',
            last_line=str(exc),
            logs=[str(exc)],
            finished_at=_now(),
            pid=None,
            exit_code=None,
        )
        return {'status': 'error', 'message': failed['message'], 'install': failed}

    initial = _set_state(
        name,
        display=display_name,
        status='running',
        message=f'{display_name} installation is in progress.',
        last_line=f'Running npm install -g {package_name}',
        logs=[f'Running npm install -g {package_name}'],
        started_at=_now(),
        finished_at='',
        pid=child.pid,
        exit_code=None,
    )

    watcher = threading.Thread(
        target=_watch_install,
        args=(name, child, command_name, display_name),
        daemon=True,
    )
    watcher.start()

    return {
        'status': 'success',
        'message': f'{display_name} installation started.',
        'install': initial,
    }
