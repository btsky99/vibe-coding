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

# 터미널 ID — hook_bridge.py와 동일한 환경변수 사용 (T1~T8, 기본 T0)
# 각 터미널에서 `set TERMINAL_ID=T1 && claude` 형태로 실행하면 자동 추적
_TERMINAL_ID = os.environ.get('TERMINAL_ID', 'T0')

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
# [중요] orchestrate가 항상 0번 (최고 우선순위) — 복잡한 요청은 여기서 처리
_INTENT_MAP = [
    {
        "name": "orchestrate",
        # 복잡한 요청 감지 — 여러 작업이 복합된 경우 오케스트레이터로 위임
        # 단독 빌드/커밋/리뷰는 각 하위 인텐트가 처리하므로 여기선 복합 요청만
        "keywords": [
            # 복합 작업 지시 키워드
            "자동으로", "전부", "전체", "다 해줘", "다해줘", "알아서",
            "순서대로", "차례로", "단계별로", "하나씩",
            # 여러 작업 나열 패턴
            "하고", "그리고", "다음에", "그 다음",
            # 오케스트레이션 명시
            "오케스트레이터", "오케스트레이션", "orchestrat",
            # 복합 요청 예시 키워드
            "고치고 테스트", "테스트하고 배포", "리뷰하고 수정",
            "만들고 커밋", "구현하고 빌드",
        ],
        "context": (
            "═══════════════════════════════════════════════════════\n"
            "🎯  [자동 감지] 복합 요청 → AI 오케스트레이터 모드\n"
            "═══════════════════════════════════════════════════════\n"
            "⚡ 즉시 `/vibe-orchestrate` 스킬을 실행하세요.\n"
            "\n"
            "【오케스트레이터 동작 순서】\n"
            "1) 요청 분석 → 필요한 스킬 목록 결정\n"
            "2) skill_orchestrator.py로 체인 계획 저장 (대시보드 연동)\n"
            "   python scripts/skill_orchestrator.py plan \"요청\" skill1 skill2 ...\n"
            "3) 각 스킬을 Skill 도구로 순서대로 자동 실행\n"
            "4) 각 단계 완료 시 상태 업데이트\n"
            "   python scripts/skill_orchestrator.py update <step> done \"요약\"\n"
            "5) 전체 완료 후 보고\n"
            "   python scripts/skill_orchestrator.py done\n"
            "\n"
            "⚠️  에러/실패 발생 시 즉시 사용자에게 보고하고 중단할 것 — 에러 무시하고 완료 보고 금지\n"
            "⚠️  각 스킬 실행 후 실제로 성공했는지 확인(검증) 후 다음 단계 진행\n"
            "═══════════════════════════════════════════════════════"
        ),
    },
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
            "🏗️  [자동 감지] 빌드 워크플로 — Windows EXE + 설치버전 + Git 배포\n"
            "═══════════════════════════════════════════════════════\n"
            "🚨 중요: 사용자 확인 없이 모든 Step을 순서대로 즉시 실행하세요.\n"
            "\n"
            "【빌드 순서 — 전부 자동 실행, 중간에 묻지 말 것】\n"
            "Step 1) 프론트엔드 빌드 (React/Vite)\n"
            "  cd D:/vibe-coding/.ai_monitor/vibe-view && npm run build\n"
            "\n"
            "Step 2) Windows EXE 패키징 (PyInstaller)\n"
            "  cd D:/vibe-coding && pyinstaller vibe-coding.spec --noconfirm\n"
            "  → dist/vibe-coding-vX.Y.Z.exe 생성 (버전은 _version.py에서 자동)\n"
            "\n"
            "Step 3) 설치버전 빌드 (Inno Setup)\n"
            "  ISCC_PATH=\"C:/Users/com/AppData/Local/Programs/Inno Setup 6/ISCC.exe\"\n"
            "  \"$ISCC_PATH\" D:/vibe-coding/vibe-coding-setup.iss\n"
            "  → dist/vibe-coding-setup-X.Y.Z.exe 생성\n"
            "\n"
            "Step 4) Git 커밋 + 푸시 (빌드 결과 GitHub에 반영)\n"
            "  cd D:/vibe-coding\n"
            "  git add .ai_monitor/vibe-view/dist/ vibe-coding.spec vibe-coding-setup.iss\n"
            "  git add -f .ai_monitor/vibe-view/dist/\n"
            "  git commit -m 'build: EXE+설치버전 빌드 및 프론트엔드 업데이트'\n"
            "  git push origin main\n"
            "\n"
            "⚠️  Step 1→2→3→4 순서 필수. 각 Step 완료 확인 후 다음 진행.\n"
            "⚠️  빌드 완료 = 깃 푸시까지 완료. 중간에 사용자에게 묻지 말 것.\n"
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
        payload = json.dumps({
            'terminal_id': _TERMINAL_ID,
            'stage': stage,
            'task': task[:120] if task else '',
        }).encode('utf-8')
        req = _req.Request(
            'http://localhost:9571/api/agent/stage',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        _req.urlopen(req, timeout=1)
    except Exception:
        pass  # 서버 미실행 시 조용히 무시


def _save_session_snapshot() -> None:
    """Stop 이벤트 시 오늘의 세션 활동을 shared_memory.db에 자동 저장합니다.

    [동작 순서]
    1. task_logs.jsonl에서 오늘 날짜의 Claude/사용자 로그 추출
    2. 중요 항목 필터 (사용자 지시, 파일 수정, 커밋 완료)
    3. shared_memory.db에 "claude:auto-session:YYYY-MM-DD" 키로 저장
       (INSERT OR REPLACE → 당일 내 호출마다 최신 상태로 갱신)
    4. 다음 세션에서 이 키를 조회하여 이전 작업 내용 파악 가능

    [에러 시]
    모든 예외 무시 — Stop 훅 실행을 방해하지 않음
    """
    try:
        import sqlite3
        from pathlib import Path
        from datetime import datetime

        project_root = Path(_scripts_dir).parent
        data_dir = project_root / ".ai_monitor" / "data"
        logs_file = data_dir / "task_logs.jsonl"
        db_file = data_dir / "shared_memory.db"

        if not logs_file.exists() or not db_file.exists():
            return

        # 오늘 날짜의 로그만 수집
        today = datetime.now().strftime("%Y-%m-%d")
        important_lines = []
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
                # 중요 이벤트만 추출 (노이즈 제거)
                if agent == "사용자" and "[지시]" in task:
                    important_lines.append(task)
                elif agent == "Claude" and any(k in task for k in ["수정 완료", "생성 완료", "커밋 완료"]):
                    important_lines.append(task)

        if not important_lines:
            return

        # 최근 20개만 보관 (과거 항목은 truncate)
        summary = "\n".join(important_lines[-20:])
        now = datetime.now().isoformat()
        key = f"claude:auto-session:{today}"

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO memory
              (key, id, title, content, tags, author, timestamp, updated_at, project)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key, key,
                f"[자동] Claude 세션 활동 요약 ({today})",
                summary,
                '["auto","session","claude","snapshot"]',
                "claude",
                now, now,
                "vibe-coding",
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _inject_hive_context() -> str:
    """UserPromptSubmit 시 하이브 메모리에서 현재 작업 컨텍스트를 자동 주입합니다.

    [동작]
    1. shared_memory.db에서 current-work 키 조회 (현재 진행 중인 작업 상태)
    2. 오늘의 auto-session 스냅샷 조회 (오늘 완료한 작업 목록)
    3. 두 정보를 하나의 컨텍스트 문자열로 합쳐 반환
    → Claude가 항상 하이브 상태를 알고 시작하도록 보장

    [에러 시] 빈 문자열 반환 — 훅 실행 방해하지 않음
    """
    try:
        import sqlite3
        from pathlib import Path
        from datetime import datetime

        project_root = Path(_scripts_dir).parent
        db_file = project_root / ".ai_monitor" / "data" / "shared_memory.db"
        if not db_file.exists():
            return ""

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 터미널 번호로 current-work 키 동적 탐색
        rows = cur.execute(
            "SELECT key, content FROM memory WHERE key LIKE '%:current-work' ORDER BY updated_at DESC LIMIT 1"
        ).fetchall()
        current_work = rows[0]["content"] if rows else ""

        # 오늘의 세션 스냅샷
        today = datetime.now().strftime("%Y-%m-%d")
        snap_rows = cur.execute(
            "SELECT content FROM memory WHERE key = ? LIMIT 1",
            (f"claude:auto-session:{today}",)
        ).fetchall()
        today_snap = snap_rows[0]["content"] if snap_rows else ""
        conn.close()

        parts = []
        if current_work:
            # current-work에서 핵심 정보만 추출 (전체 출력 시 노이즈)
            lines = [l for l in current_work.split("\n") if l.strip()]
            # 진행 중([x] 미완, [ ] 미완) 항목만 필터
            todo_lines = [l for l in lines if "[ ]" in l or "🔄" in l or "진행 상황" in l]
            summary = "\n".join(todo_lines[:10]) if todo_lines else "\n".join(lines[:8])
            parts.append(f"[하이브 현재 작업 상태]\n{summary}")

        if today_snap:
            snap_lines = today_snap.strip().split("\n")[-5:]  # 오늘 완료 최근 5개
            parts.append(f"[오늘 완료 항목]\n" + "\n".join(snap_lines))

        if not parts:
            return ""

        return (
            "[INFO] 하이브 컨텍스트 자동 로드됨 — 아래 내용을 바탕으로 작업 맥락을 파악하세요\n"
            + "\n\n".join(parts)
            + "\n[END 하이브 컨텍스트]"
        )
    except Exception:
        return ""


def _update_current_work(completed_items: list[str]) -> None:
    """Stop 이벤트 시 오늘 완료된 항목을 current-work 메모리에 자동 반영합니다.

    [동작]
    1. current-work에서 미완료([  ]) 항목 중 오늘 완료된 것 → [x]로 변경
    2. 완료된 작업을 '완료 이력' 섹션에 추가
    → 다음 세션에서 current-work를 보면 최신 진행 상황 파악 가능

    [에러 시] 조용히 무시
    """
    try:
        import sqlite3
        from pathlib import Path
        from datetime import datetime

        if not completed_items:
            return

        project_root = Path(_scripts_dir).parent
        db_file = project_root / ".ai_monitor" / "data" / "shared_memory.db"
        if not db_file.exists():
            return

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        rows = cur.execute(
            "SELECT key, content FROM memory WHERE key LIKE '%:current-work' ORDER BY updated_at DESC LIMIT 1"
        ).fetchall()
        if not rows:
            conn.close()
            return

        key = rows[0]["key"]
        content = rows[0]["content"]

        # 오늘 완료 항목 섹션 추가
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        completed_block = f"\n## 자동 업데이트 ({today})\n" + "\n".join(
            f"- [x] {item}" for item in completed_items[-10:]
        )
        new_content = content + completed_block

        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE memory SET content = ?, updated_at = ? WHERE key = ?",
            (new_content, now, key)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _read_messages(agent_name: str) -> list[dict]:
    """messages.jsonl에서 나(agent_name)에게 온 미읽음 메시지를 읽고 read_at을 마킹합니다.

    [동작 순서]
    1. .ai_monitor/data/messages.jsonl 읽기
    2. to == agent_name AND read_at가 없는(None/빈 문자열) 항목 필터
    3. 해당 메시지들에 read_at 타임스탬프 기록
    4. 전체 메시지 목록 파일에 재저장 (원자적 쓰기)
    5. 읽은 메시지 목록 반환

    [파일 없거나 에러 시]
    빈 리스트 반환 — 훅 실행을 중단하지 않음
    """
    from pathlib import Path
    from datetime import datetime

    project_root = Path(_scripts_dir).parent
    messages_file = project_root / ".ai_monitor" / "data" / "messages.jsonl"

    if not messages_file.exists():
        return []

    try:
        # 전체 메시지 읽기
        messages = []
        with open(messages_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        # 미읽음 메시지 필터 (나에게 온 것 + read_at 없음)
        unread = [
            m for m in messages
            if m.get("to") in (agent_name, "all")
            and not m.get("read_at")
        ]

        if not unread:
            return []

        # read_at 타임스탬프 마킹
        now = datetime.now().isoformat()
        for m in messages:
            if m in unread:
                m["read_at"] = now

        # 파일 재저장 (원자적: 전체 덮어쓰기)
        with open(messages_file, "w", encoding="utf-8") as f:
            for m in messages:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

        return unread

    except Exception:
        return []


def _check_and_install_skills() -> list[str]:
    """Claude Code 스킬 자동 설치 — UserPromptSubmit마다 실행.

    [동작 원리]
    1. scripts/ 기준으로 프로젝트 루트 탐지
    2. skills/claude/*.md 목록과 .claude/commands/*.md 목록 비교
    3. 누락된 스킬 파일을 .claude/commands/에 자동 복사
    4. 설치된 스킬 이름 목록을 반환 (로깅용)

    [자기치유 관점]
    스킬이 삭제되거나 새 스킬이 추가되어도 다음 사용자 입력 시 자동 복구됨.
    수동으로 대시보드에서 설치할 필요 없음.
    """
    installed = []
    try:
        import shutil
        from pathlib import Path

        # 프로젝트 루트: scripts/hive_hook.py 기준 상위 폴더
        project_root = Path(_scripts_dir).parent

        skills_src = project_root / "skills" / "claude"
        commands_dst = project_root / ".claude" / "commands"

        if not skills_src.exists():
            return []

        # .claude/commands/ 폴더 없으면 자동 생성
        commands_dst.mkdir(parents=True, exist_ok=True)

        # 소스와 대상 비교 → 누락 파일 복사
        for skill_file in skills_src.glob("*.md"):
            target = commands_dst / skill_file.name
            if not target.exists():
                shutil.copy2(str(skill_file), str(target))
                installed.append(skill_file.stem)

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

        # [하이브 컨텍스트 자동 주입] 작업 시작 전 current-work + 오늘 활동 자동 로드
        # → Claude가 매번 수동으로 memory.py list를 실행하지 않아도 항상 컨텍스트 보유
        hive_ctx = _inject_hive_context()
        if hive_ctx:
            print(hive_ctx, flush=True)
            if log_task:
                log_task("Hive", "[하이브 컨텍스트] 자동 주입 완료 — current-work + 오늘 활동", _TERMINAL_ID)

        # [메시지 폴링] Gemini 또는 다른 에이전트가 보낸 미읽음 메시지 확인
        # 메시지가 있으면 컨텍스트로 출력하여 Claude가 인지하도록 함
        unread = _read_messages("claude")
        if unread:
            lines = [f"📨 [{m.get('from','?')} → claude] ({m.get('type','info')}) {m.get('content','')}".strip()
                     for m in unread]
            print("[Hive 메시지] 미읽음 메시지:\n" + "\n".join(lines), flush=True)
            if log_task:
                log_task("Hive", f"[메시지 수신] {len(unread)}개 읽음: {lines[0][:60]}", _TERMINAL_ID)

        prompt = (
            data.get("prompt")
            or data.get("content")
            or data.get("message", "")
        )
        if prompt and prompt.strip():
            short = prompt.strip().replace("\n", " ")[:120]
            if log_task:
                log_task("사용자", f"[지시] {short}", _TERMINAL_ID)

            # [파이프라인 단계 업데이트] 사용자 지시 수신 → "분석" 단계 표시
            _update_pipeline_stage('analyzing', short)

            # ── 태스크 보드 자동 등록 ──────────────────────────────────────────
            # 사용자 지시가 들어올 때마다 tasks.json에 pending 태스크로 추가합니다.
            # 에이전트가 작업을 시작하면 in_progress, 완료 시 done으로 상태를 변경할 수 있습니다.
            try:
                import datetime
                _data_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), '..', '.ai_monitor', 'data'
                )
                _tasks_file = os.path.join(_data_dir, 'tasks.json')
                _tasks: list = []
                if os.path.exists(_tasks_file):
                    with open(_tasks_file, 'r', encoding='utf-8') as _f:
                        _tasks = json.load(_f)
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
                _tasks.append(_new_task)
                with open(_tasks_file, 'w', encoding='utf-8') as _f:
                    json.dump(_tasks, _f, ensure_ascii=False, indent=2)
            except Exception:
                pass  # 태스크 보드 기록 실패는 조용히 무시 (훅 자체가 중단되면 안 됨)

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

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "").strip()
            if any(cmd.startswith(p) for p in _SKIP_BASH_PREFIXES):
                return
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

        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            content = tool_input.get("content", "")
            lines = len(content.splitlines())
            log_task("Claude", f"[생성 완료] {_short_path(fp)} ({lines}줄) ✓", _TERMINAL_ID)

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

        # Claude 응답이 끝나면 in_progress 상태인 claude 태스크 처리
        # → stop_reason이 'error'가 아닌 경우에만 done으로 변경
        # → 에러/실패 상태에서는 무조건 done 처리하지 않음 (거짓 완료 방지)
        try:
            import os as _os
            _stop_reason = data.get('stop_reason', '')  # 에러 여부 확인
            _data_dir = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), '..', '.ai_monitor', 'data'
            )
            _tasks_file = _os.path.join(_data_dir, 'tasks.json')
            if _os.path.exists(_tasks_file):
                with open(_tasks_file, 'r', encoding='utf-8') as _f:
                    _tasks = json.load(_f)
                _changed = False
                for _t in _tasks:
                    if _t.get('assigned_to') == 'claude' and _t.get('status') in ('pending', 'in_progress'):
                        # 에러로 중단된 경우 'failed'로 표시, 정상 완료 시만 'done'
                        _t['status'] = 'failed' if _stop_reason == 'error' else 'done'
                        _changed = True
                if _changed:
                    with open(_tasks_file, 'w', encoding='utf-8') as _f:
                        json.dump(_tasks, _f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 오늘의 사용자 지시 + 완료 액션을 shared_memory.db에 갱신
        # → 다음 세션 시작 시 "이전에 뭘 했지?"를 바로 파악 가능
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


if __name__ == "__main__":
    main()
