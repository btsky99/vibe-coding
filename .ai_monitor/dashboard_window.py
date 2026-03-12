# ------------------------------------------------------------------------
# 파일명: dashboard_window.py
# 설명: 대시보드 독립 창 — PySide6 QWebEngineView 기반.
#       배포 버전: vibe-dashboard.exe 로 PyInstaller 빌드되어 {app}\ 에 설치됨.
#       메인 앱(server.py frozen 모드)이 vibe-dashboard.exe <port> <tab> 으로 직접 실행.
#       개발 버전: python dashboard_window.py <port> <tab> 으로 직접 실행.
#
# REVISION HISTORY:
# - 2026-03-12 Claude: 최초 커밋 + 배포 EXE 분리 대응 헤더 추가 (A안)
# ------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

ICON_PATH = BASE_DIR / 'bin' / 'app_icon.ico'
DEFAULT_PORT = 9000

try:
    HTTP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
except ValueError:
    HTTP_PORT = DEFAULT_PORT

TAB = (sys.argv[2] if len(sys.argv) > 2 else 'agent').strip().lower() or 'agent'
TITLE_MAP = {
    'agent': 'Vibe Coding Master',
    'discord': 'Discord Bridge Settings',
    'messages': 'Messages',
    'tasks': 'Tasks',
    'memory': 'Shared Memory',
    'git': 'Git',
    'mcp': 'MCP',
    'hive': 'Hive',
}
DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?page=dashboard&tab={quote(TAB)}"


class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(TITLE_MAP.get(TAB, TITLE_MAP['agent']))
        self.resize(1400, 900)

        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 1400) // 2
        y = (screen.height() - 900) // 2
        self.move(x, y)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.webview = QWebEngineView()
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        self.webview.setUrl(QUrl(DASHBOARD_URL))
        self.setCentralWidget(self.webview)
        self.setStyleSheet('QMainWindow { background-color: #1e1e1e; }')


def main() -> None:
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
    app = QApplication(sys.argv)
    app.setApplicationName('VibeCoding Dashboard')
    app.setOrganizationName('VibeCoding')

    window = DashboardWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
