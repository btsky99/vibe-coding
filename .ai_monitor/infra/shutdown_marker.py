"""
FILE: infra/shutdown_marker.py
DESCRIPTION: '사람이 껐다'는 사실을 남기는 종료 의사 표식. 감시자(hive_watchdog)가
             앱을 되살릴지 말지 가르는 유일한 근거다. 앱의 정상 종료 경로만 이 표식을
             남기므로, 크래시/강제종료는 구조적으로 이 표식을 만들 수 없다.

REVISION HISTORY:
- 2026-08-16 Claude: 신설 — "껐는데 자꾸 살아난다" 사고. 고아 워치독이 60초마다
  server.py 를 재기동했고 server.py __main__ 은 GUI 앱 전체라 창까지 되살아났다.
  감시자를 없애면 진짜 크래시 복구가 사라지므로, '사람이 끈 것'만 가려내 막는다.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# [WHY 파일인가 / DB 아님] 이 표식을 읽는 쪽(워치독)은 '앱이 죽은 뒤'에 읽는다.
#   앱이 죽으면 PG 커넥션 풀도 같이 사라지고, 내장 PG 자체가 앱과 함께 내려갈 수도
#   있다(lifecycle.cleanup_postgres). 종료를 판정하는 신호가 종료와 함께 사라지면
#   판정이 성립하지 않는다 — 그래서 규칙 4(PostgreSQL-first 로깅)의 예외다.
#   이건 '활동 로그'가 아니라 '프로세스 생사 판정용 부트 신호'다.
FILENAME = 'shutdown.intent.json'


def path(data_dir: Path | str) -> Path:
    """표식 파일 경로. data_dir 단위 = 인스턴스 단위(워치독도 --data-dir 로 같은 값을 받는다)."""
    return Path(data_dir) / FILENAME


def mark(data_dir: Path | str, reason: str) -> None:
    """사람이 끈 종료임을 기록한다. 앱의 정상 종료 경로에서만 호출할 것.

    [불변식] 호출 지점은 '창 닫힘 → 정리' 처럼 사용자 행동으로만 도달하는 코드여야 한다.
      taskkill / 크래시 / WebView2 사망은 그 코드에 도달하지 못하므로 표식이 안 남고,
      그래서 자동 복구 대상으로 정확히 남는다. 이 함수를 예외 핸들러나 atexit 같은
      '어떤 죽음이든 지나가는 자리'에 걸면 판별 능력이 통째로 사라진다.
    [실패 허용] 표식 쓰기 실패는 종료를 막지 않는다 — 최악의 결과가 '한 번 더 되살아남'
      이라 회복 가능하지만, 종료를 붙잡으면 앱이 안 꺼진다(더 나쁨).
    """
    try:
        p = path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            'ts': time.time(),
            'reason': reason,
            'pid': os.getpid(),
            'at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def clear(data_dir: Path | str) -> None:
    """표식을 지운다. 앱이 다시 정상 기동했을 때 호출.

    [WHY 반드시 지워야 하나] 표식이 남아 있으면 '다음번에 진짜로 죽었을 때'도 감시자가
      복구를 포기한다. 자동 복구를 없애지 않는 것이 이 작업의 전제 조건이므로,
      표식의 수명은 '사람이 끈 그 한 번' 으로 끝나야 한다.
    """
    try:
        path(data_dir).unlink()
    except OSError:
        pass


def read(data_dir: Path | str) -> dict | None:
    """표식 내용을 읽는다. 없거나 깨졌으면 None."""
    try:
        return json.loads(path(data_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def was_intentional(data_dir: Path | str, since_ts: float) -> dict | None:
    """since_ts(감시자 자신이 태어난 시각) 이후에 찍힌 표식만 유효로 본다.

    [WHY 시각 대조가 필요한가] 감시자는 앱의 자식이라 '앱과 같이 태어난다'. 따라서
      나보다 먼저 찍힌 표식은 이전 세대의 종료 기록이지 내 부모의 것이 아니다.
      clear() 를 어딘가에서 놓쳐도 이 대조가 있으면 옛 표식이 자동 복구를 영구히
      막는 사고로 번지지 않는다 — clear 와 이중 안전선이다.
    """
    data = read(data_dir)
    if not data:
        return None
    try:
        if float(data.get('ts', 0)) < since_ts:
            return None
    except (TypeError, ValueError):
        return None
    return data
