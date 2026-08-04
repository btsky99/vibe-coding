"""
FILE: api/connector_relay.py
DESCRIPTION: Discord 등 외부 connector의 한 턴을 헤드리스 claude로 실행하고 구조화된
             답변만 메시지 버스에 돌려주는 소비자. TUI 화면 스크레이프를 대체한다.

REVISION HISTORY:
- 2026-08-04 Claude: 신규 — PTY 화면 긁기(_clean_connector_output)를 stream-json 캡처로 교체.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

# [WHY 화면 스크레이프를 버렸나 — 2026-08-04 실측]
#   기존 경로는 Discord 메시지를 PTY(대화형 claude TUI)에 타이핑하고 화면 로그를 정규식으로
#   걸러 답변을 복원했다. TUI는 한 턴 동안 같은 화면을 수십 번 다시 그리므로 append-only
#   PTY 로그에는 스피너 프레임, 토큰 카운터, 박스 문자, 잘린 UTF-8(`프로젝��트`)이 섞인다.
#   실제 답변을 필터에 통과시킨 결과: "안녕하세요!CipherTrader작업도와드릴준비됐습니다"처럼
#   공백이 사라지거나, cmd.exe 부팅 배너가 통째로 '답변'으로 전송됐다.
#   정규식을 더 붙이는 것은 증상 가림이라 구조를 바꿨다 — claude를 `-p --output-format
#   stream-json`으로 따로 띄우면 답변이 애초에 구조화된 JSON으로 나온다.
# [WHY 이 방식이 검증됐나] api/lan_api.py의 원격 실행이 같은 조합(_build_chat_cmd + -p 인자
#   전달 + stdin=DEVNULL)을 이미 쓰고 있다. stdin=PIPE로 프롬프트를 주면
#   'stdin is not a terminal'로 실패한 이력이 있어 -p 인자 전달만이 이 코드베이스에서 검증됐다.
# [제약] connector 턴은 화면에 보이는 T1~T3 세션과 별개의 claude 세션에서 돈다.
#   같은 세션을 공유하려면 TUI를 다시 긁어야 하므로 의도적으로 분리했다. 대화 연속성은
#   아래 _SESSIONS의 --resume 으로 유지한다.

_RELAY_TIMEOUT_SEC = 600
_MAX_REPLY_CHARS = 6000

# [불변식] 같은 터미널의 연속 요청은 직렬 처리 — claude --resume은 같은 세션에 동시
#   두 턴이 들어오면 트랜스크립트가 꼬인다. 터미널별 락으로 한 번에 한 턴만 돈다.
_relay_locks: dict[str, threading.Lock] = {}
_relay_locks_guard = threading.Lock()

# [제약] 프로세스 메모리에만 산다 — 앱을 재시작하면 connector 대화가 새 세션으로 시작된다.
#   PostgreSQL 영속화는 Phase 6(세션 체크포인트)에서 함께 다룰 사안이라 여기서 선반영하지 않았다.
_SESSIONS: dict[str, str] = {}
_SESSIONS_GUARD = threading.Lock()


def _relay_lock(key: str) -> threading.Lock:
    with _relay_locks_guard:
        return _relay_locks.setdefault(key, threading.Lock())


def extract_stream_text(line: str) -> str:
    """claude stream-json 1줄 → 표시용 텍스트. handle_chat 파싱 미러(assistant/result/plain)."""
    line = line.strip()
    if not line:
        return ''
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return line + '\n'   # stream-json 아닌 일반 텍스트(폴백)
    mtype = msg.get('type', '')
    if mtype == 'assistant':
        content = msg.get('message', {}).get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        out.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        out.append(f"\n[도구: {block.get('name', '')}]\n")
            return ''.join(out)
    elif mtype == 'result':
        return ''   # result는 전체 재전송이라 중복 방지(assistant로 이미 스트리밍됨)
    return ''


def extract_session_id(line: str) -> str:
    """stream-json의 세션 ID. 첫 턴에서 받아둬야 다음 턴을 --resume으로 이어붙일 수 있다."""
    try:
        msg = json.loads(line.strip() or '{}')
    except json.JSONDecodeError:
        return ''
    return str(msg.get('session_id') or '') if isinstance(msg, dict) else ''


def resolve_cwd(terminal_id: str, config_file: Path, fallback: str) -> str:
    """터미널이 바인딩된 프로젝트 폴더.

    [WHY slug 역변환이 아니라 config] slugify는 'D:/x' → 'D--x'로 콜론을 지워 되돌릴 수 없다.
      config.json의 slot_projects가 슬롯→경로의 유일한 원천이며 daemons._discord_channel_bindings도
      같은 표를 본다. 여기서 다른 표를 만들면 Discord 채널이 엉뚱한 폴더에서 돌게 된다.
    [제약] slot_projects는 0-based, 터미널 ID는 1-based(T1 = 슬롯 0).
    """
    # [제약] config_file은 server.py가 주입하기 전이면 None일 수 있다(단위 테스트/부팅 경합).
    #   그때는 활성 프로젝트로 폴백한다 — 여기서 예외를 내면 턴 전체가 죽는다.
    if config_file is None:
        return fallback
    try:
        index = int(str(terminal_id).upper().removeprefix('T')) - 1
    except ValueError:
        return fallback
    try:
        config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
        path = str((config.get('slot_projects') or {}).get(str(index)) or '')
    except (json.JSONDecodeError, OSError):
        return fallback
    return path if path and Path(path).is_dir() else fallback


def _run_headless(cmd: list[str], cwd: str) -> tuple[str, str, int]:
    """claude 한 턴 실행 → (본문, 세션ID, 종료코드).

    [제약] stderr=DEVNULL — PIPE로 두면 stdout만 읽는 동안 stderr 버퍼가 차서 교착한다.
      대신 종료코드로 실패를 판정한다(lan_api와 동일 계약).
    """
    from infra import proc as _proc

    parts: list[str] = []
    session_id = ''
    process = _proc.popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, cwd=cwd, shell=True, encoding=None)
    killer = threading.Timer(_RELAY_TIMEOUT_SEC,
                             lambda: process.poll() is None and process.kill())
    killer.daemon = True
    killer.start()
    try:
        for raw in process.stdout:
            line = raw.decode('utf-8', 'replace')
            if not session_id:
                session_id = extract_session_id(line)
            parts.append(extract_stream_text(line))
        process.wait(timeout=5)
    finally:
        killer.cancel()
        if process.poll() is None:
            process.kill()
    return ''.join(parts).strip(), session_id, process.returncode or 0


def relay_turn(terminal_id: str, project_id: str, content: str, request_seq: int,
               bus_append, config_file: Path, fallback_cwd: str) -> None:
    """버스에 들어온 connector 요청 한 건을 실행하고 답변을 버스에 되돌린다.

    [불변식] 어떤 실패 경로에서도 반드시 assistant 메시지를 한 번 남긴다 —
      connector(gateway)는 reply_to_seq 상관 응답을 폴링하다 없으면 180초를 통째로 기다린다.
      '조용히 아무 일도 안 일어남'이 가장 디버깅하기 어려운 실패 모드라서 오류도 본문으로 보낸다.
    """
    from api.agent_api import _build_chat_cmd

    session_key = f'{terminal_id}:{project_id}'
    with _relay_lock(session_key):
        with _SESSIONS_GUARD:
            session_id = _SESSIONS.get(session_key) or None
        cwd = resolve_cwd(terminal_id, config_file, fallback_cwd)
        try:
            # [보안 — yolo=True인 이유] 기존 PTY 경로가 이미 `--dangerously-skip-permissions`로
            #   뜬 터미널에 타이핑했으므로 이것은 권한 확대가 아니라 동등 이관이다. 헤드리스에서
            #   권한 프롬프트가 뜨면 응답할 주체가 없어 매 요청이 타임아웃된다.
            #   원격 입력을 로컬보다 좁히는 것은 Phase 5(승인 게이트)의 과제 —
            #   docs/DISCORD_HARNESS_INTEGRATION_PLAN.md §3.1.7. 여기서 임의로 좁히면
            #   Discord 요청이 조용히 아무 일도 못 하게 된다.
            cmd = _build_chat_cmd('claude', session_id, yolo=True, message=content)
            body, new_session, code = _run_headless(cmd, cwd)
        except Exception as error:                      # noqa: BLE001 — 어떤 실패든 버스로 알린다
            bus_append(terminal_id, 'connector', 'assistant',
                       f'실행 실패: {type(error).__name__}', reply_to_seq=request_seq,
                       error=type(error).__name__)
            return

        # [과거사고 대비] --resume 세션이 만료/삭제되면 claude가 즉시 비정상 종료한다.
        #   저장된 세션을 버리고 새 세션으로 한 번만 재시도해야 채널이 영구히 죽지 않는다.
        if code != 0 and session_id:
            with _SESSIONS_GUARD:
                _SESSIONS.pop(session_key, None)
            try:
                body, new_session, code = _run_headless(
                    _build_chat_cmd('claude', None, yolo=True, message=content), cwd)
            except Exception as error:                  # noqa: BLE001
                bus_append(terminal_id, 'connector', 'assistant',
                           f'실행 실패: {type(error).__name__}', reply_to_seq=request_seq,
                           error=type(error).__name__)
                return

        if new_session:
            with _SESSIONS_GUARD:
                _SESSIONS[session_key] = new_session

        if code != 0:
            # 출력이 비어도 무음으로 'done' 처리하지 않는다 — 인자/실행엔진 오류가 여기로 드러난다.
            note = body or f'claude 종료코드 {code} — 출력 없음(실행엔진/인자 확인)'
            bus_append(terminal_id, 'connector', 'assistant', note[-_MAX_REPLY_CHARS:],
                       reply_to_seq=request_seq, error=f'exit_{code}')
            return

        bus_append(terminal_id, 'connector', 'assistant',
                   (body or '실행은 끝났지만 응답 본문이 비어 있습니다.')[-_MAX_REPLY_CHARS:],
                   reply_to_seq=request_seq)
