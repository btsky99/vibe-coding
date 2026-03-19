# -*- coding: utf-8 -*-
"""
FILE: scripts/hive_debate.py
DESCRIPTION: 하이브 합의 및 토론 워크플로우 헬퍼 — 에이전트 간 의견 조율.

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.extensions


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.hive_bridge import log_task, log_thought  # noqa: E402


VALID_MESSAGE_TYPES = {"proposal", "critique", "synthesis", "vote"}
DEFAULT_PARTICIPANTS = ["gemini", "claude"]


@dataclass
class DebateMessage:
    debate_id: int
    round_number: int
    agent: str
    content: str
    msg_type: str
    vote: int = 0


class DebateEngine:
    def __init__(self, port: int | None = None) -> None:
        self.db_params = {
            "host": "127.0.0.1",
            "port": int(port or os.environ.get("VIBE_PG_PORT", "5433")),
            "user": "postgres",
            "dbname": "postgres",
        }

    def _get_conn(self):
        conn = psycopg2.connect(**self.db_params)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        return conn

    def create_debate(self, topic: str, participants: list[str] | None = None) -> int:
        normalized_participants = normalize_participants(participants)
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO hive_debates (topic, participants, status)
                    VALUES (%s, %s::jsonb, 'open')
                    RETURNING id
                    """,
                    (topic, json.dumps(normalized_participants)),
                )
                debate_id = int(cursor.fetchone()[0])
        finally:
            conn.close()

        log_task("SYSTEM", f"[debate:create] #{debate_id} {topic}", status="debate_started")
        print(f"Created debate #{debate_id}: {topic}")
        return debate_id

    def get_debate(self, debate_id: int) -> dict | None:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, topic, status, participants, current_round,
                           final_decision, created_at, updated_at
                    FROM hive_debates
                    WHERE id = %s
                    """,
                    (debate_id,),
                )
                debate = cursor.fetchone()
                if not debate:
                    return None
                cursor.execute(
                    """
                    SELECT id, round, agent, type, content, vote_value, created_at
                    FROM hive_debate_messages
                    WHERE debate_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (debate_id,),
                )
                messages = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        result = dict(debate)
        result["participants"] = _decode_participants(result.get("participants"))
        result["messages"] = messages
        return result

    def list_debates(self, status: str | None = None, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if status:
                    cursor.execute(
                        """
                        SELECT id, topic, status, participants, current_round, final_decision,
                               created_at, updated_at
                        FROM hive_debates
                        WHERE status = %s
                        ORDER BY updated_at DESC, id DESC
                        LIMIT %s
                        """,
                        (status, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, topic, status, participants, current_round, final_decision,
                               created_at, updated_at
                        FROM hive_debates
                        ORDER BY updated_at DESC, id DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

        for row in rows:
            row["participants"] = _decode_participants(row.get("participants"))
        return rows

    def post_message(self, message: DebateMessage, advance_round: bool = False) -> None:
        debate = self.get_debate(message.debate_id)
        if not debate:
            raise RuntimeError(f"Debate #{message.debate_id} not found")
        if debate["status"] == "closed":
            raise RuntimeError(f"Debate #{message.debate_id} is already closed")

        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO hive_debate_messages
                        (debate_id, round, agent, type, content, vote_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message.debate_id,
                        message.round_number,
                        message.agent,
                        message.msg_type,
                        message.content,
                        message.vote,
                    ),
                )
                next_round = message.round_number + 1 if advance_round else message.round_number
                cursor.execute(
                    """
                    UPDATE hive_debates
                    SET status = CASE WHEN status = 'open' THEN 'debating' ELSE status END,
                        current_round = GREATEST(current_round, %s),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (next_round, message.debate_id),
                )
        finally:
            conn.close()

        summary = (
            f"[debate:post] #{message.debate_id} r{message.round_number} "
            f"{message.agent} {message.msg_type}"
        )
        log_task("SYSTEM", summary, status="debate_message")
        print(
            f"Posted to debate #{message.debate_id}: "
            f"round={message.round_number} agent={message.agent} type={message.msg_type}"
        )

    def close_debate(self, debate_id: int, final_decision: str) -> None:
        debate = self.get_debate(debate_id)
        if not debate:
            raise RuntimeError(f"Debate #{debate_id} not found")

        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE hive_debates
                    SET status = 'closed',
                        final_decision = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (final_decision, debate_id),
                )
        finally:
            conn.close()

        log_task("SYSTEM", f"[debate:close] #{debate_id} {final_decision[:80]}", status="debate_closed")
        log_thought(
            "system",
            "consensus",
            {
                "type": "decision",
                "title": f"Debate #{debate_id} closed",
                "content": final_decision,
                "debate_id": debate_id,
                "topic": debate["topic"],
            },
        )
        print(f"Closed debate #{debate_id}")


def normalize_participants(participants: list[str] | None) -> list[str]:
    items = participants or DEFAULT_PARTICIPANTS
    normalized = []
    for item in items:
        for part in str(item).split(","):
            value = part.strip().lower()
            if value and value not in normalized:
                normalized.append(value)
    return normalized or DEFAULT_PARTICIPANTS[:]


def _decode_participants(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return [str(item) for item in decoded]
        except Exception:
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _print_debate(debate: dict) -> None:
    participants = ", ".join(debate.get("participants") or [])
    print(f"Debate #{debate['id']}: {debate['topic']}")
    print(f"  status: {debate['status']}")
    print(f"  round: {debate['current_round']}")
    print(f"  participants: {participants or '-'}")
    if debate.get("final_decision"):
        print(f"  final_decision: {debate['final_decision']}")
    print("  messages:")
    messages = debate.get("messages") or []
    if not messages:
        print("    - none")
        return
    for message in messages:
        vote_suffix = ""
        if message.get("vote_value") not in (None, 0):
            vote_suffix = f" vote={message['vote_value']}"
        print(
            "    - "
            f"r{message['round']} {message['agent']} {message['type']}{vote_suffix}: "
            f"{message['content']}"
        )


def _print_list(rows: list[dict]) -> None:
    if not rows:
        print("No debates found.")
        return
    for row in rows:
        participants = ",".join(row.get("participants") or [])
        decision = ""
        if row.get("final_decision"):
            decision = f" decision={row['final_decision'][:60]}"
        print(
            f"#{row['id']} [{row['status']}] round={row['current_round']} "
            f"participants={participants or '-'} topic={row['topic']}{decision}"
        )


def _pop_flag(args: list[str], *names: str) -> str | None:
    for index, token in enumerate(list(args)):
        if token in names:
            if index + 1 >= len(args):
                raise SystemExit(f"Missing value for {token}")
            value = args[index + 1]
            del args[index : index + 2]
            return value
    return None


def _pop_bool_flag(args: list[str], *names: str) -> bool:
    for index, token in enumerate(list(args)):
        if token in names:
            del args[index]
            return True
    return False


def _parse_create_args(args: list[str]) -> tuple[str, list[str]]:
    work = list(args)
    participants_value = _pop_flag(work, "--participants")
    topic = " ".join(work).strip()
    if not topic:
        raise SystemExit("Usage: python scripts/hive_debate.py create [--participants a,b] <topic>")
    participants = normalize_participants([participants_value] if participants_value else None)
    return topic, participants


def _parse_post_args(args: list[str]) -> tuple[DebateMessage, bool]:
    work = list(args)
    vote = int(_pop_flag(work, "-vote", "--vote") or 0)
    advance_round = _pop_bool_flag(work, "--advance-round")
    if len(work) < 4:
        raise SystemExit(
            "Usage: python scripts/hive_debate.py post <id> <round> <agent> "
            '"content" [proposal|critique|synthesis|vote] [-vote N]'
        )

    debate_id = int(work[0])
    round_number = int(work[1])
    agent = work[2].strip().lower()
    remainder = work[3:]
    msg_type = _default_message_type(round_number)
    if remainder and remainder[-1].lower() in VALID_MESSAGE_TYPES:
        msg_type = remainder[-1].lower()
        remainder = remainder[:-1]
    content = " ".join(remainder).strip()
    if not content:
        raise SystemExit("Post content cannot be empty.")
    return DebateMessage(debate_id, round_number, agent, content, msg_type, vote), advance_round


def _parse_close_args(args: list[str]) -> tuple[int, str]:
    if len(args) < 2:
        raise SystemExit("Usage: python scripts/hive_debate.py close <id> <final_decision>")
    return int(args[0]), " ".join(args[1:]).strip()


def _parse_list_args(args: list[str]) -> tuple[str | None, int]:
    work = list(args)
    status_value = _pop_flag(work, "--status")
    limit_value = _pop_flag(work, "--limit")
    limit = int(limit_value) if limit_value else 10
    return status_value, limit


def _default_message_type(round_number: int) -> str:
    if round_number <= 1:
        return "proposal"
    if round_number == 2:
        return "critique"
    return "synthesis"


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print(
            "Usage:\n"
            '  python scripts/hive_debate.py create "topic"\n'
            '  python scripts/hive_debate.py post <id> <round> <agent> "content" [msg_type] [-vote N]\n'
            '  python scripts/hive_debate.py close <id> "final decision"\n'
            "  python scripts/hive_debate.py show <id>\n"
            "  python scripts/hive_debate.py list [--status open] [--limit 10]"
        )
        return 1

    command = args[0].lower()
    engine = DebateEngine()

    try:
        if command == "create":
            topic, participants = _parse_create_args(args[1:])
            engine.create_debate(topic, participants=participants)
            return 0

        if command == "post":
            message, advance_round = _parse_post_args(args[1:])
            engine.post_message(message, advance_round=advance_round)
            return 0

        if command == "close":
            debate_id, decision = _parse_close_args(args[1:])
            engine.close_debate(debate_id, decision)
            return 0

        if command == "show":
            if len(args) != 2:
                raise SystemExit("Usage: python scripts/hive_debate.py show <id>")
            debate = engine.get_debate(int(args[1]))
            if not debate:
                raise RuntimeError(f"Debate #{args[1]} not found")
            _print_debate(debate)
            return 0

        if command == "list":
            status, limit = _parse_list_args(args[1:])
            _print_list(engine.list_debates(status=status, limit=limit))
            return 0

        topic, participants = _parse_create_args(args)
        engine.create_debate(topic, participants=participants)
        return 0
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
