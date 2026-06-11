# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/agent_detector.py
# 📝 설명: 시스템에서 실행 중인 AI 코딩 에이전트를 자동 감지하는 모듈.
#          cmux의 AgentDetector.cs를 Python(psutil)으로 포팅.
#
#          [감지 전략 2가지]
#          1. 프로세스 트리 탐색: psutil로 자식 프로세스 이름에서 에이전트 시그니처 매칭
#          2. 환경변수 기반: TERMINAL_ID, CMUX_SURFACE_ID 등으로 에이전트 식별
#
#          [지원 에이전트]
#          - Claude Code (claude, claude-code)
#          - Codex (codex)
#          - Antigravity CLI (antigravity)
#          - Aider (aider)
#          - GitHub Copilot (copilot)
#          - Cursor (cursor)
#          - Windsurf (windsurf, cline)
#
# REVISION HISTORY:
# [2026-03-18] Claude: 최초 구현 — cmux AgentDetector.cs 기반 Python 포팅
#   - psutil 프로세스 트리 탐색으로 에이전트 감지
#   - detect_from_pid(): 특정 PID 자식에서 에이전트 탐지
#   - detect_all_agents(): 시스템 전체 활성 에이전트 목록
#   - 환경변수 TERMINAL_ID 기반 감지 병행
# ------------------------------------------------------------------------
"""

import os
import sys
from typing import Optional

# psutil 임포트 — 없으면 기본 감지만 사용
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ── 에이전트 시그니처 테이블 ─────────────────────────────────────────────
# cmux AgentDetector.cs의 AgentType enum + 프로세스 이름 패턴 매핑
# 키: 프로세스 이름에 포함되는 문자열 (소문자), 값: 에이전트 타입명
AGENT_SIGNATURES: dict[str, str] = {
    'claude': 'ClaudeCode',
    'codex': 'Codex',
    'antigravity': 'Antigravity',
    'aider': 'Aider',
    'copilot': 'GithubCopilot',
    'cursor': 'Cursor',
    'cline': 'Cline',
    'windsurf': 'Windsurf',
}


def detect_from_pid(pid: int) -> Optional[str]:
    """주어진 PID의 자식 프로세스에서 AI 에이전트를 감지합니다.

    cmux AgentDetector.cs의 GetChildProcessNames + 패턴 매칭 로직을 포팅.
    psutil.Process(pid).children(recursive=True)로 전체 자식 프로세스를 탐색하고,
    각 자식의 이름에서 AGENT_SIGNATURES 키를 매칭합니다.

    Args:
        pid: 셸(bash/cmd/powershell) 프로세스 ID

    Returns:
        에이전트 타입명 (예: 'ClaudeCode') 또는 None
    """
    if not _HAS_PSUTIL:
        return None

    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                name = child.name().lower()
                for pattern, agent_type in AGENT_SIGNATURES.items():
                    if pattern in name:
                        return agent_type
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return None


def detect_all_agents() -> list[dict]:
    """시스템 전체에서 실행 중인 모든 AI 코딩 에이전트를 탐지합니다.

    [설계 의도] 두 가지 전략을 병행하여 누락 없이 감지:
    1. psutil로 모든 프로세스를 순회하며 에이전트 시그니처 매칭
    2. 환경변수 TERMINAL_ID가 설정된 프로세스 감지 (하이브 시스템 연동)

    Returns:
        감지된 에이전트 리스트. 각 항목:
        {
            'agent_type': str,   # 'ClaudeCode', 'Codex' 등
            'pid': int,          # 에이전트 프로세스 PID
            'name': str,         # 프로세스 이름
            'cwd': str | None,   # 작업 디렉토리
            'parent_pid': int,   # 부모 프로세스 PID
            'create_time': float # 프로세스 생성 시간 (epoch)
        }
    """
    agents: list[dict] = []
    seen_pids: set[int] = set()

    if not _HAS_PSUTIL:
        # psutil 없으면 환경변수 기반 감지만 시도
        terminal_id = os.environ.get('TERMINAL_ID', '')
        if terminal_id:
            # TERMINAL_ID 포맷: "claude-T1", "antigravity-T2" 등
            for pattern, agent_type in AGENT_SIGNATURES.items():
                if pattern in terminal_id.lower():
                    agents.append({
                        'agent_type': agent_type,
                        'pid': os.getpid(),
                        'name': terminal_id,
                        'cwd': os.getcwd(),
                        'parent_pid': os.getppid(),
                        'create_time': 0,
                    })
                    break
        return agents

    # psutil 전체 프로세스 스캔
    for proc in psutil.process_iter(['pid', 'name', 'ppid', 'cwd', 'create_time']):
        try:
            info = proc.info
            name = (info.get('name') or '').lower()

            for pattern, agent_type in AGENT_SIGNATURES.items():
                if pattern in name and info['pid'] not in seen_pids:
                    seen_pids.add(info['pid'])

                    # cwd 조회 (AccessDenied 가능)
                    cwd = None
                    try:
                        cwd = info.get('cwd') or proc.cwd()
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    agents.append({
                        'agent_type': agent_type,
                        'pid': info['pid'],
                        'name': info.get('name', ''),
                        'cwd': cwd,
                        'parent_pid': info.get('ppid', 0),
                        'create_time': info.get('create_time', 0),
                    })
                    break  # 하나의 프로세스에 하나의 에이전트만 매칭
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return agents


def detect_from_env() -> Optional[str]:
    """환경변수에서 현재 터미널의 에이전트 타입을 감지합니다.

    하이브 시스템이 설정하는 TERMINAL_ID 환경변수를 읽어
    에이전트 타입을 추론합니다.

    Returns:
        에이전트 타입명 또는 None
    """
    terminal_id = os.environ.get('TERMINAL_ID', '')
    if not terminal_id:
        return None

    for pattern, agent_type in AGENT_SIGNATURES.items():
        if pattern in terminal_id.lower():
            return agent_type

    return None


# ── CLI 테스트용 ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=== 에이전트 감지 테스트 ===")
    print(f"psutil 사용 가능: {_HAS_PSUTIL}")

    # 환경변수 기반 감지
    env_agent = detect_from_env()
    print(f"환경변수 감지: {env_agent or '없음'}")

    # 현재 프로세스 기반 감지
    current_pid = os.getpid()
    pid_agent = detect_from_pid(current_pid)
    print(f"현재 PID({current_pid}) 자식 감지: {pid_agent or '없음'}")

    # 전체 시스템 스캔
    all_agents = detect_all_agents()
    print(f"\n시스템 전체 활성 에이전트: {len(all_agents)}개")
    for a in all_agents:
        print(f"  - [{a['agent_type']}] PID={a['pid']} name={a['name']} cwd={a['cwd']}")
