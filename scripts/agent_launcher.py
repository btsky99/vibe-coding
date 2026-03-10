"""
FILE: scripts/agent_launcher.py
DESCRIPTION: 통합 에이전트 런처.
             claude, codex, vibe-coding 에이전트를 NORMAL / YOLO 두 가지
             실행 모드로 기동하는 단일 진입점입니다.
             설정 파일(.ai_monitor/config.json)에 현재 모드를 저장하여
             대시보드와 배치 파일이 일관된 모드로 동작하게 합니다.

REVISION HISTORY:
- 2026-03-07 Claude Sonnet 4.6: 최초 생성 — Phase 5 Task 11
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# 프로젝트 루트 = 이 파일 부모의 부모
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / ".ai_monitor" / "config.json"

# 에이전트별 실행 명령 정의
# Why: 각 에이전트마다 YOLO(자율) 모드 플래그가 다르므로 매핑 테이블로 관리합니다.
AGENT_CMDS: dict[str, dict[str, list[str]]] = {
    "claude": {
        "normal": ["claude"],
        "yolo": ["claude", "--dangerously-skip-permissions"],
    },
    "codex": {
        "normal": ["codex"],
        "yolo": ["codex", "--yolo"],
    },
    "vibe": {
        # vibe-coding은 pythonw로 서버를 백그라운드에 띄우는 방식
        "normal": [
            str(ROOT / ".ai_monitor" / "venv" / "Scripts" / "python.exe"),
            str(ROOT / ".ai_monitor" / "server.py"),
        ],
        "yolo": [
            str(ROOT / ".ai_monitor" / "venv" / "Scripts" / "python.exe"),
            str(ROOT / ".ai_monitor" / "server.py"),
            "--auto",
        ],
    },
}


def load_config() -> dict:
    """현재 설정(모드 등)을 config.json에서 읽어 반환."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict) -> None:
    """변경된 설정을 config.json에 영속 저장."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def set_mode(mode: str) -> None:
    """전역 실행 모드(normal/yolo)를 설정 파일에 저장.

    Why: 모드는 에이전트 재시작 사이에도 유지되어야 하므로
         파일 기반 영속 저장이 필요합니다.
    """
    cfg = load_config()
    cfg["agent_mode"] = mode
    save_config(cfg)
    print(f"[모드 변경] agent_mode = {mode.upper()}")


def get_mode() -> str:
    """저장된 모드를 반환. 없으면 기본값 'normal'."""
    return load_config().get("agent_mode", "normal")


def launch(agent: str, mode: str, extra_args: list[str]) -> None:
    """지정된 에이전트를 해당 모드로 실행.

    Args:
        agent: 'claude' | 'codex' | 'vibe'
        mode:  'normal' | 'yolo'
        extra_args: 명령줄에서 추가로 전달된 인자
    """
    agent = agent.lower()
    mode = mode.lower()

    if agent not in AGENT_CMDS:
        print(f"[오류] 알 수 없는 에이전트: {agent}")
        print(f"  사용 가능: {', '.join(AGENT_CMDS.keys())}")
        sys.exit(1)

    if mode not in ("normal", "yolo"):
        print(f"[오류] 알 수 없는 모드: {mode}. 'normal' 또는 'yolo'를 사용하세요.")
        sys.exit(1)

    # 모드 영속 저장
    set_mode(mode)

    # 하이브 토론 컨텍스트 주입
    # Why: 진행 중인 토론이 있다면 에이전트가 이를 인지하고 첫 마디부터 토론에 참여하게 합니다.
    try:
        from scripts.hive_bridge import get_active_debate_context
        debate_json = get_active_debate_context()
        if debate_json:
            os.environ["HIVE_DEBATE_CONTEXT"] = debate_json
            print(f"[HIVE] Debate context injected for {agent.upper()}")
    except Exception as e:
        print(f"[HIVE] Failed to fetch debate context: {e}")

    # 중첩 세션 방지: CLAUDE 관련 환경 변수 제거
    # Why: Gemini CLI 등에서 실행 시 상속된 변수가 Claude Code의 중첩 실행 방지 로직을 트리거함.
    claude_vars = [k for k in os.environ.keys() if "CLAUDE" in k.upper()]
    if claude_vars:
        for k in claude_vars:
            del os.environ[k]

    cmd = AGENT_CMDS[agent][mode] + extra_args
    print(f"[실행] {agent.upper()} / {mode.upper()} 모드")
    print(f"  명령: {' '.join(cmd)}")

    # Codex는 TUI 스피너가 터미널 너비만큼 렌더링하므로
    # 창이 좁으면 줄 바꿈 + 덮어쓰기로 출력이 깨짐.
    # Windows에서 mode con으로 터미널 너비를 220으로 늘려 예방합니다.
    if agent == "codex" and sys.platform == "win32":
        os.system("mode con cols=220")
        os.environ["COLUMNS"] = "220"

    # 에이전트 프로세스 실행 (현재 터미널에서 대화형)
    os.execvp(cmd[0], cmd)  # execvp: 현재 프로세스를 대체하여 실행


def main():
    parser = argparse.ArgumentParser(
        description="Vibe Coding 통합 에이전트 런처",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python agent_launcher.py claude normal
  python agent_launcher.py claude yolo
  python agent_launcher.py codex yolo
  python agent_launcher.py vibe normal
  python agent_launcher.py --set-mode yolo   # 모드만 저장
  python agent_launcher.py --show-mode        # 현재 모드 출력
        """,
    )
    parser.add_argument(
        "agent",
        nargs="?",
        choices=list(AGENT_CMDS.keys()),
        help="실행할 에이전트 (claude | codex | vibe)",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["normal", "yolo"],
        help="실행 모드 (normal | yolo). 생략 시 저장된 모드 사용.",
    )
    parser.add_argument(
        "--set-mode",
        metavar="MODE",
        choices=["normal", "yolo"],
        help="에이전트를 실행하지 않고 모드만 저장합니다.",
    )
    parser.add_argument(
        "--show-mode",
        action="store_true",
        help="현재 저장된 모드를 출력합니다.",
    )

    # 알려지지 않은 인자는 에이전트에게 그대로 전달
    args, extra_args = parser.parse_known_args()

    if args.show_mode:
        print(f"현재 모드: {get_mode().upper()}")
        return

    if args.set_mode:
        set_mode(args.set_mode)
        return

    if not args.agent:
        parser.print_help()
        sys.exit(1)

    resolved_mode = args.mode or get_mode()
    launch(args.agent, resolved_mode, extra_args)


if __name__ == "__main__":
    main()
