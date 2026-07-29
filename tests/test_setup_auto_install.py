"""
FILE: tests/test_setup_auto_install.py
DESCRIPTION: First-run sequential automatic dependency installation API regression tests.

REVISION HISTORY:
- 2026-07-29 Codex: Cover duplicate request suppression during active installation.
- 2026-07-29 Codex: Verify failed first attempts remain retryable.
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


def test_auto_install_starts_one_chain_for_node_and_all_missing_clis():
    handler = _Handler()
    setup_api._AUTO_INSTALL_LAST_STARTED = 0.0
    statuses = {
        "tools": [
            _tool("nodejs", False),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_ai_toolchain_installer",
            return_value={"status": "success"},
        ) as launch,
    ):
        assert setup_api.handle_post(handler, "/api/setup/auto-install", {})

    launch.assert_called_once_with()
    assert handler.status == 202
    assert json.loads(handler.wfile.getvalue())["launched"] == [
        "nodejs",
        "claude",
        "codex",
        "antigravity",
    ]


def test_auto_install_starts_only_missing_ai_clis_when_node_is_ready():
    handler = _Handler()
    setup_api._AUTO_INSTALL_LAST_STARTED = 0.0
    statuses = {
        "tools": [
            _tool("nodejs", True),
            _tool("claude", True),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_ai_toolchain_installer",
            return_value={"status": "success"},
        ) as launch,
    ):
        assert setup_api.handle_post(handler, "/api/setup/auto-install", {})

    launch.assert_called_once_with()
    assert json.loads(handler.wfile.getvalue())["launched"] == ["codex", "antigravity"]


def test_auto_install_failure_can_be_retried():
    setup_api._AUTO_INSTALL_LAST_STARTED = 0.0
    statuses = {
        "tools": [
            _tool("nodejs", False),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_ai_toolchain_installer",
            side_effect=[
                {"status": "error", "message": "first failed"},
                {"status": "success", "message": "retry started"},
            ],
        ) as launch,
    ):
        first = _Handler()
        second = _Handler()
        assert setup_api.handle_post(first, "/api/setup/auto-install", {})
        assert setup_api.handle_post(second, "/api/setup/auto-install", {})

    assert launch.call_count == 2
    assert first.status == 500
    assert second.status == 202


def test_auto_install_does_not_open_duplicate_windows():
    statuses = {
        "tools": [
            _tool("nodejs", True),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
        ]
    }
    setup_api._AUTO_INSTALL_LAST_STARTED = 0.0
    with (
        patch("api.tools_api._get_all_status", return_value=statuses),
        patch(
            "api.tools_api.launch_ai_toolchain_installer",
            return_value={"status": "success", "message": "started"},
        ) as launch,
        patch("api.setup_api.time.monotonic", side_effect=[1000.0, 1001.0]),
    ):
        first = _Handler()
        second = _Handler()
        setup_api.handle_post(first, "/api/setup/auto-install", {})
        setup_api.handle_post(second, "/api/setup/auto-install", {})

    launch.assert_called_once_with()
    assert first.status == 202
    assert second.status == 200
    assert json.loads(second.wfile.getvalue())["status"] == "running"
