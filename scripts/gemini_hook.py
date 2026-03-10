# -*- coding: utf-8 -*-
"""
FILE: scripts/gemini_hook.py
DESCRIPTION: Gemini CLI 전용 자동 액션 트레이스 훅 핸들러.
             AfterTool / SessionEnd 이벤트를 stdin JSON으로 수신하여
             hive_bridge.log_task()로 task_logs.jsonl에 자동 기록합니다.
             또한 세션 시작 시 대시보드 서버와 UI의 생존 여부를 확인하여 자동 실행합니다.

             [Claude의 hive_hook.py와의 차이점]
             Gemini CLI는 훅 스크립트의 stdout에 반드시 유효한 JSON만 출력해야 합니다.
             hive_bridge의 print() 출력이 stdout에 섞이면 Gemini가 훅 실패로 처리합니다.
             따라서 hive_bridge 호출 전에 sys.stdout을 sys.stderr로 교체하여
             내부 print 출력이 Gemini의 JSON 파싱에 영향을 미치지 않도록 합니다.

             [지원 이벤트]
             - AfterTool  : Gemini가 파일 수정/명령 실행 후 → "[수정]", "[실행]" 로그
             - SessionEnd : 세션 종료 시 → "─── 세션 종료 ───" 구분선

REVISION HISTORY:
- 2026-03-08 Gemini: 대시보드 서버(9570) 및 UI 자동 실행 보장 로직 추가
- 2026-03-01 Claude: BeforeAgent에 태스크 보드 자동 등록 추가
- 2026-03-01 Claude: Claude↔Gemini 양방향 메시지 연결 추가
- 2026-03-01 Claude: 파일 수정 내용 상세 기록 강화
- 2026-03-01 Claude: BeforeTool 이벤트 추가 — 도구 실행 직전 대시보드 표시로 공백 최소화
- 2026-03-01 Claude: 최초 구현 — Gemini CLI AfterTool/SessionEnd 자동 로깅 시스템 구축
"""

import sys
import json
import os
import io
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

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

# ── 자동 의도 감지 워크플로 맵 (Gemini용) ──────────────────────────────────────────────
_INTENT_MAP = [
    {
        "name": "bug_fix",
        "keywords": ["버그", "에러", "수정", "고쳐", "안돼", "안됨", "문제", "오류", "bug", "error", "fix"],
        "context": (
            "==================================================\n"
            "🚨 [자동 감지] 디버깅/자가 치유(Self-Healing) 워크플로\n"
            "==================================================\n"
            "사용자의 입력에서 버그/에러 수정 의도가 감지되었습니다.\n"
            "당신은 즉시 'systematic-debugging' 스킬을 가동해야 합니다.\n"
            "[행동 지침]\n"
            "1. 원인 분석 없이 묻지 마십시오. 스스로 memory.py와 task_logs.jsonl을 확인하세요.\n"
            "2. 코드를 수정한 후 반드시 백그라운드에서 코드를 실행/테스트하여 스스로 검증하세요.\n"
            "3. 에러가 나면 스스로 다시 고칩니다. 완벽히 동작할 때만 사용자에게 보고하세요.\n"
            "=================================================="
        ),
    },
    {
        "name": "new_feature",
        "keywords": ["추가", "만들어", "구현", "개발", "기능", "feature", "create", "make"],
        "context": (
            "==================================================\n"
            "✨ [자동 감지] 신규 기능 개발/브레인스토밍 워크플로\n"
            "==================================================\n"
            "사용자의 입력에서 새로운 기능 추가 의도가 감지되었습니다.\n"
            "당신은 즉시 'brainstorming' 및 'orchestrate' 스킬을 가동하여 설계를 시작해야 합니다.\n"
            "[행동 지침]\n"
            "1. 구현 전 ai_monitor_plan.md에 마이크로 태스크 계획을 작성하세요.\n"
            "2. 설계가 완료되면 스스로 TDD 방식으로 구현을 시작하세요.\n"
            "3. 구현 후 반드시 코드를 실행하여 검증하고, PROJECT_MAP.md에 기록하세요.\n"
            "=================================================="
        ),
    }
]

def _read_gemini_messages(agent_name: str) -> list[dict]:
    """PostgreSQL pg_messages에서 Gemini에게 온 미읽음 메시지를 가져옵니다.

    [변경 이력]
    - 2026-03-08 Claude: ITCP(itcp.py) 기반으로 전환
      이전: messages.jsonl 파일 직접 파싱 (동시 쓰기 충돌 위험)
      현재: PostgreSQL pg_messages 테이블 (원자적, 동시성 안전)
      Claude와 Gemini가 동일한 pg_messages 테이블을 공유하므로
      양방향 메시지 전달이 안정적으로 작동합니다.
    """
    try:
        import sys as _sys_i
        if _scripts_dir not in _sys_i.path:
            _sys_i.path.insert(0, _scripts_dir)
        from itcp import receive as _itcp_recv
        return _itcp_recv(agent_name, mark_read=True)
    except Exception:
        return []


