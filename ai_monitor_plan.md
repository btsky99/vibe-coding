<!--
FILE: ai_monitor_plan.md
DESCRIPTION: A+B 묶음 실행 계획 — A. 회상 정밀도 개선(저정보 노이즈 컷) +
             B. 교훈 파이프 소생(사고 클러스터 자동 증류). 2026-07-16 전반 분석 후속.

REVISION HISTORY:
- 2026-07-16 Claude: 신규. 로드맵 ③(a842452) + 포트 대조(1aa84ba) 완료 → 교체.
  사용자 승인: A+B → C → 정리 → D(메타버스 재논의) 순.
-->

# 구현 계획 — A. 회상 정밀도 + B. 교훈 파이프 소생

> **근거**: 2026-07-16 전반 분석 실측 — ① 회상 노이즈(일반 지시에 무관 지식 0.5 유사도
> 주입, 이 세션에서 실증), ② 교훈 증류 승인 1건/후보 0건(재발 트리거만 있는데 재발률 0%라
> 영영 안 발화), ③ 참조율 30%. **북극성**: 삽질 감소 (`project_ultimate_goal`).

## 핵심 사실 (정찰 실측)
- 노이즈 원인 1: `daemons.py:571` 백필이 빈 설명도 '(빈 내용)'으로 임베딩(무한루프 방지) —
  저정보 레코드가 일반 쿼리와 0.5+ 매칭. agent_experience 459건 중 저정보 6건 + 커밋덤프성 다수.
- 노이즈 원인 2: `pg_vector_search.py:157` 임계 0.45 고정 — 짧은 쿼리(저정보)일수록
  임베딩 변별력이 떨어져 무관 매칭 통과.
- 교훈 파이프: `lesson.py:47 propose_candidate` 코드 호출 가능 + dedupe 내장.
  자동 트리거는 `incident.py:71` 재발 시뿐 — 재발률 0%라 영영 무발화.
- 증류 원료 실증: 30일 파일 클러스터 — hive_hook.py 3건, TerminalSlot.tsx 3건 (jsonb
  `files` 컬럼, `jsonb_array_elements_text`로 풀어야 함 — json_* 함수는 타입 불일치).
- [불변식] lessons.md 쓰기는 approve 경로 단 하나 (승인 게이트) — distill은 후보 적재만.

---

## 태스크

### [x] Task 1 (A1): 검색단 저정보 필터
- **파일**: `.ai_monitor/src/pg_vector_search.py`
- **방법**: `_TABLES`에 테이블별 `quality` WHERE 절 추가 — vector_search SQL에 AND 결합.
  - agent_experience: `length(coalesce(description,'')) >= 20`
  - hive_memory: `length(coalesce(title,'') || coalesce(content,'')) >= 30`
  - zettel_notes: `length(coalesce(title,'') || coalesce(content,'')) >= 30`
  - incident_ledger: 필터 없음 (사고는 짧아도 가치 높음)
  쿼리 시점 필터라 데이터 마이그레이션 불필요 — '(빈 내용)' placeholder는 남되 안 뜸.
- **검증**: description='' 경험노트가 vector_search 결과에서 사라짐.

### [x] Task 2 (A2): 저정보 쿼리 임계 상향
- **파일**: `.ai_monitor/api/memory_api.py`
- **방법**: recall-smart 핸들러에서 `min_sim = 0.45 if len(query) >= 20 else 0.60` —
  vector_search 호출에 `min_similarity=min_sim` 전달. 짧은 일반 지시("그럼 진행해")는
  더 높은 확신이 있을 때만 주입.
- **검증**: 저정보 쿼리로 recall-smart POST → 무관 지식 미주입.

### [x] Task 3 (B): 사고 클러스터 자동 증류
- **파일**: `scripts/lesson.py`, `scripts/incident.py`
- **방법**:
  1. lesson.py에 `distill_from_incidents(days=30, min_cluster=3)` 신설 — 파일별 사고
     클러스터(≥3건) 추출 → `propose_candidate(dedupe_key='cluster:'+파일슬러그)`로
     "[사고다발] {파일} — {n}건: 원인 요약" 후보 적재. CLI `distill` 서브커맨드 추가.
  2. incident.py record 성공 직후 `distill_from_incidents()` 조용히 호출(예외 삼킴) —
     매 사고 기록마다 클러스터 재평가, dedupe로 승인 큐 오염 없음.
- **검증**: `lesson.py distill` 실행 → hive_hook/TerminalSlot 클러스터 후보 2건 적재 →
  `lesson.py list`에 노출. 재실행 시 중복 미생성(dedupe).

### [x] Task 4: 회귀 + 커밋
- **방법**: pytest 전체. 저정보 쿼리/정상 쿼리 대조 실측(함수 단위 — recall-smart 서버
  반영은 앱 재시작 후). Conventional Commits 3단 본문. CHANGELOG/메모리 갱신.

---

## 의존성: Task 1·2·3 병렬 가능, Task 4 ← 전체.

## 완료 정의
- 일반 지시에 무관 지식이 주입되지 않음 (저정보 행 차단 + 짧은 쿼리 임계 0.60).
- 사고 3건+ 파일 클러스터가 자동으로 교훈 후보가 됨 — 승인 게이트는 불변.
- 다음: C(회상 활용 계측) → 정리(ty/psycopg3/Vite8, telegram_bridge 분할) → D(메타버스 재논의).
