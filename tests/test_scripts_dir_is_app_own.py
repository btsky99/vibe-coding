# -*- coding: utf-8 -*-
"""
FILE: tests/test_scripts_dir_is_app_own.py
DESCRIPTION: 데몬이 **이 앱의 scripts/** 를 쓰는지 고정한다 — 남의 프로젝트 것을 띄우지 않게.

             [🔴 왜 생겼나 — 2026-08-17 사장이 화면에서 뽑아 오신 실물 오류]
               File "D:\\CipherTrader\\scripts\\hive_watchdog.py", line 48
                 from src.pg_store import ensure_schema, save_state, cleanup_expired_memory
               ModuleNotFoundError: No module named 'src.pg_store'

               바이브 코딩 설치인데 **CipherTrader 의 스크립트**를 띄우고 있었다.
               원인은 server.py 의 후보 순서였다 — `PROJECT_ROOT / 'scripts'` 를 **먼저** 봤다.
               PROJECT_ROOT 는 사용자가 연 프로젝트라, 그 폴더에 scripts/ 가 있기만 하면
               (대부분의 프로젝트에 있다) 그대로 채택된다. 거기 있던 것은 8/2자 옛 사본이었고
               그 프로젝트에는 이 앱의 의존성(`.ai_monitor/src/pg_store.py`)이 없어 즉사했다.

             [고정하는 계약] 앱 소스 옆 scripts/ 가 **후보 목록의 맨 앞**이고,
               사용자 프로젝트 폴더는 **맨 뒤**다. 순서가 뒤집히면 같은 사고가 재발한다.

             [WHY 소스를 읽어 검사하나] SCRIPTS_DIR 은 server.py 를 import 하는 순간 정해지는
               모듈 상수인데, server.py import 는 DB·포트·데몬을 건드려 테스트에서 못 쓴다.
               그래서 **후보 목록의 순서**라는 계약을 텍스트로 고정한다 — 이 사고를 만든 것이
               정확히 그 순서이기 때문이다.

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — 남의 프로젝트 스크립트를 데몬으로 띄우던 사고
"""

from __future__ import annotations

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / '.ai_monitor' / 'server.py'


def _candidate_block() -> str:
    src = SERVER.read_text(encoding='utf-8')
    m = re.search(r'_scripts_candidates\s*=\s*\[(.*?)\]', src, re.S)
    assert m, ('server.py 에서 _scripts_candidates 목록을 못 찾았다 — '
               '이름이 바뀌었으면 이 테스트도 같이 고칠 것(계약은 순서다)')
    return m.group(1)


def test_앱_자신의_scripts_가_맨_앞이다():
    block = _candidate_block()
    lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith('#')]
    assert lines, '후보 목록이 비었다'
    assert '_SCRIPTS_DIR' in lines[0], (
        f'첫 후보가 앱 자신의 scripts/ 가 아니다: {lines[0]!r}\n'
        '  데몬은 이 앱의 것이다. 사용자 프로젝트 폴더가 먼저 오면 남의 옛 사본을 띄운다\n'
        '  (2026-08-17: D:\\CipherTrader\\scripts\\hive_watchdog.py → ModuleNotFoundError).')


def test_사용자_프로젝트_폴더는_맨_뒤다():
    block = _candidate_block()
    lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith('#')]
    proj = [i for i, ln in enumerate(lines) if 'PROJECT_ROOT' in ln]
    assert proj, 'PROJECT_ROOT 후보가 사라졌다 — 아주 빼면 bare 체크아웃에서 데몬이 죽는다'
    assert proj[0] == len(lines) - 1, (
        f'PROJECT_ROOT 후보가 맨 뒤가 아니다(위치 {proj[0]} / 총 {len(lines)}).\n'
        '  사용자가 연 폴더는 **마지막 후보**여야 한다.')


def test_앱_scripts_에_데몬이_실재한다():
    """계약이 맞아도 파일이 없으면 소용없다 — 이 저장소 기준으로 실물 확인."""
    scripts = SERVER.parent.parent / 'scripts'
    for name in ('hive_watchdog.py', 'codex_pg_watcher.py'):
        assert (scripts / name).exists(), f'{name} 이 앱 scripts/ 에 없다'
