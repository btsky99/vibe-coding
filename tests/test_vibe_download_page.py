"""
FILE: tests/test_vibe_download_page.py
DESCRIPTION: btsky.pe.kr Vibe Coding latest-release download wiring regression tests.

REVISION HISTORY:
- 2026-07-28 Codex: Guard DOM element arguments and version-aware GitHub asset selection.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_vibe_page_passes_dom_elements_to_release_parser():
    page = (ROOT / "web" / "vibe-coding" / "index.html").read_text(encoding="utf-8")

    assert "document.getElementById('fullDlBtn')" in page
    assert "document.getElementById('macDlBtn')" in page
    assert "document.getElementById('verInfo')" in page
    assert "winUrl = urls.winUrl" in page
    assert "macUrl = urls.macUrl" in page


def test_release_parser_selects_versioned_installer_assets():
    script = (ROOT / "web" / "site.js").read_text(encoding="utf-8")

    assert "asset.name.startsWith('vibe-coding-setup-')" in script
    assert "asset.name.endsWith('.dmg')" in script
    assert "infoEl.textContent = `최신 버전 ${data.tag_name}" in script
