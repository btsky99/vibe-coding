# 🗺️ Vibe Coding 프로젝트 맵 (PROJECT_MAP.md)

> 자동 생성: `python scripts/generate_project_map.py` | 2026-03-29 23:08
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
| `docs/TERMINAL3_SCROLL_ISSUE.md` |  |
| `docs/VIBE_PROJECT_GUIDE.md` | 하이브 마인드 운영 및 아키텍처 통합 가이드 |

## 🖥️ 서버 & API (.ai_monitor/)
### 서버 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `server.py` | 5176 | 중앙 HTTP 서버 (모든 API 라우팅, SSE, PostgreSQL 연동) |
| `_version.py` | 8 | 버전 진실의 원천 (__version__) |
| `mission_control.py` | 434 | CMUX 스타일 시스템 트레이 및 HUD 관제 센터 |
| `mission_control_ui.py` | 495 | 슬라이드인 사이드바 HUD (에이전트 상태 링) |

### API 모듈 (.ai_monitor/api/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `agent_api.py` | 1268 | CLI 에이전트 관리 API (/api/agent/*) |
| `dispatcher_api.py` | 194 | 디스패처 API (/api/dispatcher/*) — server.py에서 분리 |
| `files_api.py` | 211 | 파일 API (/api/files/*, /api/read-file, /api/save-file) — server.py에서 분리 |
| `git_api.py` | 176 | Git 저장소 관리 API (/api/git/*) |
| `hive_api.py` | 980 | 하이브 마인드 오케스트레이션 API (/api/hive/*, /api/orchestrator/*) |
| `memory_api.py` | 168 | 메모리/지식 저장소 API (/api/memory/*) |
| `pty_api.py` | 169 | PTY 터미널 제어 API (/api/pty/*) |
| `setup_api.py` | 48 |  |
| `tasks_api.py` | 235 | 태스크 API (/api/tasks/*) — server.py에서 분리 |
| `vibe_api.py` | 312 | Vibe CLI 상태 관리 API (/api/vibe/*) |

### 데이터 계층 (.ai_monitor/src/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `db.py` | 34 |  |
| `db_helper.py` | 106 |  |
| `file_store.py` | 220 | 파일 기반 레거시 저장소 |
| `logger.py` | 123 |  |
| `pg_store.py` | 1034 | PostgreSQL 데이터 저장소 (스키마 관리 + 쿼리) |
| `secure.py` | 52 |  |
| `view.py` | 243 |  |

## ⚙️ 스크립트 (scripts/)
### 에이전트/터미널
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `cli_agent.py` | 1211 | Claude/Gemini/Codex CLI 자율 오케스트레이션 엔진 |
| `agent_shell.py` | 436 | 인터랙티브 자율 에이전트 쉘 (REPL) |
| `terminal_agent.py` | 391 | 멀티터미널 자율 에이전트 디스패처 |
| `agent_launcher.py` | 227 | 통합 에이전트 런처 (NORMAL/YOLO 모드) |
| `agent_detector.py` | 198 | 활성 AI 에이전트 자동 감지 (psutil) |
| `agent_protocol.py` | 373 | RFC 관리 + 하이브 토론 프로토콜 |
| `gemini_responder.py` | 85 | Gemini CLI 자동 응답기 |

### 하이브/협업
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `auto_dispatcher.py` | 806 | 역량 기반 자동 작업 분배 + 크로스 검증 |
| `orchestrator.py` | 536 | 하이브 태스크 스케줄링 및 에이전트 감시 |
| `hive_debate.py` | 428 | 에이전트 간 의견 조율 토론 워크플로우 |
| `hive_bridge.py` | 178 | PostgreSQL 18 기반 하이브 통합 로깅 |
| `memory.py` | 230 | PostgreSQL 기반 하이브 메모리 CLI |
| `worktree_manager.py` | 349 | Git Worktree 격리 관리자 |
| `generate_hivemind_doc.py` | 323 | HIVEMIND.md 자동 생성기 |
| `analyze_hive.py` | 60 | 하이브 실시간 상태 분석 보고서 |

### 훅/이벤트
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_hook.py` | 1023 | Claude Code 자동 액션 트레이스 훅 (의도 감지) |
| `hook_bridge.py` | 494 | Claude Code UserPromptSubmit 훅 브릿지 |
| `claude_hook.py` | 208 | Claude Code PostToolUse/Stop 훅 핸들러 |
| `gemini_hook.py` | 629 | Gemini CLI 훅 + 대시보드 유지 + HIVEMIND.md 갱신 |

### 통신/ITCP
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `itcp.py` | 687 | PostgreSQL pg_messages 기반 ITCP 프로토콜 |
| `vibe_mux.py` | 619 | cmux-style Named Pipe 멀티플렉서 서버 |
| `vibe_mux_agent.py` | 524 | 터미널별 MUX 에이전트 수신/실행 루프 |
| `send_message.py` | 74 | ITCP 기반 터미널 간 메시지 전송 CLI |
| `megaphone.py` | 36 | 하이브 브로드캐스트 메시지 유틸 |

### 검증/가드
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `safety_guard.py` | 378 | Bounded Autonomy 위험 명령 탐지 (60+ 패턴) |
| `completion_guard.py` | 273 | Harness continue:false 완료 신호 감지 |
| `drift_detector.py` | 270 | ai_monitor_plan.md 이탈 감지기 |
| `plan_validator.py` | 232 | Harness 계획 검증 엔진 (V1-V5) |
| `rules_validator.py` | 147 | RULES.md 준수 자동 검증 |

### 스킬 관리
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `skill_orchestrator.py` | 463 | 스킬 체인 상태 추적 (hive_skill_chains 테이블 기반) |
| `skill_manager.py` | 129 | Gemini/Claude 스킬 통합 관리자 |
| `skill_analyzer.py` | 359 | 반복 패턴 감지 + 자기치유 스킬 업데이트 |
| `skill_predictor.py` | 187 | 마르코프 체인 기반 다음 스킬 예측 |
| `skill_ab_test.py` | 208 | 스킬 A/B 테스트 + 성능 분석 |

### 모니터링
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_watchdog.py` | 567 | 자가 치유(3계층) 엔진 + skill_analyzer 트리거 |
| `claude_watchdog.py` | 204 | Claude 에이전트 행(hang) 오류 감지 + 재시작 |
| `heal_daemon.py` | 128 | pg_logs 감시 + 에러 자동 수리 |
| `terminal_status.py` | 73 | 터미널 상태 모니터 |

### 유틸리티
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `vibe_cli.py` | 308 | cmux 호환 vibe CLI (notify/set-progress/codex) |
| `task.py` | 172 | 하이브 태스크 CLI (create/list/update) |
| `auto_version.py` | 82 | 버전 자동 증가 (patch +1) 유틸리티 |
| `auto_release.py` | 77 | 자율 배포(Autonomous Release) 엔진 |
| `lock_manager.py` | 103 | 파일 수정 충돌 방지 잠금 (JSON 기반) |
| `osc_parser.py` | 257 | OSC 시퀀스 파서 (Kitty/RXVT 알림) |
| `git_visualizer.py` | 65 | Git 워크트리/브랜치 시각화 |
| `screenshot_analyzer.py` | 154 | Gemini Vision 기반 스크린샷 버그 감지 |
| `generate_project_map.py` | 426 | PROJECT_MAP.md 자동 생성 스크립트 (이 파일) |

### 인프라
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `pg_manager.py` | 269 | 포터블 PostgreSQL 18 + pgvector 통합 관리자 |
| `setup_hive_pg.py` | 133 | PostgreSQL 18 + pgvector 자동 설치 |
| `install_codex.py` | 85 | Codex CLI npm 설치 및 검증 |

### 마이그레이션
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `migrate_memory_to_pg.py` | 83 | SQLite → PostgreSQL 데이터 이관 |
| `migrate_sqlite_to_files.py` | 127 | SQLite → 파일 시스템 마이그레이션 |

### 기타
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `build_verify.py` | 637 |  |
| `gemini_output_filter.py` | 78 |  |
| `gemini_session_repair.py` | 216 |  |
| `harness_verify.py` | 170 |  |
| `install_playwright_cli.py` | 65 |  |
| `run_gemini_clean.py` | 130 |  |
| `telegram_bridge.py` | 1616 |  |
| `test_pg_logging.py` | 71 | PostgreSQL 로깅 테스트 |

## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)
### 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `App.tsx` | 1098 | 최상위 레이아웃 오케스트레이터 (레이아웃 모드, 사이드바, 폴링 조율) |
| `main.tsx` | 75 |  |
| `types.ts` | 157 |  |
| `constants.tsx` | 93 |  |

### 컴포넌트 (components/)
| 컴포넌트 | 줄 수 | 설명 |
|----------|------|------|
| `ActivityBar.tsx` | 195 | 좌측 아이콘 바 (HiveEngineStatus LED 링 통합) |
| `ChatSlot.tsx` | 607 |  |
| `FileExplorer.tsx` | 519 | 파일 시스템 탐색기 (트리/플랫 뷰) |
| `FilePathText.tsx` | 102 | 파일 경로 렌더링 (클릭 가능 링크화) |
| `FileTreeNode.tsx` | 165 | 파일 트리 노드 (재귀 폴더 확장) |
| `FloatingWindow.tsx` | 221 | 파일 에디터 부유 창 (드래그/리사이즈) |
| `MessageComposer.tsx` | 135 | 에이전트 간 메시지 작성 폼 |
| `SetupBanner.tsx` | 152 |  |
| `TerminalSlot.tsx` | 1468 | 단일 터미널 슬롯 (XTerm.js + WebSocket + 에이전트 선택) |
| `ThoughtTrace.tsx` | 108 | AI 사고 로그 표시 |
| `TopMenuBar.tsx` | 427 | VS Code 스타일 메뉴바 (파일/편집/보기/AI 도구) |
| `VibeEditor.tsx` | 140 | 코드 에디터 래퍼 (Monaco Editor) |

### 패널 컴포넌트 (components/panels/)
| 패널 | 줄 수 | 설명 |
|------|------|------|
| `AgentPanel.tsx` | 2934 | 자율 에이전트 통합 컨트롤 패널 (SSE 스트림, 워크플로우, 사고흐름) |
| `AgentTerminalCard.tsx` | 256 |  |
| `DispatcherPanel.tsx` | 436 | 멀티-LLM 디스패처 (역량 레이더 차트) |
| `GitPanel.tsx` | 250 | Git 통합 (브랜치, 스테이징, 커밋) |
| `GroupChatPanel.tsx` | 879 |  |
| `HivePanel.tsx` | 275 | 하이브 시스템 진단 (헬스 체크, 자가 치유) |
| `KanbanPanel.tsx` | 446 | 오케스트레이션 수평 파이프라인 뷰 |
| `MemoryPanel.tsx` | 374 | 공유 지식 베이스 (PostgreSQL) |
| `MessagesPanel.tsx` | 466 | 에이전트 간 메시지 채널 (채팅 버블 스타일) |
| `OrchestratorPanel.tsx` | 394 | 스킬 체인 현황판 |
| `SkillResultsPanel.tsx` | 492 | 스킬 실행 결과 (라이브 + 기록) |
| `TaskBoardPanel.tsx` | 460 | 칸반 스타일 태스크 보드 |
| `TasksPanel.tsx` | 375 | 에이전트 간 태스크 큐 |
| `TelegramPanel.tsx` | 243 |  |

## 🧪 테스트 (tests/)
| 파일 | 줄 수 | 테스트 대상 |
|------|------|------------|
| `test_agent_api.py` | 383 | api/agent_api.py |
| `test_codex_orchestration.py` | 77 |  |
| `test_dispatcher_loop.py` | 101 | scripts/auto_dispatcher.py + scripts/itcp.py |
| `test_harness_verify.py` | 80 |  |
| `test_itcp_context.py` | 72 | scripts/itcp.py 컨텍스트 빌딩 |
| `test_itcp_fallback.py` | 225 | scripts/itcp.py 폴백 경로 |
| `test_new_api_modules.py` | 467 |  |
| `FileExplorer.test.tsx` | 128 | FileExplorer 컴포넌트 |

## 🏗️ 빌드 & CI
| 파일 | 설명 |
|------|------|
| `vibe-coding.spec` | PyInstaller 실행 파일 빌드 설정 |
| `vibe-coding-setup.iss` | Inno Setup 인스톨러 생성 스크립트 |
| `.github/workflows/build-release.yml` | GitHub Actions 빌드 & 릴리즈 워크플로우 |
| `run_vibe.bat` | 하이브 서버 및 대시보드 실행 배치 파일 |

---
> 자동 생성 완료: 2026-03-29 23:08
