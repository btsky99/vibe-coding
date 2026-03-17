# -*- coding: utf-8 -*-
"""
FILE: scripts/claude_hook.py
DESCRIPTION: Claude Code 전용 자동 훅 핸들러.
             PostToolUse / Stop 이벤트를 stdin JSON으로 수신하여
             hive_bridge.log_task() → pg_logs,
             hive_bridge.log_thought() → pg_thoughts 에 자동 기록합니다.
             지식 그래프(KnowledgeGraphPanel)에 Claude 노드가 표시되려면
             pg_thoughts에 데이터가 쌓여야 합니다.

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


def main():
    # stdin에서 이벤트 JSON 수신
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    event = data.get('hook_event_name', '')

    # ── 터미널 ID 감지 (환경변수 TERMINAL_ID, 기본 T0) ────────────────────
    terminal_id = os.environ.get('TERMINAL_ID', 'T0')
    agent_name  = os.environ.get('HIVE_AGENT', 'claude')
    agent_label = f'{agent_name}:{terminal_id}'

    # ── hive_bridge import ──────────────────────────────────────────────
    try:
        from hive_bridge import log_task, log_thought
    except ImportError:
        sys.exit(0)

    # ── UserPromptSubmit: 작업 시작 시 하이브에 자동 기록 ─────────────────
    #    핵심: 다른 에이전트가 "이 터미널이 뭘 하고 있는지" 볼 수 있게 하는 것
    if event == 'UserPromptSubmit':
        user_prompt = (data.get('prompt') or data.get('user_prompt') or data.get('content') or data.get('message') or '').strip()
        if user_prompt:
            short_prompt = _short(user_prompt, 120)
            # pg_logs에 작업 시작 기록
            log_task(agent_label, f'[작업 시작] {short_prompt}')
            # pg_thoughts에 사고 과정 기록 — 지식 그래프에 표시됨
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

        # 파일 생성/수정
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

        # Bash 명령 실행
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


if __name__ == '__main__':
    main()
