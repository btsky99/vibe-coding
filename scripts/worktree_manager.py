# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/worktree_manager.py
# 📝 설명: Git Worktree 격리 관리자 — Harness 방식 병렬 에이전트 격리 구현.
#          각 터미널 에이전트(T1~T8)가 독립된 Git worktree에서 작업하여
#          파일 충돌을 구조적으로 0%로 만드는 핵심 인프라.
#
# 사용법:
#   python scripts/worktree_manager.py setup T1          # T1 worktree 생성
#   python scripts/worktree_manager.py setup --all       # T1~T8 전체 생성
#   python scripts/worktree_manager.py status            # 모든 worktree 상태 확인
#   python scripts/worktree_manager.py cleanup T3        # T3 worktree 제거
#   python scripts/worktree_manager.py cleanup --all     # 전체 제거
#   python scripts/worktree_manager.py path T2           # T2의 worktree 경로 출력
#
# REVISION HISTORY:
# [2026-03-07] Claude: [신규] Harness Git Worktree 격리 구현 (Feature #1)
#   - 에이전트별 독립 worktree 생성/삭제/조회 기능
#   - worktree 상태를 .ai_monitor/data/worktree_state.json 에 영속화
#   - hive_bridge 연동으로 생성/삭제 이벤트 로깅
# ------------------------------------------------------------------------

import sys
import os
import io
import json
import argparse
import subprocess
from datetime import datetime

# Windows 터미널 한글/이모지 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ─── 경로 상수 ────────────────────────────────────────────────────────────────
PROJECT_ROOT   = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA_DIR       = os.path.join(PROJECT_ROOT, '.ai_monitor', 'data')
STATE_FILE     = os.path.join(DATA_DIR, 'worktree_state.json')
# worktree 저장 위치: 프로젝트 부모 폴더 아래 vibe-wt/ 디렉터리
WT_BASE        = os.path.normpath(os.path.join(PROJECT_ROOT, '..', 'vibe-wt'))

# 지원하는 터미널 슬롯 목록
ALL_SLOTS = [f'T{i}' for i in range(1, 9)]


# ─── 상태 파일 헬퍼 ───────────────────────────────────────────────────────────

def _load_state() -> dict:
    """worktree_state.json 로드 — 없으면 빈 dict 반환"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    """worktree_state.json 저장"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Git 헬퍼 ─────────────────────────────────────────────────────────────────

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

def _git(args: list, cwd: str = None) -> tuple[int, str, str]:
    """git 명령 실행 — (returncode, stdout, stderr) 반환"""
    cmd = ['git'] + args
    result = subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=_NO_WINDOW
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_branch() -> str:
    """현재 브랜치명 반환 (실패 시 'main')"""
    rc, out, _ = _git(['rev-parse', '--abbrev-ref', 'HEAD'])
    return out if rc == 0 and out else 'main'


def _worktree_exists_in_git(path: str) -> bool:
    """git worktree list 에서 해당 경로가 존재하는지 확인"""
    rc, out, _ = _git(['worktree', 'list', '--porcelain'])
    if rc != 0:
        return False
    # 경로 구분자 통일 후 비교
    norm_path = os.path.normpath(path).lower()
    for line in out.splitlines():
        if line.startswith('worktree '):
            listed = os.path.normpath(line[9:].strip()).lower()
            if listed == norm_path:
                return True
    return False


# ─── hive_bridge 로깅 (선택적 연동) ──────────────────────────────────────────

