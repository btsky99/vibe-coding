---
name: vibe-execute-plan
description: >
  ai_monitor_plan.md의 계획을 순서대로 실행합니다. 계획 외 작업 추가 금지.
  Use when: "계획 실행", "플랜 실행해줘", "계획대로 진행", vibe-write-plan 완료 직후, ai_monitor_plan.md에 태스크 목록이 있을 때.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

당신은 지금 Vibe Coding 계획 실행 프로토콜을 실행합니다.

# 🚀 계획 실행 프로토콜

## 실행 순서

0. **계획 검증 (필수)**: `python scripts/plan_validator.py` 실행
   - exit(0) → 모든 V1-V5 통과 → 즉시 진행
   - exit(1) → 경고 있음 → 경고 내용 보고 후 사용자 승인 받고 진행
   - exit(2) → 치명적 오류 → **실행 중단**, 계획 수정 후 재시작
1. `ai_monitor_plan.md` 로드 — 전체 태스크 목록 확인
2. 의존성 순서대로 태스크 실행
3. 각 태스크 완료 시: "✓ Task N 완료: {내용}" 보고
4. 에러 발생 시 즉시 중단 → `/vibe:debug` 가동

## 완료 후 처리

- `CHANGELOG.md` 업데이트
- `PROJECT_MAP.md` 관련 항목 최신화
- `git commit` (Conventional Commits 형식)
- 완료된 태스크 목록 + 변경 파일 목록 최종 보고

어떤 계획 파일을 실행할까요?
