# ------------------------------------------------------------------------
# 파일명: knowledge_graph_window.py
# 설명: 지식 그래프 독립 창 — PySide6 QWebEngineView 기반.
#       메인 앱에서 /api/graph/launch 호출 시 서브프로세스로 실행됩니다.
#       포트는 커맨드라인 인수로 전달받아 로컬 서버의 ?graph=1 페이지를 로드하며,
#       다른 모니터로 자유롭게 이동할 수 있는 독립 데스크톱 창입니다.
#
# REVISION HISTORY:
# - 2026-03-10 Claude: 최초 구현 — PySide6 QWebEngineView 지식 그래프 독립 창
# ------------------------------------------------------------------------

import sys
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QIcon

# ── 경로 설정 ──────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

# 아이콘 경로 — 메인 앱과 동일
ICON_PATH = BASE_DIR / "bin" / "app_icon.ico"

# ── 포트 수신 — server.py가 커맨드라인 인수로 전달 ────────────────────────
# 예: python knowledge_graph_window.py 9000
DEFAULT_PORT = 9000
try:
    HTTP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
except ValueError:
    HTTP_PORT = DEFAULT_PORT

GRAPH_URL = f"http://localhost:{HTTP_PORT}/?graph=1"


class KnowledgeGraphWindow(QMainWindow):
    """지식 그래프 독립 창.

    QWebEngineView로 로컬 React 앱의 ?graph=1 모드를 렌더링합니다.
    Force-Directed Graph(Canvas 기반)는 WebEngine이 완전히 지원하므로
    PySide6 네이티브 위젯 재구현 없이 그대로 사용합니다.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("지식 그래프 — 하이브 마인드")
        self.resize(1100, 760)

        # 화면 중앙에 배치 (사용자가 원하는 모니터로 이동 가능)
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width()  - 1100) // 2
        y = (screen.height() - 760)  // 2
        self.move(x, y)

        # 아이콘 설정
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        # ── WebEngineView 설정 ──────────────────────────────────────────
        self.webview = QWebEngineView()
        settings = self.webview.settings()
        # Canvas / WebGL / 로컬 폰트 등 ForceGraph2D에 필요한 기능 활성화
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        self.webview.setUrl(QUrl(GRAPH_URL))
        self.setCentralWidget(self.webview)

        # 배경색 — 앱 테마와 동일한 다크 배경 (#0d0d0d)
        self.setStyleSheet("QMainWindow { background-color: #0d0d0d; }")


def main():
    # DPI 스케일링 — 고해상도 모니터 대응
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("VibeCoding KnowledgeGraph")
    app.setOrganizationName("VibeCoding")

    window = KnowledgeGraphWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
