import os
import sys

# 터미널 스타일 정의 (ANSI 256 Color)
class UI:
    BLUE = '\033[38;5;75m'
    PURPLE = '\033[38;5;141m'
    GREEN = '\033[38;5;114m'
    YELLOW = '\033[38;5;220m'
    RED = '\033[38;5;203m'
    GRAY = '\033[38;5;242m'
    WHITE = '\033[38;5;255m'
    BOLD = '\033[1m'
    END = '\033[0m'
    
    # 배경색
    BG_NAVY = '\033[48;5;23m'

def draw_dashboard():
    # 데이터 설정 (실제 상황에 맞게 조정 가능)
    total = 128000
    used = 45600
    i_tokens = 28000
    cw_tokens = 13200
    cr_tokens = 2500
    o_tokens = 8100
    free = total - used
    
    used_pct = (used / total) * 100
    
    # 화면 지우기 및 시작
    # os.system('cls' if os.name == 'nt' else 'clear')
    
    print(f"\n{UI.BG_NAVY}{UI.WHITE}{UI.BOLD}  📊 GEMINI CONTEXT MONITOR  {UI.END}")
    print(f"{UI.GRAY}──────────────────────────────────────────────────{UI.END}")
    
    # 1. 컨텍스트 사용량 (Progress Bar)
    print(f"\n{UI.BOLD}  컨텍스트 사용량{UI.END}")
    
    bar_width = 30
    filled = int(bar_width * used / total)
    
    # 그라데이션 색상 결정
    bar_color = UI.GREEN
    if used_pct > 60: bar_color = UI.YELLOW
    if used_pct > 85: bar_color = UI.RED
    
    bar = f"{bar_color}{'█' * filled}{UI.GRAY}{'░' * (bar_width - filled)}{UI.END}"
    print(f"  {bar}  {UI.BOLD}{used_pct:.1f}%{UI.END} {UI.GRAY}({used//1000}k / {total//1000}k){UI.END}")
    print(f"  {bar_color}{'█' * filled}{UI.GRAY}{'░' * (bar_width - filled)}{UI.END}")

    print(f"\n{UI.GRAY}──────────────────────────────────────────────────{UI.END}")
    
    # 2. 카테고리별 사용량
    print(f"{UI.BOLD}  카테고리별 사용량{UI.END}")
    
    def print_item(icon_color, label, value, total):
        pct = (value / total) * 100
        val_str = f"{value/1000:>5.1f}k"
        print(f"  {icon_color}■{UI.END} {UI.WHITE}{label:<10}{UI.END}: {UI.BLUE}{val_str}{UI.END} {UI.GRAY}({pct:>2.0f}%){UI.END}")

    print_item(UI.BLUE, "입력 토큰", i_tokens, total)
    print_item(UI.PURPLE, "캐시 쓰기", cw_tokens, total)
    print_item(UI.PURPLE, "캐시 읽기", cr_tokens, total)
    print_item(UI.YELLOW, "출력 누적", o_tokens, total)
    
    print(f"  {UI.GREEN}■{UI.END} {UI.GREEN}{UI.BOLD}{'여유 공간':<10}{UI.END}: {UI.GREEN}{free/1000:>5.1f}k{UI.END} {UI.GRAY}({(free/total)*100:>2.0f}%){UI.END}")
    
    print(f"{UI.GRAY}──────────────────────────────────────────────────{UI.END}")
    print(f"  {UI.GRAY}Tip: {UI.END}{UI.WHITE}/compress 명령어로 공간을 확보하세요.{UI.END}\n")

if __name__ == "__main__":
    draw_dashboard()
