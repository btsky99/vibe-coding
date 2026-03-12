# ------------------------------------------------------------------------
# FILE: kanban_board.py
# DESCRIPTION: Native orchestration wallboard for PySide6.
#              In development it reads from .ai_monitor/data in the repo.
#              In frozen builds it falls back to the installed AppData data dir.
# ------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _resolve_base_dir()
PROJECT_ROOT = BASE_DIR.parent if BASE_DIR.name == ".ai_monitor" else BASE_DIR


def _resolve_data_dir() -> Path:
    dev_data = PROJECT_ROOT / ".ai_monitor" / "data"
    if dev_data.exists():
        return dev_data
    if getattr(sys, "frozen", False) and os.name == "nt":
        appdata = Path(os.getenv("APPDATA", ""))
        installed_data = appdata / "VibeCoding"
        if installed_data.exists():
            return installed_data
    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()
ICON_PATH = PROJECT_ROOT / "assets" / "icon.ico"
if not ICON_PATH.exists():
    ICON_PATH = PROJECT_ROOT / ".ai_monitor" / "bin" / "app_icon.ico"

BG = "#15171a"
PANEL = "#101214"
CARD = "#181c20"
BORDER = "#2a2f36"
TEXT = "#e5e7eb"
MUTED = "#8b93a1"
SUBTLE = "#4b5563"
GREEN = "#22c55e"
BLUE = "#38bdf8"
AMBER = "#f59e0b"
RED = "#ef4444"


