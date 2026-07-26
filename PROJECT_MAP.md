# 🗺️ Vibe Coding 프로젝트 맵 (PROJECT_MAP.md)

> 자동 생성: `python scripts/generate_project_map.py` | 2026-07-26 10:18
> 문서 드리프트 방지를 위해 파일 시스템을 스캔하여 자동 갱신합니다.

## 📜 루트 문서
| 파일 | 설명 |
|------|------|
| `AGENTS.md` | 멀티 에이전트 설정 및 협업 프로토콜 정의 |
| `CHANGELOG.md` |  |
| `CLAUDE.md` | Claude Code 전용 프로젝트 가이드 |
| `CODEX_GUIDE.md` | 코덱스(Codex) 에이전트 퀵 스타트 및 통합 사용 설명서 |
| `GEMINI.md` |  |
| `HIVEMIND.md` | 하이브 마인드 실시간 상태 문서 (자동 생성) |
| `PORTING_MAC.md` |  |
| `PROJECT_MAP.md` | 프로젝트 전체 지도 및 파일 역할 가이드 (이 파일) |
| `README.md` |  |
| `RULES.md` | 에이전트 행동 수칙, 한글 주석/커밋 표준, 하이브 마인드 운영 원칙 |
| `ai_monitor_plan.md` | 하이브 마인드 고도화 및 신규 기능 구현 로드맵 |
| `memory.md` |  |
| `docs/API_SPEC.md` | REST API 엔드포인트 및 통신 규격 상세 명세 |
| `docs/CLAUDE_CODE_AGENT_TEAMS_ANALYSIS.md` |  |
| `docs/CODEX_HARDENING.md` | Codex 경로 고도화 적용 내용과 재적용 조건 |
| `docs/CODEX_RUNTIME_SETUP.md` | 설치 후 PC별 Codex 런타임 설정 및 운영 가이드 |
| `docs/HARNESS_CHECKS.md` |  |
| `docs/HARNESS_V1.md` |  |
| `docs/HARNESS_V2.md` |  |
| `docs/METAVERSE_OFFICE_DESIGN.md` |  |
| `docs/PLATFORM_LAYERS.md` |  |
| `docs/TERMINAL3_SCROLL_ISSUE.md` |  |
| `docs/VIBE_CONVENTIONS.md` |  |
| `docs/VIBE_PROJECT_GUIDE.md` | 하이브 마인드 운영 및 아키텍처 통합 가이드 |

## 🖥️ 서버 & API (.ai_monitor/)
### 서버 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `server.py` | 2016 | 중앙 HTTP 서버 (모든 API 라우팅, SSE, PostgreSQL 연동) |
| `boot.py` | 302 | EXE 진입점 부트스트랩 (A안) — 관리 체크아웃/seed에서 server.py를 runpy 실행 |
| `soft_updater.py` | 284 | 경량 소스 업데이트 채널 — GitHub SHA 감지 + git reset 적용/롤백 |
| `_version.py` | 1 | 버전 진실의 원천 (__version__) |
| `mission_control.py` | 414 | CMUX 스타일 시스템 트레이 및 HUD 관제 센터 |
| `mission_control_ui.py` | 496 | 슬라이드인 사이드바 HUD (에이전트 상태 링) |
| `soft_manifest.json` (루트) | 6 | soft 채널 풀빌드 게이트 (min_exe — 의존성 변경 시 소스 업데이트 차단) |

