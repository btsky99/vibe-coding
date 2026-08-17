# -*- coding: utf-8 -*-
"""
FILE: tests/test_updater_recheck.py
DESCRIPTION: 갱신 확인이 **연달아 나온 판을 놓치지 않는지** 고정한다.

             [🔴 왜 이 테스트가 생겼나 — 2026-08-17 사장 신고]
               "기존에 설치되어 있는 거에서 업데이트가 안 떠."
               조사 결과 그날의 직접 원인은 '앱이 새 판 발행 전에 꺼져 있었다'였지만,
               코드를 짚다가 **진짜 눈먼 자리**가 같이 나왔다:
               server.py 의 _update_loop 가 `update_ready.json` 에 ready=true 가 있으면
               check_and_update 를 **아예 부르지 않았다.** 되받기(434MB)를 막으려던 것인데,
               그 대가로 342 를 받아 둔 앱은 그 뒤에 나온 343·344 를 영영 모른다.
               실제로 그날 새벽 세 판이 한 시간 안에 발행됐다 — 흔한 상황이다.

             [고정하는 계약]
               ① 이미 받아 둔 것과 **같은 판**이면 다시 받지 않는다(되받기 방지는 유지).
               ② 받아 둔 것보다 **새 판**이 나오면 반드시 다시 받는다(눈먼 자리 제거).
               ③ 받아 둔 파일이 사라졌으면 다시 받는다(캐시만 믿지 않는다).

             [제약] 네트워크를 타지 않는다 — _fetch_latest_release 와 실제 내려받기를
               가짜로 갈아 끼운다. 이 테스트가 회선 상태에 따라 깜빡이면 아무도 안 믿는다.

REVISION HISTORY:
- 2026-08-17 Claude: 최초 작성 — '받아 뒀으면 확인도 안 한다'가 되살아나지 않게
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))
import updater  # noqa: E402


def _release(tag: str) -> dict:
    return {
        'tag_name': tag,
        'assets': [{
            'name': f'vibe-coding-setup-{tag.lstrip("v")}.exe',
            'browser_download_url': f'https://example.invalid/{tag}.exe',
            'size': 1234,
        }],
    }


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """번들 버전을 3.7.341 로 고정하고, 내려받기를 '했다고 치는' 가짜로 바꾼다."""
    monkeypatch.setattr(updater, 'bundle_version', lambda: '3.7.341')
    monkeypatch.setattr(updater.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updater, '_get_token', lambda d: None)

    calls: list[str] = []

    def fake_download(url, dest, token, progress_cb=None, expected_size=0, expected_digest=''):
        calls.append(url)
        # [🔴 기대 크기를 그대로 맞춘다] 크기가 어긋나면 updater 가 '잘린 파일'로 보고
        #   ready 기록을 지운다(2026-08-05 사고 방어). 그러면 이 테스트가 재다운로드를
        #   '눈먼 자리'로 오해해 엉뚱한 곳을 가리킨다.
        Path(dest).write_bytes(b'x' * (expected_size or 16))
        return True

    monkeypatch.setattr(updater, '_download_asset', fake_download)
    monkeypatch.setattr(updater, '_verify_digest', lambda *a, **k: True)
    return tmp_path, calls, monkeypatch


def test_같은_판이면_다시_받지_않는다(rig):
    data, calls, mp = rig
    mp.setattr(updater, '_fetch_latest_release', lambda t: _release('v3.7.344'))
    updater.check_and_update(data)
    assert len(calls) == 1, '처음에는 받아야 한다'

    updater.check_and_update(data)              # 같은 판을 한 번 더
    assert len(calls) == 1, '같은 판을 다시 받으면 10분마다 434MB 를 되받는다'


def test_더_새_판이_나오면_다시_받는다(rig):
    """🔴 이 테스트가 이번 사고의 핵심이다 — 예전 구조는 여기서 실패한다."""
    data, calls, mp = rig
    mp.setattr(updater, '_fetch_latest_release', lambda t: _release('v3.7.342'))
    updater.check_and_update(data)
    assert len(calls) == 1

    # 한 시간 안에 다음 판이 나왔다(2026-08-17 실제 상황)
    mp.setattr(updater, '_fetch_latest_release', lambda t: _release('v3.7.344'))
    updater.check_and_update(data)
    assert len(calls) == 2, '받아 둔 판이 있어도 더 새 판은 반드시 받아야 한다'

    saved = json.loads((data / 'update_ready.json').read_text(encoding='utf-8'))
    assert saved['version'] == 'v3.7.344'


def test_받아_둔_파일이_사라지면_다시_받는다(rig):
    data, calls, mp = rig
    mp.setattr(updater, '_fetch_latest_release', lambda t: _release('v3.7.344'))
    updater.check_and_update(data)
    assert len(calls) == 1

    saved = json.loads((data / 'update_ready.json').read_text(encoding='utf-8'))
    Path(saved['exe_path']).unlink()             # 사용자가 지웠거나 청소 도구가 치웠다
    updater.check_and_update(data)
    assert len(calls) == 2, '기록만 믿고 없는 파일을 ready 로 두면 눌러도 아무 일이 없다'
