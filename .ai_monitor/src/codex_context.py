#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: src/codex_context.py
DESCRIPTION: Codex CLI 세션의 현재 컨텍스트 점유율 파서. rollout jsonl의
             token_count 이벤트에서 last_token_usage/model_context_window를 읽는다.
             claude 전용이던 /api/context-usage의 codex 공백을 메우는 유일한 원천.

REVISION HISTORY:
- 2026-08-05 Claude: 최초 구현 — 리사이클 P0 계측에서 codex 계측 부재 확인 후 신설
- 2026-08-09 Claude: session_age_sec/stale 노출 — 끝난 세션의 화석 사용률이
  현재값처럼 보이던 문제(실측: 5일 전 rollout이 79.2%로 표시)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# [WHY 6시간] rollout jsonl은 턴마다 갱신되므로, 이보다 오래 멈춘 파일은
#   'codex를 안 쓰는 중'일 가능성이 높다. 다만 유휴 상태로 살아 있는 세션도
#   같은 모습이라 available=False로 죽이지 않는다 — 자동 리사이클의 실제
#   차단은 '그 CLI가 실제 돌고 있는 터미널이 있는가'(infra/daemons._targets)가
#   맡고, 여기서는 화석임을 드러내기만 한다(관측이 거짓이면 판단도 거짓).
STALE_AFTER_SEC = 6 * 3600

# [원천] ~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<uuid>.jsonl
#   claude(~/.claude/projects/<slug>/*.jsonl)와 달리 날짜 3중 디렉터리라
#   glob 패턴이 다르다. codex CLI가 경로 규칙을 바꾸면 여기만 고치면 된다.
_SESSION_GLOB = 'sessions/*/*/*/rollout-*.jsonl'


def _codex_home() -> Path:
    return Path.home() / '.codex'


def latest_session_file(codex_home: Path | None = None) -> Path | None:
    """가장 최근에 수정된 rollout 파일. 없으면 None."""
    root = codex_home or _codex_home()
    try:
        files = list(root.glob(_SESSION_GLOB))
    except OSError:
        return None
    if not files:
        return None
    try:
        return max(files, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


def parse_token_count(path: Path) -> dict | None:
    """rollout jsonl의 '마지막' token_count 이벤트를 돌려준다.

    [WHY] 파일을 끝까지 훑는다 — token_count는 턴마다 append되고 우리가 원하는 건
      최신 상태다. tail만 읽는 최적화는 하지 않았는데, 한 줄이 수십 KB인 경우가 있어
      역방향 청크 읽기가 경계에서 JSON을 쪼갤 위험이 실익보다 크다.
    [제약] 손상된 줄은 조용히 건너뛴다 — codex가 쓰는 도중이면 마지막 줄이
      잘려 있을 수 있고, 그것 때문에 전체 계측을 포기하면 안 된다.
    """
    last = None
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if '"token_count"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                payload = obj.get('payload') or obj
                if payload.get('type') == 'token_count':
                    last = payload
    except OSError:
        return None
    return last


def context_usage(codex_home: Path | None = None) -> dict:
    """codex 현재 컨텍스트 점유율.

    반환: {available, percentage, context_used, context_window, session, reason}

    [🔴 함정] total_token_usage를 쓰면 안 된다. 그것은 세션 '누적'이라
      실측에서 28,848,246 / 258,400 = 11164% 같은 무의미한 값이 나온다.
      현재 점유는 직전 턴의 last_token_usage.input_tokens(+output)가 정답이며
      같은 세션 실측에서 204,593 / 258,400 = 79.2%로 타당한 값이 확인됐다.
    """
    path = latest_session_file(codex_home)
    if path is None:
        return {'available': False, 'percentage': 0.0, 'context_used': 0,
                'context_window': 0, 'session': '', 'reason': 'no_session_file'}

    payload = parse_token_count(path)
    if not payload:
        return {'available': False, 'percentage': 0.0, 'context_used': 0,
                'context_window': 0, 'session': path.name, 'reason': 'no_token_count_event'}

    info = payload.get('info') or payload
    last = info.get('last_token_usage') or {}
    window = int(info.get('model_context_window') or 0)
    used = int(last.get('input_tokens') or 0) + int(last.get('output_tokens') or 0)

    if window <= 0:
        return {'available': False, 'percentage': 0.0, 'context_used': used,
                'context_window': 0, 'session': path.name, 'reason': 'no_context_window'}

    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        age = 0.0

    return {
        'available': True,
        'percentage': round(used / window * 100, 1),
        'context_used': used,
        'context_window': window,
        'session': path.name,
        'session_age_sec': round(age),
        'stale': age > STALE_AFTER_SEC,
        'reason': '',
    }
