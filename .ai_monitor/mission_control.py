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

# 경로 설정
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = BASE_DIR.parent

# 데이터 디렉토리 (server.py와 동일 로직)
if os.name == 'nt':
    DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding"
else:
    DATA_DIR = Path.home() / ".vibe-coding"

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
                            task = data.get("task", "")
                            if task:
                                self.sidebar.add_log(agent, task)
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
        
        menu.addSeparator()
        
        exit_action = QAction("종료", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)

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
        """에이전트 라이브 상태 파일을 읽어 상태를 업데이트합니다."""
        live_file = DATA_DIR / "agent_live.jsonl"
        if not live_file.exists():
            return
            
        try:
            with open(live_file, "r", encoding="utf-8") as f:
                content = f.read().strip().split('\n')
                if not content: return
                status = json.loads(content[-1])
                
            if status != self.last_status:
                self.last_status = status
                self.active_agents = [name for name, info in status.items() if info.get('status') == 'active']
                
                if self.active_agents:
                    if not self.is_pulsing:
                        self.is_pulsing = True
                        self.pulse_timer.start(50)
                else:
                    self.is_pulsing = False
                    self.pulse_timer.stop()
                    self.reset_icon()
                
                self.update_tray_visuals(status)
                self.status_changed.emit(status)
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
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    mc = MissionControlApp()
    print("[Mission Control] 네이티브 관제 센터가 백그라운드에서 시작되었습니다.")
    sys.exit(app.exec())
