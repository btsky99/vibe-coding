# ------------------------------------------------------------------------
# 파일명: kanban_board.py
# 설명: 오케스트레이션 칸반 보드 — PySide6 네이티브 GUI 창.
#       브라우저 없이 독립 실행되는 데스크톱 창으로,
#       다른 모니터로 자유롭게 이동할 수 있습니다.
#       task_logs.jsonl + skill_results.jsonl 을 3초마다 폴링하여
#       터미널별 활동 현황을 칸반 컬럼으로 시각화합니다.
#
# REVISION HISTORY:
# - 2026-03-07 Claude: 최초 구현 — PySide6 네이티브 칸반 보드 GUI
# ------------------------------------------------------------------------

import sys
import os
import json
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QFrame, QPushButton, QSizePolicy
)
from PySide6.QtGui import QColor, QPalette, QFont, QIcon
from PySide6.QtCore import Qt, QTimer, Signal, QObject

# ── 경로 설정 ──────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# 데이터 디렉토리 — server.py와 동일 로직
if os.name == 'nt':
    DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
else:
    DATA_DIR = Path.home() / ".vibe-coding"

# 개발 환경 폴백: APPDATA에 없으면 소스 옆 data/ 사용
if not DATA_DIR.exists():
    DATA_DIR = BASE_DIR / "data"

# 아이콘
ICON_PATH = BASE_DIR.parent / ".ai_monitor" / "bin" / "app_icon.ico"
if not ICON_PATH.exists():
    ICON_PATH = BASE_DIR / "bin" / "app_icon.ico"

# ── 스킬 카탈로그 (웹 UI와 동일 목록) ─────────────────────────────────────
SKILL_CATALOG = [
    {"name": "vibe-orchestrate",  "en": "Orchestrate",   "label": "오케스트레이터",  "color": "#7c3aed", "main": True},
    {"name": "vibe-brainstorm",   "en": "Brainstorm",    "label": "브레인스토밍",    "color": "#ca8a04"},
    {"name": "vibe-write-plan",   "en": "Write Plan",    "label": "계획 작성",       "color": "#ea580c"},
    {"name": "vibe-execute-plan", "en": "Execute Plan",  "label": "계획 실행",       "color": "#2563eb"},
    {"name": "vibe-debug",        "en": "Debug",         "label": "디버그 분석",     "color": "#dc2626"},
    {"name": "vibe-tdd",          "en": "TDD",           "label": "테스트 주도",     "color": "#16a34a"},
    {"name": "vibe-code-review",  "en": "Code Review",   "label": "코드 리뷰",       "color": "#0891b2"},
    {"name": "vibe-release",      "en": "Release",       "label": "릴리스",          "color": "#9333ea"},
    {"name": "vibe-heal",         "en": "Self-Heal",     "label": "자기 치유",       "color": "#db2777"},
]

# ── 색상 테마 상수 ─────────────────────────────────────────────────────────
BG_MAIN    = "#1e1e1e"
BG_COL     = "#141414"
BG_HEADER  = "#252526"
BG_CARD    = "#1a1a1a"
TEXT_WHITE = "#cccccc"
TEXT_DIM   = "#777777"
TEXT_MUTED = "#444444"
BORDER     = "#2a2a2a"
COLOR_PRI  = "#7c3aed"

# ── 에이전트 색상 ──────────────────────────────────────────────────────────
def agent_color(agent: str) -> str:
    a = (agent or "").lower()
    if "claude" in a:  return "#f59e0b"   # 황금
    if "gemini" in a:  return "#60a5fa"   # 파랑
    return "#6b7280"                       # 회색


