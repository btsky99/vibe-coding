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

## 2026-07-14 — 자가치유 장치(회상 v2 등)는 '작동한다'고 가정 말고 계측으로 실사용을 확인할 것 — 메커니즘이 맞아도 
자가치유 장치(회상 v2 등)는 '작동한다'고 가정 말고 계측으로 실사용을 확인할 것 — 메커니즘이 맞아도 서빙 프로세스 모델 미warm/데몬 미가동으로 실효 0일 수 있음
근거: 2026-07-05: vector_search는 정상이나 recall-smart가 모델 미warm으로 항상 fallback → 회상 실사용 0. 계측(heal_metrics) 없인 '작동 중'으로 착각했음

## 2026-07-17 — [사고다발] .ai_monitor/vibe-view/src/components/TerminalSlot.tsx
[사고다발] .ai_monitor/vibe-view/src/components/TerminalSlot.tsx — 30일 내 사고 3건. 이 파일 수정 전 incident.py search로 과거 원인 필독
근거: 원인들: Codex: wham/usage 실응답 스키마(rate_limit.primary_window/reset_at / TUI 마우스 리포팅(DECSET 1000/1002) 중 xterm이 좌클릭 드래그를 TUI로 전달해 로컬  / TUI(claude CLI)가 마우스 리포팅 DECSET 1000/1006을 켜면 xterm이 드래그를 전부

## 2026-07-17 — [사고다발] scripts/hive_hook.py — 30일 내 사고 3건. 이 파일 수정 전 inciden
[사고다발] scripts/hive_hook.py — 30일 내 사고 3건. 이 파일 수정 전 incident.py search로 과거 원인 필독
근거: 원인들: recall_client 포트 스캔이 9000부터 첫 응답 서버를 프로젝트 무검증 채택 — 서버별 PG DB / 공유 등록된 훅이 프로젝트 식별을 __file__ 기준으로 해 항상 vibe-coding으로 오인 + act / 대조 로직이 recall_client에 갇혀 있어 같은 패턴 4곳이 미수정으로 잔존 (ab0f1a3의 후속)
