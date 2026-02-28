# -*- coding: utf-8 -*-
"""
FILE: scripts/gemini_hook.py
DESCRIPTION: Gemini CLI 전용 자동 액션 트레이스 훅 핸들러.
             AfterTool / SessionEnd 이벤트를 stdin JSON으로 수신하여
             hive_bridge.log_task()로 task_logs.jsonl에 자동 기록합니다.

             [Claude의 hive_hook.py와의 차이점]
             Gemini CLI는 훅 스크립트의 stdout에 반드시 유효한 JSON만 출력해야 합니다.
             hive_bridge의 print() 출력이 stdout에 섞이면 Gemini가 훅 실패로 처리합니다.
             따라서 hive_bridge 호출 전에 sys.stdout을 sys.stderr로 교체하여
             내부 print 출력이 Gemini의 JSON 파싱에 영향을 미치지 않도록 합니다.

             [지원 이벤트]
             - AfterTool  : Gemini가 파일 수정/명령 실행 후 → "[수정]", "[실행]" 로그
             - SessionEnd : 세션 종료 시 → "─── 세션 종료 ───" 구분선

REVISION HISTORY:
- 2026-03-01 Claude: 파일 수정 내용 상세 기록 강화
  - BeforeTool(수정): 변경 전/후 내용 스니펫 포함 (Claude PreToolUse와 동일 수준)
  - BeforeTool(생성): 파일 내용 미리보기 포함
  - AfterTool(수정): 수정 완료 + 결과 요약 포함
  - AfterTool(실행): 명령 완료 + 실행 결과 스니펫 포함
  - → 다른 CLI(Claude 등)가 Gemini 작업 의도·결과를 완전히 파악 가능
- 2026-03-01 Claude: BeforeTool 이벤트 추가 — 도구 실행 직전 대시보드 표시로 공백 최소화
- 2026-03-01 Claude: 최초 구현 — Gemini CLI AfterTool/SessionEnd 자동 로깅 시스템 구축
"""

import sys
import json
import os
import io

# ── [중요] stdout → stderr 교체 ────────────────────────────────────────────
# Gemini CLI는 훅 stdout의 JSON을 파싱함. hive_bridge의 print()가 섞이면 파싱 오류 발생.
# 실제 응답 출력은 _real_stdout에 보존하고, 내부 출력은 모두 stderr로 우회.
_real_stdout = sys.stdout
sys.stdout = sys.stderr  # hive_bridge 내부 print() → stderr로 리디렉션

# Windows UTF-8 인코딩 보정
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# scripts 디렉토리를 sys.path에 추가 (hive_bridge import용)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# 로깅 스킵 대상 — 단순 조회/노이즈 명령어 (Gemini CLI 기준)
_SKIP_SHELL_PREFIXES = (
    "ls ", "ls\n", "cat ", "head ", "tail ", "echo ",
    "pwd", "git status", "git log", "git diff",
    "python scripts/memory.py",
)


def _short_path(fp: str, depth: int = 3) -> str:
    """파일 경로를 마지막 N단계만 남겨 짧게 반환합니다."""
    parts = fp.replace("\\", "/").split("/")
    return "/".join(parts[-depth:]) if len(parts) >= depth else fp


def _short_cmd(cmd: str, max_len: int = 80) -> str:
    """명령어를 한 줄, max_len자 이내로 압축합니다."""
    return cmd.strip().replace("\n", " ")[:max_len]


def _snippet(text: str, max_len: int = 60) -> str:
    """긴 텍스트를 짧게 줄여 한 줄 스니펫으로 반환합니다.
    줄바꿈은 ↵로 치환하여 로그가 한 줄에 표시되도록 처리합니다."""
    if not text:
        return ""
    s = text.strip().replace("\n", "↵ ")
    return s[:max_len] + "…" if len(s) > max_len else s


def _get_path(tool_input: dict) -> str:
    """Gemini 버전에 따라 경로 필드명이 다를 수 있으므로 여러 키를 시도합니다."""
    return (
        tool_input.get("path")
        or tool_input.get("file_path")
        or tool_input.get("filename")
        or "?"
    )


def _success_response():
    """Gemini CLI가 기대하는 성공 JSON을 실제 stdout으로 출력합니다."""
    _real_stdout.write("{}\n")
    _real_stdout.flush()


