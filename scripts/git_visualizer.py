"""
FILE: scripts/git_visualizer.py
DESCRIPTION: 에이전트가 현재 Git 워크트리, 브랜치 상태 및 최근 이력을 한눈에 파악하게 돕는 시각화 도구.
             RULES.md의 'Git Worktree 강제' 규칙 준수 여부를 확인하는 데 활용됨.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 워크트리 리스트 및 브랜치 요약 기능 구현.
"""

import subprocess
import os
import sys
from pathlib import Path

def run_git(args):
    try:
        result = subprocess.run(['git'] + args, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

def get_worktrees():
    output = run_git(['worktree', 'list'])
    lines = output.split('\n')
    worktrees = []
    for line in lines:
        if line:
            parts = line.split()
            path = parts[0]
            commit = parts[1]
            branch = parts[2] if len(parts) > 2 else "(no branch)"
            worktrees.append({"path": path, "commit": commit, "branch": branch.strip('[]')})
    return worktrees

def get_recent_commits(n=5):
    return run_git(['log', '-n', str(n), '--oneline', '--graph', '--decorate'])

def visualize():
    print("\n=== [하이브 마인드 Git 상태 리포트] ===")
    
    # 1. 현재 브랜치 및 상태
    current_branch = run_git(['branch', '--show-current'])
    status_short = run_git(['status', '--short'])
    print(f"📍 현재 위치: {current_branch if current_branch else '(분리된 HEAD)'}")
    if status_short:
        print("⚠️ 변경 사항이 있습니다:")
        print(status_short)
    else:
        print("✅ 작업 디렉토리가 깨끗합니다.")

    # 2. 워크트리 현황 (RULES.md 준수 확인용)
    print("\n🏗️ 활성 워크트리 (Worktrees):")
    worktrees = get_worktrees()
    for wt in worktrees:
        is_current = " <--- (현재)" if os.path.abspath(wt['path']) == os.path.abspath(os.getcwd()) else ""
        print(f" - [{wt['branch']}] {wt['path']}{is_current}")

    # 3. 최근 커밋 이력
    print("\n📜 최근 커밋 이력:")
    print(get_recent_commits())
    
    print("======================================\n")

if __name__ == "__main__":
    visualize()
