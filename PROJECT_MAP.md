# 🗺️ vibe-coding 프로젝트 맵 (PROJECT_MAP.md)

> 자동 생성: `python scripts/generate_project_map.py` | 2026-08-14 18:03
> 문서 드리프트 방지를 위해 파일 시스템을 스캔하여 자동 갱신합니다.
> 설명은 각 파일의 표준 헤더(`DESCRIPTION:` / `📝`)에서 자동 수집합니다 — 여기 손으로 적지 말고 **파일 헤더를 고치세요**.

## 🧭 현재 상황 (내비게이션)

> 이 블록은 자동 생성된다. 파일 구조는 아래 지도, **작업 맥락은 여기**를 먼저 읽을 것.

- **브랜치**: `main` · 미커밋 49개 · 미푸시 6커밋
- **최근 커밋**
  - `f6e02a4` 2026-08-14 — fix(recycle): 화석 계측과 팬아웃 처형 제거 — T1·T2 반복 종료 근본 수정
  - `0c63d18` 2026-08-12 — docs(plan): 요구 6개 재정의 + herdr 방향 반영 — Phase 12 재작성
  - `f4a1778` 2026-08-12 — docs(plan): Phase 12 재편 — 서버에서 완결, 앱은 나중 (사용자 판단)
  - `05b5cc4` 2026-08-12 — feat(jobs): 일감 실행기 + 라우트 + git 실측 — Phase 12 Task 51~54 (1단계 완료)
  - `e010815` 2026-08-12 — feat(jobs): 일감 저장소 + 기동 게이트 — Phase 12 Task 48~50

### 📍 최근 체크포인트 (중단 지점)
- **08-13 21:40** 의도: herdr-kr 포크: 한글화 1차 + 전역 메뉴 확장(에이전트 실행/프로젝트 열기/폴더 열기) 구현
  - 결정: 메뉴 항목은 [kr] 설정 섹션으로 정의(재빌드 없이 추가 가능). 라벨/액션은 global_menu_entries() 단일 원천으로 통합
  - 다음: 폴더 열기 다이얼로그에 목록 렌더링 추가 — ui/dialogs.rs render_kr_path_overlay + overlays.rs inner rect + mouse.rs 분기. 로직/상태는 이미 완료
- **08-12 23:14** 의도: APIX 제품 구성 확정 — 중앙(btsky.pe.kr)+노드(herdr포크)+바이브코딩 별개
  - 결정: 각 PC 상주는 herdr(PTY소유·상태자동판정·소켓API), 바이브코딩은 상주에서 뺌 / herdr 본체 안 뜯고 얇은 러너로 소켓만 / herdr-kr → APIX 리네임(upstream 유지, T5 조율 후) / 자율대화보다 비서경유+일감방(사회자=비서)
  - 다음: 12-B 착수: Task 62 pg_hba 정리(선결) → 55 콘솔 일감API → 56 board화면. 실행백엔드 추상화 한 겹 넣어 herdr 이음매 확보
- **08-12 22:18** 의도: Phase 12 1단계 완료 — 일감 발주→기동게이트→주입→git실측 보고 고리
  - 결정: 게이트는 주입과 별도(launch_gate) / 전이기록은 DB 트리거가 강제 / 1단계는 프로세스 미기동(슬롯 없으면 거부) / 보고도구는 절대경로 안내
  - 다음: Task 55 기계검증(테스트·줄수·tsc) → 56 반려→incident → 57 useJobs → 58 카드패널

### ⚠️ 최근 사고 (같은 실수 반복 금지)
- **T1/T2 터미널이 60초마다 반복 종료(api_terminate) — 크래시로 오인**
  - 원인: 자동 리사이클 워처가 (1) 종료된 세션의 화석 사용률(853206/1000000=85.3%, 마지막 쓰기 7시간 전)을 현재값으로 읽고 (2) agent==claude인 running 슬롯을 전부 처형(팬아웃)했다. 새로 태어난 세션은 첫 assistant 응답 전에
  - 수정: 세션↔슬롯 결속(src/session_binding.py: first_ts>=slot.started + mtime vs last_output_at 대조)으로 터미널별 계측 도입, 워처는 status['terminals']만 보고 결속된 터미널 하나씩만 처형. claud
- **herdr: 액세스가 거부되었습니다. (os error 5) [코드 1로 프로세스 종료됨] — 바탕화면 바로가기 실행 시 반복**
  - 원인: 권한 상승(관리자) 컨텍스트에서 herdr 서버를 띄우면 named pipe 소유자가 BUILTIN\Administrators 로 잡힌다. src/ipc.rs 의 SDDL 이 D:P(A;;GA;;;SY)(A;;GA;;;OW) — SYSTEM 과 '소유자'에게만 전권이라
  - 수정: 관리자 셸에서 herdr 서버를 띄우지 않는다. 이미 떴으면 herdr 전부 종료 + 소켓 마커 파일 삭제 후 일반 권한(explorer 경유 또는 더블클릭)으로 재실행. 파이프 소유자가 YJSCOM\com 으로 바뀌면 정상. 포크에는 main.rs 에 Permissi
