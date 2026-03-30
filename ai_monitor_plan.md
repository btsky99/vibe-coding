<!--
FILE: ai_monitor_plan.md
DESCRIPTION: Paperclip 스타일 에이전트 오케스트레이션 전환 계획
REVISION HISTORY:
- 2026-03-30 Claude: 그룹 채팅 제거 + 하트비트/태스크 기반 오케스트레이션 전환 계획 수립
-->

# Paperclip 스타일 에이전트 오케스트레이션 전환

**상태:** Phase 1-5 완료 (llm_group_chat 폴더 삭제만 보류 — 사용자 확인 필요)
**목표:** 그룹 채팅 제거 → 하트비트 + 태스크 기반 비동기 통신 + 원자적 체크아웃

---

## Phase 1: DB 스키마 + pg_store.py 확장

[ ] Task 1: hive_tasks 테이블에 하트비트/체크아웃 컬럼 추가
    파일: .ai_monitor/src/pg_store.py (ensure_schema 함수, ~line 369)
    방법: ALTER TABLE로 parent_id, checkout_by, checkout_at, result 컬럼 추가
          ensure_schema()에 마이그레이션 구문 추가 (기존 패턴 line 446 참고)
    검증: python -c "from src.pg_store import ensure_schema; ensure_schema()"

[ ] Task 2: task_comments 테이블 생성
    파일: .ai_monitor/src/pg_store.py (ensure_schema 함수)
    방법: CREATE TABLE task_comments (id SERIAL, task_id TEXT REFERENCES hive_tasks,
          author TEXT, content TEXT, created_at TIMESTAMPTZ)
    검증: psql로 테이블 존재 확인
    의존성: Task 1 완료 후

[ ] Task 3: agent_heartbeats 테이블 생성
    파일: .ai_monitor/src/pg_store.py (ensure_schema 함수)
    방법: CREATE TABLE agent_heartbeats (agent_id TEXT PK, status TEXT, last_beat TIMESTAMPTZ,
          current_task TEXT, beat_count INT, config JSONB)
    검증: psql로 테이블 존재 확인
    의존성: Task 1 완료 후

[ ] Task 4: NOTIFY 트리거 생성
    파일: .ai_monitor/src/pg_store.py (ensure_schema 함수)
    방법: CREATE FUNCTION notify_task_assigned() — hive_tasks의 assigned_to 변경 시
          pg_notify('task_assigned', json) 호출하는 트리거 함수 + CREATE TRIGGER
    검증: UPDATE hive_tasks SET assigned_to='test' 후 LISTEN으로 수신 확인
    의존성: Task 1 완료 후

[ ] Task 5: pg_store.py에 원자적 체크아웃 함수 추가
    파일: .ai_monitor/src/pg_store.py
    방법: atomic_checkout(agent_id, task_id) — SELECT ... FOR UPDATE SKIP LOCKED로
          checkout_by, checkout_at 설정. 이미 체크아웃된 태스크는 실패 반환.
          release_checkout(task_id) — 체크아웃 해제
    검증: 두 번 연속 체크아웃 시 두 번째가 실패하는지 확인
    의존성: Task 1 완료 후

[ ] Task 6: pg_store.py에 코멘트/하트비트 CRUD 함수 추가
    파일: .ai_monitor/src/pg_store.py
    방법: add_task_comment(task_id, author, content)
          list_task_comments(task_id)
          record_heartbeat(agent_id, status, current_task)
          list_agent_status() — 전체 에이전트 상태 조회
    검증: 각 함수 호출 후 DB 조회로 데이터 확인
    의존성: Task 2, 3 완료 후

---

## Phase 2: 하트비트 러너

[ ] Task 7: hive_heartbeat.py 기본 프레임 작성
    파일: scripts/hive_heartbeat.py (신규)
    방법: argparse(--agent, --interval) + PostgreSQL LISTEN 'task_assigned' 채널 연결 +
          메인 루프(NOTIFY 수신 또는 타이머 만료 → 깨어남)
    검증: python scripts/hive_heartbeat.py --agent claude-T1 --interval 60 실행 시 LISTEN 대기 확인

[ ] Task 8: 하트비트 프로토콜 9단계 구현
    파일: scripts/hive_heartbeat.py
    방법: 깨어남 → agent_heartbeats 등록 → 할당된 태스크 조회 → atomic_checkout →
          status='working' → CLI 실행(subprocess) → 결과를 task_comments 기록 →
          태스크 status 변경 → status='idle' 복귀
          실패 시 3회 재시도 → blocked 전환 + 코멘트 기록
    검증: 테스트 태스크 할당 후 자동 처리되는지 확인
    의존성: Task 5, 6, 7 완료 후

