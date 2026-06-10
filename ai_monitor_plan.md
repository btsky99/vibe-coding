# 자가 치유 2.0 — 삽질 빈도 감소 시스템

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 자가 치유 2.0 구현 계획 — 회상 v2(pgvector) → 사고 장부 → 체크포인트 → 교훈 증류.
             2026-06-10 brainstorm 승인안. 북극성 지표 = 동일 에러 시그니처 재발률.

REVISION HISTORY:
- 2026-06-10 Claude: 최초 작성 (이전 계획 '스킬 정리 + Subagent 위임'은 전 태스크 완료로 교체)
-->

> 승인: 2026-06-10 (사용자 "승인 — 전체 진행"). 메모리: `project_self_heal_2.md`, `memory.md` §3.5
> 순서: Phase ④(회상 v2) → ①(사고 장부) → ②(체크포인트) → ③(교훈 증류)

## 목표
1. 회상을 ILIKE 키워드 → pgvector 임베딩으로 교체. **유사도 0.45 미만 비주입** (무관 회상 노이즈 제거)
2. 고친 에러를 기억하는 사고 장부 — 동일 에러 재발 시 과거 수정법 자동 주입
3. 세션 복구 브리핑을 파일 목록 → 의도(왜/결정/다음) 단위로 격상
4. 세션 교훈을 `.claude/rules/lessons.md`로 증류 (승인 게이트)

## 불변식 (모든 태스크 공통)
- 임베딩/확장/서버 실패 시 **기존 회상 경로 100% 보존** (폴백 의무)
- 파일당 1500줄 한도, 표준 헤더, LLM 주석, project_id 가드(`assert_project_id`)
- 새 외부 의존(onnxruntime 등)은 spec ↔ CI 양쪽 동기 (과거사고 v3.7.215~218)

---

## Phase ④ — 회상 v2 (기반 공사)

### [x] Task 1: embed_service.py 신설 — 고아 임베딩 헬퍼 이관
- **파일**: `.ai_monitor/infra/embed_service.py` (신규 ~150줄), `.ai_monitor/infra/memory_watcher.py`
- **방법**: `memory_watcher.py`의 `embed`/`cosine_sim`/`_get_embedder`를 이관. `embed_floats(text) -> list[float] | None` 추가 (pgvector는 float 리스트 필요, bytes 아님). memory_watcher에는 `from infra.embed_service import embed, cosine_sim` 재노출로 호환 유지
- **검증**: `python -c "import sys; sys.path.insert(0,'.ai_monitor'); from infra.embed_service import embed_floats; v=embed_floats('테스트'); print(len(v))"` → 384
- **의존성**: 없음

### [x] Task 2: pg_vector_search.py 신설 — vector 컬럼 + 검색
- **파일**: `.ai_monitor/src/pg_vector_search.py` (신규 ~250줄), `.ai_monitor/src/pg_schema.py` (ensure 호출 1줄)
- **방법**: `ensure_vector_schema()` — `CREATE EXTENSION IF NOT EXISTS vector` + `zettel_notes`/`hive_memory`/`agent_experience`에 `embedding vector(384)` ADD COLUMN IF NOT EXISTS + 모델명 메타 기록. 확장 실패 시 모듈 플래그 `VECTOR_AVAILABLE=False`로 전 기능 무음 스킵. `vector_search(table, query_vec, project_id, limit)` — 코사인 거리 `<=>` 정렬, 랭킹 = 유사도 + 0.1×log(1+참조횟수) − 시간감쇠(30일 반감)
- **검증**: `pytest tests/test_self_heal_2.py::test_vector_schema` (확장 있음/없음 양쪽 경로)
- **의존성**: Task 1

### [x] Task 3: 임베딩 백필 데몬
- **파일**: `.ai_monitor/infra/daemons.py` (+~60줄, 현재 515줄 → 한도 내), `.ai_monitor/server.py` (래퍼+스레드 시작 ~6줄)
- **방법**: `run_embedding_backfill(env)` — 60초 주기로 3개 테이블의 `embedding IS NULL` 행 배치(50건) 임베딩 채움. warm 모델은 embed_service 싱글톤. 단계 9 데몬 패턴(DaemonEnv) 그대로
- **검증**: 서버 기동 → 기존 zettel 행에 `SELECT count(*) FROM zettel_notes WHERE embedding IS NOT NULL` 증가 확인
- **의존성**: Task 2

