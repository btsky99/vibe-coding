# -*- coding: utf-8 -*-
"""
FILE: .ai_monitor/infra/voice_turn.py
DESCRIPTION: 음성 낭독용 '턴 채널' 저장소 — Stop 훅이 쓰고 /api/voice/turn 이 읽는다.
             경로 계산과 원자적 쓰기/읽기의 **단일 정본**. 훅(scripts/voice_turn_hook.py)과
             서버(api/voice_api.py)가 같은 파일을 가리켜야 하므로 양쪽이 이 모듈만 쓴다.

             [WHY 화면(PTY)에서 안 긁고 훅인가] 낭독에는 두 가지가 필요하다.
               ① 언제 입을 열지 — 턴 경계  ② 무엇을 읽을지 — 깨끗한 문장
             xterm 버퍼에는 ANSI·박스문자·스피너가 섞이고 '끝났는지'는 추측이 된다.
             훅은 그 둘을 확정적으로 준다(아픽스 deploy/apix-turn-hook.py 에서 이식).

             [WHY PG 가 아니라 파일인가] 규칙 4(PostgreSQL-first)는 **활동 로그** 규칙이다.
             이건 로그가 아니라 '마지막 턴'이라는 휘발성 최신값이고, 훅은 매 턴 도는
             최단 경로여야 한다 — DB 커넥션을 여는 순간 응답 지연이 사용자에게 보인다.
             기록은 pg_logs 와 트랜스크립트가 이미 갖고 있다.

             [🔴 슬롯별로 나눈다] 터미널 슬롯이 여럿이고 각 슬롯이 다른 CLI 세션이다.
             한 파일을 공유하면 T1 이 T3 의 답을 읽는다. 파일명에 터미널 ID 를 박는다.

             [🔴 프로젝트별로도 나눈다] 멀티 인스턴스(다른 프로젝트를 연 앱)가 같은 PC 에서
             동시에 돈다. 슬롯 번호는 프로젝트마다 겹치므로 슬러그로 한 겹 더 가른다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 아픽스 음성 기능 이식(턴 채널 부분)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# 낭독이 읽지 않을 분량을 들고 있어 봐야 디스크만 먹는다. 잘렸다는 사실은 truncated 로 알린다.
MAX_CHARS = 20000


def normalize_terminal_id(raw: object) -> str:
    """'1' / 1 / 'T1' 을 모두 'T1' 로 맞춘다.

    [🔴 왜 정규화가 필요한가] 발신자마다 형식이 다르다 — PTY 서버는 env TERMINAL_ID 에
      숫자만 넣고(pty-server.js), 프론트는 `T${slotId+1}` 로 만든다. 한쪽 표기로 파일을
      쓰고 다른 표기로 찾으면 '항상 waiting' 이 되는데, 그건 고장처럼 안 보여서 나쁘다.
    """
    s = str(raw or '').strip().upper()
    if not s:
        return 'T0'
    if s.startswith('T'):
        s = s[1:]
    return f'T{s}' if s else 'T0'


def turn_dir(project_slug: str) -> Path:
    """턴 파일이 놓이는 디렉토리. 임시 폴더에 둔다 — 리포를 더럽히지 않는다."""
    return Path(tempfile.gettempdir()) / 'vibe-voice' / (project_slug or '_default')


def turn_path(project_slug: str, terminal_id: object) -> Path:
    return turn_dir(project_slug) / f'turn-{normalize_terminal_id(terminal_id)}.json'


def read(project_slug: str, terminal_id: object) -> dict:
    """마지막 턴을 읽는다.

    [WHY 예외를 안 던지나] 읽는 쪽은 폴링이다. 훅이 아직 한 번도 안 돈 상태는 장애가
      아니라 그냥 '아직'이다. 여기서 예외가 나가면 화면이 이걸 고장으로 그린다.
    """
    p = turn_path(project_slug, terminal_id)
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {'seq': 0, 'waiting': True}
    except FileNotFoundError:
        return {'seq': 0, 'waiting': True}
    except (OSError, ValueError):
        # 반쯤 쓰인 파일을 읽었을 수 있다. write() 는 rename 으로 원자적이지만
        # 그래도 여기서 죽지는 않는다.
        return {'seq': 0, 'waiting': True, 'error': 'unreadable'}


def next_seq(project_slug: str, terminal_id: object) -> int:
    """턴마다 1씩 는다.

    [WHY 본문 비교로 안 하나] 같은 답이 두 번 나올 수 있다("네."). 폴링하는 쪽이
      본문만 보면 두 번째 턴을 놓친다. 순번은 그 실수를 구조적으로 막는다.
    """
    try:
        return int(read(project_slug, terminal_id).get('seq', 0)) + 1
    except (TypeError, ValueError):
        return 1


def write(project_slug: str, terminal_id: object, payload: dict) -> Path:
    """턴을 원자적으로 저장한다.

    [🔴 rename 으로 쓴다] 읽는 쪽은 폴링이다. 그냥 열어서 쓰면 반쯤 쓰인 파일을 읽어
      JSON 파싱이 깨지는 순간이 반드시 생긴다. os.replace 는 같은 볼륨에서 원자적이다.
    """
    p = turn_path(project_slug, terminal_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix='.turn-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p
