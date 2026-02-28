# -*- coding: utf-8 -*-
"""
FILE: scripts/hive_hook.py
DESCRIPTION: Claude Code 자동 액션 트레이스 훅 핸들러.
             PreToolUse / PostToolUse / Stop / UserPromptSubmit 이벤트를 수신하여
             hive_bridge.log_task()로 task_logs.jsonl + hive_mind.db에 자동 기록합니다.

             [설계 의도]
             - PreToolUse  : 수정 시작 전 "무엇을 어떻게 바꿀지" 예고 로그
             - PostToolUse : 수정 완료 후 "실제로 무엇이 바뀌었는지" 결과 로그
             - UserPromptSubmit: 사용자 지시 내용 기록
             - Stop: 응답 완료 구분선
             - 노이즈 방지: 단순 조회 명령(ls, git status 등)은 스킵

REVISION HISTORY:
- 2026-03-01 Claude: 최초 구현 — 자동 하이브 마인드 액션 트레이스 시스템 구축
- 2026-03-01 Claude: PreToolUse 추가 + PostToolUse에 실제 변경 내용(old→new) 포함
"""

import sys
import json
import os
import io

# Windows 환경 UTF-8 인코딩 강제 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# 단순 조회 명령어 스킵 목록
_SKIP_BASH_PREFIXES = (
    "ls ", "ls\n", "cat ", "head ", "tail ", "echo ",
    "pwd", "git status", "git log", "git diff",
    "python scripts/memory.py",
    "python D:/vibe-coding/scripts/memory.py",
    "python D:/vibe-coding/scripts/hive_hook.py",  # 훅 자체 재귀 방지
)


def _short_path(fp: str, depth: int = 3) -> str:
    """파일 경로를 마지막 N단계만 남겨 짧게 반환합니다."""
    parts = fp.replace("\\", "/").split("/")
    return "/".join(parts[-depth:]) if len(parts) >= depth else fp


def _short_cmd(cmd: str, max_len: int = 80) -> str:
    """명령어를 한 줄, max_len자 이내로 압축합니다."""
    return cmd.strip().replace("\n", " ")[:max_len]


def _snippet(text: str, max_len: int = 60) -> str:
    """긴 텍스트를 짧게 줄여 한 줄 스니펫으로 반환합니다."""
    if not text:
        return ""
    s = text.strip().replace("\n", "↵ ")
    return s[:max_len] + "…" if len(s) > max_len else s


def main():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return
        data = json.loads(raw)
    except Exception:
        return

    event = data.get("hook_event_name", "")

    try:
        from hive_bridge import log_task
    except ImportError:
        return

    # ── UserPromptSubmit: 사용자 지시 기록 ────────────────────────────
    if event == "UserPromptSubmit":
        prompt = (
            data.get("prompt")
            or data.get("content")
            or data.get("message", "")
        )
        if prompt and prompt.strip():
            short = prompt.strip().replace("\n", " ")[:120]
            log_task("사용자", f"[지시] {short}")

    # ── PreToolUse: 수정 시작 전 예고 로그 ────────────────────────────
    elif event == "PreToolUse":
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if tool_name == "Edit":
            fp = tool_input.get("file_path", "?")
            old = _snippet(tool_input.get("old_string", ""), 50)
            new = _snippet(tool_input.get("new_string", ""), 50)
            log_task("Claude", f"[수정 시작] {_short_path(fp)}\n  변경 전: {old}\n  변경 후: {new}")

        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            log_task("Claude", f"[파일 생성 시작] {_short_path(fp)}")

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if any(cmd.startswith(p) for p in _SKIP_BASH_PREFIXES):
                return
            if "git commit" in cmd:
                log_task("Claude", f"[커밋 시작] {_short_cmd(cmd)}")
            else:
                log_task("Claude", f"[명령 실행] {_short_cmd(cmd)}")

    # ── PostToolUse: 수정 완료 결과 로그 ──────────────────────────────
    elif event == "PostToolUse":
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if tool_name == "Edit":
            fp = tool_input.get("file_path", "?")
            log_task("Claude", f"[수정 완료] {_short_path(fp)} ✓")

        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            content = tool_input.get("content", "")
            lines = len(content.splitlines())
            log_task("Claude", f"[생성 완료] {_short_path(fp)} ({lines}줄) ✓")

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if any(cmd.startswith(p) for p in _SKIP_BASH_PREFIXES):
                return
            # 실행 결과 요약 (tool_response에서 출력 일부 추출)
            response = data.get("tool_response", {})
            output = ""
            if isinstance(response, dict):
                output = response.get("output") or response.get("stdout") or ""
            elif isinstance(response, str):
                output = response
            result_snippet = _snippet(output, 60) if output else ""
            suffix = f" → {result_snippet}" if result_snippet else " ✓"
            if "git commit" in cmd:
                log_task("Claude", f"[커밋 완료]{suffix}")
            else:
                log_task("Claude", f"[명령 완료] {_short_cmd(cmd, 50)}{suffix}")

        elif tool_name == "NotebookEdit":
            nb = tool_input.get("notebook_path", "?")
            log_task("Claude", f"[노트북 수정] {_short_path(nb)} ✓")

    # ── Stop: 응답 완료 구분선 ─────────────────────────────────────────
    elif event == "Stop":
        log_task("Claude", "─── 응답 완료 ───")


if __name__ == "__main__":
    main()
