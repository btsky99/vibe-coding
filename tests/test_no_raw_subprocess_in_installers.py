# -*- coding: utf-8 -*-
"""
FILE: tests/test_no_raw_subprocess_in_installers.py
DESCRIPTION: 설치 스크립트가 **맨손 subprocess** 로 외부 명령을 부르지 못하게 고정한다(규칙 10).

             [🔴 왜 생겼나 — 2026-08-17] 사장 신고 "실행 시 node.exe 콘솔이 계속 뜬다".
               자동 설치 경로는 부모(api/tools_api.launch_ai_toolchain_installer)가 이미
               `proc.popen` 으로 무창으로 띄우고 있었고, 그 자리 주석은 이렇게 예고까지 해 뒀다:
                 "자식이 다시 npm.cmd 등을 부르면 그 손자에는 상속되지 않으므로,
                  install_ai_toolchain.py 쪽도 infra.proc 를 써야 완전히 무창이다."
               **예고만 있고 고쳐지지는 않았다** — 네 스크립트가 전부 맨손 subprocess 였다.
               주석은 사람이 읽어야 지켜지고, 사람은 안 읽는다. 그래서 기계가 지킨다.

             [🔴 이 테스트가 '증명'하는 것과 아닌 것] 이것은 **규칙 위반이 다시 들어오는 것**을
               막는다. 2026-08-17 시점에 사장 화면의 창이 정확히 이 경로에서 났다는 것은
               **증명되지 않았다**(그 PC 의 자동 설치 기록이 비어 있었다). 위반은 위반대로
               고치고, 원인 규명은 scripts/console_watch.py 로 현장에서 잡는다.

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — 설치 스크립트의 맨손 subprocess 금지
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'

# 외부 명령을 실제로 띄우는 설치 스크립트들. 여기 목록이 곧 계약이다.
TARGETS = [
    'install_ai_toolchain.py',
    'install_npm_tool.py',
    'install_nodejs.py',
    'install_codex.py',
]

_RAW = re.compile(r'\bsubprocess\.(run|Popen|call|check_call|check_output)\s*\(')


@pytest.mark.parametrize('name', TARGETS)
def test_맨손_subprocess_로_외부명령을_부르지_않는다(name):
    p = SCRIPTS / name
    if not p.exists():
        pytest.skip(f'{name} 이 없다 — 목록에서 지울 것')
    hits = []
    for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        s = line.strip()
        if s.startswith('#') or not _RAW.search(line):
            continue
        # creationflags 를 손으로 준 줄은 의도적 예외로 본다(창을 일부러 여는 자리).
        if 'creationflags' in line:
            continue
        hits.append(f'{i}행: {s[:110]}')
    assert not hits, (
        f'{name} 이 맨손 subprocess 로 외부 명령을 부른다 — 규칙 10 위반.\n'
        f'  부모가 무창이어도 CREATE_NO_WINDOW 는 **손자에게 상속되지 않는다**.\n'
        f'  npm.cmd → node.exe 가 새 검은 창을 받는다(2026-08-17 사장 신고).\n'
        f'  고치는 법: `from _install_common import run as _run` 로 갈아 끼울 것.\n'
        + '\n'.join('  ' + h for h in hits))


def test_공용_실행기가_존재하고_창을_막는다():
    p = SCRIPTS / '_install_common.py'
    assert p.exists(), 'scripts/_install_common.py 가 없다 — 실행기는 한 곳이어야 한다'
    src = p.read_text(encoding='utf-8')
    assert 'CREATE_NO_WINDOW' in src, '폴백 경로에도 창 숨김이 있어야 한다'
    assert 'from infra import proc' in src, 'infra.proc 를 우선 쓰는 길이 있어야 한다'
