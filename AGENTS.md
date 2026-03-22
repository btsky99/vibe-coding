# 🤖 하이브 에이전트 구성 (AGENTS.md)

이 파일은 하이브 마인드에 참여하는 각 에이전트의 역할과 연동 가이드를 관리합니다.

---

## 🔵 제미나이 (Gemini)
- **역할**: 전체 설계(Architect), 워크플로우 조율(Orchestrator), 데이터 분석 및 ML 전략.
- **통로**: Gemini CLI (Google AI Studio / Vertex AI)
- **특이사항**: 하이브 마스터 노드로서 모든 계획(`ai_monitor_plan.md`)의 최종 승인권자.

## 🟠 클로드 (Claude)
- **역할**: 정밀 구현(Implementation), 프론트엔드 최적화(React/Tailwind), 고난도 로직 리팩터링.
- **통로**: Claude Code CLI / Desktop App
- **특이사항**: 코드의 시각적 품질과 사용자 경험(UX)을 책임지며, Mission Control UI 구현 전담.

## 🟢 코덱스 (Codex)
- **역할**: 자율 터미널 에이전트(Terminal Agent), 단위 테스트 구현, 반복적 리팩터링, 백그라운드 태스크.
- **통로**: `python scripts/terminal_agent.py` (vibe codex)
- **가이드**: [CODEX_GUIDE.md](./CODEX_GUIDE.md) 참조
- **특이사항**: 제미나이나 클로드의 지시를 ITCP를 통해 수신하여 로컬 환경에서 독립적으로 작업 수행.

---

## 🐝 하이브 오케스트레이션 (Hive Orchestration)
1. **ITCP (Inter-Terminal Communication Protocol)**: PostgreSQL `pg_messages`를 통한 비동기 메시징.
2. **Auto Dispatcher**: 작업 성격에 따라 가장 적합한 에이전트(Gemini, Claude, Codex)를 자동 배정.
3. **Thought Logging**: 모든 에이전트의 사고 과정은 `vibe_agent_thoughts` 테이블에 실시간 기록.
