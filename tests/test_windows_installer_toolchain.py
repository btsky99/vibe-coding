"""
FILE: tests/test_windows_installer_toolchain.py
DESCRIPTION: Regression checks for prerequisite-first Windows installer packaging.

REVISION HISTORY:
- 2026-07-29 Codex: Cover bundled Claude resolution and early single-instance protection.
- 2026-07-29 Codex: Require visible per-tool installation progress in the app.
- 2026-07-29 Codex: Ensure setup stops source-run watchdog/server/PTY before replacing Node.
- 2026-07-29 Codex: Require official Antigravity installer packaging.
- 2026-07-29 Codex: Ensure setup bundles Node/npm and runs every AI CLI installer.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_release_workflow_bundles_node_and_npm():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "Bundle Node.js and npm for first-install AI tools" in workflow
    assert "node-v$nodeVersion-win-x64.zip" in workflow
    assert '".ai_monitor\\bin\\nodejs"' in workflow


def test_installer_runs_full_toolchain_before_first_launch():
    installer = (ROOT / "vibe-coding-setup.iss").read_text(encoding="utf-8")

    assert 'Source: ".ai_monitor\\bin\\nodejs\\*"' in installer
    assert 'Source: "scripts\\install_ai_toolchain.py"' in installer
    assert 'Source: "scripts\\install_antigravity.py"' in installer
    assert "CurStep = ssPostInstall" in installer
    assert "install_ai_toolchain.py" in installer
    assert "ewWaitUntilTerminated" in installer
    assert installer.index("CurStep = ssPostInstall") < installer.index("function InitializeSetup")


def test_installed_app_exposes_bundled_node_path():
    boot = (ROOT / ".ai_monitor" / "boot.py").read_text(encoding="utf-8")

    assert "def _inject_bundled_node_path()" in boot
    assert 'app_dir / "nodejs"' in boot
    assert "_inject_bundled_node_path()" in boot


def test_installer_stops_processes_that_can_respawn_bundled_node():
    installer = (ROOT / "vibe-coding-setup.iss").read_text(encoding="utf-8")

    assert r"\scripts\hive_watchdog.py" in installer
    assert r"\.ai_monitor\server.py" in installer
    assert r"\pty-server\pty-server.js" in installer


def test_first_run_ui_reports_each_core_tool():
    api = (ROOT / ".ai_monitor" / "api" / "setup_api.py").read_text(encoding="utf-8")
    ui = (
        ROOT / ".ai_monitor" / "vibe-view" / "src" / "components" / "SetupBanner.tsx"
    ).read_text(encoding="utf-8")

    assert 'core_ids = ("nodejs", "claude", "codex", "antigravity")' in api
    assert "기본 설치팩" in ui
    assert "확인·설치 중" in ui
    assert "설치됨" in ui
    assert "window.setInterval" in ui


def test_project_claude_wrapper_finds_bundled_cli_without_recursing():
    wrapper = (ROOT / "claude.cmd").read_text(encoding="utf-8")

    assert r"%LOCALAPPDATA%\Programs\VibeCoding\nodejs\claude.cmd" in wrapper
    assert "where claude.cmd" in wrapper
    assert '"%%~fI"=="%~f0"' in wrapper


def test_frozen_app_takes_early_single_instance_mutex():
    boot = (ROOT / ".ai_monitor" / "boot.py").read_text(encoding="utf-8")

    assert "def _acquire_early_windows_instance_mutex()" in boot
    assert r'"Local\\VibeCoding.MainWindow"' in boot
    assert "_acquire_early_windows_instance_mutex()" in boot
