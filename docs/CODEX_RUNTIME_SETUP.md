<!--
FILE: docs/CODEX_RUNTIME_SETUP.md
DESCRIPTION: Per-PC Codex runtime setup guide for installed or cloned Vibe Coding environments.

REVISION HISTORY:
- 2026-03-22 Codex: Added per-PC Codex setup panel guide covering install, auto-dispatch toggle, and local operator prompt.
-->

# Codex Runtime Setup

## Purpose
This panel exists so Codex behavior can be adjusted on each PC after install without editing files by hand.

It covers:

- whether Codex joins automatic dispatch on this PC
- a local operator prompt injected into Codex task bootstrap
- Codex CLI install/status check
- direct Codex terminal launch from the current project path

## UI Location
Open the Agent panel and use `Codex Runtime Setup`.

## Saved Settings
These values are stored per PC in the runtime config:

- `codex_enabled`
- `codex_boot_prompt`
- `last_path`

In development this is usually `.ai_monitor/data/config.json`.
In installed Windows builds this is typically `%APPDATA%/VibeCoding/config.json`.

## Recommended Usage
Use `codex_enabled=false` when that PC should avoid automatic Codex dispatch.

Use `codex_boot_prompt` for short local guidance such as:

- keep changes narrow
- avoid broad refactors
- validate Python before finishing
- prefer project conventions in this repo

## What It Affects
- `scripts/auto_dispatcher.py`: excludes Codex from automatic selection when disabled
- `scripts/itcp.py`: injects the local operator prompt into Codex bootstrap context
- `scripts/cli_agent.py`: reads the same per-PC runtime config path as the server/UI

## Limits
- This does not bundle-install Codex on every PC automatically.
- Each PC still needs the `codex` CLI available locally.
- The local operator prompt affects the non-interactive Codex task path used by the app, not every external terminal workflow.
