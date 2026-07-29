"""
FILE: tests/test_setup_doctor.py
DESCRIPTION: Setup Doctor 회귀 테스트 — AI CLI 감지 + .claude/settings.json 훅 자동 수리.

REVISION HISTORY:
- 2026-07-30 Claude: check_hooks 회귀 테스트 추가 — 그룹 스키마 오인식으로 flat 훅이
                     매 진단마다 중복 추가되던 사고 재발 방지.
- 2026-07-29 Codex: Require official Antigravity `agy` detection.
- 2026-07-28 Codex: Cover partially and fully installed AI CLI states.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from setup_doctor import _REQUIRED_HOOKS, check_cli_agents, check_hooks


def test_partial_cli_installation_requires_action():
    def fake_which(command: str):
        return "C:/tools/claude.cmd" if command in {"claude", "claude.cmd"} else None

    with patch("setup_doctor.shutil.which", side_effect=fake_which):
        result = check_cli_agents()

    assert result["status"] == "missing"
    assert result["action"] == "install_cli"
    assert "codex" in result["message"]
    assert "antigravity" in result["message"]


def test_all_cli_installations_are_ready():
    with patch("setup_doctor.shutil.which", return_value="C:/tools/agent.cmd"):
        result = check_cli_agents()

    assert result["status"] == "ok"
    assert "action" not in result


def test_agy_command_satisfies_antigravity_detection():
    available = {"claude", "codex", "agy"}

    with patch(
        "setup_doctor.shutil.which",
        side_effect=lambda command: f"C:/tools/{command}.cmd" if command in available else None,
    ):
        result = check_cli_agents()

    assert result["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  check_hooks — settings.json 훅 자동 수리
#
#  [과거사고] 2026-07-30: check_hooks가 이벤트 배열의 원소를 flat {type,command}로 가정해
#  그룹 객체에 `.get("command")`를 읽어 항상 ''를 얻었다 → 이미 등록된 훅을 "누락"으로
#  오판하고 flat 항목을 append → CLI가 "hooks: Expected array, but received undefined"로
#  거부. 진단 API는 SetupBanner가 부팅마다 호출하므로 손으로 지워도 재오염됐다.
#  아래 테스트가 그 재발을 막는다.
# ═══════════════════════════════════════════════════════════════════════

# 정상(그룹) 스키마 — 실제 vibe-coding 설정 형태를 축약
_VALID_HOOKS = {
    "UserPromptSubmit": [
        {
            "matcher": "",
            "hooks": [
                {"type": "command", "command": "python D:/p/scripts/hive_hook.py"},
                {"type": "command", "command": "python D:/p/scripts/hook_bridge.py"},
            ],
        }
    ],
    "Stop": [
        {"matcher": "", "hooks": [{"type": "command", "command": "python D:/p/scripts/hive_hook.py"}]},
        {"matcher": "", "hooks": [{"type": "command", "command": 'python "D:/p/scripts/claude_hook.py" stop'}]},
    ],
}


def _write_settings(root: Path, hooks: dict) -> Path:
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": hooks}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _all_groups_valid(hooks: dict) -> bool:
    """모든 이벤트 항목이 Claude Code 정식 그룹 스키마인지 — 이게 깨지면 CLI가 설정을 거부."""
    return all(
        isinstance(group, dict)
        and isinstance(group.get("matcher"), str)
        and isinstance(group.get("hooks"), list)
        for groups in hooks.values()
        for group in groups
    )


def test_valid_group_schema_is_left_untouched(tmp_path):
    """핵심 회귀: 이미 정상 등록된 훅을 중복 추가하거나 파일을 건드리지 않아야 한다."""
    settings = _write_settings(tmp_path, _VALID_HOOKS)
    before = settings.read_text(encoding="utf-8")

    with patch("setup_doctor._PROJECT_ROOT", tmp_path):
        result = check_hooks()

    assert result["status"] == "ok"
    assert settings.read_text(encoding="utf-8") == before


def test_flat_legacy_entries_are_purged(tmp_path):
    """과거 오염분(hooks 키 없는 flat 항목)을 자동 청산하고 그룹 스키마만 남긴다."""
    corrupted = json.loads(json.dumps(_VALID_HOOKS))
    corrupted["UserPromptSubmit"].append(
        {"type": "command", "command": 'python "D:/p/scripts/hook_bridge.py" "$PROMPT"'}
    )
    corrupted["Stop"].append({"type": "command", "command": 'python "D:/p/scripts/claude_hook.py" stop'})
    settings = _write_settings(tmp_path, corrupted)

    with patch("setup_doctor._PROJECT_ROOT", tmp_path):
        result = check_hooks()

    saved = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert result["auto_fixed"] is True
    assert _all_groups_valid(saved)
    # 같은 스크립트가 이미 그룹으로 있으므로 flat 잔재는 승격 없이 폐기 — 중복 실행 방지
    assert len(saved["UserPromptSubmit"]) == 1
    assert len(saved["Stop"]) == 2


def test_missing_event_is_created_as_group(tmp_path):
    """이벤트가 아예 없을 때도 flat 리스트가 아니라 그룹으로 기록해야 한다."""
    settings = _write_settings(tmp_path, {})

    with patch("setup_doctor._PROJECT_ROOT", tmp_path):
        result = check_hooks()

    saved = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert result["auto_fixed"] is True
    assert _all_groups_valid(saved)
    assert set(saved) == {"UserPromptSubmit", "Stop"}


def test_required_commands_carry_no_shell_placeholder():
    """`$PROMPT`는 Claude Code가 치환하지 않고 hook_bridge는 argv를 읽지 않는다 — 재도입 금지."""
    for commands in _REQUIRED_HOOKS.values():
        for cmd_def in commands:
            assert "$PROMPT" not in cmd_def["command"]
