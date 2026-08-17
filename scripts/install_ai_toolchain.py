"""
FILE: scripts/install_ai_toolchain.py
DESCRIPTION: Vibe Coding first-run Node.js and AI CLI automatic installer chain.

REVISION HISTORY:
- 2026-07-29 Codex: Install official Antigravity CLI (`agy`) instead of Gemini CLI.
- 2026-07-29 Codex: Prefer installer-bundled Node/npm for deterministic first installation.
- 2026-07-29 Codex: Verify Node/npm after installation before starting dependent CLIs.
- 2026-07-29 Codex: Install missing Node.js, Claude, Codex, and Gemini sequentially.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# [🔴 규칙 10 — 창 없이 부른다] 맨손 subprocess 로 npm 을 부르면 그 손자 node.exe 가
#   새 콘솔을 받는다(CREATE_NO_WINDOW 는 상속되지 않는다). 실행기는 한 곳뿐이다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _install_common import run as _run  # noqa: E402



SCRIPT_DIR = Path(__file__).resolve().parent
AI_PACKAGES = (
    ("Claude Code", ("claude",), "@anthropic-ai/claude-code"),
    ("Codex", ("codex",), "@openai/codex"),
)


def _command_exists(names: tuple[str, ...]) -> bool:
    return any(shutil.which(name) or shutil.which(f"{name}.cmd") for name in names)


def _load_env_path():
    """공용 PATH 재병합 모듈(infra/env_path)을 불러온다. 못 찾으면 None.

    [WHY 여기서 sys.path를 건드리나] 이 스크립트는 세 가지 방식으로 실행된다 —
      ①개발: `python scripts/install_ai_toolchain.py` ②frozen: boot._run_daemon_script가
      `.ai_monitor`를 미리 주입 ③설치 EXE가 띄운 새 콘솔. ①에서만 경로 주입이 없으므로
      리포 루트 기준으로 한 번 보강한다.
    [WHY 실패를 허용하나] 이 스크립트는 '아무것도 없는 PC'의 복구 경로다. 부수적인 PATH
      최적화 때문에 설치 자체가 죽으면 안 된다. 부모(tools_api)가 spawn 직전에 이미
      force refresh 하므로, 여기서 실패해도 상속받은 PATH는 최신이다.
    """
    ai_monitor = SCRIPT_DIR.parent / ".ai_monitor"
    if ai_monitor.is_dir() and str(ai_monitor) not in sys.path:
        sys.path.insert(0, str(ai_monitor))
    try:
        from infra import env_path
        return env_path
    except Exception:
        return None


_ENV_PATH = _load_env_path()


def _refresh_windows_path() -> None:
    """설치 단계 사이마다 PATH를 다시 읽는다 — 직전 단계가 추가한 bin을 다음 단계가 보게.

    [불변식] Node 설치 → npm 탐색, npm -g 설치 → claude/codex 탐색 사이에 반드시 호출.
      빼먹으면 방금 설치한 도구를 '미설치'로 오판해 무한 재설치한다.
    """
    if _ENV_PATH is not None:
        _ENV_PATH.refresh_path(force=True)


def _find_npm() -> str | None:
    _refresh_windows_path()
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        return npm
    candidates = [
        SCRIPT_DIR.parent / "nodejs" / "npm.cmd",
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
    result = _run([sys.executable, str(node_installer)], timeout=900)
    if result.returncode != 0:
        print("[실패] Node.js 자동 설치가 완료되지 않았습니다.")
        return None
    npm = _find_npm()
    if npm:
        print(f"[ready] Node.js/npm: {npm}")
    else:
        print("[failed] npm was not found after the Node.js installer finished.")
    return npm


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
        result = _run([npm, "install", "-g", package], timeout=900)
        if result.returncode != 0:
            failures.append(display_name)
        else:
            print(f"[완료] {display_name}")

    _refresh_windows_path()
    if _command_exists(("agy",)):
        print("[skip] Antigravity CLI is already installed.")
    else:
        print("[auto install] Antigravity CLI (agy)")
        result = _run(
            [sys.executable, str(SCRIPT_DIR / "install_antigravity.py")],
            timeout=900,
        )
        if result.returncode != 0:
            failures.append("Antigravity CLI")

    # 옵시디언 — 지식 창고(wiki/)를 사람이 읽는 창.
    # [WHY npm 이 아니라 별도 스크립트인가] GUI 앱이라 winget/인스톨러 경로가 필요하다.
    # [WHY 실패해도 전체를 중단하지 않나] 위키는 파일과 DB 만으로 완전히 동작한다 —
    #   옵시디언은 3층 구조의 ③(선택적 뷰어)이라 없다고 기능이 죽지 않는다.
    #   여기서 SystemExit 를 내면 AI CLI 는 다 깔렸는데 설치팩 전체가 실패로 보인다.
    obsidian_script = SCRIPT_DIR / "install_system_tool.py"
    if obsidian_script.exists():
        print("[자동 설치] Obsidian (지식 창고 뷰어)")
        try:
            result = _run(
                [sys.executable, str(obsidian_script), "--tool", "obsidian"], timeout=900,
            )
            if result.returncode != 0:
                print("[알림] Obsidian 자동 설치 실패 — 위키는 옵시디언 없이도 동작합니다.")
        except Exception as exc:
            print(f"[알림] Obsidian 설치 건너뜀: {exc}")

    if failures:
        print(f"[일부 실패] {', '.join(failures)}")
        raise SystemExit(1)
    print("[전체 완료] 필요한 AI CLI가 모두 준비되었습니다.")


if __name__ == "__main__":
    main()
