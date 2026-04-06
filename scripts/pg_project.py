"""
FILE: scripts/pg_project.py
DESCRIPTION: PostgreSQL project DB resolver shared by script-side logging and messaging utilities.

REVISION HISTORY:
- 2026-04-06 Codex: Added shared project DB resolver so script-side PG writes use the same DB as server/pg_store.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_project_db(project_root: str | Path) -> str:
    """Resolve the per-project PostgreSQL DB name used by the server and pg_store.

    Priority:
    1. `VIBE_PG_DB` when already exported by the server/session
    2. Deterministic name derived from the absolute project path
    3. Fallback to `postgres`
    """
    env_db = os.environ.get("VIBE_PG_DB", "").strip()
    if env_db:
        return env_db

    try:
        root = Path(project_root).resolve()
        proj_raw = str(root).replace("\\", "/").replace(":", "").replace("/", "--")
        project_id = proj_raw.lstrip("-") or "default"
        safe_id = project_id.lower().replace("-", "_").replace(" ", "_")
        safe_id = "".join(ch for ch in safe_id if ch.isalnum() or ch == "_")
        db_name = f"vibe_{safe_id}"[:63]
        if db_name and db_name != "vibe_":
            return db_name
    except Exception:
        pass

    return "postgres"
