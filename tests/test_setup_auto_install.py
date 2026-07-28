"""
FILE: tests/test_setup_auto_install.py
DESCRIPTION: First-run automatic dependency installation API regression tests.

REVISION HISTORY:
- 2026-07-28 Codex: Cover Node-first ordering and missing AI CLI launch behavior.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from api import setup_api


class _Handler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass


def _tool(tool_id: str, installed: bool) -> dict:
    return {"id": tool_id, "installed": installed}


def test_auto_install_starts_node_before_npm_clis():
    handler = _Handler()
    statuses = {
        "tools": [
            _tool("nodejs", False),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    setup_api._AUTO_INSTALL_STARTED.clear()

    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_tool_installer",
            return_value={"status": "success"},
        ) as launch,
    ):
        assert setup_api.handle_post(handler, "/api/setup/auto-install", {})

    launch.assert_called_once_with("nodejs")
    assert handler.status == 202
    assert json.loads(handler.wfile.getvalue())["launched"] == ["nodejs"]


def test_auto_install_starts_only_missing_ai_clis_when_node_is_ready():
    handler = _Handler()
    statuses = {
        "tools": [
            _tool("nodejs", True),
            _tool("claude", True),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    setup_api._AUTO_INSTALL_STARTED.clear()

    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_tool_installer",
            return_value={"status": "success"},
        ) as launch,
    ):
        assert setup_api.handle_post(handler, "/api/setup/auto-install", {})

    assert [call.args[0] for call in launch.call_args_list] == ["codex", "antigravity"]
    assert json.loads(handler.wfile.getvalue())["launched"] == ["codex", "antigravity"]
