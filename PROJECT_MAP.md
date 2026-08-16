# 🗺️ vibe-coding 프로젝트 맵 (PROJECT_MAP.md)

> 자동 생성: `python scripts/generate_project_map.py` | 2026-08-17 01:03
> 문서 드리프트 방지를 위해 파일 시스템을 스캔하여 자동 갱신합니다.
> 설명은 각 파일의 표준 헤더(`DESCRIPTION:` / `📝`)에서 자동 수집합니다 — 여기 손으로 적지 말고 **파일 헤더를 고치세요**.

## 🧭 현재 상황 (내비게이션)

> 이 블록은 자동 생성된다. 파일 구조는 아래 지도, **작업 맥락은 여기**를 먼저 읽을 것.

- **브랜치**: `main` · 미커밋 48개 · 미푸시 3커밋
- **최근 커밋**
  - `2c8fdb8` 2026-08-17 — Merge remote-tracking branch 'origin/main'
  - `1d4d026` 2026-08-17 — fix(voice): 설치본에서 설치 절차를 못 찾던 경로 + 빌드는 지켜보지 말고 통보받는다
  - `4a72c5a` 2026-08-17 — feat(voice): 깐 직후 사장님 목소리가 나게 — 살림은 동봉, 모델은 첫 실행 때 받는다
  - `3b14039` 2026-08-16 — chore(release): auto-bump version to v3.7.342 [skip ci]
  - `747ea9f` 2026-08-17 — perf(voice): 보드에서 완성한 Qwen 굽기를 바이브 코딩에 이식 — 첫 소리 7.18초 → 3.2초

### 📍 최근 체크포인트 (중단 지점)
- **08-17 00:10** 의도: 보드 Qwen TTS 이식 — 조각내 굽기+참조 지문
  - 결정: CUDA그래프는 같은 일꾼 파일 공유로 이미 상속됨. 워커는 별도(파이프 소유 구조라 공유 불가) — 몫 0.35로 캡
  - 다음: apix1-5가 ag_bake_now cache_key 맞추면 미리굽기 복구. 푸시/배포는 사장 결재 후
- **08-15 10:14** 의도: LLM 위키 전환 — 지식창고를 로그덤프에서 백과사전으로 재구축
  - 결정: wiki/를 git 추적 정본으로, 로컬만(GDrive 안씀), 전부삭제+원료전량 승인, 순서=회상버그수정→위키구축→인덱싱→lint→삭제
  - 다음: 블로커: vector_available()이 ALTER TABLE 실패시 조용히 False → 회상 전체 무력화. 이것부터 수정
- **08-15 00:54** 의도: 아픽스 음성(STT+TTS) 기능을 vibe-coding 터미널 슬롯에 이식
  - 결정: WebView2에서 SpeechRecognition 실동작 확인(onstart/onaudiostart, network에러 없음). 인식+낭독 전부, 터미널 슬롯 하단 입력창에 배선. 낭독 텍스트는 Stop훅 turn 채널 신설로 공급
  - 다음: voice_turn_hook.py + voice_api.py + 마이크 권한(app_boot) + 프론트 speech/voiceBus/useVoice/VoiceBar

