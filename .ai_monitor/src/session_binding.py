#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: src/session_binding.py
DESCRIPTION: claude 세션 jsonl ↔ PTY 슬롯 결속 + 터미널별 컨텍스트 점유율 계측.
             "어느 슬롯이 어느 대화 파일을 쓰고 있는가"를 확정해, 자동 리사이클이
             세션 하나의 수치로 무관한 터미널까지 죽이는 것을 막는 원천.

REVISION HISTORY:
- 2026-08-14 Claude: 최초 구현 — 종료된 세션의 화석 수치(16시간 정지, 85.3%)로
  T1·T2가 반복 처형된 사고. 계측은 CLI 전역 1개인데 처형은 터미널 N개였다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from infra.session_parse import claude_ctx_window, parse_session_tail

# [WHY 2시간] claude jsonl은 턴마다 append된다 — 이보다 오래 멈춘 파일은 그 슬롯의
#   '진행 중 대화'로 보기 어렵다. codex(6시간)보다 짧게 잡은 근거: 2026-08-14 사고의
#   화석은 6.75시간 묵은 상태로 처형을 유발했다 — 6시간이면 아슬아슬하게 통과한다.
# [제약] 유휴지만 살아 있는 세션도 겉모습이 같아 available=False로 죽이지 않는다.
#   여기서는 화석임을 드러내기만 하고, 자동 처형 차단은 호출부(infra/daemons)가
#   맡는다 — codex_context.STALE_AFTER_SEC과 동일한 계약.
STALE_AFTER_SEC = 2 * 3600

# [WHY 14일] 결속 후보는 '슬롯이 뜬 뒤 생긴 세션'뿐이다. 슬롯이 2주 넘게 살아 있는
#   경우는 없어(앱 재시작·업데이트가 그 전에 온다) 이보다 오래된 파일을 파싱하는 건
#   순수 낭비다. 워처가 60초마다 도는 경로라 스캔 비용을 여기서 자른다.
_SCAN_WINDOW_SEC = 14 * 86400

# 첫 줄 타임스탬프만 필요하므로 앞부분만 읽는다. 보통 첫 줄은 1KB 미만이지만,
# 대형 붙여넣기가 첫 턴에 오는 경우를 감안해 여유를 뒀다.
_HEAD_BYTES = 64 * 1024

# [WHY 관용 마진] 정상이라면 셸(started)이 먼저 뜨고 대화(first_ts)가 뒤에 생긴다.
#   그런데 PTY가 started를 찍는 시점과 claude가 첫 줄을 쓰는 시점은 다른 프로세스의
#   다른 시계라 초 단위로 뒤집힐 수 있다. 마진 없이 `>=`로 자르면 정상 슬롯이
#   통째로 결속 실패해 자동 리사이클이 조용히 0회가 된다. 3분이면 스큐는 덮으면서
#   '직전 세션을 새 슬롯이 물어가는' 오배정(보통 수십 분~수 시간 차)은 안 덮는다.
_START_GRACE_SEC = 180.0

# [WHY 미래 차단] 세션의 마지막 쓰기가 그 슬롯의 마지막 출력보다 한참 미래면,
#   그 대화는 이 슬롯이 아니라 '지금 다른 슬롯에서 돌고 있는' 것이다. started만
#   보는 결속은 거의 동시에 뜬 두 슬롯을 구분 못 하는데, 이 신호가 그 구멍을 막는다.
#   [제약] detached 슬롯은 last_output_at이 0이라 검증을 건너뛴다(신호 없음).
_OUTPUT_SKEW_SEC = 120.0

# 꼬리 확장 단계. 8KB로 못 찾으면 넓힌다(parse_usage_deep 참조).
_DEEP_TAIL_STEPS = (8 * 1024, 128 * 1024, 1024 * 1024)


def parse_iso(ts: str) -> float | None:
    """ISO8601(Z 접미사 포함) → epoch 초. 파싱 실패는 None."""
    if not ts:
        return None
    try:
        s = str(ts).strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        # [제약] claude/PTY 양쪽 다 UTC로 쓴다. tz 없는 값을 로컬로 해석하면
        #   KST 기준 9시간이 통째로 어긋나 결속이 전부 실패한다.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _norm(path: str) -> str:
    return str(path or '').replace('\\', '/').rstrip('/').lower()


