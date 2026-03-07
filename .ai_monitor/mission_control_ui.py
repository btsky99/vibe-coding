# ------------------------------------------------------------------------
# 📄 파일명: mission_control_ui.py
# 🗺️ 메인 프로젝트 맵: PROJECT_MAP.md
# 📝 설명: 미션 컨트롤의 사이드바 HUD UI 컴포넌트.
#          에이전트 상태 링 및 실시간 로그를 시각화합니다.
# ------------------------------------------------------------------------

import sys
import json
import math
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QScrollArea, QFrame, QApplication)
from PySide6.QtGui import (QColor, QPainter, QBrush, QPen, QFont, 
                         QLinearGradient, QPainterPath)
from PySide6.QtCore import (Qt, QPropertyAnimation, QEasingCurve, 
                          QRect, QTimer, Signal)

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

class LogEntry(QFrame):
    """사이드바의 개별 로그 항목"""
    def __init__(self, agent, text, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(45, 45, 45, 180);
                border-radius: 5px;
                padding: 5px;
                margin-bottom: 5px;
                border-left: 3px solid #3498db;
            }
            QLabel { color: #ecf0f1; font-family: 'Consolas'; font-size: 10pt; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        
        header = QLabel(f"[{agent}]")
        header.setStyleSheet("color: #3498db; font-weight: bold;")
        layout.addWidget(header)
        
        content = QLabel(text)
        content.setWordWrap(True)
        layout.addWidget(content)

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
        
        # 에이전트 링 영역
        ring_layout = QHBoxLayout()
        self.gemini_ring = AgentRing("Gemini", "#3498db")
        self.claude_ring = AgentRing("Claude", "#2ecc71")
        ring_layout.addWidget(self.gemini_ring)
        ring_layout.addWidget(self.claude_ring)
        self.content_layout.addLayout(ring_layout)
        
        self.content_layout.addWidget(QFrame(frameShape=QFrame.HLine, styleSheet="background-color: rgba(255,255,255,20)"))
        
        # 로그 영역
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.log_container = QWidget()
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.log_container)
        self.content_layout.addWidget(self.scroll)

    def add_log(self, agent, text):
        entry = LogEntry(agent, text)
        self.log_layout.insertWidget(0, entry) # 최신 로그 상단 배치
        
        # 로그 개수 제한 (최신 30개)
        if self.log_layout.count() > 30:
            item = self.log_layout.takeAt(self.log_layout.count() - 1)
            if item.widget():
                item.widget().deleteLater()

    def update_status(self, status):
        """에이전트 상태 업데이트 (링 애니메이션)"""
        self.gemini_ring.set_active("gemini" in [a.lower() for a in status.keys()] and status.get("gemini", {}).get("status") == "active")
        self.claude_ring.set_active("claude" in [a.lower() for a in status.keys()] and status.get("claude", {}).get("status") == "active")

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