### ⚠️ 최근 사고 (같은 실수 반복 금지)
- **바이브 코딩을 껐는데 약 30분마다 앱이 저절로 다시 뜬다**
  - 원인: 고아 hive_watchdog(앱의 자식인데 앱 강제종료 시 cleanup_child_procs가 안 돌아 생존)이 60초마다 server.py를 재기동. server.py __main__은 HTTP 서버가 아니라 GUI 앱 전체(main→app_boot.run_gui
  - 수정: infra/shutdown_marker.py 신설. 앱의 정상 종료 경로(webview.start 리턴 / api/shutdown / 헤드리스 Ctrl+C)에서만 표식을 남기고, 크래시·taskkill은 그 코드에 도달할 수 없다는 점을 판별 근거로 삼음. 워치독은 재
- **설치본 마이크 단추는 눌리는데 말이 서버로 안 감 + edge-tts 목소리 목록 안 보임**
  - 원인: 설치 체크아웃에 voice-server/.venv 가 없고 setup_voice.py 를 부르는 곳이 없어 사이드카 미기동. frozen 폴백은 EXE(2026-07-23)에 음성 패키지가 없어 무효. 프론트는 서버가 준 detail 을 버려 원인이 화면에 안 뜸
  - 수정: setup_voice.ensure_env(root, run) 분리 + voice_api 자동 설치(창 없이) + 번들 검증(find_spec) 후에만 EXE 실행기 + voiceBus 가 detail 노출. 커밋 44cf301
- **무관 질의 '오늘 점심 뭐 먹지'가 회상 차단선 0.85를 0.850으로 통과**
  - 원인: 임계값을 표본 9건으로 정해 아래 여유가 0.003뿐이었고, 위키 1021섹션이 인덱스에 들어오며 그 여유가 소진됨
  - 수정: 표본을 24건으로 확장 후 재측정하여 _FLOOR 0.86으로 상향 (be9c5ac). sweep 후보 구간도 e5 코사인 띠로 이동

🔨 = 최근 7일 내 변경된 파일

## 📜 루트 문서
| 파일 | 설명 |
|------|------|
| `AGENTS.md` | Hive agent entrypoint with principles only |
| `CHANGELOG.md` |  |
| `CLAUDE.md` | 프로젝트 루트의 자동 로드 규칙 파일. 모든 Claude/AI 세션 시작 시 자동 주입됨. |
| `CODEX_GUIDE.md` | 코덱스(Codex) 에이전트 퀵 스타트 및 통합 사용 설명서 |
| `GEMINI.md` | Antigravity CLI(agy)가 자동 로드하는 프로젝트 컨텍스트 파일. |
| `HIVEMIND.md` | 하이브 마인드 실시간 상태 문서 (자동 생성) |
| `PORTING_MAC.md` |  |
| `PROJECT_MAP.md` | ` / `📝`)에서 자동 수집합니다 — 여기 손으로 적지 말고 **파일 헤더를 고치세요**. |
| `README.md` |  |
| `RULES.md` | 프로젝트 내 모든 에이전트가 준수해야 할 핵심 행동 수칙 및 코드 스타일 가이드 |
| `ai_monitor_plan.md` | 바이브 코딩의 **현재 계획**. CLAUDE.md 가 작업 시작 전에 읽으라고 지정한 문서다. |
| `memory.md` | 프로젝트의 핵심 기술적 결정, 사용자 선호도, 아키텍처 원칙 및 과거의 실수/해결책 기록소. |
| `docs/AGENT_GRAPH.md` | 이 프로젝트의 **실행 그래프 선언** — 노드(일하는 단위) / 엣지(다음으로 가는 길) / |
| `docs/API_SPEC.md` | Vibe-Coding (AI Monitor) REST API 상세 명세서 |
| `docs/CIPHERTRADER_LLM_MULTI_AGENT_DESIGN.md` | CipherTrader Crypto를 LLM 주도 다중 에이전트 자동매매 시스템으로 전환하기 위한 누적 설계 문서 |
| `docs/CLAUDE_CODE_AGENT_TEAMS_ANALYSIS.md` |  |
| `docs/CODEX_HARDENING.md` | Codex 경로 고도화 적용 내용과 다른 Windows PC 배포 조건을 정리한 운영 문서. |
| `docs/CODEX_RUNTIME_SETUP.md` | Per-PC Codex runtime setup guide for installed or cloned Vibe Coding environments. |
| `docs/HARNESS_CHECKS.md` | harness_verify.py V2에서 수행하는 검사 항목 명세와 대응 방안. |
| `docs/HARNESS_DESIGN.md` | 하네스 설계 근거 — 컨텍스트 계측 실태, 세션 리사이클 상태머신, |
| `docs/HARNESS_V1.md` |  |
| `docs/HARNESS_V2.md` | Vibe Coding 멀티에이전트 하네스 V2 명세서. |
| `docs/METAVERSE_OFFICE_DESIGN.md` | Vibe Coding용 가상 메타버스 오피스 시스템 상세 설계 문서. |
| `docs/MIIX520_SERVER_MIGRATION_PLAN.md` | Lenovo Miix 520을 Vibe Coding 중앙 버스 서버로 전환하기 위한 설치·이전·운영 계획 |
| `docs/PLATFORM_LAYERS.md` | Vibe Coding 플랫폼의 레이어 경계 정의. |
| `docs/REMOTE_CONTROL.md` | 무료 원격제어(RustDesk 셀프호스트, 아픽스 서버 경유) 구축 구조와 기기별 운영 절차. |
| `docs/TERMINAL3_SCROLL_ISSUE.md` |  |
| `docs/VIBE_CONVENTIONS.md` | .vibe/ 디렉토리 규약 — Layer 2 확장(프로젝트별 스킬/에이전트/규칙)을 |
| `docs/VIBE_PROJECT_GUIDE.md` | Vibe-Coding (AI Monitor) 프로젝트의 전체 구조, 철학 및 운영 가이드 (v5.0 최신화) |
| `docs/voice-qwen-교체.md` |  |

## 🖥️ 서버 & API (.ai_monitor/)
### 서버 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `server.py` 🔨 | 2166 | 하이브 마인드 중앙 통제 서버 — 에이전트 간 통신 중계, 상태 모니터링, 데이터 영속성 관리. |
| `boot.py` 🔨 | 452 | 경량 소스 업데이트 채널(A안)의 EXE 진입점 부트스트랩. |
| `soft_updater.py` | 549 | 경량 소스 업데이트 채널(A안)의 감지/적용 모듈. |
| `_version.py` 🔨 | 1 | 앱 버전 단일 소스 (릴리즈 파이프라인이 자동 갱신 — 수동 편집 금지) |
| `mission_control.py` | 414 | AI 에이전트 전용 네이티브 윈도우 관제 센터 (Mission Control) — 시스템 트레이 및 사이드바 HUD 관리. |
| `mission_control_ui.py` | 496 | 미션 컨트롤 사이드바 HUD UI 컴포넌트 — 에이전트 상태 링 및 실시간 로그 시각화. |
| `soft_manifest.json` (루트) | 6 | soft 채널 풀빌드 게이트 (min_exe — 의존성 변경 시 소스 업데이트 차단) |

### API 모듈 (.ai_monitor/api/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `_common.py` | 60 | 설명: API 핸들러 공용 헬퍼. 8개 도메인 모듈에 복붙돼 있던 _json_response(8중복)와 |
| `agent_api.py` 🔨 | 1441 | 설명: CLI 오케스트레이터 자율 에이전트 REST API 핸들러. |
| `codegraph_api.py` | 220 | 코드 인텔리전스 REST API 핸들러. |
| `commands_api.py` | 54 | 터미널 명령 전송 API — 대상 슬롯의 Node PTY 세션에 명령을 큐잉한다(REST 프록시). |
| `config_api.py` | 96 | 앱 설정 갱신 API — config.json에 부분 업데이트(merge)하고, last_path 변경 시 |
| `daemons_api.py` | 73 | 백그라운드 데몬 on/off API — infra/daemons.py의 DAEMON_TOGGLES 레지스트리를 |
| `dashboard_api.py` | 132 | 대시보드/에이전트 라우트 3종 — GET /api/agents(인메모리+PG 병합), |
| `events_api.py` | 103 | SSE(text/event-stream) 실시간 스트리밍 핸들러 3종 — 사고과정/자율에이전트출력/FS변경. |
| `experience_api.py` | 226 | 설명: 에이전트 경험 수집 & 성장 시스템 REST API. |
| `files_api.py` | 216 | /api/files, /api/read-file, /api/save-file, /api/file-rename, |
| `fs_dialog_api.py` | 147 | 파일시스템 다이얼로그 / 탐색 라우트 모음 — server.py do_GET/do_POST에서 추출(Phase 2 R1). |
| `git_api.py` | 235 | /api/git/* 엔드포인트 핸들러 모듈. |
| `heal_api.py` | 30 | 자가치유 계측 API — GET /api/heal/metrics. src.heal_metrics.compute_heal_metrics를 |
| `hive_api.py` 🔨 | 1304 | /api/hive/*, /api/orchestrator/*, /api/install-skills, |
| `hive_ingest_api.py` | 142 | 하이브 수집(ingest) POST 핸들러 3종 — pg_logs 기록 / thought PG 기록 / |
| `install_api.py` | 442 | 다른 프로젝트에 Vibe Coding 스킬셋(.gemini/scripts/*.md)을 복사 설치하는 라우트 핸들러. |
| `lan_api.py` 🔨 | 583 | /api/lan/* 핸들러 — 프론트(127.0.0.1 로컬서버)가 LAN 브리지를 제어하는 통로. |
| `launch_api.py` | 102 | CLI 에이전트(claude/antigravity/codex) 실행 API — 새 cmd 창에서 에이전트를 띄운다. |
| `locks_api.py` | 67 | 파일 락 API — 에이전트 간 동시 편집 충돌 방지. locks.json에 {파일: 소유에이전트}를 |
| `logs_api.py` | 168 | 로그/메시지/실시간 로그 스트림 라우트 4종 — GET /stream(SSE), GET /api/server-logs, |
| `memory_api.py` 🔨 | 454 | Postgres-first memory API handlers. recall-smart(임베딩 통합 회상) 포함. |
| `message_api.py` 🔨 | 116 | 에이전트 간 메시지 전송 API — 메시지를 DB(send_message)에 저장하고, 수신 대상 |
| `nodes_api.py` 🔨 | 91 | 상태판(독립 창 + tui.py)의 콘솔 창 라우트 2종 — 전부 **이 PC 안**의 사실만 다룬다. |
| `office_api.py` | 370 | 오피스 모드 전용 API — 프로필 중앙화(PostgreSQL SSOT) + 클래식과 네임스페이스 분리. |
| `office_launch_api.py` | 84 | 오피스 독립 서버 실행 라우트 3종 — POST /api/office/launch(office_server 프로세스 |
| `office_proxy_api.py` | 230 | 오피스 서버(office_server.py) 프로세스 관리 + HTTP 프록시. |
| `projects_api.py` | 69 | 최근 프로젝트 목록 API — projects.json에 최근 연 프로젝트 경로를 MRU(최대 20개)로 |
| `pty_api.py` 🔨 | 255 | PTY 세션 상태 및 제어 엔드포인트 — Node PTY 서버 투명 프록시. |
| `recycle_api.py` 🔨 | 489 | 컨텍스트 리사이클 HTTP 계층 — 상태머신(src/session_recycle.py)에 |
| `screenshot_api.py` | 45 | 스크린샷 멀티모달 분석 API — POST /api/screenshot/analyze. |
| `setup_api.py` 🔨 | 195 | Setup Doctor API — 초기 설정 진단 상태를 대시보드에 제공. |
| `static_api.py` | 123 | 정적 파일 서빙 + 도움말/이미지 라우트 3종 — GET /api/help, GET /api/image-file, |
| `tasks_api.py` | 302 | /api/tasks/* 및 /api/task-logs 엔드포인트 핸들러 모듈. |
| `tools_api.py` 🔨 | 1374 | AI 도구 CLI 설치 관리 API. |
| `update_api.py` | 261 | 앱 업데이트 라우트 핸들러 모음 — EXE 풀빌드 채널(updater)과 경량 소스 채널(soft_updater) |
| `vibe_api.py` | 295 | 설명: cmux 호환 vibe CLI REST API 핸들러. |
| `vibe_skills_api.py` | 246 | Platform Phase 3 — .vibe/skills + .claude/skills 병합 스캐너. |
| `voice_api.py` 🔨 | 329 | 음성 API — 턴 채널 조회 + 음성 사이드카(STT/TTS) 프록시. |
| `wiki_api.py` 🔨 | 166 | LLM 위키 상태 조회 + 초기화 API. |
| `zettel_api.py` | 203 | Hive Zettelkasten REST API 핸들러. |

### 데이터 계층 (.ai_monitor/src/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `brief_limits.py` | 89 | 프롬프트 계열 텍스트(재정박·워커 브리프·체크포인트)의 글자 수 상한과 |
| `claude_quota.py` | 171 | Claude Code CLI의 OAuth 토큰을 재사용해 Anthropic 사용량 엔드포인트 |
| `code_indexer.py` | 552 | 설명: 코드 인텔리전스 인덱서 — tree-sitter AST 파싱으로 코드 노드/엣지 추출 |
| `code_search.py` | 200 | 설명: 코드 인텔리전스 검색 — PostgreSQL FTS 기반 BM25 검색 엔진 |
| `codex_context.py` | 122 | Codex CLI 세션의 현재 컨텍스트 점유율 파서. rollout jsonl의 |
| `codex_quota.py` | 216 | Codex CLI(OpenAI)의 플랜 쿼터 사용률(5h/7d %) 공급자. |
| `db.py` | 42 | 설명: 레거시 DB 진입점 (SQLite 런타임 저장소 폐기 잔재). get_connection()은 |
| `db_helper.py` | 113 | 설명: 세션 로그 기록 헬퍼 — pg_store(upsert_session_log/list_session_logs)로 |
| `file_store.py` | 229 | 설명: 레거시 파일 기반 저장소 폴백 (PostgreSQL 미가용 시). shared_memory.json / |
| `heal_metrics.py` 🔨 | 296 | 자가치유 계측 단일 소스 — 4장치(회상v2/사고장부/체크포인트/교훈)가 실제로 삽질을 |
| `job_verify.py` 🔨 | 92 | 일감 검수 — Phase 12 Task 54(git 실측 수집). |
| `lan_discovery.py` | 120 | LAN 자동발견 — UDP 브로드캐스트로 같은 네트워크의 다른 바이브코딩 브리지를 |
| `lan_peers.py` | 221 | LAN 브리지 페어링/신뢰 저장 + HMAC 토큰. 페어링은 '코드 기반 키 파생(PAKE류)' — |
| `lan_sandbox.py` | 310 | 원격 claude 실행의 폴더 격리 계층 — 허용 폴더 화이트리스트 검증 + |
| `logger.py` | 130 | 설명: 작업 세션 로깅 진입점. log_start()가 session_id 발급 + 민감정보 마스킹 |
| `pg_base.py` | 558 | 설명: PostgreSQL 연결 인프라 — 경로 결정, psycopg2 커넥션/풀, 쿼리 실행 프리미티브 |
| `pg_experience.py` | 226 | 설명: 에이전트 경험/성장(XP·레벨·스탯) + 유사 경험 회상 + pg_logs 활동 기록 |
| `pg_incidents.py` | 182 | 설명: 사고 장부(incident_ledger) — 고친 에러의 시그니처/근본원인/수정법 기록 + |
| `pg_lan.py` | 107 | LAN 브리지 채팅 이력(lan_messages) + 원격실행 감사로그(lan_exec_log) CRUD. |
| `pg_memory.py` | 639 | 설명: 하이브 메모리(hive_memory) CRUD + zettel 승격 + 세션 로그 + 채팅 + 지식 회상 |
| `pg_office.py` | 320 | 설명: 오피스 프로필 CRUD(PostgreSQL SSOT) + 활성 세션 컨텍스트(크래시 복구) |
| `pg_schema.py` | 828 | 설명: PostgreSQL 스키마 DDL(ensure_schema) + 레거시 JSONL/JSON 마이그레이션 |
| `pg_store.py` | 127 | 설명: PostgreSQL 저장소 파사드 — 분할된 pg_* 도메인 모듈을 단일 경로로 재노출 |
| `pg_tasks.py` | 388 | 설명: 하이브 태스크(hive_tasks) CRUD + 원자적 체크아웃 + 코멘트 + 하트비트 + 상태 저장 |
| `pg_vector_search.py` 🔨 | 364 | 설명: pgvector 기반 회상 v2 — embedding 컬럼 마이그레이션 + 코사인 검색 + |
| `quota_policy.py` | 117 | provider 쿼터 snapshot을 작업 크기 권고로 변환하는 순수 정책 계층. |
| `recall_client.py` | 83 | 설명: 훅(단명 프로세스)용 회상 클라이언트 — 서버 recall-smart API 우선, |
| `secure.py` | 59 | 설명: 보안 유틸 — 로그 민감정보 마스킹(API키/Bearer/패스워드 정규식), |
| `server_locator.py` | 76 | 설명: 9000번대 바이브 서버 포트 공용 탐색기 — /api/project-info 슬러그 대조로 |
| `server_utils.py` | 59 | 서버 공통 유틸리티 — 포트 탐색, CORS, JSON 응답 헬퍼. |
| `session_binding.py` 🔨 | 299 | claude 세션 jsonl ↔ PTY 슬롯 결속 + 터미널별 컨텍스트 점유율 계측. |
| `session_recycle.py` 🔨 | 236 | 컨텍스트 리사이클 상태머신 — 세션을 마감 기록으로 봉인하고 새 컨텍스트로 |
| `wiki_generator.py` | 381 | 설명: LLM 위키 자동생성 엔진 — code_nodes → 프롬프트 조립 → hive_tasks 등록 |
| `wiki_index.py` 🔨 | 276 | wiki/ 마크다운(정본)을 zettel_notes(검색 인덱스)로 밀어 넣는다. |
| `zettelkasten.py` | 459 | Hive Zettelkasten — 카파시 Append-Review-Rescue + 루만 제텔카스텐 융합 메모 시스템. |

### 인프라 계층 (.ai_monitor/infra/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `app_boot.py` 🔨 | 491 | PyWebView 데스크톱 앱 부팅 오케스트레이션. 스플래시 창을 먼저 띄우고 |
| `cli_commands.py` | 88 | server.py 진입 시 CLI 인자(--install / --uninstall / --create-shortcut) |
| `console_scan.py` | 438 | 화면에 떠 있는 콘솔 창(정체불명 검은 cmd 창)을 찾아 "누가 띄웠는지"를 판정한다. |
| `daemons.py` 🔨 | 1076 | 설명: 백그라운드 데몬 러너 — 워치독/리사이클 워처/오케스트레이터/문서 생성/ |
| `embed_service.py` 🔨 | 214 | fastembed 기반 임베딩 서비스 싱글톤 — 회상 v2(pgvector)의 심장. |
| `env_path.py` | 128 | 실행 중인 프로세스의 PATH를 Windows 레지스트리 + 알려진 CLI bin 디렉토리 기준으로 |
| `folder_dialog.py` 🔨 | 139 | 윈도우 네이티브 폴더 선택 다이얼로그(SHBrowseForFolderW, ctypes). |
| `fs_watcher.py` | 117 | 파일 시스템 실시간 감시(watchdog) + cli_agent 출력 브로드캐스트 워커. |
| `heartbeat_daemon.py` | 725 | 설명: 자율 클로드 심장 박동 데몬 — 사람이 부르지 않아도 주기적으로 깨어나 |
| `instance_lock.py` 🔨 | 308 | 단일 인스턴스 락 획득 + HTTP/WS 서버 포트 확정 로직. |
| `lifecycle.py` | 329 | 프로세스 라이프사이클 정리 함수 모음. |
| `memory_watcher.py` | 388 | 에이전트 메모리(Claude Code / Antigravity CLI) 파일 감시 + PostgreSQL |
| `postgres_runtime.py` | 300 | 내장 PostgreSQL 18 기동/초기화 런타임. 배포(frozen) 모드에서 |
| `proc.py` | 35 | Windows 콘솔 숨김 subprocess 공용 래퍼. 앱의 모든 subprocess 호출이 |
| `project_context.py` | 204 | Platform Phase 2-3 — 활성 프로젝트 컨텍스트 Resolver. |
| `pty_process.py` | 483 | Node.js PTY 서버 프로세스 관리 함수 모음. |
| `runtime.py` 🔨 | 204 | 시스템 런타임 보조 유틸 — Python 인터프리터 후보 탐색, |
| `session_parse.py` 🔨 | 163 | CLI 세션 파일(JSONL/JSON) 토큰 usage 파서 모음. |
| `shutdown_marker.py` 🔨 | 92 | '사람이 껐다'는 사실을 남기는 종료 의사 표식. 감시자(hive_watchdog)가 |
| `splash.py` | 37 | 부팅 스플래시 창 HTML 생성. WebView 창을 무거운 초기화(PG/PTY/HTTP) |
| `tool_install.py` | 317 | CLI 도구(Antigravity/Claude Code/Codex) 설치 상태 + 백그라운드 npm |
| `voice_turn.py` 🔨 | 113 | 음성 낭독용 '턴 채널' 저장소 — Stop 훅이 쓰고 /api/voice/turn 이 읽는다. |
| `webview_health.py` 🔨 | 196 | WebView2 엔진이 창에 실제로 붙었는지 감시하고, 안 붙었으면 원인을 진단해 |
| `webview_permissions.py` 🔨 | 178 | WebView2(Windows)에서 마이크 권한 요청을 허용하는 배선. |
| `win32_icon.py` | 49 | Windows 작업표시줄/타이틀바 아이콘 강제 설정. PyWebView가 생성한 창의 |

### 음성 사이드카 (.ai_monitor/voice-server/) — 별도 프로세스·별도 venv
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `engines/tts_cache.py` | 156 | 합성 결과 디스크 캐시 — 같은 문장을 두 번 만들지 않는다. |
| `engines/tts_edge.py` | 158 | edge-tts 낭독 어댑터. 텍스트 → MP3 바이트. 이 앱의 기본 낭독 경로다. |
| `engines/tts_qwen.py` | 710 | 낭독 엔진 — Qwen3-TTS 로 사장님 목소리를 복제해 읽는다. |
| `engines/tts_split.py` | 192 | 긴 글을 낭독 단위로 자른다 — 이어 굽기(첫 문장부터 틀고 뒤를 잇는 것)의 재료. |
| `qwen/qgraph.py` | 464 |  |
| `qwen/worker.py` | 333 |  |
| `voice_server.py` | 520 | 음성 사이드카 — STT(faster-whisper) / TTS(edge-tts 단일) 서버. |

## ⚙️ 스크립트 (scripts/)
### 에이전트/터미널
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `cli_agent.py` 🔨 | 1150 | 설명: CLI 오케스트레이터 자율 에이전트 핵심 엔진. |
| `agent_shell.py` | 431 | 터미널 전용 자율 에이전트 인터랙티브 쉘. |
| `terminal_agent.py` | 411 | 멀티터미널 자율 에이전트 디스패처 (REPL 모드). |
| `agent_launcher.py` | 242 | 통합 에이전트 런처. |
| `agent_detector.py` | 198 | 설명: 시스템에서 실행 중인 AI 코딩 에이전트를 자동 감지하는 모듈. |
| `agent_protocol.py` | 373 | 에이전트 간 협업을 위한 RFC 관리 + 하이브 토론 참여 프로토콜. |

### 하이브/협업
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `orchestrator.py` | 538 | 하이브 마인드 자동 조율 오케스트레이터 — 태스크 스케줄링, 에이전트 감시, 자동 배분. |
| `hive_debate.py` | 428 | 하이브 합의 및 토론 워크플로우 헬퍼 — 에이전트 간 의견 조율. |
| `hive_bridge.py` | 213 | PostgreSQL 18 기반 하이브 마인드 통합 로깅 및 협업 브릿지 (Postgres-First). |
| `memory.py` | 317 | Hive memory CLI backed by PostgreSQL. |
| `worktree_manager.py` | 349 | Git Worktree 격리 관리자 — 병렬 에이전트 격리 구현. |
| `generate_hivemind_doc.py` | 323 | HIVEMIND.md 자동 생성기 — 하이브 DB 신호로부터 문서를 재구성. |
| `analyze_hive.py` | 66 | PostgreSQL 18 기반 하이브 마인드 고도화 분석 도구 — 에이전트 작업 패턴, 사고 연쇄, 협업 효율성 분석. |

### 훅/이벤트
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_hook.py` | 1009 | Claude Code 자동 액션 트레이스 훅 핸들러. |
| `hook_bridge.py` | 634 | Claude Code UserPromptSubmit 훅 브릿지 — 자율 에이전트 디스패치 및 하이브 컨텍스트 자동 주입. |
| `claude_hook.py` | 297 | Claude Code 전용 자동 훅 핸들러. |
| `antigravity_hook.py` | 595 | Antigravity CLI hook integration. |

### 통신/ITCP
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `itcp.py` | 793 | Inter-Terminal Communication Protocol (ITCP) — PostgreSQL 기반 터미널 간 통신 코어. |
| `send_message.py` | 74 | 터미널 간 메시지 전송 헬퍼 스크립트. |

### 검증/가드
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `safety_guard.py` | 378 | Bounded Autonomy 및 위험 명령 탐지 엔진 — 시스템 파괴 명령 사전 차단. |
| `completion_guard.py` | 273 | 서브에이전트 완료 신호 자동 감지기 — Harness continue:false 패턴. |
| `drift_detector.py` | 276 | 계획 이탈 감지기 — 현재 작업이 ai_monitor_plan.md와 일치하는지 검증. |
| `plan_validator.py` | 232 | Harness 패턴 계획 검증 엔진 (V1-V5). |
| `rules_validator.py` | 150 | 프로젝트의 행동 원칙(RULES.md) 준수 여부를 자동으로 검증하는 스크립트. |

### 스킬 관리
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `skill_orchestrator.py` | 463 | PostgreSQL 기반 스킬 체인 트래커 — 스킬 실행 순서 및 성과 기록. |
| `skill_manager.py` | 129 | Antigravity CLI 및 Claude용 스킬 통합 관리자. |
| `skill_analyzer.py` | 359 | 작업 로그를 분석하여 반복되는 패턴을 감지하고, |
| `skill_predictor.py` | 187 | 예측적 스킬 실행 — 과거 스킬 체인 시퀀스를 분석하여 |
| `skill_ab_test.py` | 208 | 스킬 A/B 테스트 — 스킬별 성공/실패율을 분석하고 |

### 모니터링
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `hive_watchdog.py` 🔨 | 689 | 하이브 마인드(Hive Mind) 시스템 자가 치유(Self-Healing) 및 모니터링 엔진. |
| `claude_watchdog.py` | 204 | Claude 자율 에이전트 워치독 — 행 오류 감지 및 자동 재시작. |

### 유틸리티
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `vibe_cli.py` | 345 | 설명: cmux 호환 vibe CLI — 에이전트 알림/진행률/상태/로그를 제어하는 커맨드라인 도구. |
| `task.py` | 172 | 하이브 태스크 CLI — 태스크 생성, 조회, 상태 변경을 위한 명령줄 도구. |
| `auto_version.py` | 82 | 버전 자동 증가 유틸리티 — _version.py의 패치 버전을 자동으로 올림. |
| `auto_release.py` | 77 | 하이브 마인드 자율 배포(Autonomous Release) 엔진 — 빌드 및 인스톨러 자동화. |
| `lock_manager.py` | 103 | 에이전트 간 파일 수정 충돌을 방지하기 위한 파일 잠금(Lock) 관리 도구. |
| `osc_parser.py` | 257 | 설명: 터미널 출력 스트림에서 OSC(Operating System Command) 시퀀스를 감지하여 |
| `git_visualizer.py` | 65 | 에이전트가 현재 Git 워크트리, 브랜치 상태 및 최근 이력을 한눈에 파악하게 돕는 시각화 도구. |
| `screenshot_analyzer.py` | 154 | 멀티모달 버그 감지 — 스크린샷을 Antigravity Vision API로 분석하여 |
| `generate_project_map.py` 🔨 | 766 | PROJECT_MAP.md 자동 생성 스크립트. |

### 인프라
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `pg_manager.py` | 275 | 하이브 마인드 전용 포터블 PostgreSQL 통합 매니저. |
| `setup_hive_pg.py` | 133 | 하이브 마인드 전용 포터블 PostgreSQL 18 + pgvector 설치 및 초기화 스크립트. |
| `install_codex.py` | 85 | Codex CLI 설치 및 초기 설정 스크립트. |

### 기타
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `antigravity_adapter.py` | 138 | Antigravity CLI(agy) 호출 격리 레이어 — closed-source 인터페이스 변경 대비 |
| `antigravity_output_filter.py` | 78 | Antigravity CLI 내부 진단 로그를 사용자 출력에서 걸러내는 보조 필터. |
| `antigravity_session_repair.py` | 216 | Antigravity CLI 세션 히스토리 자동 수리 스크립트. |
| `audit_no_window.py` 🔨 | 164 | 규칙 10 정적 감사 — "사람이 안 시킨 실행"이 콘솔 창을 띄울 수 있는 지점을 찾는다. |
| `auto.py` | 76 | 자율 클로드 heartbeat 터미널 스위치 — on/off/status. |
| `auto_metrics.py` | 201 | 자율 heartbeat 데몬(claude-auto) 실효 계측 리포트 — 채택률/blocked율/게이트 차단/자가발굴 비율을 |
| `build_verify.py` | 645 | 빌드 전 필수 조건 검증 스크립트. |
| `checkpoint.py` | 62 | 의도 단위 세션 체크포인트 CLI — "왜/어디까지 결정/다음 뭐" 3요소를 |
| `codex_pg_watcher.py` | 286 | Mirror Codex CLI history entries into PostgreSQL pg_logs. |
| `console_flicker_watch.py` 🔨 | 214 | 순간적으로 떴다 사라지는 콘솔 창의 '범인'을 잡는 감시기. |
| `fix_corrupted_titles.py` | 282 | YAML 이스케이프 누적으로 백슬래시가 뭉개진 제텔 노트 제목을 복구한다. |
| `harness_verify.py` | 437 | Vibe Coding 하네스 V2 검증 스크립트. |
| `heal_report.py` | 100 | 자가치유 계측 CLI — src/heal_metrics.compute_heal_metrics를 호출해 4장치 지표를 |
| `incident.py` | 132 | 사고 장부 CLI — 고친 에러 기록(record) / 재발 검색(search) / |
| `install_ai_toolchain.py` 🔨 | 159 | Vibe Coding first-run Node.js and AI CLI automatic installer chain. |
| `install_antigravity.py` | 88 | Install Google's official Antigravity CLI (`agy`). |
| `install_dev_tools.py` | 159 | 프로젝트 개발 도구 통합 설치 스크립트. |
| `install_frontend_deps.py` | 195 | 프론트엔드(React/Vite) 의존성 설치 스크립트. |
| `install_gh_cli.py` | 154 | GitHub CLI(gh) 자동 설치 스크립트. |
| `install_harness.py` | 331 | 하네스 V2 경량판 설치 스크립트. |
| `install_hive_hooks.py` | 307 | 외부(또는 자기) 프로젝트의 .claude/settings.local.json에 비이브 코딩 하이브 훅을 |
| `install_nodejs.py` | 143 | Node.js LTS 자동 설치 스크립트 (Windows). |
| `install_npm_tool.py` | 92 | npm 글로벌 패키지 설치 스크립트. |
| `install_playwright_cli.py` | 71 | Playwright CLI 설치 + 브라우저 다운로드 — UI 검증(스크린샷 대신 Playwright 직접 확인)용. |
| `install_psql.py` | 189 | PostgreSQL CLI(psql) PATH 등록 스크립트. |
| `install_skills.py` | 195 | 외부(또는 자기) 프로젝트의 .claude/skills/, .claude/agents/에 |
| `install_statusline.py` | 112 | Claude Code 커스텀 상태줄을 현재 PC의 사용자 전역 설정에 멱등 설치한다. |
| `install_system_tool.py` | 208 | Windows 시스템 도구 설치 스크립트. |
| `intent_map.py` | 175 | 하이브 훅 자동 의도 감지 워크플로 맵. |
| `knowledge_extract.py` 🔨 | 369 | 코드 안에 이미 적혀 있는 '진짜 지식'을 제텔카스텐으로 옮기는 추출기. |
| `lesson.py` | 170 | 세션 교훈 증류 CLI — propose(후보 적재) / list / approve(승인 시 |
| `make_source_package.py` 🔨 | 188 | 개인 인프라 정보를 걷어낸 소스 배포 zip을 만든다. 남에게 코드를 건네되 |
| `migrate_antigravity_db.py` | 83 | DB 식별자 gemini→antigravity 일회성 마이그레이션 (plan Task 9). |
| `migrate_archive_session_summaries.py` | 70 | 일회성 마이그레이션 — 이미 permanent로 오승격된 세션요약 노트를 archived=true로 내린다. |
| `migrate_vault_consolidate.py` | 240 | 지식 창고 재점검 일회성 정리 마이그레이션 (2026-07-14). |
| `migrate_vault_pretty_names.py` 🔨 | 156 | 볼트 노트 파일명을 옛 규칙(`{note_id} {제목}`)에서 새 규칙(제목만)으로 1회 개명한다. |
| `pg_project.py` | 39 | PostgreSQL project DB resolver shared by script-side logging and messaging utilities. |
| `recall.py` | 51 | 경험 회상 스크립트 — 현재 작업과 유사한 과거 경험을 검색하여 출력. |
| `recall_quality.py` 🔨 | 155 | 회상 v2의 **품질**을 측정한다. 커버리지·건수가 아니라 "관련된 걸 찾고 |
| `reembed_all.py` 🔨 | 202 | 회상 v2의 전체 임베딩을 현재 모델/라이브러리 기준으로 다시 생성한다. |
| `run_antigravity_clean.py` | 130 | Antigravity CLI 직접 실행 래퍼. |
| `session_init.py` | 246 | 모든 에이전트(Claude, Antigravity, Codex)의 세션 시작 프로토콜 실행 스크립트. |
| `setup_qwen.py` 🔨 | 229 | 사장님 목소리(Qwen3-TTS) 굽기 환경 설치 — 전용 venv + CUDA 토치 + 모델 내려받기. |
| `setup_voice.py` 🔨 | 148 | 음성 사이드카 환경 설치 — 별도 venv 를 만들고 requirements.txt 를 깐다. |
| `smoke_test.py` 🔨 | 313 | 로컬 EXE 빌드 후 smoke test 자동 실행. |
| `statusline.py` | 189 | Claude Code 커스텀 상태줄 — 컨텍스트 그리드+모델+토큰(라인1), 세션 I/O(라인2). |
| `test_pg_logging.py` | 71 | PostgreSQL 로깅 통합 테스트 스크립트. |
| `tui.py` | 378 | 터미널용 텍스트 대시보드 — GUI 없이 하이브 상태(프로젝트/쿼터/터미널/태스크)를 본다. |
| `voice_turn_hook.py` 🔨 | 229 | 음성 낭독의 토대 — Claude Code Stop 훅으로 붙어, 턴이 끝난 사실과 |
| `vps_status_api.py` | 197 | VPS 상태를 JSON으로 뱉는 읽기 전용 API. nginx가 정적 상태판과 함께 서빙한다. |
| `wait_ci.py` 🔨 | 105 | CI 빌드가 끝날 때까지 기다렸다가 **끝나는 순간 스스로 종료**한다. |
| `wiki_build.py` 🔨 | 759 | 원료(코드 주석 · 사고 장부 · 세션 메모리)를 wiki/ 백과사전 페이지로 합성한다. |
| `wiki_lint.py` 🔨 | 415 | wiki/ 백과사전이 '늙었는지'를 기계적으로 검출한다 — 죽은 출처(사라진 파일· |
| `zettel_capture.py` | 703 | 제텔카스텐 자동 캡처 엔진. |
| `zettel_sync.py` 🔨 | 1106 | Hive Zettelkasten ↔ Obsidian Vault 동기화 스크립트. |

## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)
### 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `App.tsx` 🔨 | 1161 | 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트. |
| `main.tsx` | 75 | 설명: React 앱 진입점. ErrorBoundary로 전체 트리를 감싸 |
| `types.ts` | 206 | 설명: 프론트엔드 공용 TypeScript 타입 정의 — LogRecord/GitStatus 등 API 응답 |
| `constants.tsx` 🔨 | 94 | 설명: 여러 컴포넌트에서 공유하는 전역 상수 및 타입 정의. |

### 컴포넌트 (components/)
| 컴포넌트 | 줄 수 | 설명 |
|----------|------|------|
| `ActivityBar.tsx` 🔨 | 195 | 설명: 좌측 액티비티 바 — 패널 탭 전환 아이콘 + 배지(태스크/메모리/충돌/Git 변경 수, |
| `ChatSlot.tsx` | 610 | 설명: cokacdir 패턴 채팅 UI 컴포넌트. |
| `FileExplorer.tsx` | 557 | 설명: 파일 탐색기 사이드바 패널 컴포넌트. |
| `FilePathText.tsx` | 110 | 설명: 텍스트 내 파일 경로를 정규식으로 감지해 클릭 가능한 링크 세그먼트로 분리 렌더. |
| `FileTreeNode.tsx` | 165 | 설명: 파일 탐색기의 단일 트리 노드 컴포넌트. |
| `FloatingWindow.tsx` | 221 | 설명: 파일 탐색기에서 파일 클릭 시 열리는 플로팅(부유형) 편집 창 컴포넌트. |
| `SetupBanner.tsx` 🔨 | 239 | Setup Doctor 진단 결과를 상단 배너로 표시. |
| `StatusBoard.tsx` 🔨 | 264 | 설명: 상태판 독립 창(?page=status) 본체. 이 PC의 콘솔 창 — |
| `TerminalSlot.tsx` 🔨 | 1244 | 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트. |
| `ThoughtTrace.tsx` | 108 | 설명: AI의 사고 과정(Chain of Thought)을 실시간으로 시각화하는 패널. |
| `TopMenuBar.tsx` | 574 | 설명: VS Code 스타일 상단 메뉴바 컴포넌트. |
| `VibeEditor.tsx` | 141 | 설명: Monaco Editor 기반 코드 편집기 — VS Code 스타일 하이라이팅/주석 색상 강화, |

### 패널 컴포넌트 (components/panels/)
| 패널 | 줄 수 | 설명 |
|------|------|------|
| `AgentTerminalCard.tsx` | 256 | 설명: 자율 에이전트 터미널 카드 컴포넌트. |
| `DaemonsPanel.tsx` | 143 | 백그라운드 데몬 on/off 패널. GET/POST /api/daemons만 사용하며 판정 로직은 |
| `GitPanel.tsx` | 250 | Git 저장소 실시간 감시 패널 — 브랜치 상태, 파일 변경, 커밋 로그를 5초 폴링으로 표시 |
| `HealPanel.tsx` | 129 | 자가치유 계측 패널 (읽기 전용). GET /api/heal/metrics를 불러 4장치 |
| `HivePanel.tsx` | 464 | 하이브 진단 패널 — 에이전트 상태 모니터링 + 시스템 헬스 체크 + 자가 치유 UI. |
| `LanExecDirs.tsx` | 167 | 원격 실행 허용 폴더 관리 — 이 PC가 다른 PC의 Claude에게 열어줄 폴더 목록 + 모드 지정. |
| `LanPanel.tsx` | 657 | 설명: LAN 브리지 패널 — 같은 네트워크의 다른 바이브코딩을 자동발견하고 페어링(6자리 코드)한 뒤 |
| `LanRoomChat.tsx` | 125 | LAN 그룹 채팅방 — 페어링된 모든 PC가 함께 보는 방. 1:1 채팅과 저장/표시가 완전 분리된다. |
| `MemoryPanel.tsx` 🔨 | 517 | 에이전트 간 공유 메모리(PostgreSQL hive_memory + zettel_notes) 패널 — |
| `TasksPanel.tsx` | 495 | 에이전트 간 태스크 보드 패널 컴포넌트. |
| `ToolsPanel.tsx` | 407 | AI 개발 도구 설치 관리 패널. |
| `WikiPanel.tsx` 🔨 | 167 | LLM 위키(지식 백과사전) 상태판. 페이지·검색항목 수를 보여주고 |
| `ZettelkastenPanel.tsx` | 537 | Hive Zettelkasten 패널 — 카파시 + 루만 융합 메모 시스템 UI. |

### 터미널 하위 컴포넌트 (components/terminal/)
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `AgentSelectCards.tsx` 🔨 | 174 | 설명: 터미널 미실행 슬롯의 에이전트 선택 카드 3장(Claude/Antigravity/Codex) |
| `AgentUsageBar.tsx` | 191 | 터미널 하단의 에이전트별 플랜·컨텍스트 사용량 바와 상세 팝업. |
| `ClaudeContextBar.tsx` | 277 | 설명: Claude 컨텍스트 컬러 블록 바 + 클릭 상세 팝업(/context 스타일 블록 그리드, |
| `MicPressButton.tsx` 🔨 | 81 | 설명: '누르고 말하기' 단추 하나. 누르는 동안만 듣고 손을 떼면 그대로 보낸다. |
| `MonitorView.tsx` | 169 | 설명: 자율 에이전트 모니터링 뷰 — 상태 뱃지, 오케스트레이터 스킬 체인 배지, |
| `QuotaBadge.tsx` | 87 | 설명: 터미널 헤더 플랜 쿼터 배지 — Claude/Codex 5h 게이지+% · 7d %. |
| `ShortcutEditModal.tsx` | 47 | 터미널 단축어(사용자 커스텀 명령) 편집 모달. |
| `SlashCommandMenu.tsx` | 66 | 터미널 입력 영역의 슬래시 커맨드(`/`) 드롭다운 — 카테고리별 |
| `TerminalSlotHeader.tsx` 🔨 | 257 | 설명: 터미널 슬롯 상단 바 — 이름·브랜치·락/작업/메시지 배지, 프로젝트 뱃지, 모델 배지. |
| `VoiceBar.tsx` 🔨 | 275 | 설명: 전송창 바로 아래 한 줄짜리 음성 막대 — 답 소리 듣기, 호출어 부르기, |
| `VoiceSettings.tsx` 🔨 | 170 | 설명: 목소리 고르기 팝오버 — 어떤 음성으로 읽을지, 얼마나 빠르게 읽을지. |
| `xtermSelection.ts` | 107 | 설명: 터미널 클립보드 복사 + xterm 선택(하이라이트) 유지 유틸. |

### 공용 로직 (lib/)
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `apiBase.ts` 🔨 | 22 | 설명: 서버 주소 한 줄. 지금 열려 있는 포트가 곧 그 인스턴스의 API 다. |
| `audioCapture.ts` 🔨 | 295 | 설명: 마이크 → 16kHz mono PCM → WAV. 말이 시작되고 끝나는 지점을 스스로 |
| `browserVoice.ts` 🔨 | 173 | 설명: 브라우저(WebView2) 내장 합성기로 읽는 길. 서버 사이드카 없이 즉시 말한다. |
| `clipboard.ts` | 63 | 설명: 클립보드 읽기/쓰기 공용 헬퍼 — pywebview 네이티브 브리지 우선, navigator.clipboard 폴백. |
| `folderPicker.ts` | 35 | 시스템 폴더 선택 다이얼로그 공유 헬퍼 — pywebview 네이티브 → HTTP API 순 시도. |
| `projectContext.ts` | 38 | 설명: 프론트엔드 프로젝트 컨텍스트 헬퍼 (Phase 2-5.2). |
| `speech.ts` 🔨 | 283 | 설명: 음성 입출력의 순수 로직 — 마크다운→낭독문 변환, 문장 쪼개기, 톤 프리셋, |
| `voiceBus.ts` 🔨 | 932 | 설명: 음성 입출력의 전역 단일 소유자. 마이크 한 개를 잡고, 인식된 말이 어느 |

### 훅 (hooks/)
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `useCliModels.ts` | 82 | CLI별 사용 가능한 모델 목록 조회 훅. |
| `useOfficeChat.ts` | 244 | 오피스 채팅 ↔ agent_api REST 브릿지 훅. |
| `useOfficePty.ts` | 285 | 오피스 채팅 ↔ PTY 직접 통신 훅. |
| `useOfficeState.ts` | 269 | 메타버스 오피스 전용 파생 상태 계산 훅. |
| `useVibeData.ts` | 387 | 설명: 바이브 코딩 데이터 폴링 커스텀 훅. |
| `useVoice.ts` 🔨 | 50 | 설명: lib/voiceBus.ts(전역 싱글턴)를 React 에 잇는 얇은 층. 상태 구독과 |
| `useWorkspaceProfiles.ts` | 428 | 오피스 모드 회사 조직 관리 훅. |

## 🧪 테스트 (tests/)
| 파일 | 줄 수 | 테스트 대상 |
|------|------|------------|
| `test_agent_api.py` 🔨 | 326 | agent_api.py 단위 테스트. |
| `test_ai_toolchain_installer.py` | 54 | Sequential AI toolchain installer regression tests. |
| `test_claude_quota.py` | 53 | Claude 사용량 응답에서 신규 모델별 주간 한도를 보존하는 회귀 테스트. |
| `test_cli_install_recovery.py` | 173 | CLI 자동 설치가 "성공했는데도 미설치로 보이던" 결함(2026-08-05)의 회귀 방지. |
| `test_codex_harness_v2.py` | 86 | Focused tests for Codex Harness V2 bootstrap and entrypoints. |
| `test_codex_orchestration.py` | 114 | Codex 라우팅과 오케스트레이터 연동 회귀 테스트. |
| `test_codex_pg_watcher.py` | 108 | Tests for mirroring Codex CLI history into pg_logs. |
| `test_console_scan.py` 🔨 | 192 | 콘솔 창 식별(infra/console_scan) + 상태판 라우트(api/nodes_api) 회귀 테스트. |
| `test_daemon_toggles.py` 🔨 | 329 | 데몬 on/off 토글 회귀 테스트 — 기본값 보존(전부 기동)과 선택적 비활성 동작 검증. |
| `test_harness_verify.py` | 218 | harness_verify.py V2 검증 스크립트의 단위 테스트. |
| `test_hook_server_spawn_guard.py` | 175 | hook_bridge._start_server 스폰 가드 회귀 테스트 — 앱(GUI)이 살아있는 동안 |
| `test_installed_script_runner.py` 🔨 | 119 | 설치본(frozen EXE)에서 데몬 .py를 띄울 실행기 선택 회귀 테스트. |
| `test_itcp_context.py` | 72 | scripts/itcp.py 컨텍스트 빌딩 |
| `test_itcp_fallback.py` | 226 | ITCP 폴백 로직 단위 테스트. |
| `test_knowledge_pipeline.py` | 133 | 지식 노트 파이프라인 재설계 회귀 테스트 — 세션요약 노이즈 차단 + 파일지식 1급화 + |
| `test_lan_exec_gate.py` 🔨 | 154 | LAN 원격실행 게이트 E2E — 미등록 폴더 요청이 claude를 띄우지 못하는지, 허용 요청이 |
| `test_lan_room_chat.py` | 129 | LAN 그룹방 회귀 테스트 — scope가 토큰 서명에 묶이는지, 1:1 하위호환이 보존되는지, |
| `test_lan_sandbox.py` | 193 | LAN 원격실행 폴더 격리 회귀 테스트 — 화이트리스트 검증(우회 차단) + 모드별 |
| `test_new_api_modules.py` | 341 | tasks_api, files_api 단위 테스트. |
| `test_orchestrator_monitor.py` | 64 | Regression tests for orchestration monitor data adapters. |
| `test_pg_base_params.py` | 100 | query_rows/execute의 파라미터 바인딩 계약 회귀 테스트 — %s가 서버로 새어나가지 않는지 고정. |
| `test_pg_store_split.py` | 124 | pg_store.py 분할(2026-06-10) 회귀 방지 테스트. |
| `test_pty_idle_reclaim.py` | 86 | 유휴 claude 세션 회수(방법 A) 계약 검증 — pty-server.js 소스 정적 검사. |
| `test_quota_policy.py` | 69 | 사용량 snapshot의 다섯 권고 상태와 guard 동작 회귀 테스트. |
| `test_route_table.py` | 135 | server.py 라우트 완전성 가드 — do_GET/do_POST를 if/elif에서 디스패치 테이블로 |
| `test_self_heal_2.py` | 231 | 자가 치유 2.0 회귀 방지 테스트 — 회상 v2(pgvector) 그레이스풀 |
| `test_session_binding.py` 🔨 | 269 | 세션↔슬롯 결속 + 화석(stale) 판정 회귀 테스트. 방어 대상은 |
| `test_session_recycle.py` | 280 | 컨텍스트 리사이클 GUARD/상태머신 회귀 테스트. 핵심 방어선은 |
| `test_setup_auto_install.py` 🔨 | 268 | First-run sequential automatic dependency installation API regression tests. |
| `test_setup_banner_install_actions.py` | 33 | Setup banner installer action wiring regression tests. |
| `test_setup_doctor.py` | 151 | Setup Doctor 회귀 테스트 — AI CLI 감지 + .claude/settings.json 훅 자동 수리. |
| `test_shutdown_marker.py` 🔨 | 122 | '사람이 껐다' 표식과 워치독의 복구 게이트 회귀 테스트. |
| `test_smoke_isolation.py` | 77 | smoke_test의 데이터 디렉토리 격리 계약 검증 — 설치본 %APPDATA%\\VibeCoding 오염 방지. |
| `test_updater_bundle_version.py` | 109 | updater.bundle_version() 회귀 테스트 — 풀빌드 업데이트 감지가 소스 버전에 |
| `test_updater_release_path.py` | 310 | 업데이트/패키징 경로 회귀 테스트 — 릴리즈 크리티컬 핫스팟 방어. |
| `test_vault_auto_repair.py` | 89 | 부팅 시 볼트 자가 복구(auto_repair / fix_vault_files huge_only)의 회귀 테스트. |
| `test_vibe_cli_codex.py` | 42 | Tests for Codex-specific vibe CLI helpers. |
| `test_vibe_download_page.py` | 30 | btsky.pe.kr Vibe Coding latest-release download wiring regression tests. |
| `test_windows_installer_toolchain.py` 🔨 | 114 | Regression checks for prerequisite-first Windows installer packaging. |
| `test_zettel_oneway_default.py` | 66 | 제텔 동기화가 기본 단방향(PG→Vault)인지 지키는 회귀 테스트. |
| `test_zettel_pretty_names.py` 🔨 | 102 | 볼트 파일명 규칙 회귀 테스트 — note_id 접두 제거 이후의 이름 짓기가 |
| `test_zettel_size_guard.py` | 105 | 제텔 동기화의 '비정상 크기' 방어선 회귀 테스트. |
| `test_zettel_sync_mirror.py` | 42 | Tests for mirroring the local Obsidian vault into a shared Google Drive vault. |
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
| `vibe-verify-installed` | "개발에선 되는데 설치본에서 안 된다" 류를 추측 없이 실측으로 가르는 절차. |
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
> 자동 생성 완료: 2026-08-17 01:03
