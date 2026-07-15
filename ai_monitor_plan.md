<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 로드맵 ② 안티그래비티 훅 회상 주입 이식 실행 계획 — recall-smart caller 계측 +
             antigravity_hook BeforeAgent 회상 주입 + 에이전트별 실발화율 분리 계측.

REVISION HISTORY:
- 2026-07-15 Claude: 신규. 지식창고 재설계(P1+P2) 완료 → 교체. 클로드 루프 100%(①, a165156) 후속.
-->

# 구현 계획 — 로드맵 ② 안티그래비티 훅 회상 주입 이식

> **근거**: 2026-07-14 합의 로드맵 (`project_claude_loop_100` 메모리). ① 클로드 루프 100% 실측 검증
> 완료(a165156, recall 전부 warm hit) → ② 안티그래비티는 antigravity_hook.py(BeforeAgent) 구조가
> 이미 있으나 **기록만 하고 회상 주입 미구현** — 저비용 이식 대상.
> **북극성**: 에이전트 확장이 아니라 이미 굴러가는 자가치유 루프의 실효율 완성 (`project_ultimate_goal`).

## 핵심 사실 (정찰 실측, 2026-07-15)
- 원형: `scripts/hive_hook.py:584,674` — 프롬프트 앞 120자로 `smart_recall_summary(short, limit=5)`
  1회 호출, 결과 텍스트를 컨텍스트로 주입. 예외는 전부 삼킴(훅 중단 금지).
- 이식처: `scripts/antigravity_hook.py:489` BeforeAgent — `_build_additional_context()`가 ITCP 수신
  + 의도 감지만 수행. `sys.path`에 `.ai_monitor` 이미 등록(32-34행) → `from src.recall_client import` 가능.
  [제약] BeforeAgent는 빨라야 함(2026-03-18 타임아웃 사고) — recall_client 자체가 2초 상한 + 폴백 내장이라 허용.
- 계측: `memory_api.py:130 _log_recall_event`가 서버 쪽에서 pg_logs(agent='recall') 기록 —
  호출자 구분 없음. `heal_metrics.py:87-114`는 metadata JSON 키(items/reason)만 파싱 → metadata에
  `caller` 추가는 기존 집계 무파괴.

---

## 태스크

### [x] Task 1: recall-smart에 caller 계측 필드 추가
- **파일**: `.ai_monitor/api/memory_api.py`
- **방법**: `/api/memory/recall-smart` 핸들러에서 `caller = str(data.get('caller') or 'claude')[:24]`
  추출 (기본 'claude' = 기존 호출자 하위호환). `_log_recall_event(status, items, project_id, reason, caller)`
  시그니처 확장 — metadata에 `'caller': caller` 추가. task 문자열은 형식 유지(heal_metrics 무관하지만
  사람 열람용으로 `caller=` 접미 허용).
- **검증**: 기존 호출(캐럴러 없음) → metadata.caller='claude', caller='antigravity' 전달 → 그대로 기록.

### [x] Task 2: recall_client.smart_recall_summary에 caller 파라미터
- **파일**: `.ai_monitor/src/recall_client.py`
- **방법**: `smart_recall_summary(query, limit=5, caller='claude')` — 요청 payload에 `'caller': caller`
  포함. 로컬 v1 폴백 경로는 서버 미경유라 계측 없음(기존과 동일, 변경 없음).
- **검증**: hive_hook 기존 호출 무변경 동작(기본값). 시그니처 하위호환.
- **의존**: Task 1과 독립 (병렬 가능).

### [x] Task 3: antigravity_hook BeforeAgent 회상 주입
- **파일**: `scripts/antigravity_hook.py`
- **방법**: `_build_additional_context(prompt)`에 회상 섹션 추가 — hive_hook.py:584 패턴대로
  `short = prompt.strip().replace("\n", " ")[:120]`, `smart_recall_summary(short, limit=5,
  caller='antigravity')` 호출, 결과 있으면 `sections.append(...)`. try/except로 전부 삼킴
  (Gemini CLI는 훅 JSON 오염/지연 시 hook failed — 회상 실패가 훅을 못 죽이게).
  표준 헤더 REVISION HISTORY 갱신.
- **검증**: `echo '{"hook_event_name":"BeforeAgent","prompt":"..."}' | python scripts/antigravity_hook.py`
  → stdout JSON `hookSpecificOutput.additionalContext`에 회상 텍스트 포함.
- **의존**: Task 2 완료 후.

### [x] Task 4: heal_metrics 에이전트별 실발화 분해 (heal_report.py 표시 포함)
- **파일**: `.ai_monitor/src/heal_metrics.py`
- **방법**: `_recall_metrics`의 live 블록에 `callers` 분해 추가 —
  `SELECT coalesce(metadata->>'caller','claude') AS caller, count(*) ... GROUP BY 1` (14일 창, hit/total).
  기존 fire_rate/hit_rate 집계는 무변경.
- **검증**: heal_report 실행 시 live.callers에 claude/antigravity 별 수치 노출.
- **의존**: Task 1 완료 후.

### [x] Task 5: 실측 검증 + 회귀 — 2026-07-15 완료: 훅 주입 hit(items=5, caller=antigravity DB 실측), pytest 127 통과, heal_report 에이전트별 분해(claude 60%/antigravity 100%) 노출
- **방법**: ① 서버 기동 상태에서 Task 3 검증 커맨드 실행 → pg_logs에
  `agent='recall' AND metadata->>'caller'='antigravity'` 행 생성 확인 (DB 실측).
  ② `pytest tests/` 전체 회귀. ③ `python scripts/heal_report.py`로 callers 분해 출력 확인.
- **의존**: 전체 완료 후.

---

## 의존성 요약
- Task 3 ← Task 2 / Task 4 ← Task 1 / Task 5 ← 전체. Task 1·2는 병렬 가능.

## 완료 정의
- 안티그래비티 BeforeAgent가 프롬프트마다 회상 v2를 주입받음 (서버 warm 시 벡터 회상, 불통 시 v1 폴백).
- pg_logs 회상 이벤트가 caller로 구분되어 heal_report에서 에이전트별 실발화율이 보임.
- 기존 클로드 훅 경로는 무변경 동작 (하위호환).
- 배포는 `/vibe-release`로 별도 진행 (미배포 지식창고 재설계 c3ce0c9와 함께 나감).

## 남은 로드맵
③ 코덱스 래퍼 주입 — 오피스 Phase 5(채팅→agent_api 브릿지)가 통로. 이 계획 범위 아님.
