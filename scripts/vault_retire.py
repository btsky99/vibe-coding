#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/vault_retire.py
DESCRIPTION: 옵시디언 볼트 갈래 접기(경량화 2단계) — 파생물 .md 트리를 지운다.
             기본은 **말만 하고 아무것도 안 지운다**. 지우려면 `--apply`.

             [🔴 이 스크립트가 지우는 것은 파생물뿐이다] 지식 본체는 PostgreSQL
               `zettel_notes` 에 있고 회상/pgvector 는 그 표를 읽는다
               (`src/pg_vector_search.py:36`). 볼트 .md 는 옵시디언으로 보기 위한
               사본이라, 다시 만들고 싶으면 config `"vault_export": true` 로 되켜면
               데몬이 다시 내보낸다. 즉 **되돌릴 수 있는 삭제**다.

             [🔴 왜 데몬이 아니라 사람이 부르는 도구인가] 데몬이 수천 개 파일을
               자동 삭제하면 오작동 한 번을 되돌릴 수 없다. 스위치(안 쓴다)와
               청소(지운다)를 일부러 갈랐다 — `infra/daemons.py:_vault_export_enabled`.

             [🔴🔴 구글 드라이브 미러는 절대 건드리지 않는다] 미러에는 **다른
               프로젝트(CipherTrader) 지식이 섞여 산다**(feedback_no_hardcoding_tpsl 등).
               크로스-프로젝트 허브였기 때문이다. 거기를 청소하면 남의 것을 지운다.
               그래서 대상에서 아예 뺐고, 인자로도 지정할 수 없게 했다.

             [세 관문 — 하나라도 안 맞으면 안 지운다]
               ① 백업이 온전한가        지울 장수 이상을 백업이 갖고 있어야 한다
               ② 스위치가 꺼져 있나      켜져 있으면 데몬이 60초 뒤 다시 만든다(헛일)
               ③ 앱이 죽어 있나         돌고 있으면 옛 코드가 메모리에서 다시 쓴다
                                       (부팅 시 1회 exec_module — 앱 재시작이 유일한 적용 수단)

             [사용]
               python scripts/vault_retire.py                      # 무엇을 지울지만 본다
               python scripts/vault_retire.py --apply               # 실제로 지운다
               python scripts/vault_retire.py --backup <경로>        # 백업 위치 지정

REVISION HISTORY:
- 2026-08-19 Claude: 최초 작성 — 결재 42 경량화 2단계. 볼트 3갈래를 wiki/ 한 곳으로.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# [과거사고] cp949 콘솔이 줄표(—)를 못 찍어 스크립트가 첫 출력에서 죽는 일이 반복됐다
# (bab2488 · wiki_index_build.py). **삭제 도구가 출력에서 죽으면 무엇을 지웠는지 모른다.**
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP = Path('D:/vault-backup-20260818-2130')

# [불변식] 여기에 GDrive 미러를 넣지 마라 — 파일 상단 주석의 이유를 먼저 읽을 것.
def targets() -> list[tuple[str, Path]]:
    appdata = os.getenv('APPDATA')
    out: list[tuple[str, Path]] = []
    if appdata:
        out.append(('appdata-vault', Path(appdata) / 'VibeCoding' / 'vault'))
    else:                                    # 맥/리눅스
        out.append(('appdata-vault', Path.home() / '.vibe-coding' / 'vault'))
    out.append(('zettel-vault', ROOT / '.zettel-vault'))
    return out


def count_md(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for _ in p.rglob('*.md'))


def size_mb(p: Path) -> float:
    if not p.exists():
        return 0.0
    total = 0
    for f in p.rglob('*'):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


def gate_backup(backup: Path, need: dict[str, int]) -> list[str]:
    """① 백업이 온전한가. 갈래별로 **지울 장수 이상**을 갖고 있어야 통과."""
    bad = []
    if not backup.exists():
        return [f'백업 폴더가 없다: {backup}']
    for name, n in need.items():
        if n == 0:
            continue
        have = count_md(backup / name)
        if have < n:
            bad.append(f'백업 {name}: {have}장 < 지울 {n}장')
        else:
            print(f'  ✔ 백업 {name}: {have}장 (지울 것 {n}장)')
    return bad


