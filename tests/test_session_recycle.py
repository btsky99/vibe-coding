#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: tests/test_session_recycle.py
DESCRIPTION: 컨텍스트 리사이클 GUARD/상태머신 회귀 테스트. 핵심 방어선은
             "SEAL 실패 시 기존 세션을 죽이지 않는다"(보안 불변식 10).

REVISION HISTORY:
- 2026-08-05 Claude: 최초 작성 — Phase 6 구현과 동시
"""
import sys
from pathlib import Path

_MON = Path(__file__).resolve().parent.parent / '.ai_monitor'
sys.path.insert(0, str(_MON / 'src'))
sys.path.insert(0, str(_MON))

import pytest  # noqa: E402

from brief_limits import LIMITS, check_len, enforce, truncate_smart  # noqa: E402
from session_recycle import (  # noqa: E402
    DEFAULT_THRESHOLD,
    GuardInput,
    build_reanchor,
    execute_recycle,
    plan_recycle,
)


class FakeDeps:
    """상태머신 실행 경로를 기록하는 가짜 의존성."""

    def __init__(self, **fail):
        self.fail = fail
        self.calls = []
        self.states = []
        self.checkpoint = {'intent': '리사이클 구현', 'next_step': '테스트 작성',
                           'decisions': ['컬럼 확장으로 결정'], 'modified_files': ['a.py']}
        self.fallback = ''

    def _hit(self, name):
        self.calls.append(name)
        return not self.fail.get(name, False)

    def set_state(self, state, token):
        self.states.append(state)

    def seal(self, payload):
        return self._hit('seal')

    def collect_checkpoint(self):
        self.calls.append('collect')
        return self.checkpoint

    def drain(self, timeout):
        return self._hit('drain')

    def user_active(self):
        self.calls.append('user_active')
        return self.fail.get('user_active', False)

    def terminate(self):
        return self._hit('terminate')

    def spawn(self):
        return self._hit('spawn')

    def inject(self, text):
        return self._hit('inject')

    def save_fallback(self, text):
        self.calls.append('save_fallback')
        self.fallback = text
        return 'C:/tmp/reanchor-T1.md'


# ────────────────────────── GUARD ──────────────────────────

def test_guard_blocks_when_already_running():
    d = plan_recycle(GuardInput(recycle_state='swapping'))
    assert not d.allowed and d.reason == 'already_running'


def test_guard_already_running_survives_force():
    """force는 사용자 의도지만, 동시 실행 경쟁은 의도로 뚫으면 안 된다."""
    d = plan_recycle(GuardInput(recycle_state='sealing', force=True))
    assert not d.allowed and d.reason == 'already_running'


def test_guard_blocks_awaiting_approval():
    d = plan_recycle(GuardInput(awaiting_approval=True))
    assert not d.allowed and d.reason == 'awaiting_approval'


def test_guard_blocks_flapping():
    d = plan_recycle(GuardInput(seconds_since_last_recycle=5))
    assert not d.allowed and d.reason == 'flap_guard'


def test_guard_auto_blocks_when_user_typing():
    d = plan_recycle(GuardInput(trigger='auto', seconds_since_last_input=3,
                                context_pct=99))
    assert not d.allowed and d.reason == 'user_active'


def test_guard_manual_ignores_user_typing():
    """수동 요청은 사람이 직접 낸 것이므로 타이핑 가드를 적용하지 않는다."""
    d = plan_recycle(GuardInput(trigger='manual', seconds_since_last_input=1))
    assert d.allowed


def test_guard_auto_blocks_below_threshold():
    d = plan_recycle(GuardInput(trigger='auto', context_pct=50))
    assert not d.allowed and d.reason == 'below_threshold'


def test_guard_auto_blocks_unmeasurable_cli():
    """P0 실측: antigravity는 계측 원천이 죽어 있어 자동 트리거 대상이 아니다."""
    d = plan_recycle(GuardInput(trigger='auto', cli='antigravity', context_pct=99))
    assert not d.allowed and d.reason == 'cli_not_measurable'


def test_guard_auto_blocks_when_measurement_missing():
    """계측 실패를 '0%'로 오해해 통과시키거나, 반대로 조용히 도는 일이 없어야 한다."""
    d = plan_recycle(GuardInput(trigger='auto', context_pct=None))
    assert not d.allowed and d.reason == 'no_measurement'


def test_guard_auto_allows_above_threshold():
    d = plan_recycle(GuardInput(trigger='auto', context_pct=DEFAULT_THRESHOLD + 1,
                                seconds_since_last_input=999))
    assert d.allowed and d.reason == 'threshold_reached'


# ─────────────────── 상태머신 (핵심 불변식) ───────────────────

def test_seal_failure_never_terminates_session():
    """🔴 최우선 회귀: 마감 기록에 실패하면 기존 세션을 절대 죽이지 않는다."""
    deps = FakeDeps(seal=True)
    res = execute_recycle(GuardInput(), deps, 'T1', 'tok')
    assert not res.ok
    assert res.reason == 'seal_failed'
    assert 'terminate' not in deps.calls
    assert 'spawn' not in deps.calls
    assert deps.states[-1] == ''      # 상태를 되돌려 다음 시도를 막지 않는다


def test_auto_drain_timeout_backs_off_without_killing():
    deps = FakeDeps(drain=True)
    res = execute_recycle(GuardInput(trigger='auto', context_pct=99,
                                     seconds_since_last_input=999), deps, 'T1', 'tok')
    assert not res.ok and res.reason == 'drain_timeout'
    assert 'terminate' not in deps.calls


def test_manual_drain_timeout_proceeds():
    deps = FakeDeps(drain=True)
    res = execute_recycle(GuardInput(trigger='manual'), deps, 'T1', 'tok')
    assert res.ok and 'terminate' in deps.calls


def test_late_user_input_aborts_before_swap():
    """GUARD 통과 후 SWAP 직전에 타이핑이 시작되면 물러난다(레이스 방어)."""
    deps = FakeDeps(user_active=True)
    res = execute_recycle(GuardInput(trigger='auto', context_pct=99,
                                     seconds_since_last_input=999), deps, 'T1', 'tok')
    assert not res.ok and res.reason == 'user_active_late'
    assert 'terminate' not in deps.calls


def test_spawn_failure_preserves_reanchor_to_file():
    """새 세션 기동 실패 = 세션 상실. 재정박 프롬프트만은 파일로 건진다."""
    deps = FakeDeps(spawn=True)
    res = execute_recycle(GuardInput(), deps, 'T1', 'tok')
    assert not res.ok and res.reason == 'spawn_failed'
    assert res.fallback_path and '다음 할 일' in deps.fallback


def test_inject_failure_preserves_reanchor_to_file():
    deps = FakeDeps(inject=True)
    res = execute_recycle(GuardInput(), deps, 'T1', 'tok')
    assert not res.ok and res.reason == 'inject_failed'
    assert res.fallback_path


def test_happy_path_runs_all_stages_in_order():
    deps = FakeDeps()
    res = execute_recycle(GuardInput(), deps, 'T1', 'tok')
    assert res.ok
    assert res.stages == ['guard', 'sealing', 'draining', 'swapping', 'reanchoring']
    assert deps.calls.index('seal') < deps.calls.index('terminate')
    assert deps.calls.index('terminate') < deps.calls.index('spawn')


def test_guard_rejection_touches_nothing():
    deps = FakeDeps()
    res = execute_recycle(GuardInput(recycle_state='sealing'), deps, 'T1', 'tok')
    assert not res.ok and deps.calls == []


# ─────────────────── 재정박 프롬프트 / 상한 ───────────────────

def test_reanchor_respects_limit_and_keeps_next_step():
    cp = {'intent': '가' * 900, 'next_step': '다음단계표식',
          'decisions': ['나' * 900], 'modified_files': [f'f{i}.py' for i in range(50)]}
    text, info = build_reanchor(cp)
    assert len(text) <= LIMITS['reanchor']
    assert info['truncated']
    # 중간 절단이므로 꼬리(다음 할 일 안내 문구)가 살아 있어야 한다
    assert '바로 진행할 것' in text


def test_reanchor_short_input_not_truncated():
    text, info = build_reanchor({'intent': '짧음', 'next_step': '계속'})
    assert not info['truncated'] and '짧음' in text and '계속' in text


def test_truncate_smart_keeps_head_and_tail():
    src = 'H' * 500 + 'M' * 2000 + 'T' * 500
    out = truncate_smart(src, 1500)
    assert len(out) <= 1500
    assert out.startswith('H') and out.endswith('T')
    assert '생략' in out


def test_truncate_smart_handles_tiny_limit():
    out = truncate_smart('가' * 100, 5)
    assert len(out) <= 5


@pytest.mark.parametrize('kind', list(LIMITS))
def test_enforce_never_exceeds_limit(kind):
    out, info = enforce(kind, '자' * 5000)
    assert len(out) <= LIMITS[kind] and info['truncated']


# ────────── SEAL 기준선 회귀 (통합 결함, 2026-08-05) ──────────

class ClockDeps:
    """RecycleDeps.user_active만 실제 구현으로 시험한다(DB는 _session_clock으로 대체)."""

    def __init__(self, ts, age, seal_ts=None):
        from api.recycle_api import RecycleDeps
        self._real = RecycleDeps('T1', 'p', 'claude')
        self._real._seal_ts = seal_ts
        self._real._session_clock = lambda: (ts, age)

    def user_active(self):
        return self._real.user_active()


def test_user_active_ignores_seal_own_write():
    """🔴 SEAL이 updated_at을 NOW()로 밀어도 '사용자 활동'으로 오판하면 안 된다.

    이 오판이 자동 리사이클을 100% drain_timeout으로 죽였다.
    """
    # SEAL 직후: updated_at == 기준선 → 새 쓰기 없음
    assert ClockDeps(ts=1000.0, age=0.0, seal_ts=1000.0).user_active() is False


def test_user_active_detects_write_after_seal():
    """기준선 이후 훅이 쓰면(=세션이 실제로 움직임) 활동으로 본다."""
    assert ClockDeps(ts=1005.0, age=0.0, seal_ts=1000.0).user_active() is True


def test_user_active_before_seal_uses_age():
    """SEAL 전(GUARD 단계)에는 기준선이 없으므로 나이 기준을 쓴다."""
    assert ClockDeps(ts=1000.0, age=3.0).user_active() is True
    assert ClockDeps(ts=1000.0, age=999.0).user_active() is False


def test_user_active_unknown_does_not_lock_manual():
    """판정 불가를 True로 처리하면 수동 리사이클까지 영구히 잠긴다."""
    assert ClockDeps(ts=None, age=None).user_active() is False


def test_check_len_unknown_kind_falls_back_generously():
    """미등록 종류에 0을 주면 프롬프트가 통째로 잘려 조용히 빈 세션이 된다."""
    ok, _, limit = check_len('unknown-kind', '가' * 100)
    assert ok and limit == max(LIMITS.values())
