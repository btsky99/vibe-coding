# -*- coding: utf-8 -*-
"""
FILE: tests/test_installer_run_commands.py
DESCRIPTION: 인스톨러 [Run] 의 PowerShell 명령이 **문법적으로 성립하는지** 고정한다.

             [🔴 왜 생겼나 — 2026-08-17 사장 신고] "설치했는데 목소리 안 나오고,
               설치 시 에러도 나는 것 같다." 설치 로그를 뜯어 보니 [Run] 네 개가
               **전부 `Process exit code: 1`** 이었다. 원인은 중괄호 이스케이프:
                 · Inno 는 `{` 로 상수를 연다 → 리터럴 `{` 는 `{{` 로 적는 것이 맞다
                 · 그런데 닫는 `}` 는 이스케이프가 **필요 없다**. `}}` 로 적으면
                   `}` 두 개가 그대로 나가 PowerShell 이 파싱에 실패한다
               실제로 나간 명령: `... -ErrorAction SilentlyContinue }} catch {}}`
               그중 첫 번째가 **Windows Defender 예외 등록**이다. 그것이 실패하면
               PyInstaller EXE(빌드마다 해시가 바뀐다)가 격리 대상이 되어,
               앱은 뜨는데 **자식으로 뜨는 음성 사이드카만 조용히 죽는** 모양이 된다.

             [🔴 이 사고가 3주씩 안 잡히는 이유] 설치는 조용히 끝난다(exit 0). 실패한 것은
               [Run] 항목뿐이라 화면에 아무 말도 안 뜨고, 로그를 열어야만 보인다.
               그래서 **기계가 대신 본다** — 이 테스트가 그 자리다.

             [제약] PowerShell 이 있는 환경에서만 실제 파싱을 한다. 없으면 중괄호 균형만
               본다 — 그것만으로도 이번 사고는 잡힌다.

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — [Run] 네 개가 전부 exit 1 이던 사고
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ISS = Path(__file__).resolve().parent.parent / 'vibe-coding-setup.iss'


def _run_params() -> list[tuple[int, str]]:
    """[Run] 의 powershell.exe 항목에서 -Command 뒤의 실제 명령을 뽑는다."""
    out = []
    for i, line in enumerate(ISS.read_text(encoding='utf-8').splitlines(), 1):
        if not line.startswith('Filename: "powershell.exe"'):
            continue
        m = re.search(r'Parameters:\s*"(.*?)";\s*Flags', line)
        if not m:
            continue
        params = m.group(1)
        cmd = params.split('-Command ', 1)[1] if '-Command ' in params else params
        # Inno 의 이스케이프를 실제로 나가는 글자로 되돌린다
        cmd = cmd.replace('""', '"')                 # iss 문자열 안의 "" → "
        if cmd.startswith('"') and cmd.endswith('"'):
            cmd = cmd[1:-1]
        cmd = cmd.replace('{{', '{')                 # 리터럴 중괄호
        # Inno 상수/전처리기는 설치 때 값으로 바뀐다 — 파싱에는 아무 경로나 넣으면 된다
        cmd = re.sub(r'\{#?[A-Za-z][\w]*\}', 'C:\\\\dummy', cmd)
        out.append((i, cmd))
    return out


def test_run_항목이_실제로_있다():
    got = _run_params()
    assert got, '[Run] 의 powershell 항목을 하나도 못 찾았다 — 정규식이 iss 와 어긋났다'


@pytest.mark.parametrize('lineno,cmd', _run_params(),
                         ids=[f'line{n}' for n, _ in _run_params()])
def test_중괄호가_짝이_맞는다(lineno, cmd):
    """🔴 이번 사고를 직접 잡는 검사 — `}` 가 `{` 보다 많으면 그것이 그 버그다."""
    opens, closes = cmd.count('{'), cmd.count('}')
    assert opens == closes, (
        f'iss {lineno}행: 중괄호 짝이 안 맞는다({{ {opens}개 vs }} {closes}개). '
        f'Inno 에서 닫는 중괄호는 이스케이프하지 않는다 — `}}}}` 로 적으면 '
        f'`}}` 두 개가 나가 PowerShell 이 죽는다(2026-08-17 사고).')


@pytest.mark.parametrize('lineno,cmd', _run_params(),
                         ids=[f'line{n}' for n, _ in _run_params()])
def test_파워셸이_실제로_파싱한다(lineno, cmd):
    """실행하지 않고 **파싱만** 시킨다 — 문법 오류면 여기서 걸린다."""
    ps = shutil.which('powershell') or shutil.which('pwsh')
    if not ps:
        pytest.skip('powershell 이 없는 환경 — 중괄호 검사로 갈음한다')
    probe = (
        '$src = [Console]::In.ReadToEnd(); $errs = $null; '
        '[void][System.Management.Automation.Language.Parser]::ParseInput('
        '$src, [ref]$null, [ref]$errs); '
        'if ($errs.Count -gt 0) { $errs[0].Message; exit 1 } else { exit 0 }'
    )
    r = subprocess.run([ps, '-NoProfile', '-NonInteractive', '-Command', probe],
                       input=cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert r.returncode == 0, (
        f'iss {lineno}행의 명령이 PowerShell 문법 오류다 → 설치 때 exit 1 로 조용히 실패한다.\n'
        f'  파서 메시지: {(r.stdout or "").strip()[:200]}\n'
        f'  명령 앞부분: {cmd[:160]}')
