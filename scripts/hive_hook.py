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
- 2026-03-01 Claude: 빌드 워크플로에 Step3(git commit+push) 추가 + 스킬 자동 실행 지시
  - build_exe: npm build → pyinstaller → git commit+push 전체 사이클로 확장
  - 각 의도에 "즉시 /vibe-XXX 스킬을 실행하세요" 지시 추가
  - Claude가 컨텍스트 수신 즉시 스킬 도구를 호출하도록 강제
- 2026-03-01 Claude: 자동 의도 감지(Intent Detection) 시스템 추가
  - UserPromptSubmit에서 키워드 분석 → 워크플로 컨텍스트 stdout 주입
  - 지원 의도: 빌드(EXE/프론트엔드), 커밋/푸시, 코드리뷰, 디버그, 테스트
  - stdout 출력 → Claude Code가 Claude에게 시스템 컨텍스트로 전달
  - 사용자가 매번 설명 없이 자연어 지시만으로 자동 워크플로 실행 가능
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

# ── 자동 의도 감지 워크플로 맵 ──────────────────────────────────────────────
# 각 항목: keywords(한/영 포함) + context(Claude에게 주입할 워크플로 설명)
# 우선순위: 리스트 순서 (앞이 높음)
_INTENT_MAP = [
    {
        "name": "build_exe",
        # Windows 실행파일/설치버전 빌드 의도
        "keywords": [
            "빌드", "build", "빌드해", "빌드 해", "빌드해줘", "빌드해 줘",
            "실행파일", "설치파일", "설치버전", "배포버전", "배포 버전",
            "exe", "pyinstaller", "패키징", "패키지",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🏗️  [자동 감지] 빌드 워크플로 — Windows EXE 빌드 + Git 배포\n"
            "═══════════════════════════════════════════════════════\n"
            "⚡ 즉시 `/vibe-release` 스킬을 실행하거나 아래 순서를 따르세요.\n"
            "\n"
            "【빌드 순서 — 반드시 이 순서대로 전부 실행】\n"
            "Step 1) 프론트엔드 빌드 (React/Vite)\n"
            "  cd D:/vibe-coding/.ai_monitor/vibe-view && npm run build\n"
            "\n"
            "Step 2) Windows EXE 패키징 (PyInstaller)\n"
            "  cd D:/vibe-coding && pyinstaller vibe-coding.spec --noconfirm\n"
            "  → dist/vibe-coding.exe 생성 (약 60MB)\n"
            "\n"
            "Step 3) Git 커밋 + 푸시 (빌드 결과 GitHub에 반영)\n"
            "  git add .ai_monitor/vibe-view/dist/ vibe-coding.spec\n"
            "  git add -f .ai_monitor/vibe-view/dist/\n"
            "  git commit -m 'build: EXE 및 프론트엔드 빌드 업데이트'\n"
            "  git push origin main\n"
            "\n"
            "⚠️  Step 1 → Step 2 → Step 3 순서 필수. 빌드 = 깃 푸시까지 완료해야 끝.\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
    {
        "name": "commit_push",
        # Git 커밋/푸시 의도 (웹 배포 포함)
        "keywords": [
            "커밋", "commit", "커밋해", "커밋 해", "커밋해줘",
            "푸시", "push", "푸시해", "푸시해줘",
            "올려줘", "올려", "깃헙", "github", "깃허브",
            "배포해줘", "배포 해줘", "배포하자",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "📤  [자동 감지] Git 커밋/푸시 워크플로\n"
            "═══════════════════════════════════════════════════════\n"
            "【실행 순서】\n"
            "1) git status — 변경 파일 확인\n"
            "2) git diff   — 변경 내용 파악\n"
            "3) git add <관련 파일>  — 변경 파일 스테이징 (민감정보 제외)\n"
            "4) git commit -m \"$(cat <<'EOF'\n"
            "   <type>(<scope>): <요약>\n"
            "\n"
            "   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            "   EOF\n"
            "   )\"\n"
            "5) git push origin main\n"
            "\n"
            "【커밋 타입】\n"
            "  feat: 새 기능 | fix: 버그 수정 | docs: 문서\n"
            "  refactor: 리팩터 | build: 빌드/패키징 | chore: 기타\n"
            "\n"
            "⚠️  git push 전 반드시 사용자에게 확인 요청\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
    {
        "name": "code_review",
        # 코드 리뷰 의도
        "keywords": [
            "리뷰", "review", "코드 검토", "검토해", "검토 해줘",
            "코드 리뷰", "코드리뷰", "점검",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🔍  [자동 감지] 코드 리뷰 워크플로\n"
            "═══════════════════════════════════════════════════════\n"
            "⚡ 즉시 `/vibe-code-review` 스킬을 실행하세요.\n"
            "4가지 관점: 코드품질 / 보안(OWASP) / 성능 / 설계\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
    {
        "name": "debug",
        # 디버그/버그 수정 의도
        "keywords": [
            "디버그", "debug", "버그", "bug",
            "오류", "에러", "error", "안 돼", "안돼", "안됨",
            "고쳐줘", "고쳐", "수정해줘",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🐛  [자동 감지] 디버그 워크플로\n"
            "═══════════════════════════════════════════════════════\n"
            "⚡ 즉시 `/vibe-debug` 스킬을 실행하세요.\n"
            "4단계: 증상파악 → 원인추적 → 근본수정 → 검증\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
    {
        "name": "test",
        # 테스트 의도
        "keywords": [
            "테스트", "test", "테스트해", "테스트 실행",
            "검증", "확인해줘", "작동 확인",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🧪  [자동 감지] 테스트 워크플로\n"
            "═══════════════════════════════════════════════════════\n"
            "⚡ 즉시 `/vibe-tdd` 스킬을 실행하세요.\n"
            "RED → GREEN → REFACTOR 사이클\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
    {
        "name": "plan",
        # 계획/설계 의도
        "keywords": [
            "계획", "설계", "plan", "brainstorm", "브레인스토밍",
            "어떻게 할까", "어떻게 구현", "방법이 뭔지",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🧠  [자동 감지] 설계 워크플로 → /vibe-brainstorm\n"
            "═══════════════════════════════════════════════════════\n"
            "1) 요구사항 정제 — 명확한 목표 정의\n"
            "2) 접근법 비교 — 최소 2가지 대안 제시\n"
            "3) 설계 승인 후 구현 시작\n"
            "⚠️  승인 전 코드 작성 금지\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
]


def _detect_intent(prompt: str) -> str | None:
    """사용자 프롬프트에서 워크플로 의도를 감지하고 컨텍스트 문자열을 반환합니다.

    [매칭 방식]
    - 프롬프트를 소문자로 변환 후 키워드 부분 문자열 검색
    - 첫 번째 매칭 의도를 반환 (우선순위: _INTENT_MAP 순서)
    - 매칭 없으면 None 반환
    """
    prompt_lower = prompt.lower()
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

    # ── UserPromptSubmit: 사용자 지시 기록 + 의도 감지 컨텍스트 주입 ──────
    if event == "UserPromptSubmit":
        prompt = (
            data.get("prompt")
            or data.get("content")
            or data.get("message", "")
        )
        if prompt and prompt.strip():
            short = prompt.strip().replace("\n", " ")[:120]
            if log_task:
                log_task("사용자", f"[지시] {short}")

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
        if log_task is None:
            return
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
        if log_task:
            log_task("Claude", "─── 응답 완료 ───")


if __name__ == "__main__":
    main()
