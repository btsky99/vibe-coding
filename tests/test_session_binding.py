#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: tests/test_session_binding.py
DESCRIPTION: 세션↔슬롯 결속 + 화석(stale) 판정 회귀 테스트. 방어 대상은
             2026-08-14 사고 — 끝난 세션의 85.3%로 T1·T2가 60초마다 동시 처형됨.
             핵심 불변식은 "결속을 확정 못 하면 아무도 죽이지 않는다".

REVISION HISTORY:
- 2026-08-14 Claude: 최초 작성 — src/session_binding 구현과 동시
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MON = Path(__file__).resolve().parent.parent / '.ai_monitor'
sys.path.insert(0, str(_MON / 'src'))
sys.path.insert(0, str(_MON))

import pytest  # noqa: E402

import session_binding as sb  # noqa: E402
from infra.daemons import plan_terminal_recycles  # noqa: E402
from infra.session_parse import parse_session_tail  # noqa: E402


@pytest.fixture()
def daemons_plan():
    """워처의 처형 판정(순수 함수). 무한 루프 밖으로 뺀 덕에 직접 검증 가능."""
    return plan_terminal_recycles

NOW = datetime(2026, 8, 14, 8, 0, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


def iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace('+00:00', 'Z')


def write_session(dirpath: Path, name: str, cwd: str, first_min: float,
                  last_min: float, tokens: int, model: str = 'claude-opus-5') -> Path:
    """결속 판정에 필요한 최소 형태의 claude 세션 jsonl을 만든다."""
    path = dirpath / f'{name}.jsonl'
    lines = [{'type': 'user', 'sessionId': name, 'cwd': cwd,
              'timestamp': iso(first_min)}]
    if tokens > 0:
        lines.append({
            'type': 'assistant', 'sessionId': name, 'cwd': cwd,
            'timestamp': iso(last_min),
            'message': {'model': model,
                        'usage': {'input_tokens': tokens, 'output_tokens': 10,
                                  'cache_read_input_tokens': 0,
                                  'cache_creation_input_tokens': 0}},
        })
    path.write_text('\n'.join(json.dumps(o) for o in lines) + '\n', encoding='utf-8')
    # 실제 환경에서 mtime과 마지막 레코드 시각은 일치한다. 결속이 mtime을
    # 대조 신호로 쓰므로 테스트도 그 관계를 지켜야 의미가 있다.
    touch(path, last_min if tokens > 0 else first_min)
    return path


def touch(path: Path, minutes_ago: float) -> None:
    ts = (NOW - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(path, (ts, ts))


def slot(tid: str, cwd: str, started_min: float, output_min: float | None = None) -> dict:
    s = {'terminal_id': tid, 'running': True, 'agent': 'claude',
         'cwd': cwd, 'started': iso(started_min)}
    if output_min is not None:
        s['last_output_at'] = int((NOW - timedelta(minutes=output_min)).timestamp() * 1000)
    return s


@pytest.fixture()
def projects(tmp_path, monkeypatch):
    """~/.claude/projects 를 tmp로 갈아끼운다."""
    home = tmp_path / 'home'
    (home / '.claude' / 'projects' / 'D--sample-proj').mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: home))
    return home / '.claude' / 'projects' / 'D--sample-proj'


# ── 사고 재현 ────────────────────────────────────────────────────────────

def test_화석은_결속되지_않는다(projects):
    """2026-08-14 사고 그대로: 어제 끝난 85.3% 세션 + 방금 뜬 슬롯 2개."""
    write_session(projects, 'fossil', 'D:/sample-proj', first_min=1200, last_min=420,
                  tokens=853_206)                       # 7시간 전 마지막 쓰기
    write_session(projects, 'fresh1', 'D:/sample-proj', first_min=5, last_min=1, tokens=1000)
    write_session(projects, 'fresh2', 'D:/sample-proj', first_min=3, last_min=1, tokens=1000)

    slots = [slot('T1', 'D:/sample-proj', started_min=6), slot('T2', 'D:/sample-proj', started_min=4)]
    bound = sb.bind_slots(slots, sb.collect_claude_sessions({'d:/sample-proj'}, NOW_EPOCH))

    assert set(bound) == {'T1', 'T2'}
    assert 'fossil' not in bound['T1']['path']
    assert 'fossil' not in bound['T2']['path']
    # 나중에 뜬 슬롯이 나중에 생긴 대화를 갖는다
    assert 'fresh2' in bound['T2']['path']
    assert 'fresh1' in bound['T1']['path']


