# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/heal_daemon.py
# 📝 설명: 자율 자기치유 데몬 (Self-Healing Daemon).
#          task_logs.jsonl을 주기적으로 분석하여 반복 오류 패턴을 감지하고,
#          패턴 발견 시 messages.jsonl로 vibe-heal 지시를 자동 전송합니다.
#          claude_watchdog.py가 이 메시지를 감지하여 cli_agent를 통해 자동 치유합니다.
#
#          [동작 흐름]
#          heal_daemon (주기 분석)
#            → 패턴 감지
#            → messages.jsonl에 heal 지시 전송
#            → claude_watchdog 자동 감지
#            → cli_agent → Claude/Gemini 자동 실행
#            → 치유 완료 (사용자 개입 없음)
#
#          [실행 방법]
#          python scripts/heal_daemon.py              # 기본 5분 주기
#          python scripts/heal_daemon.py --interval 60  # 60초 주기 (테스트용)
#          python scripts/heal_daemon.py --once        # 1회 분석 후 종료
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-03-05] Claude: 최초 구현
#   - task_logs.jsonl 반복 패턴 감지 (24시간 윈도우)
#   - 동일 키워드 3회 이상 = 패턴으로 판정
#   - 쿨다운 1시간: 같은 패턴 중복 치유 방지
#   - heal_state.json으로 치유 이력 영속화 (재시작 후에도 중복 방지)
#   - messages.jsonl → claude_watchdog 연동
# ------------------------------------------------------------------------
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# ─── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
DATA_DIR      = _PROJECT_ROOT / ".ai_monitor" / "data"
TASK_LOG_FILE = DATA_DIR / "task_logs.jsonl"
MSG_FILE      = DATA_DIR / "messages.jsonl"
# 치유 이력 파일: 쿨다운 추적용 (재시작 후에도 유지)
HEAL_STATE    = DATA_DIR / "heal_state.json"

# ─── 상수 ────────────────────────────────────────────────────────────────────
# 분석 윈도우: 최근 24시간 이내 로그만 대상
ANALYSIS_WINDOW_HOURS = 24
# 패턴 감지 임계값: 동일 키워드 N회 이상이면 치유 트리거
PATTERN_THRESHOLD = 3
# 쿨다운: 같은 패턴은 N시간 이내 재트리거 안 함
COOLDOWN_HOURS = 1
# 기본 분석 주기 (초)
DEFAULT_INTERVAL_SEC = 300  # 5분


# ─── 패턴 감지 대상 — 오류/실패/반복 요청 시그널 ─────────────────────────────
# task_logs에서 "문제가 있다"는 신호가 되는 키워드들
_ERROR_SIGNALS_KO = ['오류', '에러', '실패', '안돼', '안됨', '안 돼', '안 됨',
                      '깨짐', '고쳐', '버그', '문제', '왜', '또', '계속']
_ERROR_SIGNALS_EN = ['error', 'fail', 'failed', 'exception', 'traceback',
                      'invalid', 'undefined', 'cannot', 'unable']

# 프로젝트 공통 단어 (노이즈) — 패턴 감지에서 제외
_SKIP_WORDS = {
    'vibe', 'coding', 'skill', 'skills', 'scripts', 'claude', 'gemini',
    'agent', 'agents', 'hive', 'python', 'data', 'file', 'files',
    '실행', '완료', '시작', '명령', '코드', '파일', '수정', '작업', '결과',
    'the', 'a', 'an', 'is', 'in', 'at', 'of', 'for', 'to', 'with', 'and',
    '', ' ',
}


def _is_error_task(task: str) -> bool:
    """task 문자열이 오류/실패/반복 요청을 나타내는지 판단합니다."""
    task_lower = task.lower()
    for sig in _ERROR_SIGNALS_KO + _ERROR_SIGNALS_EN:
        if sig in task_lower:
            return True
    return False


def _extract_keywords(task: str) -> list[str]:
    """오류/실패 task에서 패턴 키워드를 추출합니다.

    [로직]
    - [지시] 접두어를 가진 사용자 지시 우선 처리
    - Python ErrorType (TypeError 등) 추출
    - 오류 관련 한글 키워드 추출
    - 프로젝트 공통 단어(_SKIP_WORDS) 제외
    """
    import re
    keywords = []

    # Python 에러 타입 추출 (가장 신뢰도 높음)
    error_matches = re.findall(r'\b\w+Error\b|\b\w+Exception\b', task)
    keywords.extend([e.lower() for e in error_matches])

    # [지시] 접두어 있는 사용자 요청에서 핵심 행위 동사 추출
    if '[지시]' in task:
        cleaned = task.replace('[지시]', '').strip()
        kor_words = re.findall(r'[가-힣]{3,5}', cleaned)
        keywords.extend([w for w in kor_words if w in _ERROR_SIGNALS_KO])

    # Python 파일명 추출 (같은 파일에서 반복 오류 시 유용)
    cleaned = re.sub(r'\[.*?\]', ' ', task)
    file_matches = re.findall(r'[\w]+\.(?:py|tsx|ts|js)\b', cleaned)
    keywords.extend([f.lower() for f in file_matches])

    # 오류 시그널 영문 키워드만 추출 (일반 단어 제외)
    for sig in _ERROR_SIGNALS_EN:
        if sig in task.lower():
            keywords.append(sig)

    return [k for k in keywords if k not in _SKIP_WORDS]


def _load_task_logs(hours: int = ANALYSIS_WINDOW_HOURS) -> list[dict]:
    """task_logs.jsonl에서 최근 N시간 이내 로그를 읽어옵니다."""
    if not TASK_LOG_FILE.exists():
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    logs = []
    try:
        with TASK_LOG_FILE.open(encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get('timestamp', '')
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts >= cutoff:
                            logs.append(entry)
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] task_logs 읽기 실패: {e}")
    return logs