def read_jsonl(path: Path, limit: int = 500) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rows: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def relative_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", ""))
    except Exception:
        return ""
    diff = datetime.now() - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{max(1, seconds)}초 전"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    return f"{seconds // 86400}일 전"


def format_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", ""))
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return str(iso)


def cli_badge(cli: str) -> tuple[str, str]:
    value = (cli or "").lower()
    if value == "gemini":
        return "Gemini", "color:#93c5fd;background:#1d4ed822;"
    if value == "claude":
        return "Claude", "color:#86efac;background:#16653422;"
    return (cli or "Agent"), "color:#d1d5db;background:#37415144;"


class SectionFrame(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(
            f"background:{PANEL};border-bottom:1px solid {BORDER};border-top-left-radius:14px;border-top-right-radius:14px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title_label.setStyleSheet(f"color:{TEXT};border:none;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        if subtitle:
          sub_label = QLabel(subtitle)
          sub_label.setFont(QFont("Consolas", 8))
          sub_label.setStyleSheet(f"color:{MUTED};border:none;")
          header_layout.addWidget(sub_label)

        layout.addWidget(header)

        body = QWidget()
        body.setStyleSheet("border:none;background:transparent;")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        self.body_layout.setSpacing(10)
        layout.addWidget(body)


class RunCard(QFrame):
    def __init__(self, terminal_id: str, payload: dict, parent=None):
        super().__init__(parent)
        status = payload.get("status", "idle")
        border = AMBER if status == "running" else GREEN if status == "done" else RED if status == "error" else BORDER
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {CARD};
                border: 1px solid {border}55;
                border-radius: 12px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        slot = QLabel(terminal_id)
        slot.setFont(QFont("Consolas", 10, QFont.Bold))
        slot.setStyleSheet("color:#f8fafc;border:none;")
        top.addWidget(slot)

        badge_text, badge_style = cli_badge(payload.get("cli", ""))
        badge = QLabel(badge_text)
        badge.setFont(QFont("Consolas", 8, QFont.Bold))
        badge.setStyleSheet(f"border:none;border-radius:6px;padding:2px 6px;{badge_style}")
        top.addWidget(badge)
        top.addStretch()

        stamp = QLabel(relative_time(payload.get("ts")))
        stamp.setFont(QFont("Consolas", 8))
        stamp.setStyleSheet(f"color:{MUTED};border:none;")
        top.addWidget(stamp)
        layout.addLayout(top)

        task = QLabel(payload.get("task") or "작업 설명 없음")
        task.setWordWrap(True)
        task.setFont(QFont("Segoe UI", 9, QFont.Medium))
        task.setStyleSheet(f"color:{TEXT};border:none;")
        layout.addWidget(task)

        last_line = payload.get("last_line") or ""
        if last_line:
            line_label = QLabel(last_line[:180])
            line_label.setWordWrap(True)
            line_label.setFont(QFont("Consolas", 8))
            line_label.setStyleSheet(f"color:{MUTED};background:#0b0d10;border:none;padding:8px;border-radius:8px;")
            layout.addWidget(line_label)

        footer = QLabel(f"상태: {status}")
        footer.setFont(QFont("Segoe UI", 8, QFont.Bold))
        footer.setStyleSheet(
            f"color:{AMBER if status == 'running' else GREEN if status == 'done' else RED if status == 'error' else MUTED};border:none;"
        )
        layout.addWidget(footer)


class SessionCard(QFrame):
    def __init__(self, session: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {CARD};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        terminal_id = session.get("terminal_id")
        slot = QLabel(f"T{terminal_id}" if terminal_id else "공용")
        slot.setFont(QFont("Consolas", 9, QFont.Bold))
        slot.setStyleSheet("color:#f8fafc;border:none;")
        top.addWidget(slot)
        top.addStretch()

        time_label = QLabel(format_time(session.get("completed_at")))
        time_label.setFont(QFont("Consolas", 8))
        time_label.setStyleSheet(f"color:{MUTED};border:none;")
        top.addWidget(time_label)
        layout.addLayout(top)

        request = QLabel(session.get("request") or "요청 없음")
        request.setWordWrap(True)
        request.setFont(QFont("Segoe UI", 9, QFont.Medium))
        request.setStyleSheet(f"color:{TEXT};border:none;")
        layout.addWidget(request)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        results = session.get("results") or []
        for result in results[:4]:
            pill = QLabel((result.get("skill") or "").replace("vibe-", ""))
            pill.setFont(QFont("Consolas", 8, QFont.Bold))
            status = result.get("status", "")
            color = GREEN if status == "done" else RED if status == "error" else AMBER if status == "running" else MUTED
            pill.setStyleSheet(
                f"color:{color};background:{color}22;border:none;border-radius:6px;padding:3px 6px;"
            )
            chips.addWidget(pill)
        chips.addStretch()
        layout.addLayout(chips)


class KanbanBoardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vibe Coding - 오케스트레이션 보드")
        self.resize(1440, 860)
        self.setMinimumSize(980, 620)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        central = QWidget()
        central.setStyleSheet(f"background:{BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"background:#0d1014;border-bottom:1px solid {BORDER};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)

        title = QLabel("오케스트레이션 보드")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title.setStyleSheet(f"color:{TEXT};border:none;")
        header_layout.addWidget(title)

        hint = QLabel("메인 팝업보다 더 넓게, 최근 실행과 완료 기록만 보여줍니다")
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet(f"color:{MUTED};border:none;")
        header_layout.addWidget(hint)
        header_layout.addStretch()

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Consolas", 8))
        self.status_label.setStyleSheet(f"color:{MUTED};border:none;")
        header_layout.addWidget(self.status_label)

        refresh = QPushButton("새로고침")
        refresh.setFixedHeight(28)
        refresh.setStyleSheet(
            f"""
            QPushButton {{
                background:{BLUE}22;
                color:{BLUE};
                border:1px solid {BLUE}55;
                border-radius:8px;
                padding:0 12px;
            }}
            QPushButton:hover {{
                background:{BLUE}33;
            }}
            """
        )
        refresh.clicked.connect(self.refresh_data)
        header_layout.addWidget(refresh)
        root.addWidget(header)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(14)
        root.addWidget(content)

        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(10)
        content_layout.addLayout(self.summary_row)

        self.active_section = SectionFrame("활성 터미널", "agent_live.jsonl")
        self.active_scroll = QScrollArea()
        self.active_scroll.setWidgetResizable(True)
        self.active_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.active_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.active_body = QWidget()
        self.active_list = QVBoxLayout(self.active_body)
        self.active_list.setContentsMargins(0, 0, 0, 0)
        self.active_list.setSpacing(10)
        self.active_scroll.setWidget(self.active_body)
        self.active_section.body_layout.addWidget(self.active_scroll)

        self.completed_section = SectionFrame("최근 완료", "skill_results.jsonl")
        self.completed_scroll = QScrollArea()
        self.completed_scroll.setWidgetResizable(True)
        self.completed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.completed_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.completed_body = QWidget()
        self.completed_list = QVBoxLayout(self.completed_body)
        self.completed_list.setContentsMargins(0, 0, 0, 0)
        self.completed_list.setSpacing(10)
        self.completed_scroll.setWidget(self.completed_body)
        self.completed_section.body_layout.addWidget(self.completed_scroll)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(self.active_section, 3)
        columns.addWidget(self.completed_section, 2)
        content_layout.addLayout(columns, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(3000)
        self.refresh_data()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _summary_badge(self, label: str, value: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"""
            QFrame {{
                background:{PANEL};
                border:1px solid {color}44;
                border-radius:12px;
            }}
            """
        )
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        frame.setMinimumHeight(70)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        name = QLabel(label)
        name.setFont(QFont("Segoe UI", 8))
        name.setStyleSheet(f"color:{MUTED};border:none;")
        layout.addWidget(name)

        number = QLabel(value)
        number.setFont(QFont("Consolas", 15, QFont.Bold))
        number.setStyleSheet(f"color:{color};border:none;")
        layout.addWidget(number)
        return frame

    def _read_live_runs(self) -> dict[str, dict]:
        events = read_jsonl(DATA_DIR / "agent_live.jsonl", limit=1200)
        runs: dict[str, dict] = {}
        for event in events:
            run_id = str(event.get("run_id", "")).strip()
            if not run_id:
                continue

            existing = runs.get(run_id, {})
            merged = {
                "run_id": run_id,
                "terminal_id": event.get("terminal_id") or existing.get("terminal_id") or "T?",
                "task": event.get("task") or existing.get("task") or "",
                "cli": event.get("cli") or existing.get("cli") or "",
                "status": existing.get("status") or "idle",
                "ts": event.get("ts") or existing.get("ts") or "",
                "last_line": existing.get("last_line") or "",
            }

            event_type = event.get("type", "")
            if event_type == "started":
                merged["status"] = "running"
            elif event_type == "done":
                merged["status"] = event.get("status") or "done"
            elif event_type == "error":
                merged["status"] = "error"
            elif event_type == "output":
                line = str(event.get("line", "")).strip()
                if line:
                    merged["last_line"] = line

            runs[run_id] = merged

        by_terminal: dict[str, dict] = {}
        for payload in runs.values():
            terminal_id = str(payload.get("terminal_id") or "T?")
            if terminal_id == "T?":
                continue
            current = by_terminal.get(terminal_id)
            if current is None or str(payload.get("ts", "")) > str(current.get("ts", "")):
                by_terminal[terminal_id] = payload
        return by_terminal

    def _read_completed_sessions(self) -> list[dict]:
        rows = read_jsonl(DATA_DIR / "skill_results.jsonl", limit=120)
        rows.sort(key=lambda row: str(row.get("completed_at", "")), reverse=True)
        return rows[:10]

    def refresh_data(self) -> None:
        live_runs = self._read_live_runs()
        sessions = self._read_completed_sessions()

        while self.summary_row.count():
            item = self.summary_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        running_count = len([row for row in live_runs.values() if row.get("status") == "running"])
        visible_count = len(live_runs)
        self.summary_row.addWidget(self._summary_badge("활성 터미널", str(visible_count), BLUE))
        self.summary_row.addWidget(self._summary_badge("실행 중", str(running_count), AMBER))
        self.summary_row.addWidget(self._summary_badge("최근 완료", str(len(sessions)), GREEN))

        self._clear_layout(self.active_list)
        if live_runs:
            for terminal_id, payload in sorted(live_runs.items(), key=lambda item: item[0]):
                self.active_list.addWidget(RunCard(terminal_id, payload))
        else:
            empty = QLabel("표시할 활성 터미널이 없습니다.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(180)
            empty.setStyleSheet(f"color:{MUTED};border:none;")
            self.active_list.addWidget(empty)
        self.active_list.addStretch()

        self._clear_layout(self.completed_list)
        if sessions:
            for session in sessions:
                self.completed_list.addWidget(SessionCard(session))
        else:
            empty = QLabel("완료 기록이 없습니다.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(180)
            empty.setStyleSheet(f"color:{MUTED};border:none;")
            self.completed_list.addWidget(empty)
        self.completed_list.addStretch()

        now = datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(f"데이터: {DATA_DIR}   갱신: {now}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Vibe Coding Orchestration Board")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(CARD))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(PANEL))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(BLUE))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = KanbanBoardWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
