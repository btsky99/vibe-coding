"""
FILE: tests/test_setup_auto_install.py
DESCRIPTION: First-run sequential automatic dependency installation API regression tests.
             + "기본 설치팩"이 이미 깔린 뒤에도 매 실행 다시 뜨던 결함의 회귀
             (자동 = 무창 + 총 3회 상한 / 수동 클릭 = 콘솔 + 무제한).

REVISION HISTORY:
- 2026-08-14 Claude: 자동/수동 경로 분리 + 시도 횟수 디스크 상한 회귀 추가.
  쿨다운이 프로세스 메모리에만 있어 앱 재시작마다 0으로 돌아갔고, 그때마다 설치
  콘솔이 떠 포커스를 뺏었다(절대 규칙 10 계열).
- 2026-07-29 Codex: Cover duplicate request suppression during active installation.
- 2026-07-29 Codex: Verify failed first attempts remain retryable.
- 2026-07-28 Codex: Cover Node-first ordering and missing AI CLI launch behavior.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from api import setup_api, tools_api  # noqa: E402
from infra import runtime  # noqa: E402

# [2026-08-15] obsidian 편입 — 기본 설치팩은 setup_api 와 **같은 순서**여야 한다.
#   launched 목록을 순서까지 비교하는 단언이 있어, 순서가 어긋나면 실패한다.
_CORE = ("nodejs", "claude", "codex", "antigravity", "obsidian")


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """[격리 필수] 시도 횟수 마커는 app_data_dir에 **남는다**. tmp로 돌리지 않으면
    개발 트리(.ai_monitor/data)에 쌓여 테스트가 누적 실행 횟수에 의존하게 되고,
    3회를 넘기는 순간 무관한 테스트가 'exhausted'로 깨진다.
    """
    monkeypatch.setattr(runtime, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(setup_api, "_AUTO_INSTALL_LAST_STARTED", 0.0)


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

    def json(self):
        return json.loads(self.wfile.getvalue())


def _tool(tool_id: str, installed: bool) -> dict:
    return {"id": tool_id, "installed": installed}


def test_auto_install_starts_one_chain_for_node_and_all_missing_clis():
    handler = _Handler()
    statuses = {
        "tools": [
            _tool("nodejs", False),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
            _tool("obsidian", False),
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

    launch.assert_called_once_with(visible=False)
    assert handler.status == 202
    assert handler.json()["launched"] == [
        "nodejs",
        "claude",
        "codex",
        "antigravity",
        "obsidian",
    ]


def test_auto_install_starts_only_missing_ai_clis_when_node_is_ready():
    handler = _Handler()
    statuses = {
        "tools": [
            _tool("nodejs", True),
            _tool("claude", True),
            _tool("codex", False),
            _tool("antigravity", False),
            _tool("obsidian", False),
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

    launch.assert_called_once_with(visible=False)
    assert handler.json()["launched"] == ["codex", "antigravity", "obsidian"]


def test_auto_install_failure_can_be_retried():
    statuses = {
        "tools": [
            _tool("nodejs", False),
            _tool("claude", False),
            _tool("codex", False),
            _tool("antigravity", False),
            _tool("obsidian", False),
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
            _tool("obsidian", False),
        ]
    }
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

    launch.assert_called_once_with(visible=False)
    assert first.status == 202
    assert second.status == 200
    assert second.json()["status"] == "running"


# ── 2026-08-14: "설치 다 됐는데 또 뜬다" 회귀 ─────────────────────────────────

def _prepare(monkeypatch, installed=()):
    """설치 상태·런처를 대역으로 갈아끼우고 visible 인자 기록 리스트를 돌려준다."""
    calls = []
    monkeypatch.setattr(
        tools_api, "_get_all_status",
        lambda: {"tools": [_tool(tid, tid in installed) for tid in _CORE]},
    )
    monkeypatch.setattr(
        tools_api, "launch_ai_toolchain_installer",
        lambda visible=True: (calls.append(visible), {"status": "success", "message": "ok"})[1],
    )
    return calls


def _post(body=None):
    h = _Handler()
    assert setup_api.handle_post(h, "/api/setup/auto-install", body or {}) is True
    return h


def test_auto_path_is_windowless(monkeypatch):
    """[규칙 10] 사람이 안 누른 자동 설치는 콘솔 창을 만들면 안 된다."""
    calls = _prepare(monkeypatch)
    assert _post().json()["status"] == "started"
    assert calls == [False]


def test_manual_click_opens_console(monkeypatch):
    """배너 버튼은 사람이 결과를 보려고 누른 것 — 창을 그대로 연다."""
    calls = _prepare(monkeypatch)
    assert _post({"manual": True}).json()["status"] == "started"
    assert calls == [True]


def test_auto_install_stops_after_three_attempts(monkeypatch):
    """[핵심] 도구가 끝내 안 잡혀도 4번째부터는 자동 실행 안 함.

    옛 코드는 쿨다운(프로세스 메모리)만 있어 앱을 껐다 켤 때마다 다시 돌았다.
    """
    calls = _prepare(monkeypatch)
    for _ in range(setup_api._AUTO_INSTALL_MAX_ATTEMPTS):
        monkeypatch.setattr(setup_api, "_AUTO_INSTALL_LAST_STARTED", 0.0)
        assert _post().json()["status"] == "started"
    assert len(calls) == setup_api._AUTO_INSTALL_MAX_ATTEMPTS

    monkeypatch.setattr(setup_api, "_AUTO_INSTALL_LAST_STARTED", 0.0)
    assert _post().json()["status"] == "exhausted"
    assert len(calls) == setup_api._AUTO_INSTALL_MAX_ATTEMPTS      # 추가 실행 없음


def test_exhausted_auto_does_not_block_manual(tmp_path, monkeypatch):
    """상한은 자동 경로 전용 — 사용자가 직접 누르면 언제든 다시 설치된다."""
    calls = _prepare(monkeypatch)
    (tmp_path / "setup_auto_install.json").write_text(
        json.dumps({"attempts": 99}), encoding="utf-8")

    assert _post().json()["status"] == "exhausted"
    monkeypatch.setattr(setup_api, "_AUTO_INSTALL_LAST_STARTED", 0.0)
    assert _post({"manual": True}).json()["status"] == "started"
    assert calls == [True]


def test_all_installed_never_launches(monkeypatch):
    """다 깔려 있으면 자동이든 수동이든 설치기를 아예 안 띄운다."""
    calls = _prepare(monkeypatch, installed=_CORE)
    assert _post().json()["status"] == "idle"
    assert _post({"manual": True}).json()["status"] == "idle"
    assert calls == []


def test_attempt_counter_survives_restart(tmp_path, monkeypatch):
    """시도 횟수는 디스크에 남아야 한다 — 메모리 카운터면 재시작으로 리셋된다."""
    _prepare(monkeypatch)
    _post()
    assert setup_api._read_auto_install_attempts() == 1
    saved = json.loads((tmp_path / "setup_auto_install.json").read_text(encoding="utf-8"))
    assert saved["last_targets"] == list(_CORE)


def test_corrupt_state_file_is_not_fatal(tmp_path, monkeypatch):
    """마커가 깨져도 앱이 죽으면 안 된다 — 0회로 보고 예전과 같이 동작."""
    calls = _prepare(monkeypatch)
    (tmp_path / "setup_auto_install.json").write_text("{ broken", encoding="utf-8")
    assert _post().json()["status"] == "started"
    assert calls == [False]
