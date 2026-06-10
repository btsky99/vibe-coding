# 증류된 세션 교훈 (lessons.md)

<!--
FILE: .claude/rules/lessons.md
DESCRIPTION: 세션에서 증류된 프로젝트 특화 교훈 저장소. CLAUDE.md가 링크하여
             매 세션 자동 로드됨 — 컨텍스트가 날아가도 교훈은 살아남는다.

REVISION HISTORY:
- 2026-06-10 Claude: 신설 (자가 치유 2.0 ③ Task 16)

[운영 규칙 — 에이전트 필독]
1. 이 파일은 `python scripts/lesson.py approve <id>`로만 항목이 추가된다.
   에이전트가 직접 Edit로 항목을 추가하는 것 금지 — 승인 게이트 우회다.
2. 교훈 후보 제안 의무: 사용자가 같은 내용을 두 번 정정하거나, 같은 실수가
   반복 감지되면 `python scripts/lesson.py propose "교훈" --why "근거"` 실행.
3. 각 교훈은 "다음 세션의 LLM이 같은 삽질을 안 하게 하는 1~3줄"이어야 한다.
   일반 상식/코드로 알 수 있는 것 금지 — CLAUDE.md 규칙 3(LLM 주석)과 동일 기준.
-->

> 승인된 교훈만 아래에 추가된다. 추가: `lesson.py propose` → 사용자 승인 → `lesson.py approve`

---
