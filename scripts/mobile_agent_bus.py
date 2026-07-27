"""
FILE: scripts/mobile_agent_bus.py
DESCRIPTION: Note20-hosted three-agent pilot bus.
             APIS1 Claude (Note20) plans, APIS3 Antigravity (Galaxy Tab S4)
             analyzes over Tailscale SSH, APIS2 Codex (Note20) verifies, and
             APIS1 produces the final handoff. SQLite WAL stores every stage.

REVISION HISTORY:
- 2026-07-27 Codex: Added the first Note20-centered APIS1/APIS2/APIS3 bus pilot.
- 2026-07-27 Codex: Forced UTF-8 terminal output and added persisted result lookup.
- 2026-07-27 Codex: Added job-scoped handoff ACK evidence for verifiable routing.
- 2026-07-27 Codex: Added the APIS1 Telegram gateway and durable update cursor.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path


HOME = Path.home()
BUS_DIR = HOME / "apis-bus"
DB_PATH = BUS_DIR / "agent_bus.sqlite3"
WORK_DIR = HOME / "work"
TAB_HOST = os.environ.get("APIS3_HOST", "100.109.151.7")
TAB_PORT = os.environ.get("APIS3_PORT", "8022")
TAB_USER = os.environ.get("APIS3_USER", "u0_a233")
TAB_KEY = HOME / ".ssh" / "id_ed25519_tabbus"
RUN_TIMEOUT_SECONDS = 10 * 60

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def connect_db() -> sqlite3.Connection:
    """Open the single-device job store with crash-tolerant WAL semantics."""
    BUS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            current_stage TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            final_result TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def record_event(
    conn: sqlite3.Connection,
    job_id: str,
    stage: str,
    agent: str,
    status: str,
    content: str = "",
) -> None:
    """Persist a stage transition before printing it for remote observers."""
    now = time.time()
    conn.execute(
        """
        INSERT INTO events(job_id, stage, agent, status, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, stage, agent, status, content, now),
    )
    conn.execute(
        "UPDATE jobs SET status=?, current_stage=?, updated_at=? WHERE id=?",
        (status, stage, now, job_id),
    )
    conn.commit()
    print(f"[{job_id[:8]}] {stage}: {agent} {status}", flush=True)


def run_process(args: list[str], timeout: int = RUN_TIMEOUT_SECONDS) -> str:
    """Run one agent without a shell and return its clean stdout."""
    result = subprocess.run(
        args,
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=os.environ.copy(),
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        detail = output or (result.stderr or "").strip()
        raise RuntimeError(detail[-4000:] or f"exit code {result.returncode}")
    if not output:
        raise RuntimeError("agent returned no output")
    return output


def run_claude(prompt: str) -> str:
    """Use APIS1 in plan mode so the pilot cannot mutate device files."""
    return run_process(
        ["claude", "-p", "--permission-mode", "plan", prompt],
    )


def run_codex(prompt: str) -> str:
    """Use APIS2 with a read-only sandbox for independent verification."""
    return run_process(
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            prompt,
        ],
    )


def run_antigravity(prompt: str) -> str:
    """Run APIS3 remotely; base64 prevents prompt corruption by nested shells."""
    encoded = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    remote = (
        f"p=$(printf %s {shlex.quote(encoded)} | base64 -d); "
        'cd "$HOME/work" && '
        'antigravity --mode plan -p "$p" --print-timeout 5m'
    )
    return run_process(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-i",
            str(TAB_KEY),
            "-p",
            TAB_PORT,
            f"{TAB_USER}@{TAB_HOST}",
            remote,
        ]
    )


def clipped(value: str, limit: int = 8000) -> str:
    """Bound handoff prompts while retaining the latest result."""
    if len(value) <= limit:
        return value
    return value[:4000] + "\n...[truncated]...\n" + value[-4000:]


