"""
FILE: tests/test_zettel_sync_mirror.py
DESCRIPTION: Tests for mirroring the local Obsidian vault into a shared Google Drive vault.

REVISION HISTORY:
- 2026-05-03 Codex: Add non-destructive vault mirror coverage.
"""

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import zettel_sync


def test_mirror_vault_copies_grouped_structure_and_keeps_target_only_files(tmp_path):
    source = tmp_path / "local"
    target = tmp_path / "gdrive"
    (source / "영구지식").mkdir(parents=True)
    (source / "작업기록").mkdir()
    (source / "_project" / "vibe-coding").mkdir(parents=True)
    (target / "crypto").mkdir(parents=True)

    (source / "영구지식" / "vibe-1.md").write_text("permanent", encoding="utf-8")
    (source / "작업기록" / "vibe-2.md").write_text("fleeting", encoding="utf-8")
    (source / "_project" / "vibe-coding" / "PROJECT_MAP.md").write_text("map", encoding="utf-8")
    (source / "무제.canvas").write_text("canvas", encoding="utf-8")
    (target / "crypto" / "keep.md").write_text("keep", encoding="utf-8")

    copied = zettel_sync.mirror_vault(source, target)

    assert copied == 4
    assert (target / "영구지식" / "vibe-1.md").read_text(encoding="utf-8") == "permanent"
    assert (target / "작업기록" / "vibe-2.md").read_text(encoding="utf-8") == "fleeting"
    assert (target / "_project" / "vibe-coding" / "PROJECT_MAP.md").exists()
    assert (target / "무제.canvas").read_text(encoding="utf-8") == "canvas"
    assert (target / "crypto" / "keep.md").read_text(encoding="utf-8") == "keep"

    assert zettel_sync.mirror_vault(source, target) == 0
