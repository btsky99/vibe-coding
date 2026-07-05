# 구현 계획 — 자가치유 계측 (Self-Heal Metrics)

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 자가치유 2.0의 4장치(회상v2/사고장부/체크포인트/교훈)가 실제로 삽질을 줄이는지 재는
             진단 계기판. 리포트+패널, 4장치 균등, 이중계측(성과+커버리지).

REVISION HISTORY:
- 2026-07-05 Claude: 신규 계획 (이전 'soft 업데이트 채널'은 v3.7.243 출고+트랙B검증 완료로 교체)
-->

> 설계 승인: 2026-07-05 brainstorm. 메모리: `project_heal_metrics.md`
> 목표: "장치는 다 깔렸는데 실제로 삽질을 줄이나?"를 재는 계기판. 북극성=재발률.
> 핵심 원칙: 계산 로직 **단일 소스**(중복 금지). CLI·API·패널이 같은 함수 호출.
> 이중계측: 장치별 *성과 지표* + *기록 성실도(입력 커버리지)*를 나란히 — 재발률 0%+사고 15건이면 "🟡 표본 부족" 경고.

> **스키마 실검증 완료(2026-07-05):**
> - incident_ledger: recurrence_count, created_at, last_seen_at, project_id
> - active_session_context: intent/decisions/next_step, updated_at, agent_id, status
> - zettel_notes: **access_count**, embedding, archived, note_type / hive_memory·agent_experience: **ref_count**, embedding
> - ⚠️ 참조 카운트 컬럼명이 테이블마다 다름(access_count vs ref_count) — 코어가 구분 처리

---

## 마일스톤 A — 계측 코어 + CLI + API (백엔드)

### [x] Task 1: heal_metrics.py 코어 — compute_heal_metrics 단일 소스
- 파일: `.ai_monitor/src/heal_metrics.py` (신규, 표준 헤더)
- 방법: `compute_heal_metrics(project_id: str = '') -> dict`. pg_base.query_rows만 사용(쓰기 없음).
  4장치 섹션 반환:
  - `recall`: 테이블별 임베딩 커버리지(emb/total), 참조율(access_count>0 또는 ref_count>0 / total),
    참조합. zettel=access_count / hive_memory·agent_experience=ref_count 로 컬럼 분기.
  - `incidents`: total, recurred(recurrence_count>1), 재발률, 주별 추이(created_at).
  - `checkpoints`: total, 최근 7일(updated_at), agent별 분포.
  - `lessons`: lessons.md 승인 항목 수(파싱). propose 이력 테이블 없으면 approve율 생략.
  - 각 장치에 `sample_ok: bool`(표본 충분?) + `verdict`(🟢/🟡/🔴) 필드 — 이중계측 핵심.
- 검증: `python -c "import sys;sys.path.insert(0,'.ai_monitor');from src.heal_metrics import compute_heal_metrics as f;import json;print(json.dumps(f(),ensure_ascii=False,indent=2))"` → 4섹션 JSON, 베이스라인(참조합 2·임베딩 37%)과 일치
- 의존성: 없음 (스키마 검증 완료)

### [x] Task 2: heal_report.py — CLI 래퍼
- 파일: `scripts/heal_report.py` (신규, 표준 헤더)
- 방법: compute_heal_metrics 호출 → 터미널 예쁘게 출력(incident.py stats 스타일). 장치별 성과+커버리지 나란히, verdict 이모지, "표본 부족" 경고. `--json` 플래그로 raw 출력.
- 검증: `python scripts/heal_report.py` → 4장치 요약 출력 / `--json` → dict
- 의존성: Task 1

### [x] Task 3: heal_api.py + server.py 위임
- 파일: `.ai_monitor/api/heal_api.py` (신규), `.ai_monitor/server.py`
- 방법: `handle_get(handler, project_id)` → compute_heal_metrics → JSON 응답(오늘 update_api/install_api 패턴). server.py do_GET에 `elif path=='/api/heal/metrics': heal_api.handle_get(self, _current_project_id())` + import 1줄.
- 검증: 서버 기동 후 `curl localhost:9000/api/heal/metrics` → 200 JSON. server.py 줄 수 +3 이내
- 의존성: Task 1

---

## 마일스톤 B — 패널 (프론트, 읽기 전용)

### [x] Task 4: HealPanel.tsx + 라우팅
- 파일: `.ai_monitor/vibe-view/src/components/panels/HealPanel.tsx` (신규), `App.tsx`
- 방법: `withProjectId('/api/heal/metrics')` fetch → 4장치 카드. 성과 지표 + 커버리지 바 + verdict 뱃지. 표본 부족은 🟡 경고 배너. 폴링 없음(수동 새로고침 or 진입 시 1회). App.tsx 라우팅 1줄.
- 검증: `npm run build` 통과 + Playwright로 패널 렌더/데이터 표시 확인(스크린샷 금지)
- 의존성: Task 3

### [x] Task 5: 베이스라인 메모리 + 문서 갱신
- 파일: `project_heal_metrics.md`(메모리), `PROJECT_MAP.md`
- 방법: v1 실측 베이스라인 확정치 기록 + 신규 파일 4개 역할 PROJECT_MAP 기재. v2 후보(recall 적중률·이어받기 성공률=로깅 훅 필요) 명시.
- 검증: 메모리에 베이스라인 수치 + PROJECT_MAP에 heal_metrics/heal_report/heal_api/HealPanel 등재
- 의존성: Task 4

---

## 실행 순서
1 → (2 ∥ 3) → 4 → 5
- Task 1이 모든 것의 단일 소스 — 먼저.
- 2(CLI)와 3(API)는 1 위에서 병렬 가능.
- 4(패널)는 3(API) 후. 5(문서)는 마지막.

## 범위 고정 (스코프 방어)
- 계측은 **진단만** — access_count=2 원인 수정·임베딩 백필 강제는 **별도 후속 태스크**.
- recall 적중률·이어받기 성공률(로깅 훅 필요)은 **v2 분리** — v1은 기존 테이블 직접 조회 가능한 것만.
- 지표는 데이터 있는 것만, 없으면 "미측정"으로 정직하게.
