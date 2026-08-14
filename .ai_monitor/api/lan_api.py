"""
FILE: api/lan_api.py
DESCRIPTION: /api/lan/* 핸들러 — 프론트(127.0.0.1 로컬서버)가 LAN 브리지를 제어하는 통로.
             실제 LAN 통신은 lan_bridge.py 프로세스가 하고, 여기서는 로컬 프록시만 한다.
             브리지 포트는 data_dir/lan_bridge_port 파일에서 얻는다(파일 부재=브리지 꺼짐).

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 6. project_id 비의존(이식성).
- 2026-07-22 Claude: Phase 3 Task 5/6 — 원격 에이전트 실행 전송/승인 API + 출력캡처 스레드.
  마스터 게이트 lan_remote_exec_enabled(기본 OFF) + 3중 보안. 실행=agent_api 재사용.
"""
# [WHY 프록시 구조] 프론트 → 로컬서버(lan_api) → 브리지(로컬 9020~). 프론트가 브리지에 직접
#   붙지 않는 이유: 브리지 포트가 동적이라 프론트가 모르고, 기존 UI는 전부 로컬서버 경유라
#   경로 일관성 유지. 브리지 꺼짐/살아있음도 여기서 running 플래그로 흡수.
import hashlib
import json
import subprocess as _sp
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.server_utils import send_json
from src.pg_lan import (save_lan_message, get_lan_messages, get_lan_room_messages,
                        save_lan_exec, update_lan_exec_status, get_lan_exec_log)

# [그룹방] to_peer 특수값 — 방 메시지는 상대 지정 없이 이 값으로 저장된다(1:1과 저장 분리).
ROOM_ID = '*'

# [Phase3] 실행 중인 원격 exec 프로세스 — exec_id → Popen. 취소/중복정리용(단일 lan_api 프로세스).
_EXEC_PROCS: dict = {}
_EXEC_LOCK = threading.Lock()
# [Phase3 Task11] 원격 실행 최대 수명 — 무한 실행/방치 프로세스 차단. 초과 시 강제종료.
_EXEC_TIMEOUT_SEC = 30 * 60
# [보안 W4] 수신 후 이 시간 초과한 대기 요청은 drain 시 폐기 — 토글 OFF 구간에 큐잉된
#   과거 요청이 토글 ON 순간 일괄(특히 auto 무팝업) 실행되는 버스트를 차단.
_EXEC_STALE_SEC = 120


def _exec_ts_age_sec(ts_str: str) -> float:
    """브리지 수신 ts('%Y-%m-%dT%H:%M:%S', 로컬) → 경과 초. 파싱 실패 시 0(안전측: 최신 취급)."""
    if not ts_str:
        return 0.0
    try:
        return max(0.0, time.time() - time.mktime(time.strptime(ts_str, '%Y-%m-%dT%H:%M:%S')))
    except (ValueError, OverflowError):
        return 0.0


def _bridge_port(data_dir: Path) -> int | None:
    f = Path(data_dir) / 'lan_bridge_port'
    if not f.exists():
        return None
    try:
        return int(f.read_text(encoding='utf-8').strip())
    except (ValueError, OSError):
        return None


def _proxy(data_dir: Path, method: str, subpath: str, body: dict | None = None) -> dict:
    """브리지로 요청 전달. 브리지 꺼짐이면 running:false, 통신 실패면 error."""
    port = _bridge_port(data_dir)
    if not port:
        return {'running': False, 'error': 'LAN 브리지가 꺼져 있음'}
    url = f'http://127.0.0.1:{port}/lan/{subpath}'
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    try:
        req = Request(url, data=data, method=method, headers=headers)
        with urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read())
        out.setdefault('running', True)
        return out
    except URLError as e:
        # 포트 파일은 있으나 연결 불가 = 브리지 비정상 종료(파일 stale).
        return {'running': False, 'error': f'브리지 통신 실패: {e}'}


def _self_id(dd: Path) -> str:
    """브리지 status에서 이 기기 self_id 획득 — 채팅 DB 저장/조회의 '나' 식별자."""
    return _proxy(dd, 'GET', 'status').get('self_id', '')


# ── 자동 공유(auto-share) 안전장치 유틸 ──────────────────────────────
# [WHY] 클로드 자율 판단 발송은 오발송/프라이버시 사고 위험이 커, 서버측에서 강제하는
#   방어선(민감필터·dedup·레이트리밋)을 프론트/스킬이 우회 못하게 여기 고정한다.
#   설계: memory project_lan_auto_share.md (A안, 마스터 토글 기본 OFF).