def _load_heal_state() -> dict:
    """치유 이력을 heal_state.json에서 로드합니다."""
    if not HEAL_STATE.exists():
        return {}
    try:
        with HEAL_STATE.open(encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_heal_state(state: dict) -> None:
    """치유 이력을 heal_state.json에 저장합니다."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with HEAL_STATE.open('w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] heal_state 저장 실패: {e}")


def _is_cooled_down(pattern_key: str, state: dict) -> bool:
    """해당 패턴이 쿨다운 중이면 True를 반환합니다."""
    last_heal = state.get(pattern_key)
    if not last_heal:
        return True  # 치유 이력 없음 → 즉시 실행 가능
    try:
        last_ts = datetime.fromisoformat(last_heal)
        elapsed = (datetime.now() - last_ts).total_seconds() / 3600
        return elapsed >= COOLDOWN_HOURS
    except Exception:
        return True


def _send_heal_trigger(pattern: str, count: int) -> None:
    """messages.jsonl에 자기치유 지시 메시지를 전송합니다.

    claude_watchdog.py가 이 메시지를 감지하여 자동으로 cli_agent를 실행합니다.
    """
    content = (
        f"[자동 자기치유] 반복 패턴 감지: '{pattern}' ({count}회 반복)\n"
        f"/vibe-heal 스킬을 실행하여 근본 원인을 분석하고 수정하세요."
    )
    msg = {
        'from': 'heal_daemon',
        'to': 'agent',
        'content': content,
        'ts': datetime.now().isoformat(),
        'type': 'heal_trigger',
        'pattern': pattern,
        'count': count,
    }
    try:
        MSG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MSG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
        print(f"  ✅ 치유 지시 전송: '{pattern}' ({count}회)")
    except Exception as e:
        print(f"  ❌ 치유 지시 전송 실패: {e}")


def analyze_and_heal() -> int:
    """task_logs를 분석하여 반복 패턴을 감지하고 필요 시 치유를 트리거합니다.

    Returns:
        int: 트리거된 치유 건수
    """
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔍 자기치유 데몬 분석 시작...")

    logs = _load_task_logs()
    if not logs:
        print("  → task_logs 없음 (분석 대상 없음)")
        return 0

    print(f"  → 최근 {ANALYSIS_WINDOW_HOURS}시간 로그: {len(logs)}개")

    # ── 키워드 빈도 분석 (오류/실패 신호가 있는 항목만 대상) ─────────────────
    keyword_counter: Counter = Counter()
    error_log_count = 0
    for entry in logs:
        task = entry.get('task', '')
        # "[명령 완료]" 항목은 결과 로그이므로 제외
        if '[명령 완료]' in task or '[완료]' in task:
            continue
        # 오류 신호가 없는 일반 실행 로그는 제외
        if not _is_error_task(task):
            continue
        error_log_count += 1
        kws = _extract_keywords(task)
        keyword_counter.update(kws)

    print(f"  → 오류/실패 관련 로그: {error_log_count}개 분석")

    # 임계값 이상인 패턴만 추출
    patterns = [
        (kw, cnt) for kw, cnt in keyword_counter.most_common(20)
        if cnt >= PATTERN_THRESHOLD and len(kw) >= 3
    ]

    if not patterns:
        print("  → 반복 패턴 없음 (정상)")
        return 0

    print(f"  → 반복 패턴 {len(patterns)}개 감지:")
    for kw, cnt in patterns[:5]:
        print(f"     '{kw}': {cnt}회")

    # ── 쿨다운 체크 후 치유 트리거 ────────────────────────────────────────────
    state = _load_heal_state()
    triggered = 0

    for pattern, count in patterns:
        if not _is_cooled_down(pattern, state):
            print(f"  ⏳ '{pattern}': 쿨다운 중 (건너뜀)")
            continue

        _send_heal_trigger(pattern, count)

        # 치유 이력 업데이트
        state[pattern] = datetime.now().isoformat()
        triggered += 1

        # 한 번에 최대 2개 패턴만 트리거 (에이전트 과부하 방지)
        if triggered >= 2:
            break

    _save_heal_state(state)

    if triggered > 0:
        print(f"  🧬 치유 트리거 {triggered}건 전송 완료")
    else:
        print("  → 모든 패턴 쿨다운 중 (재트리거 보류)")

    return triggered


def main():
    """메인 진입점 — 주기적 분석 루프 또는 1회 실행."""
    parser = argparse.ArgumentParser(description='Vibe Coding 자기치유 데몬')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL_SEC,
                        help=f'분석 주기(초), 기본값: {DEFAULT_INTERVAL_SEC}')
    parser.add_argument('--once', action='store_true',
                        help='1회 분석 후 종료 (테스트/수동 실행용)')
    args = parser.parse_args()

    print("🧬 Vibe Coding 자기치유 데몬 시작")
    print(f"   분석 주기: {args.interval}초 ({args.interval // 60}분)")
    print(f"   패턴 임계값: {PATTERN_THRESHOLD}회 이상")
    print(f"   쿨다운: {COOLDOWN_HOURS}시간")
    print(f"   감시 파일: {TASK_LOG_FILE}")
    print("─" * 50)

    if args.once:
        # 1회 실행 모드 (수동 테스트)
        analyze_and_heal()
        return

    # ── 주기적 분석 루프 ──────────────────────────────────────────────────────
    while True:
        try:
            analyze_and_heal()
        except Exception as e:
            print(f"[ERROR] 분석 오류: {e}")

        print(f"  💤 다음 분석까지 {args.interval}초 대기...")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
