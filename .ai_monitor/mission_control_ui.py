# ------------------------------------------------------------------------
# 📄 파일명: mission_control_ui.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 미션 컨트롤의 사이드바 HUD UI 컴포넌트.
#          에이전트 상태 링 및 실시간 로그를 시각화합니다.
#          Codex 에이전트 링 및 NORMAL/YOLO 글로벌 모드 토글 포함.
#
# REVISION HISTORY:
# - 2026-03-07 Claude Sonnet 4.6: Codex 링, 모드 토글 위젯 추가 — Phase 5 Task 12
# - 2026-03-10 Claude Sonnet 4.6: KnowledgeGraphHUD 추가 — Phase 6 Task 17
#              shared_memory.db의 memory 테이블을 읽어 에이전트별 기억 노드를
#              태그 기반 연결선으로 이어주는 미니 지식 그래프 QPainter 렌더링.
# ------------------------------------------------------------------------

import sys
import json
import math
import sqlite3
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QFrame, QApplication, QPushButton)
from PySide6.QtGui import (QColor, QPainter, QBrush, QPen, QFont,
                           QLinearGradient, QPainterPath)
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve,
                            QRect, QTimer, Signal)

# 에이전트 런처 경로 (모드 저장/로드에 사용)
_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER = _ROOT / "scripts" / "agent_launcher.py"
_CONFIG = _ROOT / ".ai_monitor" / "config.json"
# 공유 메모리 DB 경로 (지식 그래프 데이터 소스)
_MEMORY_DB = _ROOT / ".ai_monitor" / "data" / "shared_memory.db"

# 에이전트별 색상 상수 (AgentRing과 통일)
_AGENT_COLORS: dict[str, str] = {
    "claude":  "#2ecc71",   # 초록
    "gemini":  "#3498db",   # 파랑
    "user":    "#e74c3c",   # 빨강
    "codex":   "#f39c12",   # 주황
}
_DEFAULT_NODE_COLOR = "#95a5a6"  # 회색 (미분류)