def test_화석만_있으면_계측_불가_처형_대상_아님(projects):
    """옛 로직이 T1·T2를 죽인 조건 — 이제는 available=False라 아무도 안 죽는다."""
    write_session(projects, 'fossil', 'D:/sample-proj', first_min=1200, last_min=420,
                  tokens=853_206)
    slots = [slot('T1', 'D:/sample-proj', started_min=6), slot('T2', 'D:/sample-proj', started_min=4)]

    got = sb.measure_terminals(slots, NOW_EPOCH)

    assert set(got) == {'T1', 'T2'}
    for tid in ('T1', 'T2'):
        assert got[tid]['available'] is False
        assert got[tid]['reason'] == 'unbound_session'


def test_장수_슬롯이_화석을_물면_stale로_드러난다(projects):
    """슬롯이 오래 살아 화석이 결속 조건을 통과하는 경우의 2차 방어선."""
    write_session(projects, 'fossil', 'D:/sample-proj', first_min=1200, last_min=420,
                  tokens=853_206)
    slots = [slot('T1', 'D:/sample-proj', started_min=1300)]   # 슬롯이 세션보다 먼저 떴다

    m = sb.measure_terminals(slots, NOW_EPOCH)['T1']

    assert m['available'] is True          # 계측 자체는 된다(codex와 동일 계약)
    assert m['percentage'] == 85.3
    assert m['stale'] is True              # 처형 차단은 호출부가 이 플래그로 한다
    assert m['session_age_sec'] == pytest.approx(420 * 60, abs=2)


def test_살아있는_세션은_stale이_아니다(projects):
    write_session(projects, 'live', 'D:/sample-proj', first_min=60, last_min=2, tokens=900_000)
    m = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=61)], NOW_EPOCH)['T1']

    assert m['available'] is True and m['stale'] is False
    assert m['percentage'] == 90.0         # opus-5 → 1M 창


# ── 오배정 방지 ──────────────────────────────────────────────────────────

def test_다른_프로젝트_세션은_결속되지_않는다(projects):
    write_session(projects, 'other', 'D:/CipherTrader', first_min=5, last_min=1,
                  tokens=900_000)
    got = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=6)], NOW_EPOCH)

    assert got['T1']['reason'] == 'unbound_session'


def test_슬롯보다_먼저_시작된_대화는_결속되지_않는다(projects):
    """--continue/--resume 케이스 — 안 죽는 쪽으로 실패해야 한다."""
    write_session(projects, 'resumed', 'D:/sample-proj', first_min=600, last_min=1,
                  tokens=900_000)
    got = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=5)], NOW_EPOCH)

    assert got['T1']['available'] is False
    assert got['T1']['reason'] == 'unbound_session'


def test_시계_스큐는_관용_마진이_흡수한다(projects):
    """대화가 슬롯보다 1분 '먼저' 기록돼도 결속은 유지된다(마진 3분)."""
    write_session(projects, 'skewed', 'D:/sample-proj', first_min=6, last_min=1, tokens=900_000)
    got = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=5)], NOW_EPOCH)

    assert got['T1']['available'] is True and got['T1']['percentage'] == 90.0


def test_남의_슬롯에서_진행중인_대화는_거부된다(projects):
    """last_output_at 판별자 — 내가 출력한 적 없는 시각의 대화는 내 것이 아니다."""
    write_session(projects, 'busy', 'D:/sample-proj', first_min=10, last_min=1, tokens=900_000)
    # 슬롯은 9분째 아무것도 출력하지 않았는데 대화는 1분 전까지 진행됐다
    got = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=11, output_min=9)],
                               NOW_EPOCH)

    assert got['T1']['reason'] == 'unbound_session'


def test_한_세션은_한_슬롯에만_배정된다(projects):
    write_session(projects, 'only', 'D:/sample-proj', first_min=5, last_min=1, tokens=900_000)
    slots = [slot('T1', 'D:/sample-proj', started_min=6), slot('T2', 'D:/sample-proj', started_min=6)]

    bound = sb.bind_slots(slots, sb.collect_claude_sessions({'d:/sample-proj'}, NOW_EPOCH))

    assert len(bound) == 1


