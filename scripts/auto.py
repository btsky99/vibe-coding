# -*- coding: utf-8 -*-
"""
FILE: scripts/auto.py
DESCRIPTION: 자율 클로드 heartbeat 터미널 스위치 — on/off/status.
             텔레그램 /auto 명령과 같은 hive_state 'heartbeat' 플래그를 조작한다.
             (데몬 본체는 .ai_monitor/infra/heartbeat_daemon.py — 서버 프로세스 안에서 가동)

REVISION HISTORY:
- 2026-07-17 Claude: 신규 — 터미널에서 텔레그램 없이 자율 모드 제어 (사용자 요청)
"""
import sys
from pathlib import Path

# [WHY] scripts/에서 .ai_monitor 패키지 접근 — 프로젝트 루트 기준 상대 경로 고정
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '.ai_monitor'))


def _wake_now() -> None:
    """NOTIFY로 데몬 즉시 기상 — 폴링(10분) 대기 생략. 실패해도 무해(폴링이 잡음)."""
    try:
        from src.pg_base import execute
        execute('NOTIFY hive_heartbeat;')
    except Exception:
        pass


def main() -> int:
    from infra.heartbeat_daemon import (
        AGENT_ID, DAILY_LIMIT, FAIL_LIMIT, load_hb_state, save_hb_state,
    )
    cmd = (sys.argv[1].lower() if len(sys.argv) > 1 else 'status')

    if cmd == 'on':
        s = load_hb_state()
        s['enabled'] = True
        # [WHY] 연속 실패 자동 정지 후 재개가 가드에 다시 걸리지 않게 리셋 (텔레그램 /auto on과 동일 계약)
        s['consecutive_fails'] = 0
        save_hb_state(s)
        _wake_now()
        print('🫀 자율 모드 ON — 태스크 소비/자가 발굴 시작 (서버가 떠 있어야 동작)')
        print(f'   태스크 맡기기: python scripts/task.py create "내용" --agent {AGENT_ID}')
        return 0

    if cmd == 'off':
        s = load_hb_state()
        s['enabled'] = False
        save_hb_state(s)
        print('⏹ 자율 모드 OFF')
        return 0

    if cmd == 'status':
        s = load_hb_state()
        icon = '🟢 ON' if s.get('enabled') else '🔴 OFF'
        print(f'🫀 자율 클로드 상태: {icon}')
        print(f"   오늘 수행: {s.get('daily_count', 0)}/{DAILY_LIMIT}건")
        print(f"   연속 실패: {s.get('consecutive_fails', 0)}/{FAIL_LIMIT}")
        print(f"   마지막 사이클: {s.get('last_cycle_at') or '-'} ({s.get('last_result') or '-'})")
        try:
            from src.pg_store import find_tasks_for_agent
            pending = find_tasks_for_agent(AGENT_ID)
            print(f'   대기 태스크: {len(pending)}건')
            for t in pending[:5]:
                print(f"     - [{t.get('priority')}] {t.get('title', '')[:60]}")
        except Exception as e:
            print(f'   대기 태스크: 조회 실패 ({e})')
        if not s.get('enabled'):
            print('   켜기: python scripts/auto.py on')
        return 0

    print('사용법: python scripts/auto.py [on|off|status]')
    return 1


if __name__ == '__main__':
    sys.exit(main())
