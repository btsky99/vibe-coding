---
name: vibe-write-plan
description: >
  승인된 아이디어를 마이크로태스크로 분해하여 ai_monitor_plan.md에 저장합니다.
  Use when: 브레인스토밍 후 설계가 승인되었을 때, "계획 짜줘", "태스크 분해해줘", vibe-brainstorm 완료 직후.
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
---

당신은 지금 Vibe Coding 계획 작성 프로토콜을 실행합니다.

# 📝 구현 계획 작성

**원칙: 계획 승인 전 코드 작성 금지.**

## 절차

1. **코드베이스 스캔**: 수정할 파일들의 현재 상태 파악
2. **태스크 분해**: 각 태스크는 30분 내 완료 가능한 크기로

각 태스크 형식:
```
[ ] Task N: {동사} + {대상} + {목적}
    파일: {경로}
    방법: {구체적인 구현 방법 — 추상적 설명 금지}
    완료 조건: {통과/실패를 판별할 수 있는 Done When 조건}
    의존성: Task N 완료 후 시작 (없으면 생략)
```

**완료 조건 작성 원칙 (Harness 패턴)**:
- "동작한다" ❌ → "python X.py 실행 시 exit(0) 반환" ✅
- "추가한다" ❌ → "UI에서 Y 버튼 클릭 시 Z 결과 확인" ✅
- 검증 명령어나 UI 경로를 명시할수록 좋음

3. **의존성 명시**: "Task 3은 Task 1 완료 후 시작" 형식
4. **계획 저장**: `ai_monitor_plan.md`에 저장
5. **계획 자동 검증**: `python scripts/plan_validator.py` 실행 — V1-V5 통과 확인
6. **승인 요청**: 사용자 확인 후 `/vibe:execute-plan`으로 이동

어떤 기능의 계획을 작성할까요?
