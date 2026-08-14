"""
FILE: tests/test_windows_installer_toolchain.py
DESCRIPTION: Regression checks for prerequisite-first Windows installer packaging.

REVISION HISTORY:
- 2026-07-29 Codex: Require first-launch/login guidance after CLI installation.
- 2026-07-29 Codex: Require PTY agents to use resolved absolute Windows CLI paths.
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


def test_first_run_ui_reports_only_missing_core_tools():
    """서버는 네 도구를 항상 내려주고, UI는 **안 깔린 것만** 보여준다.

    [변경 2026-08-14] 예전엔 설치 완료 도구까지 나열해 배너가 영구히 남았다
    ("설치됨" / "설치 완료 · 최초 1회 실행/로그인 필요" 칩). 설치가 끝난 뒤에도
    계속 뜨는 게 문제였으므로 그 라벨들을 일부러 없앴다 — 되살리지 말 것.
    """
    api = (ROOT / ".ai_monitor" / "api" / "setup_api.py").read_text(encoding="utf-8")
    ui = (
        ROOT / ".ai_monitor" / "vibe-view" / "src" / "components" / "SetupBanner.tsx"
    ).read_text(encoding="utf-8")

    assert 'core_ids = ("nodejs", "claude", "codex", "antigravity")' in api
    assert "기본 설치팩" in ui
    assert "확인·설치 중" in ui
    assert "pendingTools.length > 0" in ui          # 미설치가 있을 때만 그린다
    assert "pendingTools.length === 0" in ui        # 없으면 배너 자체를 안 그린다
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


def test_pty_resolves_real_windows_cli_before_launch():
    pty_server = (
        ROOT / ".ai_monitor" / "pty-server" / "pty-server.js"
    ).read_text(encoding="utf-8")

    assert "function resolveWindowsCli(name)" in pty_server
    assert "function interactiveAgentCommand(" in pty_server
    assert "resolveWindowsCli('claude')" in pty_server
    assert "resolveWindowsCli('codex')" in pty_server
    assert "resolveWindowsCli('agy')" in pty_server
    # [2026-08-01 갱신] 예전엔 `agent === 'shell' && BASH_AVAILABLE`로 Git Bash를 골랐지만
    # 맥/리눅스 포팅(2026-07-22) 때 셸 선택이 플랫폼 분기로 재설계됐다(POSIX=로그인 셸,
    # Windows=cmd.exe). 테스트만 옛 문자열을 붙들고 있어 CI 릴리즈가 pytest 게이트에서
    # 막혔다(7/30 빌드 실패). 검사 대상을 살아있는 계약으로 옮긴다.
    assert "function posixLoginShell()" in pty_server
    assert "shell = 'cmd.exe'" in pty_server
    assert "ptyProcess.write(agentLine(interactiveAgentCommand" in pty_server