### API 모듈 (.ai_monitor/api/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `_common.py` | 49 |  |
| `agent_api.py` | 1393 | CLI 에이전트 관리 API (/api/agent/*) |
| `codegraph_api.py` | 220 |  |
| `commands_api.py` | 54 |  |
| `config_api.py` | 96 |  |
| `dashboard_api.py` | 132 |  |
| `events_api.py` | 103 |  |
| `experience_api.py` | 226 |  |
| `files_api.py` | 216 | 파일 API (/api/files/*, /api/read-file, /api/save-file) — server.py에서 분리 |
| `fs_dialog_api.py` | 147 |  |
| `git_api.py` | 235 | Git 저장소 관리 API (/api/git/*) |
| `heal_api.py` | 30 |  |
| `hive_api.py` | 1301 | 하이브 마인드 오케스트레이션 API (/api/hive/*, /api/orchestrator/*) |
| `hive_ingest_api.py` | 142 |  |
| `install_api.py` | 421 |  |
| `lan_api.py` | 475 |  |
| `launch_api.py` | 102 |  |
| `locks_api.py` | 67 |  |
| `logs_api.py` | 168 |  |
| `memory_api.py` | 412 | 메모리/지식 저장소 API (/api/memory/*) |
| `message_api.py` | 92 |  |
| `office_api.py` | 370 |  |
| `office_launch_api.py` | 84 |  |
| `office_proxy_api.py` | 230 |  |
| `projects_api.py` | 69 |  |
| `pty_api.py` | 246 | PTY 터미널 제어 API (/api/pty/*) |
| `screenshot_api.py` | 45 |  |
| `setup_api.py` | 48 |  |
| `static_api.py` | 123 |  |
| `tasks_api.py` | 302 | 태스크 API (/api/tasks/*) — server.py에서 분리 |
| `telegram_api.py` | 227 |  |
| `tools_api.py` | 1068 |  |
| `update_api.py` | 213 |  |
| `vibe_api.py` | 295 | Vibe CLI 상태 관리 API (/api/vibe/*) |
| `vibe_skills_api.py` | 246 |  |
| `zettel_api.py` | 203 |  |

### 데이터 계층 (.ai_monitor/src/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `claude_quota.py` | 162 |  |
| `code_indexer.py` | 552 |  |
| `code_search.py` | 200 |  |
| `codex_quota.py` | 216 |  |
| `db.py` | 42 |  |
| `db_helper.py` | 114 |  |
| `file_store.py` | 229 | 파일 기반 레거시 저장소 |
| `heal_metrics.py` | 273 |  |
| `lan_discovery.py` | 120 |  |
| `lan_peers.py` | 221 |  |
| `logger.py` | 130 |  |
| `pg_base.py` | 538 |  |
| `pg_experience.py` | 226 |  |
| `pg_incidents.py` | 182 |  |
| `pg_lan.py` | 85 |  |
| `pg_memory.py` | 639 |  |
| `pg_office.py` | 320 |  |
| `pg_schema.py` | 817 |  |
| `pg_store.py` | 127 | PostgreSQL 데이터 저장소 (스키마 관리 + 쿼리) |
| `pg_tasks.py` | 388 |  |
| `pg_vector_search.py` | 224 |  |
| `recall_client.py` | 83 |  |
| `secure.py` | 59 |  |
| `server_locator.py` | 76 |  |
| `server_utils.py` | 59 |  |
| `wiki_generator.py` | 381 |  |
| `zettelkasten.py` | 459 |  |

## ⚙️ 스크립트 (scripts/)
### 에이전트/터미널
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `cli_agent.py` | 1151 | Claude/Antigravity/Codex CLI 자율 오케스트레이션 엔진 |
| `agent_shell.py` | 431 | 인터랙티브 자율 에이전트 쉘 (REPL) |
| `terminal_agent.py` | 411 | 멀티터미널 자율 에이전트 디스패처 |
| `agent_launcher.py` | 242 | 통합 에이전트 런처 (NORMAL/YOLO 모드) |
| `agent_detector.py` | 198 | 활성 AI 에이전트 자동 감지 (psutil) |
| `agent_protocol.py` | 373 | RFC 관리 + 하이브 토론 프로토콜 |

### 하이브/협업
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `orchestrator.py` | 538 | 하이브 태스크 스케줄링 및 에이전트 감시 |
| `hive_debate.py` | 428 | 에이전트 간 의견 조율 토론 워크플로우 |
| `hive_bridge.py` | 213 | PostgreSQL 18 기반 하이브 통합 로깅 |
| `memory.py` | 317 | PostgreSQL 기반 하이브 메모리 CLI |
| `worktree_manager.py` | 349 | Git Worktree 격리 관리자 |
| `generate_hivemind_doc.py` | 323 | HIVEMIND.md 자동 생성기 |
| `analyze_hive.py` | 66 | 하이브 실시간 상태 분석 보고서 |

### 훅/이벤트
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_hook.py` | 1009 | Claude Code 자동 액션 트레이스 훅 (의도 감지) |
| `hook_bridge.py` | 582 | Claude Code UserPromptSubmit 훅 브릿지 |
| `claude_hook.py` | 297 | Claude Code PostToolUse/Stop 훅 핸들러 |
| `antigravity_hook.py` | 595 | Gemini CLI 훅 + 대시보드 유지 + HIVEMIND.md 갱신 |

### 통신/ITCP
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `itcp.py` | 793 | PostgreSQL pg_messages 기반 ITCP 프로토콜 |
| `send_message.py` | 74 | ITCP 기반 터미널 간 메시지 전송 CLI |

### 검증/가드
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `safety_guard.py` | 378 | Bounded Autonomy 위험 명령 탐지 (60+ 패턴) |
| `completion_guard.py` | 273 | Harness continue:false 완료 신호 감지 |
| `drift_detector.py` | 270 | ai_monitor_plan.md 이탈 감지기 |
| `plan_validator.py` | 232 | Harness 계획 검증 엔진 (V1-V5) |
| `rules_validator.py` | 150 | RULES.md 준수 자동 검증 |

### 스킬 관리
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `skill_orchestrator.py` | 463 | 스킬 체인 상태 추적 (hive_skill_chains 테이블 기반) |
| `skill_manager.py` | 129 | Antigravity/Claude 스킬 통합 관리자 |
| `skill_analyzer.py` | 359 | 반복 패턴 감지 + 자기치유 스킬 업데이트 |
| `skill_predictor.py` | 187 | 마르코프 체인 기반 다음 스킬 예측 |
| `skill_ab_test.py` | 208 | 스킬 A/B 테스트 + 성능 분석 |

### 모니터링
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_watchdog.py` | 562 | 자가 치유(3계층) 엔진 + skill_analyzer 트리거 |
| `claude_watchdog.py` | 204 | Claude 에이전트 행(hang) 오류 감지 + 재시작 |

### 유틸리티
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `vibe_cli.py` | 345 | cmux 호환 vibe CLI (notify/set-progress/codex) |
| `task.py` | 172 | 하이브 태스크 CLI (create/list/update) |
| `auto_version.py` | 82 | 버전 자동 증가 (patch +1) 유틸리티 |
| `auto_release.py` | 77 | 자율 배포(Autonomous Release) 엔진 |
| `lock_manager.py` | 103 | 파일 수정 충돌 방지 잠금 (JSON 기반) |
| `osc_parser.py` | 257 | OSC 시퀀스 파서 (Kitty/RXVT 알림) |
| `git_visualizer.py` | 65 | Git 워크트리/브랜치 시각화 |
| `screenshot_analyzer.py` | 154 | Antigravity Vision 기반 스크린샷 버그 감지 |
| `generate_project_map.py` | 499 | PROJECT_MAP.md 자동 생성 스크립트 (이 파일) |

### 인프라
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `pg_manager.py` | 269 | 포터블 PostgreSQL 18 + pgvector 통합 관리자 |
| `setup_hive_pg.py` | 133 | PostgreSQL 18 + pgvector 자동 설치 |
| `install_codex.py` | 85 | Codex CLI npm 설치 및 검증 |

### 기타
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `antigravity_adapter.py` | 138 |  |
| `antigravity_output_filter.py` | 78 |  |
| `antigravity_session_repair.py` | 216 |  |
| `auto.py` | 76 |  |
| `auto_metrics.py` | 201 |  |
| `build_verify.py` | 645 |  |
| `checkpoint.py` | 62 |  |
| `codex_pg_watcher.py` | 286 |  |
| `harness_verify.py` | 437 |  |
| `heal_report.py` | 100 |  |
| `incident.py` | 132 |  |
| `install_dev_tools.py` | 159 |  |
| `install_frontend_deps.py` | 195 |  |
| `install_gh_cli.py` | 154 |  |
| `install_harness.py` | 331 |  |
| `install_hive_hooks.py` | 307 |  |
| `install_nodejs.py` | 135 |  |
| `install_npm_tool.py` | 92 |  |
| `install_playwright_cli.py` | 65 |  |
| `install_psql.py` | 189 |  |
| `install_skills.py` | 195 |  |
| `install_statusline.py` | 112 | 상태줄 ~/.claude 멱등 설치기 (PC 간 이식) |
| `install_system_tool.py` | 208 |  |
| `intent_map.py` | 175 |  |
| `lesson.py` | 170 |  |
| `migrate_antigravity_db.py` | 83 |  |
| `migrate_archive_session_summaries.py` | 70 |  |
| `migrate_vault_consolidate.py` | 240 |  |
| `pg_project.py` | 39 |  |
| `recall.py` | 51 |  |
| `run_antigravity_clean.py` | 130 |  |
| `session_init.py` | 246 |  |
| `smoke_test.py` | 282 |  |
| `statusline.py` | 189 | Claude Code 상태줄 원본 (install_statusline.py가 ~/.claude로 배포) |
| `telegram_agent_bot.py` | 1347 |  |
| `telegram_bridge.py` | 466 |  |
| `telegram_helpers.py` | 324 |  |
| `test_pg_logging.py` | 71 | PostgreSQL 로깅 테스트 |
| `zettel_capture.py` | 701 |  |
| `zettel_sync.py` | 876 |  |

## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)
### 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `App.tsx` | 1003 | 최상위 레이아웃 오케스트레이터 (레이아웃 모드, 사이드바, 폴링 조율) |
| `main.tsx` | 75 |  |
| `types.ts` | 206 |  |
| `constants.tsx` | 93 |  |

### 컴포넌트 (components/)
| 컴포넌트 | 줄 수 | 설명 |
|----------|------|------|
| `ActivityBar.tsx` | 187 | 좌측 아이콘 바 (HiveEngineStatus LED 링 통합) |
| `ChatSlot.tsx` | 597 |  |
| `FileExplorer.tsx` | 557 | 파일 시스템 탐색기 (트리/플랫 뷰) |
| `FilePathText.tsx` | 110 | 파일 경로 렌더링 (클릭 가능 링크화) |
| `FileTreeNode.tsx` | 165 | 파일 트리 노드 (재귀 폴더 확장) |
| `FloatingWindow.tsx` | 221 | 파일 에디터 부유 창 (드래그/리사이즈) |
| `SetupBanner.tsx` | 152 |  |
| `TerminalSlot.tsx` | 1096 | 단일 터미널 슬롯 (XTerm.js + WebSocket + 에이전트 선택) |
| `ThoughtTrace.tsx` | 108 | AI 사고 로그 표시 |
| `TopMenuBar.tsx` | 574 | VS Code 스타일 메뉴바 (파일/편집/보기/AI 도구) |
| `VibeEditor.tsx` | 141 | 코드 에디터 래퍼 (Monaco Editor) |

### 패널 컴포넌트 (components/panels/)
| 패널 | 줄 수 | 설명 |
|------|------|------|
| `AgentTerminalCard.tsx` | 256 |  |
| `GitPanel.tsx` | 250 | Git 통합 (브랜치, 스테이징, 커밋) |
| `HealPanel.tsx` | 129 |  |
| `HivePanel.tsx` | 464 | 하이브 시스템 진단 (헬스 체크, 자가 치유) |
| `LanPanel.tsx` | 530 |  |
| `MemoryPanel.tsx` | 469 | 공유 지식 베이스 (PostgreSQL) |
| `TasksPanel.tsx` | 495 | 에이전트 간 태스크 큐 |
| `TelegramPanel.tsx` | 278 |  |
| `ToolsPanel.tsx` | 407 |  |
| `ZettelkastenPanel.tsx` | 537 |  |

## 🧪 테스트 (tests/)
| 파일 | 줄 수 | 테스트 대상 |
|------|------|------------|
| `test_agent_api.py` | 298 | api/agent_api.py |
| `test_codex_harness_v2.py` | 86 |  |
| `test_codex_orchestration.py` | 114 |  |
| `test_codex_pg_watcher.py` | 108 |  |
| `test_harness_verify.py` | 218 |  |
| `test_itcp_context.py` | 72 | scripts/itcp.py 컨텍스트 빌딩 |
| `test_itcp_fallback.py` | 226 | scripts/itcp.py 폴백 경로 |
| `test_knowledge_pipeline.py` | 133 |  |
| `test_new_api_modules.py` | 341 |  |
| `test_orchestrator_monitor.py` | 64 |  |
| `test_pg_store_split.py` | 124 |  |
| `test_route_table.py` | 106 |  |
| `test_self_heal_2.py` | 231 |  |
| `test_telegram_hub.py` | 347 |  |
| `test_updater_release_path.py` | 229 |  |
| `test_vibe_cli_codex.py` | 42 |  |
| `test_zettel_sync_mirror.py` | 42 |  |
| `FileExplorer.test.tsx` | 136 | FileExplorer 컴포넌트 |

## 🤖 Claude 통합 (.claude/)
### Skills (.claude/skills/) — Slash 명령 워크플로우
| 스킬 | 설명 |
|------|------|
| `vibe-brainstorm` | 모든 기능 구현 전 필수 단계. 요구사항을 정제하고 설계를 승인받습니다. 승인 전 코드 작성 금지. |
| `vibe-code-review` | 코드 품질, 성능, 가독성을 3가지 관점에서 검토합니다. 보안 심층 점검은 /vibe-security를 사용하세요. |
| `vibe-debug` | 버그의 근본 원인을 4단계로 분석합니다. 증상이 아닌 원인을 수정합니다. |
| `vibe-execute-plan` | ai_monitor_plan.md의 계획을 순서대로 실행합니다. 계획 외 작업 추가 금지. |
| `vibe-harness-init` | 하네스 V2를 새 프로젝트에 자동 설치합니다. AGENTS.md / RULES.md / HARNESS_V2.md / |
| `vibe-heal` | 자기치유 스킬. 반복 오류 패턴을 감지하고 근본 원인을 수정하여 재발을 방지합니다. |
| `vibe-orchestrate` | Vibe Coding 통합 컨트롤 타워. 하이브 컨텍스트 로드 + 요청 분석 + 스킬 체인 자동 실행 + 자기치유. |
| `vibe-release` | 설치본 빌드 릴리즈 파이프라인 (Windows .exe + macOS .dmg). 버전 증가 → 커밋 → 푸시 → |
| `vibe-security` | OWASP Top 10 기반 보안 취약점을 4단계로 점검합니다. 배포 전 필수 보안 검토. |
| `vibe-share` | LAN 자동 공유 — 작업한 파일과 세션 요약을 같은 네트워크의 페어링된 내 다른 PC로 전송. |
| `vibe-tdd` | RED-GREEN-REFACTOR 사이클로 테스트 주도 개발을 진행합니다. |
| `vibe-write-plan` | 승인된 아이디어를 마이크로태스크로 분해하여 ai_monitor_plan.md에 저장합니다. |
| `vibe-zettel` | 제텔카스텐 지식 관리 스킬. 노트 캡처, 정제(fleeting→permanent 승격), 유사 노트 연결, 검색, Obsidian 동기화. |

### Subagents (.claude/agents/) — 위임 대상
| Agent | 매핑 스킬 |
|-------|-----------|
| `code-reviewer` | /vibe-code-review |
| `debugger` | /vibe-debug |
| `security-auditor` | /vibe-security |

> 라우팅 정책 상세: [`.claude/agents/README.md`](.claude/agents/README.md)

## 🏗️ 빌드 & CI
| 파일 | 설명 |
|------|------|
| `vibe-coding.spec` | PyInstaller 실행 파일 빌드 설정 |
| `vibe-coding-setup.iss` | Inno Setup 인스톨러 생성 스크립트 |
| `.github/workflows/build-release.yml` | GitHub Actions 빌드 & 릴리즈 워크플로우 |
| `run_vibe.bat` | 하이브 서버 및 대시보드 실행 배치 파일 |

---
> 자동 생성 완료: 2026-07-26 10:18
