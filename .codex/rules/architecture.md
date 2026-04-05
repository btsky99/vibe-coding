<!--
FILE: .codex/rules/architecture.md
DESCRIPTION: Codex-focused architecture and API module reference
REVISION HISTORY:
- 2026-04-05 Codex: Added Codex-side architecture and API detail split from top-level guide
-->

# Codex Architecture

## System Shape
- Frontend: React/TypeScript app in `.ai_monitor/vibe-view/`, bundled by Vite.
- Backend: central Python HTTP server in `.ai_monitor/server.py`.
- Data: PostgreSQL 18 is the primary runtime store and message backbone.
- Terminal: PTY support is handled through `.ai_monitor/pty-server/` and PTY APIs.

## Backend Modules
- `.ai_monitor/server.py`: main HTTP entrypoint, static serving, SSE, API routing.
- `.ai_monitor/src/pg_store.py`: PostgreSQL schema, reads, writes, orchestration persistence.
- `.ai_monitor/src/db_helper.py`: DB helpers and transaction wrappers.
- `.ai_monitor/src/file_store.py`: file-backed fallback storage for selected flows.

## API Modules
- `.ai_monitor/api/agent_api.py`: agent lifecycle, launch, stop, status, terminal integration.
- `.ai_monitor/api/hive_api.py`: hive orchestration, health, logs, summaries, message flows.
- `.ai_monitor/api/tasks_api.py`: task CRUD and task status coordination.
- `.ai_monitor/api/dispatcher_api.py`: routing work to the best agent and verification requests.
- `.ai_monitor/api/memory_api.py`: shared memory APIs backed by PostgreSQL.
- `.ai_monitor/api/git_api.py`: git status, worktree flows, commit-related operations.
- `.ai_monitor/api/pty_api.py`: PTY session creation and terminal control.
- `.ai_monitor/api/files_api.py`: file read, save, browse endpoints.
- `.ai_monitor/api/vibe_api.py`: UI status, notifications, progress, sidebar state.

## Frontend Landmarks
- `.ai_monitor/vibe-view/src/App.tsx`: app shell and high-level state coordination.
- `.ai_monitor/vibe-view/src/components/panels/AgentPanel.tsx`: live agent control panel.
- `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`: xterm.js terminal surface.

## Primary References
- Full endpoint contract: [docs/API_SPEC.md](../../docs/API_SPEC.md)
- Full repository map: [PROJECT_MAP.md](../../PROJECT_MAP.md)
- Harness model: [docs/HARNESS_V2.md](../../docs/HARNESS_V2.md)
