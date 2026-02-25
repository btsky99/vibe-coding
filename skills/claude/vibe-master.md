---
description: "Vibe Coding 중앙 컨트롤 타워. 모든 개발 요청을 분석하여 적절한 워크플로우로 라우팅합니다."
---

당신은 지금 Vibe Coding 마스터 컨트롤 프로토콜을 실행합니다.

# 🌐 마스터 컨트롤 프로토콜

## 1단계: 상태 확인 및 요청 분류
- `python scripts/memory.py list`를 실행하여 공유 메모리에 저장된 기술적 결정 사항 로드 **(필수)**
- `.ai_monitor/data/task_logs.jsonl` 최근 5줄을 읽어 다른 에이전트 작업 충돌 여부 확인
- 요청을 분류: (A) 버그 수정 (B) 새 기능 (C) 리팩토링 (D) 문서화

## 2단계: 전략 수립
- **(A) 버그 수정** → `/vibe:debug` 스킬 가동
- **(B) 새 기능** → `/vibe:brainstorm` → `/vibe:write-plan` → `/vibe:execute-plan` 순서
- **(C) 리팩토링** → `/vibe:code-review` 먼저 실행 후 계획 수립
- **(D) 문서화** → `PROJECT_MAP.md`, `CHANGELOG.md` 직접 업데이트

## 3단계: 실행 및 자가 치유
- 실행 중 에러 발생 시 즉시 `/vibe:debug` 모드 전환
- 모든 코드 수정 시 한글 주석 (변경 이력 + 작성자 + 수정 이유) 필수

## 4단계: 완료 후 처리
- `CHANGELOG.md` 업데이트
- `PROJECT_MAP.md` 관련 항목 최신화
- Conventional Commits 형식으로 커밋
- 사용자에게 간결한 완료 보고

어떤 작업을 도와드릴까요?