def read_head_meta(path: Path) -> dict:
    """결속 판정에 필요한 메타 — {first_ts, cwd, session_id}. 머리에서만 읽는다.

    [WHY mtime이 아니라 첫 줄 시각] 판정에 필요한 건 '이 대화가 슬롯보다 나중에
      시작됐는가'다. mtime은 마지막 쓰기라 어제 시작한 대화도 방금 한 줄 쓰면
      최신으로 보인다 — 바로 그 착시가 2026-08-14 화석 사고의 뿌리다.
    [WHY 꼬리가 아니라 머리] cwd도 여기서 같이 읽는다. 꼬리 파싱은 거대한
      tool_result 한 줄이 창을 통째로 먹으면 None을 내는데, 그러면 활발한 세션이
      후보 목록에서 조용히 빠진다. 머리 쪽 첫 줄은 항상 작은 메타 레코드다.
    """
    out = {'first_ts': '', 'cwd': '', 'session_id': ''}
    try:
        with open(path, 'rb') as f:
            raw = f.read(_HEAD_BYTES).decode('utf-8', errors='ignore')
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # 헤드 경계에서 잘린 줄 — 다음 줄로 넘어간다
        if not isinstance(obj, dict):
            continue
        if not out['first_ts'] and obj.get('timestamp'):
            out['first_ts'] = str(obj['timestamp'])
        if not out['cwd'] and obj.get('cwd'):
            out['cwd'] = str(obj['cwd']).replace('\\', '/')
        if not out['session_id'] and obj.get('sessionId'):
            out['session_id'] = str(obj['sessionId'])
        if all(out.values()):
            break
    return out


def parse_usage_deep(path: Path) -> dict | None:
    """꼬리를 넓혀 가며 마지막 assistant usage를 찾는다.

    [WHY] 기본 8KB 꼬리에 usage가 없을 수 있다 — 거대한 tool_result 한 줄이 꼬리를
      통째로 차지하면 활발히 도는 세션이 model='unknown'/0토큰으로 읽힌다(실측
      2026-08-14: T3가 그 상태였다). '계측 불가'가 지속되면 자동 리사이클이 조용히
      0회가 되는데, 그건 화석 사고와 같은 종류의 침묵이다.
    [제약] 결속된 슬롯(최대 8개)에만 쓴다 — 후보 전체에 걸면 60초마다 수 MB를
      읽는다. 결속 판정에 필요한 건 cwd/first_ts뿐이라 그쪽은 8KB로 충분하다.
    """
    last = None
    for size in _DEEP_TAIL_STEPS:
        info = parse_session_tail(path, tail_bytes=size)
        if info:
            last = info
            if (info.get('input_tokens') or 0) > 0:
                return info
        # [WHY None이어도 계속] 창이 거대한 한 줄의 '중간'에 떨어지면 완전한 JSON이
        #   하나도 없어 None이 나온다. 여기서 포기하면 넓혀 읽는 의미가 통째로
        #   사라진다 — 정확히 그 경우를 위해 만든 함수다.
        try:
            if path.stat().st_size <= size:
                break  # 파일 전체를 이미 읽었다 — 더 넓혀도 결과가 같다
        except OSError:
            break
    return last


def collect_claude_sessions(cwds: set[str], now: float | None = None) -> list[dict]:
    """주어진 cwd들에 속한 claude 세션 파일 목록(결속 후보).

    [WHY 전체 스캔] 디렉터리 슬러그(`D--apix`)는 claude 본체의 인코딩 규칙이라
      우리가 재현하면 어긋난다(과거사고: 설치본에서 디렉터리 미발견). 파일 안의
      cwd를 진실로 삼고 디렉터리 이름은 믿지 않는다.
    """
    now = now if now is not None else time.time()
    root = Path.home() / '.claude' / 'projects'
    out: list[dict] = []
    if not cwds or not root.exists():
        return out
    try:
        files = [p for d in root.iterdir() if d.is_dir() for p in d.glob('*.jsonl')]
    except OSError:
        return out
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size <= 0:
            continue  # 태어나자마자 죽은 빈 세션 — 결속 후보가 못 된다
        if now - st.st_mtime > _SCAN_WINDOW_SEC:
            continue
        meta = read_head_meta(path)
        cwd = _norm(meta.get('cwd'))
        if not cwd or cwd not in cwds:
            continue
        # 토큰 usage는 여기서 읽지 않는다 — 결속이 끝난 슬롯에만 넓혀 읽는다
        # (parse_usage_deep). 후보 전체에 걸면 60초마다 수 MB를 훑게 된다.
        meta['path'] = str(path)
        meta['cwd_norm'] = cwd
        meta['mtime'] = st.st_mtime  # '마지막으로 쓰인 시각' — 슬롯 대조용
        out.append(meta)
    return out