def _send_session_summary() -> None:
    """SessionEnd 시 오늘 Gemini 활동 요약을 messages.jsonl에 기록합니다."""
    try:
        from pathlib import Path
        from datetime import datetime

        project_root = Path(_scripts_dir).parent
        data_dir = project_root / ".ai_monitor" / "data"
        logs_file = data_dir / "task_logs.jsonl"
        messages_file = data_dir / "messages.jsonl"

        if not logs_file.exists():
            return

        today = datetime.now().strftime("%Y-%m-%d")
        actions = []
        with open(logs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not entry.get("timestamp", "").startswith(today):
                    continue
                task = entry.get("task", "")
                agent = entry.get("agent", "")
                if agent == "Gemini" and any(k in task for k in ["수정 완료", "생성 완료", "커밋", "실행 완료"]):
                    actions.append(task)

        if not actions:
            return

        summary = "\n".join(actions[-10:])

        # ITCP를 통해 PostgreSQL pg_messages에 저장 (files.jsonl 폴백 자동 처리)
        # [변경 이력] 2026-03-08: messages.jsonl 직접 쓰기 → ITCP(pg_messages) 방식으로 전환
        try:
            import sys as _sys_i
            if _scripts_dir not in _sys_i.path:
                _sys_i.path.insert(0, _scripts_dir)
            from itcp import send as _itcp_send
            _itcp_send(
                from_terminal="gemini",
                to_terminal="claude",
                content=f"[Gemini 세션 종료 요약 {today}]\n{summary}",
                channel="hive",
                msg_type="session_summary",
            )
        except Exception:
            pass

    except Exception:
        pass


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

def _hook_response(decision="allow", context=None):
    """Gemini CLI 훅 응답 형식을 맞추어 출력합니다 (특히 BeforeAgent용)."""
    resp = {"decision": decision}
    if context:
        resp["hookSpecificOutput"] = {"additionalContext": context}
    _real_stdout.write(json.dumps(resp) + "\n")
    _real_stdout.flush()

def _send_heartbeat(status="active", task="Thinking..."):
    """서버에 현재 상태(활성)를 알려 대시보드에서 '유휴'로 표시되지 않도록 합니다."""
    import urllib.request
    import json
    try:
        data = json.dumps({"agent": "Gemini", "status": status, "task": task}).encode("utf-8")
        req = urllib.request.Request("http://localhost:9000/api/agents/heartbeat", data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=0.5)
    except Exception:
        pass

def _ensure_dashboard_running():
    """대시보드 서버(9570)와 UI가 실행 중인지 확인하고, 꺼져 있다면 자동 실행합니다.
    [체크 로직]
    1. localhost:9000/api/agents/heartbeat 호출 시도 (서버 생사 확인)
    2. 실패 시 server.py 실행
    3. UI 프로세스 존재 여부 확인 후 미실행 시 mission_control_ui.py 실행
    """
    import urllib.request
    import subprocess
    import os
    import time

    # 1. 서버 체크 (9000 포트는 심장 박동용 API)
    server_alive = False
    try:
        with urllib.request.urlopen("http://localhost:9000/api/agents/heartbeat", timeout=0.2) as response:
            if response.status == 200:
                server_alive = True
    except Exception:
        pass

    if not server_alive:
        # 서버가 꺼져 있으면 실행
        try:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _server_script = os.path.join(_root, ".ai_monitor", "server.py")
            # -X utf8 플래그로 인코딩 방어, 백그라운드 실행
            subprocess.Popen([sys.executable, "-X", "utf8", _server_script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            time.sleep(1) # 부팅 대기
        except Exception:
            pass

    # 2. UI 체크 및 실행
    try:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _ui_script = os.path.join(_root, ".ai_monitor", "mission_control_ui.py")
        subprocess.Popen([sys.executable, "-X", "utf8", _ui_script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except Exception:
        pass

def main():
    # ── 대시보드 자동 실행 보장 ────────────────────────────────────
    _ensure_dashboard_running()

    # ── 하트비트 전송 (제미나이가 살아있음을 알림) ────────────────────
    _send_heartbeat()

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

    # ── BeforeAgent (User Prompt Intent Detection + Claude 메시지 수신) ──
    if event == "BeforeAgent":
        prompt = data.get("prompt", "")
        additional_context = ""

        # [메시지 폴링] Claude가 보낸 미읽음 메시지 확인 후 컨텍스트에 추가
        unread = _read_gemini_messages("gemini")
        if unread:
            msg_lines = [
                f"📨 [{m.get('from','?')} → gemini] ({m.get('type','info')}) {m.get('content','')}".strip()
                for m in unread
            ]
            additional_context += "[Claude 메시지]\n" + "\n".join(msg_lines) + "\n\n"

        # 키워드 매칭으로 의도 파악
        for intent in _INTENT_MAP:
            for keyword in intent["keywords"]:
                if re.search(r"\b" + re.escape(keyword) + r"\b", prompt, re.IGNORECASE) or keyword in prompt:
                    additional_context += intent["context"]
                    break
            if additional_context and intent["context"] in additional_context:
                break

        # ── 태스크 보드 자동 등록 ──────────────────────────────────────────
        if prompt and prompt.strip():
            try:
                import datetime
                from src.pg_store import save_task
                _short = prompt.strip().replace("\n", " ")[:80]
                _new_task = {
                    "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "title": _short,
                    "description": prompt.strip()[:500],
                    "status": "in_progress",
                    "assigned_to": "gemini",
                    "priority": "medium",
                    "created_by": "user",
                    "created_at": datetime.datetime.now().isoformat(),
                }
                save_task(_new_task)
            except Exception:
                pass

        if additional_context:
            _hook_response(decision="allow", context=additional_context)
            try:
                from hive_bridge import log_task
                if unread:
                    log_task("Gemini-Hook", f"[메시지 수신] {len(unread)}개 읽음: {msg_lines[0][:60]}")
            except Exception:
                pass
        else:
            _hook_response(decision="allow")
        return

    # ── hive_bridge import (BeforeTool, AfterTool, SessionEnd) ──────
    try:
        from hive_bridge import log_task, log_thought
    except ImportError:
        _success_response()
        return

    # ── 이벤트별 처리 ──────────────────────────────────────────────────

    if event == "BeforeTool":
        tool_name = (data.get("tool_name") or data.get("tool") or data.get("name", ""))
        tool_input = (data.get("tool_input") or data.get("input") or data.get("args", {}))

        if tool_name in ("write_file", "create_file", "overwrite_file"):
            fp = _get_path(tool_input)
            content = tool_input.get("content") or tool_input.get("text") or ""
            preview = _snippet(content, 60) if content else "(내용 없음)"
            log_task("Gemini", f"[생성 시작] {_short_path(fp)}\n  내용 미리보기: {preview}")

        elif tool_name in ("replace", "edit_file", "str_replace"):
            fp = _get_path(tool_input)
            old = _snippet(tool_input.get("old_str") or tool_input.get("old_string") or tool_input.get("old") or "", 50)
            new = _snippet(tool_input.get("new_str") or tool_input.get("new_string") or tool_input.get("new") or tool_input.get("content") or "", 50)
            msg = f"[수정 시작] {_short_path(fp)}"
            if old: msg += f"\n  변경 전: {old}"
            if new: msg += f"\n  변경 후: {new}"
            log_task("Gemini", msg)

        elif tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
            cmd = (tool_input.get("command") or tool_input.get("cmd") or tool_input.get("code", "")).strip()
            if not any(cmd.startswith(p) for p in _SKIP_SHELL_PREFIXES):
                log_task("Gemini", f"[실행 준비] {_short_cmd(cmd)}")

    elif event == "AfterTool":
        tool_name = (data.get("tool_name") or data.get("tool") or data.get("name", ""))
        tool_input = (data.get("tool_input") or data.get("input") or data.get("args", {}))
        tool_result = (data.get("tool_result") or data.get("result") or data.get("output") or data.get("response") or {})
        result_text = ""
        if isinstance(tool_result, str):
            result_text = _snippet(tool_result, 60)
        elif isinstance(tool_result, dict):
            result_text = _snippet(tool_result.get("output") or tool_result.get("content") or tool_result.get("message") or str(tool_result), 60)

        if tool_name in ("write_file", "create_file", "overwrite_file"):
            fp = _get_path(tool_input)
            content = tool_input.get("content") or tool_input.get("text") or ""
            lines = len(content.splitlines()) if content else 0
            log_task("Gemini", f"[생성 완료] {_short_path(fp)} ({lines}줄) ✓")
            log_thought("gemini", "file-write", {
                "type": "action",
                "title": f"파일 생성: {_short_path(fp)}",
                "content": f"{lines}줄 작성. 미리보기: {_snippet(content, 80)}"
            })

        elif tool_name in ("replace", "edit_file", "str_replace"):
            fp = _get_path(tool_input)
            result_suffix = f" → {result_text}" if result_text else " ✓"
            log_task("Gemini", f"[수정 완료] {_short_path(fp)}{result_suffix}")
            log_thought("gemini", "file-edit", {
                "type": "action",
                "title": f"파일 수정: {_short_path(fp)}",
                "content": f"결과: {result_text or '성공'}"
            })

        elif tool_name in ("run_shell_command", "shell", "bash", "execute_command"):
            cmd = (tool_input.get("command") or tool_input.get("cmd") or tool_input.get("code", "")).strip()
            if any(cmd.startswith(p) for p in _SKIP_SHELL_PREFIXES):
                pass
            elif "git commit" in cmd:
                log_task("Gemini", f"[커밋] {_short_cmd(cmd)}")
                log_thought("gemini", "git", {
                    "type": "decision",
                    "title": "Git 커밋",
                    "content": _short_cmd(cmd)
                })
            else:
                result_suffix = f" → {result_text}" if result_text else " ✓"
                log_task("Gemini", f"[실행 완료] {_short_cmd(cmd, 50)}{result_suffix}")

    elif event == "SessionEnd":
        log_task("Gemini", "─── Gemini 세션 종료 ───")
        try:
            from src.pg_store import bulk_update_tasks
            bulk_update_tasks('gemini', ['pending', 'in_progress'], 'done')
        except Exception:
            pass
        _send_session_summary()

    _success_response()

if __name__ == "__main__":
    main()
