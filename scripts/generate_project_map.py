"""
FILE: scripts/generate_project_map.py
DESCRIPTION: PROJECT_MAP.md 자동 생성 스크립트.
             실제 파일 구조를 스캔하여 PROJECT_MAP.md를 자동 갱신합니다.
             문서 드리프트를 방지하기 위해 파일 시스템을 진실의 원천으로 사용합니다.

REVISION HISTORY:
- 2026-03-22 Claude: 최초 생성 — 5축 모듈 맵 기반 자동 생성
"""

import os
import time
from pathlib import Path


# ── 프로젝트 루트 ─────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 파일 설명 데이터베이스 ─────────────────────────────────────────────────
# 각 파일의 한줄 설명을 관리. 여기에 없는 파일은 "(설명 없음)"으로 표시.
FILE_DESCRIPTIONS = {
    # ── 루트 문서 ──
    "PROJECT_MAP.md": "프로젝트 전체 지도 및 파일 역할 가이드 (이 파일)",
    "RULES.md": "에이전트 행동 수칙, 한글 주석/커밋 표준, 하이브 마인드 운영 원칙",
    "CLAUDE.md": "Claude Code 전용 프로젝트 가이드",
    "AGENTS.md": "멀티 에이전트 설정 및 협업 프로토콜 정의",
    "HIVEMIND.md": "하이브 마인드 실시간 상태 문서 (자동 생성)",
    "CODEX_GUIDE.md": "코덱스(Codex) 에이전트 퀵 스타트 및 통합 사용 설명서",
    "ai_monitor_plan.md": "하이브 마인드 고도화 및 신규 기능 구현 로드맵",
    "vibe-coding.spec": "PyInstaller 실행 파일 빌드 설정",
    "vibe-coding-setup.iss": "Inno Setup 인스톨러 생성 스크립트",
    "run_vibe.bat": "하이브 서버 및 대시보드 실행 배치 파일",

    # ── docs/ ──
    "docs/VIBE_PROJECT_GUIDE.md": "하이브 마인드 운영 및 아키텍처 통합 가이드",
    "docs/API_SPEC.md": "REST API 엔드포인트 및 통신 규격 상세 명세",
    "docs/CODEX_HARDENING.md": "Codex 경로 고도화 적용 내용과 재적용 조건",
    "docs/CODEX_RUNTIME_SETUP.md": "설치 후 PC별 Codex 런타임 설정 및 운영 가이드",

    # ── .ai_monitor/ 코어 ──
    "server.py": "중앙 HTTP 서버 (모든 API 라우팅, SSE, PostgreSQL 연동)",
    "mission_control.py": "CMUX 스타일 시스템 트레이 및 HUD 관제 센터",
    "mission_control_ui.py": "슬라이드인 사이드바 HUD (에이전트 상태 링)",
    "_version.py": "버전 진실의 원천 (__version__)",

    # ── .ai_monitor/api/ ──
    "api/hive_api.py": "하이브 마인드 오케스트레이션 API (/api/hive/*, /api/orchestrator/*)",
    "api/agent_api.py": "CLI 에이전트 관리 API (/api/agent/*)",
    "api/mcp_api.py": "MCP 서버 관리 API (/api/mcp/*)",
    "api/vibe_api.py": "Vibe CLI 상태 관리 API (/api/vibe/*)",
    "api/git_api.py": "Git 저장소 관리 API (/api/git/*)",
    "api/memory_api.py": "메모리/지식 저장소 API (/api/memory/*)",
    "api/pty_api.py": "PTY 터미널 제어 API (/api/pty/*)",
    "api/dispatcher_api.py": "디스패처 API (/api/dispatcher/*) — server.py에서 분리",
    "api/tasks_api.py": "태스크 API (/api/tasks/*) — server.py에서 분리",
    "api/files_api.py": "파일 API (/api/files/*, /api/read-file, /api/save-file) — server.py에서 분리",

    # ── .ai_monitor/src/ ──
    "src/pg_store.py": "PostgreSQL 데이터 저장소 (스키마 관리 + 쿼리)",
    "src/file_store.py": "파일 기반 레거시 저장소",

    # ── scripts/ 에이전트/터미널 ──
    "scripts/cli_agent.py": "Claude/Gemini/Codex CLI 자율 오케스트레이션 엔진",
    "scripts/agent_shell.py": "인터랙티브 자율 에이전트 쉘 (REPL)",
    "scripts/terminal_agent.py": "멀티터미널 자율 에이전트 디스패처",
    "scripts/agent_launcher.py": "통합 에이전트 런처 (NORMAL/YOLO 모드)",
    "scripts/agent_detector.py": "활성 AI 에이전트 자동 감지 (psutil)",
    "scripts/agent_protocol.py": "RFC 관리 + 하이브 토론 프로토콜",
    "scripts/gemini_responder.py": "Gemini CLI 자동 응답기",

    # ── scripts/ 하이브/협업 ──
    "scripts/auto_dispatcher.py": "역량 기반 자동 작업 분배 + 크로스 검증",
    "scripts/orchestrator.py": "하이브 태스크 스케줄링 및 에이전트 감시",
    "scripts/hive_debate.py": "에이전트 간 의견 조율 토론 워크플로우",
    "scripts/hive_bridge.py": "PostgreSQL 18 기반 하이브 통합 로깅",
    "scripts/memory.py": "PostgreSQL 기반 하이브 메모리 CLI",
    "scripts/worktree_manager.py": "Git Worktree 격리 관리자",
    "scripts/generate_hivemind_doc.py": "HIVEMIND.md 자동 생성기",
    "scripts/analyze_hive.py": "하이브 실시간 상태 분석 보고서",

    # ── scripts/ 훅/이벤트 ──
    "scripts/hive_hook.py": "Claude Code 자동 액션 트레이스 훅 (의도 감지)",
    "scripts/hook_bridge.py": "Claude Code UserPromptSubmit 훅 브릿지",
    "scripts/claude_hook.py": "Claude Code PostToolUse/Stop 훅 핸들러",
    "scripts/gemini_hook.py": "Gemini CLI 훅 + 대시보드 유지 + HIVEMIND.md 갱신",

    # ── scripts/ 통신 ──
    "scripts/itcp.py": "PostgreSQL pg_messages 기반 ITCP 프로토콜",
    "scripts/vibe_mux.py": "cmux-style Named Pipe 멀티플렉서 서버",
    "scripts/vibe_mux_agent.py": "터미널별 MUX 에이전트 수신/실행 루프",
    "scripts/send_message.py": "ITCP 기반 터미널 간 메시지 전송 CLI",
    "scripts/megaphone.py": "하이브 브로드캐스트 메시지 유틸",
    "scripts/discord_bridge.py": "Discord 멀티터미널 브릿지",

    # ── scripts/ 검증/가드 ──
    "scripts/safety_guard.py": "Bounded Autonomy 위험 명령 탐지 (60+ 패턴)",
    "scripts/completion_guard.py": "Harness continue:false 완료 신호 감지",
    "scripts/drift_detector.py": "ai_monitor_plan.md 이탈 감지기",
    "scripts/plan_validator.py": "Harness 계획 검증 엔진 (V1-V5)",
    "scripts/rules_validator.py": "RULES.md 준수 자동 검증",

    # ── scripts/ 스킬 관리 ──
    "scripts/skill_orchestrator.py": "스킬 체인 상태 추적 (hive_skill_chains 테이블 기반)",
    "scripts/skill_manager.py": "Gemini/Claude 스킬 통합 관리자",
    "scripts/skill_analyzer.py": "반복 패턴 감지 + 자기치유 스킬 업데이트",
    "scripts/skill_predictor.py": "마르코프 체인 기반 다음 스킬 예측",
    "scripts/skill_ab_test.py": "스킬 A/B 테스트 + 성능 분석",

    # ── scripts/ 모니터링 ──
    "scripts/hive_watchdog.py": "자가 치유(3계층) 엔진 + skill_analyzer 트리거",
    "scripts/claude_watchdog.py": "Claude 에이전트 행(hang) 오류 감지 + 재시작",
    "scripts/heal_daemon.py": "pg_logs 감시 + 에러 자동 수리",
    "scripts/terminal_status.py": "터미널 상태 모니터",

    # ── scripts/ 유틸리티 ──
    "scripts/vibe_cli.py": "cmux 호환 vibe CLI (notify/set-progress/codex)",
    "scripts/task.py": "하이브 태스크 CLI (create/list/update)",
    "scripts/auto_version.py": "버전 자동 증가 (patch +1) 유틸리티",
    "scripts/auto_release.py": "자율 배포(Autonomous Release) 엔진",
    "scripts/lock_manager.py": "파일 수정 충돌 방지 잠금 (JSON 기반)",
    "scripts/osc_parser.py": "OSC 시퀀스 파서 (Kitty/RXVT 알림)",
    "scripts/git_visualizer.py": "Git 워크트리/브랜치 시각화",
    "scripts/screenshot_analyzer.py": "Gemini Vision 기반 스크린샷 버그 감지",

    # ── scripts/ 인프라 ──
    "scripts/pg_manager.py": "포터블 PostgreSQL 18 + pgvector 통합 관리자",
    "scripts/setup_hive_pg.py": "PostgreSQL 18 + pgvector 자동 설치",
    "scripts/install_codex.py": "Codex CLI npm 설치 및 검증",

    # ── scripts/ 마이그레이션 ──
    "scripts/migrate_memory_to_pg.py": "SQLite → PostgreSQL 데이터 이관",
    "scripts/migrate_sqlite_to_files.py": "SQLite → 파일 시스템 마이그레이션",

    # ── scripts/ 테스트/디버깅 ──
    "scripts/test_pg_logging.py": "PostgreSQL 로깅 테스트",
    "scripts/test_discord.py": "Discord 브릿지 통합 테스트",
    "scripts/debug_discord.py": "Discord 브릿지 디버거",
    "scripts/generate_project_map.py": "PROJECT_MAP.md 자동 생성 스크립트 (이 파일)",

    # ── 프론트엔드 컴포넌트 ──
    "App.tsx": "최상위 레이아웃 오케스트레이터 (레이아웃 모드, 사이드바, 폴링 조율)",
    "ActivityBar.tsx": "좌측 아이콘 바 (HiveEngineStatus LED 링 통합)",
    "TerminalSlot.tsx": "단일 터미널 슬롯 (XTerm.js + WebSocket + 에이전트 선택)",
    "TopMenuBar.tsx": "VS Code 스타일 메뉴바 (파일/편집/보기/AI 도구)",
    "FileExplorer.tsx": "파일 시스템 탐색기 (트리/플랫 뷰)",
    "FloatingWindow.tsx": "파일 에디터 부유 창 (드래그/리사이즈)",
    "VibeEditor.tsx": "코드 에디터 래퍼 (Monaco Editor)",
    "MessageComposer.tsx": "에이전트 간 메시지 작성 폼",
    "ThoughtTrace.tsx": "AI 사고 로그 표시",
    "DiscordSettingsModal.tsx": "Discord 설정 모달",
    "FileTreeNode.tsx": "파일 트리 노드 (재귀 폴더 확장)",
    "FilePathText.tsx": "파일 경로 렌더링 (클릭 가능 링크화)",
    "AgentPanel.tsx": "자율 에이전트 통합 컨트롤 패널 (SSE 스트림, 워크플로우, 사고흐름)",
    "MessagesPanel.tsx": "에이전트 간 메시지 채널 (채팅 버블 스타일)",
    "TasksPanel.tsx": "에이전트 간 태스크 큐",
    "TaskBoardPanel.tsx": "칸반 스타일 태스크 보드",
    "MemoryPanel.tsx": "공유 지식 베이스 (PostgreSQL)",
    "HivePanel.tsx": "하이브 시스템 진단 (헬스 체크, 자가 치유)",
    "DispatcherPanel.tsx": "멀티-LLM 디스패처 (역량 레이더 차트)",
    "OrchestratorPanel.tsx": "스킬 체인 현황판",
    "KanbanPanel.tsx": "오케스트레이션 수평 파이프라인 뷰",
    "SkillResultsPanel.tsx": "스킬 실행 결과 (라이브 + 기록)",
    "GitPanel.tsx": "Git 통합 (브랜치, 스테이징, 커밋)",
    "McpPanel.tsx": "MCP 관리자 (카탈로그 + Smithery 검색)",
    "DiscordConfigPanel.tsx": "Discord 설정 패널",
}