[ ] Task 9: CLI 어댑터 구현 (Claude/Gemini/Codex)
    파일: scripts/hive_heartbeat.py
    방법: _run_claude(task) → claude --print "태스크 내용" 실행 + 결과 파싱
          _run_gemini(task) → gemini CLI 실행
          _run_codex(task) → codex CLI 실행
          각 어댑터는 (stdout, exit_code) 반환
    검증: 각 CLI가 설치된 환경에서 간단한 태스크 실행 성공
    의존성: Task 8 완료 후

---

## Phase 3: REST API + 기존 코드 연동

[ ] Task 10: tasks_api.py에 하트비트/체크아웃/코멘트 엔드포인트 추가
    파일: .ai_monitor/api/tasks_api.py (기존 파일 확장)
    방법: GET /api/tasks/:id/comments — 태스크 코멘트 조회
          POST /api/tasks/:id/comments — 코멘트 추가
          POST /api/tasks/:id/checkout — 원자적 체크아웃
          GET /api/agents/status — 전체 에이전트 하트비트 상태
          POST /api/agents/:id/trigger — 수동 하트비트 트리거 (pg_notify)
    검증: curl로 각 엔드포인트 호출 성공
    의존성: Task 6 완료 후

[ ] Task 11: server.py에 새 라우트 연결
    파일: .ai_monitor/server.py
    방법: do_GET/do_POST에서 tasks_api 확장 엔드포인트 라우팅 추가
          기존 tasks_api 호출부에 새 함수 전달 (atomic_checkout 등)
    검증: 서버 시작 후 API 호출 성공
    의존성: Task 10 완료 후

[ ] Task 12: auto_dispatcher.py를 새 태스크 시스템에 연동
    파일: scripts/auto_dispatcher.py
    방법: 기존 _save_dispatch_to_hive_tasks() 수정 — assigned_to 설정 시
          pg_notify('task_assigned') 자동 트리거되도록 확인
          디스패치 결과를 task_comments에도 기록
    검증: python scripts/auto_dispatcher.py fan-out "테스트" 후 NOTIFY 수신 확인
    의존성: Task 4, 10 완료 후

---

## Phase 4: UI 고도화

[ ] Task 13: TaskBoardPanel을 Paperclip 스타일 칸반으로 개편
    파일: .ai_monitor/vibe-view/src/components/panels/TaskBoardPanel.tsx (기존 460줄)
    방법: 4컬럼 칸반 (backlog→todo→working→done) + 상태 버튼 전환
          각 카드에 담당 에이전트 뱃지 + 코멘트 수 표시
          태스크 클릭 시 코멘트 목록 + 코멘트 작성 폼
          /api/tasks/:id/comments 호출하여 코멘트 로드
    검증: 브라우저에서 칸반 렌더링 + 코멘트 표시 확인

[ ] Task 14: AgentMonitorPanel 신규 작성
    파일: .ai_monitor/vibe-view/src/components/panels/AgentMonitorPanel.tsx (신규)
    방법: /api/agents/status 폴링(5초) → 에이전트별 카드 표시
          상태 아이콘 (🟢working/💤idle/🔴offline)
          현재 태스크 표시 + 하트비트 횟수
          수동 트리거 버튼 → POST /api/agents/:id/trigger
    검증: 에이전트 상태 변경 시 UI 반영

[ ] Task 15: App.tsx에 새 패널 등록 + GroupChat 탭 제거
    파일: .ai_monitor/vibe-view/src/App.tsx
    방법: GroupChatPanel import 제거 + AgentMonitorPanel import 추가
          탭 목록에서 '그룹채팅' → '에이전트' 교체
    검증: 탭 전환 시 새 패널 표시 + 그룹채팅 탭 없음 확인
    의존성: Task 13, 14 완료 후

---

## Phase 5: 정리 및 문서

[ ] Task 16: llm_group_chat/ 폴더 삭제 + 서버 참조 제거
    파일: llm_group_chat/ (전체 삭제), .mcp.json (groupchat 제거),
          .ai_monitor/server.py (~line 5072-5108 그룹챗 스레드 코드 제거)
    방법: git rm -r llm_group_chat/
          .mcp.json에서 groupchat 항목 삭제
          server.py에서 run_group_chat_server, init_group_chat_bridge 제거
    검증: 서버 시작 시 에러 없음
    의존성: Task 15 완료 후

[ ] Task 17: GroupChatPanel.tsx 삭제
    파일: .ai_monitor/vibe-view/src/components/panels/GroupChatPanel.tsx (삭제)
    방법: 파일 삭제 + 다른 파일에서 GroupChatPanel import 제거
    검증: npx vite build 성공
    의존성: Task 15 완료 후

[ ] Task 18: CLAUDE.md + HIVEMIND.md 업데이트
    파일: CLAUDE.md, HIVEMIND.md
    방법: 그룹 채팅 관련 안내 삭제 → 하트비트/태스크 안내로 교체
    검증: 문서 내 'group_chat' 검색 결과 0건
    의존성: Task 16 완료 후