- **노드 간 대화: 글씨는 주입되는데 엔터가 안 눌려 상대 클로드가 못 읽음 + 읽어도 답장 불가**
  - 원인: 3중 원인 — ①배달이 프론트 poll에 얹혀 있어 UI가 안 돌면 배달 0건(근거였던 '커서는 하나뿐'이 틀림: message_cursors 키는 node_id+agent_id) ②Enter를 본문과 한 덩어리로 보내 Ink TUI가 붙여넣기로 판정해 CR을 줄바꿈으
  - 수정: fetch_new에 cursor_key 추가해 배달 전용 커서 분리 + 리스너가 deliver_pending 호출 + pty-server가 본문/Enter를 150ms 띄워 별도 전송하고 본문 개행 제거 + _reply_script()로 절대경로 안내

### 🔥 사고다발 파일 — 수정 전 `incident.py search` 필독
- `scripts/hive_hook.py` — 30일 내 3건

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
| `ai_monitor_plan.md` | 아픽스 콘솔 구축 계획 — btsky.pe.kr 을 개인 전용 총괄 관제판으로 전환하고 |
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

## 🖥️ 서버 & API (.ai_monitor/)
### 서버 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `server.py` 🔨 | 2198 | 하이브 마인드 중앙 통제 서버 — 에이전트 간 통신 중계, 상태 모니터링, 데이터 영속성 관리. |
| `boot.py` 🔨 | 412 | 경량 소스 업데이트 채널(A안)의 EXE 진입점 부트스트랩. |
| `soft_updater.py` 🔨 | 549 | 경량 소스 업데이트 채널(A안)의 감지/적용 모듈. |
| `_version.py` 🔨 | 1 | 앱 버전 단일 소스 (릴리즈 파이프라인이 자동 갱신 — 수동 편집 금지) |
| `mission_control.py` | 414 | AI 에이전트 전용 네이티브 윈도우 관제 센터 (Mission Control) — 시스템 트레이 및 사이드바 HUD 관리. |
| `mission_control_ui.py` | 496 | 미션 컨트롤 사이드바 HUD UI 컴포넌트 — 에이전트 상태 링 및 실시간 로그 시각화. |
| `soft_manifest.json` (루트) | 6 | soft 채널 풀빌드 게이트 (min_exe — 의존성 변경 시 소스 업데이트 차단) |