def bind_slots(slots: list[dict], sessions: list[dict]) -> dict[str, dict]:
    """슬롯 → 그 슬롯이 실제로 쓰는 세션 파일. 확정 못 하면 아예 넣지 않는다.

    규칙: 대화는 자기를 띄운 셸보다 나중에 생긴다 — `first_ts >= slot.started`.
      슬롯을 started 내림차순으로 훑으며 아직 임자 없는 최신 세션을 하나씩 집는다.
      같은 프로젝트에 슬롯이 여럿이면 나중에 뜬 슬롯이 나중에 생긴 대화를 갖는다.

    [불변식] 확정 실패는 '결속 없음'이지 '아무거나 배정'이 아니다 — 이 계측의
      소비자가 하는 일이 '터미널을 죽이고 새로 띄우는 것'이라, 추측 배정은 살아
      있는 남의 세션을 소리 없이 증발시킨다(2026-08-09 T1 고정 폴백과 같은 종류).
    [한계] `claude --continue`/`--resume`은 옛 파일에 이어 쓰므로 first_ts가
      슬롯보다 빠르다 → 결속 실패 → 자동 리사이클 대상에서 빠진다(수동은 가능).
      '안 죽는 쪽'으로 실패하는 것이 옳은 방향이라 이대로 둔다.
    """
    pool: list[tuple[float, dict]] = []
    for sess in sessions:
        first = parse_iso(sess.get('first_ts'))
        if first is None:
            continue  # 첫 타임스탬프를 못 읽으면 시작 시점을 모른다 → 후보 제외
        pool.append((first, sess))
    pool.sort(key=lambda t: t[0], reverse=True)

    ordered: list[tuple[float, dict]] = []
    for slot in slots:
        started = parse_iso(slot.get('started'))
        if started is None:
            continue
        ordered.append((started, slot))
    ordered.sort(key=lambda t: t[0], reverse=True)

    taken: set[str] = set()
    bound: dict[str, dict] = {}
    for started, slot in ordered:
        cwd = _norm(slot.get('cwd'))
        tid = str(slot.get('terminal_id') or '')
        if not cwd or not tid:
            continue
        floor = started - _START_GRACE_SEC
        # PTY는 epoch ms로 준다. 0/없음은 '신호 없음'이라 검증을 건너뛴다.
        try:
            out_at = float(slot.get('last_output_at') or 0) / 1000.0
        except (TypeError, ValueError):
            out_at = 0.0
        for first, sess in pool:
            if first < floor:
                # pool이 first_ts 내림차순이라 이 뒤는 전부 더 오래됐다.
                break
            if sess['path'] in taken or sess['cwd_norm'] != cwd:
                continue
            if out_at > 0:
                # mtime = 그 대화가 마지막으로 쓰인 시각. 파일 안 타임스탬프가 아닌
                # 이유: 결속 전이라 usage 파싱을 아직 안 했고(비용), mtime은 stat
                # 한 번이면 얻는 데다 '마지막 쓰기'라는 뜻이 정확히 같다.
                last = sess.get('mtime')
                if last is not None and last > out_at + _OUTPUT_SKEW_SEC:
                    continue  # 이 슬롯이 출력한 적 없는 시각에 진행된 대화 = 남의 것
            bound[tid] = sess
            taken.add(sess['path'])
            break
    return bound


def measure_terminals(slots: list[dict], now: float | None = None) -> dict[str, dict]:
    """running claude 슬롯별 컨텍스트 점유율.

    반환: {terminal_id: {cli, available, percentage, stale, session_age_sec, ...}}
    결속 실패 슬롯도 `available=False`로 반드시 넣는다 — 키가 없으면 호출부가
    '그런 터미널 없음'과 '결속 실패'를 구분 못 해 원인 추적이 막힌다.
    """
    now = now if now is not None else time.time()
    targets = [s for s in slots
               if s.get('running') and str(s.get('agent') or '') == 'claude'
               and s.get('terminal_id')]
    out: dict[str, dict] = {}
    if not targets:
        return out

    cwds = {_norm(s.get('cwd')) for s in targets if s.get('cwd')}
    bound = bind_slots(targets, collect_claude_sessions(cwds, now))

    for slot in targets:
        tid = str(slot['terminal_id'])
        sess = bound.get(tid)
        if not sess:
            out[tid] = {'cli': 'claude', 'available': False, 'percentage': 0.0,
                        'reason': 'unbound_session'}
            continue
        # 결속이 끝난 뒤에야 넓혀 읽는다 — 후보 전체가 아니라 슬롯 수만큼만.
        deep = parse_usage_deep(Path(sess['path']))
        if deep and (deep.get('input_tokens') or 0) > 0:
            sess = {**sess, **deep}
        window = claude_ctx_window(str(sess.get('model') or ''))
        used = (int(sess.get('input_tokens') or 0)
                + int(sess.get('cache_read') or 0)
                + int(sess.get('cache_write') or 0))
        base = {
            'cli': 'claude',
            'session_id': str(sess.get('session_id') or ''),
            'model': str(sess.get('model') or ''),
            'last_ts': str(sess.get('last_ts') or ''),
        }
        if window <= 0 or used <= 0:
            # 방금 태어나 아직 assistant 응답이 없는 세션. 0%로 보고하면 '여유
            # 있음'과 구분이 안 되고, 옛 사고에서는 이 세션이 후순위로 밀려 화석이
            # 계측 승자가 됐다 — 이제는 결속으로 화석이 아예 후보에서 빠진다.
            out[tid] = {**base, 'available': False, 'percentage': 0.0,
                        'reason': 'no_usage_yet'}
            continue
        last = parse_iso(sess.get('last_ts'))
        age = (now - last) if last is not None else None
        out[tid] = {
            **base,
            'available': True,
            'percentage': round(used / window * 100, 1),
            'context_used': used,
            'context_window': window,
            'session_age_sec': round(age) if age is not None else None,
            'stale': bool(age is not None and age > STALE_AFTER_SEC),
            'reason': '',
        }
    return out
