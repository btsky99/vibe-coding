<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 프로젝트 전체 보안/성능/품질 고도화 + 멀티-LLM 자율 협업 로드맵
REVISION HISTORY:
- 2026-03-18 Claude: P5 cmux 기반 vibe CLI + 알림 시스템 고도화 계획 추가
- 2026-03-17 Claude: P4 멀티-LLM 자율 협업 시스템 구축 계획 추가
- 2026-03-16 Claude: P0 보안 5건 + P1 성능/안정성 5건 전부 완료
- 2026-03-16 Claude: P0 보안 + P1 성능/안정성 + P2 코드품질 고도화 계획 수립
-->

# 📋 프로젝트 보안/성능/품질 고도화 + 자율 협업 (v3.7.82)

**작성일:** 2026-03-17
**목표:** P0~P3 완료 → P4 멀티-LLM 자율 협업 시스템 구축

---

## 🔴 P0: 보안 수정 (Critical) — ✅ 전부 완료

[x] Task 1: SQL 인젝션 수정 — server.py parameterized query 전환
[x] Task 2: SQL 인젝션 수정 — hive_bridge.py parameterized query 전환
[x] Task 3: 커맨드 인젝션 수정 — /api/launch
[x] Task 4: 경로 순회 수정 — 파일 접근 API 보안 강화
[x] Task 5: psycopg2 의존성 등록

## 🟡 P1: 성능/안정성 개선 — ✅ 전부 완료

[x] Task 6~10: 에러 핸들링, API_BASE 통합, bare except 정리, PG 포트 통합, ISS 통합

## 🔵 P3: 하이브 인텔리전스 — ✅ 전부 완료

[x] Task 11~14: Red Team, Living Doc, Consensus, Drift Detection

---

## 🟣 P4: 멀티-LLM 자율 협업 시스템 (v3.7.82~)

**목표:** Claude(T1) + Gemini(T2) + Codex(T3)가 자율적으로 작업 분배/실행/검증

[x] Task 15: 자율 태스크 디스패처 (auto_dispatcher.py) 구현
    - 에이전트 역량 프로필 기반 자동 매칭 알고리즘
    - Fan-Out/Fan-In 병렬 분배 패턴
    - 크로스 검증 루프: 작성자 ≠ 검증자 강제
    - CLI: dispatch, fan-out, verify, status, score

[x] Task 16: 서버 디스패처 API 추가
    - GET /api/dispatcher/score — 에이전트별 적합도 점수
    - GET /api/dispatcher/status — 분배 현황
    - POST /api/dispatcher/dispatch — 태스크 자동 분배
    - POST /api/dispatcher/fan-out — 병렬 분배
    - POST /api/dispatcher/verify — 크로스 검증 요청

[x] Task 17: /api/heartbeat Content-Type 수정
    - text/plain → application/json 변환 (JSON 식별 가능하도록)

[x] Task 18: /api/shutdown 엔드포인트 구현
    - 프론트엔드 TopMenuBar.tsx와 정합 (이전: /api/shutdown-disabled → 404)
    - PTY 세션 정리 후 안전 종료

[x] Task 19: T2/T3에 ITCP 작업 지시 전송
    - Gemini(T2): 프론트엔드 점검 + 문서 생성 + 코드 리뷰
    - Codex(T3): 유닛 테스트 + API 통합 테스트 + 안정성 점검

[x] Task 20: 대시보드 디스패처 UI 패널 추가
    - DispatcherPanel.tsx 생성 — 에이전트 역량 바 차트 + 실시간 분배 현황
    - 태스크 디스패치 폼 (유형 자동감지, 에이전트 선택, 우선순위)
    - 적합도 미리보기 + 디스패치 히스토리
    - ActivityBar에 Target 아이콘 탭 추가, App.tsx에 패널 등록
    - 프론트엔드 빌드 완료

[x] Task 21: 자동 디스패치 트리거 — UserPromptSubmit 연동
    - hive_hook.py _INTENT_MAP에 "multi_dispatch" 의도 추가 (최고 우선순위)
    - 키워드: 분담/나눠/T1/T2/T3/제미나이/코덱스/각자/지시해 등
    - auto_dispatcher.py fan-out 자동 호출 가이드 컨텍스트 주입

[x] Task 22: 에이전트 자동 피드백 루프
    - Stop 이벤트 시 수정 파일 있으면 자동 크로스 검증 요청
    - auto_dispatcher.request_verification() 자동 호출
    - 작성자(claude) ≠ 검증자 강제 — ITCP review 채널로 전송

---

## 🟢 P5: cmux 기반 vibe CLI + 알림 시스템 고도화 (v3.7.89~)

**목표:** cmux의 CLI/알림/IPC 설계를 기존 server.py + PostgreSQL 위에 구현
**접근:** API 확장형 MVP (Named Pipe는 추후)

### Phase 1: 백엔드 인프라