### API 모듈 (.ai_monitor/api/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `_common.py` | 60 | 설명: API 핸들러 공용 헬퍼. 8개 도메인 모듈에 복붙돼 있던 _json_response(8중복)와 |
| `agent_api.py` | 1441 | 설명: CLI 오케스트레이터 자율 에이전트 REST API 핸들러. |
| `central_api.py` 🔨 | 270 | 중앙 대화(아픽스 서버) HTTP 라우트 5종 — Task 26. |
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
| `jobs_api.py` 🔨 | 166 | 일감(job) HTTP 라우트 — Phase 12 Task 53. |
| `lan_api.py` | 583 | /api/lan/* 핸들러 — 프론트(127.0.0.1 로컬서버)가 LAN 브리지를 제어하는 통로. |
| `launch_api.py` | 102 | CLI 에이전트(claude/antigravity/codex) 실행 API — 새 cmd 창에서 에이전트를 띄운다. |
| `locks_api.py` | 67 | 파일 락 API — 에이전트 간 동시 편집 충돌 방지. locks.json에 {파일: 소유에이전트}를 |
| `logs_api.py` | 168 | 로그/메시지/실시간 로그 스트림 라우트 4종 — GET /stream(SSE), GET /api/server-logs, |
| `memory_api.py` | 412 | Postgres-first memory API handlers. recall-smart(임베딩 통합 회상) 포함. |
| `message_api.py` 🔨 | 116 | 에이전트 간 메시지 전송 API — 메시지를 DB(send_message)에 저장하고, 수신 대상 |
| `nodes_api.py` 🔨 | 167 | 상태판(독립 창 + tui.py)의 데이터 공급 라우트 4종. |
| `office_api.py` | 370 | 오피스 모드 전용 API — 프로필 중앙화(PostgreSQL SSOT) + 클래식과 네임스페이스 분리. |
| `office_launch_api.py` | 84 | 오피스 독립 서버 실행 라우트 3종 — POST /api/office/launch(office_server 프로세스 |
| `office_proxy_api.py` | 230 | 오피스 서버(office_server.py) 프로세스 관리 + HTTP 프록시. |
| `projects_api.py` | 69 | 최근 프로젝트 목록 API — projects.json에 최근 연 프로젝트 경로를 MRU(최대 20개)로 |
| `pty_api.py` 🔨 | 255 | PTY 세션 상태 및 제어 엔드포인트 — Node PTY 서버 투명 프록시. |
| `recycle_api.py` 🔨 | 489 | 컨텍스트 리사이클 HTTP 계층 — 상태머신(src/session_recycle.py)에 |
| `screenshot_api.py` | 45 | 스크린샷 멀티모달 분석 API — POST /api/screenshot/analyze. |
| `setup_api.py` | 137 | Setup Doctor API — 초기 설정 진단 상태를 대시보드에 제공. |
| `static_api.py` | 123 | 정적 파일 서빙 + 도움말/이미지 라우트 3종 — GET /api/help, GET /api/image-file, |
| `tasks_api.py` | 302 | /api/tasks/* 및 /api/task-logs 엔드포인트 핸들러 모듈. |
| `tools_api.py` 🔨 | 1311 | AI 도구 CLI 설치 관리 API. |
| `update_api.py` 🔨 | 261 | 앱 업데이트 라우트 핸들러 모음 — EXE 풀빌드 채널(updater)과 경량 소스 채널(soft_updater) |
| `vibe_api.py` | 295 | 설명: cmux 호환 vibe CLI REST API 핸들러. |
| `vibe_skills_api.py` | 246 | Platform Phase 3 — .vibe/skills + .claude/skills 병합 스캐너. |
| `zettel_api.py` | 203 | Hive Zettelkasten REST API 핸들러. |

### 데이터 계층 (.ai_monitor/src/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `brief_limits.py` | 89 | 프롬프트 계열 텍스트(재정박·워커 브리프·체크포인트)의 글자 수 상한과 |
| `central_inject.py` 🔨 | 602 | 중앙 대화(아픽스 버스) → 로컬 터미널 슬롯 PTY 주입. '@1-2'로 온 말이 화면에만 |
| `central_listener.py` 🔨 | 367 | 중앙 대화(agent_messages) 실시간 수신 신호기 — Task 27. |
| `claude_quota.py` | 171 | Claude Code CLI의 OAuth 토큰을 재사용해 Anthropic 사용량 엔드포인트 |
| `code_indexer.py` | 552 | 설명: 코드 인텔리전스 인덱서 — tree-sitter AST 파싱으로 코드 노드/엣지 추출 |
| `code_search.py` | 200 | 설명: 코드 인텔리전스 검색 — PostgreSQL FTS 기반 BM25 검색 엔진 |
| `codex_context.py` 🔨 | 122 | Codex CLI 세션의 현재 컨텍스트 점유율 파서. rollout jsonl의 |
| `codex_quota.py` | 216 | Codex CLI(OpenAI)의 플랜 쿼터 사용률(5h/7d %) 공급자. |
| `db.py` | 42 | 설명: 레거시 DB 진입점 (SQLite 런타임 저장소 폐기 잔재). get_connection()은 |
| `db_helper.py` | 113 | 설명: 세션 로그 기록 헬퍼 — pg_store(upsert_session_log/list_session_logs)로 |
| `file_store.py` | 229 | 설명: 레거시 파일 기반 저장소 폴백 (PostgreSQL 미가용 시). shared_memory.json / |
| `heal_metrics.py` | 273 | 자가치유 계측 단일 소스 — 4장치(회상v2/사고장부/체크포인트/교훈)가 실제로 삽질을 |
| `job_runner.py` 🔨 | 197 | 노드 쪽 일감 실행기 — Phase 12 Task 51. |
| `job_verify.py` 🔨 | 92 | 일감 검수 — Phase 12 Task 54(git 실측 수집). |
| `lan_discovery.py` | 120 | LAN 자동발견 — UDP 브로드캐스트로 같은 네트워크의 다른 바이브코딩 브리지를 |
| `lan_peers.py` 🔨 | 221 | LAN 브리지 페어링/신뢰 저장 + HMAC 토큰. 페어링은 '코드 기반 키 파생(PAKE류)' — |
| `lan_sandbox.py` 🔨 | 310 | 원격 claude 실행의 폴더 격리 계층 — 허용 폴더 화이트리스트 검증 + |
| `logger.py` | 130 | 설명: 작업 세션 로깅 진입점. log_start()가 session_id 발급 + 민감정보 마스킹 |
| `node_identity.py` 🔨 | 310 | 이 PC(노드)의 영구 정체성. config.json에 node_id(uuid4, 최초 1회) + node_label을 |
| `pg_base.py` 🔨 | 558 | 설명: PostgreSQL 연결 인프라 — 경로 결정, psycopg2 커넥션/풀, 쿼리 실행 프리미티브 |
| `pg_central.py` 🔨 | 548 | 중앙 PG(아픽스 서버) 커넥션 격리 모듈. config.json의 central_db 설정을 읽어 |
| `pg_experience.py` | 226 | 설명: 에이전트 경험/성장(XP·레벨·스탯) + 유사 경험 회상 + pg_logs 활동 기록 |
| `pg_incidents.py` | 182 | 설명: 사고 장부(incident_ledger) — 고친 에러의 시그니처/근본원인/수정법 기록 + |
| `pg_jobs.py` 🔨 | 383 | 아픽스 일감(job) 저장소 — Phase 12 Task 48·49. |
| `pg_lan.py` | 107 | LAN 브리지 채팅 이력(lan_messages) + 원격실행 감사로그(lan_exec_log) CRUD. |
| `pg_memory.py` | 639 | 설명: 하이브 메모리(hive_memory) CRUD + zettel 승격 + 세션 로그 + 채팅 + 지식 회상 |
| `pg_office.py` | 320 | 설명: 오피스 프로필 CRUD(PostgreSQL SSOT) + 활성 세션 컨텍스트(크래시 복구) |
| `pg_schema.py` | 828 | 설명: PostgreSQL 스키마 DDL(ensure_schema) + 레거시 JSONL/JSON 마이그레이션 |
| `pg_store.py` | 127 | 설명: PostgreSQL 저장소 파사드 — 분할된 pg_* 도메인 모듈을 단일 경로로 재노출 |
| `pg_tasks.py` | 388 | 설명: 하이브 태스크(hive_tasks) CRUD + 원자적 체크아웃 + 코멘트 + 하트비트 + 상태 저장 |
| `pg_vector_search.py` 🔨 | 248 | 설명: pgvector 기반 회상 v2 — embedding 컬럼 마이그레이션 + 코사인 검색 + |
| `quota_policy.py` | 117 | provider 쿼터 snapshot을 작업 크기 권고로 변환하는 순수 정책 계층. |
| `recall_client.py` | 83 | 설명: 훅(단명 프로세스)용 회상 클라이언트 — 서버 recall-smart API 우선, |
| `secure.py` | 59 | 설명: 보안 유틸 — 로그 민감정보 마스킹(API키/Bearer/패스워드 정규식), |
| `server_locator.py` | 76 | 설명: 9000번대 바이브 서버 포트 공용 탐색기 — /api/project-info 슬러그 대조로 |
| `server_utils.py` | 59 | 서버 공통 유틸리티 — 포트 탐색, CORS, JSON 응답 헬퍼. |
| `session_binding.py` 🔨 | 299 | claude 세션 jsonl ↔ PTY 슬롯 결속 + 터미널별 컨텍스트 점유율 계측. |
| `session_recycle.py` | 236 | 컨텍스트 리사이클 상태머신 — 세션을 마감 기록으로 봉인하고 새 컨텍스트로 |
| `wiki_generator.py` | 381 | 설명: LLM 위키 자동생성 엔진 — code_nodes → 프롬프트 조립 → hive_tasks 등록 |
| `zettelkasten.py` | 459 | Hive Zettelkasten — 카파시 Append-Review-Rescue + 루만 제텔카스텐 융합 메모 시스템. |

### 인프라 계층 (.ai_monitor/infra/)
| 모듈 | 줄 수 | 설명 |
|------|------|------|
| `app_boot.py` | 441 | PyWebView 데스크톱 앱 부팅 오케스트레이션. 스플래시 창을 먼저 띄우고 |
| `cli_commands.py` | 88 | server.py 진입 시 CLI 인자(--install / --uninstall / --create-shortcut) |
| `console_scan.py` | 438 | 화면에 떠 있는 콘솔 창(정체불명 검은 cmd 창)을 찾아 "누가 띄웠는지"를 판정한다. |
| `daemons.py` 🔨 | 1027 | 설명: 백그라운드 데몬 러너 — 워치독/리사이클 워처/오케스트레이터/문서 생성/ |
| `embed_service.py` | 152 | fastembed 기반 임베딩 서비스 싱글톤 — 회상 v2(pgvector)의 심장. |
| `env_path.py` | 128 | 실행 중인 프로세스의 PATH를 Windows 레지스트리 + 알려진 CLI bin 디렉토리 기준으로 |
| `folder_dialog.py` 🔨 | 139 | 윈도우 네이티브 폴더 선택 다이얼로그(SHBrowseForFolderW, ctypes). |
| `fs_watcher.py` | 117 | 파일 시스템 실시간 감시(watchdog) + cli_agent 출력 브로드캐스트 워커. |
| `heartbeat_daemon.py` | 725 | 설명: 자율 클로드 심장 박동 데몬 — 사람이 부르지 않아도 주기적으로 깨어나 |
| `instance_lock.py` | 179 | 단일 인스턴스 락 획득 + HTTP/WS 서버 포트 확정 로직. |
| `lifecycle.py` | 329 | 프로세스 라이프사이클 정리 함수 모음. |
| `memory_watcher.py` | 388 | 에이전트 메모리(Claude Code / Antigravity CLI) 파일 감시 + PostgreSQL |
| `node_status.py` 🔨 | 330 | 원격 노드의 두 가지 사실을 아픽스 서버에서 한 번에 조회 + CLI(claude/codex) 설치 점검. |
| `postgres_runtime.py` | 300 | 내장 PostgreSQL 18 기동/초기화 런타임. 배포(frozen) 모드에서 |
| `proc.py` | 35 | Windows 콘솔 숨김 subprocess 공용 래퍼. 앱의 모든 subprocess 호출이 |
| `project_context.py` | 204 | Platform Phase 2-3 — 활성 프로젝트 컨텍스트 Resolver. |
| `pty_process.py` | 483 | Node.js PTY 서버 프로세스 관리 함수 모음. |
| `runtime.py` 🔨 | 158 | 시스템 런타임 보조 유틸 — Python 인터프리터 후보 탐색, |
| `session_parse.py` 🔨 | 163 | CLI 세션 파일(JSONL/JSON) 토큰 usage 파서 모음. |
| `splash.py` | 37 | 부팅 스플래시 창 HTML 생성. WebView 창을 무거운 초기화(PG/PTY/HTTP) |
| `tool_install.py` | 317 | CLI 도구(Antigravity/Claude Code/Codex) 설치 상태 + 백그라운드 npm |
| `tunnel_daemon.py` 🔨 | 388 | 중앙 PG(아픽스 서버)로 가는 SSH 터널을 띄우고 살려두는 데몬. |
| `win32_icon.py` | 49 | Windows 작업표시줄/타이틀바 아이콘 강제 설정. PyWebView가 생성한 창의 |

## ⚙️ 스크립트 (scripts/)
### 에이전트/터미널
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `cli_agent.py` | 1150 | 설명: CLI 오케스트레이터 자율 에이전트 핵심 엔진. |
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
| `drift_detector.py` 🔨 | 276 | 계획 이탈 감지기 — 현재 작업이 ai_monitor_plan.md와 일치하는지 검증. |
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
| `hive_watchdog.py` | 562 | 하이브 마인드(Hive Mind) 시스템 자가 치유(Self-Healing) 및 모니터링 엔진. |
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
| `generate_project_map.py` 🔨 | 728 | PROJECT_MAP.md 자동 생성 스크립트. |

### 인프라
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `pg_manager.py` 🔨 | 275 | 하이브 마인드 전용 포터블 PostgreSQL 통합 매니저. |
| `setup_hive_pg.py` | 133 | 하이브 마인드 전용 포터블 PostgreSQL 18 + pgvector 설치 및 초기화 스크립트. |
| `install_codex.py` | 85 | Codex CLI 설치 및 초기 설정 스크립트. |

### 기타
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `antigravity_adapter.py` | 138 | Antigravity CLI(agy) 호출 격리 레이어 — closed-source 인터페이스 변경 대비 |
| `antigravity_output_filter.py` | 78 | Antigravity CLI 내부 진단 로그를 사용자 출력에서 걸러내는 보조 필터. |
| `antigravity_session_repair.py` | 216 | Antigravity CLI 세션 히스토리 자동 수리 스크립트. |
| `auto.py` | 76 | 자율 클로드 heartbeat 터미널 스위치 — on/off/status. |
| `auto_metrics.py` | 201 | 자율 heartbeat 데몬(claude-auto) 실효 계측 리포트 — 채택률/blocked율/게이트 차단/자가발굴 비율을 |
| `build_verify.py` | 645 | 빌드 전 필수 조건 검증 스크립트. |
| `central_say.py` 🔨 | 105 | 슬롯 CLI가 아픽스 중앙 대화(서로 대화)에 답하는 수단. |
| `checkpoint.py` | 62 | 의도 단위 세션 체크포인트 CLI — "왜/어디까지 결정/다음 뭐" 3요소를 |
| `codex_pg_watcher.py` | 286 | Mirror Codex CLI history entries into PostgreSQL pg_logs. |
| `fix_corrupted_titles.py` 🔨 | 282 | YAML 이스케이프 누적으로 백슬래시가 뭉개진 제텔 노트 제목을 복구한다. |
| `harness_verify.py` | 437 | Vibe Coding 하네스 V2 검증 스크립트. |
| `heal_report.py` | 100 | 자가치유 계측 CLI — src/heal_metrics.compute_heal_metrics를 호출해 4장치 지표를 |
| `incident.py` | 132 | 사고 장부 CLI — 고친 에러 기록(record) / 재발 검색(search) / |
| `install_ai_toolchain.py` | 142 | Vibe Coding first-run Node.js and AI CLI automatic installer chain. |
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
| `job_report.py` 🔨 | 72 | 슬롯 CLI 가 맡은 일감의 결과를 중앙에 되돌리는 수단 — Phase 12 Task 51. |
| `lesson.py` | 170 | 세션 교훈 증류 CLI — propose(후보 적재) / list / approve(승인 시 |
| `make_source_package.py` 🔨 | 188 | 개인 인프라 정보를 걷어낸 소스 배포 zip을 만든다. 남에게 코드를 건네되 |
| `migrate_antigravity_db.py` | 83 | DB 식별자 gemini→antigravity 일회성 마이그레이션 (plan Task 9). |
| `migrate_archive_session_summaries.py` | 70 | 일회성 마이그레이션 — 이미 permanent로 오승격된 세션요약 노트를 archived=true로 내린다. |
| `migrate_vault_consolidate.py` | 240 | 지식 창고 재점검 일회성 정리 마이그레이션 (2026-07-14). |
| `pg_project.py` | 39 | PostgreSQL project DB resolver shared by script-side logging and messaging utilities. |
| `recall.py` | 51 | 경험 회상 스크립트 — 현재 작업과 유사한 과거 경험을 검색하여 출력. |
| `recall_quality.py` 🔨 | 126 | 회상 v2의 **품질**을 측정한다. 커버리지·건수가 아니라 "관련된 걸 찾고 |
| `reembed_all.py` 🔨 | 181 | 회상 v2의 전체 임베딩을 현재 모델/라이브러리 기준으로 다시 생성한다. |
| `run_antigravity_clean.py` | 130 | Antigravity CLI 직접 실행 래퍼. |
| `session_init.py` | 246 | 모든 에이전트(Claude, Antigravity, Codex)의 세션 시작 프로토콜 실행 스크립트. |
| `smoke_test.py` | 303 | 로컬 EXE 빌드 후 smoke test 자동 실행. |
| `statusline.py` | 189 | Claude Code 커스텀 상태줄 — 컨텍스트 그리드+모델+토큰(라인1), 세션 I/O(라인2). |
| `test_pg_logging.py` | 71 | PostgreSQL 로깅 통합 테스트 스크립트. |
| `tui.py` 🔨 | 378 | 터미널용 텍스트 대시보드 — GUI 없이 하이브 상태(프로젝트/쿼터/터미널/태스크)를 본다. |
| `vps_status_api.py` 🔨 | 197 | VPS 상태를 JSON으로 뱉는 읽기 전용 API. nginx가 정적 상태판과 함께 서빙한다. |
| `zettel_capture.py` 🔨 | 703 | 제텔카스텐 자동 캡처 엔진. |
| `zettel_sync.py` 🔨 | 988 | Hive Zettelkasten ↔ Obsidian Vault 동기화 스크립트. |

## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)
### 코어
| 파일 | 줄 수 | 설명 |
|------|------|------|
| `App.tsx` 🔨 | 1138 | 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트. |
| `main.tsx` | 75 | 설명: React 앱 진입점. ErrorBoundary로 전체 트리를 감싸 |
| `types.ts` | 206 | 설명: 프론트엔드 공용 TypeScript 타입 정의 — LogRecord/GitStatus 등 API 응답 |
| `constants.tsx` | 93 | 설명: 여러 컴포넌트에서 공유하는 전역 상수 및 타입 정의. |

### 컴포넌트 (components/)
| 컴포넌트 | 줄 수 | 설명 |
|----------|------|------|
| `ActivityBar.tsx` 🔨 | 191 | 설명: 좌측 액티비티 바 — 패널 탭 전환 아이콘 + 배지(태스크/메모리/충돌/Git 변경 수, |
| `ChatSlot.tsx` | 610 | 설명: cokacdir 패턴 채팅 UI 컴포넌트. |
| `FileExplorer.tsx` | 557 | 설명: 파일 탐색기 사이드바 패널 컴포넌트. |
| `FilePathText.tsx` | 110 | 설명: 텍스트 내 파일 경로를 정규식으로 감지해 클릭 가능한 링크 세그먼트로 분리 렌더. |
| `FileTreeNode.tsx` | 165 | 설명: 파일 탐색기의 단일 트리 노드 컴포넌트. |
| `FloatingWindow.tsx` | 221 | 설명: 파일 탐색기에서 파일 클릭 시 열리는 플로팅(부유형) 편집 창 컴포넌트. |
| `SetupBanner.tsx` | 227 | Setup Doctor 진단 결과를 상단 배너로 표시. |
| `StatusBoard.tsx` 🔨 | 494 | 설명: 상태판 독립 창(?page=status) 본체. 두 가지를 한 화면에 보여준다. |
| `TerminalSlot.tsx` 🔨 | 1100 | 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트. |
| `ThoughtTrace.tsx` | 108 | 설명: AI의 사고 과정(Chain of Thought)을 실시간으로 시각화하는 패널. |
| `TopMenuBar.tsx` | 574 | 설명: VS Code 스타일 상단 메뉴바 컴포넌트. |
| `VibeEditor.tsx` | 141 | 설명: Monaco Editor 기반 코드 편집기 — VS Code 스타일 하이라이팅/주석 색상 강화, |

### 패널 컴포넌트 (components/panels/)
| 패널 | 줄 수 | 설명 |
|------|------|------|
| `AgentTerminalCard.tsx` | 256 | 설명: 자율 에이전트 터미널 카드 컴포넌트. |
| `CentralPanel.tsx` 🔨 | 166 | 설명: 중앙 대화(아픽스 서버) 패널 — 여러 PC의 클로드가 한 PG를 공유해 주고받는 대화창. |
| `DaemonsPanel.tsx` | 143 | 백그라운드 데몬 on/off 패널. GET/POST /api/daemons만 사용하며 판정 로직은 |
| `GitPanel.tsx` | 250 | Git 저장소 실시간 감시 패널 — 브랜치 상태, 파일 변경, 커밋 로그를 5초 폴링으로 표시 |
| `HealPanel.tsx` | 129 | 자가치유 계측 패널 (읽기 전용). GET /api/heal/metrics를 불러 4장치 |
| `HivePanel.tsx` | 464 | 하이브 진단 패널 — 에이전트 상태 모니터링 + 시스템 헬스 체크 + 자가 치유 UI. |
| `LanExecDirs.tsx` | 167 | 원격 실행 허용 폴더 관리 — 이 PC가 다른 PC의 Claude에게 열어줄 폴더 목록 + 모드 지정. |
| `LanPanel.tsx` 🔨 | 657 | 설명: LAN 브리지 패널 — 같은 네트워크의 다른 바이브코딩을 자동발견하고 페어링(6자리 코드)한 뒤 |
| `LanRoomChat.tsx` | 125 | LAN 그룹 채팅방 — 페어링된 모든 PC가 함께 보는 방. 1:1 채팅과 저장/표시가 완전 분리된다. |
| `MemoryPanel.tsx` | 469 | 에이전트 간 공유 메모리(SQLite) 패널 — 검색, CRUD, 폴링 로직을 포함한 독립 컴포넌트 |
| `TasksPanel.tsx` | 495 | 에이전트 간 태스크 보드 패널 컴포넌트. |
| `ToolsPanel.tsx` | 407 | AI 개발 도구 설치 관리 패널. |
| `ZettelkastenPanel.tsx` | 537 | Hive Zettelkasten 패널 — 카파시 + 루만 융합 메모 시스템 UI. |

## 🧪 테스트 (tests/)
| 파일 | 줄 수 | 테스트 대상 |
|------|------|------------|
| `test_agent_api.py` | 326 | agent_api.py 단위 테스트. |
| `test_ai_toolchain_installer.py` | 54 | Sequential AI toolchain installer regression tests. |
| `test_central_api.py` 🔨 | 284 | 중앙 대화 HTTP 라우트(Task 26)와 실시간 수신 신호기(Task 27)의 규약 회귀 — |
| `test_central_api_routes.py` 🔨 | 64 | 중앙 대화 HTTP 라우트 배선 회귀 테스트 — 구현만 되고 안 붙는 사고 방지 + 원격 실행 금지선 고정. |
| `test_central_e2e.py` 🔨 | 161 | 중앙 대화 실왕복 E2E (Task 28) — 중앙 서버가 실제로 붙을 때만 돈다. |
| `test_central_inject_remote.py` 🔨 | 249 | 🔴 원격 주입 4중 게이트 회귀 테스트. 주입은 bypass 권한 CLI에 대한 사실상의 |
| `test_central_listener_health.py` 🔨 | 109 | 🔴 리스너가 '조용한 단절'을 빠져나오는지 고정하는 회귀 테스트. |
| `test_central_messaging.py` 🔨 | 176 | 중앙 대화(agent_messages) 송수신 규약의 회귀 테스트 — 중앙 서버 없이 검증한다. |
| `test_central_optional.py` 🔨 | 104 | 🔴 중앙 서버를 쓰지 않는 사용자에게 아무 변화가 없음을 고정하는 회귀 테스트. |
| `test_claude_quota.py` | 53 | Claude 사용량 응답에서 신규 모델별 주간 한도를 보존하는 회귀 테스트. |
| `test_cli_install_recovery.py` | 173 | CLI 자동 설치가 "성공했는데도 미설치로 보이던" 결함(2026-08-05)의 회귀 방지. |
| `test_codex_harness_v2.py` | 86 | Focused tests for Codex Harness V2 bootstrap and entrypoints. |
| `test_codex_orchestration.py` | 114 | Codex 라우팅과 오케스트레이터 연동 회귀 테스트. |
| `test_codex_pg_watcher.py` | 108 | Tests for mirroring Codex CLI history into pg_logs. |
| `test_config_self_heal.py` 🔨 | 163 | config.json 자가복구 회귀 테스트 — 읽기 실패가 '설정 없음'으로 둔갑해 |
| `test_console_scan.py` | 206 | 콘솔 창 식별(infra/console_scan) + 상태판 라우트(api/nodes_api) 회귀 테스트. |
| `test_daemon_toggles.py` | 329 | 데몬 on/off 토글 회귀 테스트 — 기본값 보존(전부 기동)과 선택적 비활성 동작 검증. |
| `test_harness_verify.py` | 218 | harness_verify.py V2 검증 스크립트의 단위 테스트. |
| `test_hook_server_spawn_guard.py` 🔨 | 175 | hook_bridge._start_server 스폰 가드 회귀 테스트 — 앱(GUI)이 살아있는 동안 |
| `test_itcp_context.py` | 72 | scripts/itcp.py 컨텍스트 빌딩 |
| `test_itcp_fallback.py` | 226 | ITCP 폴백 로직 단위 테스트. |
| `test_knowledge_pipeline.py` | 133 | 지식 노트 파이프라인 재설계 회귀 테스트 — 세션요약 노이즈 차단 + 파일지식 1급화 + |
| `test_lan_exec_gate.py` | 154 | LAN 원격실행 게이트 E2E — 미등록 폴더 요청이 claude를 띄우지 못하는지, 허용 요청이 |
| `test_lan_room_chat.py` | 129 | LAN 그룹방 회귀 테스트 — scope가 토큰 서명에 묶이는지, 1:1 하위호환이 보존되는지, |
| `test_lan_sandbox.py` | 193 | LAN 원격실행 폴더 격리 회귀 테스트 — 화이트리스트 검증(우회 차단) + 모드별 |
| `test_launch_gate.py` 🔨 | 130 | 기동 게이트 회귀 테스트 — Phase 12 Task 50. |
| `test_new_api_modules.py` | 341 | tasks_api, files_api 단위 테스트. |
| `test_node_identity.py` 🔨 | 127 | 노드 정체성 회귀 테스트 — ID 영속성, 라벨 독립성, node_ref 왕복, 손상 복구. |
| `test_node_status.py` 🔨 | 124 | 노드 상태 판정(생존/접속 분리) + 원격 명령 조립 규약의 회귀 테스트. |
| `test_orchestrator_monitor.py` | 64 | Regression tests for orchestration monitor data adapters. |
| `test_pg_base_params.py` 🔨 | 100 | query_rows/execute의 파라미터 바인딩 계약 회귀 테스트 — %s가 서버로 새어나가지 않는지 고정. |
| `test_pg_central.py` 🔨 | 123 | 중앙 PG 커넥션 모듈 회귀 테스트 — 미설정/오설정에서 예외 없이 None인지, |
| `test_pg_jobs.py` 🔨 | 120 | 일감 저장소 회귀 테스트 — Phase 12 Task 48·49. |
| `test_pg_store_split.py` | 124 | pg_store.py 분할(2026-06-10) 회귀 방지 테스트. |
| `test_pty_idle_reclaim.py` | 86 | 유휴 claude 세션 회수(방법 A) 계약 검증 — pty-server.js 소스 정적 검사. |
| `test_quota_policy.py` | 69 | 사용량 snapshot의 다섯 권고 상태와 guard 동작 회귀 테스트. |
| `test_route_table.py` | 135 | server.py 라우트 완전성 가드 — do_GET/do_POST를 if/elif에서 디스패치 테이블로 |
| `test_self_heal_2.py` | 231 | 자가 치유 2.0 회귀 방지 테스트 — 회상 v2(pgvector) 그레이스풀 |
| `test_session_binding.py` 🔨 | 269 | 세션↔슬롯 결속 + 화석(stale) 판정 회귀 테스트. 방어 대상은 |
| `test_session_recycle.py` | 280 | 컨텍스트 리사이클 GUARD/상태머신 회귀 테스트. 핵심 방어선은 |
| `test_setup_auto_install.py` | 153 | First-run sequential automatic dependency installation API regression tests. |
| `test_setup_banner_install_actions.py` | 33 | Setup banner installer action wiring regression tests. |
| `test_setup_doctor.py` | 151 | Setup Doctor 회귀 테스트 — AI CLI 감지 + .claude/settings.json 훅 자동 수리. |
| `test_smoke_isolation.py` | 77 | smoke_test의 데이터 디렉토리 격리 계약 검증 — 설치본 %APPDATA%\\VibeCoding 오염 방지. |
| `test_tunnel_daemon.py` 🔨 | 226 | 중앙 PG SSH 터널 데몬 회귀 테스트 — 게이트/ssh 옵션/우리터널 판정/고아 회수. |
| `test_updater_bundle_version.py` | 109 | updater.bundle_version() 회귀 테스트 — 풀빌드 업데이트 감지가 소스 버전에 |
| `test_updater_release_path.py` | 310 | 업데이트/패키징 경로 회귀 테스트 — 릴리즈 크리티컬 핫스팟 방어. |
| `test_vault_auto_repair.py` 🔨 | 89 | 부팅 시 볼트 자가 복구(auto_repair / fix_vault_files huge_only)의 회귀 테스트. |
| `test_vibe_cli_codex.py` | 42 | Tests for Codex-specific vibe CLI helpers. |
| `test_vibe_download_page.py` | 30 | btsky.pe.kr Vibe Coding latest-release download wiring regression tests. |
| `test_windows_installer_toolchain.py` | 105 | Regression checks for prerequisite-first Windows installer packaging. |
| `test_zettel_oneway_default.py` 🔨 | 66 | 제텔 동기화가 기본 단방향(PG→Vault)인지 지키는 회귀 테스트. |
| `test_zettel_size_guard.py` 🔨 | 105 | 제텔 동기화의 '비정상 크기' 방어선 회귀 테스트. |
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
> 자동 생성 완료: 2026-08-14 18:03
