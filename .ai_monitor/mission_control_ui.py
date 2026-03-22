"""
FILE: .ai_monitor/mission_control_ui.py
DESCRIPTION: 미션 컨트롤 사이드바 HUD UI 컴포넌트 — 에이전트 상태 링 및 실시간 로그 시각화.

REVISION HISTORY:
- 2026-03-07 Claude Sonnet 4.6: Codex 링, 모드 토글 위젯 추가 — Phase 5 Task 12
- 2026-03-22 Claude: KnowledgeGraphHUD 제거 (지식그래프 기능 삭제)
- 2026-03-19 Claude: 표준 헤더 형식 적용 + 레거시 shared_memory.db 주석 수정
"""

import sys
import json
import math
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


class AgentRing(QWidget):
    """CMUX 스타일의 에이전트 상태 링 위젯.

    [2026-03-18] Claude: cmux 3중 알림 체계 구현
    - flash_ring(): 파란색 테두리 2회 깜빡임 (200ms 간격) — cmux trigger-flash 미러
    - badge_count: 미읽음 알림 수 → 빨간 원형 배지 표시
    - progress_arc: 진행률 호(arc) 오버레이 — cmux set-progress 미러
    """
    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.name = name
        self.color = QColor(color)
        self.setFixedSize(100, 100)
        self.angle = 0
        self.pulse = 0
        self.is_active = False

        # P5: cmux 호환 알림 상태
        self._badge_count = 0        # 미읽음 알림 수
        self._progress_arc = -1.0    # 진행률 (0.0~1.0, -1이면 비표시)
        self._flash_alpha = 0        # 링 플래시 투명도 (0~255, 애니메이션용)
        self._flash_count = 0        # 남은 플래시 횟수

        # 애니메이션용 타이머
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)

        # P5: 링 플래시 타이머 (200ms 간격)
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._do_flash_step)

    def set_active(self, active):
        self.is_active = active

    def flash_ring(self):
        """파란색 테두리 2회 깜빡임 — cmux trigger-flash 미러.
        200ms on → 200ms off → 200ms on → 200ms off (총 800ms)
        """
        self._flash_count = 4  # 4 스텝 (on-off-on-off)
        self._flash_alpha = 255
        self._flash_timer.start(200)

    def _do_flash_step(self):
        """플래시 애니메이션의 한 스텝을 실행합니다."""
        self._flash_count -= 1
        if self._flash_count <= 0:
            self._flash_alpha = 0
            self._flash_timer.stop()
        else:
            # 홀수 스텝: on(255), 짝수 스텝: off(0)
            self._flash_alpha = 255 if (self._flash_count % 2 == 1) else 0
        self.update()

    def set_badge_count(self, count: int):
        """미읽음 알림 배지 수를 설정합니다."""
        self._badge_count = max(0, count)
        self.update()

    def set_progress(self, value: float):
        """진행률 호를 설정합니다. -1이면 비표시, 0.0~1.0이면 호 표시."""
        self._progress_arc = value
        self.update()

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

        # P5: 진행률 호 (progress arc) — 에이전트 링 바깥에 얇은 호로 표시
        if 0.0 <= self._progress_arc <= 1.0:
            progress_pen = QPen(QColor(46, 204, 113, 200))  # 초록색 반투명
            progress_pen.setWidth(3)
            painter.setPen(progress_pen)
            painter.setBrush(Qt.NoBrush)
            # 호 각도: 12시 방향(90°)에서 시계방향으로 진행률만큼
            span_angle = int(self._progress_arc * 360 * 16)
            start_angle = 90 * 16  # 12시 방향
            arc_rect = self.rect().adjusted(10, 10, -10, -10)
            painter.drawArc(arc_rect, start_angle, -span_angle)

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

        # P5: 링 플래시 오버레이 — 파란색 링이 깜빡이는 효과
        if self._flash_alpha > 0:
            flash_pen = QPen(QColor(52, 152, 219, self._flash_alpha))  # 파란색
            flash_pen.setWidth(6)
            painter.setPen(flash_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius + 2, radius + 2)

        # 이름 텍스트
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, self.name.upper())

        # P5: 미읽음 알림 배지 — 우상단 빨간 원 + 숫자
        if self._badge_count > 0:
            badge_x = self.width() - 22
            badge_y = 5
            badge_r = 10
            # 빨간 원
            painter.setBrush(QBrush(QColor(231, 76, 60)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(badge_x, badge_y, badge_r * 2, badge_r * 2)
            # 숫자
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            badge_text = str(self._badge_count) if self._badge_count < 100 else "99+"
            painter.drawText(badge_x, badge_y, badge_r * 2, badge_r * 2,
                             Qt.AlignCenter, badge_text)

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

    def _get_ring(self, agent: str):
        """에이전트 이름으로 AgentRing 위젯을 반환합니다."""
        name = agent.lower().split(':')[0].split('-')[0]
        if 'gemini' in name:
            return self.gemini_ring
        elif 'claude' in name:
            return self.claude_ring
        elif 'codex' in name:
            return self.codex_ring
        return None

    def flash_agent_ring(self, agent: str):
        """에이전트 링에 파란색 깜빡임 효과를 트리거합니다.
        cmux trigger-flash 미러.
        """
        ring = self._get_ring(agent)
        if ring:
            ring.flash_ring()
            # 배지 카운트 증가
            ring.set_badge_count(ring._badge_count + 1)

    def update_agent_progress(self, agent: str, value: float):
        """에이전트 링에 진행률 호를 표시합니다.
        cmux set-progress 미러. value=-1이면 비표시.
        """
        ring = self._get_ring(agent)
        if ring:
            ring.set_progress(value)

    def update_agent_status_field(self, agent: str, key: str, value: str):
        """에이전트 사이드바 상태 필드를 업데이트합니다.
        cmux set-status 미러. 현재는 로그로 표시.
        """
        self.add_log(agent, f"📊 {key}: {value}", "info")

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