[x] Task 23: PostgreSQL에 vibe 알림/상태/로그 스키마 생성
    파일: .ai_monitor/server.py (ensure_postgres_running 내 스키마 섹션)
    방법: vibe_notifications, vibe_agent_state, vibe_agent_logs 3개 테이블 CREATE IF NOT EXISTS
          + NOTIFY 트리거 함수 생성 (vibe_notification 채널)
    검증: psql로 테이블 존재 확인 + INSERT 시 NOTIFY 발생 확인
    의존: 없음

[x] Task 24: api/vibe_api.py 신규 생성 — /api/vibe/* REST 핸들러
    파일: .ai_monitor/api/vibe_api.py (신규)
    방법: handle_notify, handle_progress, handle_status, handle_log, handle_sidebar_state
          각 핸들러가 PostgreSQL에 CRUD 수행. 기존 api/agent_api.py 패턴 참고.
          - POST /api/vibe/notify → INSERT vibe_notifications + pg_notify
          - POST /api/vibe/progress → UPSERT vibe_agent_state (key='_progress')
          - POST /api/vibe/status → UPSERT vibe_agent_state
          - POST /api/vibe/log → INSERT vibe_agent_logs
          - DELETE /api/vibe/progress, status, log → DELETE
          - GET /api/vibe/sidebar → SELECT 전체 상태 조회
    검증: curl로 각 엔드포인트 호출 후 PG 데이터 확인
    의존: Task 23 완료 후

[x] Task 25: server.py에 vibe_api 라우팅 추가
    파일: .ai_monitor/server.py
    방법: import api.vibe_api + do_GET/do_POST/do_DELETE에 /api/vibe/* elif 추가
    검증: server.py 기동 후 /api/vibe/notify POST 성공 확인
    의존: Task 24 완료 후

### Phase 2: CLI 도구

[x] Task 26: scripts/vibe_cli.py 신규 생성 — cmux 호환 CLI
    파일: scripts/vibe_cli.py (신규)
    방법: argparse 기반 8개 서브커맨드 (notify, set-progress, clear-progress,
          set-status, clear-status, log, clear-log, sidebar-state)
          내부: urllib.request → server.py API / 폴백: psql 직접 INSERT
    검증: python scripts/vibe_cli.py notify --title "테스트" --body "완료"
    의존: Task 25 완료 후

### Phase 3: OSC 파서 + 에이전트 감지

[x] Task 27: scripts/osc_parser.py 신규 생성 — OSC 시퀀스 파서
    파일: scripts/osc_parser.py (신규)
    방법: 정규식 기반 OSC 9/99/777/133 추출 + strip()
    검증: 단위 테스트 — 각 OSC 타입별 파싱 결과 검증
    의존: 없음 (독립)

[x] Task 28: scripts/agent_detector.py 신규 생성 — 에이전트 프로세스 감지
    파일: scripts/agent_detector.py (신규)
    방법: psutil 기반 프로세스 트리 탐색 + 환경변수 TERMINAL_ID 병행
    검증: Claude Code 실행 중 detect_all_agents() 호출 시 감지 확인
    의존: 없음 (독립)

[x] Task 29: cli_agent.py에 OSC 파서 통합
    파일: scripts/cli_agent.py
    방법: _ANSI_ESCAPE 필터 전에 osc_parser.parse()로 알림 추출 → API 전송
    검증: Claude CLI가 OSC 777 알림 출력 시 vibe_notifications에 기록 확인
    의존: Task 25, Task 27 완료 후

### Phase 4: Mission Control UI 알림

[x] Task 30: mission_control.py에 vibe_notification 채널 구독 추가
    파일: .ai_monitor/mission_control.py
    방법: PgListenerThread에 LISTEN vibe_notification + 시그널 emit
          + QSystemTrayIcon.showMessage()로 Windows 토스트
    검증: vibe notify CLI → 시스템 트레이 알림 팝업 확인
    의존: Task 23 완료 후

[x] Task 31: mission_control_ui.py에 링 플래시 + 배지 + 진행률 호 추가
    파일: .ai_monitor/mission_control_ui.py
    방법: AgentRing 확장 — flash_ring(), badge_count, progress_arc
    검증: vibe notify → AgentRing 파란 깜빡임 + 배지 숫자 표시 확인
    의존: Task 30 완료 후

### 의존성 그래프
```
Task 23 (PG) ──→ Task 24 (API) ──→ Task 25 (라우팅) ──→ Task 26 (CLI)
    │                                      │
    └──→ Task 30 (MC 구독) ──→ Task 31 (UI)│
                                            ↓
Task 27 (OSC) ──→ Task 29 (cli_agent 통합) ←┘
Task 28 (감지) — 독립
```

### 실행 순서
1. **동시 시작:** Task 23 + Task 27 + Task 28
2. **Task 23 완료 후:** Task 24 → Task 25 → Task 26
3. **Task 23 완료 후 (병렬):** Task 30 → Task 31
4. **Task 25 + Task 27 완료 후:** Task 29

---

## 🔵 P6: cmux-style 터미널 MUX — 에이전트 간 텍스트 직접 주입 (v3.7.90~)

**목표:** cmux `surface.send_text` 모방 — Claude 터미널에서 Gemini/Codex 터미널에 직접 명령 주입
**핵심:** Named Pipe (Windows) 기반 IPC + 에이전트 자동 수신/실행 루프

### Phase 1: MUX 코어

[x] Task 32: scripts/vibe_mux.py — Named Pipe MUX 서버 + CLI
    파일: scripts/vibe_mux.py (신규)
    방법: Windows Named Pipe `\\.\pipe\vibe-mux` 서버
          - JSON 프로토콜 (cmux 호환): {"method":"surface.send_text","params":{"terminal":"T2","text":"..."}}
          - terminal.register / terminal.list / surface.send_text / surface.send_key
          - 터미널 레지스트리: 어떤 에이전트가 어떤 파이프에 연결되어 있는지 추적
          - CLI 모드: python vibe_mux.py send-text T2 "분석해줘" / list / send-key T2 enter
    검증: 파이프 서버 기동 후 CLI로 send-text 시 해당 터미널에 텍스트 도달 확인
    의존: 없음

[x] Task 33: scripts/vibe_mux_agent.py — 터미널별 MUX 에이전트 (수신/실행 루프)
    파일: scripts/vibe_mux_agent.py (신규)
    방법: 각 에이전트 터미널에서 백그라운드 스레드로 실행
          - Named Pipe `\\.\pipe\vibe-mux-T{n}` 생성 + MUX 서버에 등록
          - 파이프에서 명령 수신 → cli_agent.run() 호출로 자동 실행
          - PostgreSQL LISTEN 병행: ITCP 메시지도 자동 수신/실행
          - 결과를 ITCP로 반환 (auto_dispatcher.report_task_completion)
    검증: T2 에이전트 루프 기동 → T1에서 send-text → T2가 자동 실행 → 결과 ITCP 반환
    의존: Task 32

### Phase 2: 서버 API + 대시보드 통합

[x] Task 34: server.py에 /api/mux/* REST 엔드포인트 추가
    파일: .ai_monitor/server.py
    방법: POST /api/mux/send-text (터미널에 텍스트 전송)
          GET /api/mux/terminals (활성 터미널 목록)
          POST /api/mux/send-key (특수 키 전송)
          내부: vibe_mux.py의 Named Pipe 클라이언트로 명령 전달
    검증: curl POST /api/mux/send-text → 해당 터미널에서 실행 확인
    의존: Task 32, Task 33

[x] Task 35: cli_agent.py에 MUX 에이전트 자동 등록
    파일: scripts/cli_agent.py
    방법: run() 시작 시 vibe_mux_agent 백그라운드 스레드 자동 기동
          - 현재 터미널 ID(T1~T8)를 MUX에 자동 등록
          - stdin=subprocess.PIPE로 변경 (DEVNULL → PIPE)
          - 외부에서 주입된 텍스트를 stdin에 write
    검증: 대시보드에서 에이전트 실행 시 MUX 자동 등록 + send-text 수신 가능 확인
    의존: Task 32, Task 33

### Phase 3: 자동 오케스트레이션

[x] Task 36: auto_dispatcher.py를 MUX 기반으로 업그레이드
    파일: scripts/auto_dispatcher.py
    방법: dispatch() → ITCP send() 대신 vibe_mux send_text() 사용
          - 에이전트가 실행 중이면 MUX로 직접 명령 주입 (즉시)
          - 에이전트가 미실행이면 기존 ITCP 폴백 (다음 실행 시 수신)
          - fan_out()도 MUX 경유로 병렬 주입
    검증: dispatch "보안 점검" → T2 Gemini가 즉시 실행 시작 확인
    의존: Task 34, Task 35

### 의존성 그래프
```
Task 32 (MUX 서버) ──→ Task 33 (에이전트 루프) ──→ Task 35 (cli_agent 통합)
    │                       │                            │
    └──→ Task 34 (서버 API) ←┘                           ↓
                                                    Task 36 (디스패처 업그레이드)
```

### 실행 순서
1. Task 32 (MUX 코어)
2. Task 33 (에이전트 루프) — Task 32 완료 후
3. Task 34 + Task 35 — 병렬 (Task 32, 33 완료 후)
4. Task 36 — 전부 완료 후

---

## 변경 요약
- **P0~P3 완료**: 보안/성능/하이브 인텔리전스 전부 완료.
- **P4 완료**: 멀티-LLM 자율 협업 시스템 전부 완료 (Task 15~22).
  - 디스패처 코어 + 서버 API + ITCP 통합 + 대시보드 UI + 자동 피드백 루프
- **P5 완료**: cmux 기반 vibe CLI + 알림 시스템 고도화 (Task 23~31)
- **P6 진행중**: cmux-style 터미널 MUX — 에이전트 간 텍스트 직접 주입 (Task 32~36)
