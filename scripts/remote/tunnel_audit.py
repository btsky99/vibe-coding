#!/usr/bin/env python3
"""
FILE: scripts/remote/tunnel_audit.py
DESCRIPTION: VPS 역터널 포트에 **실제로 어느 기계가 붙어 있는지** 호스트키 지문으로 판정한다.
             라벨(`cipher`, `na2js`)이 아니라 기계가 증명하는 값으로 대조하는 것이 요점.
             `--record` 로 포트↔기계를 장부에 고정하면, 다음부터 바뀐 순간을 잡아낸다.

             사용:
               python scripts/remote/tunnel_audit.py                  # 현황 판정
               python scripts/remote/tunnel_audit.py --record 22002=na2js
               python scripts/remote/tunnel_audit.py --json           # 기계 판독용

[🔴 이 도구가 존재하는 이유 — 라벨을 믿었다가 진단이 두 번 오염됐다]
  역터널 포트는 사람이 `-TunnelPort 22001` 로 손수 넣는 값이고, 어디에도 '이 포트는 누구
  것'이라는 검증 가능한 기록이 없었다. 다른 PC 것을 복사해 온 설정이 남아 있으면 그 PC가
  남의 포트를 차지한 채 조용히 살아 있고, 관리하는 쪽은 `ssh cipher` 가 붙으니 맞다고
  믿는다. 2026-08-11 na2js 진단이 정확히 이 방식으로 두 번 엉뚱한 기계를 가리켰다.

  sshd 호스트키 지문은 **기계가 개인키 소유로 증명하는 값**이라 복사해 온 설정으로는
  흉내 낼 수 없다. 그래서 판정의 정본을 지문에 둔다.

[제약] VPS 에 ssh 로 붙을 수 있는 관리 PC 에서만 의미가 있다. 노드 쪽에서는 돌릴 이유가 없다.
[제약] 지문 조회는 ssh-keyscan 이므로 **인증하지 않는다** — 남의 노드에 로그인하지 않고
  '누구인지'만 확인한다. 이 도구에 로그인 기능을 넣지 말 것(감사 도구가 침입 도구가 된다).

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성 — 손으로 관리하던 포트 배정이 조용히 어긋나던 문제.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# 역터널 배정 대역. Setup-RemoteNode.ps1 의 안내(22001~)와 같은 범위를 본다.
PORT_MIN, PORT_MAX = 22001, 22099

# [WHY 홈이 아니라 LOCALAPPDATA 인가] 같은 폴더에 tunnel-*.cmd / rustdesk-server.txt 등
#   원격 접속 관련 비밀이 이미 모여 있다. 장부만 다른 곳에 두면 백업·이사에서 빠진다.
def _ledger_path() -> Path:
    base = os.environ.get('LOCALAPPDATA')
    root = Path(base) / 'vibe-remote' if base else Path.home() / '.vibe-remote'
    return root / 'tunnel-nodes.json'


# VPS 에서 돌릴 조사 스크립트. stdin 으로 넘긴다.
# [WHY stdin 인가] 따옴표가 3중(python → ssh → bash)으로 겹치면 조용히 깨진 명령이
#   'ss 결과 없음'으로 보여 "터널이 없다"는 오진이 된다. 본문을 그대로 흘려보내면
#   이스케이프가 아예 필요 없다.
PROBE = r'''
for p in $(ss -ltn 2>/dev/null | grep -oE '127\.0\.0\.1:[0-9]+' | cut -d: -f2 | sort -un); do
  [ "$p" -ge PORT_MIN_ ] && [ "$p" -le PORT_MAX_ ] || continue
  pid=$(ss -ltnp "sport = :$p" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  peer=$(ss -tnp state established "sport = :22" 2>/dev/null | grep "pid=$pid," | awk '{print $4}' | head -1)
  since=$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//')
  banner=$(timeout 5 nc -w 4 127.0.0.1 "$p" 2>/dev/null | head -1 | tr -d '\r')
  fp=$(ssh-keyscan -T 6 -p "$p" -t ed25519 127.0.0.1 2>/dev/null \
       | ssh-keygen -lf - 2>/dev/null | head -1 | awk '{print $2}')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "${fp:-?}" "${peer:-?}" "${since:-?}" "${banner:-?}" "${pid:-?}"
done
'''


def probe(ssh_host: str) -> list[dict]:
    """VPS 를 조사해 포트별 실측을 돌려준다. 실패하면 빈 목록 + stderr 안내."""
    script = (PROBE.replace('PORT_MIN_', str(PORT_MIN))
                   .replace('PORT_MAX_', str(PORT_MAX)))
    try:
        # [🔴 text=True 로 stdin 을 넘기지 말 것 — 윈도우에서 조용히 깨진다]
        #   텍스트 모드는 '\n' 을 os.linesep('\r\n')으로 바꿔 쓴다. 그 \r 이 그대로
        #   원격 bash 에 들어가 `$'do\r': command not found` 로 죽는다. 증상은
        #   "터널이 하나도 없다"로만 보여, 스크립트 버그가 인프라 장애로 둔갑한다.
        #   바이트로 넘기면 번역 자체가 일어나지 않는다.
        r = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', ssh_host, 'bash', '-s'],
            input=script.encode('utf-8'), capture_output=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'[FAIL] VPS 조사 실패({ssh_host}): {exc}', file=sys.stderr)
        return []
    if r.returncode != 0:
        err = r.stderr.decode('utf-8', 'replace').strip()[:300]
        print(f'[FAIL] ssh 종료코드 {r.returncode}: {err}', file=sys.stderr)
        return []

    out = []
    for line in r.stdout.decode('utf-8', 'replace').splitlines():
        parts = line.split('\t')
        if len(parts) != 6 or not parts[0].isdigit():
            continue
        port, fp, peer, since, banner, pid = parts
        out.append({'port': int(port), 'fingerprint': fp, 'peer': peer,
                    'since': since, 'banner': banner, 'pid': pid})
    return out


def load_ledger() -> dict:
    """지문 → {name, port, ...} 장부. 없으면 빈 장부."""
    try:
        return json.loads(_ledger_path().read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    except Exception as exc:                                   # noqa: BLE001
        # [🔴 깨진 장부를 빈 장부로 취급하지 않는다] 빈 것으로 보면 아래 --record 가
        #   기존 기록을 통째로 덮어써 '누가 어느 포트였나'가 영구 소멸한다.
        #   같은 함정으로 config.json 을 잃은 전례가 있다(2026-08-11 na2js).
        print(f'[FAIL] 장부를 읽지 못했다 — 덮어쓰지 않고 멈춘다: {exc}', file=sys.stderr)
        raise SystemExit(2)


def save_ledger(data: dict) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def judge(rows: list[dict], ledger: dict) -> list[dict]:
    """포트별 판정. 장부는 **지문이 열쇠**다 — 포트를 열쇠로 삼으면 기계가 바뀐 것을
    '같은 노드'로 읽어버려, 정확히 이 도구가 잡으려는 사고를 놓친다."""
    by_port = {int(v.get('port') or 0): (fp, v) for fp, v in ledger.items()}
    seen_fps = set()
    out = []

    for r in rows:
        fp = r['fingerprint']
        seen_fps.add(fp)
        known = ledger.get(fp)
        expected = by_port.get(r['port'])

        if known and int(known.get('port') or 0) == r['port']:
            verdict, detail = 'OK', known.get('name', '?')
        elif known:
            # 이 기계는 아는데 배정된 포트가 아니다 — 남의 자리에 앉아 있다.
            verdict = 'MOVED'
            detail = f"{known.get('name','?')} — 장부상 {known.get('port')}번인데 {r['port']}번에 있다"
        elif expected:
            # 포트는 배정돼 있는데 다른 기계다. 진단 오염의 실체가 바로 이 줄이다.
            verdict = 'SQUAT'
            detail = f"장부상 {expected[1].get('name','?')} 자리인데 **다른 기계**가 물고 있다"
        else:
            verdict, detail = 'UNKNOWN', '장부에 없는 기계 — --record 로 이름을 붙여라'

        out.append({**r, 'verdict': verdict, 'detail': detail})

    # 장부에 있는데 지금 안 붙어 있는 노드도 알려준다(끊김은 침묵으로 나타나므로).
    for fp, v in ledger.items():
        if fp not in seen_fps:
            out.append({'port': int(v.get('port') or 0), 'fingerprint': fp, 'peer': '-',
                        'since': '-', 'banner': '-', 'pid': '-',
                        'verdict': 'DOWN', 'detail': f"{v.get('name','?')} — 터널이 안 붙어 있다"})
    return sorted(out, key=lambda x: x['port'])


MARK = {'OK': '✅', 'SQUAT': '🔴', 'MOVED': '🟠', 'UNKNOWN': '⚠️ ', 'DOWN': '💤'}


def render(rows: list[dict]) -> None:
    if not rows:
        print('역터널 포트가 하나도 열려 있지 않다. (VPS 조사 실패면 위 [FAIL] 참조)')
        return
    print()
    print(f"{'포트':<6} {'판정':<8} {'지문(앞 16)':<20} {'접속元':<22} 비고")
    print('-' * 100)
    for r in rows:
        fp = (r['fingerprint'] or '?')
        fp = fp[7:23] if fp.startswith('SHA256:') else fp[:16]
        print(f"{r['port']:<6} {MARK.get(r['verdict'], '  ')}{r['verdict']:<6} "
              f"{fp:<20} {r['peer']:<22} {r['detail']}")
    print()
    bad = [r for r in rows if r['verdict'] in ('SQUAT', 'MOVED')]
    if bad:
        print('🔴 포트 배정이 실제와 어긋난다. 이 상태로는 `ssh <별칭>` 이 엉뚱한 PC 에 붙는다.')
        print('   해당 노드에서 Setup-RemoteNode.ps1 을 올바른 -TunnelPort 로 다시 돌리고,')
        print('   그 PC 의 %LOCALAPPDATA%\\vibe-remote\\tunnel-<남의이름>.cmd 와 예약 작업을 지운다.')


def main() -> int:
    ap = argparse.ArgumentParser(description='VPS 역터널 포트 실제 소유자 감사')
    ap.add_argument('--ssh-host', default='vibe-seoul', help='VPS ssh 별칭 (기본: vibe-seoul)')
    ap.add_argument('--record', action='append', default=[], metavar='PORT=NAME',
                    help='지금 그 포트에 붙어 있는 기계를 그 이름으로 장부에 고정')
    ap.add_argument('--json', action='store_true', help='판정 결과를 JSON 으로')
    args = ap.parse_args()

    rows = probe(args.ssh_host)
    ledger = load_ledger()

    for spec in args.record:
        port_s, _, name = spec.partition('=')
        if not name.strip() or not port_s.strip().isdigit():
            print(f'[FAIL] --record 형식은 PORT=NAME 이다: {spec}', file=sys.stderr)
            return 2
        port = int(port_s)
        live = next((r for r in rows if r['port'] == port), None)
        if not live or live['fingerprint'] in ('?', ''):
            # [WHY 붙어 있을 때만 기록하나] 지문 없이 이름만 적으면 그것이야말로
            #   지금까지 문제였던 '검증되지 않은 라벨'이다. 장부는 실측만 담는다.
            print(f'[FAIL] {port}번에 붙어 있는 기계가 없다(또는 지문 조회 실패) — 기록하지 않는다.',
                  file=sys.stderr)
            return 1
        ledger[live['fingerprint']] = {'name': name.strip(), 'port': port,
                                       'peer': live['peer'], 'recorded': live['since']}
        save_ledger(ledger)
        print(f"[OK] {port}번 = {name.strip()} (지문 {live['fingerprint'][:23]}…) 장부에 고정")

    result = judge(rows, ledger)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
