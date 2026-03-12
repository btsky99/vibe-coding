# Repository Guidelines

## Project Structure & Module Organization
- `.ai_monitor/server.py` is the main control server. Keep API changes aligned with the extracted modules in `.ai_monitor/api/` (`agent_api.py`, `hive_api.py`, `git_api.py`, `memory_api.py`, etc.).
- `.ai_monitor/src/` holds shared Python helpers and native dashboard resources.
- `.ai_monitor/vibe-view/src/` contains the React/Vite UI rendered inside the native desktop shell. UI components live under `components/` and `components/panels/`.
- `scripts/` contains launchers, bridges, watchdogs, and release helpers. `assets/` stores icons, `docs/` stores project docs, and `skills/` stores assistant-specific automation assets.

## Build, Test, and Development Commands
- `python -m venv .ai_monitor/venv && .ai_monitor\venv\Scripts\pip install -r .ai_monitor\requirements.txt`: create the local Python environment and install backend dependencies.
- `cd .ai_monitor\vibe-view && npm ci`: install frontend dependencies.
- `python .ai_monitor/server.py`: run the server directly for backend work.
- `run_vibe.bat`: preferred Windows launcher.
- `cd .ai_monitor\vibe-view && npm run dev`: start the Vite UI in development mode.
- `python -m py_compile .ai_monitor/server.py`: match the CI syntax gate.
- `ruff check .ai_monitor/server.py --select E9,F821,F823`: run the same Python lint scope used in GitHub Actions.
- `cd .ai_monitor\vibe-view && npm run lint && npm run build`: verify and bundle the frontend.
- `pyinstaller vibe-coding.spec --noconfirm`: build the Windows executable.

## Coding Style & Naming Conventions
- Python uses 4-space indentation and snake_case for modules, functions, and helpers.
- TypeScript/React uses 2-space indentation, semicolons, single quotes, PascalCase component files, and camelCase for hooks/state.
- Keep non-trivial route logic in `.ai_monitor/api/` rather than growing `server.py` further.
- Follow existing naming patterns such as `*_bridge.py`, `*_watchdog.py`, and `*Panel.tsx`.

## Testing Guidelines
- No coverage threshold is enforced today.
- Run focused smoke checks for the area you touched. Existing repo-owned scripts include `.ai_monitor/test_winpty.py`, `.ai_monitor/test_pty.py`, and `scripts/test_discord.py`.
- For frontend changes, run `npm run lint` and `npm run build`. For backend changes, run `py_compile`, `ruff`, and at least one relevant smoke script.

## Commit & Pull Request Guidelines
- Follow the current history: Conventional Commit style with optional scopes, for example `feat(ui): ...`, `fix: ...`, `build: ...`.
- Keep commits small and separate UI, backend, and release-packaging work when possible.
- PRs should include the problem statement, linked issues, verification commands, and screenshots or GIFs for dashboard/UI changes.

## Configuration & Security
- Copy `.env.template` to `.env` for Discord integration and keep real tokens and channel IDs out of git.
- Treat logs, `dist/`, `build/`, and machine-local `.ai_monitor/data/` changes as non-source artifacts unless a release or fixture update explicitly requires them.

## GitHub CLI & Token Efficiency
- **NEVER** use external GitHub MCP servers unless explicitly requested.
- **ALWAYS** use the GitHub CLI (`gh`) directly or via `scripts/utils/gh_helper.py` to minimize token consumption.
- When using `gh`, prefer `--json` with specific fields (e.g., `gh pr list --json number,title`) to avoid fetching unnecessary metadata.
- Use `GitHubHelper.run_gh()` for automated tasks to ensure data trimming (removal of URLs, timestamps, etc.) is applied before the AI processes the result.