def _load_graph_data() -> tuple[list, list]:
    """shared_memory.db의 memory 테이블에서 지식 그래프 데이터를 로드합니다.

    [설계 의도] Task 17 — 하이브 기억 지식 그래프 시각화
    - 최신 24개 메모리 항목을 읽어 에이전트별로 클러스터링합니다.
    - 에이전트 클러스터를 원형으로 배치하고, 각 클러스터 내 노드도 서브 원형 배치합니다.
    - 동일 태그를 가진 노드 사이에 엣지(연결선)를 생성합니다.
      (엣지 과밀 방지를 위해 태그당 최대 3개 노드만 연결)

    Returns:
        nodes: [(x, y, label, color, size), ...]  — 정규화 좌표 (0~1)
        edges: [(x1, y1, x2, y2), ...]            — 정규화 좌표 (0~1)
    """
    try:
        conn = sqlite3.connect(str(_MEMORY_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 최신 24개만 조회 (성능 및 가독성)
        cur.execute("""
            SELECT key, title, author, tags
            FROM memory
            ORDER BY updated_at DESC
            LIMIT 24
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return [], []

    if not rows:
        return [], []

    # ── 에이전트별 그룹화 ──────────────────────────────────────────────
    # author 필드 예: "claude", "claude-code:terminal-1", "gemini", "user"
    # 첫 번째 세그먼트를 에이전트 식별자로 사용
    groups: dict[str, list] = {}
    for row in rows:
        agent = (row["author"] or "user").lower().split(":")[0]
        groups.setdefault(agent, []).append(row)

    # ── 레이아웃: 에이전트 클러스터를 캔버스 중앙 기준 원형 배치 ──────
    agent_list = list(groups.keys())
    n_agents   = len(agent_list)
    cx0, cy0   = 0.50, 0.48   # 전체 중심
    CLUSTER_R  = 0.30          # 클러스터 중심 간격 반경 (정규화)

    positions:  dict[str, tuple[float, float]] = {}
    color_map:  dict[str, str] = {}

    for i, agent in enumerate(agent_list):
        # 에이전트 클러스터 중심 (원형 배치)
        if n_agents == 1:
            acx, acy = cx0, cy0
        else:
            angle = (2 * math.pi * i / n_agents) - math.pi / 2
            acx = cx0 + CLUSTER_R * math.cos(angle)
            acy = cy0 + CLUSTER_R * math.sin(angle) * 0.65  # Y 압축 (와이드 캔버스)

        agent_nodes = groups[agent]
        n_nodes = len(agent_nodes)
        # 서브 클러스터 반경: 노드가 많을수록 넓게, 최대 0.14
        sub_r = min(0.14, 0.04 * n_nodes)

        for j, row in enumerate(agent_nodes):
            if n_nodes == 1:
                nx, ny = acx, acy
            else:
                sub_angle = (2 * math.pi * j / n_nodes)
                nx = acx + sub_r * math.cos(sub_angle)
                ny = acy + sub_r * math.sin(sub_angle) * 0.65

            # 경계 클램프 (패딩 고려)
            nx = max(0.06, min(0.94, nx))
            ny = max(0.06, min(0.94, ny))

            key = row["key"]
            positions[key] = (nx, ny)

            # 에이전트 색상 결정
            color = _DEFAULT_NODE_COLOR
            for prefix, clr in _AGENT_COLORS.items():
                if agent.startswith(prefix):
                    color = clr
                    break
            color_map[key] = color

    # ── 노드 리스트 구성 ──────────────────────────────────────────────
    nodes: list = []
    key_to_row = {row["key"]: row for row in rows}
    for key, (x, y) in positions.items():
        label = key.split(":")[-1][:8]   # key 마지막 세그먼트를 레이블로
        color = color_map[key]
        nodes.append((x, y, label, color, 5))

    # ── 엣지: 동일 태그를 공유하는 노드 연결 ─────────────────────────
    # 같은 #태그를 가진 노드끼리 엣지로 연결하여 지식의 흐름을 시각화합니다.
    tag_to_keys: dict[str, list[str]] = {}
    for row in rows:
        raw_tags = row["tags"] or ""
        # 태그 형식 처리: JSON 배열 또는 공백 구분 #태그 문자열 양쪽 지원
        try:
            tag_list = json.loads(raw_tags) if raw_tags.startswith("[") else []
        except Exception:
            tag_list = []
        if not tag_list:
            # 공백 구분 #태그 형식 파싱
            tag_list = [t.lstrip("#").strip() for t in raw_tags.split()]
        for tag in tag_list:
            tag = str(tag).lstrip("#").strip()
            if len(tag) > 2:  # 너무 짧은 태그(1~2글자) 제외
                tag_to_keys.setdefault(tag, []).append(row["key"])

    edges: list = []
    seen_pairs: set = set()
    for tag, keys in tag_to_keys.items():
        if len(keys) < 2:
            continue
        # 엣지 과밀 방지: 태그당 최대 3개 노드만 상호 연결
        for a in range(min(len(keys), 3)):
            for b in range(a + 1, min(len(keys), 3)):
                pair = tuple(sorted([keys[a], keys[b]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if keys[a] in positions and keys[b] in positions:
                    x1, y1 = positions[keys[a]]
                    x2, y2 = positions[keys[b]]
                    edges.append((x1, y1, x2, y2))

    return nodes, edges


class _GraphCanvas(QWidget):
    """지식 그래프를 QPainter로 렌더링하는 캔버스 위젯.

    [설계 의도] QWidget을 직접 상속하여 paintEvent를 오버라이드.
    외부 그래프 라이브러리 없이 QPainter만으로 노드/엣지를 그립니다.
    - 엣지: 반투명 회색-보라 선 (연결 관계 시각화)
    - 노드: 에이전트 색상의 글로우 원 + 내부 원
    - 레이블: 노드 하단 8pt 소형 텍스트 (key 마지막 세그먼트)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._nodes: list = []   # [(x, y, label, color, size), ...]
        self._edges: list = []   # [(x1, y1, x2, y2), ...]

    def set_graph(self, nodes: list, edges: list) -> None:
        """그래프 데이터를 갱신하고 다시 그립니다."""
        self._nodes = nodes
        self._edges = edges
        self.update()   # repaint 트리거

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # ── 엣지 그리기 (노드보다 먼저 — 노드가 위에 오도록) ──────────
        edge_pen = QPen(QColor(120, 100, 200, 70))
        edge_pen.setWidth(1)
        painter.setPen(edge_pen)
        painter.setBrush(Qt.NoBrush)
        for x1, y1, x2, y2 in self._edges:
            painter.drawLine(int(x1 * w), int(y1 * h),
                             int(x2 * w), int(y2 * h))

        # ── 노드 그리기 ────────────────────────────────────────────────
        font = painter.font()
        font.setPointSize(6)
        painter.setFont(font)

        for x, y, label, color, size in self._nodes:
            ax, ay = int(x * w), int(y * h)
            r = size

            # 글로우 효과 (바깥쪽 반투명 원)
            glow_color = QColor(color)
            glow_color.setAlpha(35)
            painter.setBrush(QBrush(glow_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(ax - r * 2, ay - r * 2, r * 4, r * 4)

            # 노드 본체
            painter.setBrush(QBrush(QColor(color)))
            border_pen = QPen(QColor(color).lighter(160))
            border_pen.setWidth(1)
            painter.setPen(border_pen)
            painter.drawEllipse(ax - r, ay - r, r * 2, r * 2)

            # 레이블 (노드 아래)
            painter.setPen(QColor(190, 190, 210, 170))
            painter.drawText(ax - 18, ay + r + 2, 36, 11,
                             Qt.AlignCenter, label)

        painter.end()


class KnowledgeGraphHUD(QFrame):
    """하이브 기억 지식 그래프 시각화 HUD 위젯.

    [설계 의도] Task 17 — 대시보드 사이드바에 에이전트 기억 관계망을 시각화.
    shared_memory.db의 최신 24개 memory 항목을 읽어:
      - 에이전트별 클러스터(Gemini=파랑, Claude=초록, user=빨강)로 노드를 구성
      - 동일 태그를 가진 노드 사이에 연결선(엣지)을 그어 지식 계보를 표현
    30초마다 자동 갱신됩니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedHeight(190)
        self.setStyleSheet("""
            background-color: rgba(12, 12, 22, 200);
            border-radius: 8px;
            border: 1px solid rgba(120, 80, 200, 50);
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(3)

        # 헤더 레이블
        header_row = QHBoxLayout()
        icon_label = QLabel("🧠")
        icon_label.setStyleSheet("font-size: 9pt;")
        title_label = QLabel("지식 그래프")
        title_label.setStyleSheet(
            "color: #9b59b6; font-size: 8pt; font-weight: bold;"
        )
        # 상태 레이블 (노드 수 표시)
        self.stat_label = QLabel("로딩 중...")
        self.stat_label.setStyleSheet("color: #7f8c8d; font-size: 7pt;")
        self.stat_label.setAlignment(Qt.AlignRight)
        header_row.addWidget(icon_label)
        header_row.addWidget(title_label)
        header_row.addStretch()
        header_row.addWidget(self.stat_label)
        layout.addLayout(header_row)

        # 그래프 캔버스
        self.canvas = _GraphCanvas()
        layout.addWidget(self.canvas)

        # 범례 (에이전트 색상 가이드)
        legend_row = QHBoxLayout()
        legend_row.setSpacing(8)
        for label, color in [("Gemini", "#3498db"), ("Claude", "#2ecc71"), ("User", "#e74c3c")]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 7pt;")
            txt = QLabel(label)
            txt.setStyleSheet("color: #7f8c8d; font-size: 6pt;")
            legend_row.addWidget(dot)
            legend_row.addWidget(txt)
        legend_row.addStretch()
        layout.addLayout(legend_row)

        # 30초 자동 갱신 타이머
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(30_000)
        self._refresh()  # 초기 로드

    def _refresh(self) -> None:
        """DB에서 최신 메모리를 읽어 그래프를 갱신합니다."""
        nodes, edges = _load_graph_data()
        self.canvas.set_graph(nodes, edges)
        self.stat_label.setText(f"{len(nodes)}노드 {len(edges)}엣지")

class AgentRing(QWidget):
    """CMUX 스타일의 에이전트 상태 링 위젯"""
    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.name = name
        self.color = QColor(color)
        self.setFixedSize(100, 100)
        self.angle = 0
        self.pulse = 0
        self.is_active = False
        
        # 애니메이션용 타이머
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)

    def set_active(self, active):
        self.is_active = active

    def update_animation(self):
        if self.is_active:
            self.angle = (self.angle + 5) % 360
            self.pulse = (self.pulse + 0.1) % (2 * math.pi)
        else:
            self.pulse = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center = self.rect().center()
        radius = 35 + (3 * math.sin(self.pulse) if self.is_active else 0)
        
        # 배경 원 (그림자/글로우 효과)
        glow_color = QColor(self.color)
        glow_color.setAlpha(50 if self.is_active else 20)
        painter.setBrush(QBrush(glow_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, radius + 5, radius + 5)
        
        # 메인 링
        pen = QPen(self.color)
        pen.setWidth(4)
        if not self.is_active:
            pen.setStyle(Qt.DotLine)
            pen.setColor(QColor(100, 100, 100, 100))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        
        if self.is_active:
            painter.drawArc(self.rect().adjusted(15, 15, -15, -15), self.angle * 16, 300 * 16)
        else:
            painter.drawEllipse(center, radius, radius)
            
        # 이름 텍스트
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, self.name.upper())

class DebateHUD(QFrame):
    """현재 진행 중인 하이브 토론 상태를 보여주는 HUD 위젯"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("debate_hud")
        self.hide() # 기본적으로 숨김
        
        self.setStyleSheet("""
            #debate_hud {
                background-color: rgba(52, 152, 219, 40);
                border: 1px solid #3498db;
                border-radius: 10px;
                margin: 5px;
                padding: 10px;
            }
            QLabel { color: #ecf0f1; font-family: 'Segoe UI'; }
            .topic { font-size: 11pt; font-weight: bold; color: #3498db; }
            .round { font-size: 9pt; color: #bdc3c7; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        header = QHBoxLayout()
        self.round_label = QLabel("ROUND 1")
        self.round_label.setProperty("class", "round")
        header.addWidget(self.round_label)
        
        self.status_label = QLabel("DEBATING...")
        self.status_label.setStyleSheet("color: #e67e22; font-weight: bold; font-size: 8pt;")
        self.status_label.setAlignment(Qt.AlignRight)
        header.addStretch()
        header.addWidget(self.status_label)
        layout.addLayout(header)
        
        self.topic_label = QLabel("Topic: Analyzing System...")
        self.topic_label.setProperty("class", "topic")
        self.topic_label.setWordWrap(True)
        layout.addWidget(self.topic_label)

    def update_debate(self, topic, round_num, status):
        self.topic_label.setText(f"Topic: {topic}")
        self.round_label.setText(f"ROUND {round_num}")
        self.status_label.setText(status.upper())
        self.show()

class LogEntry(QFrame):
    """사이드바의 개별 로그 항목"""
    def __init__(self, agent, text, msg_type="info", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        
        # 메시지 타입에 따른 색상 설정
        colors = {
            "info": "#3498db",      # Blue
            "proposal": "#2ecc71",  # Green
            "critique": "#e74c3c",  # Red
            "synthesis": "#9b59b6", # Purple
            "vote": "#f1c40f"       # Yellow
        }
        color = colors.get(msg_type, "#3498db")
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(45, 45, 45, 180);
                border-radius: 5px;
                padding: 5px;
                margin-bottom: 5px;
                border-left: 3px solid {color};
            }}
            QLabel {{ color: #ecf0f1; font-family: 'Consolas'; font-size: 10pt; }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        
        header = QLabel(f"[{agent.upper()}]" if msg_type == "info" else f"[{agent.upper()} / {msg_type.upper()}]")
        header.setStyleSheet(f"color: {color}; font-weight: bold;")
        layout.addWidget(header)
        
        content = QLabel(text)
        content.setWordWrap(True)
        layout.addWidget(content)

class ModeToggle(QWidget):
    """NORMAL / YOLO 글로벌 실행 모드 전환 위젯.

    Why: 사용자가 에이전트를 재시작하지 않고 UI에서 바로 모드를 전환할 수 있어야
         워크플로우가 끊기지 않습니다. 선택된 모드는 config.json에 즉시 저장됩니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 현재 저장된 모드 로드
        self._current_mode = self._load_mode()

        self.btn_normal = QPushButton("NORMAL")
        self.btn_yolo = QPushButton("YOLO")
        for btn in (self.btn_normal, self.btn_yolo):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(QFont("Segoe UI", 9, QFont.Bold))

        self.btn_normal.clicked.connect(lambda: self._set_mode("normal"))
        self.btn_yolo.clicked.connect(lambda: self._set_mode("yolo"))

        layout.addWidget(QLabel("모드:"))
        layout.addWidget(self.btn_normal)
        layout.addWidget(self.btn_yolo)

        self._refresh_style()

    def _load_mode(self) -> str:
        """config.json에서 agent_mode 읽기. 없으면 'normal'."""
        if _CONFIG.exists():
            try:
                with open(_CONFIG, "r", encoding="utf-8") as f:
                    return json.load(f).get("agent_mode", "normal")
            except Exception:
                pass
        return "normal"

    def _set_mode(self, mode: str) -> None:
        """모드를 config.json에 저장하고 UI 색상 갱신."""
        self._current_mode = mode
        # agent_launcher.py로 저장 (서브프로세스 호출)
        if _LAUNCHER.exists():
            subprocess.Popen(
                [sys.executable, str(_LAUNCHER), "--set-mode", mode],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        else:
            # 런처가 없으면 직접 파일 수정
            cfg: dict = {}
            if _CONFIG.exists():
                try:
                    with open(_CONFIG, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    pass
            cfg["agent_mode"] = mode
            _CONFIG.parent.mkdir(parents=True, exist_ok=True)
            with open(_CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        self._refresh_style()

    def _refresh_style(self) -> None:
        """현재 모드에 따라 버튼 강조 스타일 적용."""
        active = "background-color: #e74c3c; color: white; border-radius: 4px;" if self._current_mode == "yolo" else ""
        inactive = "background-color: #27ae60; color: white; border-radius: 4px;" if self._current_mode == "normal" else ""
        self.btn_normal.setStyleSheet(inactive or "background-color: #555; color: #aaa; border-radius: 4px;")
        self.btn_yolo.setStyleSheet(active or "background-color: #555; color: #aaa; border-radius: 4px;")


class MissionControlSidebar(QWidget):
    """슬라이드인 사이드바 HUD"""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 윈도우 크기 설정 (우측 사이드바)
        screen = QApplication.primaryScreen().geometry()
        self.w = 350
        self.h = screen.height() - 100
        self.setFixedSize(self.w, self.h)

        self.is_visible = False
        self.target_x = screen.width() - self.w - 20
        self.hidden_x = screen.width() + 10
        self.move(self.hidden_x, 50)

        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        # 배경 컨테이너
        self.container = QFrame()
        self.container.setObjectName("sidebar_container")
        self.container.setStyleSheet("""
            #sidebar_container {
                background-color: rgba(20, 20, 20, 220);
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
        """)
        self.main_layout.addWidget(self.container)

        self.content_layout = QVBoxLayout(self.container)

        # 상단 타이틀
        title = QLabel("MISSION CONTROL")
        title.setStyleSheet("color: #bdc3c7; font-size: 14pt; font-weight: bold; margin: 10px;")
        title.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(title)

        # 글로벌 모드 토글 (NORMAL / YOLO)
        # Why: 사이드바 최상단에 노출하여 현재 실행 모드를 항상 인지할 수 있게 합니다.
        self.mode_toggle = ModeToggle()
        self.content_layout.addWidget(self.mode_toggle)

        self.content_layout.addWidget(
            QFrame(frameShape=QFrame.HLine, styleSheet="background-color: rgba(255,255,255,20);")
        )

        # 에이전트 링 영역 — Gemini / Claude / Codex
        ring_layout = QHBoxLayout()
        self.gemini_ring = AgentRing("Gemini", "#3498db")
        self.claude_ring = AgentRing("Claude", "#2ecc71")
        # Codex 링: 주황색으로 구분 (OpenAI 브랜드 계열)
        self.codex_ring = AgentRing("Codex", "#f39c12")
        ring_layout.addWidget(self.gemini_ring)
        ring_layout.addWidget(self.claude_ring)
        ring_layout.addWidget(self.codex_ring)
        self.content_layout.addLayout(ring_layout)

        # 하이브 토론 HUD
        # Why: 토론이 활성화될 때만 나타나며, 현재 논의 중인 핵심 주제를 강조합니다.
        self.debate_hud = DebateHUD()
        self.content_layout.addWidget(self.debate_hud)

        self.content_layout.addWidget(
            QFrame(frameShape=QFrame.HLine, styleSheet="background-color: rgba(255,255,255,20);")
        )

        # 지식 그래프 HUD (Task 17)
        # Why: 에이전트들의 기억 항목을 시각적 그래프로 표현하여
        #      하이브의 지식 계보와 에이전트 간 협력 관계를 직관적으로 파악할 수 있게 합니다.
        self.graph_hud = KnowledgeGraphHUD()
        self.content_layout.addWidget(self.graph_hud)

        self.content_layout.addWidget(
            QFrame(frameShape=QFrame.HLine, styleSheet="background-color: rgba(255,255,255,20);")
        )

        # 로그 영역
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.log_container = QWidget()
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.log_container)
        self.content_layout.addWidget(self.scroll)

    def add_log(self, agent, text, msg_type="info"):
        entry = LogEntry(agent, text, msg_type)
        self.log_layout.insertWidget(0, entry)  # 최신 로그 상단 배치

        # 로그 개수 제한 (최신 30개)
        if self.log_layout.count() > 30:
            item = self.log_layout.takeAt(self.log_layout.count() - 1)
            if item.widget():
                item.widget().deleteLater()

    def update_status(self, status):
        """에이전트 상태 업데이트 (링 애니메이션).

        status 딕셔너리 예시:
            {"gemini": {"status": "active"}, "claude": {"status": "idle"}, "codex": {"status": "active"}}
        """
        def _is_active(name: str) -> bool:
            return status.get(name, {}).get("status") == "active"

        self.gemini_ring.set_active(_is_active("gemini"))
        self.claude_ring.set_active(_is_active("claude"))
        self.codex_ring.set_active(_is_active("codex"))

    def toggle(self):
        self.is_visible = not self.is_visible
        
        self.animation = QPropertyAnimation(self, b"pos")
        self.animation.setDuration(400)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        
        start_pos = self.pos()
        end_x = self.target_x if self.is_visible else self.hidden_x
        
        self.animation.setStartValue(start_pos)
        self.animation.setEndValue(QRect(end_x, 50, self.w, self.h).topLeft())
        
        if self.is_visible:
            self.show()
        self.animation.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    sidebar = MissionControlSidebar()
    sidebar.toggle()
    
    # 더미 데이터 테스트
    QTimer.singleShot(1000, lambda: sidebar.add_log("GEMINI", "분석을 시작합니다..."))
    QTimer.singleShot(2000, lambda: sidebar.update_status({"gemini": {"status": "active"}}))
    
    sys.exit(app.exec())