# [불변식] 파일명(경로 아님) 소문자에 부분일치. 확장자·키워드 양쪽 커버.
_SENSITIVE_PATTERNS = (
    '.env', 'credential', 'secret', 'token', 'password', 'passwd',
    '.pem', '.key', '.pfx', '.p12', 'id_rsa', '.keystore', 'apikey', 'api_key',
)
# [제약] 레이트리밋은 프로세스 메모리(단일 lan_api 프로세스 전제). 재시작 시 리셋 — 스팸
#   억제가 목적이라 영속화 불필요. dedup은 파일로 영속(재시작 후에도 재발송 방지).
_SHARE_SENT_TS: deque = deque()
_RATE_MAX_PER_MIN = 20


def _config(dd: Path) -> dict:
    f = dd / 'config.json'
    if f.exists():
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return {}
    return {}


def _is_sensitive(path: str) -> bool:
    """민감 파일이면 True — 발송 차단. 경로 구분자 무관하게 파일명만 검사."""
    name = path.lower().replace('\\', '/').rsplit('/', 1)[-1]
    return any(pat in name for pat in _SENSITIVE_PATTERNS)


def _hash_file(path: str) -> str | None:
    """파일 내용 sha256. dedup 키 — 내용이 바뀌면 해시가 달라져 재발송 허용."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as fp:
            for chunk in iter(lambda: fp.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load_seen(dd: Path) -> set:
    f = dd / 'lan_share_seen.json'
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            return set()
    return set()


def _save_seen(dd: Path, seen: set) -> None:
    # [제약] 무한 증가 방지 — 최근 500개만 유지. 오래된 해시는 재발송 가능해지지만
    #   실사용상 같은 산출물을 500건 뒤에 다시 보낼 일은 드물어 수용.
    try:
        (dd / 'lan_share_seen.json').write_text(
            json.dumps(sorted(seen)[-500:]), encoding='utf-8')
    except OSError:
        pass


def _rate_ok() -> bool:
    now = time.time()
    while _SHARE_SENT_TS and now - _SHARE_SENT_TS[0] > 60:
        _SHARE_SENT_TS.popleft()
    return len(_SHARE_SENT_TS) < _RATE_MAX_PER_MIN


def _pick_online_peer(dd: Path, req_peer: str):
    """온라인이면서 페어링된(신뢰) 피어를 고른다.
    반환: (peer_dict, reason). peer_dict None이면 reason에 실패 사유.
    [불변식] online ∩ trusted 만 대상 — 발견됐지만 미페어링 피어로는 절대 안 보냄."""
    status = _proxy(dd, 'GET', 'status')
    if not status.get('running', False):
        return None, {'reason': 'bridge_off'}
    online = status.get('online', []) or []
    trusted_ids = {p.get('peer_id') for p in (status.get('trusted', []) or [])}
    paired = [p for p in online if p.get('peer_id') in trusted_ids]
    if req_peer:
        peer = next((p for p in paired if p.get('peer_id') == req_peer), None)
        return (peer, None) if peer else (None, {'reason': 'peer_offline'})
    if len(paired) == 1:
        return paired[0], None
    if not paired:
        return None, {'reason': 'no_peer'}
    return None, {'reason': 'ambiguous', 'peers': paired}


# ── 원격 실행 러너 (Phase 3 Task 6) ──────────────────────────────────
# [WHY 재사용] agent_api의 명령 빌더(_build_chat_cmd)와 콘솔숨김 popen(_proc.popen)을
#   그대로 재사용 — claude 실행법 중복 금지([[feedback-no-duplicates]]). 다른 점은 출력 목적지:
#   handle_chat은 SSE로 브라우저에 보내지만, 여기선 브리지 exec-emit로 요청자에게 역방향 릴레이.
# [제약] handle_run(싱글턴+SSE)은 caller가 출력을 폴링할 수 없어 부적합 → 전용 캡처 스레드.

def _extract_stream_text(line: str) -> str:
    """claude stream-json 1줄 → 표시용 텍스트.

    [2026-08-14] api/connector_relay.py에서 이관 — Discord 커넥터 계층을 걷어내며
      유일하게 남은 소비자가 여기가 됐다. 원래 '중복 금지'로 relay에 두고 빌려
      썼는데, 빌려주던 쪽이 사라졌으니 소비자가 소유한다.
    [제약] agent_api.handle_chat의 파싱과 형식이 같아야 한다 — 같은 claude
      stream-json을 읽는다. 한쪽 출력 형식이 바뀌면 양쪽을 같이 고칠 것.
    """
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


def _run_remote_exec(dd: Path, peer_id: str, exec_id: str, task: str, project_id: str,
                     target_dir: str = '') -> None:
    """[대상측] 승인된 태스크를 격리된 작업공간에서 claude로 실행하며 출력을 역방향 푸시.

    [보안 — 2026-07-30 전면 교체] 이전 구현은 `yolo=True`(--dangerously-skip-permissions) +
    `cwd=_project_root`였다. 3중 게이트가 '누가 요청하나'만 막고 '무엇을 건드리나'는 무제한이라,
    페어링된 PC가 수신 PC의 프로젝트 루트를 통째로 편집할 수 있었다. 지금은:
      ① target_dir이 화이트리스트(lan_exec_allowed_dirs) 이하인지 검증 — 미등록이면 실행 거부
      ② copy 모드면 worktree/사본에서 실행 → 원본이 클로드 시야에 없음
      ③ yolo 제거, deny 프로파일을 --settings로 주입
    [제약] direct 모드는 완전 격리가 아니다 — deny는 Bash 접두 매칭이라 절대경로 Edit을 못 막는다
    (src/lan_sandbox.SANDBOX_SETTINGS 주석 참조). 사용자가 명시적으로 등록한 폴더에만 허용된다.
    출력 원문은 DB에 안 남기고 요약 절단본만(Critic).
    """
    from infra import proc as _proc          # 지연 import(순환 회피)
    from src import lan_sandbox
    try:
        from api.agent_api import _build_chat_cmd
    except Exception as e:
        update_lan_exec_status(exec_id, 'error', f'실행엔진 로드 실패: {e}', project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': f'[오류] {e}', 'done': True})
        return

    # [게이트④ 폴더] 화이트리스트 검증 + 작업공간 준비. 실패 사유는 요청자에게 그대로 알린다
    #   — '조용히 아무 일도 안 일어남'이 가장 디버깅하기 어려운 실패 모드라서.
    ws = None
    try:
        target, mode = lan_sandbox.resolve_target(_config(dd), target_dir)
        ws = lan_sandbox.prepare_workspace(target, mode, exec_id, dd)
        settings_path = str(lan_sandbox.materialize_settings(dd))
    except lan_sandbox.SandboxError as e:
        update_lan_exec_status(exec_id, 'error', f'[폴더 거부] {e}', project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': f'[폴더 거부] {e}', 'done': True})
        return

    # [리뷰 C1] task를 -p 인자로 전달 + stdin=DEVNULL — handle_chat의 유일 검증된 claude 실행 패턴.
    #   [과거사고] claude에 stdin=PIPE로 프롬프트를 주면 'stdin is not a terminal' 실패 이력이 있어
    #   -p 인자 전달만이 이 코드베이스에서 검증됐다(claude-api 확인). 셸 메타문자 잔여 위험(보안 W1)은
    #   승인 팝업(태스크 전문 표시)+yolo 전제상 handle_chat과 동일 수준으로 수용 — 임의 실행은 이미 승인됨.
    cmd = _build_chat_cmd('claude', None, yolo=False, message=task, settings_path=settings_path)
    full: list[str] = []
    proc = None
    watchdog = None
    try:
        _proxy(dd, 'POST', 'exec-emit', {
            'peer_id': peer_id, 'exec_id': exec_id, 'done': False,
            'chunk': f'[샌드박스] {ws.kind} 모드 · 작업 폴더: {ws.cwd}\n'})
        proc = _proc.popen(cmd, stdin=_sp.DEVNULL, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                           cwd=str(ws.cwd), shell=True, encoding=None)
        with _EXEC_LOCK:
            _EXEC_PROCS[exec_id] = proc
        # [Task11] 타임아웃 워치독 — 초과 시 kill. stdout 루프가 break되며 정리로 이어짐.
        watchdog = threading.Timer(_EXEC_TIMEOUT_SEC,
                                   lambda: proc.poll() is None and proc.kill())
        watchdog.daemon = True
        watchdog.start()
        update_lan_exec_status(exec_id, 'running', '', project_id)
        for raw in proc.stdout:
            text = _extract_stream_text(raw.decode('utf-8', 'replace'))
            if text:
                full.append(text)
                _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                                 'chunk': text, 'done': False})
        proc.wait(timeout=5)
        # [리뷰 C2] 종료코드 확인 — claude가 인자 오류 등으로 즉시 죽어 출력이 비어도 'done'으로
        #   오기록되던 무음 실패 차단. stderr=DEVNULL(데드락 회피)이라 코드로만 성패를 판정한다.
        rc = proc.returncode
        if rc not in (0, None):
            note = f'[실행 실패: claude 종료코드 {rc}' + ('' if full else ' — 출력 없음(실행엔진/인자 확인)') + ']'
            update_lan_exec_status(exec_id, 'error', (''.join(full)[-2000:] or note), project_id)
            _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                             'chunk': note, 'done': True})
        else:
            summary = ''.join(full)[-2000:]
            update_lan_exec_status(exec_id, 'done', summary, project_id)
            # [WHY 변경목록 통지] copy 모드는 원본에 아무것도 반영되지 않는다. 무엇이 바뀌었고
            #   사본이 어디 있는지 알려주지 않으면 원격 작업 결과가 사본에 갇혀 유실된다.
            #   반영 여부는 사람이 결정하는 것이 Phase A 계약(자동 머지 금지).
            tail = ''
            try:
                changed = ws.finish(keep=True)
                if ws.is_copy:
                    listed = '\n'.join('  ' + c for c in changed[:50]) or '  (변경 없음)'
                    more = f'\n  … 외 {len(changed) - 50}개' if len(changed) > 50 else ''
                    tail = (f'\n[변경 파일 {len(changed)}개 — 원본 아닌 사본에 반영됨]\n'
                            f'{listed}{more}\n[사본 위치] {ws.cwd}\n')
            except Exception as e:
                tail = f'\n[변경목록 수집 실패] {e}\n'
            _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                             'chunk': tail, 'done': True})
    except Exception as e:
        update_lan_exec_status(exec_id, 'error', str(e)[:2000], project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': f'[실행 오류] {e}', 'done': True})
    finally:
        # [리뷰 W4] 예외/타임아웃/취소 어느 경로든 자식 프로세스를 반드시 정리(30분 워치독에만 의존 금지).
        if watchdog is not None:
            watchdog.cancel()
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        with _EXEC_LOCK:
            _EXEC_PROCS.pop(exec_id, None)


def _start_exec(dd: Path, peer_id: str, exec_id: str, task: str, project_id: str,
                target_dir: str = '') -> None:
    """실행 러너를 데몬 스레드로 시작(승인 시 호출). HTTP 핸들러를 막지 않음.

    [제약] target_dir은 요청자가 보낸 값 — 신뢰하지 않는다. 검증은 _run_remote_exec 진입부의
    resolve_target이 담당한다(스레드 안에서 실패해도 요청자에게 사유가 emit되도록).
    """
    threading.Thread(target=_run_remote_exec,
                     args=(dd, peer_id, exec_id, task, project_id, target_dir),
                     daemon=True, name=f'lan-exec-{exec_id[:8]}').start()


def _drain_chat_inbox(dd: Path, self_id: str, project_id: str) -> None:
    """브리지 수신버퍼를 1회성으로 비워 DB에 옮긴다. 1:1/그룹방 폴링이 공유하는 헬퍼.

    [불변식] 브리지 chat-drain은 큐를 비우는 1회성 호출이다. 1:1 폴링과 방 폴링이 각자
    다르게 저장하면 먼저 호출한 쪽이 상대 메시지를 잘못된 스코프로 저장해버린다 →
    저장 로직을 여기 하나로 모아 어느 쪽이 먼저 폴링해도 결과가 같게 만든다.
    """
    drained = _proxy(dd, 'GET', 'chat-drain')
    for m in drained.get('messages', []) or []:
        to = ROOM_ID if m.get('scope') == 'room' else self_id
        save_lan_message(m.get('from_peer', ''), to, m.get('content', ''), project_id)


def handle_get(handler, path: str, params: dict, *, DATA_DIR, PROJECT_ID='') -> bool:
    """GET /api/lan/{status,chat,exec/pending,exec/output,exec/log}."""
    dd = Path(DATA_DIR)
    if path == '/api/lan/status':
        send_json(handler, _proxy(dd, 'GET', 'status'))
        return True
    if path == '/api/lan/chat':
        peer_id = params.get('peer_id', [''])[0]
        since = params.get('since', ['0'])[0]
        self_id = _self_id(dd)
        # ① 브리지 수신버퍼를 비우며 내 DB로 옮긴다(브리지는 project_id 무지 → 여기서 저장).
        #   [그룹방] scope='room'이면 to_peer=ROOM_ID로 저장해 방 쿼리에 걸리게 한다. 1:1로
        #   저장하면 방에 안 보이고, 반대로 하면 1:1 창에 남의 방 메시지가 섞인다.
        _drain_chat_inbox(dd, self_id, PROJECT_ID)
        # ② DB에서 나↔peer 대화를 since 커서로 증분 반환.
        rows = get_lan_messages(self_id, peer_id, since, PROJECT_ID) if peer_id else []
        send_json(handler, {'self_id': self_id, 'messages': rows})
        return True
    if path == '/api/lan/chat/room':
        # [그룹방] 방 메시지 증분 조회. drain은 1:1과 공유(브리지 버퍼가 하나라 어느 쪽을
        #   폴링해도 양쪽 메시지가 DB로 넘어가야 한다).
        since = params.get('since', ['0'])[0]
        self_id = _self_id(dd)
        _drain_chat_inbox(dd, self_id, PROJECT_ID)
        send_json(handler, {'self_id': self_id,
                            'messages': get_lan_room_messages(since, PROJECT_ID)})
        return True
    if path == '/api/lan/exec/pending':
        # [리뷰C3] 취소 신호 먼저 처리 — 토글 상태와 무관하게 실행 중 프로세스를 죽인다
        #   (실행 중이면 이미 토글 ON이었던 상태라 여기서 drain해야 취소가 실효).
        cancels = _proxy(dd, 'GET', 'exec-cancel-drain')
        for cxid in cancels.get('exec_ids', []) or []:
            with _EXEC_LOCK:
                p = _EXEC_PROCS.get(cxid)
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
            update_lan_exec_status(cxid, 'error', '[요청자 취소]', PROJECT_ID)
        # [Phase3 게이트①] 마스터 토글 OFF면 대기건을 절대 회수하지 않는다(우회 불가한 관문).
        #   OFF인 PC는 상대가 태스크를 보내도 브리지 큐에 쌓일 뿐 승인 UI에 노출 안 됨.
        if not _config(dd).get('lan_remote_exec_enabled', False):
            send_json(handler, {'enabled': False, 'pending': []})
            return True
        drained = _proxy(dd, 'GET', 'exec-pending-drain')
        pending_out = []
        for item in drained.get('pending', []) or []:
            # [W4] 오래된(토글 OFF 구간 누적) 요청은 폐기 — 저장/승인/실행 어느 것도 안 함.
            if _exec_ts_age_sec(item.get('ts', '')) > _EXEC_STALE_SEC:
                continue
            exec_id = item.get('exec_id', '')
            from_peer = item.get('from_peer', '')
            task = item.get('task', '')
            save_lan_exec(exec_id, 'in', from_peer, task, 'received', PROJECT_ID)
            if item.get('exec_trust') == 'auto':
                # 자동승인 피어 — 팝업 생략하고 즉시 실행(감사로그는 이미 기록됨).
                #   [보안] auto여도 폴더 화이트리스트는 우회 못 함 — 검증은 러너 진입부.
                _start_exec(dd, from_peer, exec_id, task, PROJECT_ID, item.get('target_dir', ''))
            else:
                pending_out.append(item)   # 'ask' — 승인 팝업으로 노출
        send_json(handler, {'enabled': True, 'pending': pending_out})
        return True
    if path == '/api/lan/exec/output':
        exec_id = params.get('exec_id', [''])[0]
        drained = _proxy(dd, 'GET', f'exec-output-drain?exec_id={exec_id}')
        send_json(handler, {'chunks': drained.get('chunks', [])})
        return True
    if path == '/api/lan/exec/log':
        send_json(handler, {'log': get_lan_exec_log(PROJECT_ID, 100)})
        return True
    if path == '/api/lan/exec/dirs':
        # [Phase A] 내 PC가 원격실행에 허용한 폴더 목록 + 마스터 토글 상태(UI 관리용).
        from src.lan_sandbox import allowed_dirs
        cfg = _config(dd)
        send_json(handler, {'enabled': bool(cfg.get('lan_remote_exec_enabled', False)),
                            'dirs': allowed_dirs(cfg)})
        return True
    if path == '/api/lan/exec/peer-dirs':
        # [Phase A] 상대 PC가 허용한 폴더 목록 — 전송 UI의 폴더 선택지.
        peer_id = params.get('peer_id', [''])[0]
        send_json(handler, _proxy(dd, 'POST', 'exec-dirs', {'peer_id': peer_id}))
        return True
    return False


def handle_post(handler, path: str, data: dict, *, DATA_DIR, PROJECT_ID='') -> bool:
    """POST /api/lan/{pair-begin,pair-connect,send,chat-send}."""
    dd = Path(DATA_DIR)
    if path == '/api/lan/pair-begin':
        send_json(handler, _proxy(dd, 'POST', 'pair-begin', {}))
        return True
    if path == '/api/lan/pair-connect':
        send_json(handler, _proxy(dd, 'POST', 'pair-connect', data or {}))   # {ip, http_port, code}
        return True
    if path == '/api/lan/send':
        send_json(handler, _proxy(dd, 'POST', 'send', data or {}))           # {peer_id, path}
        return True
    if path == '/api/lan/chat-send':
        peer_id = (data or {}).get('peer_id', '')
        content = (data or {}).get('content', '')
        res = _proxy(dd, 'POST', 'chat-send', {'peer_id': peer_id, 'content': content})
        if res.get('ok'):
            # 내 발신분도 내 DB에 기록(양쪽이 각자 자기 DB에 이력 보유).
            save_lan_message(_self_id(dd), peer_id, content, PROJECT_ID)
        send_json(handler, res)
        return True
    if path == '/api/lan/chat-room-send':
        # [그룹방] 페어링 전원 팬아웃. 일부 피어가 오프라인이어도 나머지에게 가면 성공으로 본다
        #   — 한 대 꺼진 걸로 방 전체를 막으면 방이 사실상 죽는다(브리지 broadcast_chat과 동일 계약).
        content = (data or {}).get('content', '')
        if not str(content).strip():
            send_json(handler, {'ok': False, 'error': '빈 메시지'})
            return True
        res = _proxy(dd, 'POST', 'chat-broadcast', {'content': content})
        if res.get('ok'):
            save_lan_message(_self_id(dd), ROOM_ID, content, PROJECT_ID)
        send_json(handler, res)
        return True
    if path == '/api/lan/exec':
        # [Phase3 요청자] 태스크 전송. exec_id 생성 → 브리지 → 상대. 감사로그(out) 기록.
        peer_id = (data or {}).get('peer_id', '')
        task = (data or {}).get('task', '')
        target_dir = (data or {}).get('target_dir', '')
        if not peer_id or not task.strip():
            send_json(handler, {'ok': False, 'error': 'peer_id/task 필요'})
            return True
        if not str(target_dir).strip():
            # [WHY 여기서 막나] 폴더 없이 보내면 상대가 '폴더 거부'로 응답할 뿐이라 왕복 낭비 +
            #   사용자에게는 그냥 실패로 보인다. 요청자 쪽에서 먼저 걸러 원인을 명확히 알린다.
            send_json(handler, {'ok': False, 'error': '작업 폴더를 선택하세요 (상대 PC가 허용한 폴더만 가능)'})
            return True
        exec_id = uuid.uuid4().hex
        res = _proxy(dd, 'POST', 'exec-send',
                     {'peer_id': peer_id, 'exec_id': exec_id, 'task': task,
                      'target_dir': target_dir})
        if res.get('ok'):
            save_lan_exec(exec_id, 'out', peer_id, task, 'running', PROJECT_ID)
        send_json(handler, {**res, 'exec_id': exec_id})
        return True
    if path == '/api/lan/exec/approve':
        # [Phase3 대상] 승인 팝업의 '승인'. trust='auto'면 이후 자동승인으로 격상.
        d = data or {}
        exec_id = d.get('exec_id', '')
        from_peer = d.get('from_peer', '')
        task = d.get('task', '')
        if d.get('trust') == 'auto':
            _proxy(dd, 'POST', 'exec-trust', {'peer_id': from_peer, 'mode': 'auto'})
        update_lan_exec_status(exec_id, 'approved', '', PROJECT_ID)
        _start_exec(dd, from_peer, exec_id, task, PROJECT_ID, d.get('target_dir', ''))
        send_json(handler, {'ok': True})
        return True
    if path == '/api/lan/exec/reject':
        # [Phase3 대상] 승인 거부 — 상태 기록 + 요청자에게 거부 통지(done).
        d = data or {}
        exec_id = d.get('exec_id', '')
        from_peer = d.get('from_peer', '')
        update_lan_exec_status(exec_id, 'rejected', '', PROJECT_ID)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': from_peer, 'exec_id': exec_id,
                                         'chunk': '[상대가 실행을 거부함]', 'done': True})
        send_json(handler, {'ok': True})
        return True
    if path == '/api/lan/exec/cancel':
        # [리뷰C3] 요청자측: 대상에게 취소 릴레이 → 대상 server가 drain해 claude(yolo)를 실제 kill.
        #   로컬 kill만으로는 대상 프로세스가 계속 도는 문제를 해결. peer_id는 프론트가 전달.
        exec_id = (data or {}).get('exec_id', '')
        peer_id = (data or {}).get('peer_id', '')
        if peer_id:
            _proxy(dd, 'POST', 'exec-cancel', {'peer_id': peer_id, 'exec_id': exec_id})
        # 내 PC가 실행 대상이기도 한 경우(로컬 실행)엔 즉시 kill로 보강.
        with _EXEC_LOCK:
            proc = _EXEC_PROCS.get(exec_id)
        killed = False
        if proc and proc.poll() is None:
            try:
                proc.kill(); killed = True
            except Exception:
                pass
        if killed:
            update_lan_exec_status(exec_id, 'error', '[취소됨]', PROJECT_ID)
        send_json(handler, {'ok': True, 'killed': killed})
        return True
    if path == '/api/lan/auto-share':
        # [WHY] 클로드 자율 판단 발송의 서버측 관문. 입력 {files:[path...], summary, peer_id?}.
        #   마스터 토글 OFF면 no-op — 우회 불가하게 여기서 강제한다.
        if not _config(dd).get('lan_auto_share_enabled', False):
            send_json(handler, {'ok': False, 'reason': 'disabled'})
            return True
        files = (data or {}).get('files', []) or []
        summary = (data or {}).get('summary', '') or ''
        peer, err = _pick_online_peer(dd, (data or {}).get('peer_id', '') or '')
        if peer is None:
            send_json(handler, {'ok': False, **err})
            return True
        if not _rate_ok():
            send_json(handler, {'ok': False, 'reason': 'rate_limited'})
            return True
        peer_id = peer.get('peer_id', '')
        seen = _load_seen(dd)
        sent_files, skipped = [], []
        for fp in files:
            if _is_sensitive(fp):
                skipped.append({'path': fp, 'why': 'sensitive'}); continue
            fh = _hash_file(fp)
            if fh is None:
                skipped.append({'path': fp, 'why': 'unreadable'}); continue
            if ('f:' + fh) in seen:
                skipped.append({'path': fp, 'why': 'dup'}); continue
            if not _rate_ok():
                skipped.append({'path': fp, 'why': 'rate_limited'}); continue
            r = _proxy(dd, 'POST', 'send', {'peer_id': peer_id, 'path': fp})
            if r.get('ok'):
                sent_files.append(fp); seen.add('f:' + fh); _SHARE_SENT_TS.append(time.time())
            else:
                skipped.append({'path': fp, 'why': 'send_failed', 'detail': r.get('error', 'unknown')})
        summary_sent = False
        if summary:
            s = summary[:8000]   # 브리지 chat 상한(8KB) 상속
            skey = 's:' + hashlib.sha256(s.encode('utf-8')).hexdigest()
            if skey not in seen and _rate_ok():
                r = _proxy(dd, 'POST', 'chat-send', {'peer_id': peer_id, 'content': s})
                if r.get('ok'):
                    summary_sent = True; seen.add(skey); _SHARE_SENT_TS.append(time.time())
                    save_lan_message(_self_id(dd), peer_id, s, PROJECT_ID)
        _save_seen(dd, seen)
        send_json(handler, {
            'ok': True, 'peer': peer.get('name') or peer_id, 'peer_id': peer_id,
            'sent_files': sent_files, 'skipped': skipped, 'summary_sent': summary_sent,
        })
        return True
    return False