def count_lines(filepath: Path) -> int:
    """파일의 줄 수를 반환합니다."""
    try:
        return sum(1 for _ in open(filepath, encoding='utf-8', errors='replace'))
    except Exception:
        return 0


def get_description(rel_path: str, filename: str) -> str:
    """파일 설명을 데이터베이스에서 조회합니다."""
    # 전체 상대 경로로 먼저 검색
    if rel_path in FILE_DESCRIPTIONS:
        return FILE_DESCRIPTIONS[rel_path]
    # 파일명만으로 검색 (컴포넌트 등)
    if filename in FILE_DESCRIPTIONS:
        return FILE_DESCRIPTIONS[filename]
    return ""


def scan_section(base: Path, rel_dir: str, extensions: tuple, skip_dirs: set = None) -> list:
    """디렉토리를 스캔하여 (상대경로, 줄수, 설명) 리스트를 반환합니다."""
    skip_dirs = skip_dirs or set()
    target = base / rel_dir if rel_dir else base
    if not target.exists():
        return []

    results = []
    for item in sorted(target.iterdir()):
        if item.name.startswith('.') or item.name.startswith('__'):
            continue
        if item.is_dir() and item.name in skip_dirs:
            continue
        if item.is_file() and item.suffix in extensions:
            rel = str(item.relative_to(base)).replace('\\', '/')
            lines = count_lines(item)
            desc = get_description(rel, item.name)
            results.append((rel, lines, desc))
    return results


