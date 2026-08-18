# -*- coding: utf-8 -*-
"""
FILE: scripts/wait_ci.py
DESCRIPTION: CI 빌드가 끝날 때까지 기다렸다가 **끝나는 순간 스스로 종료**한다.
             릴리즈 스킬 Step 4 가 부르는 물건이다.

             [🔴 왜 이 스크립트가 생겼나 — 2026-08-17 사장 지시] 전에는 스킬이
               "빌드 완료까지 주기적 확인" 이라고 적어 두었다. 그래서 에이전트가
               10~15분 동안 `gh run view` 를 되풀이하며 **지켜보고만** 있었고,
               그동안 다른 일이 멈춰 사장이 "다 됐냐"를 되묻게 됐다.
               사장 말씀 그대로: "빌드가 돌고있으면 감시하지말고 끝나면 통보만해."

             [🔴 그래서 이 파일의 계약은 '끝나면 죽는다' 하나다]
               백그라운드로 띄우면 **종료 자체가 통보**가 된다(하네스가 알려 준다).
               `tail -f` 처럼 안 끝나는 명령으로 바꾸면 통보가 영영 안 온다 —
               그 순간 이 파일은 존재 이유를 잃는다.

             [🔴 침묵을 성공으로 읽지 않는다] 성공만 기다리면 크래시·취소·타임아웃에서
               영원히 안 끝난다. **끝난 상태 전부**(success/failure/cancelled/…)를
               끝으로 친다. 판정은 마지막 줄과 종료코드로 낸다.

             [제약] gh CLI 로그인이 되어 있어야 한다. 없으면 즉시 그 사실을 알리고
               죽는다 — 조용히 기다리면 그것도 '통보 없음'이다.

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — 빌드를 지켜보지 말고 끝나면 통보받으라는 지시
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

# [🔴 첫 print 보다 먼저 — 2026-08-18 실측] 이 스크립트는 배포 스킬이 백그라운드로
#   띄운다. 그런데 윈도우 콘솔 기본 코드페이지(cp949)로 줄표(—)를 못 찍어
#   **첫 진행 출력에서 UnicodeEncodeError 로 죽었다.** 죽으면 '끝나면 통보' 계약이
#   깨지고, 스킬은 기다린 줄 알지만 실제로는 아무도 안 기다린 상태가 된다
#   (오늘 v3.7.350 배포에서 그대로 겪었다 — 같은 함정을 incident.py·smoke_test.py 도 겪음).
#   [WHY errors='replace'] 통보가 목적이지 글자 모양이 목적이 아니다. 못 찍는 글자
#   하나 때문에 대기가 죽는 쪽이 훨씬 나쁘다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                        # noqa: BLE001
        pass                                                 # 재설정 실패는 대기를 막지 않는다

WORKFLOW = 'Build & Release'
POLL_S = 30
# [WHY 상한을 두나] CI 가 영영 안 끝나는 일이 있다(러너 대기·행). 그때도 **통보는 와야**
#   한다 — 말없이 남아 있으면 지켜보는 것과 같아진다.
MAX_S = 60 * 45

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # 규칙 10 — 창을 띄우지 않는다


def _gh(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60,
                           creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or '').strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f'{type(e).__name__}: {e}'


def latest_run() -> dict | None:
    rc, out = _gh(['run', 'list', '--limit', '10', '--json',
                   'status,conclusion,name,displayTitle,databaseId,url'])
    if rc != 0 or not out:
        return None
    try:
        rows = json.loads(out)
    except ValueError:
        return None
    for r in rows:
        if r.get('name') == WORKFLOW:
            return r
    return rows[0] if rows else None


def main() -> int:
    rc, _ = _gh(['auth', 'status'])
    if rc != 0:
        print('[!] gh 로그인이 안 돼 있어 빌드를 기다릴 수 없다', flush=True)
        return 2

    t0 = time.time()
    seen = ''
    while True:
        run = latest_run()
        if run is None:
            print('[!] 빌드 목록을 못 읽었다 — gh 응답 없음', flush=True)
            return 2
        status = run.get('status') or ''
        if status != seen:
            print(f"[{int(time.time() - t0)}초] {run.get('name')} — {status}", flush=True)
            seen = status
        if status == 'completed':
            concl = run.get('conclusion') or '(결론 없음)'
            print(f"빌드 끝 — {concl} :: {run.get('displayTitle', '')[:60]}", flush=True)
            print(run.get('url', ''), flush=True)
            if concl != 'success':
                # 실패 원인 첫 줄까지 얹어 준다 — 통보를 받고 또 캐러 가지 않게.
                _, log = _gh(['run', 'view', str(run.get('databaseId')), '--log-failed'])
                for line in (log.splitlines() or [])[-15:]:
                    print('  |', line, flush=True)
                return 1
            return 0
        if time.time() - t0 > MAX_S:
            print(f'[!] {MAX_S // 60}분이 지나도 안 끝났다 — 지금 상태 {status}', flush=True)
            return 3
        time.sleep(POLL_S)


if __name__ == '__main__':
    sys.exit(main())
