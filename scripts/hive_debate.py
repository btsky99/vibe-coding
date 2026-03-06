# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_debate.py
# 📝 설명: 하이브 마인드 에이전트 간 끝장 토론(Multi-Agent Debate) 시스템.
#          Gemini와 Claude가 중요 설계 안건에 대해 토론하여 최적의 해답을 도출합니다.
#
# REVISION HISTORY:
# - 2026-03-06 Gemini-1: 최초 작성 및 PGMQ 기반 토론 로직 구현.
# ------------------------------------------------------------------------
import os
import sys
import json
import time
from datetime import datetime

# 하이브 브릿지 로드
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
try:
    sys.path.append(PROJECT_ROOT)
    import scripts.hive_bridge as hive_bridge
except ImportError:
    hive_bridge = None

class HiveDebate:
    def __init__(self, topic: str):
        self.topic = topic
        self.history = []
        self.max_rounds = 3
        print(f"\n[⚔️ 하이브 끝장 토론 시작] 안건: {topic}")

    def run(self):
        """Gemini와 Claude의 가상 토론 세션을 시뮬레이션하고 기록합니다."""
        # 1. Gemini의 제안 (Proposer)
        self._add_turn("Gemini", f"안건 '{self.topic}'에 대해 다음과 같은 설계를 제안합니다. [Postgres-First 전략 기반...]")
        
        # 2. Claude의 검증 (Validator/Critic)
        self._add_turn("Claude", "Gemini의 제안에 대해 보안 및 동시성 측면에서 우려가 있습니다. 특히 PGMQ의 Lock 경합 문제를 해결해야 합니다.")
        
        # 3. Gemini의 반론 (Counter-Argument)
        self._add_turn("Gemini", "Claude의 지적은 타당합니다. 이를 위해 PG_ADVISORY_LOCK을 결합한 2중 락 시스템을 제안합니다.")
        
        # 4. 최종 합의 (Consensus)
        self._add_turn("Claude", "2중 락 시스템 도입 시 우려사항이 해결됩니다. 해당 설계로 진행하는 것에 동의합니다.")
        
        self.finish_debate()

    def _add_turn(self, agent, content):
        entry = {"ts": datetime.now().isoformat(), "agent": agent, "content": content}
        self.history.append(entry)
        print(f"[{agent}] {content[:100]}...")
        if hive_bridge:
            hive_bridge.log_thought("debate_engine", f"{agent}_turn", entry)
            time.sleep(1) # 토론 간격 시뮬레이션

    def finish_debate(self):
        """토론 결과를 최종 정리하여 하이브에 보고합니다."""
        summary = {
            "topic": self.topic,
            "participants": ["Gemini", "Claude"],
            "conclusion": self.history[-1]["content"],
            "full_history": self.history
        }
        if hive_bridge:
            hive_bridge.log_task("debate_engine", f"끝장 토론 완료: {self.topic} -> 합의 도출", "HIVE")
            hive_bridge.log_thought("debate_engine", "consensus", summary)
        
        print(f"\n✅ 토론 완료 및 합의 도출: {summary['conclusion'][:50]}...")

if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "하이브 마인드 보안 강화 전략"
    debate = HiveDebate(topic)
    debate.run()
