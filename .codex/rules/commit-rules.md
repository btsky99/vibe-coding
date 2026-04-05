<!--
FILE: .codex/rules/commit-rules.md
DESCRIPTION: Codex-side commit message template and forbidden patterns
REVISION HISTORY:
- 2026-04-05 Codex: Added Codex-side commit rules split from top-level guide
-->

# Codex Commit Rules

`RULES.md`가 최종 source of truth이며, 여기서는 Codex 작업용 요약만 제공한다.

## Required Format
```text
<type>(<scope>): <50자 이내 요약>

## 변경 이유 (Why)
왜 이 변경이 필요한지, 기존 문제나 배경이 무엇인지 적는다.

## 변경 내용 (What)
- 파일/모듈 단위의 핵심 변경 사항을 적는다.

## 영향 범위 (Impact)
다른 기능에 미치는 영향이나 "없음"을 명시한다.
```

## Allowed Types
- `feat`: 기능 추가
- `fix`: 버그 수정
- `refactor`: 동작 변경 없는 구조 개선
- `docs`: 문서/주석 변경
- `build`: 빌드, 패키징, 배포 관련 변경
- `chore`: 기타 유지보수

## Forbidden
- 제목만 쓰고 본문을 생략하는 커밋
- 이유 없이 모호한 표현만 남기는 커밋
- 영어 제목만 두고 본문 없는 커밋
- `--no-verify`로 검증을 우회하는 커밋
