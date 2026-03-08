# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/bin/codex_wrapper.py
DESCRIPTION: Codex CLI용 고성능 래퍼. 
             - 시각적 메뉴(Dashbord) 제공
             - 타 AI 도구(Gemini, Claude) 연동/설치 기능 탑재
             - MCP 서버 연동 자동화

REVISION HISTORY:
- 2026-03-07 Gemini-1: 대폭 고도화 (메뉴 시스템, AI 도구 설치 기능 추가)
REVISION HISTORY:
- 2026-03-08 Claude: ITCP 자동 수신 로직 추가
  - _itcp_auto_receive(): 세션 시작 시 pg_messages에서 미읽음 메시지 자동 수신
  - Claude/Gemini는 UserPromptSubmit 훅으로 자동 수신하지만
    Codex는 훅 시스템이 없으므로 래퍼 진입 시점에 직접 호출합니다.
"""

import os
import sys
import argparse
import subprocess
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BIN_DIR         = Path(__file__).resolve().parent
AI_MONITOR_DIR  = BIN_DIR.parent
PROJECT_ROOT    = AI_MONITOR_DIR.parent
SCRIPTS_DIR     = PROJECT_ROOT / "scripts"

TERMINAL_AGENT  = SCRIPTS_DIR / "terminal_agent.py"
CLI_AGENT       = SCRIPTS_DIR / "cli_agent.py"
PYTHON_BIN      = AI_MONITOR_DIR / "venv" / "Scripts" / "python.exe"

console = Console()


# ── ITCP 자동 수신 ─────────────────────────────────────────────────────────────
def _itcp_auto_receive() -> None:
    """세션 시작 시 PostgreSQL pg_messages에서 Codex에게 온 미읽음 메시지를 자동 수신합니다.

    [설계 의도]
    Claude/Gemini는 UserPromptSubmit 훅(hive_hook.py, gemini_hook.py)이 매 프롬프트마다
    자동으로 itcp.receive()를 호출하지만, Codex는 훅 시스템이 없습니다.
    따라서 래퍼 진입 시점(main)에 이 함수를 호출하여 메시지 수신 공백을 보완합니다.

    [변경 이력] 2026-03-08 Claude: ITCP 도입으로 신규 추가
    """
    itcp_script = SCRIPTS_DIR / "itcp.py"
    if not itcp_script.exists():
        return

    try:
        no_window = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [str(PYTHON_BIN), str(itcp_script), "receive", "codex"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, cwd=str(PROJECT_ROOT),
            env={**os.environ, "PGCLIENTENCODING": "UTF8"},
            creationflags=no_window,
        )
        output = result.stdout.strip()
        if output and "미읽음 없음" not in output and "no unread" not in output.lower():
            # 메시지가 있을 때만 출력 (없으면 조용히 통과)
            console.print(Panel(
                output,
                title="[bold cyan]📨 하이브 메시지[/bold cyan]",
                border_style="cyan",
            ))
    except Exception:
        pass  # 수신 실패 시 조용히 통과 — 메인 기능에 영향 없음


# ── 로고 및 시각 효과 ──────────────────────────────────────────────────────────
def print_logo():
    logo_text = """
    [bold cyan]
     ██████╗ ██████╗ ██████╗ ███████╗██╗  ██╗
    ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗██╔╝
    ██║     ██║   ██║██║  ██║█████╗   ╚███╔╝ 
    ██║     ██║   ██║██║  ██║██╔══╝   ██╔██╗ 
    ╚██████╗╚██████╔╝██████╔╝███████╗██╔╝ ██╗
     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
    [/bold cyan]
    [bold white]Vibe Coding Ecosystem - AI Orchestrator CLI[/bold white]
    """
    console.print(logo_text)

# ── 메뉴 대시보드 ──────────────────────────────────────────────────────────────
def show_dashboard():
    print_logo()
    
    table = Table(title="Codex Control Panel", border_style="bright_blue")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    table.add_row("1. Chat (REPL)", "AI 에이전트와 대화형 터미널 세션을 시작합니다.")
    table.add_row("2. YOLO Mode", "자율적으로 과업을 완수하는 에이전트를 가동합니다.")
    table.add_row("3. Install to AI", "Gemini CLI나 Claude에 Codex 도구를 설치합니다.")
    table.add_row("4. Hive Mind View", "현재 프로젝트의 하이브 마인드 지식 베이스를 확인합니다.")
    table.add_row("q. Exit", "Codex CLI를 종료합니다.")

    console.print(table)
    
    choice = Prompt.ask("원하시는 작업을 선택하세요", choices=["1", "2", "3", "4", "q"], default="1")
    
    if choice == "1":
        run_agent("", yolo_mode=False)
    elif choice == "2":
        task = Prompt.ask("YOLO 모드로 수행할 과업을 입력하세요")
        run_agent(task, yolo_mode=True)
    elif choice == "3":
        install_to_ai()
    elif choice == "4":
        console.print("[yellow]Hive Mind View는 준비 중입니다...[/yellow]")
    elif choice == "q":
        console.print("[bold red]Codex를 종료합니다.[/bold red]")

# ── AI 도구(Gemini, Claude) 설치 로직 ──────────────────────────────────────────
# Codex를 각 AI 도구의 MCP 서버로 실제 등록합니다.
# Gemini: ~/.gemini/settings.json의 mcpServers 섹션에 추가
# Claude Desktop: %APPDATA%/Claude/claude_desktop_config.json의 mcpServers 섹션에 추가
def install_to_ai():
    console.print(Panel("[bold green]Codex AI 도구 설치 마법사[/bold green]"))

    target = Prompt.ask("설치할 대상을 선택하세요", choices=["gemini", "claude", "all"], default="all")

    # MCP 서버로 등록할 Codex 서버의 실행 정보
    # terminal_agent.py를 MCP stdio 서버로 래핑하여 등록합니다.
    python_bin  = str(PYTHON_BIN).replace("\\", "/")
    mcp_script  = str(BIN_DIR / "mcp_server.py").replace("\\", "/")

    mcp_entry = {
        "command": python_bin,
        "args": [mcp_script],
        "env": {
            "PROJECT_ROOT": str(PROJECT_ROOT).replace("\\", "/")
        }
    }

    if target in ["gemini", "all"]:
        _install_to_gemini(mcp_entry)

    if target in ["claude", "all"]:
        _install_to_claude(mcp_entry)


def _install_to_gemini(mcp_entry: dict):
    """Gemini CLI ~/.gemini/settings.json에 vibe-coding MCP 서버를 등록합니다."""
    gemini_settings = Path.home() / ".gemini" / "settings.json"

    console.print("[cyan]Gemini CLI 연동을 시도합니다...[/cyan]")

    if not gemini_settings.exists():
        console.print(f"[yellow]⚠ Gemini CLI 설정 파일을 찾을 수 없습니다: {gemini_settings}[/yellow]")
        console.print("[yellow]  Gemini CLI가 설치되어 있지 않을 수 있습니다.[/yellow]")
        return

    try:
        # 기존 설정 읽기
        with open(gemini_settings, "r", encoding="utf-8") as f:
            settings = json.load(f)

        # mcpServers 섹션이 없으면 생성
        if "mcpServers" not in settings:
            settings["mcpServers"] = {}

        # vibe-coding 항목 추가 또는 업데이트
        settings["mcpServers"]["vibe-coding"] = mcp_entry

        # 파일에 다시 씁니다 (들여쓰기 2칸, UTF-8)
        with open(gemini_settings, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        console.print(f"[green]✔ Gemini CLI에 vibe-coding MCP 서버가 등록되었습니다.[/green]")
        console.print(f"  [dim]파일: {gemini_settings}[/dim]")

    except Exception as e:
        console.print(f"[bold red]✗ Gemini CLI 설치 실패:[/bold red] {e}")


def _install_to_claude(mcp_entry: dict):
    """Claude Desktop %APPDATA%/Claude/claude_desktop_config.json에 vibe-coding MCP 서버를 등록합니다."""
    appdata = os.environ.get("APPDATA", "")
    claude_config = Path(appdata) / "Claude" / "claude_desktop_config.json"

    console.print("[cyan]Claude Desktop 연동을 시도합니다...[/cyan]")

    if not claude_config.parent.exists():
        console.print(f"[yellow]⚠ Claude Desktop 설정 폴더를 찾을 수 없습니다: {claude_config.parent}[/yellow]")
        console.print("[yellow]  Claude Desktop이 설치되어 있지 않을 수 있습니다.[/yellow]")
        return

    try:
        # 기존 설정 읽기 (없으면 빈 객체로 시작)
        if claude_config.exists():
            with open(claude_config, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

        # mcpServers 섹션이 없으면 생성
        if "mcpServers" not in config:
            config["mcpServers"] = {}

        # vibe-coding 항목 추가 또는 업데이트
        config["mcpServers"]["vibe-coding"] = mcp_entry

        # 파일에 다시 씁니다
        with open(claude_config, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        console.print(f"[green]✔ Claude Desktop에 vibe-coding MCP 서버가 등록되었습니다.[/green]")
        console.print(f"  [dim]파일: {claude_config}[/dim]")
        console.print(f"  [dim]Claude Desktop을 재시작해야 적용됩니다.[/dim]")

    except Exception as e:
        console.print(f"[bold red]✗ Claude Desktop 설치 실패:[/bold red] {e}")

# ── 에이전트 실행 ──────────────────────────────────────────────────────────────
def run_agent(task, yolo_mode=False, cli="auto"):
    env = os.environ.copy()
    env["TERMINAL_ID"] = "CODEX"
    
    if not task:
        # 대화형 모드
        cmd = [str(PYTHON_BIN), str(TERMINAL_AGENT)]
    elif yolo_mode:
        cmd = [str(PYTHON_BIN), str(CLI_AGENT), task, cli]
    else:
        cmd = [str(PYTHON_BIN), str(TERMINAL_AGENT), task, cli]

    try:
        subprocess.run(cmd, env=env, check=False)
    except Exception as e:
        console.print(f"[bold red]ERROR:[/bold red] Codex 실행 실패: {e}")

# ── 메인 진입점 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Codex CLI - Vibe Coding AI Agent")
    parser.add_argument("task", nargs="?", help="에이전트에게 내릴 지시 내용")
    parser.add_argument("--yolo", "-y", action="store_true", help="자율 모드(YOLO)로 실행합니다.")
    parser.add_argument("--cli", default="auto", choices=["auto", "claude", "gemini"], help="사용할 기반 모델")
    parser.add_argument("--install", action="store_true", help="AI 도구(Gemini, Claude)에 Codex를 설치합니다.")

    args, unknown = parser.parse_known_args()

    # 세션 시작 시 ITCP 미읽음 메시지 자동 수신
    # Claude/Gemini는 훅으로 자동 처리되지만 Codex는 여기서 직접 호출
    _itcp_auto_receive()

    if args.install:
        install_to_ai()
        return

    if not args.task:
        # 지시 사항이 없으면 대시보드 출력
        show_dashboard()
        return

    run_agent(args.task, yolo_mode=args.yolo, cli=args.cli)

if __name__ == "__main__":
    main()