def generate():
    """PROJECT_MAP.md를 생성합니다."""
    now = time.strftime('%Y-%m-%d %H:%M')
    lines = []
    lines.append(f"# 🗺️ Vibe Coding 프로젝트 맵 (PROJECT_MAP.md)")
    lines.append(f"")
    lines.append(f"> 자동 생성: `python scripts/generate_project_map.py` | {now}")
    lines.append(f"> 문서 드리프트 방지를 위해 파일 시스템을 스캔하여 자동 갱신합니다.")
    lines.append(f"")

    # ── 1. 루트 문서 ──
    lines.append("## 📜 루트 문서")
    lines.append("| 파일 | 설명 |")
    lines.append("|------|------|")
    root_docs = [f for f in PROJECT_ROOT.iterdir()
                 if f.is_file() and f.suffix == '.md' and not f.name.startswith('.')]
    root_docs.sort(key=lambda x: x.name)
    for f in root_docs:
        desc = get_description(f.name, f.name)
        lines.append(f"| `{f.name}` | {desc} |")
    # docs/ 하위
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.exists():
        for f in sorted(docs_dir.iterdir()):
            if f.is_file() and f.suffix == '.md':
                rel = f"docs/{f.name}"
                desc = get_description(rel, f.name)
                lines.append(f"| `{rel}` | {desc} |")
    lines.append("")

    # ── 2. 서버 & API ──
    lines.append("## 🖥️ 서버 & API (.ai_monitor/)")
    ai_dir = PROJECT_ROOT / ".ai_monitor"

    lines.append("### 서버 코어")
    lines.append("| 파일 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    core_files = ['server.py', '_version.py', 'mission_control.py', 'mission_control_ui.py']
    for name in core_files:
        fp = ai_dir / name
        if fp.exists():
            lc = count_lines(fp)
            desc = get_description(name, name)
            lines.append(f"| `{name}` | {lc} | {desc} |")

    lines.append("")
    lines.append("### API 모듈 (.ai_monitor/api/)")
    lines.append("| 모듈 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    api_dir = ai_dir / "api"
    if api_dir.exists():
        for f in sorted(api_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name != '__init__.py':
                rel = f"api/{f.name}"
                lc = count_lines(f)
                desc = get_description(rel, f.name)
                lines.append(f"| `{f.name}` | {lc} | {desc} |")

    lines.append("")
    lines.append("### 데이터 계층 (.ai_monitor/src/)")
    lines.append("| 모듈 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    src_dir = ai_dir / "src"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name != '__init__.py':
                rel = f"src/{f.name}"
                lc = count_lines(f)
                desc = get_description(rel, f.name)
                lines.append(f"| `{f.name}` | {lc} | {desc} |")
    lines.append("")

    # ── 3. Scripts ──
    lines.append("## ⚙️ 스크립트 (scripts/)")
    scripts_dir = PROJECT_ROOT / "scripts"

    # 카테고리별 그룹핑
    categories = {
        "에이전트/터미널": ["cli_agent.py", "agent_shell.py", "terminal_agent.py",
                           "agent_launcher.py", "agent_detector.py", "agent_protocol.py", "gemini_responder.py"],
        "하이브/협업": ["auto_dispatcher.py", "orchestrator.py", "hive_debate.py", "hive_bridge.py",
                        "memory.py", "worktree_manager.py", "generate_hivemind_doc.py", "analyze_hive.py"],
        "훅/이벤트": ["hive_hook.py", "hook_bridge.py", "claude_hook.py", "gemini_hook.py"],
        "통신/ITCP": ["itcp.py", "vibe_mux.py", "vibe_mux_agent.py", "send_message.py",
                       "megaphone.py", "discord_bridge.py"],
        "검증/가드": ["safety_guard.py", "completion_guard.py", "drift_detector.py",
                      "plan_validator.py", "rules_validator.py"],
        "스킬 관리": ["skill_orchestrator.py", "skill_manager.py", "skill_analyzer.py",
                      "skill_predictor.py", "skill_ab_test.py"],
        "모니터링": ["hive_watchdog.py", "claude_watchdog.py", "heal_daemon.py", "terminal_status.py"],
        "유틸리티": ["vibe_cli.py", "task.py", "auto_version.py", "auto_release.py",
                     "lock_manager.py", "osc_parser.py", "git_visualizer.py", "screenshot_analyzer.py",
                     "generate_project_map.py"],
        "인프라": ["pg_manager.py", "setup_hive_pg.py", "install_codex.py"],
        "마이그레이션": ["migrate_memory_to_pg.py", "migrate_sqlite_to_files.py"],
    }

    categorized = set()
    for cat_name, cat_files in categories.items():
        lines.append(f"### {cat_name}")
        lines.append("| 파일 | 줄 수 | 설명 |")
        lines.append("|------|------|------|")
        for name in cat_files:
            fp = scripts_dir / name
            if fp.exists():
                lc = count_lines(fp)
                desc = get_description(f"scripts/{name}", name)
                lines.append(f"| `{name}` | {lc} | {desc} |")
                categorized.add(name)
        lines.append("")

    # 미분류 파일
    uncategorized = []
    if scripts_dir.exists():
        for f in sorted(scripts_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name not in categorized and not f.name.startswith('__'):
                uncategorized.append(f)
    if uncategorized:
        lines.append("### 기타")
        lines.append("| 파일 | 줄 수 | 설명 |")
        lines.append("|------|------|------|")
        for f in uncategorized:
            lc = count_lines(f)
            desc = get_description(f"scripts/{f.name}", f.name)
            lines.append(f"| `{f.name}` | {lc} | {desc} |")
        lines.append("")

    # ── 4. 프론트엔드 ──
    lines.append("## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)")
    vv_src = ai_dir / "vibe-view" / "src"

    lines.append("### 코어")
    lines.append("| 파일 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    core_tsx = ['App.tsx', 'main.tsx', 'types.ts', 'constants.tsx']
    for name in core_tsx:
        fp = vv_src / name
        if fp.exists():
            lc = count_lines(fp)
            desc = get_description(name, name)
            lines.append(f"| `{name}` | {lc} | {desc} |")
    lines.append("")

    lines.append("### 컴포넌트 (components/)")
    lines.append("| 컴포넌트 | 줄 수 | 설명 |")
    lines.append("|----------|------|------|")
    comp_dir = vv_src / "components"
    if comp_dir.exists():
        for f in sorted(comp_dir.iterdir()):
            if f.is_file() and f.suffix in ('.tsx', '.ts') and '.test.' not in f.name:
                lc = count_lines(f)
                desc = get_description(f.name, f.name)
                lines.append(f"| `{f.name}` | {lc} | {desc} |")
    lines.append("")

    lines.append("### 패널 컴포넌트 (components/panels/)")
    lines.append("| 패널 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    panels_dir = comp_dir / "panels" if comp_dir.exists() else None
    if panels_dir and panels_dir.exists():
        for f in sorted(panels_dir.iterdir()):
            if f.is_file() and f.suffix == '.tsx':
                lc = count_lines(f)
                desc = get_description(f.name, f.name)
                lines.append(f"| `{f.name}` | {lc} | {desc} |")
    lines.append("")

    # ── 5. 테스트 ──
    lines.append("## 🧪 테스트 (tests/)")
    lines.append("| 파일 | 줄 수 | 테스트 대상 |")
    lines.append("|------|------|------------|")
    tests_dir = PROJECT_ROOT / "tests"
    test_targets = {
        "test_agent_api.py": "api/agent_api.py",
        "test_dispatcher_loop.py": "scripts/auto_dispatcher.py + scripts/itcp.py",
        "test_itcp_context.py": "scripts/itcp.py 컨텍스트 빌딩",
        "test_itcp_fallback.py": "scripts/itcp.py 폴백 경로",
    }
    if tests_dir.exists():
        for f in sorted(tests_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name.startswith('test_'):
                lc = count_lines(f)
                target = test_targets.get(f.name, "")
                lines.append(f"| `{f.name}` | {lc} | {target} |")
    # 프론트엔드 테스트
    if comp_dir and comp_dir.exists():
        for f in comp_dir.rglob('*.test.tsx'):
            lc = count_lines(f)
            lines.append(f"| `{f.name}` | {lc} | {f.stem.replace('.test', '')} 컴포넌트 |")
    lines.append("")

    # ── 6. 빌드/CI ──
    lines.append("## 🏗️ 빌드 & CI")
    lines.append("| 파일 | 설명 |")
    lines.append("|------|------|")
    build_files = [
        ("vibe-coding.spec", "PyInstaller 실행 파일 빌드 설정"),
        ("vibe-coding-setup.iss", "Inno Setup 인스톨러 생성 스크립트"),
        (".github/workflows/build-release.yml", "GitHub Actions 빌드 & 릴리즈 워크플로우"),
        ("run_vibe.bat", "하이브 서버 및 대시보드 실행 배치 파일"),
    ]
    for path, desc in build_files:
        fp = PROJECT_ROOT / path
        if fp.exists():
            lines.append(f"| `{path}` | {desc} |")
    lines.append("")

    # ── 통계 ──
    lines.append("---")
    lines.append(f"> 자동 생성 완료: {now}")

    # 파일 작성
    output = PROJECT_ROOT / "PROJECT_MAP.md"
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"✅ PROJECT_MAP.md 갱신 완료 ({len(lines)}줄)")


if __name__ == '__main__':
    generate()
