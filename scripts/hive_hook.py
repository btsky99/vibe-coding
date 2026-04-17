# -*- coding: utf-8 -*-
"""
FILE: scripts/hive_hook.py
DESCRIPTION: Claude Code 자동 액션 트레이스 훅 핸들러.
             PreToolUse / PostToolUse / Stop / UserPromptSubmit 이벤트를 수신하여
             hive_bridge.log_task()로 task_logs.jsonl + hive_mind.db에 자동 기록합니다.

             [핵심 기능 — 자동 의도 감지 (Intent Detection)]
             UserPromptSubmit 이벤트 수신 시 사용자 프롬프트를 분석합니다.
             키워드 매칭으로 의도를 파악하고, 관련 워크플로 컨텍스트를 stdout에
             출력합니다. Claude Code는 이 출력을 Claude에게 시스템 컨텍스트로 전달하며
             Claude는 자동으로 올바른 워크플로를 실행합니다.

             [지원 이벤트]
             - UserPromptSubmit : 사용자 지시 기록 + 의도 감지 컨텍스트 주입
             - PreToolUse       : 수정 시작 전 "무엇을 어떻게 바꿀지" 예고 로그
             - PostToolUse      : 수정 완료 후 "실제로 무엇이 바뀌었는지" 결과 로그
             - Stop             : 응답 완료 구분선

REVISION HISTORY:
- 2026-03-01 Claude: Stop 이벤트 세션 자동 스냅샷 저장 추가
  - _save_session_snapshot(): 오늘 task_logs에서 사용자 지시 + 완료 액션 추출
  - shared_memory.db에 "claude:auto-session:YYYY-MM-DD" 키로 INSERT OR REPLACE
  - 다음 세션에서 이전 세션 활동을 즉시 확인 가능
- 2026-03-01 Claude: Gemini↔Claude 메시지 폴링 추가
  - read_messages(agent_name): messages.jsonl에서 미읽음 메시지 필터링 후 read_at 마킹
  - UserPromptSubmit 시 read_messages("claude") 호출 → 미읽음 메시지 stdout 출력
- 2026-03-01 Claude: AI 오케스트레이터 자동 트리거 추가
  - _INTENT_MAP 최상단에 "orchestrate" 의도 추가 (최고 우선순위)
  - 복잡도 감지: 여러 의도 동시 매칭 또는 "자동/전부/다/전체" 키워드 → orchestrate 강제
  - /vibe-orchestrate 스킬로 스킬 체인 자동 수립·실행 지시
- 2026-03-01 Claude: 빌드 워크플로에 Inno Setup Step3 추가 + 확인 없이 자동 실행 지시
  - Step3 = Inno Setup (ISCC.exe) 설치버전 빌드 추가 (dist/vibe-coding-setup-X.Y.Z.exe)
  - ISCC.exe 경로: C:/Users/com/AppData/Local/Programs/Inno Setup 6/ISCC.exe
  - "중간에 묻지 말 것" 지시로 완전 자동 실행 강제
- 2026-03-01 Claude: 빌드 워크플로에 Step3(git commit+push) 추가 + 스킬 자동 실행 지시
  - build_exe: npm build → pyinstaller → git commit+push 전체 사이클로 확장
  - 각 의도에 "즉시 /vibe-XXX 스킬을 실행하세요" 지시 추가
  - Claude가 컨텍스트 수신 즉시 스킬 도구를 호출하도록 강제
- 2026-03-01 Claude: 자동 의도 감지(Intent Detection) 시스템 추가
  - UserPromptSubmit에서 키워드 분석 → 워크플로 컨텍스트 stdout 주입
  - 지원 의도: 빌드(EXE/프론트엔드), 커밋/푸시, 코드리뷰, 디버그, 테스트
  - stdout 출력 → Claude Code가 Claude에게 시스템 컨텍스트로 전달
  - 사용자가 매번 설명 없이 자연어 지시만으로 자동 워크플로 실행 가능
- 2026-03-07 Claude: [Phase7] Harness 패턴 이식 — Auto-Stop + UserPromptSubmit 검증 연동
  - Stop 이벤트: plan_validator.check_all_done() → 모든 [x] 시 {"continue": false} 출력
  - UserPromptSubmit: "계획 실행" 키워드 감지 시 plan_validator 자동 실행 후 결과 주입
- 2026-03-01 Claude: 최초 구현 — 자동 하이브 마인드 액션 트레이스 시스템 구축
- 2026-03-01 Claude: PreToolUse 추가 + PostToolUse에 실제 변경 내용(old→new) 포함
"""

import sys
import json
import os
import io
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

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

# 터미널 ID — hook_bridge.py와 동일한 환경변수 사용 (T1~T8, 기본 T0)
# 각 터미널에서 `set TERMINAL_ID=T1 && claude` 형태로 실행하면 자동 추적
_TERMINAL_ID = os.environ.get('TERMINAL_ID', 'T0')

# ── Self-Reflect 세션 추적 변수 ────────────────────────────────────────────
# Stop 이벤트 시 pg_thoughts에 자기반성 기록에 사용 (세션 단위 누적)
_SESSION_MODIFIED_FILES: list = []   # PostToolUse에서 수정된 파일 경로 누적
_SESSION_LAST_TASK: str = ""         # UserPromptSubmit에서 마지막 지시 내용
_SESSION_HAD_ERROR: bool = False     # Stop reason이 error이면 True

# 단순 조회 명령어 스킵 목록
_SESSION_ASSIGNED_TASKS: list = []
_SESSION_REVIEW_REQUESTS: list = []