### [x] Task 4: recall-smart API
- **파일**: `.ai_monitor/api/memory_api.py` (+~80줄, 현재 208줄)
- **방법**: `POST /api/memory/recall-smart` {query, limit, kinds} → 쿼리 임베딩(서버 warm 모델) → 3개 테이블 vector_search → **유사도 0.45 미만 제외** → 반환 항목 `access_count`/참조 카운트 증가(피드백 루프) → {items, fallback:false}. VECTOR_AVAILABLE=False면 기존 `recall_context_summary`+`recall_knowledge_summary` 결과를 {fallback:true}로 반환
- **검증**: `curl -X POST localhost:9000/api/memory/recall-smart -d '{"query":"오피스 채팅 버그"}'` → 관련 항목만, 무관 쿼리 → items 빈 배열
- **의존성**: Task 2 (Task 3와 병렬 가능)

### [x] Task 5: recall_client.py — 훅용 클라이언트 (폴백 내장)
- **파일**: `.ai_monitor/src/recall_client.py` (신규 ~100줄)
- **방법**: `hook_bridge.py:57` `_find_active_server_port` 패턴 재사용(VIBE_SERVER_PORT 우선). `smart_recall_summary(query, limit)` — recall-smart 호출(타임아웃 2초) → 성공 시 포맷된 요약 텍스트, 실패/타임아웃 시 기존 `recall_context_summary`+`recall_knowledge_summary` 직접 호출. 훅 지연 상한 = 2초 보장
- **검증**: 서버 켜고/끄고 2회 실행 — 둘 다 출력 나오고 끈 쪽은 폴백 경로 로그
- **의존성**: Task 4

### [x] Task 6: hive_hook.py 회상부 교체
- **파일**: `scripts/hive_hook.py` (719~739줄 교체, 현재 1002줄 — 순감 예상)
- **방법**: 경험 회상+지식 회상 2개 블록을 `recall_client.smart_recall_summary` 1회 호출로 통합. 예외 시 무음 통과(기존 동작 유지)
- **검증**: UserPromptSubmit 시뮬: `echo '{"hook_event_name":"UserPromptSubmit","prompt":"오피스 채팅 버그"}' | python scripts/hive_hook.py` → 관련 회상만 출력. 무관 프롬프트("ok 진행해") → 회상 미출력
- **의존성**: Task 5

### [x] Task 7: EXE 패키징 동기 (독립 태스크 — 사고 재발 방지)
- **파일**: `vibe-coding.spec`, `.github/workflows/build-release.yml`, `scripts/build_verify.py`
- **방법**: hiddenimports에 `fastembed`/`onnxruntime`/`tokenizers` 추가 — **spec ↔ CI 양쪽 동시**. build_verify에 `from infra.embed_service import embed_floats` 임포트 체크 추가. 모델 캐시 경로는 DATA_DIR 하위로 고정(EXE 모드 홈 디렉토리 오염 방지)
- **검증**: `pyinstaller vibe-coding.spec --noconfirm` 로컬 빌드 → EXE 기동 → 백필 데몬 로그에 모델 로드 성공 (오프라인이면 폴백 로그)
- **의존성**: Task 3

### [x] Task 8: Phase ④ 테스트
- **파일**: `tests/test_self_heal_2.py` (신규)
- **방법**: ①vector 스키마 양쪽 경로 ②0.45 임계 필터링 ③참조 카운트 증가 ④recall_client 폴백 (서버 mock)
- **검증**: `pytest tests/test_self_heal_2.py -v` 전체 통과
- **의존성**: Task 5

## Phase ① — 사고 장부

### [x] Task 9: pg_incidents.py — incident_ledger
- **파일**: `.ai_monitor/src/pg_incidents.py` (신규 ~200줄), `pg_schema.py` (테이블 등록)
- **방법**: 테이블 (id, project_id, error_signature, error_text, root_cause, fix_description, fix_commit, files JSONB, recurrence_count, last_seen_at, embedding vector(384)). `normalize_signature(text)` — 경로/줄번호/0x주소/타임스탬프/UUID 제거 → sha256. `record_incident`(동일 시그니처면 recurrence_count++ / 수정법 갱신), `search_incidents`(시그니처 정확 → 벡터 유사 순). 쓰기 함수 `assert_project_id` 가드
- **검증**: 같은 에러 경로만 다르게 2회 record → 1행 + recurrence_count=2
- **의존성**: Task 2

### [x] Task 10: incident.py CLI — record/search/stats
- **파일**: `scripts/incident.py` (신규 ~80줄)
- **방법**: `record --error "..." --cause "..." --fix "..." [--commit]` / `search "에러텍스트"` / `stats` — **stats = 북극성 지표**: 재발률(recurrence_count>1 비율), 주별 추이, 최다 재발 Top5
- **검증**: record→search 왕복 + stats 출력
- **의존성**: Task 9

