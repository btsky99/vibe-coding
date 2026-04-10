# 🧬 진화하는 LLM — 에이전트 경험 수집 & 성장 시스템

## 🎯 목표
AI 에이전트가 작업할수록 경험이 쌓이고, 과거 경험을 활용해 더 잘하게 되며,
오피스에서 성장(레벨/스킬)이 시각적으로 보이는 시스템을 만든다.

## 🛠️ 태스크 리스트

### Phase 1: 경험 수집 엔진 (Experience Engine)

- [x] **Task 1: `agent_experience` + `agent_stats` 테이블 생성** ✅
    - 파일: `.ai_monitor/src/pg_store.py`
    - agent_experience: agent_id, task_type(feat/fix/refactor/docs/test), domain(frontend/backend/db/infra), file_patterns(JSONB), duration_sec, outcome(success/fail/partial), xp_earned, session_id, created_at
    - agent_stats: agent_id(PK), total_xp, level, task_count, skill_map(JSONB), streak_days, last_active, updated_at
    - 레벨 공식: level = floor(sqrt(total_xp / 100))
    - `init_schema()`에 CREATE TABLE 추가 + CRUD 함수

- [x] **Task 2: 경험 수집 API** ✅
    - 파일: `.ai_monitor/api/experience_api.py` (신규)
    - POST `/api/experience` — 작업 완료 시 경험 기록 + agent_stats 자동 갱신
    - GET `/api/experience/stats` — 에이전트별 레벨/XP/스킬맵 반환
    - GET `/api/experience/history?agent=claude&limit=20` — 최근 경험 목록
    - XP 가중치: feat=100, fix=60, refactor=40, docs=20, test=50

- [x] **Task 3: server.py 라우팅 연결** ✅
    - 파일: `.ai_monitor/server.py`
    - experience_api의 handle_get/handle_post를 기존 라우터에 연결

- [x] **Task 4: 기존 pg_logs에서 초기 경험 데이터 마이닝** ✅
    - 파일: `.ai_monitor/src/pg_store.py`
    - pg_logs + hive_sessions 커밋 메시지에서 task_type 추출 (feat/fix/refactor prefix)
    - 파일 확장자로 domain 추론 (.tsx→frontend, .py→backend)
    - 초기 시드로 agent_experience 채우기

### Phase 2: 경험 회상 시스템 (Experience Recall)

- [x] **Task 5: 유사 경험 검색 함수** ✅
    - 파일: `.ai_monitor/src/pg_store.py`
    - 입력: 현재 작업 설명(텍스트), domain, task_type
    - agent_experience에서 유사 작업 검색 (domain + task_type 매칭 + 텍스트 유사도)
    - 반환: 과거 경험 목록 (뭘 했는지, 어떻게 했는지, 성공/실패 여부)

- [x] **Task 6: 회상 API 엔드포인트** ✅
    - 파일: `.ai_monitor/api/experience_api.py`
    - GET `/api/experience/recall?query=...&domain=...` — 유사 경험 검색
    - 새 작업 시작 시 "이전에 비슷한 작업을 N번 했고, 마지막엔 이렇게 해결했어" 반환

- [x] **Task 7: 하네스 연동 — 자동 경험 기록 + 자동 회상 주입** ✅
    - `scripts/claude_hook.py` — PostToolUse에서 git commit 감지 시 `_spawn_experience_record()` 호출
    - `scripts/hive_hook.py` — UserPromptSubmit에서 `recall_context_summary()` 자동 주입
    - `scripts/recall.py` — CLI 수동 검색 스크립트
    - 키워드 ILIKE + pg_trgm similarity 하이브리드 검색으로 한글 정확도 개선

### Phase 3: 오피스 시각화 (Gamification)

- [x] **Task 8: 프론트엔드 경험 데이터 폴링** ✅
    - 파일: `.ai_monitor/vibe-view/src/components/office/OfficeApp.tsx`
    - `/api/experience/stats` 주기적 폴링, 에이전트별 레벨/XP 상태 관리

- [x] **Task 9: 에이전트 레벨 뱃지 + XP 바 렌더링** ✅
    - 파일: `.ai_monitor/vibe-view/src/components/office/IsoAgent.tsx`
    - 에이전트 머리 위에 레벨 뱃지 (Lv.7 등)
    - 경험치 바 (현재 XP / 다음 레벨 XP)

- [x] **Task 10: 스킬 트리 패널** ✅
    - 파일: `.ai_monitor/vibe-view/src/components/office/OfficeApp.tsx`
    - 에이전트 클릭 시 스킬맵 표시 (frontend/backend/db/infra 레이더 차트 또는 바)
    - 최근 작업 히스토리도 간단히 표시

## ⚠️ 예상 위험 및 대응
- **XP 인플레이션**: task_type별 기본 XP 가중치로 균형 조절
- **중복 기록**: session_id + agent_id 유니크 제약으로 방지

---
**작성일:** 2026-04-10
**상태:** ✅ 완료 (2026-04-10)
