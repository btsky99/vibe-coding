# -*- coding: utf-8 -*-
"""
FILE: scripts/voice_turn_hook.py
DESCRIPTION: 음성 낭독의 토대 — Claude Code Stop 훅으로 붙어, 턴이 끝난 사실과
             그 턴의 최종 응답 텍스트를 슬롯별 턴 파일에 남긴다.
             읽는 쪽은 /api/voice/turn (api/voice_api.py) 이고, 저장 경로·형식의
             정본은 infra/voice_turn.py 다.

             아픽스(D:/apix deploy/apix-turn-hook.py)에서 이식. 그쪽에서 실측으로
             얻은 함정 주석은 값이 크므로 그대로 가져왔다.

             [🔴 thinking 은 절대 내보내지 않는다] 트랜스크립트의 assistant 항목에는
             text·thinking·tool_use 가 섞여 있다. thinking 을 읽어 주는 비서는 만들면
             안 된다 — 사용자가 듣기로 한 적이 없는 말이다. extract()의 type=='text'
             조건을 넓히지 말 것.

             [WHY 마지막 text 블록만인가] 한 턴에는 도구 사이사이의 중계 멘트가 여럿
             있다("이제 확인하겠습니다"). 다 읽으면 장황하다. 읽을 것은 마지막 답이다.

             [🔴 async 훅으로 등록한다] .claude/settings.json 에서 async:true.
             wait_settle 이 최대 6초를 쓰므로, 동기로 걸면 그 시간이 그대로 사용자
             대기가 된다.

사용: Stop 훅이 stdin 으로 JSON 을 준다. 사람이 부를 일은 시험할 때뿐이다.
      echo '{"transcript_path":"C:/path/to.jsonl","cwd":"D:/vibe-coding"}' | python scripts/voice_turn_hook.py

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 아픽스 음성 기능 이식(턴 채널 훅)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from infra import voice_turn                                  # noqa: E402
from infra.project_context import find_project_root_marker, slugify  # noqa: E402

# 트랜스크립트 뒤에서부터 이만큼만 본다. [WHY] 파일이 수십 MB 로 자라도 훅은 매 턴
# 돈다. 전체를 파싱하면 턴마다 그 비용을 낸다.
TAIL_BYTES = 2_000_000


def _quiet(msg: str) -> int:
    """훅은 조용히 실패한다.

    [🔴 WHY] 여기서 낸 에러가 사용자 화면에 뜨면 CLI 가 고장 난 것처럼 보인다.
      실제로는 부가 기능(낭독) 하나가 이번 턴에 안 된 것뿐이다.
    """
    print(json.dumps({'suppressOutput': True, 'note': msg}), end='')
    return 0


def wait_settle(path: str, cap: float = 6.0, quiet: float = 0.5,
                poll: float = 0.1) -> None:
    """트랜스크립트가 더 이상 자라지 않을 때까지 기다린다.

    [🔴 이 함수가 없으면 훅은 '틀린 답'을 저장한다 — 아픽스 2026-08-14 실측]
      Stop 훅은 **마지막 응답이 트랜스크립트에 기록되기 직전에** 불릴 수 있다.
      실측한 턴에서 최종 답(2037자)과 훅 실행이 같은 초에 걸렸고, 훅은 그 직전
      상태를 읽어 중계 멘트(74자)를 최종 답으로 저장했다.

      나쁜 이유는 실패가 아니라 **성공처럼 보이기 때문**이다. seq 는 올라가고 JSON 도
      멀쩡하다. 음성은 답 대신 "이제 확인하겠습니다"를 읽는데 화면엔 단서가 없다.

    [WHY 타임스탬프 비교가 아닌가] '이번 턴의 마지막'을 시각으로 판정하려면 훅 호출
      시각과 기록 시각의 선후를 믿어야 하는데 둘은 같은 초 안에서 뒤집힌다.
      '파일이 더 안 자란다'는 그 가정이 필요 없다.
    """
    last: tuple[int, float] | None = None
    stable_since: float | None = None
    deadline = time.time() + cap
    while time.time() < deadline:
        try:
            st = os.stat(path)
        except OSError:
            return
        cur = (st.st_size, st.st_mtime)
        if cur == last:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= quiet:
                return
        else:
            last = cur
            stable_since = None
        time.sleep(poll)


def read_tail_lines(path: str) -> list[str]:
    """파일 끝에서 TAIL_BYTES 만큼만 읽어 줄로 자른다.

    [제약] 첫 줄은 중간이 잘렸을 수 있다. 파싱 실패는 정상으로 취급하고 건너뛴다 —
      잘린 줄 하나 때문에 훅이 죽으면 안 된다.
    """
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
        raw = f.read()
    return raw.decode('utf-8', errors='replace').splitlines()


def extract(lines: list[str]) -> tuple[str, list[str]]:
    """마지막 assistant 응답 text 와, 그 턴의 모든 text 블록을 돌려준다.

    [🔴 어디까지가 '이번 턴'인가] 뒤에서부터 올라가다가 **사람이 친 user 메시지**를
      만나면 멈춘다. 도구 결과도 type=user 로 들어오는데(content 가 리스트) 그건 턴
      안이므로 경계가 아니다. 둘을 구분하지 않으면 턴이 통째로 뭉치거나 반대로 첫
      멘트에서 잘린다.
    """
    texts: list[str] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:                      # noqa: BLE001  잘린 줄·비JSON
            continue

        t = d.get('type')
        msg = d.get('message') or {}

        if t == 'user':
            content = msg.get('content')
            # 문자열이면 사람이 친 것 = 턴의 시작. 리스트면 tool_result 라 계속 간다.
            if isinstance(content, str):
                break
            continue

        if t != 'assistant':
            continue

        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if not isinstance(block, dict):
                continue
            # [🔴] thinking 은 여기서 걸러진다. 이 조건을 넓히지 말 것.
            if block.get('type') == 'text':
                s = (block.get('text') or '').strip()
                if s:
                    texts.append(s)

    texts.reverse()
    return (texts[-1] if texts else ''), texts


def resolve_slug(cwd: str) -> str:
    """이 턴이 어느 프로젝트의 것인지.

    [🔴 __file__ 이 아니라 stdin cwd 로 판정한다] 훅은 원본 파일이 공유 등록되어
      다른 프로젝트의 세션에서도 이 스크립트가 그대로 실행된다. __file__ 기준으로
      슬러그를 잡으면 남의 프로젝트 턴이 vibe-coding 파일에 쌓인다
      (project_hook_cross_project_boundary 참조 — 같은 결함이 과거에 났다).
    """
    if cwd:
        root = find_project_root_marker(Path(cwd))
        if root:
            return slugify(root)
        return slugify(Path(cwd))
    return slugify(ROOT_DIR)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:                          # noqa: BLE001
        return _quiet('bad stdin')

    # [🔴 재진입 방지] 문서가 명시한다 — Stop 훅이 다시 불릴 때는 이 값이 참이고,
    #   그때는 아무것도 하지 않고 성공으로 빠져야 한다. 안 지키면 루프가 된다.
    if payload.get('stop_hook_active'):
        return _quiet('reentrant')

    tp = payload.get('transcript_path') or ''
    if not tp or not os.path.isfile(tp):
        return _quiet('no transcript')

    # [🔴 반드시 읽기 전에 기다린다] 순서를 바꾸면 경쟁 상태가 그대로 돌아온다.
    wait_settle(tp)

    try:
        text, all_text = extract(read_tail_lines(tp))
    except Exception as e:                     # noqa: BLE001
        return _quiet(f'extract failed: {e}')

    if not text:
        return _quiet('no text block')

    cwd = payload.get('cwd', '') or ''
    slug = resolve_slug(cwd)
    tid = os.environ.get('TERMINAL_ID', '')

    truncated = len(text) > voice_turn.MAX_CHARS
    out = {
        'seq': voice_turn.next_seq(slug, tid),
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'session_id': payload.get('session_id', ''),
        'cwd': cwd,
        'terminal_id': voice_turn.normalize_terminal_id(tid),
        'text': text[:voice_turn.MAX_CHARS],
        'truncated': truncated,
        'chars': len(text),
        'blocks': len(all_text),
        'all_text': all_text[:-1][-5:],        # 중계 멘트는 최근 5개까지만
    }

    try:
        voice_turn.write(slug, tid, out)
    except Exception as e:                     # noqa: BLE001
        return _quiet(f'write failed: {e}')

    print(json.dumps({'suppressOutput': True}), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
