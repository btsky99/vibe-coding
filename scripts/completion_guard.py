# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/completion_guard.py
# 📝 설명: 서브에이전트 완료 신호 자동 감지기 — Harness `{"continue": false}` 패턴 구현.
#
#          에이전트가 할당된 작업을 마쳤을 때 무한히 새 작업을 요청하는 대신
#          `{"continue": false}` 신호를 출력/기록하고 루프를 자동 종료합니다.
#
# 두 가지 사용 방식:
#   (A) 에이전트 출력 감시 모드 — 다른 프로세스의 출력을 파이프로 받아 신호 감지
#       echo '{"continue": false}' | python scripts/completion_guard.py watch
#
#   (B) 태스크 완료 신호 전송 모드 — 에이전트가 작업 완료 후 직접 호출
#       python scripts/completion_guard.py done --slot T1 --task-id "abc123" --summary "로그인 버그 수정 완료"
#
#   (C) 상태 조회 모드 — 슬롯이 완료 신호를 보냈는지 확인
#       python scripts/completion_guard.py check --slot T1
#
#   (D) 리셋 모드 — 새 작업 시작 전 완료 신호 초기화
#       python scripts/completion_guard.py reset --slot T1
#
# REVISION HISTORY:
# [2026-03-07] Claude: [신규] Harness completion guard 구현 (Feature #3)
#   - {"continue": false} 패턴 감지 및 에이전트 루프 자동 종료
#   - 완료 신호를 .ai_monitor/data/completion_signals.json 에 영속화
#   - hive_bridge 연동으로 완료 이벤트 로깅
# ------------------------------------------------------------------------

import sys
import os
import io
import json
import argparse
import re
from datetime import datetime

# Windows 터미널 한글/이모지 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ─── 경로 상수 ────────────────────────────────────────────────────────────────
PROJECT_ROOT  = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA_DIR      = os.path.join(PROJECT_ROOT, '.ai_monitor', 'data')
SIGNALS_FILE  = os.path.join(DATA_DIR, 'completion_signals.json')

# 완료 신호로 인식하는 패턴 목록 (대소문자 무관)
# Harness 방식 + Vibe 방식 모두 지원
COMPLETION_PATTERNS = [
    # JSON 신호 패턴
    r'\{[^}]*"continue"\s*:\s*false[^}]*\}',   # {"continue": false}
    r'\{[^}]*"done"\s*:\s*true[^}]*\}',         # {"done": true}
    r'\{[^}]*"finished"\s*:\s*true[^}]*\}',     # {"finished": true}
    r'\{[^}]*"completed"\s*:\s*true[^}]*\}',    # {"completed": true}
    # 텍스트 신호 패턴 (에이전트 출력 텍스트)
    r'\[완료\]\s*모든\s*태스크\s*완료',
    r'TASK_COMPLETE',
    r'ALL_DONE',
    r'작업\s*완료[.!。]?\s*$',
]

_COMPILED = [re.compile(p, re.IGNORECASE | re.UNICODE) for p in COMPLETION_PATTERNS]


# ─── 상태 파일 헬퍼 ───────────────────────────────────────────────────────────

def _load_signals() -> dict:
    """completion_signals.json 로드"""
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_signals(signals: dict) -> None:
    """completion_signals.json 저장"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SIGNALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)


# ─── 완료 신호 감지 ───────────────────────────────────────────────────────────

def detect_completion(text: str) -> tuple[bool, str]:
    """
    텍스트에서 완료 신호를 감지합니다.

    반환: (is_complete, matched_pattern)
    """
    for pattern in _COMPILED:
        match = pattern.search(text)
        if match:
            return True, match.group(0)
    return False, ''


def _log_event(slot: str, task_id: str, summary: str) -> None:
    """완료 이벤트를 hive_bridge로 로깅 (없으면 조용히 스킵)"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hive_bridge
        hive_bridge.log_action(
            agent='claude',
            action='task:completed',
            detail=f'[{slot}] task={task_id} | {summary}',
            skill='completion_guard'
        )
    except Exception:
        pass


# ─── 주요 기능 ────────────────────────────────────────────────────────────────

def send_done_signal(slot: str, task_id: str = '', summary: str = '') -> None:
    """
    지정 슬롯에 완료 신호를 기록합니다.
    에이전트가 작업 완료 후 직접 호출하는 방식입니다.

    동작:
    - completion_signals.json 에 슬롯별 완료 상태 기록
    - hive_bridge 로 완료 이벤트 로깅
    - 표준 출력에 JSON 완료 신호 출력 (파이프라인 호환)
    """
    slot = slot.upper()
    signals = _load_signals()
    entry = {
        'slot'       : slot,
        'task_id'    : task_id,
        'summary'    : summary,
        'completed_at': datetime.now().isoformat(),
        'continue'   : False   # Harness 호환 필드
    }
    signals[slot] = entry
    _save_signals(signals)
    _log_event(slot, task_id, summary)

    # 표준 출력에 JSON 완료 신호 출력 — 파이프라인 상위에서 감지 가능
    print(json.dumps({'continue': False, 'slot': slot, 'summary': summary}, ensure_ascii=False))
    print(f'[CompletionGuard] {slot} 완료 신호 전송 — {summary}', file=sys.stderr)


