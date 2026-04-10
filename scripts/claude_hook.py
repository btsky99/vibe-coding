# -*- coding: utf-8 -*-
"""
FILE: scripts/claude_hook.py
DESCRIPTION: Claude Code 전용 자동 훅 핸들러.
             PostToolUse / Stop 이벤트를 stdin JSON으로 수신하여
             hive_bridge.log_task() → pg_logs 에 자동 기록합니다.

             [Claude Code 훅 이벤트 스키마]
             stdin으로 JSON 수신:
               PostToolUse: { "hook_event_name": "PostToolUse",
                              "tool_name": "...", "tool_input": {...},
                              "tool_response": {...} }
               Stop:        { "hook_event_name": "Stop",
                              "session_id": "...", "stop_reason": "..." }

REVISION HISTORY:
- 2026-03-17 Claude: UserPromptSubmit 이벤트 추가 — 작업 시작 시 하이브에 자동 기록
  - 사용자 지시를 받으면 즉시 pg_logs + pg_thoughts에 "[작업 시작] T{N}: {내용}" 기록
  - 모든 에이전트가 서로 뭘 하는지 알 수 있도록 하이브 마인드 핵심 원칙 강제
- 2026-03-10 Claude: 최초 구현 — pg_logs + pg_thoughts 자동 기록 (지식 그래프 연동)
"""

import sys
import json
import os
import io
import subprocess
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
SCRIPTS_DIR = ROOT_DIR / 'scripts'

