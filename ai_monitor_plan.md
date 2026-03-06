# 🧠 하이브 마인드 "슈퍼 DB" 구축 계획서 (ai_monitor_plan.md)

> 작성: 2026-03-06 (Gemini-1)
> 목표: PostgreSQL 하나로 Vector DB(기억), Search(검색), MQ(메시지 큐)를 통합하여 하이브 마인드의 인프라를 최적화하고 지능을 극대화함.

---

## 🚀 Phase 4: 하이브 "슈퍼 DB" 완전 통합 및 레거시 제거 (Postgres-First)

> **"기존의 모든 JSONL 및 SQLite 레거시를 폐기하고 PostgreSQL 18로 단일화합니다."**

### 4.1. 통합 로깅 시스템 구축 (Postgres)
- [x] `.ai_monitor/bin/pgsql/` 인프라 구축 및 실행 (Port 5433).
- [ ] `pg_logs`, `pg_thoughts`, `pg_messages` 테이블 스키마 설계 및 생성.
- [ ] `scripts/hive_bridge.py`: JSONL 쓰기 중단 및 Postgres PGMQ/Table 기반 전환.

### 4.2. 사고 과정(Thought Stream) 고도화
- [ ] `orchestrator.py`: `_write_thought`를 Postgres `pg_thoughts` 테이블로 전환.
- [ ] AI 사고의 연쇄(Thought Chain)를 `JSONB`로 구조화하여 저장.
- [ ] **[시각화]** Mission Control UI에서 에이전트 간 사고 교차 분석 뷰 구현.

### 4.3. 실시간 시각화 엔진 (Vibe-View)
- [ ] `server.py`: Postgres `LISTEN/NOTIFY` 기반의 실시간 스트리밍 구현.
- [ ] 레거시 SQLite(`hive_mind.db`) 및 JSONL 데이터 마이그레이션 후 파일 삭제.

---

## 🛸 Phase 5: 차세대 "초지능" 고도화 엔진 구현 (Autonomous Evolution)

### 5.1. Self-Healing (자가 치유 엔진)
- [ ] `scripts/heal_daemon.py`: `pg_logs` 에러 감시 및 자동 수리 로직 구현.
- [ ] 에러 발생 시 `execute-plan`과 연동하여 자율 코드 수정 및 테스트 수행.

### 5.2. Knowledge-Graph (지식 그래프 엔진)
- [ ] `pgvector` 기반 전역 코드 및 결정 사항(memory.md) 임베딩.
- [ ] 하이브 마스터가 과거의 맥락을 100% 이해하고 제안하는 'Smart Oracle' 기능.

### 5.3. Multi-Agent Debate (에이전트 끝장 토론)
- [ ] Gemini vs Claude 설계 논쟁 모드 구현.
- [ ] 최상의 정답을 도출하기 위한 논리 검증 시스템 구축.

### 5.4. Autonomous-Release (자율 배포 엔진)
- [ ] 프로젝트 구성을 자동 감지하는 'Smart Builder' 시스템.
- [ ] 버전 업, 빌드, 패키징, 릴리즈 자동화 파이프라인 구축.

---

## 🛠️ 현재 진행 상태 및 마스터 지침
- **전략**: 모든 엔진은 PostgreSQL 18 인프라를 기반으로 작동합니다.
- **상태**: 3대 기본 엔진(Brainstorm, Plan, Execute) 가동 중.
- **목표**: 2026-03-08까지 초지능 엔진 4종 완전 통합.

---

## 🕒 진행 상태 및 이슈 리포트
- **[2026-03-06]**: EDB PostgreSQL 바이너리 설치 성공.
- **[2026-03-06]**: `pgvector` 다운로드 링크 404 이슈 발생 -> 수동 확보 및 로컬 배치 전략으로 선회.

---

## 📢 검증 전략
1. `psql`로 접속하여 `vector`, `pgmq` 익스텐션이 정상 로드되는지 확인.
2. 5433 포트가 윈도우 부팅이나 다른 DB 설치와 무관하게 독립적으로 작동하는지 확인.
3. 데이터 폴더가 프로젝트 루트(`.ai_monitor/data/pgsql_data/`) 내에 안전하게 보관되는지 확인.