_SKIP_BASH_PREFIXES = (
    "ls ", "ls\n", "cat ", "head ", "tail ", "echo ",
    "pwd", "git status", "git log", "git diff",
    "python scripts/memory.py",
    "python D:/vibe-coding/scripts/memory.py",
    "python D:/vibe-coding/scripts/hive_hook.py",  # 훅 자체 재귀 방지
)

# ── 자동 의도 감지 워크플로 맵 (intent_map.py에서 로드) ──────────────────────
from intent_map import INTENT_MAP as _INTENT_MAP


def _update_pipeline_stage(stage: str, task: str = '') -> None:
    """서버 API를 통해 이 대화형 세션의 파이프라인 단계를 실시간 업데이트합니다.

    [동작]
    - POST /api/agent/stage 호출 → agent_api._interactive_stages 업데이트
    - 모니터링 패널(TerminalSlot)에서 현재 단계가 실시간으로 표시됨
    - 단계: analyzing(사용자 지시 접수) → modifying(파일 수정) → verifying(후처리) → done(완료)

    [에러 시] 서버 미실행 등 예외는 조용히 무시 (훅 자체를 방해하지 않음)
    """
    try:
        import urllib.request as _req
        from datetime import datetime as _dt
        # cli 타입을 함께 전송 — backend가 에이전트 종류를 정확히 식별하기 위함
        # [2026-03-08] Codex가 T3 슬롯에서 claude 타입으로 잘못 표시되던 버그 수정
        _cli_type = os.environ.get('VIBE_CLI_TYPE', 'claude')  # codex_wrapper.py 등이 설정
        payload = json.dumps({
            'terminal_id': _TERMINAL_ID,
            'stage': stage,
            'task': task[:120] if task else '',
            'cli': _cli_type,
        }).encode('utf-8')
        req = _req.Request(
            'http://localhost:9000/api/agent/stage',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        _req.urlopen(req, timeout=1)
    except Exception:
        pass  # 서버 미실행 시 조용히 무시


def _save_session_snapshot() -> None:
    """Stop 이벤트 시 오늘의 세션 활동을 메모리 저장소에 자동 저장합니다."""
    try:
        from datetime import datetime
        from src.pg_store import set_memory

        project_root = Path(_scripts_dir).parent
        logs_file = project_root / ".ai_monitor" / "data" / "task_logs.jsonl"
        if not logs_file.exists():
            return

        today = datetime.now().strftime("%Y-%m-%d")
        important_lines = []
        with open(logs_file, "r", encoding="utf-8") as handle:
            for line in handle:
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
                if agent == "사용자" and "[지시]" in task:
                    important_lines.append(task)
                elif agent == "Claude" and any(keyword in task for keyword in ["수정 완료", "생성 완료", "커밋 완료"]):
                    important_lines.append(task)

        if not important_lines:
            return

        now = datetime.now().isoformat()
        set_memory(
            key=f"claude:auto-session:{today}",
            title=f"[자동] Claude 세션 활동 요약 ({today})",
            content="\n".join(important_lines[-20:]),
            tags=["auto", "session", "claude", "snapshot"],
            author="claude",
            project="vibe-coding",
            created_at=now,
            updated_at=now,
        )
    except Exception:
        pass


def _inject_hive_context() -> str:
    """UserPromptSubmit 시 하이브 메모리에서 현재 작업 컨텍스트를 자동 주입합니다."""
    try:
        from datetime import datetime
        from src.pg_store import get_memory, list_memory

        rows = [row for row in list_memory(top_k=20, show_all=True) if str(row.get('key', '')).endswith(':current-work')]
        current_work = rows[0]["content"] if rows else ""

        today = datetime.now().strftime("%Y-%m-%d")
        today_row = get_memory(f"claude:auto-session:{today}")
        today_snap = today_row.get("content", "") if today_row else ""

        parts = []
        if current_work:
            lines = [line for line in current_work.split("\n") if line.strip()]
            todo_lines = [line for line in lines if "[ ]" in line or "진행 상황" in line or "🔄" in line]
            summary = "\n".join(todo_lines[:10]) if todo_lines else "\n".join(lines[:8])
            parts.append(f"[하이브 현재 작업 상태]\n{summary}")

        if today_snap:
            parts.append(f"[오늘 완료 항목]\n" + "\n".join(today_snap.strip().split("\n")[-5:]))

        if not parts:
            return ""

        return (
            "[INFO] 하이브 컨텍스트 자동 로드됨. 아래 내용을 바탕으로 작업 맥락을 파악하세요.\n"
            + "\n\n".join(parts)
            + "\n[END 하이브 컨텍스트]"
        )
    except Exception:
        return ""


def _update_current_work(completed_items: list[str]) -> None:
    """Stop 이벤트 시 오늘 완료된 항목을 current-work 메모리에 자동 반영합니다."""
    try:
        from datetime import datetime
        from src.pg_store import list_memory, set_memory

        if not completed_items:
            return

        rows = [row for row in list_memory(top_k=20, show_all=True) if str(row.get('key', '')).endswith(':current-work')]
        if not rows:
            return

        key = rows[0]["key"]
        content = rows[0]["content"]
        completed_block = f"\n## 자동 업데이트 ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n" + "\n".join(
            f"- [x] {item}" for item in completed_items[-10:]
        )
        set_memory(
            key=key,
            title=rows[0].get("title", key),
            content=content + completed_block,
            tags=rows[0].get("tags", []),
            author=rows[0].get("author", "claude"),
            project=rows[0].get("project", "vibe-coding"),
            created_at=rows[0].get("created_at", ""),
            updated_at=datetime.now().isoformat(),
        )
    except Exception:
        pass


def _read_messages(agent_name: str) -> list[dict]:
    """PostgreSQL pg_messages에서 나(agent_name)에게 온 미읽음 메시지를 가져옵니다.

    [변경 이력]
    - 2026-03-08 Claude: ITCP(itcp.py) 기반으로 전환
      이전: messages.jsonl 파일 직접 파싱 (동시 쓰기 충돌 위험)
      현재: PostgreSQL pg_messages 테이블 (원자적, 동시성 안전)

    [동작 순서]
    1. itcp.receive(agent_name) 호출 → pg_messages에서 미읽음 메시지 조회
    2. PostgreSQL 미실행 시 messages.jsonl 폴백 자동 처리 (itcp 내부에서 처리)
    3. 조회한 메시지를 is_read=true로 업데이트 (이중 수신 방지)
    4. 읽은 메시지 목록 반환

    [파일 없거나 에러 시]
    빈 리스트 반환 — 훅 실행을 중단하지 않음
    """
    try:
        # itcp 모듈 동적 임포트 (scripts/ 디렉토리에 위치)
        import sys as _sys_itcp
        if _scripts_dir not in _sys_itcp.path:
            _sys_itcp.path.insert(0, _scripts_dir)
        from itcp import receive as _itcp_receive
        # [2026-03-18 Claude] 터미널 ID 전달 — 같은 에이전트 간 자기 메시지 제외
        # T1의 Claude가 보낸 메시지를 T1이 다시 읽는 문제 방지
        return _itcp_receive(agent_name, mark_read=True, my_terminal_id=_TERMINAL_ID)
    except Exception:
        return []


def _remember_itcp_work_items(messages: list[dict]) -> None:
    """Track real dispatch/review work items seen in the Claude inbox."""
    global _SESSION_ASSIGNED_TASKS, _SESSION_REVIEW_REQUESTS
    try:
        from itcp import parse_task_reference as _parse_task_reference
    except Exception:
        return

    for message in messages:
        ref = _parse_task_reference(message)
        task_id = ref.get("task_id", "")
        if not task_id:
            continue
        if ref.get("kind") == "review":
            if not any(item.get("task_id") == task_id for item in _SESSION_REVIEW_REQUESTS):
                _SESSION_REVIEW_REQUESTS.append(ref)
        elif ref.get("kind") == "task":
            if not any(item.get("task_id") == task_id for item in _SESSION_ASSIGNED_TASKS):
                _SESSION_ASSIGNED_TASKS.append(ref)


def _report_completed_itcp_work(agent_name: str) -> None:
    """Emit task result / verify result messages for actual assigned work."""
    global _SESSION_ASSIGNED_TASKS, _SESSION_REVIEW_REQUESTS
    if _SESSION_HAD_ERROR:
        return

    summary_bits = []
    if _SESSION_LAST_TASK:
        summary_bits.append(_SESSION_LAST_TASK[:120])
    if _SESSION_MODIFIED_FILES:
        summary_bits.append("files=" + ", ".join(_SESSION_MODIFIED_FILES[-5:]))
    summary = " | ".join(summary_bits) if summary_bits else "session completed"

    try:
        from auto_dispatcher import (
            report_task_completion as _report_task_completion,
            report_verification_result as _report_verification_result,
        )
    except Exception:
        return

    while _SESSION_ASSIGNED_TASKS:
        ref = _SESSION_ASSIGNED_TASKS.pop(0)
        task_id = ref.get("task_id", "")
        if task_id:
            _report_task_completion(task_id=task_id, author=agent_name, result_summary=summary)

    while _SESSION_REVIEW_REQUESTS:
        ref = _SESSION_REVIEW_REQUESTS.pop(0)
        task_id = ref.get("task_id", "")
        if task_id:
            _report_verification_result(
                task_id=task_id,
                reviewer=agent_name,
                summary=summary,
                verdict="approved",
                author=ref.get("author", ""),
            )


def _check_and_install_skills() -> list[str]:
    """Claude Code 스킬 자동 설치 — UserPromptSubmit마다 실행.

    [동작 원리 — Skills 2.0]
    1. scripts/ 기준으로 프로젝트 루트 탐지
    2. 스킬 소스 탐색:
       - frozen(배포): sys._MEIPASS/claude_skills/<name>/SKILL.md
       - dev(개발): PROJECT_ROOT/.claude/skills/<name>/SKILL.md (소스=대상 → 복사 불필요)
    3. 누락된 스킬 디렉토리를 .claude/skills/<name>/에 자동 복사
    4. 설치된 스킬 이름 목록 반환 (로깅용)

    [자기치유]
    스킬이 삭제되거나 새 스킬이 추가되어도 다음 사용자 입력 시 자동 복구됨.
    """
    installed = []
    try:
        import shutil
        import sys
        from pathlib import Path

        # 프로젝트 루트: scripts/hive_hook.py 기준 상위 폴더
        project_root = Path(_scripts_dir).parent

        # 소스 경로: frozen → sys._MEIPASS/claude_skills/, dev → .claude/skills/
        if getattr(sys, 'frozen', False):
            skills_src = Path(sys._MEIPASS) / 'claude_skills'
        else:
            skills_src = project_root / '.claude' / 'skills'

        if not skills_src.exists():
            return []

        skills_dst = project_root / '.claude' / 'skills'

        # 소스와 대상이 같으면 (개발 환경) 복사 불필요
        if skills_src.resolve() == skills_dst.resolve():
            return []

        skills_dst.mkdir(parents=True, exist_ok=True)

        # 소스 내 각 스킬 디렉토리 순회 → 누락된 것만 복사
        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir() or not (skill_dir / 'SKILL.md').exists():
                continue
            target = skills_dst / skill_dir.name
            if not target.exists():
                shutil.copytree(str(skill_dir), str(target))
                installed.append(skill_dir.name)

    except Exception:
        pass

    return installed


def _detect_intent(prompt: str) -> str | None:
    """사용자 프롬프트에서 워크플로 의도를 감지하고 컨텍스트 문자열을 반환합니다.

    [매칭 방식 — 2단계 감지]
    1단계) 복잡도 감지: 여러 의도가 동시에 매칭되면 orchestrate 강제 적용
       - build + debug, debug + test 등 복합 요청은 오케스트레이터로 위임
    2단계) 단순 의도 감지: _INTENT_MAP 순서대로 첫 번째 매칭 반환

    [orchestrate 우선순위]
    - _INTENT_MAP[0] = orchestrate (키워드 우선 매칭)
    - 2개 이상 의도 동시 매칭 → orchestrate 자동 전환
    """
    prompt_lower = prompt.lower()

    # 1단계: 복잡도 감지 — 2개 이상의 서로 다른 의도(orchestrate 제외)가 동시 매칭되면
    # 복합 요청으로 판단하고 orchestrate 컨텍스트 반환
    matched_intents = []
    orchestrate_ctx = None
    for intent in _INTENT_MAP:
        if intent["name"] == "orchestrate":
            orchestrate_ctx = intent["context"]
            continue  # orchestrate는 1단계에서 제외하고 카운트만
        for kw in intent["keywords"]:
            if kw.lower() in prompt_lower:
                if intent["name"] not in matched_intents:
                    matched_intents.append(intent["name"])
                break

    # 서로 다른 의도 2개 이상 → 복합 요청 → orchestrate 강제
    if len(matched_intents) >= 2 and orchestrate_ctx:
        return orchestrate_ctx

    # 2단계: 단순 의도 감지 — _INTENT_MAP 순서대로 첫 번째 매칭 반환 (orchestrate 포함)
    for intent in _INTENT_MAP:
        for kw in intent["keywords"]:
            if kw.lower() in prompt_lower:
                return intent["context"]

    return None


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
    # 오피스 세션(OFFICE_MODE=true)에서는 hook 비활성화 — 대화형 세션이므로
    if os.environ.get('OFFICE_MODE') == 'true':
        return

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
        log_task = None

    # ── UserPromptSubmit: 스킬 자동 설치 + 사용자 지시 기록 + 의도 감지 ────
    if event == "UserPromptSubmit":
        # [자기치유] 누락된 Claude Code 스킬 자동 감지 및 설치
        # 매 사용자 입력 시 skills/claude/와 .claude/commands/ 비교 → 자동 동기화
        newly_installed = _check_and_install_skills()
        if newly_installed and log_task:
            log_task("Hive", f"[자기치유] 스킬 자동 설치: {', '.join(newly_installed)}", _TERMINAL_ID)

        # [하네스 V2 자동 검증] 매 세션 시작 시 하네스 상태를 자동 체크
        # harness_verify.py를 실행하여 에러/경고를 Claude 컨텍스트에 주입
        # → "규칙서만 있고 심판이 없는" 상태 방지 (HARNESS_V2 세션 프로토콜 강제)
        try:
            import subprocess as _sp_harness
            _harness_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harness_verify.py')
            if os.path.exists(_harness_script):
                _no_win_h = getattr(_sp_harness, 'CREATE_NO_WINDOW', 0x08000000)
                _harness_r = _sp_harness.run(
                    [sys.executable, _harness_script, '--json'],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace',
                    timeout=10,
                    creationflags=_no_win_h
                )
                if _harness_r.returncode == 0:
                    # 하네스 정상 — 간결한 상태만 표시
                    try:
                        _h_data = json.loads(_harness_r.stdout)
                        _h_summary = _h_data.get("summary", {})
                        _h_warns = _h_data.get("details", {}).get("warnings", [])
                        _h_msg = f"[HARNESS V2] status=ok ({_h_summary.get('passes', 0)} checks passed"
                        if _h_warns:
                            _h_msg += f", {len(_h_warns)} warnings)"
                        else:
                            _h_msg += ")"
                        print(_h_msg, flush=True)
                    except json.JSONDecodeError:
                        pass
                else:
                    # 하네스 실패 — 에러 상세를 Claude에게 전달
                    try:
                        _h_data = json.loads(_harness_r.stdout)
                        _h_errors = _h_data.get("details", {}).get("errors", [])
                        _h_warns = _h_data.get("details", {}).get("warnings", [])
                        _h_lines = ["⚠️ [HARNESS V2] status=FAIL — 작업 전 하네스 수정 필요:"]
                        for e in _h_errors:
                            _h_lines.append(f"  FAIL {e}")
                        for w in _h_warns[:3]:  # 경고는 최대 3개만
                            _h_lines.append(f"  WARN {w}")
                        print("\n".join(_h_lines), flush=True)
                    except json.JSONDecodeError:
                        print(f"⚠️ [HARNESS V2] 검증 실패 (파싱 오류)", flush=True)
        except Exception:
            pass  # 하네스 검증 실패는 훅 전체를 중단하지 않음

        # ── [2026-04-14] 중단 세션 복구 브리핑 ──────────────────────────────
        # 이전 세션이 비정상 종료(Stop 없이 끝남)되었으면 미완료 작업 브리핑 자동 출력.
        # 매 프롬프트마다 active_session_context를 확인하여 중단된 세션이 있는지 감지.
        try:
            from src.pg_store import get_interrupted_sessions, complete_active_session
            _interrupted = get_interrupted_sessions()
            if _interrupted:
                _resume_lines = ["🔄 [세션 복구] 이전에 중단된 작업이 감지되었습니다:"]
                for _sess in _interrupted:
                    _task = _sess.get('task_summary', '(알 수 없음)')
                    _files_raw = _sess.get('modified_files', '[]')
                    try:
                        _files = json.loads(_files_raw) if isinstance(_files_raw, str) else _files_raw
                    except Exception:
                        _files = []
                    _tid = _sess.get('terminal_id', '?')
                    _updated = _sess.get('updated_at', '')
                    _resume_lines.append(f"  [{_tid}] 작업: {_task}")
                    if _files:
                        _resume_lines.append(f"       수정 파일: {', '.join(_files[:8])}")
                    _resume_lines.append(f"       마지막 활동: {_updated}")
                    # 이전 세션은 '중단'으로 마킹 (중복 브리핑 방지)
                    complete_active_session(_sess.get('terminal_id', ''))
                # uncommitted git 변경도 함께 표시
                try:
                    import subprocess as _sp_git
                    _no_win = getattr(_sp_git, 'CREATE_NO_WINDOW', 0x08000000)
                    _git_r = _sp_git.run(
                        ['git', 'diff', '--stat', '--no-color'],
                        capture_output=True, text=True, encoding='utf-8', errors='replace',
                        timeout=5, cwd=str(ROOT_DIR), creationflags=_no_win,
                    )
                    if _git_r.returncode == 0 and _git_r.stdout.strip():
                        _resume_lines.append(f"  📂 커밋 안 된 변경:")
                        for _gl in _git_r.stdout.strip().split('\n')[:8]:
                            _resume_lines.append(f"       {_gl.strip()}")
                except Exception:
                    pass
                _resume_lines.append("⚠️  이전 작업을 이어서 진행할지, 새 작업을 시작할지 사용자에게 확인하세요.")
                print("\n".join(_resume_lines), flush=True)
                if log_task:
                    log_task("Hive", f"[세션 복구] 중단 세션 {len(_interrupted)}건 감지 → 브리핑 완료", _TERMINAL_ID)
        except Exception:
            pass  # 복구 실패는 훅 흐름 차단 안 함

        # [하이브 컨텍스트 자동 주입] 작업 시작 전 current-work + 오늘 활동 자동 로드
        # → Claude가 매번 수동으로 memory.py list를 실행하지 않아도 항상 컨텍스트 보유
        hive_ctx = _inject_hive_context()
        if hive_ctx:
            print(hive_ctx, flush=True)
            if log_task:
                log_task("Hive", "[하이브 컨텍스트] 자동 주입 완료 — current-work + 오늘 활동", _TERMINAL_ID)

        # [2026-03-22] Self-Reflect 주입 제거 (pg_thoughts 삭제됨)

        # [ITCP 메시지 폴링] PostgreSQL pg_messages에서 Claude에게 온 미읽음 메시지 수신
        # Gemini, Codex 등 다른 터미널 에이전트가 보낸 메시지를 자동으로 컨텍스트에 주입
        # [2026-03-08] ITCP(itcp.py) 기반으로 전환 — PostgreSQL pg_messages FIRST
        unread = _read_messages("claude")
        if unread:
            _remember_itcp_work_items(unread)
            # 채널별 이모지 매핑 — 메시지 유형을 시각적으로 구분
            _CHANNEL_EMOJI = {
                "debug": "🐛", "task": "📋", "review": "🔍",
                "broadcast": "📢", "hive": "🧠", "general": "💬",
            }
            lines = []
            for m in unread:
                emoji = _CHANNEL_EMOJI.get(m.get('channel', 'general'), '📨')
                from_a = m.get('from_agent', m.get('from', '?'))
                ch = m.get('channel', 'general')
                content = m.get('content', '')
                lines.append(f"{emoji} [{from_a} → claude] ({ch}) {content}")
            print("[ITCP 수신 메시지] 다른 에이전트에서 온 메시지:\n" + "\n".join(lines), flush=True)
            if log_task:
                log_task("Hive", f"[ITCP 메시지 수신] {len(unread)}개: {lines[0][:60]}", _TERMINAL_ID)

        prompt = (
            data.get("prompt")
            or data.get("content")
            or data.get("message", "")
        )
        if prompt and prompt.strip():
            short = prompt.strip().replace("\n", " ")[:120]
            if log_task:
                log_task("사용자", f"[지시] {short}", _TERMINAL_ID)

            # self-reflect: 새 지시 시작 시 마지막 지시 + 파일 목록 리셋
            global _SESSION_LAST_TASK, _SESSION_MODIFIED_FILES, _SESSION_HAD_ERROR, _SESSION_ASSIGNED_TASKS, _SESSION_REVIEW_REQUESTS
            _SESSION_LAST_TASK = short
            _SESSION_MODIFIED_FILES = []
            _SESSION_HAD_ERROR = False
            _SESSION_ASSIGNED_TASKS = []
            _SESSION_REVIEW_REQUESTS = []

            # ── [2026-04-14] 활성 세션 컨텍스트 기록 ──────────────────────────
            # 매 지시마다 DB에 현재 작업 상태를 기록 → 튕겨도 마지막 상태가 남아있음
            try:
                from src.pg_store import upsert_active_session
                upsert_active_session(
                    terminal_id=_TERMINAL_ID,
                    agent_id='claude',
                    task_summary=short,
                    modified_files=[],  # 새 지시 시작 → 파일 목록 리셋
                )
            except Exception:
                pass  # DB 기록 실패는 훅 흐름 차단 안 함

            # [파이프라인 단계 업데이트] 사용자 지시 수신 → "분석" 단계 표시
            _update_pipeline_stage('analyzing', short)

            # ── 태스크 보드 자동 등록 ──────────────────────────────────────────
            # 사용자 지시가 들어올 때마다 tasks.json에 pending 태스크로 추가합니다.
            # 에이전트가 작업을 시작하면 in_progress, 완료 시 done으로 상태를 변경할 수 있습니다.
            try:
                import datetime
                from src.pg_store import save_task
                # 새 태스크 항목 구성 — 대시보드 TasksPanel이 기대하는 형식 그대로 사용
                _new_task = {
                    "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "title": short[:80],
                    "description": prompt.strip()[:500],
                    "status": "in_progress",  # 지시 수신 즉시 작업 시작
                    "assigned_to": "claude",
                    "priority": "medium",
                    "created_by": "user",
                    "created_at": datetime.datetime.now().isoformat(),
                }
                save_task(_new_task)
            except Exception:
                pass  # 태스크 보드 기록 실패는 조용히 무시 (훅 자체가 중단되면 안 됨)

            # ── Plan Validator 자동 연동 (Harness 패턴) ──────────────────────
            # "계획 실행", "execute-plan", "실행해줘" 등 실행 키워드 감지 시
            # plan_validator.py를 자동 실행하여 V1-V5 결과를 컨텍스트로 주입.
            # 검증 실패 시 Claude에게 경고 → 불완전한 계획 실행 방지.
            _EXECUTE_KEYWORDS = [
                "계획 실행", "execute-plan", "실행해줘", "플랜 실행",
                "plan 실행", "vibe-execute", "계획대로", "진행해줘", "진행해"
            ]
            if any(kw in prompt for kw in _EXECUTE_KEYWORDS):
                try:
                    import subprocess as _sp_val
                    _plan_f = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), '..', 'ai_monitor_plan.md'
                    )
                    _val_script = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), 'plan_validator.py'
                    )
                    if os.path.exists(_val_script) and os.path.exists(_plan_f):
                        _no_win = getattr(_sp_val, 'CREATE_NO_WINDOW', 0x08000000)
                        _val_r = _sp_val.run(
                            [sys.executable, _val_script, _plan_f],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            creationflags=_no_win
                        )
                        # ANSI 코드 제거 후 출력 (Claude가 읽기 쉽게)
                        import re as _re_ansi
                        _ansi_re = _re_ansi.compile(r'\x1b\[[0-9;]*m')
                        _val_out = _ansi_re.sub('', _val_r.stdout).strip()
                        if _val_out:
                            _prefix = "⚠️ [계획 검증 경고]" if _val_r.returncode > 0 else "[계획 검증]"
                            print(f"{_prefix}\n{_val_out}", flush=True)
                except Exception:
                    pass  # validator 오류는 조용히 무시

            # ── 경험 회상 자동 주입 ──────────────────────────────────────────
            # 사용자 지시와 유사한 과거 작업 경험을 자동 검색하여 컨텍스트에 주입.
            # 에이전트가 과거 경험을 활용해 더 나은 판단을 할 수 있도록 한다.
            try:
                from src.pg_store import recall_context_summary
                _recall_text = recall_context_summary(short, limit=3)
                if _recall_text:
                    print(_recall_text, flush=True)
            except Exception:
                pass  # 회상 실패는 훅 전체를 중단하지 않음

            # ── C.2 지식 회상 자동 주입 (zettel + hive) ─────────────────────
            # 작업 결과(agent_experience)와 별개로, 누적된 정제 지식을 함께 주입.
            # 에이전트가 과거 합의/가이드/학습 내용을 세션 첫 턴부터 참조 가능.
            try:
                from src.pg_store import recall_knowledge_summary
                _know_text = recall_knowledge_summary(short, limit=3)
                if _know_text:
                    print(_know_text, flush=True)
            except Exception:
                pass  # 지식 회상 실패도 훅 전체를 중단하지 않음

            # 의도 감지: 키워드 매칭 → 관련 워크플로 컨텍스트를 stdout으로 출력
            # Claude Code는 이 출력을 Claude에게 시스템 컨텍스트로 주입함
            # 사용자가 자연어로 "빌드해줘", "커밋해줘" 등만 말해도 자동 워크플로 실행 가능
            intent_context = _detect_intent(prompt)
            if intent_context:
                print(intent_context, flush=True)

    # ── PreToolUse: 수정 시작 전 예고 로그 ────────────────────────────
    elif event == "PreToolUse":
        if log_task is None:
            return
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if tool_name == "Edit":
            fp = tool_input.get("file_path", "?")
            old = _snippet(tool_input.get("old_string", ""), 50)
            new = _snippet(tool_input.get("new_string", ""), 50)
            log_task("Claude", f"[수정 시작] {_short_path(fp)}\n  변경 전: {old}\n  변경 후: {new}", _TERMINAL_ID)
            # [파이프라인 단계] 파일 수정 시작 → "수정" 단계 표시
            _update_pipeline_stage('modifying', f'수정 중: {_short_path(fp)}')

        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            log_task("Claude", f"[파일 생성 시작] {_short_path(fp)}", _TERMINAL_ID)
            # [파이프라인 단계] 파일 생성 시작 → "수정" 단계 표시
            _update_pipeline_stage('modifying', f'생성 중: {_short_path(fp)}')

        elif tool_name in ("Read", "Glob", "Grep", "Search", "Agent"):
            # [파이프라인 단계] 파일 읽기/검색 → "분석" 단계 표시
            # 수정 후 다시 파일을 읽는 경우에도 정확히 "분석"으로 돌아감
            fp = tool_input.get("file_path") or tool_input.get("pattern") or tool_input.get("path") or ""
            _update_pipeline_stage('analyzing', f'분석 중: {_short_path(fp)}' if fp else '분석 중')

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if any(cmd.startswith(p) for p in _SKIP_BASH_PREFIXES):
                return

            # [파이프라인 단계] 명령 실행 → "검증" 단계 표시
            # Bash 도구는 테스트/빌드/검증 목적으로 사용되므로 verifying 단계로 전환
            _update_pipeline_stage('verifying', f'검증 중: {_short_cmd(cmd, 40)}')

            # ── Bounded Autonomy: 위험 명령 사전 차단 ────────────────────
            try:
                import sys as _sys_sg
                _sg_dir = os.path.dirname(os.path.abspath(__file__))
                if _sg_dir not in _sys_sg.path:
                    _sys_sg.path.insert(0, _sg_dir)
                from safety_guard import check as _sg_check, warn as _sg_warn
                _safe, _reason = _sg_check(cmd)
                if not _safe:
                    # 차단: pg_logs에 BLOCKED 기록 + 경고 출력
                    log_task("Claude", f"[BLOCKED] {_reason}: {_short_cmd(cmd)}", _TERMINAL_ID, "blocked")
                    print(f"\n⚠️  [Bounded Autonomy] 위험 명령 차단: {_reason}\n명령: {cmd[:80]}", flush=True)
                    import sys as _sys_exit
                    _sys_exit.exit(2)  # PreToolUse exit(2) = 도구 실행 차단
                _warn_msg = _sg_warn(cmd)
                if _warn_msg:
                    print(f"⚠️  [경고] {_warn_msg}", flush=True)
            except SystemExit:
                raise  # exit(2) 재전파
            except Exception:
                pass  # safety_guard 오류는 무시 (보수적 접근)

            if "git commit" in cmd:
                log_task("Claude", f"[커밋 시작] {_short_cmd(cmd)}", _TERMINAL_ID)
            else:
                log_task("Claude", f"[명령 실행] {_short_cmd(cmd)}", _TERMINAL_ID)

    # ── PostToolUse: 수정 완료 결과 로그 ──────────────────────────────
    elif event == "PostToolUse":
        if log_task is None:
            return
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if tool_name == "Edit":
            fp = tool_input.get("file_path", "?")
            log_task("Claude", f"[수정 완료] {_short_path(fp)} ✓", _TERMINAL_ID)
            # self-reflect: 수정 파일 누적
            if fp not in _SESSION_MODIFIED_FILES:
                _SESSION_MODIFIED_FILES.append(_short_path(fp))
            # [2026-04-14] 활성 세션에 수정 파일 실시간 추가
            try:
                from src.pg_store import update_session_files
                update_session_files(_TERMINAL_ID, _short_path(fp))
            except Exception:
                pass

        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            content = tool_input.get("content", "")
            lines = len(content.splitlines())
            log_task("Claude", f"[생성 완료] {_short_path(fp)} ({lines}줄) ✓", _TERMINAL_ID)
            # self-reflect: 생성 파일 누적
            if fp not in _SESSION_MODIFIED_FILES:
                _SESSION_MODIFIED_FILES.append(_short_path(fp))
            # [2026-04-14] 활성 세션에 생성 파일 실시간 추가
            try:
                from src.pg_store import update_session_files
                update_session_files(_TERMINAL_ID, _short_path(fp))
            except Exception:
                pass

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if any(cmd.startswith(p) for p in _SKIP_BASH_PREFIXES):
                return
            response = data.get("tool_response", {})
            output = ""
            if isinstance(response, dict):
                output = response.get("output") or response.get("stdout") or ""
            elif isinstance(response, str):
                output = response
            result_snippet = _snippet(output, 60) if output else ""
            suffix = f" → {result_snippet}" if result_snippet else " ✓"
            if "git commit" in cmd:
                log_task("Claude", f"[커밋 완료]{suffix}", _TERMINAL_ID)
            else:
                log_task("Claude", f"[명령 완료] {_short_cmd(cmd, 50)}{suffix}", _TERMINAL_ID)

        elif tool_name == "NotebookEdit":
            nb = tool_input.get("notebook_path", "?")
            log_task("Claude", f"[노트북 수정] {_short_path(nb)} ✓", _TERMINAL_ID)

    # ── Stop: 응답 완료 구분선 + 태스크 done 처리 + 세션 스냅샷 ───────────
    elif event == "Stop":
        if log_task:
            log_task("Claude", "─── 응답 완료 ───", _TERMINAL_ID)

        # [파이프라인 단계] Claude 응답 완료 → "완료" 단계 표시
        _update_pipeline_stage('done')

        # ── [2026-04-14] 활성 세션 완료 마킹 ──────────────────────────────
        # 정상적으로 Stop 이벤트가 발생하면 active → done으로 변경
        # 튕기면 이 코드가 실행 안 됨 → active 상태로 남아 → 다음 세션에서 감지
        try:
            from src.pg_store import complete_active_session
            complete_active_session(_TERMINAL_ID)
        except Exception:
            pass

        # Claude 응답이 끝나면 in_progress 상태인 claude 태스크 처리
        # → stop_reason이 'error'가 아닌 경우에만 done으로 변경
        # → 에러/실패 상태에서는 무조건 done 처리하지 않음 (거짓 완료 방지)
        try:
            from src.pg_store import bulk_update_tasks
            _stop_reason = data.get('stop_reason', '')  # 에러 여부 확인
            if _stop_reason == 'error':
                _SESSION_HAD_ERROR = True
            bulk_update_tasks(
                'claude',
                ['pending', 'in_progress'],
                'failed' if _stop_reason == 'error' else 'done',
            )
        except Exception:
            pass

        # ── [P4] 자동 피드백 루프: 작업 완료 시 크로스 검증 자동 요청 ─────────
        # 수정된 파일이 있고, 에러가 아닌 정상 완료일 때만 크로스 검증 요청
        # auto_dispatcher.request_verification()을 호출하여 다른 에이전트에 검증 위임
        try:
            if _SESSION_MODIFIED_FILES and not _SESSION_HAD_ERROR and _SESSION_LAST_TASK:
                from auto_dispatcher import request_verification as _rv
                _task_summary = f"{_SESSION_LAST_TASK[:100]} | 수정 파일: {', '.join(_SESSION_MODIFIED_FILES[-5:])}"
                _rv(
                    task_id=f"AUTO-{_TERMINAL_ID}-{int(time.time())}",
                    result_summary=_task_summary,
                    author="claude",
                )
        except Exception:
            pass  # 디스패처 미설치 등 예외는 조용히 무시

        # 오늘의 사용자 지시 + 완료 액션을 shared_memory.db에 갱신
        # → 다음 세션 시작 시 "이전에 뭘 했지?"를 바로 파악 가능
        try:
            _report_completed_itcp_work("claude")
        except Exception:
            pass
        _save_session_snapshot()

        # [current-work 자동 업데이트] 오늘 완료된 항목을 하이브 메모리에 자동 반영
        # → 다음 세션에서 current-work를 보면 최신 진행 상황 바로 파악 가능
        try:
            import os as _os2
            from datetime import datetime as _dt2
            _today2 = _dt2.now().strftime("%Y-%m-%d")
            _logs2 = _os2.path.join(
                _os2.path.dirname(_os2.path.abspath(__file__)), '..', '.ai_monitor', 'data', 'task_logs.jsonl'
            )
            _done_items = []
            if _os2.path.exists(_logs2):
                with open(_logs2, "r", encoding="utf-8") as _lf:
                    for _line in _lf:
                        _line = _line.strip()
                        if not _line:
                            continue
                        try:
                            _entry = json.loads(_line)
                        except Exception:
                            continue
                        if not _entry.get("timestamp", "").startswith(_today2):
                            continue
                        _task = _entry.get("task", "")
                        if _entry.get("agent") == "Claude" and any(
                            k in _task for k in ["수정 완료", "생성 완료", "커밋 완료", "빌드 완료"]
                        ):
                            _done_items.append(_task[:80])
            _update_current_work(_done_items)
        except Exception:
            pass

        # ── Auto-Stop: 계획 완료 시 {"continue": false} 신호 출력 ────────────
        # ai_monitor_plan.md의 모든 태스크가 [x] 상태이면 Claude Code에
        # continue: false 신호를 보내 세션을 자동 종료합니다.
        # 오피스 세션(OFFICE_MODE=true)에서는 Auto-Stop 비활성화 — 대화형 세션이므로.
        try:
            import re as _re_stop, json as _json_stop, os as _os_stop
            from pathlib import Path as _PV_Path
            if _os_stop.environ.get('OFFICE_MODE') == 'true':
                raise Exception('skip')  # 오피스 세션 → Auto-Stop 스킵
            # _scripts_dir 글로벌 변수 대신 직접 계산 — self-reflect 블록의 지역 재할당 충돌 방지
            _stop_scripts = _os_stop.path.dirname(_os_stop.path.abspath(__file__))
            _plan_path = _PV_Path(_stop_scripts).parent / "ai_monitor_plan.md"
            if _plan_path.exists():
                _plan_txt = _plan_path.read_text(encoding='utf-8')
                # [ ] 미완료 태스크가 없고 [x] 완료 태스크가 하나라도 있으면 전체 완료
                _incomplete = _re_stop.findall(r'-\s+\[ \]', _plan_txt)
                _complete   = _re_stop.findall(r'-\s+\[[xX]\]', _plan_txt)
                if _complete and not _incomplete:
                    if log_task:
                        log_task("Claude", "[Auto-Stop] 계획 완료 — 세션 자동 종료", _TERMINAL_ID)
                    print(_json_stop.dumps({"continue": False}), flush=True)
        except Exception:
            pass  # validator 오류는 무시 — 훅 흐름 방해 금지

        # ── Self-Reflect: 세션 완료 후 pg_thoughts에 자기반성 기록 ──────────
        # 수정한 파일이 있을 때만 반성 기록 (단순 질문 응답은 제외)
        try:
            if _SESSION_MODIFIED_FILES or _SESSION_HAD_ERROR:
                import sys as _sys_r
                _scripts_dir = _os2.path.dirname(_os2.path.abspath(__file__))
                if _scripts_dir not in _sys_r.path:
                    _sys_r.path.insert(0, _scripts_dir)
                from hive_bridge import reflect_to_pg as _reflect
                _learned = [f"수정 완료: {f}" for f in _SESSION_MODIFIED_FILES] if _SESSION_MODIFIED_FILES else []
                _failed  = ["에러로 종료됨"] if _SESSION_HAD_ERROR else []
                _reflect(
                    agent_name="claude",
                    task_summary=_SESSION_LAST_TASK or "작업 완료",
                    learned=_learned,
                    failed=_failed,
                    files_changed=list(_SESSION_MODIFIED_FILES),
                    terminal_id=_TERMINAL_ID
                )
        except Exception:
            pass


if __name__ == "__main__":
    main()
