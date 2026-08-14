#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: src/session_recycle.py
DESCRIPTION: 컨텍스트 리사이클 상태머신 — 세션을 마감 기록으로 봉인하고 새 컨텍스트로
             교체한 뒤 재정박한다. GUARD 판정은 순수 함수, 실행은 주입된 deps 경유.
             설계 근거는 docs/HARNESS_DESIGN.md §2.

REVISION HISTORY:
- 2026-08-05 Claude: 최초 구현 — 하네스 v2.1 분석에서 도출(① 컨텍스트 리사이클)
- 2026-08-14 Claude: 근거 문서 경로 갱신 — Discord 계획서 폐기(커넥터 전면 제거)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from brief_limits import enforce

# 상태 전이: '' → sealing → draining → swapping → reanchoring → ''
STATES = ('sealing', 'draining', 'swapping', 'reanchoring')

# [WHY] 플래핑 방지 60초 — 리사이클 직후 컨텍스트 계측이 아직 옛 세션 파일을 가리켜
#   임계치 초과로 다시 읽힐 수 있다. 계측 원천(jsonl)이 갱신될 여유를 준다.
FLAP_GUARD_SEC = 60.0
# [WHY] 사용자 입력 30초 — 자동 트리거가 타이핑 중인 사람의 세션을 죽이는 것이
#   이 기능의 최악 실패 모드다. 수동 요청은 사람이 의도한 것이므로 적용하지 않는다.
USER_ACTIVE_SEC = 30.0
DRAIN_TIMEOUT_SEC = 20.0
DEFAULT_THRESHOLD = 85.0

# [P0 계측 2026-08-05] 자동 트리거 가능 CLI — 실측으로 확정한 화이트리스트.
#   claude:      ~/.claude/projects/*/*.jsonl (639개) → context_used/200k 정상
#   codex:       ~/.codex/sessions/**/rollout-*.jsonl → last_token_usage 79.2% 실측
#   antigravity: /api/antigravity-context-usage가 폐기 경로(~/.gemini/tmp/*/chats)를
#     읽고 있어 항상 화석(mtime 5/26)만 본다. 실제 대화는 antigravity-cli/conversations
#     /*.db(SQLite, 8/4)라 계측 자체가 불가 → 자동 트리거에서 제외하고 수동만 허용.
#     agy용 파서가 생기면 여기에 추가하고 daemons 임계치 폴링도 함께 열 것.
AUTO_TRIGGER_CLIS = ('claude', 'codex')


@dataclass
class GuardInput:
    """GUARD 판정 입력 — 전부 호출부가 수집해서 넣는다(이 모듈은 I/O를 안 한다)."""
    trigger: str = 'manual'              # 'auto' | 'manual'
    cli: str = 'claude'
    recycle_state: str = ''
    awaiting_approval: bool = False
    seconds_since_last_input: float | None = None
    seconds_since_last_recycle: float | None = None
    context_pct: float | None = None
    threshold: float = DEFAULT_THRESHOLD
    force: bool = False


@dataclass
class Decision:
    allowed: bool
    reason: str = ''
    detail: str = ''


@dataclass
class RecycleResult:
    ok: bool = False
    stage: str = ''
    reason: str = ''
    token: str = ''
    reanchor_chars: int = 0
    truncated: bool = False
    fallback_path: str = ''
    stages: list[str] = field(default_factory=list)


def plan_recycle(gi: GuardInput) -> Decision:
    """재시작 가능/금지 판정. 순수 함수 — 부작용 없음, 테스트가 이 함수를 직접 친다.

    [불변식] already_running은 force로도 못 뚫는다 — 그건 사용자 의도가 아니라
      실제 동시 실행 경쟁이고, 뚫으면 PTY를 두 번 죽여 세션을 잃는다.
    """
    if gi.recycle_state:
        return Decision(False, 'already_running', f'현재 단계: {gi.recycle_state}')

    if gi.force:
        return Decision(True, 'forced')

    if gi.awaiting_approval:
        return Decision(False, 'awaiting_approval', '승인 대기 프롬프트가 떠 있음')

    if (gi.seconds_since_last_recycle is not None
            and gi.seconds_since_last_recycle < FLAP_GUARD_SEC):
        return Decision(False, 'flap_guard',
                        f'{gi.seconds_since_last_recycle:.0f}초 전 리사이클됨')

    if gi.trigger != 'auto':
        return Decision(True, 'manual')

    # ── 이하 자동 트리거 전용 ──
    if gi.cli not in AUTO_TRIGGER_CLIS:
        return Decision(False, 'cli_not_measurable',
                        f'{gi.cli}는 컨텍스트 계측 불가 — 수동 리사이클만 가능')

    if (gi.seconds_since_last_input is not None
            and gi.seconds_since_last_input < USER_ACTIVE_SEC):
        return Decision(False, 'user_active',
                        f'{gi.seconds_since_last_input:.0f}초 전 사용자 입력')

    if gi.context_pct is None:
        return Decision(False, 'no_measurement', '컨텍스트 사용률을 읽지 못함')

    if gi.context_pct < gi.threshold:
        return Decision(False, 'below_threshold',
                        f'{gi.context_pct:.1f}% < {gi.threshold:.1f}%')

    return Decision(True, 'threshold_reached', f'{gi.context_pct:.1f}%')