def main():
    # ── stdin에서 훅 이벤트 JSON 수신 ──────────────────────────────────
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            _success_response()
            return
        data = json.loads(raw)
    except Exception:
        _success_response()
        return

    event = data.get("hook_event_name", "")

    # ── hive_bridge import ─────────────────────────────────────────────
    try:
        from hive_bridge import log_task
    except ImportError:
        _success_response()
        return

    # ── 이벤트별 처리 ──────────────────────────────────────────────────

    if event == "BeforeTool":
        # ── 도구 실행 직전: "어떤 파일을, 무슨 내용으로 바꿀지" 기록 ──────
        # Claude의 PreToolUse와 동일한 수준의 정보를 사전 공유.
        # 다른 CLI(Claude 등)가 Gemini의 작업 의도를 즉시 인지 가능.
        tool_name = (
            data.get("tool_name") or data.get("tool") or data.get("name", "")
        )
        tool_input = (
            data.get("tool_input") or data.get("input") or data.get("args", {})
        )

        if tool_name in ("write_file", "create_file", "overwrite_file"):
            # 파일 생성 — 파일명 + 첫 몇 줄 미리보기
            fp = _get_path(tool_input)
            content = tool_input.get("content") or tool_input.get("text") or ""
            preview = _snippet(content, 60) if content else "(내용 없음)"
            log_task("Gemini", f"[생성 시작] {_short_path(fp)}\n  내용 미리보기: {preview}")

        elif tool_name in ("replace", "edit_file", "str_replace"):
            # 파일 수정 — 파일명 + 변경 전/후 스니펫 (Claude PreToolUse와 동일 형식)
            fp = _get_path(tool_input)
            old = _snippet(
                tool_input.get("old_str") or tool_input.get("old_string")
                or tool_input.get("old") or "", 50
            )
            new = _snippet(
                tool_input.get("new_str") or tool_input.get("new_string")
                or tool_input.get("new") or tool_input.get("content") or "", 50
            )
            msg = f"[수정 시작] {_short_path(fp)}"
            if old:
                msg += f"\n  변경 전: {old}"
            if new:
                msg += f"\n  변경 후: {new}"
            log_task("Gemini", msg)

        elif tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
            cmd = (
                tool_input.get("command") or tool_input.get("cmd") or tool_input.get("code", "")
            ).strip()
            if not any(cmd.startswith(p) for p in _SKIP_SHELL_PREFIXES):
                log_task("Gemini", f"[실행 준비] {_short_cmd(cmd)}")

    elif event == "AfterTool":
        # ── 도구 실행 완료: "실제로 무엇이 바뀌었는지" 결과 기록 ──────────
        # tool_result 필드에서 성공/실패 및 변경 결과 추출.
        # 다른 CLI가 Gemini의 작업 완료 여부와 결과를 파악 가능.
        tool_name = (
            data.get("tool_name") or data.get("tool") or data.get("name", "")
        )
        tool_input = (
            data.get("tool_input") or data.get("input") or data.get("args", {})
        )
        # tool_result: Gemini CLI가 도구 실행 결과를 담는 필드 (버전별 다를 수 있음)
        tool_result = (
            data.get("tool_result") or data.get("result")
            or data.get("output") or data.get("response") or {}
        )
        result_text = ""
        if isinstance(tool_result, str):
            result_text = _snippet(tool_result, 60)
        elif isinstance(tool_result, dict):
            result_text = _snippet(
                tool_result.get("output") or tool_result.get("content")
                or tool_result.get("message") or str(tool_result), 60
            )

        if tool_name in ("write_file", "create_file", "overwrite_file"):
            fp = _get_path(tool_input)
            content = tool_input.get("content") or tool_input.get("text") or ""
            lines = len(content.splitlines()) if content else 0
            suffix = f" ({lines}줄 작성)" if lines else ""
            log_task("Gemini", f"[생성 완료] {_short_path(fp)}{suffix} ✓")

        elif tool_name in ("replace", "edit_file", "str_replace"):
            fp = _get_path(tool_input)
            # 수정 결과 — 성공 여부 + 결과 요약
            result_suffix = f" → {result_text}" if result_text else " ✓"
            log_task("Gemini", f"[수정 완료] {_short_path(fp)}{result_suffix}")

        elif tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
            cmd = (
                tool_input.get("command") or tool_input.get("cmd") or tool_input.get("code", "")
            ).strip()

            # 조회·노이즈 명령어 스킵
            if any(cmd.startswith(p) for p in _SKIP_SHELL_PREFIXES):
                pass
            elif "git commit" in cmd:
                log_task("Gemini", f"[커밋] {_short_cmd(cmd)}")
            else:
                result_suffix = f" → {result_text}" if result_text else " ✓"
                log_task("Gemini", f"[실행 완료] {_short_cmd(cmd, 50)}{result_suffix}")

        # read_file / glob / grep 등 조회 도구는 스킵

    elif event == "SessionEnd":
        # Gemini 세션 종료 — 구분선 기록
        log_task("Gemini", "─── Gemini 세션 종료 ───")

    # ── Gemini CLI가 요구하는 JSON 응답 출력 ───────────────────────────
    _success_response()


if __name__ == "__main__":
    main()
