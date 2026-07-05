# 구현 계획 — server.py 디스패치 테이블 재구조화 (Phase 1)

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: server.py do_GET/do_POST의 if/elif 93분기를 라우트 테이블(dict)로 재구조화.
             하이브리드(테이블→legacy 폴백) + 완전성 가드로 회귀 위험 관리. Phase 1=위임 라우트만.

REVISION HISTORY:
- 2026-07-05 Claude: 신규 (이전 '자가치유 계측'은 완료). brainstorm 승인 C(단계적).
-->

> 설계 승인: 2026-07-05 brainstorm(범위 C 단계적). 메모리: `project_server_split_plan.md`
> 목표: do_GET/do_POST(1334줄, 분기 93개)를 2단계 테이블로. Phase 1 ~200줄↓ (server.py 3559→~3350).
> 안전: 하이브리드 폴백(테이블 miss→기존 elif) + 완전성 가드(라우트 누락 시 실패) + 메서드별 커밋.

## 골든 라우트 (HEAD 캡처, 완전성 가드 기준)
- GET: 31 exact + 11 prefix / POST: 36 exact + 13 prefix
- 중첩 처리: exact 테이블 먼저 → prefix 나중 (git/diff는 exact, git/는 prefix)

---

### [ ] Task 1: 완전성 가드 (변경 前 필수)
- 파일: `tests/test_route_table.py` (신규)
- 방법: 골든 라우트 집합을 상수로 고정. server.py 소스에서 라우트 리터럴(dict키·path==·startswith)
  추출 → 골든 ⊆ 추출 assert(누락=실패). prefix 비중첩 assert.
- 검증: 현재 코드에서 pytest 통과(baseline green). 임의 라우트 지우면 실패 확인.
- 의존성: 없음

### [ ] Task 2: 디스패치 인프라 + do_GET 위임 라우트 이전
- 파일: `.ai_monitor/server.py`
- 방법: GET_ROUTES(dict, exact) + GET_PREFIX_ROUTES(list, 원본순서) 모듈레벨. 단순=lambda,
  body읽는 위임=wrapper. do_GET을 `_set_request_pid→exact→prefix→_do_GET_legacy`로 교체.
  위임 라우트만 이전, 인라인은 _do_GET_legacy 잔류.
- 검증: 완전성 가드 + pytest 103 + import 스모크.
- 의존성: Task 1

### [ ] Task 3: do_POST 위임 라우트 이전 (Task 2 동형)
- 파일: `.ai_monitor/server.py`
- 방법: POST_ROUTES + POST_PREFIX_ROUTES. body 선읽기 위임(memory/zettel 등)은 wrapper.
- 검증: 완전성 가드 + pytest 103 + import 스모크.
- 의존성: Task 2

### [ ] Task 4: 문서/메모리
- 방법: dispatch table 도입 + Phase 2(인라인 40개 이전) 후속 명시.
- 의존성: Task 3

## 범위 고정
- Phase 1 = 인프라 + 위임 라우트만. 인라인 40개는 Phase 2.
- 하이브리드 폴백 유지(롤백 안전). 매 단계 완전성 가드 필수(near-miss 재발 방지).
