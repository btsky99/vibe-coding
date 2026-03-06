# 🧠 하이브 마인드 "슈퍼 DB" 구축 계획서 (ai_monitor_plan.md)

> 작성: 2026-03-06 (Gemini-1)
> 목표: PostgreSQL 하나로 Vector DB(기억), Search(검색), MQ(메시지 큐)를 통합하여 하이브 마인드의 인프라를 최적화하고 지능을 극대화함.

---

## 🏗️ Phase 4: 하이브 "슈퍼 DB" 구축 (Postgres is All You Need)

### 4.1. 전용 포터블 PostgreSQL 환경 구축
- [x] `.ai_monitor/bin/pgsql/` 디렉토리 구조 생성.
- [x] PostgreSQL 18 윈도우 64비트 바이너리 확보.
- [x] 포터블 DB 초기화 (`initdb`) 및 포트 **5433** 설정 완료.

### 4.2. PGVector (AI 장기 기억 장치)
- [x] `pgvector` v0.8.2-pg18 배치 완료 (lib/vector.dll + share/extension/).
- [x] `CREATE EXTENSION vector;` 활성화 완료 (v0.8.2).
- [ ] `shared_memory.db`의 지식 이관 준비.

### 4.3. PG Search (지능형 고성능 검색)
- [x] `pg_trgm` v1.6 및 `fuzzystrmatch` v1.2 익스텐션 활성화 완료.
- [ ] 에이전트가 모든 소스 코드를 '의미 단위'로 검색할 수 있는 인덱스 설계.

### 4.4. PGMQ (에이전트 간 고속 통신 큐)
- [x] PGMQ SQL 스크립트 확보 및 DB 적용.
- [x] 에이전트 간의 메시지(messages.jsonl)를 고속 DB 큐 방식으로 전환 고려.
- [x] **[완료]** `pgmq.sql` (SQL-only) 수동 배치 및 `pgmq` 스키마 초기화.

### 4.5. PG Search 고도화 (Elasticsearch급 검색)
- [x] `pg_trgm` 기반 GIN 인덱스 고도화 및 BM25 유사 검색 쿼리 튜닝.
- [x] 하이브 지식 베이스(shared_memory)를 위한 전문 검색 뷰(Materialized View) 구축.

### 4.6. 통합 DB 매니저 및 자동화
- [x] `pg_manager.py`: 시작/중지/상태/setup 커맨드 구현 완료 (UnicodeEncodeError 수정).
- [x] **[완료]** `pg_manager.py`에 PGMQ 초기화 SQL 구문 추가 및 자동 실행 연동.

---

## 🕒 진행 상태 및 이슈 리포트
- **[2026-03-06]**: EDB PostgreSQL 바이너리 설치 성공.
- **[2026-03-06]**: `pgvector` 다운로드 링크 404 이슈 발생 -> 수동 확보 및 로컬 배치 전략으로 선회.

---

## 📢 검증 전략
1. `psql`로 접속하여 `vector`, `pgmq` 익스텐션이 정상 로드되는지 확인.
2. 5433 포트가 윈도우 부팅이나 다른 DB 설치와 무관하게 독립적으로 작동하는지 확인.
3. 데이터 폴더가 프로젝트 루트(`.ai_monitor/data/pgsql_data/`) 내에 안전하게 보관되는지 확인.
