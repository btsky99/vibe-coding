"""
FILE: tests/test_setup_banner_install_actions.py
DESCRIPTION: Setup banner installer action wiring regression tests.

REVISION HISTORY:
- 2026-07-29 Codex: Require every setup action to use the full toolchain endpoint.
- 2026-07-29 Codex: Guard Claude and all-CLI POST actions against no-op regressions.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_setup_banner_starts_claude_installer():
    source = (
        ROOT / ".ai_monitor" / "vibe-view" / "src" / "components" / "SetupBanner.tsx"
    ).read_text(encoding="utf-8")

    assert "action === 'install_claude'" in source
    assert "`${API_BASE}/api/setup/auto-install`" in source
    assert "/api/tools/install" not in source


def test_setup_banner_starts_all_cli_auto_installer():
    source = (
        ROOT / ".ai_monitor" / "vibe-view" / "src" / "components" / "SetupBanner.tsx"
    ).read_text(encoding="utf-8")

    assert "action === 'install_cli'" in source
    assert "`${API_BASE}/api/setup/auto-install`" in source
    assert "설치 시작 중..." in source
