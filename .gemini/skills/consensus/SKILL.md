---
name: consensus
description: 에이전트 간의 의견 충돌이나 중요한 설계 결정 시, 하이브 토론 시스템을 통해 합의를 도출하는 스킬입니다.
---

# 🛡️ 집단 합의 프로토콜 (Collective Consensus)

이 스킬은 독단적인 결정을 지양하고, 하이브 마인드 내의 모든 에이전트(Gemini, Claude, Codex 등)가 동의하거나 최적이라고 판단하는 결론을 내리기 위해 사용합니다.

## 🤝 토론이 필요한 시점 (Trigger)
- **Architectural Shift:** 시스템의 근간이 되는 라이브러리 교체나 DB 스키마 대폭 변경.
- **Ambiguous Requirement:** 사용자의 요청이 모호하여 여러 해석이 가능할 때.
- **Conflicting Decision:** 다른 에이전트가 과거에 내린 결정이나 구현을 수정/삭제해야 할 때.
- **Security Impact:** 보안에 큰 영향을 줄 수 있는 새로운 기능을 도입할 때.

## 🏛️ 토론 프로세스 (Debate Protocol)

### 1. 세션 생성 (Initiate)
`scripts/hive_debate.py "토론 주제"` 명령을 사용하여 새로운 토론 ID를 생성합니다.

### 2. 제안 및 논거 제시 (Proposal)
자신의 제안(Proposal)을 게시하고, 왜 이 방식이 최선인지 구체적인 논거(데이터, 성능, 유지보수성 등)를 제시합니다.
- `scripts/hive_debate.py post [ID] 1 [AGENT_NAME] "제안 내용" proposal`

### 3. 교차 검증 및 비판 (Critique & Cross-Verify)
상대 에이전트(Claude 등)에게 비판적 관점에서 검토를 요청합니다. Red Team 관점에서 취약점을 찾아내도록 유도하십시오.
- `scripts/hive_debate.py post [ID] 1 [OTHER_AGENT] "비판 내용" critique -vote -1`

### 4. 조정 및 합의 (Resolution)
비판 사항을 수용하거나 반박하며 제안을 수정합니다. 최종적으로 모든 참여자가 `+1` 투표를 하거나 합리적인 결론에 도달하면 토론을 종료합니다.
- `scripts/hive_debate.py close [ID] "최종 합의된 결론"`

## 📓 기록 및 전파 (Knowledge Propagation)
최종 합의된 내용은 반드시 다음 장소에 기록하여 **'집단 기억'**으로 만듭니다.
1.  **memory.md:** '주요 기술적 결정(Architectural Decisions)' 섹션에 추가.
2.  **HIVEMIND.md:** '최신 사고 스트림'에 반영하여 가시화.

---
**마지막 업데이트:** 2026-03-17 - [Vibe Coding] 집단 합의(Consensus) 강화
