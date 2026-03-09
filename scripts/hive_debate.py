# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_debate.py
# 📝 설명: 하이브 마인드 에이전트 간 토론(Debate) 및 합의(Consensus) 엔진.
#          PostgreSQL 18 기반의 실시간 협업 시스템을 제공합니다.
# ------------------------------------------------------------------------

import os
import sys
import json
import time
import psycopg2
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from scripts.hive_bridge import post_message, log_task

class DebateEngine:
    """하이브 마인드 토론 엔진. 여러 에이전트의 의견을 모아 최적의 결정을 도출합니다."""

    def __init__(self, port=5433):
        self.db_params = {
            "host": "localhost",
            "port": port,
            "user": "postgres",
            "database": "postgres"
        }

    def _get_conn(self):
        conn = psycopg2.connect(**self.db_params)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        return conn

    def create_debate(self, topic, participants=["gemini", "claude"]):
        """새로운 토론 세션을 생성합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO hive_debates (topic, participants, status)
                    VALUES (%s, %s, %s) RETURNING id
                ''', (topic, json.dumps(participants), "open"))
                debate_id = cursor.fetchone()[0]
                
                log_task("SYSTEM", f"🚀 토론 시작: {topic}", status="debate_started")
                print(f"✅ 토론 생성됨 (ID: {debate_id}): {topic}")
                return debate_id
        finally:
            conn.close()

    def post_message(self, debate_id, round, agent, content, msg_type="proposal", vote=0):
        """에이전트의 의견 또는 비판을 게시합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO hive_debate_messages (debate_id, round, agent, type, content, vote_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (debate_id, round, agent, msg_type, content, vote))
                
                print(f"💬 [{agent}] Round {round} {msg_type}: {content[:50]}...")
        finally:
            conn.close()

    def get_debate_status(self, debate_id):
        """현재 토론의 상태와 메시지 목록을 가져옵니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM hive_debates WHERE id = %s", (debate_id,))
                debate = cursor.fetchone()
                
                cursor.execute("SELECT * FROM hive_debate_messages WHERE debate_id = %s ORDER BY created_at ASC", (debate_id,))
                messages = cursor.fetchall()
                
                return {"debate": debate, "messages": messages}
        finally:
            conn.close()

    def close_debate(self, debate_id, final_decision):
        """토론을 종료하고 최종 결정을 기록합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    UPDATE hive_debates 
                    SET status = %s, final_decision = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', ("closed", final_decision, debate_id))
                
                log_task("SYSTEM", f"🏁 토론 종료: {final_decision[:50]}...", status="debate_closed")
                print(f"✅ 토론 종료됨 (ID: {debate_id})")
        finally:
            conn.close()

if __name__ == "__main__":
    # 간단한 자가 테스트
    engine = DebateEngine()
    
    if len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
        did = engine.create_debate(topic)
        
        # Mock Debate
        engine.post_message(did, 1, "gemini", f"'{topic}'에 대해 새로운 아키텍처를 제안합니다.", "proposal")
        time.sleep(1)
        engine.post_message(did, 1, "claude", "제안된 방식은 보안상 취약점이 있을 수 있습니다.", "critique", vote=-1)
        time.sleep(1)
        engine.close_debate(did, f"보안이 강화된 '{topic}' 하이브리드 모델로 최종 합의됨.")
    else:
        print("사용법: python scripts/hive_debate.py [주제]")
