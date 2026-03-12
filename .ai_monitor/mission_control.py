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

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
import psycopg2
import select


def _python_runner_cmds() -> list[str]:
    """독립 창용 보조 스크립트를 실행할 실제 Python 인터프리터 후보를 반환합니다."""
    candidates: list[str] = []
    seen: set[str] = set()

    for path in (
        BASE_DIR / 'venv' / 'Scripts' / 'python.exe',
        PROJECT_ROOT / '.ai_monitor' / 'venv' / 'Scripts' / 'python.exe',
        PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe',
    ):
        path_str = str(path)
        if path.exists() and path_str not in seen:
            candidates.append(path_str)
            seen.add(path_str)

    exe_name = Path(sys.executable).name.lower()
    if exe_name.startswith('python') and sys.executable not in seen:
        candidates.append(sys.executable)
        seen.add(sys.executable)

    for name in ('python', 'py'):
        resolved = shutil.which(name)
        if resolved and resolved not in seen:
            candidates.append(resolved)
            seen.add(resolved)

    return candidates or ['python']

class PgListenerThread(QThread):
    """PostgreSQL LISTEN 채널을 감시하는 백그라운드 스레드"""
    log_received = Signal(dict)
    status_changed = Signal(dict)
    debate_received = Signal(dict) # 토론 이벤트 신규

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        try:
            conn = psycopg2.connect(host="localhost", port=5433, user="postgres", database="postgres")
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            cursor.execute("LISTEN hive_log_channel;")
            
            while self.running:
                if select.select([conn], [], [], 2) == ([], [], []):
                    continue
                
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    try:
                        ev = json.loads(notify.payload)
                        table = ev.get("table")
                        data = ev.get("data", {})
                        
                        # 1. 로그 데이터 처리
                        if table == "hive_logs":
                            self.log_received.emit(data)
                            
                            # 상태 데이터 처리
                            meta = data.get("metadata", {})
                            if isinstance(meta, str): meta = json.loads(meta)
                            status = meta.get("raw_status")
                            if status:
                                self.status_changed.emit({
                                    "agent": data.get("agent"),
                                    "status": status,
                                    "terminal_id": meta.get("terminal_id")
                                })
                        
                        # 2. 토론 데이터 처리 (신규)
                        elif table in ("hive_debates", "hive_debate_messages"):
                            self.debate_received.emit({"table": table, "data": data})
                            
                    except Exception as e: 
                        print(f"[PgListener] Parse Error: {e}")
            conn.close()
        except Exception as e:
            print(f"[PgListener] Connection Error: {e}")

class MissionControlApp(QObject):
    """
    미션 컨트롤의 메인 애플리케이션 엔진.
    트레이 아이콘 관리 및 PostgreSQL 실시간 이벤트를 담당합니다.
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
        
        # PostgreSQL 실시간 리스너 시작
        self.pg_thread = PgListenerThread()
        self.pg_thread.log_received.connect(self.on_pg_log)
        self.pg_thread.status_changed.connect(self.on_pg_status)
        self.pg_thread.debate_received.connect(self.on_pg_debate) # 토론 연동
        self.pg_thread.start()
        
        # 펄스 애니메이션 타이머 (50ms 간격)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.timeout.connect(self.update_pulse)
        self.pulse_frame = 0
        self.is_pulsing = False
        
        self.last_status = {}
        self.active_agents = []
        self.terminal_states = {} # 터미널별 상태 저장

    def on_pg_log(self, data):
        """PG 리스너로부터 로그 수신 시 사이드바 업데이트"""
        agent = data.get("agent", "SYSTEM")
        meta = data.get("metadata", {})
        if isinstance(meta, str): meta = json.loads(meta)
        tid = meta.get("terminal_id", "")
        
        display_name = f"{agent} [{tid}]" if tid else agent
        message = data.get("message", "")
        if message:
            self.sidebar.add_log(display_name, message)

    def on_pg_debate(self, ev):
        """토론 이벤트 발생 시 HUD 및 로그 업데이트"""
        table = ev["table"]
        data = ev["data"]
        
        if table == "hive_debates":
            # 토론 HUD 업데이트
            self.sidebar.debate_hud.update_debate(
                data.get("topic"), 
                data.get("current_round", 1), 
                data.get("status")
            )
            if data.get("status") == "closed":
                self.sidebar.add_log("SYSTEM", f"🏁 결론: {data.get('final_decision')}", "synthesis")
        
        elif table == "hive_debate_messages":
            # 개별 의견을 색상별 로그로 출력
            agent = data.get("agent")
            msg_type = data.get("type", "proposal")
            content = data.get("content")
            self.sidebar.add_log(agent, content, msg_type)

    def on_pg_status(self, ev):
        """PG 리스너로부터 상태 변경 수신 시 트레이 아이콘 업데이트"""
        tid = ev.get("terminal_id")
        if not tid: return
        
        status = ev.get("status")
        agent = ev.get("agent", "").lower()
        
        if status == "running":
            self.terminal_states[tid] = agent
        else:
            if tid in self.terminal_states:
                del self.terminal_states[tid]

        # 활성 에이전트 목록 추출
        active_names = list(set(self.terminal_states.values()))
        
        # 상태가 변했는지 확인
        if active_names != self.active_agents:
            self.active_agents = active_names
            if self.active_agents:
                if not self.is_pulsing:
                    self.is_pulsing = True
                    self.pulse_timer.start(50)
            else:
                self.is_pulsing = False
                self.pulse_timer.stop()
                self.reset_icon()
            
            self.update_tray_visuals(None)
            # 사이드바 상태 업데이트용 데이터 포맷팅
            ui_status = {name: {"status": "active"} for name in active_names}
            for name in ["claude", "gemini", "codex"]:
                if name not in ui_status: ui_status[name] = {"status": "idle"}
            self.status_changed.emit(ui_status)

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
            python_cmds = _python_runner_cmds()
            if not python_cmds:
                raise RuntimeError('Python interpreter not found for kanban launch')
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            subprocess.Popen(
                [python_cmds[0], str(kanban_script)],
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
