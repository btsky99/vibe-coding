"""
FILE: scripts/agent_protocol.py
DESCRIPTION: 에이전트 간 협업을 위한 RFC 관리 + 하이브 토론 참여 프로토콜.
             Gemini와 Claude 간의 명확한 역할 분담, 작업 승인, 토론 참여를 지원합니다.

REVISION HISTORY:
- 2026-02-26 Gemini-1: 초기 구현 (하이브 에볼루션 v5.0 Task 5)
- 2026-03-10 Claude: Task 15-3 — DebateParticipant 클래스 추가.
                     에이전트가 PostgreSQL 토론(hive_debates)에 참여하여
                     비판적 의견을 생성·게시하는 프롬프트 체인 구현.
"""

import os
import sys
import json
import time
import textwrap
from datetime import datetime
from pathlib import Path

# 윈도우 CP949 터미널에서 한글/이모지/유니코드 출력 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 프로젝트 루트 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RFC_DIR = os.path.join(BASE_DIR, ".ai_monitor", "data", "rfcs")

class AgentProtocol:
    def __init__(self):
        os.makedirs(RFC_DIR, exist_ok=True)

    def create_rfc(self, title: str, description: str, author: str, assigned_to: str) -> str:
        """새로운 작업 요청서(RFC)를 생성합니다."""
        rfc_id = f"RFC-{int(time.time())}"
        rfc_data = {
            "id": rfc_id,
            "title": title,
            "description": description,
            "author": author,
            "assigned_to": assigned_to,
            "status": "PENDING",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "comments": []
        }
        
        file_path = os.path.join(RFC_DIR, f"{rfc_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(rfc_data, f, indent=2, ensure_ascii=False)
            
        print(f"📄 [RFC 생성] {rfc_id}: {title} (From: {author} -> To: {assigned_to})")
        return rfc_id

    def update_rfc_status(self, rfc_id: str, status: str, comment: str, author: str):
        """RFC의 상태를 업데이트하고 댓글을 남깁니다."""
        file_path = os.path.join(RFC_DIR, f"{rfc_id}.json")
        if not os.path.exists(file_path):
            print(f"[ERROR] RFC를 찾을 수 없습니다: {rfc_id}")
            return
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["status"] = status
        data["updated_at"] = datetime.now().isoformat()
        data["comments"].append({
            "author": author,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        })
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print(f"🔄 [RFC 업데이트] {rfc_id} 상태 변경: {status} by {author}")

    def list_rfcs(self, status: str = None) -> list:
        """RFC 목록을 조회합니다."""
        rfcs = []
        for filename in os.listdir(RFC_DIR):
            if filename.endswith(".json"):
                with open(os.path.join(RFC_DIR, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if status is None or data["status"] == status:
                        rfcs.append(data)
        return sorted(rfcs, key=lambda x: x["created_at"], reverse=True)

class DebateParticipant:
    """하이브 토론(hive_debates) 참여 프로토콜.

    PostgreSQL에서 진행 중인 토론 컨텍스트를 가져오고,
    에이전트 역할에 맞는 구조화된 의견(proposal / critique / synthesis)을
    생성·게시하는 프롬프트 체인을 제공합니다.

    사용 흐름:
        participant = DebateParticipant(agent_name="claude", port=5433)
        prompt = participant.build_prompt(debate_id)   # 프롬프트 확인
        participant.respond(debate_id, content, msg_type="critique")  # 응답 게시
    """

    # 에이전트별 성격 설정 — 토론 시 프롬프트 컨텍스트로 주입됩니다
    AGENT_PERSONAS = {
        "claude": (
            "당신은 Claude입니다. 정밀 로직 구현과 보안을 담당하는 AI입니다.\n"
            "제안의 취약점·보안 위험·엣지 케이스를 비판적으로 분석하고,\n"
            "반드시 대안적 해결 방법을 함께 제시하십시오."
        ),
        "gemini": (
            "당신은 Gemini입니다. 전체 설계와 오케스트레이션을 담당하는 AI입니다.\n"
            "시스템 전체 아키텍처 관점에서 제안을 평가하고,\n"
            "확장성과 통합 용이성 측면의 의견을 제시하십시오."
        ),
    }

    # 라운드별 기본 의견 유형 매핑 (라운드 1=proposal, 2=critique, 3+=synthesis)
    ROUND_TYPE_MAP = {1: "proposal", 2: "critique", 3: "synthesis"}

    def __init__(self, agent_name: str = "claude", port: int = 5433):
        self.agent_name = agent_name.lower()
        self.db_params = {
            "host": "localhost",
            "port": port,
            "user": "postgres",
            "database": "postgres",
        }

    def _get_conn(self):
        """autocommit 모드로 PostgreSQL 연결을 반환합니다."""
        try:
            import psycopg2
            import psycopg2.extensions
            conn = psycopg2.connect(**self.db_params)
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            return conn
        except ImportError:
            raise RuntimeError("psycopg2-binary가 설치되어 있지 않습니다. pip install psycopg2-binary")

    def get_debate(self, debate_id: int) -> dict | None:
        """debate_id에 해당하는 토론 정보와 메시지 목록을 반환합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # 토론 메타 정보 조회
                cur.execute(
                    "SELECT id, topic, status, participants, current_round FROM hive_debates WHERE id = %s",
                    (debate_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                debate = {
                    "id": row[0], "topic": row[1], "status": row[2],
                    "participants": row[3], "current_round": row[4],
                }

                # 지금까지 오간 메시지 전체 조회
                cur.execute(
                    """SELECT round, agent, type, content
                       FROM hive_debate_messages
                       WHERE debate_id = %s
                       ORDER BY created_at ASC""",
                    (debate_id,),
                )
                debate["messages"] = [
                    {"round": r[0], "agent": r[1], "type": r[2], "content": r[3]}
                    for r in cur.fetchall()
                ]
                return debate
        finally:
            conn.close()

    def get_active_debate(self) -> dict | None:
        """현재 open/debating 상태인 가장 최신 토론을 반환합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM hive_debates
                       WHERE status IN ('open', 'debating')
                       ORDER BY id DESC LIMIT 1"""
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self.get_debate(row[0])
        finally:
            conn.close()

    def build_prompt(self, debate_id: int) -> str:
        """주어진 토론의 컨텍스트를 에이전트가 이해할 수 있는 프롬프트 문자열로 변환합니다.

        반환된 문자열을 Claude/Gemini CLI의 입력으로 사용하면
        에이전트가 토론 맥락을 파악하고 의견을 생성할 수 있습니다.
        """
        debate = self.get_debate(debate_id)
        if not debate:
            return f"[ERROR] 토론 ID {debate_id}를 찾을 수 없습니다."

        # 에이전트 페르소나 주입
        persona = self.AGENT_PERSONAS.get(
            self.agent_name,
            f"당신은 {self.agent_name} 에이전트입니다."
        )

        # 이전 메시지 포맷팅
        history_lines = []
        for m in debate["messages"]:
            history_lines.append(
                f"  [Round {m['round']}][{m['agent'].upper()}][{m['type']}] {m['content']}"
            )
        history_text = "\n".join(history_lines) if history_lines else "  (아직 메시지 없음)"

        # 현재 라운드에 맞는 기대 의견 유형 결정
        current_round = debate.get("current_round", 1)
        expected_type = self.ROUND_TYPE_MAP.get(current_round, "synthesis")

        prompt = textwrap.dedent(f"""
            ═══════════════════════════════════════════════
            🧠 하이브 토론 참여 요청 (Debate ID: {debate['id']})
            ═══════════════════════════════════════════════
            [페르소나]
            {persona}

            [토론 주제]
            {debate['topic']}

            [현재 상태]
            Status: {debate['status']} | Round: {current_round}

            [이전 발언 기록]
            {history_text}

            [요청 사항]
            위 토론에 Round {current_round}의 '{expected_type}' 의견으로 참여하십시오.
            - 100자 이내의 명확하고 비판적인 의견을 작성하십시오.
            - 반드시 근거와 대안을 포함하십시오.
            ═══════════════════════════════════════════════
        """).strip()
        return prompt

    def respond(
        self,
        debate_id: int,
        content: str,
        msg_type: str = None,
        vote: int = 0,
    ) -> bool:
        """에이전트의 의견을 hive_debate_messages 테이블에 게시합니다.

        Args:
            debate_id: 참여할 토론 ID
            content:   게시할 의견 내용
            msg_type:  의견 유형 (proposal/critique/synthesis/vote).
                       None이면 현재 라운드에 맞게 자동 결정됩니다.
            vote:      찬반 값 (1=찬성, -1=반대, 0=중립)

        Returns:
            성공 여부
        """
        debate = self.get_debate(debate_id)
        if not debate:
            print(f"[ERROR] 토론 ID {debate_id}를 찾을 수 없습니다.")
            return False

        current_round = debate.get("current_round", 1)
        resolved_type = msg_type or self.ROUND_TYPE_MAP.get(current_round, "synthesis")

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # 의견 삽입
                cur.execute(
                    """INSERT INTO hive_debate_messages
                           (debate_id, round, agent, type, content, vote_value)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (debate_id, current_round, self.agent_name, resolved_type, content, vote),
                )
                # 토론 상태를 'debating'으로 전환 (open 상태였다면)
                cur.execute(
                    """UPDATE hive_debates
                       SET status = 'debating', updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s AND status = 'open'""",
                    (debate_id,),
                )

            print(
                f"✅ [{self.agent_name.upper()}] Round {current_round} '{resolved_type}' 게시 완료\n"
                f"   내용: {content[:80]}{'...' if len(content) > 80 else ''}"
            )
            return True
        except Exception as e:
            print(f"[ERROR] 의견 게시 실패: {e}")
            return False
        finally:
            conn.close()

    def advance_round(self, debate_id: int) -> int:
        """토론을 다음 라운드로 진행시킵니다. 새 라운드 번호를 반환합니다."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE hive_debates
                       SET current_round = current_round + 1,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = %s
                       RETURNING current_round""",
                    (debate_id,),
                )
                new_round = cur.fetchone()[0]
                print(f"⏩ 토론 ID {debate_id} → Round {new_round} 시작")
                return new_round
        finally:
            conn.close()


if __name__ == "__main__":
    # 확장된 CLI 인터페이스
    protocol = AgentProtocol()

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python agent_protocol.py [create|list|update]  — RFC 관리\n"
            "  python agent_protocol.py debate <debate_id> <agent> [msg_type] <content>  — 토론 참여\n"
            "  python agent_protocol.py debate-prompt <debate_id> <agent>               — 프롬프트 출력\n"
        )
        sys.exit(1)

    cmd = sys.argv[1]

    # ── RFC 커맨드 ─────────────────────────────────────
    if cmd == "create":
        protocol.create_rfc(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "list":
        for rfc in protocol.list_rfcs():
            print(f"[{rfc['status']}] {rfc['id']} - {rfc['title']} ({rfc['author']} -> {rfc['assigned_to']})")

    # ── 토론 커맨드 ────────────────────────────────────
    elif cmd == "debate":
        # 사용법: debate <debate_id> <agent> [msg_type] <content>
        if len(sys.argv) < 5:
            print("사용법: python agent_protocol.py debate <debate_id> <agent> [msg_type] <content>")
            sys.exit(1)
        debate_id  = int(sys.argv[2])
        agent_name = sys.argv[3]
        # msg_type은 선택: proposal/critique/synthesis/vote 중 하나면 타입으로 처리
        valid_types = {"proposal", "critique", "synthesis", "vote"}
        if sys.argv[4] in valid_types and len(sys.argv) >= 6:
            msg_type = sys.argv[4]
            content  = " ".join(sys.argv[5:])
        else:
            msg_type = None
            content  = " ".join(sys.argv[4:])

        participant = DebateParticipant(agent_name=agent_name)
        participant.respond(debate_id, content, msg_type=msg_type)

    elif cmd == "debate-prompt":
        # 현재 토론의 프롬프트를 화면에 출력합니다 (에이전트 CLI 입력용)
        if len(sys.argv) < 4:
            print("사용법: python agent_protocol.py debate-prompt <debate_id> <agent>")
            sys.exit(1)
        debate_id  = int(sys.argv[2])
        agent_name = sys.argv[3]
        participant = DebateParticipant(agent_name=agent_name)
        print(participant.build_prompt(debate_id))

    else:
        print(f"알 수 없는 커맨드: {cmd}")
