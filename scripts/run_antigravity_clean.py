# -*- coding: utf-8 -*-
"""
FILE: scripts/run_antigravity_clean.py
DESCRIPTION: Antigravity CLI 직접 실행 래퍼.
             프로젝트 경로에서 Antigravity CLI를 실행할 때 stderr 노이즈를 로그 파일로 분리합니다.

REVISION HISTORY:
- 2026-03-22 Codex: 최초 작성
  - Antigravity CLI 내부 MCP/훅/텔레메트리 stderr를 별도 로그 파일에 기록
  - 프로젝트 런처/대시보드가 공통으로 사용할 수 있는 직접 실행 진입점 제공
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from antigravity_output_filter import AntigravityCliNoiseFilter


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / ".ai_monitor" / "data"
STDERR_LOG = DATA_DIR / "gemini-cli.stderr.log"


def _find_antigravity() -> str | None:
    """PATH 또는 npm 기본 경로에서 Antigravity CLI 실행 파일을 찾습니다."""
    found = shutil.which("antigravity") or shutil.which("antigravity.cmd")
    if found:
        return found

    if os.name == "nt":
        npm_dir = Path(os.environ.get("APPDATA", "")) / "npm"
        for ext in (".cmd", ".ps1", ""):
            candidate = npm_dir / f"antigravity{ext}"
            if candidate.exists():
                return str(candidate)

    return None


def _tail_text(text: str, max_lines: int = 12) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _extract_cwd(args: list[str]) -> tuple[Path, list[str]]:
    """선택적 --cwd 인자를 분리하고 나머지 Antigravity 인자를 반환합니다."""
    if len(args) >= 2 and args[0] == "--cwd":
        return Path(args[1]).resolve(), args[2:]
    return ROOT, args


def _use_stdout_filter(args: list[str]) -> bool:
    """비대화형 -p 실행일 때만 stdout 필터를 켭니다."""
    return "-p" in args or "--prompt" in args


def main() -> int:
    antigravity_bin = _find_antigravity()
    if not antigravity_bin:
        print("[antigravity-launch] Antigravity CLI를 찾지 못했습니다.", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env.pop("CLAUDE_CODE_SSE_PORT", None)
    env.setdefault("PYTHONUTF8", "1")
    # instructor 패키지가 deprecated google.generativeai를 import할 때 FutureWarning 억제
    env.setdefault("PYTHONWARNINGS", "ignore::FutureWarning")

    run_cwd, antigravity_args = _extract_cwd(sys.argv[1:])
    filter_stdout = _use_stdout_filter(antigravity_args)
    if os.name == "nt":
        cmd = ["cmd.exe", "/d", "/c", antigravity_bin, *antigravity_args]
        use_shell = False
    else:
        cmd = [antigravity_bin, *antigravity_args]
        use_shell = False

    with STDERR_LOG.open("a+", encoding="utf-8", errors="replace") as stderr_log:
        stderr_log.seek(0, os.SEEK_END)
        stderr_start = stderr_log.tell()

        proc = subprocess.Popen(
            cmd,
            cwd=str(run_cwd),
            env=env,
            shell=use_shell,
            stdin=None,
            stdout=subprocess.PIPE if filter_stdout else None,
            stderr=stderr_log,
        )
        if filter_stdout and proc.stdout is not None:
            noise_filter = AntigravityCliNoiseFilter()
            for raw_line in iter(proc.stdout.readline, b""):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                line = noise_filter.filter_line(line)
                if line is None:
                    continue
                if line:
                    print(line)
        rc = proc.wait()
        stderr_log.flush()

        if rc != 0:
            stderr_log.seek(stderr_start)
            captured = stderr_log.read()
            print(f"[gemini-launch] Gemini CLI 종료 코드: {rc}", file=sys.stderr)
            print(f"[antigravity-launch] stderr 로그: {STDERR_LOG}", file=sys.stderr)
            tail = _tail_text(captured)
            if tail:
                print("[antigravity-launch] 최근 stderr:", file=sys.stderr)
                print(tail, file=sys.stderr)

        return rc


if __name__ == "__main__":
    raise SystemExit(main())