def run_pipeline(goal: str) -> dict[str, str]:
    """Execute the fixed three-agent pilot and return all handoff artifacts."""
    conn = connect_db()
    job_id = uuid.uuid4().hex
    now = time.time()
    conn.execute(
        """
        INSERT INTO jobs(id, goal, status, current_stage, created_at, updated_at)
        VALUES (?, ?, 'queued', 'queued', ?, ?)
        """,
        (job_id, goal, now, now),
    )
    conn.commit()

    outputs: dict[str, str] = {}
    try:
        record_event(conn, job_id, "plan", "APIS1-Claude", "running")
        outputs["plan"] = run_claude(
            "You are APIS1, the coordinator. Do not call tools or modify files. "
            "Turn the following goal into a concise analysis assignment for APIS3. "
            f"Include success criteria. This bus job ID is {job_id}. End with the "
            f"exact line HANDOFF_APIS1_TO_APIS3:{job_id}.\n\nGOAL:\n" + goal
        )
        record_event(conn, job_id, "plan", "APIS1-Claude", "completed", outputs["plan"])

        record_event(conn, job_id, "analysis", "APIS3-Antigravity", "running")
        outputs["analysis"] = run_antigravity(
            "You are APIS3, the analyst on Galaxy Tab S4. Do not call tools or modify files. "
            "Analyze APIS1's assignment and return concrete findings and risks. "
            f"You received bus job {job_id} from APIS1 on Note20. End with the exact "
            f"line HANDOFF_APIS3_TO_APIS2:{job_id}.\n\n"
            + clipped(outputs["plan"])
        )
        record_event(
            conn, job_id, "analysis", "APIS3-Antigravity", "completed", outputs["analysis"]
        )

        record_event(conn, job_id, "verify", "APIS2-Codex", "running")
        outputs["verification"] = run_codex(
            "You are APIS2, the verifier. Do not modify files. Check the following "
            "APIS3 analysis against the original goal. The bus captured this response "
            f"from Galaxy Tab S4 for job {job_id}. Verify that APIS3 returned "
            f"HANDOFF_APIS3_TO_APIS2:{job_id}. State PASS if the job ID matches and "
            "the response addresses the assignment; otherwise state FAIL. End with "
            f"the exact line HANDOFF_APIS2_TO_APIS1:{job_id}.\n\nORIGINAL GOAL:\n"
            + goal
            + "\n\nAPIS3 ANALYSIS:\n"
            + clipped(outputs["analysis"])
        )
        record_event(
            conn, job_id, "verify", "APIS2-Codex", "completed", outputs["verification"]
        )

        record_event(conn, job_id, "finalize", "APIS1-Claude", "running")
        outputs["final"] = run_claude(
            "You are APIS1, the coordinator. Do not call tools or modify files. "
            "Produce the final concise answer using APIS3's analysis and APIS2's "
            f"verification for bus job {job_id}. The system recorded completed stages "
            "plan(APIS1), analysis(APIS3), and verify(APIS2). Confirm success only if "
            f"APIS2 returned HANDOFF_APIS2_TO_APIS1:{job_id}. Clearly distinguish "
            "confirmed facts from proposals.\n\n"
            "GOAL:\n"
            + goal
            + "\n\nAPIS3:\n"
            + clipped(outputs["analysis"])
            + "\n\nAPIS2:\n"
            + clipped(outputs["verification"])
        )
        record_event(conn, job_id, "finalize", "APIS1-Claude", "completed", outputs["final"])
        conn.execute(
            """
            UPDATE jobs
            SET status='completed', current_stage='done', updated_at=?, final_result=?
            WHERE id=?
            """,
            (time.time(), outputs["final"], job_id),
        )
        conn.commit()
        return {"job_id": job_id, **outputs}
    except Exception as exc:
        message = str(exc)
        conn.execute(
            "UPDATE jobs SET status='failed', updated_at=?, error=? WHERE id=?",
            (time.time(), message, job_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def show_status(limit: int) -> None:
    """Print recent jobs without requiring an additional service."""
    conn = connect_db()
    rows = conn.execute(
        """
        SELECT id, status, current_stage, goal, datetime(created_at, 'unixepoch', 'localtime') AS created
        FROM jobs ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in rows:
        print(
            f"{row['id'][:8]} {row['status']:<10} {row['current_stage']:<10} "
            f"{row['created']} {row['goal'][:80]}"
        )
    conn.close()


def show_result(job_prefix: str) -> None:
    """Print the persisted final result for one unambiguous job prefix."""
    conn = connect_db()
    rows = conn.execute(
        """
        SELECT id, status, final_result, error
        FROM jobs WHERE id LIKE ? ORDER BY created_at DESC LIMIT 2
        """,
        (job_prefix + "%",),
    ).fetchall()
    conn.close()
    if not rows:
        raise SystemExit(f"job not found: {job_prefix}")
    if len(rows) > 1:
        raise SystemExit(f"ambiguous job prefix: {job_prefix}")
    row = rows[0]
    print(
        json.dumps(
            {
                "job_id": row["id"],
                "status": row["status"],
                "final_result": row["final_result"],
                "error": row["error"],
            },
            ensure_ascii=False,
        )
    )


def setting_get(key: str, default: str = "") -> str:
    """Read a durable gateway setting from the bus database."""
    conn = connect_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def setting_set(key: str, value: str) -> None:
    """Persist a gateway cursor so restarts never replay old Telegram tasks."""
    conn = connect_db()
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


class TelegramGateway:
    """APIS1 ingress: authorized human messages become three-agent bus jobs."""

    def __init__(self) -> None:
        self.token = (HOME / ".apis1_bot_token").read_text(encoding="utf-8").strip()
        allowed_path = HOME / ".apis_allowed_chats"
        self.allowed = {
            line.strip()
            for line in allowed_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        if not self.token or not self.allowed:
            raise RuntimeError("APIS1 token or allowed chat list is empty")
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.offset = int(setting_get("telegram_offset", "0") or "0")
        self.busy = threading.Lock()

    def call(self, method: str, body: dict | None = None) -> object:
        """Call Telegram Bot API without third-party Python packages."""
        request = urllib.request.Request(
            f"{self.api}/{method}",
            data=json.dumps(body or {}).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(payload.get("description") or f"Telegram {method} failed")
        return payload.get("result")

    def send(self, chat_id: str, text: str) -> None:
        """Send bounded plain-text chunks so formatting cannot break delivery."""
        value = str(text or "결과가 비어 있습니다.")
        for index in range(0, len(value), 3900):
            self.call("sendMessage", {"chat_id": chat_id, "text": value[index : index + 3900]})

    def latest_status(self) -> str:
        """Return a compact operator view for Telegram /status."""
        conn = connect_db()
        rows = conn.execute(
            """
            SELECT id, status, current_stage, goal
            FROM jobs ORDER BY created_at DESC LIMIT 5
            """
        ).fetchall()
        conn.close()
        if not rows:
            return "APIS 중앙 버스 정상\n작업 이력 없음"
        lines = ["APIS 중앙 버스 정상", "최근 작업:"]
        lines.extend(
            f"- {row['id'][:8]} {row['status']}/{row['current_stage']} {row['goal'][:50]}"
            for row in rows
        )
        return "\n".join(lines)

    def execute_job(self, chat_id: str, goal: str) -> None:
        """Run the pipeline in a worker so Telegram polling remains alive."""
        if not self.busy.acquire(blocking=False):
            self.send(chat_id, "현재 다른 작업이 실행 중입니다. /status로 확인해 주세요.")
            return
        try:
            self.send(
                chat_id,
                "APIS 중앙 버스 작업 시작\n"
                "APIS1 Claude → APIS3 Antigravity → APIS2 Codex → APIS1",
            )
            result = run_pipeline(goal)
            self.send(chat_id, f"작업 완료 [{result['job_id'][:8]}]\n\n{result['final']}")
        except Exception as exc:
            self.send(chat_id, f"버스 작업 실패: {str(exc)[-3000:]}")
        finally:
            self.busy.release()

    def handle_message(self, message: dict) -> None:
        """Authorize the human sender and map commands to bus actions."""
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        text = str(message.get("text") or "").strip()
        if not chat_id or chat_id not in self.allowed or not text or sender.get("is_bot"):
            return

        command, _, rest = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        if command in ("/start", "/help"):
            self.send(
                chat_id,
                "APIS1 중앙 버스 온라인\n"
                "/run <작업> — 세 에이전트 실행\n"
                "/status — 최근 상태\n"
                "/result <작업ID> — 저장된 최종 결과",
            )
            return
        if command == "/status":
            self.send(chat_id, self.latest_status())
            return
        if command == "/result":
            prefix = rest.strip()
            if not prefix:
                self.send(chat_id, "사용법: /result <작업ID 앞 8자리>")
                return
            conn = connect_db()
            rows = conn.execute(
                "SELECT id, status, final_result, error FROM jobs WHERE id LIKE ? LIMIT 2",
                (prefix + "%",),
            ).fetchall()
            conn.close()
            if len(rows) != 1:
                self.send(chat_id, "작업을 찾지 못했거나 ID가 모호합니다.")
                return
            row = rows[0]
            self.send(
                chat_id,
                f"{row['id'][:8]} {row['status']}\n\n"
                f"{row['final_result'] or row['error'] or '아직 결과 없음'}",
            )
            return

        goal = rest.strip() if command == "/run" else ""
        if not goal and chat.get("type") == "private" and not text.startswith("/"):
            goal = text
        if not goal:
            if command == "/run":
                self.send(chat_id, "사용법: /run <작업 내용>")
            return
        threading.Thread(
            target=self.execute_job,
            args=(chat_id, goal),
            daemon=True,
            name="apis-bus-job",
        ).start()

    def serve(self) -> None:
        """Long-poll Telegram forever and resume after network failures."""
        me = self.call("getMe") or {}
        print(f"APIS1 gateway started (@{me.get('username', '')})", flush=True)
        if self.offset <= 0:
            latest = self.call("getUpdates", {"offset": -1, "limit": 1, "timeout": 0}) or []
            if latest:
                self.offset = int(latest[-1]["update_id"]) + 1
                setting_set("telegram_offset", str(self.offset))
        while True:
            try:
                updates = self.call(
                    "getUpdates",
                    {"offset": self.offset, "timeout": 25, "allowed_updates": ["message"]},
                )
                for update in updates or []:
                    self.offset = int(update["update_id"]) + 1
                    setting_set("telegram_offset", str(self.offset))
                    self.handle_message(update.get("message") or {})
            except Exception as exc:
                print(f"Telegram poll error: {exc}", flush=True)
                time.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description="APIS three-agent mobile bus")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize the SQLite WAL job store")
    run_parser = sub.add_parser("run", help="run one APIS1→APIS3→APIS2→APIS1 pipeline")
    run_parser.add_argument("goal")
    status_parser = sub.add_parser("status", help="show recent jobs")
    status_parser.add_argument("--limit", type=int, default=10)
    result_parser = sub.add_parser("result", help="show one persisted final result")
    result_parser.add_argument("job_prefix")
    sub.add_parser("serve", help="run the APIS1 Telegram gateway")
    args = parser.parse_args()

    if args.command == "init":
        conn = connect_db()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        print(json.dumps({"ok": True, "db": str(DB_PATH), "journal_mode": mode}))
        return 0
    if args.command == "status":
        show_status(args.limit)
        return 0
    if args.command == "result":
        show_result(args.job_prefix)
        return 0
    if args.command == "serve":
        TelegramGateway().serve()
        return 0

    result = run_pipeline(args.goal)
    print("\n=== APIS BUS FINAL ===")
    print(result["final"])
    print(f"\njob_id={result['job_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
