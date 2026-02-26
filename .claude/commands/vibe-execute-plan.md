---
description: "ai_monitor_plan.md의 계획을 순서대로 실행합니다. 계획 외 작업 추가 금지."
---

당신은 지금 Vibe Coding 계획 실행 프로토콜을 실행합니다.

# 🚀 계획 실행 프로토콜

## 실행 순서

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