for p in [str(MONITOR_DIR), str(SCRIPTS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Windows UTF-8 보정
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── 단순 조회 명령어는 기록 스킵 (노이즈 방지) ──────────────────────────────
_SKIP_PREFIXES = (
    "ls ", "cat ", "head ", "tail ", "echo ", "pwd",
    "git status", "git log", "git diff",
    "python scripts/memory.py",
    "find ", "grep ", "rg ",
)

def _extract_commit_msg(cmd: str) -> str:
    """git commit 명령에서 실제 커밋 메시지를 추출한다.

    지원 패턴:
      git commit -m "feat(scope): 메시지"
      git commit -m "$(cat <<'EOF'\n메시지\nEOF\n)"
    """
    import re as _re
    # 패턴 1: HEREDOC — git commit -m "$(cat <<'EOF'\n내용\nEOF)"
    m = _re.search(r"cat\s+<<['\"]?EOF['\"]?\n(.+?)(?:\n\s*Co-Authored|\nEOF)", cmd, _re.DOTALL)
    if m:
        return m.group(1).strip()
    # 패턴 2: 단순 -m "..." 또는 -m '...'
    m = _re.search(r'-m\s+["\'](.+?)["\']', cmd, _re.DOTALL)
    if m:
        return m.group(1).strip()
    # 폴백: 전체 명령에서 git commit 부분 제거
    return cmd.replace('git commit', '').strip()[:200]


def _short(text: str, n: int = 60) -> str:
    """긴 문자열을 n자로 자릅니다."""
    text = text.strip().replace('\n', ' ')
    return text[:n] + '…' if len(text) > n else text

def _short_path(path: str) -> str:
    """절대경로에서 파일명만 반환합니다."""
    if not path:
        return '(unknown)'
    p = Path(path)
    # 프로젝트 루트 기준 상대경로 표시
    try:
        return str(p.relative_to(ROOT_DIR))
    except ValueError:
        return p.name

def _get_path(tool_input: dict) -> str:
    """tool_input에서 파일 경로를 추출합니다."""
    return (tool_input.get('file_path') or tool_input.get('path') or
            tool_input.get('filename') or '')


def _spawn_experience_record(agent: str, commit_msg: str):
    """커밋 메시지에서 경험을 추출하여 백그라운드로 DB에 기록한다."""
    import re as _re
    # task_type 추출 (feat/fix/refactor/...)
    m = _re.match(r'^(feat|fix|refactor|docs|build|chore|test)', commit_msg.lower())
    task_type = m.group(1) if m else 'chore'

    # domain 추론: scope에서 힌트 (예: feat(office) → frontend)
    scope_match = _re.search(r'\((\w+)\)', commit_msg)
    scope = scope_match.group(1).lower() if scope_match else ''
    domain_map = {
        'office': 'frontend', 'ui': 'frontend', 'view': 'frontend',
        'server': 'backend', 'api': 'backend', 'pty': 'backend',
        'db': 'db', 'pg': 'db', 'sql': 'db',
        'zettel': 'backend', 'release': 'infra', 'build': 'infra',
    }
    domain = domain_map.get(scope, 'general')

    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    # recall.py를 재활용하지 않고 직접 DB 호출하는 작은 스크립트 실행
    py_code = (
        f"import sys; sys.path.insert(0, {str(MONITOR_DIR)!r}); "
        f"from src.pg_store import ensure_schema, record_experience; "
        f"ensure_schema(); "
        f"record_experience("
        f"agent_id={agent.lower()!r}, task_type={task_type!r}, "
        f"domain={domain!r}, outcome='success', "
        f"description={commit_msg[:200]!r})"
    )
    try:
        subprocess.Popen(
            [sys.executable, '-c', py_code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_no_window,
        )
    except Exception:
        pass  # 훅 실패가 Claude 응답을 막으면 안 됨


def _spawn_zettel_capture(mode: str, agent: str, data: dict):
    """제텔카스텐 자동 캡처를 백그라운드로 spawn한다."""
    import json as _json
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    capture_script = str(SCRIPTS_DIR / 'zettel_capture.py')
    try:
        subprocess.Popen(
            [sys.executable, capture_script,
             '--mode', mode, '--agent', agent,
             '--data', _json.dumps(data, ensure_ascii=False)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_no_window,
        )
    except Exception:
        pass  # 캡처 실패해도 훅 전체가 실패하면 안 됨


def _do_log(data: dict):
    """실제 로깅 로직 — 백그라운드 워커(_bg_worker)에서 호출됩니다."""
    event = data.get('hook_event_name', '')

    # ── 터미널 ID 감지 (환경변수 TERMINAL_ID, 기본 T0) ────────────────────
    terminal_id = data.get('_terminal_id', 'T0')
    agent_name  = data.get('_agent_name', 'claude')
    agent_label = f'{agent_name}:{terminal_id}'

    # ── hive_bridge import ──────────────────────────────────────────────
    try:
        from hive_bridge import log_task, log_thought
    except ImportError:
        return

    # ── UserPromptSubmit: 작업 시작 시 하이브에 자동 기록 ─────────────────
    if event == 'UserPromptSubmit':
        user_prompt = (data.get('prompt') or data.get('user_prompt') or data.get('content') or data.get('message') or '').strip()
        if user_prompt:
            short_prompt = _short(user_prompt, 120)
            log_task(agent_label, f'[작업 시작] {short_prompt}')
            log_thought(agent_name, 'task-start', {
                'type': 'intent',
                'title': f'[{terminal_id}] 새 작업 수신',
                'content': short_prompt,
                'terminal': terminal_id
            })

    # ── PostToolUse: 파일 수정·실행 완료 후 pg_logs + pg_thoughts 기록 ────
    elif event == 'PostToolUse':
        tool_name  = data.get('tool_name', '')
        tool_input = data.get('tool_input') or {}

        if tool_name in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
            fp = _get_path(tool_input)
            rel = _short_path(fp)

            if tool_name == 'Write':
                content = tool_input.get('content', '')
                lines   = len(content.splitlines())
                log_task('Claude', f'[생성 완료] {rel} ({lines}줄) ✓')
                log_thought('claude', 'file-write', {
                    'type': 'action',
                    'title': f'파일 생성: {rel}',
                    'content': f'{lines}줄 작성. 미리보기: {_short(content, 80)}'
                })
            else:
                old = _short(tool_input.get('old_string', ''), 40)
                new = _short(tool_input.get('new_string', ''), 40)
                log_task('Claude', f'[수정 완료] {rel} ✓')
                log_thought('claude', 'file-edit', {
                    'type': 'action',
                    'title': f'파일 수정: {rel}',
                    'content': f'변경 전: {old} → 변경 후: {new}'
                })

        elif tool_name == 'Bash':
            cmd = tool_input.get('command', '').strip()
            if not any(cmd.startswith(p) for p in _SKIP_PREFIXES):
                short_cmd = _short(cmd, 60)
                if 'git commit' in cmd:
                    log_task('Claude', f'[커밋] {short_cmd}')
                    log_thought('claude', 'git', {
                        'type': 'decision',
                        'title': f'Git 커밋',
                        'content': short_cmd
                    })
                    # ── 제텔카스텐 자동 캡처: 커밋 → 노트 생성 ──
                    _commit_msg = _extract_commit_msg(cmd)
                    _spawn_zettel_capture('commit', agent_name, {
                        'message': _commit_msg,
                    })
                    # ── 경험 자동 기록: 커밋 → agent_experience 추가 ──
                    _spawn_experience_record(agent_name, _commit_msg)
                elif 'npm run build' in cmd or 'build' in cmd:
                    log_task('Claude', f'[빌드] {short_cmd}')
                    log_thought('claude', 'build', {
                        'type': 'action',
                        'title': '빌드 실행',
                        'content': short_cmd
                    })
                else:
                    log_task('Claude', f'[실행 완료] {short_cmd}')

    # ── Stop: 세션 종료 시 pg_thoughts에 세션 요약 기록 ─────────────────────
    elif event == 'Stop':
        stop_reason = data.get('stop_reason', 'end_turn')
        session_id  = data.get('session_id', '')[:8]
        log_task('Claude', f'─── Claude 세션 종료 ({stop_reason}) ───')
        log_thought('claude', 'session', {
            'type': 'log',
            'title': f'세션 종료 [{session_id}]',
            'content': f'stop_reason: {stop_reason}'
        })
        # ── 제텔카스텐 자동 캡처: 세션 종료 → 세션 요약 노트 생성 ──
        _spawn_zettel_capture('session', agent_name, {})


def main():
    """stdin에서 이벤트를 읽고, 로깅은 백그라운드 프로세스로 넘긴 뒤 즉시 종료합니다.
    이렇게 하면 Claude Code UI의 전송 버튼이 hook 완료를 기다리지 않아도 됩니다."""
    # stdin에서 이벤트 JSON 수신
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    if not data.get('hook_event_name'):
        sys.exit(0)

    # ── 환경변수를 data에 주입 (백그라운드 프로세스에서도 사용하기 위해) ────
    data['_terminal_id'] = os.environ.get('TERMINAL_ID', 'T0')
    data['_agent_name']  = os.environ.get('HIVE_AGENT', 'claude')

    # ── --bg-worker 모드: 백그라운드에서 실제 로깅 수행 ─────────────────────
    if '--bg-worker' in sys.argv:
        _do_log(data)
        return

    # ── 기본 모드: 백그라운드 프로세스를 spawn하고 즉시 종료 ─────────────────
    #    Windows에서 CREATE_NO_WINDOW로 detach하여 UI를 블로킹하지 않음
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        proc = subprocess.Popen(
            [sys.executable, __file__, '--bg-worker'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_no_window,
        )
        # stdin으로 원본 JSON 전달 후 즉시 닫기
        proc.stdin.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        proc.stdin.close()
        # 프로세스 완료를 기다리지 않음 — 즉시 종료
    except Exception:
        # spawn 실패 시 동기 폴백 (최소한 로그는 남기기)
        _do_log(data)


if __name__ == '__main__':
    main()
