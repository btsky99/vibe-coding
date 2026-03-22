<!--
FILE: ai_monitor_plan.md
DESCRIPTION: Claude/Gemini 런타임 설정 패널 추가
REVISION HISTORY:
- 2026-03-23 Claude: Claude/Gemini 런타임 설정 패널 추가 계획 수립
- 2026-03-22 Gemini: P7 코덱스 가이드 및 CLI 강화 완료
-->

# Claude/Gemini 런타임 설정 패널 추가

## 목표
대시보드 AgentPanel에 Codex만 있는 런타임 설정 섹션에 Claude, Gemini 설정 패널도 추가

## 태스크

[x] Task 1: Claude/Gemini 상태 변수 및 config 리더 함수 추가
    파일: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx
    방법: CodexSetupState 패턴을 복제하여 claude/gemini용 상태, 리더 함수 추가
    검증: TypeScript 컴파일 에러 없음

[x] Task 2: Claude/Gemini API 호출 함수 추가
    파일: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx
    방법: loadClaudeSetup, loadClaudeToolStatus, saveClaudeSetup, installClaudeCli, openClaudeTerminal + Gemini 동일 패턴
    검증: 함수 정의 완료, useEffect 초기화에 포함

[x] Task 3: Claude/Gemini 런타임 설정 UI 패널 추가
    파일: .ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx
    방법: Codex 런타임 설정 UI를 복제하여 Claude(보라), Gemini(파랑) 테마로 배치. Codex 패널 위에 Claude → Gemini → Codex 순서
    검증: 대시보드에서 3개 에이전트 설정 패널 모두 표시

[ ] Task 4: 서버 config/update API에서 claude/gemini 설정 필드 지원 확인
    파일: .ai_monitor/server.py
    방법: config/update가 범용 키-값 저장이면 추가 작업 불필요. 아니면 claude_enabled, gemini_enabled 필드 추가
    검증: 저장/로드 정상 동작

[ ] Task 5: 빌드 및 통합 테스트
    파일: .ai_monitor/vibe-view/
    방법: npm run build 성공 확인, 대시보드에서 3개 패널 동작 확인
    검증: 빌드 에러 없음, UI 정상 렌더링