def check_done(slot: str) -> dict | None:
    """
    슬롯이 완료 신호를 보냈는지 확인합니다.

    반환: 완료 엔트리 dict (없거나 완료 안 했으면 None)
    """
    slot = slot.upper()
    signals = _load_signals()
    entry = signals.get(slot)
    if entry and not entry.get('continue', True):
        return entry
    return None


def reset_signal(slot: str) -> None:
    """슬롯의 완료 신호를 초기화합니다 (새 작업 시작 전 호출)."""
    slot = slot.upper()
    signals = _load_signals()
    if slot in signals:
        del signals[slot]
        _save_signals(signals)
        print(f'[CompletionGuard] {slot} 신호 초기화 완료')
    else:
        print(f'[CompletionGuard] {slot} 기록 없음 — 스킵')


def watch_stdin() -> int:
    """
    표준 입력(stdin)을 한 줄씩 읽으며 완료 신호를 감지합니다.
    완료 신호를 감지하면 exit code 0으로 종료,
    EOF까지 신호 없으면 exit code 1로 종료합니다.

    사용 예:
        some_agent_command | python scripts/completion_guard.py watch
    """
    print('[CompletionGuard] 입력 감시 시작 (Ctrl+C로 중단)', file=sys.stderr)
    for line in sys.stdin:
        line = line.rstrip()
        # 표준 출력으로 그대로 전달 (파이프 투명 통과)
        print(line)
        is_done, matched = detect_completion(line)
        if is_done:
            print(f'\n[CompletionGuard] 완료 신호 감지: {matched}', file=sys.stderr)
            return 0
    print('[CompletionGuard] EOF 도달 — 완료 신호 없음', file=sys.stderr)
    return 1


def status_all() -> None:
    """모든 슬롯의 완료 신호 상태를 출력합니다."""
    signals = _load_signals()
    if not signals:
        print('[CompletionGuard] 기록된 완료 신호 없음')
        return

    print(f'\n{"슬롯":<6} {"완료시각":<22} {"태스크ID":<20} {"요약"}')
    print('─' * 80)
    for slot, entry in sorted(signals.items()):
        if not entry.get('continue', True):
            print(f'{slot:<6} {entry.get("completed_at","")[:19]:<22} '
                  f'{entry.get("task_id","")[:19]:<20} {entry.get("summary","")}')


# ─── CLI 진입점 ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='서브에이전트 완료 신호(completion guard) 관리'
    )
    sub = parser.add_subparsers(dest='cmd')

    # done — 완료 신호 전송
    p_done = sub.add_parser('done', help='작업 완료 신호 전송')
    p_done.add_argument('--slot', default='T1', help='슬롯명 (기본: T1)')
    p_done.add_argument('--task-id', default='', help='태스크 ID')
    p_done.add_argument('--summary', default='', help='작업 완료 요약')

    # check — 완료 여부 확인
    p_check = sub.add_parser('check', help='완료 신호 확인')
    p_check.add_argument('--slot', required=True, help='슬롯명')

    # reset — 신호 초기화
    p_reset = sub.add_parser('reset', help='완료 신호 초기화')
    p_reset.add_argument('--slot', required=True, help='슬롯명')
    p_reset.add_argument('--all', action='store_true', help='전체 초기화')

    # watch — stdin 감시
    sub.add_parser('watch', help='stdin 감시 — 완료 신호 라인 감지')

    # status — 전체 상태 조회
    sub.add_parser('status', help='모든 슬롯 완료 신호 상태 조회')

    args = parser.parse_args()

    if args.cmd == 'done':
        send_done_signal(args.slot, args.task_id, args.summary)

    elif args.cmd == 'check':
        entry = check_done(args.slot)
        if entry:
            print(json.dumps(entry, ensure_ascii=False, indent=2))
            sys.exit(0)   # 완료됨
        else:
            print(f'[CompletionGuard] {args.slot} — 아직 완료 신호 없음')
            sys.exit(1)   # 미완료

    elif args.cmd == 'reset':
        if args.all:
            # 전체 초기화
            _save_signals({})
            print('[CompletionGuard] 전체 신호 초기화 완료')
        else:
            reset_signal(args.slot)

    elif args.cmd == 'watch':
        sys.exit(watch_stdin())

    elif args.cmd == 'status':
        status_all()

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
