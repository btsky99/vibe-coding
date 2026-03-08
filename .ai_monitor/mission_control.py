# ------------------------------------------------------------------------
# 📄 파일명: mission_control.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: AI 에이전트 전용 네이티브 윈도우 관제 센터 (Mission Control).
#          시스템 트레이 위젯 및 사이드바 HUD를 관리합니다.
# ------------------------------------------------------------------------

import sys
import os
import json
import time
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu)
from PySide6.QtGui import QIcon, QAction, QColor, QPainter, QBrush
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from mission_control_ui import MissionControlSidebar

# ── 칸반 보드 윈도우 임포트 ──────────────────────────────────────────────
try:
    from kanban_board import KanbanBoardWindow
except ImportError:
    KanbanBoardWindow = None

# 경로 설정
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parent

# 데이터 디렉토리 결정 로직 (프로젝트 로컬 우선)
# Why: agent_shell.py와 server.py가 프로젝트 로컬 .ai_monitor/data를 사용하므로
#      모니터링 앱도 동일한 소스를 바라봐야 실시간 동기화가 가능합니다.
_local_data = PROJECT_ROOT / ".ai_monitor" / "data"
if _local_data.exists():
    DATA_DIR = _local_data
elif getattr(sys, 'frozen', False):
    if os.name == 'nt':
        DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
    else:
        DATA_DIR = Path.home() / ".vibe-coding"
else:
    # 개발 모드 폴백
    DATA_DIR = BASE_DIR / "data"

if not DATA_DIR.exists():
    try: os.makedirs(DATA_DIR, exist_ok=True)
    except: pass

# 아이콘 경로
ICON_PATH = PROJECT_ROOT / ".ai_monitor" / "bin" / "app_icon.ico"
if not ICON_PATH.exists():
    ICON_PATH = PROJECT_ROOT / "assets" / "vibe_coding_icon.ico"