# ── 잡음 방지 ────────────────────────────────────────────────────────────

def test_빈_세션_파일은_후보가_아니다(projects):
    (projects / 'empty.jsonl').write_text('', encoding='utf-8')
    assert sb.collect_claude_sessions({'d:/sample-proj'}, NOW_EPOCH) == []


def test_응답_전_세션은_임계_판정에서_빠진다(projects):
    """태어나자마자 죽던 세션 — 0%로 보고하면 '여유 있음'과 구분이 안 된다."""
    write_session(projects, 'newborn', 'D:/sample-proj', first_min=1, last_min=1, tokens=0)
    m = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=2)], NOW_EPOCH)['T1']

    assert m['available'] is False and m['reason'] == 'no_usage_yet'


def test_죽은_슬롯은_계측하지_않는다(projects):
    write_session(projects, 'live', 'D:/sample-proj', first_min=5, last_min=1, tokens=900_000)
    dead = {**slot('T1', 'D:/sample-proj', started_min=6), 'running': False}

    assert sb.measure_terminals([dead], NOW_EPOCH) == {}


def test_거대한_tool_result가_꼬리를_먹어도_usage를_찾는다(projects):
    """8KB 꼬리에 usage가 안 걸리는 실제 상황 — 못 찾으면 자동이 조용히 0회가 된다."""
    path = write_session(projects, 'huge', 'D:/sample-proj', first_min=10, last_min=2,
                         tokens=900_000)
    # assistant usage 뒤에 32KB짜리 tool_result 한 줄을 붙인다
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'type': 'user', 'sessionId': 'huge', 'cwd': 'D:/sample-proj',
                            'timestamp': iso(1), 'blob': 'x' * 32_000}) + '\n')
    touch(path, 1)

    assert (parse_session_tail(path) or {}).get('input_tokens', 0) == 0  # 기본 8KB는 놓친다
    assert sb.parse_usage_deep(path)['input_tokens'] == 900_000

    m = sb.measure_terminals([slot('T1', 'D:/sample-proj', started_min=11)], NOW_EPOCH)['T1']
    assert m['available'] is True and m['percentage'] == 90.0


# ── 워처 판정 (2회 사고 지점) ────────────────────────────────────────────

def test_처형은_임계를_넘긴_그_터미널_하나뿐(daemons_plan):
    """팬아웃 금지 — 세션 하나의 수치로 옆 슬롯을 죽이지 않는다(2026-08-14)."""
    terminals = {
        'T1': {'cli': 'claude', 'available': True, 'percentage': 91.0, 'stale': False},
        'T2': {'cli': 'claude', 'available': True, 'percentage': 12.0, 'stale': False},
    }
    targets, _ = daemons_plan(terminals, {'claude', 'codex'}, 85.0)

    assert targets == [('T1', 'claude', 91.0)]


def test_화석은_처형하지_않고_기록만_남긴다(daemons_plan):
    terminals = {'T1': {'cli': 'claude', 'available': True, 'percentage': 85.3,
                        'stale': True, 'session_age_sec': 26403}}
    targets, notes = daemons_plan(terminals, {'claude'}, 85.0)

    assert targets == []
    assert notes and '화석' in notes[0][1] and '7.3시간' in notes[0][1]


def test_결속_실패는_처형_대상이_아니며_침묵하지_않는다(daemons_plan):
    terminals = {'T1': {'cli': 'claude', 'available': False,
                        'reason': 'unbound_session'}}
    targets, notes = daemons_plan(terminals, {'claude'}, 85.0)

    assert targets == []
    assert notes[0][0] == 'unbound:T1'


def test_자동_대상_아닌_CLI는_건드리지_않는다(daemons_plan):
    terminals = {'T1': {'cli': 'antigravity', 'available': True,
                        'percentage': 99.0, 'stale': False}}
    assert daemons_plan(terminals, {'claude', 'codex'}, 85.0) == ([], [])


def test_tz_없는_타임스탬프는_UTC로_읽는다():
    """KST 로컬 해석으로 새면 9시간이 어긋나 결속이 전부 실패한다."""
    assert sb.parse_iso('2026-08-14T08:00:00') == NOW_EPOCH
    assert sb.parse_iso('2026-08-14T08:00:00Z') == NOW_EPOCH
    assert sb.parse_iso('') is None and sb.parse_iso('garbage') is None
