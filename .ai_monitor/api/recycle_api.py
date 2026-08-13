#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: api/recycle_api.py
DESCRIPTION: 컨텍스트 리사이클 HTTP 계층 — 상태머신(src/session_recycle.py)에
             실제 PostgreSQL·PTY·계측 의존성을 주입해 실행한다.
             GET /api/session/recycle/status, POST /api/session/recycle.

REVISION HISTORY:
- 2026-08-05 Claude: 최초 구현 — Phase 6(컨텍스트 리사이클)
- 2026-08-09 Claude: terminal_id 'T1' 하드코딩 폴백 제거 — 대상 터미널을
  호출부가 반드시 지정하게 강제(엉뚱한 슬롯 처형 사고)
- 2026-08-14 Claude: claude 계측에 stale 노출 + status에 terminals(터미널별 계측)
  추가 — 끝난 세션의 화석 85.3%로 T1·T2가 반복 처형된 사고
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import session_binding as sb
import session_recycle as sr
from session_recycle import GuardInput, execute_recycle, make_token, plan_recycle


def _json(handler, payload: dict, status: int = 200) -> None:
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def _body(handler) -> dict:
    try:
        length = int(handler.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        return json.loads(handler.rfile.read(length).decode('utf-8')) or {}
    except (ValueError, TypeError, OSError):
        return {}


# ────────────────────────── 계측 ──────────────────────────

def _get_json_from_server(path: str, project_id: str = '') -> dict | None:
    """로컬 서버의 GET 엔드포인트를 호출한다(계측 정본 재사용 통로)."""
    import urllib.error
    import urllib.request
    try:
        from src.server_locator import find_server_port
        port = find_server_port(project_id)
    except Exception:
        port = None
    if not port:
        return None
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return None

def measure_context(cli: str, project_id: str = '') -> dict:
    """CLI별 현재 컨텍스트 점유율.

    [🔴 과거사고 2026-07-16 재발방지] project_id를 반드시 흘려보낸다. 비워두면
      find_server_port가 '첫 응답 포트' 폴백으로 떨어져 멀티 프로젝트 동시 가동
      시(9000=타 프로젝트, 9010=여기) 남의 서버(별도 PG DB)의 컨텍스트를 읽는다.
      그 값으로 리사이클을 판정하면 멀쩡한 세션을 남의 사용률 때문에 죽인다.

    [P0 계측 2026-08-05] antigravity는 의도적으로 available=False다 —
      /api/antigravity-context-usage가 폐기 경로(~/.gemini/tmp/*/chats)를 읽어
      70일 된 화석만 본다. 여기서 0%를 반환하면 '여유 있음'으로 오독되어
      자동 트리거가 영원히 안 도는 걸 아무도 모르게 된다. reason으로 드러낸다.

    [🔴 과거사고 2026-08-14] 이 값은 'CLI 전역 1개'다 — 어느 터미널의 것인지
      모른다. 자동 처형의 대상 선정에 이 값을 쓰면 안 된다(terminals를 쓸 것).
      여기 남은 용도는 UI 표시와 GUARD의 context_pct 하나뿐이다.
    """
    if cli == 'codex':
        from codex_context import context_usage
        return context_usage()

    if cli == 'claude':
        # [WHY] jsonl 파싱을 여기서 재구현하지 않는다 — 그 로직(_parse_session_tail)은
        #   server.py 소유라 임포트가 불가하고, 베껴 오면 두 벌이 서로 어긋난다.
        #   /api/context-usage를 그대로 호출해 계측 정본을 하나로 유지한다.
        #   서버는 ThreadingMixIn이라 자기 자신 호출이 데드락되지 않는다.
        # [과거사고 2026-07-16] 포트를 9000부터 훑어 첫 응답을 채택하면 다른 프로젝트
        #   서버(별도 PG DB)에 붙는다 → server_locator로 project_id 대조 필수.
        snap = _get_json_from_server('/api/context-usage', project_id)
        if not snap:
            return {'available': False, 'percentage': 0.0, 'reason': 'server_unreachable'}
        window = int(snap.get('context_window') or 0)
        used = int(snap.get('context_used') or 0)
        if window <= 0 or used <= 0:
            return {'available': False, 'percentage': 0.0, 'reason': 'no_active_session'}
        # [🔴 과거사고 2026-08-14] 나이를 안 실어 보냈다. 어제 끝난 8MB 세션이
        #   853,206/1,000,000 = 85.3%로 16시간째 고정 보고됐고, 워처는 그것을
        #   현재값으로 읽어 60초마다 살아 있는 터미널을 죽였다. codex 경로에는
        #   이미 있던 장치(codex_context.stale)가 claude에만 빠져 있었다.
        last = sb.parse_iso(snap.get('last_ts') or '')
        age = (time.time() - last) if last is not None else None
        return {'available': True, 'percentage': round(used / window * 100, 1),
                'context_used': used, 'context_window': window,
                'last_ts': str(snap.get('last_ts') or ''),
                'session_age_sec': round(age) if age is not None else None,
                'stale': bool(age is not None and age > sb.STALE_AFTER_SEC),
                'reason': ''}

    return {'available': False, 'percentage': 0.0,
            'reason': f'{cli}_measurement_unavailable'}


def _pty_slots(project_id: str) -> list[dict]:
    """PTY 슬롯 목록(terminal_id 주입). 실패는 빈 목록 — '대상 없음'으로 흡수한다.

    [제약] project_id를 반드시 실어 보낸다 — 빼면 응답 키가 `T3@D--CipherTrader`
      같은 네임스페이스 형태로 섞여 나와 terminal_id로 그대로 쓸 수 없다.
    """
    import urllib.error
    import urllib.parse
    import urllib.request
    try:
        from api import pty_api
        base = getattr(pty_api, '_node_pty_url', '') or ''
    except Exception:
        base = ''
    if not base:
        return []
    qs = urllib.parse.urlencode({'project_id': project_id})
    try:
        with urllib.request.urlopen(f'{base}/api/pty/sessions?{qs}', timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for tid, slot in data.items():
        if isinstance(slot, dict):
            out.append({**slot, 'terminal_id': tid})
    return out


def measure_terminals(project_id: str) -> dict:
    """터미널별 계측 — 자동 리사이클의 대상 선정에 쓰는 유일한 정본.

    [WHY] CLI 전역 계측(measure_context)은 '세션 1개'의 수치인데 처형은 '터미널
      N개'였다. 2026-08-09 수정이 T1 고정 폴백을 팬아웃으로 바꿔놓아, 세션 하나가
      임계를 넘으면 같은 CLI를 쓰는 슬롯이 전부 죽었다(2026-08-14 T1·T2 동시 처형).
    [codex 규칙] rollout 파일에는 cwd가 없어 슬롯 결속이 불가능하다. 러닝 codex
      터미널이 정확히 1개일 때만 전역 계측을 그 터미널의 것으로 인정한다 —
      2개 이상이면 어느 세션이 누구 것인지 알 수 없으므로 계측 없음으로 낸다.
      '모르면 안 죽인다'가 이 모듈 전체의 실패 방향이다.
    """
    slots = _pty_slots(project_id)
    out = sb.measure_terminals(slots)

    codex_slots = [s for s in slots
                   if s.get('running') and str(s.get('agent') or '') == 'codex'
                   and s.get('terminal_id')]
    if len(codex_slots) == 1:
        m = dict(measure_context('codex', project_id))
        m['cli'] = 'codex'
        out[str(codex_slots[0]['terminal_id'])] = m
    else:
        for slot in codex_slots:
            out[str(slot['terminal_id'])] = {
                'cli': 'codex', 'available': False, 'percentage': 0.0,
                'reason': 'ambiguous_codex_sessions'}
    return out


# ────────────────────────── deps ──────────────────────────

class RecycleDeps:
    """상태머신이 요구하는 부작용을 실제 시스템에 연결한다."""

    def __init__(self, terminal_id: str, project_id: str, cli: str):
        self.terminal_id = terminal_id
        self.project_id = project_id
        self.cli = cli
        self._sealed: dict = {}
        # SEAL 직후의 updated_at(epoch). user_active가 '나이'에서 '기준선 이후 새 쓰기'로
        # 판정을 바꾸는 스위치 — None이면 아직 SEAL 전이다.
        self._seal_ts: float | None = None

    # -- SEAL --
    def seal(self, payload: dict) -> bool:
        """마감 기록 저장. 여기서 False가 나오면 상태머신이 즉시 멈춘다(불변식 1)."""
        try:
            from src.pg_store import set_session_checkpoint
        except Exception:
            return False
        files = self._modified_files()
        note = f"[리사이클 {payload.get('trigger', 'manual')}] 컨텍스트 한계로 세션 교체"
        try:
            ok = set_session_checkpoint(
                terminal_id=self.terminal_id, decision=note,
                project_id=self.project_id)
        except Exception:
            return False
        if ok:
            self._sealed['modified_files'] = files
            # [불변식] 기준선은 SEAL 성공 직후에만 찍는다 — 실패했는데 찍으면
            #   user_active가 '새 쓰기 없음'으로 오판해 DRAIN이 무조건 통과한다.
            self._seal_ts = self._session_clock()[0]
        return bool(ok)

    def _session_clock(self) -> tuple[float | None, float | None]:
        """(updated_at epoch, 그 값의 나이(초)). 행이 없거나 실패면 (None, None)."""
        try:
            from src.db_helper import query_rows
            rows = query_rows(
                "SELECT EXTRACT(EPOCH FROM updated_at) AS ts, "
                "EXTRACT(EPOCH FROM (NOW() - updated_at)) AS age "
                "FROM active_session_context WHERE terminal_id = %s "
                "AND status = 'active' AND project_id = %s LIMIT 1;",
                (self.terminal_id, self.project_id)) or []
        except Exception:
            return (None, None)
        if not rows:
            return (None, None)
        try:
            ts, age = rows[0].get('ts'), rows[0].get('age')
            return (float(ts) if ts is not None else None,
                    float(age) if age is not None else None)
        except (TypeError, ValueError):
            return (None, None)

    def _modified_files(self) -> list[str]:
        """[제약] git 없는 프로젝트에서도 실패하면 안 된다 — 빈 목록으로 계속 간다.

        [🔴 2026-08-09] proc.run 필수 — 리사이클은 자동 발동(데몬)이라 subprocess.run
          직호출이면 사용자가 아무것도 안 했는데 검은 cmd 창이 뜬다.
        """
        from infra import proc
        try:
            out = proc.run(['git', 'status', '--porcelain'], capture_output=True,
                           text=True, timeout=5, cwd=self.project_root())
            if out.returncode != 0:
                return []
            return [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()][:40]
        except Exception:
            return []

    def project_root(self) -> str:
        return str(Path(__file__).resolve().parent.parent.parent)

    @staticmethod
    def _json_list(value) -> list:
        """jsonb ::text 문자열을 리스트로 되돌린다.

        [🔴 과거사고 2026-08-05] get_interrupted_sessions는 decisions/modified_files를
          `::text`로 뽑아 '[]' 같은 '문자열'을 준다. 이 변환 없이 넘기면 build_reanchor가
          문자열을 순회해 재정박 프롬프트에 '- [', '- ]' 같은 글자 부스러기가 박혔다
          (내용이 비어 있어도 발생 — '[]'는 truthy라 헤더까지 출력됐다).
        """
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except ValueError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    def collect_checkpoint(self) -> dict:
        try:
            from src.pg_store import get_interrupted_sessions
            rows = get_interrupted_sessions(terminal_id=self.terminal_id,
                                            project_id=self.project_id) or []
        except Exception:
            rows = []
        cp = dict(rows[0]) if rows else {}
        cp['decisions'] = self._json_list(cp.get('decisions'))
        # [WHY] setdefault를 쓰지 않는다 — 행에는 modified_files 키가 '[]' 문자열로
        #   항상 존재해 setdefault가 무조건 no-op이 됐고, SEAL이 git status로 모아둔
        #   실제 변경 파일 목록이 통째로 버려졌다. DB가 비었을 때만 SEAL 값을 쓴다.
        cp['modified_files'] = (self._json_list(cp.get('modified_files'))
                                or self._sealed.get('modified_files', []))
        return cp

    # -- 상태 --
    def set_state(self, state: str, token: str) -> None:
        try:
            from src.db_helper import execute
            stamp = ', recycled_at = NOW()' if state == '' else ''
            execute(
                "UPDATE active_session_context "
                f"SET recycle_state = %s, recycle_token = %s{stamp} "
                "WHERE terminal_id = %s AND status = 'active' AND project_id = %s;",
                (state, token, self.terminal_id, self.project_id))
        except Exception:
            pass  # 상태 기록 실패가 리사이클 자체를 막지는 않는다

    # -- DRAIN / PTY --
    def drain(self, timeout: float) -> bool:
        """진행 중 도구가 끝나길 기다린다. 지금은 인터럽트 후 정착 대기."""
        self._pty_post('interrupt')
        deadline = time.time() + min(timeout, sr.DRAIN_TIMEOUT_SEC)
        while time.time() < deadline:
            time.sleep(1.0)
            if not self.user_active():
                return True
        return False

    def user_active(self) -> bool:
        """최근 사용자 입력 여부 — 자동 리사이클의 최후 방어선.

        [🔴 과거사고 2026-08-05] SEAL 이후에도 updated_at의 '나이'로 판정했더니,
          SEAL(set_session_checkpoint)이 바로 그 컬럼을 NOW()로 갱신해 항상
          나이 0초 → 항상 True가 됐다. 결과: drain이 20초를 꽉 채우고 False를
          반환 → 자동 리사이클이 구조적으로 100% 실패, 수동은 매번 20초 낭비.
          가짜 deps를 쓰는 단위 테스트로는 절대 안 잡히는 통합 결함이었다.
        [불변식] SEAL 후에는 나이가 아니라 '기준선 이후 새 쓰기가 있었는가'로 본다.
          이 행의 updated_at은 훅(UserPromptSubmit/Stop)과 checkpoint.py가 쓰므로
          기준선보다 새 값 = 그 사이 세션이 실제로 움직였다는 뜻이다.
        [제약] 판정 불가(행 없음/DB 실패)는 False — 여기서 True로 막으면
          수동 요청까지 영구히 잠긴다.
        """
        ts, age = self._session_clock()
        if ts is None:
            return False
        if self._seal_ts is not None:
            return ts > self._seal_ts
        return age is not None and age < sr.USER_ACTIVE_SEC

    def _pty_post(self, action: str) -> bool:
        import urllib.error
        import urllib.request
        try:
            from api import pty_api
            base = getattr(pty_api, '_node_pty_url', '') or ''
        except Exception:
            return False
        if not base:
            return False
        url = f'{base}/api/pty/{action}/{self.terminal_id}?project_id={self.project_id}'
        try:
            req = urllib.request.Request(url, method='POST', data=b'{}',
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def terminate(self) -> bool:
        return self._pty_post('terminate')

    def spawn(self) -> bool:
        return self._pty_post('spawn')

    def inject(self, text: str) -> bool:
        import urllib.error
        import urllib.request
        try:
            from api import pty_api
            base = getattr(pty_api, '_node_pty_url', '') or ''
        except Exception:
            return False
        if not base:
            return False
        url = f'{base}/api/pty/write/{self.terminal_id}?project_id={self.project_id}'
        data = json.dumps({'data': text + '\r'}).encode('utf-8')
        try:
            req = urllib.request.Request(url, method='POST', data=data,
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def save_fallback(self, text: str) -> str:
        """세션을 못 살렸을 때 재정박 프롬프트를 파일로 건진다(수동 복구용)."""
        try:
            out = Path(self.project_root()) / '_local'
            out.mkdir(parents=True, exist_ok=True)
            path = out / f'reanchor-{self.terminal_id}.md'
            path.write_text(text, encoding='utf-8')
            return str(path)
        except OSError:
            return ''


# ────────────────────────── 핸들러 ──────────────────────────

def _guard_input(body: dict, cli: str, trigger: str, project_id: str,
                 terminal_id: str) -> GuardInput:
    """[제약] terminal_id는 호출부(handle_post)가 검증해 넘긴 값만 받는다.

    [🔴 과거사고 2026-08-09] 여기서 `body.get('terminal_id') or 'T1'`로 자체
      폴백을 두었고 handle_post에도 같은 폴백이 중복돼 있었다. 리사이클 워처가
      terminal_id를 아예 안 보내므로 codex가 임계를 넘어도 GUARD는 T1 행을 읽고
      SWAP은 T1을 죽였다 — codex가 어느 슬롯에 있든 처형은 항상 T1이었다.
      폴백을 지운 이유: 대상을 못 정하면 '아무나 죽이기'보다 거부가 안전하다.
    """
    measurement = measure_context(cli, project_id)
    try:
        from src.db_helper import query_rows
        rows = query_rows(
            "SELECT recycle_state, EXTRACT(EPOCH FROM (NOW() - recycled_at)) AS since, "
            "EXTRACT(EPOCH FROM (NOW() - updated_at)) AS age "
            "FROM active_session_context WHERE terminal_id = %s AND status = 'active' "
            "AND project_id = %s LIMIT 1;",
            (terminal_id, project_id)) or []
    except Exception:
        rows = []
    row = rows[0] if rows else {}
    since = row.get('since')
    # [WHY] age를 여기서 채워야 GUARD의 user_active 분기가 살아난다 — 이 필드를
    #   비워두면 순수 함수의 1차 방어선이 통째로 무력화되고, 사람이 타이핑 중인
    #   세션을 죽이는 최악 실패 모드를 SWAP 직전 재확인 하나에만 의존하게 된다.
    #   이 시점은 SEAL 전이라 updated_at이 아직 오염되지 않아 '나이'가 유효하다.
    age = row.get('age')
    return GuardInput(
        trigger=trigger, cli=cli,
        recycle_state=str(row.get('recycle_state') or ''),
        seconds_since_last_input=float(age) if age is not None else None,
        seconds_since_last_recycle=float(since) if since is not None else None,
        context_pct=measurement.get('percentage') if measurement.get('available') else None,
        threshold=float(body.get('threshold') or sr.DEFAULT_THRESHOLD),
        force=bool(body.get('force')),
    )


def handle_get(handler, path: str, params: dict | None = None,
               PROJECT_ID: str = '') -> bool:
    if path != '/api/session/recycle/status':
        return False
    params = params or {}
    cli = (params.get('cli', ['claude'])[0] if params else 'claude')
    # [WHY] 쿼리 우선, 없으면 서버가 주입한 현재 활성 프로젝트 — 빈 값으로 두면
    #   measure_context가 '첫 응답 포트'로 떨어져 남의 프로젝트를 계측한다.
    project_id = (params.get('project_id', [''])[0] if params else '') or PROJECT_ID
    _json(handler, {
        'measurement': {c: measure_context(c, project_id)
                        for c in ('claude', 'codex', 'antigravity')},
        # [불변식] 자동 리사이클 워처는 measurement가 아니라 terminals만 본다 —
        #   measurement에는 '어느 터미널의 값인가'가 없다(2026-08-14 사고).
        'terminals': measure_terminals(project_id),
        'auto_trigger_clis': list(sr.AUTO_TRIGGER_CLIS),
        'threshold': sr.DEFAULT_THRESHOLD,
        'cli': cli,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    })
    return True


def handle_post(handler, path: str, PROJECT_ID: str = '') -> bool:
    if path != '/api/session/recycle':
        return False
    body = _body(handler)
    terminal_id = str(body.get('terminal_id') or '').strip()
    # [불변식] project_id가 비면 UPDATE/SELECT가 어떤 행에도 안 걸려 상태 기록이
    #   조용히 사라진다(0건을 '정상'으로 오독). 본문 → 서버 주입 순으로 채운다.
    project_id = str(body.get('project_id') or '') or PROJECT_ID
    cli = str(body.get('cli') or 'claude')
    trigger = 'auto' if body.get('trigger') == 'auto' else 'manual'

    # [불변식] 대상 터미널은 호출부가 명시한다 — 폴백 금지.
    #   이 엔드포인트의 부작용은 '특정 PTY를 죽이고 새로 띄우는 것'이라
    #   대상을 추측하면 살아 있는 남의 세션이 소리 없이 증발한다(위 과거사고).
    #   프론트에는 호출부가 없어(유일 호출자 = infra/daemons.py 리사이클 워처)
    #   필수화로 깨지는 UI 경로가 없음을 확인하고 거부로 바꿨다.
    if not terminal_id:
        _json(handler, {'ok': False, 'stage': 'guard', 'reason': 'no_terminal_id',
                        'detail': 'terminal_id는 필수 — 대상 터미널을 명시할 것'}, 400)
        return True

    gi = _guard_input(body, cli, trigger, project_id, terminal_id)
    if body.get('dry_run'):
        d = plan_recycle(gi)
        _json(handler, {'allowed': d.allowed, 'reason': d.reason, 'detail': d.detail})
        return True

    deps = RecycleDeps(terminal_id, project_id, cli)
    token = make_token(terminal_id, datetime.now(timezone.utc).isoformat())
    res = execute_recycle(gi, deps, terminal_id, token)
    _json(handler, {
        'ok': res.ok, 'stage': res.stage, 'reason': res.reason, 'token': res.token,
        'stages': res.stages, 'reanchor_chars': res.reanchor_chars,
        'truncated': res.truncated, 'fallback_path': res.fallback_path,
    }, 200 if res.ok else 409)
    return True
