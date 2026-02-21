import os
import sys
import json
import string
from pathlib import Path
from datetime import datetime
from typing import Iterator

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Log, DirectoryTree, Label, Input, Select
from textual.containers import Grid, Vertical, Horizontal
from textual.widget import Widget
from textual.events import MouseDown, MouseMove, MouseUp

if getattr(sys, 'frozen', False):
    # PyInstaller exe: data 폴더는 exe와 같은 위치
    AI_MONITOR_DIR = Path(sys.executable).resolve().parent
    DATA_DIR = AI_MONITOR_DIR / "data"
else:
    AI_MONITOR_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = AI_MONITOR_DIR / "data"
SESSIONS_FILE = DATA_DIR / "sessions.jsonl"
CONFIG_FILE = AI_MONITOR_DIR / "config.json"

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"projects": {"vibe-coding": "D:/vibe-coding"}}

def get_drives():
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives

class Resizer(Widget):
    """사이드바 너비 조절용 마우스 드래그 핸들"""
    DEFAULT_CSS = """
    Resizer {
        width: 1;
        height: 100%;
        background: $surface;
    }
    Resizer:hover {
        background: $accent;
    }
    """
    def on_mouse_down(self, event: MouseDown) -> None:
        self.capture_mouse()
        self.dragging = True
        self.start_x = event.screen_x
        self.sidebar = self.app.query_one("#sidebar")
        self.start_width = self.app.sidebar_width

    def on_mouse_move(self, event: MouseMove) -> None:
        if getattr(self, "dragging", False):
            delta = event.screen_x - self.start_x
            new_width = max(15, min(self.start_width + delta, self.app.console.size.width - 20))
            self.app.sidebar_width = new_width
            self.sidebar.styles.width = new_width

    def on_mouse_up(self, event: MouseUp) -> None:
        self.dragging = False
        self.release_mouse()

class SessionViewer(App):
    """AI 세션 모니터링 뷰어 (Textual 기반) - 프로덕션 자동 버전"""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main_container {
        layout: horizontal;
        height: 1fr;
    }
    #sidebar {
        width: 30;
        height: 100%;
        border-right: solid $accent;
        transition: width 200ms in_out_cubic;
    }
    #sidebar.-hidden {
        width: 0;
        border-right: none;
    }
    #terminal_grid {
        height: 100%;
        width: 1fr;
    }

    /* 격자 레이아웃 (가로 배열로 세로로 길게) */
    #terminal_grid.layout-stack {
        layout: grid;
        grid-size: 2 2;
    }

    .panel {
        height: 100%;
        width: 100%;
        border: round $accent;
        padding: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "종료"),
        ("r", "refresh_data", "새로고침"),
        ("b", "toggle_sidebar", "탐색기 보기/숨기기"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        self.config_data = load_config()
        self.projects = self.config_data.get("projects", {"vibe-coding": "D:/vibe-coding"})

        with Horizontal(id="main_container"):
            # 좌측 사이드바
            with Vertical(id="sidebar"):
                yield Label(" 탐색 경로 선택", classes="panel-title")

                options = []
                for name, p in self.projects.items():
                    options.append((f">> {name} ({p})", p))
                for d in get_drives():
                    options.append((f">> 드라이브 {d}", d))

                default_path = options[0][1] if options else "C:\\"
                yield Select(options, id="path_select", value=default_path)
                yield DirectoryTree(path=default_path, id="project_tree")

            # 마우스 드래그 너비 조절 핸들
            yield Resizer()

            # 우측 4분할 격자 (수직 배열)
            with Grid(id="terminal_grid", classes="layout-stack"):
                self.terms = [
                    Log(classes="panel", id="term1"),
                    Log(classes="panel", id="term2"),
                    Log(classes="panel", id="term3"),
                    Log(classes="panel", id="term4")
                ]
                for i, term in enumerate(self.terms):
                    term.border_title = f"Terminal Slot {i+1}"
                    yield term

        yield Footer()

    def on_mount(self) -> None:
        self.last_file_size = 0
        self.sidebar_width = 30
        self.update_data()
        self.set_interval(1.5, self.update_data)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """선택창에서 드라이브/디렉토리 변경 처리"""
        if event.select.id == "path_select" and event.value:
            new_path = str(event.value)
            if os.path.exists(new_path) and os.path.isdir(new_path):
                tree = self.query_one("#project_tree", DirectoryTree)
                tree.path = new_path
                await tree.reload()
                self.notify(f"경로 이동: {new_path}")
            else:
                self.notify(f"유효하지 않은 경로입니다: {new_path}", severity="error")

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        if sidebar.has_class("-hidden"):
            sidebar.remove_class("-hidden")
        else:
            sidebar.add_class("-hidden")

    def action_refresh_data(self) -> None:
        self.last_file_size = 0
        self.update_data()

    def update_data(self) -> None:
        if not SESSIONS_FILE.exists():
            return

        current_size = SESSIONS_FILE.stat().st_size
        if current_size == self.last_file_size:
            return

        self.last_file_size = current_size

        for term in self.terms:
            term.clear()

        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()

                for line in lines[-100:]:
                    line = line.strip()
                    if not line: continue
                    record = json.loads(line)

                    tid = record.get("terminal_id", "Unknown")
                    status = record.get("status", "running")
                    agent = record.get("agent", "unknown")
                    proj = record.get("project", "?")
                    title = record.get("trigger", "작업 내용 없음")
                    commit = record.get("commit", "")

                    msg = f"[{status}] {agent} @ {proj}\n > {title}"
                    if commit:
                        msg += f"\n   Commit: {commit}"

                    if status == "running": icon = "[RUN]"
                    elif status == "success": icon = "[OK]"
                    else: icon = "[ERR]"

                    display_msg = f"{icon} {msg}\n"

                    slot_index = hash(tid) % len(self.terms)
                    self.terms[slot_index].write(display_msg)

        except Exception as e:
            self.terms[0].write(f"Error parse: {e}")

if __name__ == "__main__":
    app = SessionViewer()
    app.run()
