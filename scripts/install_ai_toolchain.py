"""
FILE: scripts/install_ai_toolchain.py
DESCRIPTION: Vibe Coding first-run Node.js and AI CLI automatic installer chain.

REVISION HISTORY:
- 2026-07-29 Codex: Install missing Node.js, Claude, Codex, and Gemini sequentially.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
AI_PACKAGES = (
    ("Claude Code", ("claude",), "@anthropic-ai/claude-code"),
    ("Codex", ("codex",), "@openai/codex"),
    ("Gemini / Antigravity", ("gemini", "antigravity"), "@google/gemini-cli"),
)


def _command_exists(names: tuple[str, ...]) -> bool:
    return any(shutil.which(name) or shutil.which(f"{name}.cmd") for name in names)


def _refresh_windows_path() -> None:
    """Refresh PATH after winget/MSI so the same installer process can continue."""
    if os.name != "nt":
        return
    paths = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    try:
        import winreg

        registry_paths = (
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment"),
        )
        for hive, key_name in registry_paths:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, "Path")
                    paths.extend(os.path.expandvars(value).split(os.pathsep))
            except OSError:
                continue
    except ImportError:
        pass

    paths.extend([
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs"),
        str(Path(os.environ.get("APPDATA", "")) / "npm"),
    ])
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(path for path in paths if path))


def _find_npm() -> str | None:
    _refresh_windows_path()
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        return npm
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd",
        Path(os.environ.get("APPDATA", "")) / "npm" / "npm.cmd",
    ]
    return str(next((path for path in candidates if path.exists()), "")) or None


def _install_node_if_missing() -> str | None:
    npm = _find_npm()
    if npm:
        print(f"[건너뜀] Node.js/npm 설치됨: {npm}")
        return npm

    node_installer = SCRIPT_DIR / "install_nodejs.py"
    print("[자동 설치] Node.js/npm이 없어 먼저 설치합니다.")
    result = subprocess.run([sys.executable, str(node_installer)], timeout=900)
    if result.returncode != 0:
        print("[실패] Node.js 자동 설치가 완료되지 않았습니다.")
        return None
    return _find_npm()


def main() -> None:
    print("=" * 62)
    print("  Vibe Coding 필수 AI 도구 자동 설치")
    print("  Node.js → Claude Code → Codex → Gemini")
    print("=" * 62)

    npm = _install_node_if_missing()
    if not npm:
        print("[중단] npm을 찾지 못했습니다. Node.js 설치를 완료한 뒤 다시 시도해 주세요.")
        raise SystemExit(1)

    failures = []
    for display_name, commands, package in AI_PACKAGES:
        _refresh_windows_path()
        if _command_exists(commands):
            print(f"[건너뜀] {display_name}이 이미 설치되어 있습니다.")
            continue
        print(f"[자동 설치] {display_name}: npm install -g {package}")
        result = subprocess.run([npm, "install", "-g", package], timeout=900)
        if result.returncode != 0:
            failures.append(display_name)
        else:
            print(f"[완료] {display_name}")

    if failures:
        print(f"[일부 실패] {', '.join(failures)}")
        raise SystemExit(1)
    print("[전체 완료] 필요한 AI CLI가 모두 준비되었습니다.")


if __name__ == "__main__":
    main()
