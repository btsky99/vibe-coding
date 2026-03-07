# ------------------------------------------------------------------------
# 📄 파일명: terminal_status.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 터미널 내부에 상주하며 에이전트의 현재 상태를 요약 표시합니다.
# ------------------------------------------------------------------------

import os
import json
import time
import sys
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# 데이터 디렉토리 설정
if os.name == 'nt':
    DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
else:
    DATA_DIR = Path.home() / ".vibe-coding"

console = Console()

def get_agent_status():
    live_file = DATA_DIR / "agent_live.jsonl"
    if not live_file.exists():
        return {}
    try:
        with open(live_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines: return {}
            return json.loads(lines[-1])
    except:
        return {}

def generate_status_line():
    status = get_agent_status()
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    
    # 에이전트별 요약
    summary = []
    active_count = 0
    for name, info in status.items():
        st = info.get("status", "idle")
        color = "green" if st == "active" else "bright_black"
        if st == "active": active_count += 1
        summary.append(f"[{color}]●[/] {name.upper()}")
    
    status_text = Text.from_markup(" | ".join(summary))
    
    # 현재 시각 및 활성 수
    time_str = time.strftime("%H:%M:%S")
    right_text = Text.from_markup(f"[cyan]{time_str}[/] | [bold yellow]Active: {active_count}[/]")
    
    table.add_row(status_text, right_text)
    return Panel(table, style="blue", title="[bold white]Vibe Hive Status[/]", title_align="left")

if __name__ == "__main__":
    # 터미널 창 크기 조절 (선택 사항)
    # os.system('mode con: cols=100 lines=30')
    
    with Live(generate_status_line(), refresh_per_second=2, vertical_overflow="visible") as live:
        try:
            while True:
                time.sleep(0.5)
                live.update(generate_status_line())
        except KeyboardInterrupt:
            pass