def build_reanchor(checkpoint: dict) -> tuple[str, dict]:
    """마감 기록 → 새 세션 첫 주입 프롬프트. 상한(1500자)은 brief_limits가 강제.

    [WHY] 규칙 파일 '내용'이 아니라 '경로'만 넣는다 — 새 세션은 CLAUDE.md를 자동
      로드하므로 본문을 복사하면 같은 내용을 두 번 먹여 컨텍스트를 낭비한다.
      리사이클의 목적이 컨텍스트 절약인데 재정박이 뚱뚱하면 자기모순이다.
    """
    intent = (checkpoint.get('intent') or '').strip()
    next_step = (checkpoint.get('next_step') or '').strip()
    decisions = checkpoint.get('decisions') or []
    files = checkpoint.get('modified_files') or []

    lines = ['[세션 이어받기] 이전 세션이 컨텍스트 한계로 교체됐다. 아래에서 계속한다.', '']
    if intent:
        lines.append(f'■ 하던 일: {intent}')
    if next_step:
        lines.append(f'■ 다음 할 일: {next_step}')
    if decisions:
        lines.append('■ 확정된 결정 (재논의 금지):')
        lines += [f'  - {d}' for d in decisions[-5:]]
    if files:
        lines.append(f'■ 건드린 파일: {", ".join(files[:12])}')
        if len(files) > 12:
            lines.append(f'  (외 {len(files) - 12}개)')
    lines += ['', '■ 규칙: CLAUDE.md + .claude/rules/ 참조 (본문은 자동 로드됨)',
              '재설명을 요구하지 말고 위 "다음 할 일"부터 바로 진행할 것.']

    return enforce('reanchor', '\n'.join(lines))


def make_token(terminal_id: str, started_at: str) -> str:
    """멱등 토큰 — 같은 토큰의 재요청은 no-op, 다른 토큰은 경쟁으로 간주."""
    return f'{terminal_id}:{started_at}'


def execute_recycle(gi: GuardInput, deps, terminal_id: str, token: str) -> RecycleResult:
    """상태머신 실행. deps는 아래 호출자를 가진 객체(테스트는 가짜를 주입).

      seal(payload) -> bool          마감 기록 저장
      collect_checkpoint() -> dict   저장된 마감 기록 회수
      set_state(state, token) -> None
      drain(timeout) -> bool         진행 중 도구 종료 대기
      user_active() -> bool          SWAP 직전 재확인
      terminate() -> bool            기존 PTY 종료
      spawn() -> bool                새 PTY 기동
      inject(text) -> bool           재정박 주입
      save_fallback(text) -> str     SWAP/주입 실패 시 프롬프트를 파일로 보존

    [불변식 1] SEAL 실패 → terminate 호출 금지. 기록 없이 죽이면 세션이 통째로 증발한다
      (통합 계획 보안 불변식 10). 이 순서는 어떤 최적화로도 바꾸지 않는다.
    [불변식 2] GUARD를 통과했어도 SWAP 직전 user_active를 한 번 더 본다 —
      GUARD와 SWAP 사이(SEAL+DRAIN 최대 20초)에 사람이 타이핑을 시작할 수 있다.
    """
    res = RecycleResult(token=token)

    decision = plan_recycle(gi)
    if not decision.allowed:
        res.stage, res.reason = 'guard', decision.reason
        return res
    res.stages.append('guard')

    # ── SEAL ──
    deps.set_state('sealing', token)
    res.stage = 'sealing'
    if not deps.seal({'terminal_id': terminal_id, 'trigger': gi.trigger}):
        deps.set_state('', '')
        res.reason = 'seal_failed'
        return res           # [불변식 1] 여기서 반드시 멈춘다
    res.stages.append('sealing')

    # ── DRAIN ──
    deps.set_state('draining', token)
    res.stage = 'draining'
    if not deps.drain(DRAIN_TIMEOUT_SEC):
        # 자동 트리거는 물러난다 — 강제 진행은 도중 작업을 끊을 수 있고,
        # 자동은 "다음 기회"가 60초 뒤에 또 온다. 수동은 사람이 의도했으므로 진행.
        if gi.trigger == 'auto' and not gi.force:
            deps.set_state('', '')
            res.reason = 'drain_timeout'
            return res
    res.stages.append('draining')

    # ── SWAP ──
    if gi.trigger == 'auto' and not gi.force and deps.user_active():
        deps.set_state('', '')
        res.stage, res.reason = 'swapping', 'user_active_late'
        return res           # [불변식 2] 늦게 들어온 사용자 입력 존중

    checkpoint = deps.collect_checkpoint() or {}
    reanchor, info = build_reanchor(checkpoint)
    res.reanchor_chars = len(reanchor)
    res.truncated = bool(info.get('truncated'))

    deps.set_state('swapping', token)
    res.stage = 'swapping'
    if not deps.terminate():
        deps.set_state('', '')
        res.reason = 'terminate_failed'
        return res
    if not deps.spawn():
        # 옛 세션은 죽었고 새 세션은 안 떴다 — 재정박 프롬프트만은 반드시 건진다.
        res.fallback_path = deps.save_fallback(reanchor) or ''
        deps.set_state('', '')
        res.reason = 'spawn_failed'
        return res
    res.stages.append('swapping')

    # ── REANCHOR ──
    deps.set_state('reanchoring', token)
    res.stage = 'reanchoring'
    if not deps.inject(reanchor):
        res.fallback_path = deps.save_fallback(reanchor) or ''
        deps.set_state('', '')
        res.reason = 'inject_failed'
        return res
    res.stages.append('reanchoring')

    deps.set_state('', '')
    res.ok, res.stage, res.reason = True, 'done', decision.reason
    return res