def _log_event(event: str, slot: str, path: str) -> None:
    """worktree 생성/삭제 이벤트를 hive_bridge로 로깅 (없으면 조용히 스킵)"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hive_bridge
        hive_bridge.log_action(
            agent='claude',
            action=f'worktree:{event}',
            detail=f'[{slot}] {path}',
            skill='worktree_manager'
        )
    except Exception:
        pass


# ─── 핵심 기능 ────────────────────────────────────────────────────────────────

def setup_worktree(slot: str, branch: str = None) -> dict:
    """
    지정된 슬롯(T1~T8)에 Git worktree를 생성합니다.

    동작:
    1. 슬롯에 대응하는 브랜치명 결정 (예: wt/T1)
    2. 해당 브랜치가 없으면 현재 브랜치에서 분기 생성
    3. WT_BASE/T1/ 경로에 worktree 생성
    4. worktree_state.json 에 상태 기록

    반환: {'slot', 'path', 'branch', 'status'}
    """
    slot = slot.upper()
    if slot not in ALL_SLOTS:
        return {'error': f'알 수 없는 슬롯: {slot}. T1~T8 중 하나여야 합니다.'}

    wt_path   = os.path.join(WT_BASE, slot)
    wt_branch = branch or f'wt/{slot.lower()}'

    state = _load_state()

    # 이미 존재하면 상태만 반환
    if slot in state and os.path.exists(state[slot]['path']):
        if _worktree_exists_in_git(state[slot]['path']):
            print(f'[Worktree] {slot} 이미 존재: {state[slot]["path"]}')
            return state[slot]

    # worktree 저장 디렉터리 준비
    os.makedirs(WT_BASE, exist_ok=True)

    # 브랜치 존재 여부 확인
    rc, _, _ = _git(['rev-parse', '--verify', wt_branch])
    if rc != 0:
        # 브랜치가 없으면 현재 HEAD에서 새 브랜치 생성 후 worktree 연결
        rc2, out2, err2 = _git(['worktree', 'add', '-b', wt_branch, wt_path])
    else:
        # 브랜치가 이미 있으면 그 브랜치를 worktree로 체크아웃
        rc2, out2, err2 = _git(['worktree', 'add', wt_path, wt_branch])

    if rc2 != 0:
        print(f'[Worktree][오류] {slot} 생성 실패: {err2}')
        return {'error': err2}

    # .env 링크: 프로젝트 루트의 .env 파일이 있으면 worktree에 심볼릭링크
    _link_env_file(wt_path)

    entry = {
        'slot'      : slot,
        'path'      : wt_path,
        'branch'    : wt_branch,
        'created_at': datetime.now().isoformat(),
        'status'    : 'active'
    }
    state[slot] = entry
    _save_state(state)
    _log_event('created', slot, wt_path)

    print(f'[Worktree] {slot} 생성 완료 → {wt_path} (branch: {wt_branch})')
    return entry


def _link_env_file(wt_path: str) -> None:
    """프로젝트 루트 .env를 worktree에 심볼릭링크 (환경 설정 공유)"""
    src_env = os.path.join(PROJECT_ROOT, '.env')
    dst_env = os.path.join(wt_path, '.env')
    if os.path.exists(src_env) and not os.path.exists(dst_env):
        try:
            os.symlink(src_env, dst_env)
        except Exception:
            pass  # 권한 없거나 지원 안 하는 플랫폼이면 조용히 스킵


def cleanup_worktree(slot: str, force: bool = False) -> bool:
    """
    지정된 슬롯의 worktree를 제거합니다.

    force=True 이면 미커밋 변경사항이 있어도 강제 제거합니다.
    """
    slot = slot.upper()
    state = _load_state()

    if slot not in state:
        print(f'[Worktree] {slot} 상태 기록 없음 — 스킵')
        return False

    wt_path   = state[slot]['path']
    wt_branch = state[slot].get('branch', '')

    # git worktree remove
    args = ['worktree', 'remove', wt_path]
    if force:
        args.append('--force')
    rc, _, err = _git(args)

    if rc != 0 and not force:
        print(f'[Worktree][경고] {slot} 제거 실패 (미커밋 변경?): {err}')
        print(f'  강제 제거하려면: python scripts/worktree_manager.py cleanup {slot} --force')
        return False

    # worktree 브랜치 삭제 (wt/ 네임스페이스만 자동 정리)
    if wt_branch.startswith('wt/'):
        _git(['branch', '-D', wt_branch])

    del state[slot]
    _save_state(state)
    _log_event('removed', slot, wt_path)

    print(f'[Worktree] {slot} 제거 완료 ({wt_path})')
    return True


def status_all() -> list:
    """
    모든 worktree 상태를 출력합니다.
    활성 여부는 경로 존재 + git worktree list 교차 확인합니다.
    """
    state = _load_state()

    # git worktree list --porcelain 으로 실제 상태도 확인
    rc, raw, _ = _git(['worktree', 'list', '--porcelain'])
    git_paths = set()
    if rc == 0:
        for line in raw.splitlines():
            if line.startswith('worktree '):
                git_paths.add(os.path.normpath(line[9:].strip()).lower())

    print(f'\n{"슬롯":<6} {"경로":<45} {"브랜치":<20} {"상태":<10} {"생성일"}')
    print('─' * 100)

    results = []
    for slot in ALL_SLOTS:
        if slot in state:
            entry = state[slot]
            path  = entry.get('path', '')
            norm  = os.path.normpath(path).lower()
            alive = os.path.exists(path) and norm in git_paths
            status_str = 'active' if alive else 'stale'
            created = entry.get('created_at', '')[:19]
            print(f'{slot:<6} {path:<45} {entry.get("branch",""):<20} {status_str:<10} {created}')
            results.append({**entry, 'alive': alive})
        else:
            print(f'{slot:<6} {"(미생성)":<45} {"":<20} {"none":<10}')

    return results


def get_path(slot: str) -> str | None:
    """지정 슬롯의 worktree 경로 반환 (없으면 None)"""
    slot = slot.upper()
    state = _load_state()
    if slot in state:
        path = state[slot]['path']
        return path if os.path.exists(path) else None
    return None


# ─── CLI 진입점 ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Git Worktree 격리 관리자 — 에이전트별 독립 worktree 관리'
    )
    sub = parser.add_subparsers(dest='cmd')

    # setup
    p_setup = sub.add_parser('setup', help='worktree 생성')
    p_setup.add_argument('slot', nargs='?', help='슬롯 (예: T1)')
    p_setup.add_argument('--all', action='store_true', help='T1~T8 전체 생성')
    p_setup.add_argument('--branch', help='사용할 브랜치명 (기본: wt/t1)')

    # cleanup
    p_clean = sub.add_parser('cleanup', help='worktree 제거')
    p_clean.add_argument('slot', nargs='?', help='슬롯 (예: T1)')
    p_clean.add_argument('--all', action='store_true', help='전체 제거')
    p_clean.add_argument('--force', action='store_true', help='강제 제거')

    # status
    sub.add_parser('status', help='모든 worktree 상태 확인')

    # path
    p_path = sub.add_parser('path', help='특정 슬롯 경로 출력')
    p_path.add_argument('slot', help='슬롯 (예: T2)')

    args = parser.parse_args()

    if args.cmd == 'setup':
        if args.all:
            for slot in ALL_SLOTS:
                setup_worktree(slot, args.branch)
        elif args.slot:
            setup_worktree(args.slot, args.branch)
        else:
            parser.error('슬롯명(T1~T8) 또는 --all 이 필요합니다.')

    elif args.cmd == 'cleanup':
        if args.all:
            for slot in ALL_SLOTS:
                cleanup_worktree(slot, force=args.force)
        elif args.slot:
            cleanup_worktree(args.slot, force=args.force)
        else:
            parser.error('슬롯명 또는 --all 이 필요합니다.')

    elif args.cmd == 'status':
        status_all()

    elif args.cmd == 'path':
        path = get_path(args.slot)
        if path:
            print(path)
        else:
            print(f'[Worktree] {args.slot} worktree 없음', file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
