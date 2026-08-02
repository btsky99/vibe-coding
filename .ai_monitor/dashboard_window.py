"""
FILE: .ai_monitor/dashboard_window.py
DESCRIPTION: 대시보드 독립 창 — PySide6 QWebEngineView 기반. 배포 시 vibe-dashboard.exe로 빌드.

REVISION HISTORY:
- 2026-07-16 Claude: 9차 정리 — kanban 탭 은퇴. 오케스트레이션 보드(TaskBoardPanel/?kanban=1)
                     은퇴로 진입 경로 소멸. /api/kanban/launch 라우트도 동시 제거됨.
- 2026-04-09 Claude: 클래식/오피스 창 충돌 및 로딩 지연 수정.
                     (1) QWebEngineProfile과 QWebEnginePage의 parent를 self.webview →
                         self(QMainWindow)로 승격. webview 파괴 시 profile이 page보다
                         먼저 소멸되는 수명 역전을 막아 종료 시 크래시/강제 종료를 해결.
                         Qt 공식 규칙: profile must outlive page.
                     (2) 저장 경로와 profile_name을 TAB별로 분리
                         (qt_webengine/{tab}/, vibe-{tab}-{project}). 이전에는 classic과
                         office가 동일한 qt_webengine/ + "vibe-office-*" 프로필을 공유해
                         Chromium 캐시/IndexedDB lock 경합이 발생, 한쪽이 강제 종료되거나
                         초기 로드가 크게 지연되었음.
                     (3) _fetch_project_name() timeout 2초 → 0.5초로 단축.
                         저장 경로 격리를 위해 프로필 생성 전 동기 호출이 필요하지만
                         타임아웃을 짧게 잡아 서버 지연 시 UI 블로킹을 최소화.
- 2026-04-09 Claude: QWebEngineProfile에 영구 저장 경로 설정.
                     기본 프로필은 Qt가 휘발성 OTR로 취급해 localStorage/쿠키가
                     앱 재실행 시 유실되는 문제가 있었음. %APPDATA%/vibe-coding/{dev|exe}/
                     {project}/qt_webengine/ 로 고정해 메인 pywebview 창과 같은
                     네임스페이스 규칙을 따른다.
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
- 2026-03-13 Claude: kanban 탭 추가 — B안 통합. kanban_board.py(PySide6 네이티브) 제거하고
                     React TaskBoardPanel(?kanban=1)으로 일원화. 동일 API 데이터 사용으로
                     두 창 간 데이터 불일치 문제 해소.
- 2026-03-12 Claude: 최초 커밋 + 배포 EXE 분리 대응 헤더 추가 (A안)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


BASE_DIR = Path(__file__).resolve().parent


def _resolve_qt_storage_path(project_name: str, tab: str) -> Path:
    """Qt WebEngine 영구 저장 경로 — 메인 창(WebView2)과 같은 네임스페이스 규칙.

    %APPDATA%/vibe-coding/{dev|exe}/{project}/qt_webengine/{tab}/
    개발 모드와 EXE 빌드를 분리해 스키마 차이로 인한 데이터 손상을 방지한다.
    TAB별 하위 디렉터리로 분리해 classic/office 등 여러 창이 동시에 떠도
    Chromium 캐시/IndexedDB lock 경합이 발생하지 않도록 한다.
    """
    appdata = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    mode = 'exe' if getattr(sys, 'frozen', False) else 'dev'
    safe_name = project_name or 'default'
    safe_tab = tab or 'agent'
    path = Path(appdata) / 'vibe-coding' / mode / safe_name / 'qt_webengine' / safe_tab
    path.mkdir(parents=True, exist_ok=True)
    return path

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
    # office: 가상 오피스(메타버스) 독립 창
    'office': '바이브 코딩 - 오피스',
    # status: 노드/콘솔 창 상태판. 옆에 띄워 두고 보는 용도라 창을 작게 잡는다.
    'status': '바이브 코딩 - 상태판',
}
if TAB == 'office':
    DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?page=office"
elif TAB == 'status':
    DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?page=status"
else:
    DASHBOARD_URL = f"http://localhost:{HTTP_PORT}/?page=dashboard&tab={quote(TAB)}"


def _fetch_project_name() -> str:
    """서버 API에서 현재 프로젝트명을 가져온다. 실패 시 빈 문자열 반환.

    timeout을 0.5초로 짧게 잡아 서버가 느려도 UI 표시가 지연되지 않도록 한다.
    저장 경로 격리를 위해 프로필 생성 전에 프로젝트명이 필요하므로 동기 호출 유지.
    """
    try:
        with urlopen(f"http://localhost:{HTTP_PORT}/api/project-info", timeout=0.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('project_name', '')
    except Exception:
        return ''


class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # 프로젝트명을 서버에서 동적으로 가져와 타이틀에 반영 (0.5s 타임아웃)
        base_title = TITLE_MAP.get(TAB, TITLE_MAP['agent'])
        project_name = _fetch_project_name()
        title = f"{base_title} [{project_name}]" if project_name else base_title
        self.setWindowTitle(title)
        # 상태판은 곁눈질용 보조 창이라 좁고 길게 — 세컨 모니터 가장자리에 두기 좋은 비율.
        if TAB == 'office':
            w, h = 1440, 860
        elif TAB == 'status':
            w, h = 720, 900
        else:
            w, h = 1400, 900
        self.resize(w, h)

        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - w) // 2
        y = (screen.height() - h) // 2
        self.move(x, y)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.webview = QWebEngineView()

        # ── 영구 저장 프로필 — localStorage/쿠키/캐시가 재실행 후에도 유지되도록 경로 고정 ──
        # 프로필 이름과 저장 경로를 TAB별로 분리해야 classic과 office 창이 동시에 떠도
        # Chromium 캐시/IndexedDB lock 경합이 발생하지 않는다.
        # 또한 QWebEngineProfile의 parent는 반드시 self(MainWindow)여야 한다.
        # webview를 parent로 두면 종료 시 profile이 page보다 먼저 파괴되어 수명 역전으로
        # Qt가 크래시/강제 종료됨 (Qt 공식 규칙: profile must outlive page).
        storage_path = _resolve_qt_storage_path(project_name, TAB)
        profile_name = f"vibe-{TAB}-{project_name or 'default'}"
        self._profile = QWebEngineProfile(profile_name, self)
        self._profile.setPersistentStoragePath(str(storage_path))
        self._profile.setCachePath(str(storage_path / 'cache'))
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        # Qt 페이지에 프로필 연결 — page의 parent도 self로 두어 명시적 수명 관리
        self._page = QWebEnginePage(self._profile, self)
        self.webview.setPage(self._page)
        print(f"[dashboard_window] Qt storage: {storage_path}")

        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
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
