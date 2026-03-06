# Harness 패턴 이식 — Acceptance Criteria + Plan Validator + 에이전트 자동 중지

## 목표
Claude Code Harness의 핵심 패턴 3가지를 Vibe Coding에 이식하여 에이전트 신뢰도 향상.
1. Acceptance Criteria(완료 조건) 강화 — 태스크마다 "Done When" 명시
2. Plan Validator V1-V5 — 실행 전 계획 품질 자동 검증
3. 에이전트 자동 중지 — 모든 태스크 완료 시 `{"continue": false}` 신호

## 날짜: 2026-03-07

---

- [x] Task 1: vibe-write-plan.md에 완료 조건(Done When) 필드 추가
    파일: .claude/commands/vibe-write-plan.md
    방법: 태스크 형식 템플릿에 `완료 조건:` 필드를 추가하여 모든 계획에 검증 가능한 완료 기준 명시 강제.
          "검증"을 "완료 조건(Done When)"으로 강화 — 단순 확인법이 아닌 통과/실패 판별 가능한 조건으로.
    완료 조건: vibe-write-plan.md에 Done When 필드가 포함된 태스크 템플릿이 있을 것.

- [x] Task 2: vibe-execute-plan.md에 plan_validator 실행 단계 추가
    파일: .claude/commands/vibe-execute-plan.md
    방법: 실행 전 "0단계: 계획 검증" 추가.
          `python scripts/plan_validator.py ai_monitor_plan.md` 실행 후 V1-V5 통과 시에만 진행.
    완료 조건: vibe-execute-plan.md 실행 절차 0번에 plan_validator 호출 단계가 있을 것.
    의존성: Task 3 완료 후 시작 가능.

- [x] Task 3: scripts/plan_validator.py 신규 생성 — V1-V5 검증 엔진
    파일: scripts/plan_validator.py (신규)
    방법: ai_monitor_plan.md를 파싱하여 5가지 품질 규칙 검사.
          V1: 파일 경로 명시 여부 (범위 명확성)
          V2: 방법 필드 존재 여부 (모호성 제거)
          V3: 같은 파일이 2개 이상 태스크에 중복 등장 여부 (겹침 검사)
          V4: 의존성 태스크가 실제 존재하는지 (순서 검증)
          V5: 완료 조건 필드 존재 여부 (Done When 명시)
          검사 통과 → exit(0), 실패 → 경고 출력 후 exit(1).
    완료 조건: `python scripts/plan_validator.py ai_monitor_plan.md` 실행 시 V1-V5 결과가 출력될 것.

- [x] Task 4: hive_hook.py Stop 이벤트에 자동 중지 신호 추가
    파일: scripts/hive_hook.py
    방법: Stop 이벤트 처리부에서 ai_monitor_plan.md를 파싱.
          모든 [ ] 태스크가 [x]로 완료된 경우 stdout에
          `{"continue": false}` JSON 출력 → Claude Code가 세션 자동 종료.
          완료되지 않은 태스크가 있으면 출력하지 않음 (정상 계속).
    완료 조건: 모든 태스크 완료 상태의 plan 파일로 테스트 시 {"continue": false} 출력될 것.
    의존성: Task 3 완료 후 시작 (plan 파싱 로직 재사용).

- [x] Task 5: plan_validator를 UserPromptSubmit 훅에도 연동
    파일: scripts/hive_hook.py
    방법: UserPromptSubmit 이벤트에서 "계획 실행", "execute-plan", "실행해줘" 등의
          키워드 감지 시 plan_validator.py 자동 실행 후 결과를 컨텍스트로 주입.
          검증 실패 시 "⚠️ 계획 검증 실패: V3 파일 중복" 경고를 Claude에게 알림.
    완료 조건: "계획 실행" 입력 시 훅이 validator 결과를 자동으로 주입할 것.
    의존성: Task 3, Task 4 완료 후 시작.

---

## 검증 시나리오 (전체 완료 후)

1. `python scripts/plan_validator.py ai_monitor_plan.md` → V1-V5 검사 결과 출력
2. 모든 태스크 [x] 상태 파일로 hive_hook.py Stop 이벤트 테스트 → `{"continue": false}` 확인
3. vibe-write-plan 스킬 실행 시 새 태스크 형식(Done When 포함) 확인

## 기술 스택
- Python 3.11+ (plan_validator.py, hive_hook.py)
- Markdown 파싱 (정규식 기반, 외부 의존성 없음)
- Claude Code Hooks 시스템 (Stop, UserPromptSubmit)
