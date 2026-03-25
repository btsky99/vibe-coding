"""
FILE: .ai_monitor/dashboard_window.py
DESCRIPTION: 대시보드 독립 창 — PySide6 QWebEngineView 기반. 배포 시 vibe-dashboard.exe로 빌드.

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
# REVISION HISTORY:
# - 2026-03-13 Claude: kanban 탭 추가 — B안 통합. kanban_board.py(PySide6 네이티브) 제거하고
#                      React TaskBoardPanel(?kanban=1)으로 일원화. 동일 API 데이터 사용으로
#                      두 창 간 데이터 불일치 문제 해소.
# - 2026-03-12 Claude: 최초 커밋 + 배포 EXE 분리 대응 헤더 추가 (A안)
# ------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


BASE_DIR = Path(__file__).resolve().parent

ICON_PATH = BASE_DIR / 'bin' / 'app_icon.ico'
DEFAULT_PORT = 9000

try:
    HTTP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
except ValueError:
    HTTP_PORT = DEFAULT_PORT

TAB = (sys.argv[2] if len(sys.argv) > 2 else 'agent').strip().lower() or 'agent'
TITLE_MAP = {
    'agent': '바이브 코딩',
    'messages': '바이브 코딩 - 메시지',
    'tasks': '바이브 코딩 - 태스크',
    'memory': '바이브 코딩 - 공유 메모리',
    'git': '바이브 코딩 - Git',
    'mcp': '바이브 코딩 - MCP',
    'hive': '바이브 코딩 - 하이브',
    # kanban: React TaskBoardPanel 기반 오케스트레이션 보드 (B안 통합)
    'kanban': '바이브 코딩 - 오케스트레이션 보드',
}
# kanban 탭은 ?kanban=1 파라미터로 KanbanOnlyApp 컴포넌트를 렌더링
# 그 외 탭은 기존 ?page=dashboard&tab=<name> 경로 사용
if TAB == 'kanban':
    DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?kanban=1"
else:
    DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?page=dashboard&tab={quote(TAB)}"


def _fetch_project_name() -> str:
    """서버 API에서 현재 프로젝트명을 가져온다. 실패 시 빈 문자열 반환."""
    try:
        with urlopen(f"http://localhost:{HTTP_PORT}/api/project-info", timeout=2) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('project_name', '')
    except Exception:
        return ''


class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # 프로젝트명을 서버에서 동적으로 가져와 타이틀에 반영
        base_title = TITLE_MAP.get(TAB, TITLE_MAP['agent'])
        project_name = _fetch_project_name()
        title = f"{base_title} [{project_name}]" if project_name else base_title
        self.setWindowTitle(title)
        # kanban(오케스트레이션 보드)은 기존 kanban_board.py와 동일한 크기로 시작
        w, h = (1440, 860) if TAB == 'kanban' else (1400, 900)
        self.resize(w, h)

        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - w) // 2
        y = (screen.height() - h) // 2
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
    app.setApplicationName('바이브 코딩')
    app.setOrganizationName('VibeCoding')

    window = DashboardWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
