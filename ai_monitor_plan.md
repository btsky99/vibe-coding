<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 프로젝트 전체 보안/성능/품질 고도화 + 멀티-LLM 자율 협업 로드맵
REVISION HISTORY:
- 2026-03-17 Claude: P4 멀티-LLM 자율 협업 시스템 구축 계획 추가
- 2026-03-16 Claude: P0 보안 5건 + P1 성능/안정성 5건 전부 완료
- 2026-03-16 Claude: P0 보안 + P1 성능/안정성 + P2 코드품질 고도화 계획 수립
-->

# 📋 프로젝트 보안/성능/품질 고도화 + 자율 협업 (v3.7.82)

**작성일:** 2026-03-17
**목표:** P0~P3 완료 → P4 멀티-LLM 자율 협업 시스템 구축

---

## 🔴 P0: 보안 수정 (Critical) — ✅ 전부 완료

[x] Task 1: SQL 인젝션 수정 — server.py parameterized query 전환
[x] Task 2: SQL 인젝션 수정 — hive_bridge.py parameterized query 전환
[x] Task 3: 커맨드 인젝션 수정 — /api/launch
[x] Task 4: 경로 순회 수정 — 파일 접근 API 보안 강화
[x] Task 5: psycopg2 의존성 등록

## 🟡 P1: 성능/안정성 개선 — ✅ 전부 완료

[x] Task 6~10: 에러 핸들링, API_BASE 통합, bare except 정리, PG 포트 통합, ISS 통합

## 🔵 P3: 하이브 인텔리전스 — ✅ 전부 완료

[x] Task 11~14: Red Team, Living Doc, Consensus, Drift Detection

---

## 🟣 P4: 멀티-LLM 자율 협업 시스템 (v3.7.82~)

**목표:** Claude(T1) + Gemini(T2) + Codex(T3)가 자율적으로 작업 분배/실행/검증

[x] Task 15: 자율 태스크 디스패처 (auto_dispatcher.py) 구현
    - 에이전트 역량 프로필 기반 자동 매칭 알고리즘
    - Fan-Out/Fan-In 병렬 분배 패턴
    - 크로스 검증 루프: 작성자 ≠ 검증자 강제
    - CLI: dispatch, fan-out, verify, status, score

[x] Task 16: 서버 디스패처 API 추가
    - GET /api/dispatcher/score — 에이전트별 적합도 점수
    - GET /api/dispatcher/status — 분배 현황
    - POST /api/dispatcher/dispatch — 태스크 자동 분배
    - POST /api/dispatcher/fan-out — 병렬 분배
    - POST /api/dispatcher/verify — 크로스 검증 요청

[x] Task 17: /api/heartbeat Content-Type 수정
    - text/plain → application/json 변환 (JSON 식별 가능하도록)

[x] Task 18: /api/shutdown 엔드포인트 구현
    - 프론트엔드 TopMenuBar.tsx와 정합 (이전: /api/shutdown-disabled → 404)
    - PTY 세션 정리 후 안전 종료

[x] Task 19: T2/T3에 ITCP 작업 지시 전송
    - Gemini(T2): 프론트엔드 점검 + 문서 생성 + 코드 리뷰
    - Codex(T3): 유닛 테스트 + API 통합 테스트 + 안정성 점검

[x] Task 20: 대시보드 디스패처 UI 패널 추가
    - DispatcherPanel.tsx 생성 — 에이전트 역량 바 차트 + 실시간 분배 현황
    - 태스크 디스패치 폼 (유형 자동감지, 에이전트 선택, 우선순위)
    - 적합도 미리보기 + 디스패치 히스토리
    - ActivityBar에 Target 아이콘 탭 추가, App.tsx에 패널 등록
    - 프론트엔드 빌드 완료

[x] Task 21: 자동 디스패치 트리거 — UserPromptSubmit 연동
    - hive_hook.py _INTENT_MAP에 "multi_dispatch" 의도 추가 (최고 우선순위)
    - 키워드: 분담/나눠/T1/T2/T3/제미나이/코덱스/각자/지시해 등
    - auto_dispatcher.py fan-out 자동 호출 가이드 컨텍스트 주입

[x] Task 22: 에이전트 자동 피드백 루프
    - Stop 이벤트 시 수정 파일 있으면 자동 크로스 검증 요청
    - auto_dispatcher.request_verification() 자동 호출
    - 작성자(claude) ≠ 검증자 강제 — ITCP review 채널로 전송

---

## 변경 요약
- **P0~P3 완료**: 보안/성능/하이브 인텔리전스 전부 완료.
- **P4 완료**: 멀티-LLM 자율 협업 시스템 전부 완료 (Task 15~22).
  - 디스패처 코어 + 서버 API + ITCP 통합 + 대시보드 UI + 자동 피드백 루프