### [x] Task 11: 훅 에러 감지 → 장부 주입
- **파일**: `scripts/hive_hook.py` (+~25줄)
- **방법**: UserPromptSubmit 프롬프트에 `Traceback|Error|Exception|에러|오류` 패턴 감지 시 `search_incidents` → 히트 시 "⚡ [사고 장부] 과거 동일/유사 사고 — 원인/수정법/커밋" 주입. recall_client처럼 무음 폴백
- **검증**: 과거 기록한 에러 텍스트 포함 프롬프트 시뮬 → 장부 주입 출력
- **의존성**: Task 9, Task 6

### [x] Task 12: vibe-debug 스킬에 장부 통합
- **파일**: `.claude/skills/vibe-debug/SKILL.md`
- **방법**: 0단계 "장부 조회(`python scripts/incident.py search`)" 추가 + 마지막 단계 "수정 완료 시 `incident.py record` 의무" 추가
- **검증**: SKILL.md에 두 단계 존재 + 명령 경로 유효
- **의존성**: Task 10

## Phase ② — 의도 단위 체크포인트

### [x] Task 13: 스키마 확장 + checkpoint CLI
- **파일**: `pg_schema.py` (ALTER ~5줄), 해당 pg_store 도메인 모듈 (+~40줄), `scripts/checkpoint.py` (신규 ~60줄)
- **방법**: `active_session_context`에 `intent TEXT, decisions JSONB, next_step TEXT` ADD COLUMN IF NOT EXISTS. `checkpoint.py "의도" --decided "결정" --next "다음"` → 현재 active 세션 행 UPDATE
- **검증**: CLI 실행 → SELECT로 3컬럼 반영 확인
- **의존성**: 없음 (Phase ④와 병렬 가능)

### [x] Task 14: 복구 브리핑 의도 표시
- **파일**: 세션 복구 브리핑 생성부 (`scripts/hook_bridge.py`의 "[세션 복구]" 출력 — 실행 시 정확 위치 확인)
- **방법**: 브리핑에 intent/decisions/next_step 3줄 추가 (값 있을 때만). 기존 파일 목록은 유지
- **검증**: intent 기록 후 세션 복구 시뮬 → "왜/결정/다음" 줄 출력
- **의존성**: Task 13

### [x] Task 15: 체크포인트 규칙 1줄
- **파일**: `CLAUDE.md` (절대 규칙 아님 — §세부 규칙 안내), `.claude/rules/hive-sync.md`
- **방법**: "큰 작업 단계 전환 시 `python scripts/checkpoint.py` 기록" 1줄 추가
- **검증**: 두 파일에 규칙 존재
- **의존성**: Task 13

## Phase ③ — 교훈 증류

### [x] Task 16: lessons.md + lesson.py (승인 게이트)
- **파일**: `.claude/rules/lessons.md` (신규), `CLAUDE.md` (링크 1줄), `scripts/lesson.py` (신규 ~80줄)
- **방법**: `lesson.py propose "교훈" --why "근거"` → hive_memory에 `lesson-candidate:*` 적재. `lesson.py approve <id>` → lessons.md append (날짜+교훈+왜). **approve 없이는 파일 불변** — CLAUDE.md 본문 자동 수정 절대 금지. 에이전트 규칙: 사용자 정정/동일 실수 반복 감지 시 propose 의무 (lessons.md 헤더에 명기)
- **검증**: propose→approve 왕복 → lessons.md에 항목, approve 전엔 파일 무변경
- **의존성**: 없음

### [x] Task 17: 종합 검증 + 문서 갱신
- **파일**: `PROJECT_MAP.md` (자동 재생성), `memory.md`, 신규 파일 줄 수 점검
- **방법**: `pytest tests/` 전체 + `python scripts/generate_project_map.py` + 신규/수정 파일 `wc -l` ≤1500 확인 + 메모리 갱신
- **검증**: 테스트 전체 통과 + 규칙 8 리포트 출력
- **의존성**: Task 8, 11, 12, 14, 15, 16

---

## 의존성 요약
- Task 1→2→{3,4}→5→6→8 (④ 메인 체인), 7은 3 이후 언제든
- Task 9→{10,11}, 12는 10 이후 / ①은 2 완료 후 시작
- Task 13→{14,15} / ②는 독립 — ④와 병렬 가능
- Task 16 독립 / Task 17 최종
