"""
FILE: tests/test_windows_installer_toolchain.py
DESCRIPTION: Regression checks for prerequisite-first Windows installer packaging.

REVISION HISTORY:
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
