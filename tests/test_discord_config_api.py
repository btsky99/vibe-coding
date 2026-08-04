"""
FILE: tests/test_discord_config_api.py
DESCRIPTION: Discord 공용 토큰·Node ID·터미널 채널 binding 저장 계약 회귀 테스트.

REVISION HISTORY:
- 2026-08-03 Codex: 최초 작성.
- 2026-08-03 Codex: 공용 토큰 하나와 터미널별 채널 ID v2 스키마로 갱신.
"""
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".ai_monitor"))
from api import discord_config_api


def test_config_round_trip_and_file_does_not_contain_raw_token(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_config_api.os, "name", "posix")
    path = tmp_path / "discord_secrets.dat"
    config = {
        "version": 2, "token": "secret-token", "node_id": "pc1",
        "guild_ids": ["123456789012345"], "user_ids": ["223456789012345"],
        "channels": {"T1": "323456789012345", "T2": "423456789012345"},
    }
    discord_config_api.save_config(path, config)
    assert discord_config_api.load_config(path) == config
    assert "secret-token" not in path.read_text(encoding="utf-8")


def test_invalid_values_are_filtered_while_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_config_api.os, "name", "posix")
    path = tmp_path / "discord_secrets.dat"
    discord_config_api.save_config(path, {
        "version": 2, "token": "token", "node_id": "PC-A",
        "guild_ids": ["123456789012345", "bad"], "user_ids": ["223456789012345"],
        "channels": {"T1": "323456789012345", "T10": "423456789012345", "T2": "bad"},
    })
    loaded = discord_config_api.load_config(path)
    assert loaded["node_id"] == "pc-a"
    assert loaded["guild_ids"] == ["123456789012345"]
    assert loaded["channels"] == {"T1": "323456789012345"}


def test_legacy_per_terminal_tokens_are_not_automatically_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(discord_config_api.os, "name", "posix")
    path = tmp_path / "discord_secrets.dat"
    raw = discord_config_api._protect(b'{"T1":"exposed-old-token"}')
    path.write_text(raw, encoding="utf-8")
    assert discord_config_api.load_config(path) == discord_config_api._empty_config()
