---
name: vibe-code-review
description: >
  코드 품질, 성능, 가독성을 3가지 관점에서 검토합니다. 보안 심층 점검은 /vibe-security를 사용하세요.
  Use when: "코드 리뷰", "리팩터링", "최적화", 배포 전 검토, PR 리뷰 요청 시.
allowed-tools: Read, Bash, Grep, Glob
user-invocable: true
---

당신은 지금 Vibe Coding 코드 리뷰 프로토콜을 실행합니다.

# 🧐 코드 리뷰 프로토콜

## 3가지 검토 관점

> 💡 보안 심층 점검(OWASP Top 10)은 `/vibe-security` 스킬이 전담합니다. 배포 전에는 반드시 별도로 실행하세요.

### ⚡ 성능
- N+1 쿼리, 불필요한 루프
- 메모리 누수 (이벤트 리스너, 타이머 정리)
- 불필요한 재렌더링 (React)

### 🏗️ 코드 품질
- 단일 책임 원칙 위반
- 중복 코드 (DRY 원칙)
- 에러 처리 누락

### 📖 가독성
- 변수/함수명 명확성
- 복잡한 로직에 Why 주석 유무
- 함수 길이 (50줄 초과 여부)

## 결과 형식
```
🔴 Critical: ...
🟡 Warning: ...
🔵 Info: ...
✅ Good: ...
```

무엇을 리뷰할까요?