class MissionControlApp(QObject):
    """
    미션 컨트롤의 메인 애플리케이션 엔진.
    트레이 아이콘 관리 및 상태 폴링을 담당합니다.
    """
    status_changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.tray_icon = QSystemTrayIcon(self)
        
        # 사이드바 초기화
        self.sidebar = MissionControlSidebar()
        self.status_changed.connect(self.sidebar.update_status)
        
        # 기본 아이콘 로드
        self.base_pixmap = None
        if ICON_PATH.exists():
            from PySide6.QtGui import QPixmap
            self.base_pixmap = QPixmap(str(ICON_PATH)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            from PySide6.QtGui import QPixmap
            self.base_pixmap = QPixmap(32, 32)
            self.base_pixmap.fill(Qt.transparent)

        self.tray_icon.setIcon(QIcon(self.base_pixmap))
        self.setup_menu()
        self.tray_icon.show()
        
        # 상태 폴링 타이머 (1초 간격)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_agent_status)
        self.poll_timer.start(1000)
        
        # 로그 테일링 타이머 (500ms 간격)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.tail_logs)
        self.log_timer.start(500)
        self.last_log_pos = 0
        self.initialize_log_pos()
        
        # 펄스 애니메이션 타이머 (50ms 간격)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self.update_pulse)
        self.pulse_frame = 0
        self.is_pulsing = False
        
        self.last_status = {}
        self.active_agents = []

    def initialize_log_pos(self):
        """서버 시작 시 로그 파일의 끝으로 포인터 이동"""
        log_file = DATA_DIR / "task_logs.jsonl"
        if log_file.exists():
            self.last_log_pos = log_file.stat().st_size

    def tail_logs(self):
        """task_logs.jsonl 파일을 실시간으로 읽어 사이드바에 추가합니다."""
        log_file = DATA_DIR / "task_logs.jsonl"
        if not log_file.exists(): return
        
        try:
            curr_size = log_file.stat().st_size
            if curr_size < self.last_log_pos: # 파일이 로테이트되거나 비워진 경우
                self.last_log_pos = 0
                
            if curr_size > self.last_log_pos:
                with open(log_file, "r", encoding="utf-8") as f:
                    f.seek(self.last_log_pos)
                    new_lines = f.readlines()
                    self.last_log_pos = f.tell()
                    
                    for line in new_lines:
                        if not line.strip(): continue
                        try:
                            data = json.loads(line)
                            agent = data.get("agent", "SYSTEM")
                            tid = data.get("terminal_id", "")
                            # 터미널 ID가 있으면 에이전트 이름 옆에 표시 (예: CLAUDE [T1])
                            display_name = f"{agent} [{tid}]" if tid else agent
                            task = data.get("task", "")
                            if task:
                                self.sidebar.add_log(display_name, task)
                        except: pass
        except Exception as e:
            print(f"[Mission Control] 로그 테일링 오류: {e}")

    def setup_menu(self):
        menu = QMenu()
        
        title_action = QAction("Vibe Mission Control", self)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
        
        self.open_action = QAction("사이드바 열기 (Ctrl+Alt+M)", self)
        self.open_action.triggered.connect(self.toggle_sidebar)
        menu.addAction(self.open_action)

        if KanbanBoardWindow:
            kanban_action = QAction("칸반 보드 열기 (네이티브)", self)
            kanban_action.triggered.connect(self.open_kanban)
            menu.addAction(kanban_action)
        
        menu.addSeparator()
        
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)

    def open_kanban(self):
        """네이티브 칸반 보드 창을 독립 프로세스로 실행합니다.
        
        Why: Mission Control 프로세스 안에서 창을 띄우면 사이드바와 생명주기를 공유하게 되므로,
             독립적으로 다른 모니터로 이동하거나 닫을 수 있도록 별도 프로세스로 띄우는 것이 유리합니다.
        """
        try:
            import subprocess
            kanban_script = BASE_DIR / 'kanban_board.py'
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            subprocess.Popen(
                [sys.executable, str(kanban_script)],
                creationflags=_no_window,
                close_fds=True,
            )
        except Exception as e:
            print(f"[Mission Control] 칸반 보드 실행 실패: {e}")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_sidebar()

    def toggle_sidebar(self):
        self.sidebar.toggle()
        if self.sidebar.is_visible:
            self.open_action.setText("사이드바 닫기")
        else:
            self.open_action.setText("사이드바 열기")

    def poll_agent_status(self):
        """agent_live.jsonl 이벤트를 분석하여 다중 터미널 상태를 집계합니다.

        Why: 여러 터미널(T1~T8)에서 에이전트가 동시에 실행될 수 있으므로,
             개별 이벤트들을 모아 현재 활성 상태인 에이전트 목록을 추출해야 합니다.
        """
        live_file = DATA_DIR / "agent_live.jsonl"
        if not live_file.exists():
            return
            
        try:
            with open(live_file, "r", encoding="utf-8") as f:
                # 성능을 위해 마지막 200줄만 읽음
                lines = f.readlines()[-200:]
                if not lines: return

            # 터미널별 최근 상태 추적
            terminal_status = {}
            for line in lines:
                try:
                    ev = json.loads(line)
                    # agent_shell은 'terminal_id' 또는 'terminal' 키를 사용
                    tid = ev.get("terminal_id") or ev.get("terminal")
                    if not tid: continue
                    
                    etype = ev.get("type")
                    if etype == "started":
                        terminal_status[tid] = {"status": "active", "cli": ev.get("cli")}
                    elif etype in ("done", "error", "stopped"):
                        terminal_status[tid] = {"status": "idle"}
                except: continue

            # 에이전트 종류별(claude, gemini, codex) 활성 여부 집계
            current_map = {"claude": {"status": "idle"}, "gemini": {"status": "idle"}, "codex": {"status": "idle"}}
            active_names = []
            
            for tid, info in terminal_status.items():
                if info.get("status") == "active":
                    cli = info.get("cli", "").lower()
                    if cli in current_map:
                        current_map[cli]["status"] = "active"
                        if cli not in active_names:
                            active_names.append(cli)

            # 상태 변경 시에만 UI 업데이트
            if current_map != self.last_status:
                self.last_status = current_map
                self.active_agents = active_names
                
                if self.active_agents:
                    if not self.is_pulsing:
                        self.is_pulsing = True
                        self.pulse_timer.start(50)
                else:
                    self.is_pulsing = False
                    self.pulse_timer.stop()
                    self.reset_icon()
                
                self.update_tray_visuals(current_map)
                self.status_changed.emit(current_map)
        except Exception as e:
            print(f"[Mission Control] 폴링 오류: {e}")

    def update_pulse(self):
        """아이콘에 펄싱하는 상태 점을 그립니다."""
        import math
        self.pulse_frame = (self.pulse_frame + 1) % 40
        opacity = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self.pulse_frame * 0.15))
        
        from PySide6.QtGui import QPixmap, QColor, QBrush, QPen
        new_pixmap = self.base_pixmap.copy()
        painter = QPainter(new_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        dot_color = QColor(155, 89, 182) # Purple
        active_names = [a.lower() for a in self.active_agents]
        if "claude" in active_names:
            dot_color = QColor(46, 204, 113) # Green
        elif "gemini" in active_names:
            dot_color = QColor(52, 152, 219) # Blue
            
        dot_color.setAlphaF(opacity)
        painter.setBrush(QBrush(dot_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(20, 2, 10, 10)
        painter.end()
        self.tray_icon.setIcon(QIcon(new_pixmap))

    def reset_icon(self):
        self.tray_icon.setIcon(QIcon(self.base_pixmap))

    def update_tray_visuals(self, status):
        if self.active_agents:
            self.tray_icon.setToolTip(f"실행 중: {', '.join(self.active_agents)}")
        else:
            self.tray_icon.setToolTip("Vibe 에이전트 대기 중")

if __name__ == "__main__":
    # --kanban 인자가 있으면 칸반 보드 창만 독립 실행
    if "--kanban" in sys.argv and KanbanBoardWindow:
        app = QApplication(sys.argv)
        # 칸반 보드 전용 다크 테마 팔레트 설정
        from PySide6.QtGui import QPalette, QColor
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#1e1e1e"))
        pal.setColor(QPalette.WindowText, QColor("#cccccc"))
        app.setPalette(pal)
        
        window = KanbanBoardWindow()
        window.show()
        sys.exit(app.exec())

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    mc = MissionControlApp()
    print("[Mission Control] 네이티브 관제 센터가 백그라운드에서 시작되었습니다.")
    sys.exit(app.exec())