def gate_switch() -> list[str]:
    """② 내보내기 스위치가 꺼져 있나. 켜져 있으면 지워도 데몬이 다시 만든다."""
    bad = []
    cands = [ROOT / '.ai_monitor' / 'config.json']
    appdata = os.getenv('APPDATA')
    if appdata:
        cands.append(Path(appdata) / 'VibeCoding' / 'config.json')
    for c in cands:
        if not c.exists():
            continue
        try:
            cfg = json.loads(c.read_text(encoding='utf-8'))
        except Exception as exc:                           # noqa: BLE001
            print(f'  ? {c} 를 못 읽었다({type(exc).__name__}) — 꺼진 것으로 본다')
            continue
        if cfg.get('vault_export', False):
            bad.append(f'{c} 에 "vault_export": true — 지워도 다시 만들어진다')
        else:
            print(f'  ✔ 스위치 꺼짐: {c}')
    return bad


def gate_app_dead() -> list[str]:
    """③ 앱이 죽어 있나.

    [WHY 이 관문이 필요한가] zettel_sync.py 는 부팅 때 **1회 exec_module** 로 메모리에
      올라간다(`infra/daemons.py`). 그래서 파일을 고쳐도 도는 앱은 옛 코드로 60초마다
      다시 쓴다 — 실측된 함정이고, 지우는 쪽에서는 '지웠는데 되살아난다'로 나타난다.
    """
    try:
        import psutil                                     # type: ignore
    except Exception:                                      # noqa: BLE001
        print('  ? psutil 이 없어 앱 가동 여부를 못 쟀다 — 직접 확인할 것')
        return []
    alive = []
    for pr in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = ' '.join(pr.info.get('cmdline') or [])
        except Exception:                                  # noqa: BLE001
            continue
        low = cmd.lower()
        if 'server.py' in low or 'vibe-coding.exe' in low:
            alive.append(f"pid {pr.info['pid']}: {cmd[:90]}")
    if alive:
        return ['앱/서버가 돌고 있다 — 먼저 끄고 다시 실행하라:\n      ' + '\n      '.join(alive)]
    print('  ✔ 앱/서버가 돌지 않는다')
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description='볼트 갈래 접기 — 기본은 말만 한다')
    ap.add_argument('--apply', action='store_true', help='실제로 지운다')
    ap.add_argument('--backup', default=str(DEFAULT_BACKUP), help='백업 폴더')
    a = ap.parse_args()
    backup = Path(a.backup)

    print('[볼트 접기] 대상 — 구글 드라이브 미러는 대상이 아니다(남의 프로젝트 지식이 섞여 있음)')
    need: dict[str, int] = {}
    total = 0
    for name, p in targets():
        n = count_md(p)
        need[name] = n
        total += n
        state = f'{n}장 · {size_mb(p):.2f}MB' if p.exists() else '없음(할 일 없음)'
        print(f'  {name:<16} {state}')
        print(f'  {"":<16} {p}')

    if total == 0:
        print('\n지울 것이 없다 — 이미 접혀 있다.')
        return 0

    print('\n[관문] 세 가지를 본다')
    problems = gate_backup(backup, need) + gate_switch() + gate_app_dead()
    if problems:
        print('\n🔴 안 지운다 — 아래를 먼저 해결하라:')
        for b in problems:
            print(f'  - {b}')
        return 1

    if not a.apply:
        print(f'\n관문 셋 통과. 지금은 **아무것도 안 지웠다**(총 {total}장 예정).')
        print('실제로 지우려면: python scripts/vault_retire.py --apply')
        return 0

    removed = 0
    for name, p in targets():
        if not p.exists():
            continue
        try:
            shutil.rmtree(p)
            print(f'  지웠다 — {name} ({need[name]}장) {p}')
            removed += need[name]
        except Exception as exc:                           # noqa: BLE001
            # [WHY 계속 가나] 한 갈래가 잠겨 있어도 다른 갈래는 접을 수 있다. 실패는 남긴다.
            print(f'  🔴 실패 — {name}: {type(exc).__name__}: {exc}')
    print(f'\n총 {removed}장 접었다. 되돌리려면 config.json "vault_export": true 후 앱 재시작.')
    print(f'백업은 그대로 있다: {backup}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