# ════════════════════════════════════════════════════════════════════════════
# 카드 위젯 — 칸반 컬럼 안의 단일 항목
# ════════════════════════════════════════════════════════════════════════════
class KanbanCard(QFrame):
    def __init__(self, agent: str, task: str, ts: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            KanbanCard {{
                background: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: 6px;
            }}
            KanbanCard:hover {{
                border-color: #3a3a3a;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # 에이전트 + 시각 행
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)

        agent_lbl = QLabel(agent or "system")
        agent_lbl.setFont(QFont("Consolas", 8, QFont.Bold))
        agent_lbl.setStyleSheet(f"color: {agent_color(agent)}; background: transparent;")
        top.addWidget(agent_lbl)
        top.addStretch()

        # 시각 — HH:MM:SS만 표시
        try:
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = ts[:8] if ts else ""
        time_lbl = QLabel(time_str)
        time_lbl.setFont(QFont("Consolas", 7))
        time_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        top.addWidget(time_lbl)
        layout.addLayout(top)

        # 태스크 내용 (최대 3줄 truncate)
        short = task[:120] + ("…" if len(task) > 120 else "")
        task_lbl = QLabel(short)
        task_lbl.setFont(QFont("맑은 고딕", 8))
        task_lbl.setStyleSheet(f"color: {TEXT_WHITE}; background: transparent; opacity: 0.7;")
        task_lbl.setWordWrap(True)
        task_lbl.setMaximumHeight(52)
        layout.addWidget(task_lbl)


# ════════════════════════════════════════════════════════════════════════════
# 칸반 컬럼 위젯 — 헤더 + 스크롤 가능한 카드 목록
# ════════════════════════════════════════════════════════════════════════════
class KanbanColumn(QFrame):
    def __init__(self, title: str, subtitle: str = "", accent: str = COLOR_PRI, parent=None):
        super().__init__(parent)
        self.accent = accent
        self.setFixedWidth(240)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(f"""
            KanbanColumn {{
                background: {BG_COL};
                border: 1px solid {accent}44;
                border-radius: 8px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 컬럼 헤더
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"""
            QFrame {{
                background: {BG_HEADER};
                border-bottom: 1px solid {accent}30;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 10, 0)

        # 색상 점
        dot = QLabel("●")
        dot.setFont(QFont("Arial", 8))
        dot.setStyleSheet(f"color: {accent}; background: transparent;")
        h_lay.addWidget(dot)

        # 타이틀
        t_lbl = QLabel(title)
        t_lbl.setFont(QFont("맑은 고딕", 10, QFont.Bold))
        t_lbl.setStyleSheet(f"color: {TEXT_WHITE}; background: transparent;")
        h_lay.addWidget(t_lbl)
        h_lay.addStretch()

        # 서브타이틀 (카운트 등)
        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setFont(QFont("Consolas", 8))
        self.sub_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h_lay.addWidget(self.sub_lbl)
        outer.addWidget(header)

        # 스크롤 영역 — 카드 목록
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {BG_COL}; }}
            QScrollBar:vertical {{
                width: 4px; background: {BG_COL};
            }}
            QScrollBar::handle:vertical {{
                background: #3a3a3a; border-radius: 2px;
            }}
        """)

        self.cards_widget = QWidget()
        self.cards_widget.setStyleSheet(f"background: {BG_COL};")
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(6, 6, 6, 6)
        self.cards_layout.setSpacing(4)
        self.cards_layout.addStretch()  # 하단 여백 밀기

        self.scroll.setWidget(self.cards_widget)
        outer.addWidget(self.scroll)

    def set_subtitle(self, text: str):
        self.sub_lbl.setText(text)

    def clear_cards(self):
        """카드 목록 초기화 (stretch 이전까지만 제거)"""
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_card(self, agent: str, task: str, ts: str):
        card = KanbanCard(agent, task, ts)
        # stretch 바로 앞에 삽입 (항상 아래로 쌓이도록)
        idx = max(0, self.cards_layout.count() - 1)
        self.cards_layout.insertWidget(idx, card)

    def add_empty_label(self, text: str = "기록 없음"):
        lbl = QLabel(text)
        lbl.setFont(QFont("맑은 고딕", 8))
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        lbl.setAlignment(Qt.AlignCenter)
        idx = max(0, self.cards_layout.count() - 1)
        self.cards_layout.insertWidget(idx, lbl)


# ════════════════════════════════════════════════════════════════════════════
# 스킬 카탈로그 컬럼 — 정적 목록
# ════════════════════════════════════════════════════════════════════════════
class SkillCatalogColumn(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(230)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(f"""
            SkillCatalogColumn {{
                background: {BG_COL};
                border: 1px solid {COLOR_PRI}33;
                border-radius: 8px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 헤더
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"""
            QFrame {{
                background: {BG_HEADER};
                border-bottom: 1px solid {COLOR_PRI}25;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 10, 0)
        icon_lbl = QLabel("□")
        icon_lbl.setFont(QFont("Arial", 10))
        icon_lbl.setStyleSheet(f"color: {COLOR_PRI}; background: transparent;")
        h_lay.addWidget(icon_lbl)
        title_lbl = QLabel("스킬 목록")
        title_lbl.setFont(QFont("맑은 고딕", 10, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {TEXT_WHITE}; background: transparent;")
        h_lay.addWidget(title_lbl)
        h_lay.addStretch()
        sub = QLabel("Skill Catalog")
        sub.setFont(QFont("Consolas", 7))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h_lay.addWidget(sub)
        outer.addWidget(header)

        # 스크롤 가능 스킬 목록
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {BG_COL}; }}
            QScrollBar:vertical {{
                width: 4px; background: {BG_COL};
            }}
            QScrollBar::handle:vertical {{
                background: #3a3a3a; border-radius: 2px;
            }}
        """)

        content = QWidget()
        content.setStyleSheet(f"background: {BG_COL};")
        v = QVBoxLayout(content)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(5)

        for skill in SKILL_CATALOG:
            card = self._make_skill_card(skill)
            v.addWidget(card)
        v.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _make_skill_card(self, skill: dict) -> QFrame:
        is_main = skill.get("main", False)
        color = skill.get("color", COLOR_PRI)

        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {"#0d0d1a" if is_main else BG_CARD};
                border: 1px solid {color + "40" if is_main else BORDER};
                border-radius: 6px;
                padding: 2px;
            }}
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        # 영어명 + MAIN 배지
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        dot = QLabel("●")
        dot.setFont(QFont("Arial", 6))
        dot.setStyleSheet(f"color: {color}; background: transparent;")
        row.addWidget(dot)
        en_lbl = QLabel(skill["en"])
        en_lbl.setFont(QFont("Consolas", 9, QFont.Bold))
        en_lbl.setStyleSheet(f"color: {color}; background: transparent;")
        row.addWidget(en_lbl)
        row.addStretch()
        if is_main:
            badge = QLabel("MAIN")
            badge.setFont(QFont("Consolas", 7, QFont.Bold))
            badge.setStyleSheet(f"color: {color}; background: {color}22; border-radius: 3px; padding: 1px 4px;")
            row.addWidget(badge)
        lay.addLayout(row)

        # 한글명
        kr_lbl = QLabel(skill["label"])
        kr_lbl.setFont(QFont("맑은 고딕", 8, QFont.Bold))
        kr_lbl.setStyleSheet(f"color: #888888; background: transparent;")
        kr_lbl.setIndent(14)
        lay.addWidget(kr_lbl)

        return frame


# ════════════════════════════════════════════════════════════════════════════
# 메인 칸반 보드 창
# ════════════════════════════════════════════════════════════════════════════
class KanbanBoardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vibe Coding — 칸반 보드")
        self.resize(1400, 860)
        self.setMinimumSize(800, 500)

        # 앱 아이콘
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        # 전체 팔레트 다크 테마
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(BG_MAIN))
        pal.setColor(QPalette.WindowText, QColor(TEXT_WHITE))
        pal.setColor(QPalette.Base, QColor(BG_COL))
        pal.setColor(QPalette.Text, QColor(TEXT_WHITE))
        QApplication.setPalette(pal)

        # 중앙 위젯
        central = QWidget()
        central.setStyleSheet(f"background: {BG_MAIN};")
        self.setCentralWidget(central)
        main_v = QVBoxLayout(central)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(0)

        # ── 타이틀바 ──────────────────────────────────────────────────────
        titlebar = QFrame()
        titlebar.setFixedHeight(46)
        titlebar.setStyleSheet(f"""
            QFrame {{
                background: #0f0f1e;
                border-bottom: 1px solid {COLOR_PRI}44;
            }}
        """)
        tb_lay = QHBoxLayout(titlebar)
        tb_lay.setContentsMargins(16, 0, 16, 0)
        tb_lay.setSpacing(12)

        # 로고 점
        logo = QLabel("◆")
        logo.setFont(QFont("Arial", 14))
        logo.setStyleSheet(f"color: {COLOR_PRI}; background: transparent;")
        tb_lay.addWidget(logo)

        title_lbl = QLabel("Vibe Coding  —  칸반 보드")
        title_lbl.setFont(QFont("맑은 고딕", 11, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {TEXT_WHITE}; background: transparent;")
        tb_lay.addWidget(title_lbl)

        hint = QLabel("  이 창을 다른 모니터로 드래그하세요")
        hint.setFont(QFont("맑은 고딕", 8))
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tb_lay.addWidget(hint)
        tb_lay.addStretch()

        # 라이브 상태 표시
        self.live_lbl = QLabel("● 폴링 중...")
        self.live_lbl.setFont(QFont("Consolas", 8))
        self.live_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tb_lay.addWidget(self.live_lbl)

        # 새로고침 버튼
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFont(QFont("맑은 고딕", 8))
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_PRI}22;
                color: {COLOR_PRI};
                border: 1px solid {COLOR_PRI}44;
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: {COLOR_PRI}44; }}
        """)
        refresh_btn.clicked.connect(self.refresh_data)
        tb_lay.addWidget(refresh_btn)

        main_v.addWidget(titlebar)

        # ── 수평 스크롤 가능 칸반 영역 ────────────────────────────────────
        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.board_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.board_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {BG_MAIN}; }}
            QScrollBar:horizontal {{
                height: 6px; background: {BG_MAIN};
            }}
            QScrollBar::handle:horizontal {{
                background: #3a3a3a; border-radius: 3px; min-width: 30px;
            }}
        """)

        self.board_widget = QWidget()
        self.board_widget.setStyleSheet(f"background: {BG_MAIN};")
        self.board_layout = QHBoxLayout(self.board_widget)
        self.board_layout.setContentsMargins(12, 12, 12, 12)
        self.board_layout.setSpacing(10)
        self.board_layout.addStretch()  # 우측 여백

        self.board_scroll.setWidget(self.board_widget)
        main_v.addWidget(self.board_scroll)

        # ── 터미널 컬럼 캐시 ──────────────────────────────────────────────
        # key: terminal_id(str), value: KanbanColumn
        self.terminal_columns: dict[str, KanbanColumn] = {}

        # 스킬 카탈로그 컬럼은 항상 맨 앞에 고정
        self._skill_col = SkillCatalogColumn()
        self.board_layout.insertWidget(0, self._skill_col)

        # ── 폴링 타이머 (3초) ─────────────────────────────────────────────
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh_data)
        self.poll_timer.start(3000)

        # 최초 로드
        self.refresh_data()

    # ── 데이터 로드 ────────────────────────────────────────────────────────
    def refresh_data(self):
        """task_logs.jsonl + skill_results.jsonl 읽어 칸반 갱신"""
        logs = self._load_task_logs()
        self._update_board(logs)
        now = datetime.now().strftime("%H:%M:%S")
        self.live_lbl.setText(f"● 갱신됨 {now}")
        self.live_lbl.setStyleSheet(f"color: #22c55e; background: transparent;")

    def _load_task_logs(self) -> list[dict]:
        """task_logs.jsonl 전체 파싱 — 최근 500줄만 처리"""
        log_file = DATA_DIR / "task_logs.jsonl"
        if not log_file.exists():
            return []
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            result = []
            for line in lines[-500:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except Exception:
                    pass
            return result
        except Exception:
            return []

    # ── 보드 갱신 ──────────────────────────────────────────────────────────
    def _update_board(self, logs: list[dict]):
        """터미널별로 그룹화하여 칸반 컬럼에 반영"""
        # 터미널별 로그 그룹화 (최근 15개)
        grouped: dict[str, list[dict]] = {}
        for entry in logs:
            tid = str(entry.get("terminal_id", "T?"))
            grouped.setdefault(tid, []).append(entry)

        # 기존에 없는 터미널 컬럼 생성
        for tid in sorted(grouped.keys()):
            if tid not in self.terminal_columns:
                accent = self._tid_color(tid)
                col = KanbanColumn(
                    title=tid,
                    subtitle="",
                    accent=accent,
                )
                # stretch 바로 앞에 삽입 (스킬 카탈로그 다음)
                insert_idx = self.board_layout.count() - 1
                self.board_layout.insertWidget(insert_idx, col)
                self.terminal_columns[tid] = col

        # 각 컬럼 카드 갱신
        for tid, col in self.terminal_columns.items():
            entries = grouped.get(tid, [])
            recent = entries[-20:]  # 최근 20개만 표시
            col.clear_cards()
            col.set_subtitle(f"{len(entries)}건")
            if not recent:
                col.add_empty_label("기록 없음")
            else:
                for entry in recent:
                    agent = entry.get("agent", "")
                    task  = entry.get("task", "")
                    ts    = entry.get("timestamp", "")
                    # 빈 라인 구분자("───") 카드 생략
                    if "───" in task and len(task) < 20:
                        continue
                    col.add_card(agent, task, ts)

    def _tid_color(self, tid: str) -> str:
        """터미널 ID별 고정 색상"""
        colors = ["#2563eb", "#16a34a", "#ca8a04", "#dc2626",
                  "#9333ea", "#0891b2", "#db2777", "#ea580c"]
        try:
            idx = int("".join(filter(str.isdigit, tid)) or "0") % len(colors)
        except Exception:
            idx = 0
        return colors[idx]


# ════════════════════════════════════════════════════════════════════════════
# 진입점
# ════════════════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Vibe Kanban Board")
    app.setStyle("Fusion")

    # Fusion 스타일 다크 팔레트
    pal = app.palette()
    pal.setColor(QPalette.Window,          QColor("#1e1e1e"))
    pal.setColor(QPalette.WindowText,      QColor("#cccccc"))
    pal.setColor(QPalette.Base,            QColor("#141414"))
    pal.setColor(QPalette.AlternateBase,   QColor("#1a1a1a"))
    pal.setColor(QPalette.ToolTipBase,     QColor("#252526"))
    pal.setColor(QPalette.ToolTipText,     QColor("#cccccc"))
    pal.setColor(QPalette.Text,            QColor("#cccccc"))
    pal.setColor(QPalette.Button,          QColor("#2d2d2d"))
    pal.setColor(QPalette.ButtonText,      QColor("#cccccc"))
    pal.setColor(QPalette.BrightText,      QColor("#ffffff"))
    pal.setColor(QPalette.Link,            QColor("#7c3aed"))
    pal.setColor(QPalette.Highlight,       QColor("#7c3aed"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)

    window = KanbanBoardWindow()
    window.show()

    # 화면 중앙에 배치
    screen = app.primaryScreen().availableGeometry()
    w = window.width()
    h = window.height()
    window.move(
        (screen.width()  - w) // 2 + screen.left(),
        (screen.height() - h) // 2 + screen.top(),
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
