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
from src.pg_lan import (save_lan_message, get_lan_messages,
                        save_lan_exec, update_lan_exec_status, get_lan_exec_log)

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


def _run_remote_exec(dd: Path, peer_id: str, exec_id: str, task: str, project_id: str) -> None:
    """[대상측] 승인된 태스크를 claude로 실행하며 출력을 브리지로 역방향 푸시.

    [보안] yolo(권한 스킵) — 원격 자율 실행이라 대상에 사람이 대기하지 않음. 승인 팝업이
    이미 게이트했고 내 PC끼리 전제. 출력 원문은 DB에 안 남기고 요약 절단본만(Critic).
    """
    from infra import proc as _proc          # 지연 import(순환 회피)
    try:
        from api.agent_api import _build_chat_cmd, _project_root
    except Exception as e:
        update_lan_exec_status(exec_id, 'error', f'실행엔진 로드 실패: {e}', project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': f'[오류] {e}', 'done': True})
        return

    # [보안 A03] task를 -p 인자로 셸 명령줄에 실으면 Windows list2cmdline이 cmd.exe 메타문자
    #   (& | > < ^ %)를 이스케이프하지 않아 하위명령이 분리 실행된다(감사로그↔실제셸 불일치).
    #   프롬프트를 stdin으로 전달해 명령줄엔 고정 토큰만 남긴다 → task 미노출로 인젝션 원천 차단.
    #   claude print 모드(-p)는 프롬프트 인자가 없으면 stdin에서 읽는다.
    cmd = _build_chat_cmd('claude', None, yolo=True, message='')
    cmd.append('-p')
    full: list[str] = []
    try:
        proc = _proc.popen(cmd, stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                           cwd=_project_root or None, shell=True, encoding=None)
        try:
            proc.stdin.write(task.encode('utf-8'))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
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
        watchdog.cancel()
        summary = ''.join(full)[-2000:]
        update_lan_exec_status(exec_id, 'done', summary, project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': '', 'done': True})
    except Exception as e:
        update_lan_exec_status(exec_id, 'error', str(e)[:2000], project_id)
        _proxy(dd, 'POST', 'exec-emit', {'peer_id': peer_id, 'exec_id': exec_id,
                                         'chunk': f'[실행 오류] {e}', 'done': True})
    finally:
        with _EXEC_LOCK:
            _EXEC_PROCS.pop(exec_id, None)


def _start_exec(dd: Path, peer_id: str, exec_id: str, task: str, project_id: str) -> None:
    """실행 러너를 데몬 스레드로 시작(승인 시 호출). HTTP 핸들러를 막지 않음."""
    threading.Thread(target=_run_remote_exec, args=(dd, peer_id, exec_id, task, project_id),
                     daemon=True, name=f'lan-exec-{exec_id[:8]}').start()


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
        drained = _proxy(dd, 'GET', 'chat-drain')
        for m in drained.get('messages', []):
            save_lan_message(m.get('from_peer', ''), self_id, m.get('content', ''), PROJECT_ID)
        # ② DB에서 나↔peer 대화를 since 커서로 증분 반환.
        rows = get_lan_messages(self_id, peer_id, since, PROJECT_ID) if peer_id else []
        send_json(handler, {'self_id': self_id, 'messages': rows})
        return True
    if path == '/api/lan/exec/pending':
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
                _start_exec(dd, from_peer, exec_id, task, PROJECT_ID)
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
    if path == '/api/lan/exec':
        # [Phase3 요청자] 태스크 전송. exec_id 생성 → 브리지 → 상대. 감사로그(out) 기록.
        peer_id = (data or {}).get('peer_id', '')
        task = (data or {}).get('task', '')
        if not peer_id or not task.strip():
            send_json(handler, {'ok': False, 'error': 'peer_id/task 필요'})
            return True
        exec_id = uuid.uuid4().hex
        res = _proxy(dd, 'POST', 'exec-send',
                     {'peer_id': peer_id, 'exec_id': exec_id, 'task': task})
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
        _start_exec(dd, from_peer, exec_id, task, PROJECT_ID)
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
        # 실행 중 프로세스 강제 종료(대상측). 요청자 취소는 UI에서 폴링 중단.
        exec_id = (data or {}).get('exec_id', '')
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
