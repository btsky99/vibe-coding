"""
FILE: src/central_inject.py
DESCRIPTION: 중앙 대화(아픽스 버스) → 로컬 터미널 슬롯 PTY 주입. '@1-2'로 온 말이 화면에만
             뜨고 끝나던 것을, 그 슬롯의 CLI가 실제로 읽고 답하게 만드는 배선.
             수신 슬롯이 답하면 그 답은 다시 버스에 실려 양쪽 '서로 대화'에 남는다.

[🔴 원격 발신 주입은 '금지'가 아니라 '게이트'다 — 2026-08-11 변경]
  슬롯 CLI는 대개 bypass 권한으로 떠 있어, 주입된 텍스트는 사실상 그 PC에서의 명령 실행이다.
  그래서 초판은 원격 발신을 통째로 막았다(화면 표시까지가 끝). 그 판단의 근거인
  "중앙 DB 계정 하나가 모든 노드에 대한 RCE 권한이 된다"는 지금도 유효하다.
  바뀐 것은 범위다 — **내가 소유한 노드끼리**로 좁혀 허용한다(사용자 결정 2026-08-11).

  · 로컬 발신 → deliver_local. 그 PC 사용자가 스스로 친 말이라 게이트 없음
  · 원격 발신 → deliver_remote. 4중 게이트를 전부 통과해야만 꽂힌다
      ① 토글(기본 꺼짐) ② 허용 노드 목록에 발신자가 있음
      ③ 수신 슬롯이 명시됨(브로드캐스트는 주입 안 함) ④ 창당 상한
  두 경로를 합치지 말 것 — 발신 시점 주입에는 게이트가 없고, 있어서도 안 된다.
  대화는 되돌릴 수 있어도 실행은 되돌릴 수 없다는 원칙은 그대로다.

[🔴 왜 poll 경로가 아니라 발신 시점에 거는가]
  pg_central.fetch_new는 `from_node <> self`로 자기 노드 발신을 걸러낸다(브로드캐스트를
  자기가 되받아 무한 루프가 되는 것을 막는 불변식). 그래서 같은 노드의 1-1 → 1-2는
  poll로 절대 돌아오지 않는다. 발신 시점에 거는 것이 유일하게 동작하는 지점이다.

[불변식] 주입 상한은 '슬롯당 창 안에서 N회'다. 두 에이전트가 서로 답하면 사람이 끼지 않는
  무한 왕복이 되므로, 상한이 루프의 유일한 제동 장치다. 상한에 걸리면 조용히 버리지 않고
  로그를 남긴다 — '왜 답이 안 오지'가 관측 불가능해지는 것이 더 나쁘다.

REVISION HISTORY:
- 2026-08-09 Claude: 신규. 중앙 버스 슬롯 멘션의 양방향화(1-1 ↔ 1-2).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from urllib.parse import quote

# 주입 상한 — 슬롯당 _WINDOW_SEC 안에서 _MAX_PER_WINDOW회.
# [WHY 이 값인가] 사람이 끼어 있는 대화는 분당 몇 마디를 넘지 않는다. 반대로 에이전트끼리
#   자동 왕복이 붙으면 초당으로 튄다 — 두 경우를 가르는 선으로 잡았다. 상한에 걸린 뒤에는
#   창이 지날 때까지 주입이 멈추므로, 폭주는 최대 _MAX_PER_WINDOW개에서 끝난다.
_WINDOW_SEC = 300.0
_MAX_PER_WINDOW = 8

# 원격(다른 노드) 발신 주입의 별도 상한. 로컬보다 보수적으로 잡는다.
# [WHY 별도인가] 로컬 왕복은 내 PC 안의 두 슬롯이라 최악이어도 내 자원만 태운다.
#   원격은 남의 PC에서 명령이 실행되는 것이라 폭주 비용의 성격이 다르다.
_MAX_REMOTE_PER_WINDOW = 4

_lock = threading.RLock()
_recent: dict[str, list[float]] = {}     # slot_id → 주입 시각들


def _slot_no(agent_id: str) -> int:
    """'claude:T2' → 2. 슬롯을 못 읽으면 0.

    [제약] 외부 커넥터(디스코드 등)가 보낸 from/to에는 슬롯이 없다 — 0을 돌려 호출부가
      주입을 건너뛰게 한다. 여기서 1로 폴백하면 남의 슬롯에 남의 말을 꽂게 된다.
    """
    m = re.search(r'[:@]?T(\d+)\b', str(agent_id or ''), re.I)
    return int(m.group(1)) if m else 0


def _rate_ok(slot_id: str, limit: int = _MAX_PER_WINDOW) -> bool:
    """상한 검사 + 소비 기록. [제약] 호출과 동시에 카운트한다 — 검사와 기록을 나누면
      두 스레드가 같은 창에서 동시에 통과한다.
    [제약] limit 를 인자로 받는 이유는 원격 주입이 더 낮은 상한을 쓰기 때문이다.
      호출부는 slot_id 도 다른 키('remote:...')를 넘겨 창을 분리한다 — 키를 공유하면
      원격 폭주가 로컬 대화 몫까지 먹는다."""
    now = time.time()
    with _lock:
        hits = [t for t in _recent.get(slot_id, []) if now - t < _WINDOW_SEC]
        if len(hits) >= limit:
            _recent[slot_id] = hits
            return False
        hits.append(now)
        _recent[slot_id] = hits
        return True


def _find_slot_session(pty_url: str, slot: int) -> str | None:
    """살아 있는 T{slot} 세션의 project_id를 돌려준다. 없으면 None.

    [🔴 sessions의 키와 write 경로의 id는 다른 규약이다] 목록 키는 'T2@D--vibe-coding'
      (표시용 라벨)인데, write는 `/api/pty/write/T2?project_id=D--vibe-coding`이다.
      라벨을 그대로 경로에 넣으면 pty-server가 _resolveSessionKey에서 못 찾아 404를
      돌려준다 — 실제로 처음 그렇게 만들어 404를 받았다. 그래서 슬롯과 프로젝트를
      분리해 돌려준다.
    [제약] 응답에는 project 접미사가 없는 'T2'(running=false) 껍데기가 같이 들어 있다 —
      running 필터를 빼면 죽은 세션에 write 해놓고 성공으로 착각한다.
    """
    try:
        with urllib.request.urlopen(f'{pty_url}/api/pty/sessions', timeout=2) as r:
            sessions = json.loads(r.read().decode('utf-8'))
    except Exception:
        return None
    if not isinstance(sessions, dict):
        return None
    prefix = f'T{slot}'
    for key, info in sessions.items():
        if not isinstance(info, dict) or not info.get('running'):
            continue
        if str(key).split('@')[0] == prefix:
            return str(info.get('project_id') or '_default')
    return None


def _format(from_addr: str, to_addr: str, content: str) -> str:
    """주입될 한 줄. 발신자 주소와 답장 방법을 같이 실어야 왕복이 성립한다.

    [WHY 답장 방법을 매번 붙이는가] 수신 슬롯의 CLI는 이 버스의 존재를 모른다. 답하는 법을
      본문에 넣지 않으면 사람에게 답해버리고 대화가 버스에 안 남는다 — 양방향이 깨진다.
    """
    return (f'[아픽스 {from_addr} → {to_addr}] {content}\n'
            f'(이건 아픽스 중앙 대화로 온 말이야. 답장: '
            f'python scripts/central_say.py {from_addr} "답할 내용")')


def remote_gate(config_file=None) -> tuple[bool, set[int]]:
    """원격 주입 게이트 상태 — (켜졌는가, 허용 node_seq 집합).

    [🔴 기본은 꺼짐이고, 켜도 '허용 목록에 적힌 노드만' 통과한다]
      파일 헤더의 판단(원격 주입 = 그 PC에서의 명령 실행 = 사실상 RCE)은 여전히 유효하다.
      이 게이트는 그 판단을 뒤집는 것이 아니라, **내가 소유한 노드끼리로 범위를 좁혀**
      허용하는 장치다. 중앙 DB 계정이 새더라도 허용 목록에 없는 노드에는 닿지 못한다.
    [WHY seq 로 적는가] uuid 는 사람이 설정 파일에 옮겨 적다 틀리기 쉽고, 틀리면 조용히
      '아무도 허용 안 됨'이 된다. 화면에 보이는 번호(아픽스 3-1의 3)를 그대로 쓴다.
    [불변식] allow_nodes 가 비면 꺼진 것과 같다 — 명시적 허용만 인정한다.
      "enabled 만 켰는데 왜 안 되지"보다 "허용 목록을 안 적었다"가 훨씬 안전한 실패다.

    설정 예:
      "central_remote_inject": {"enabled": true, "allow_nodes": [3]}
    """
    try:
        from src.node_identity import CONFIG_FILE, _read_config
        raw = _read_config(config_file or CONFIG_FILE).get('central_remote_inject')
    except Exception:
        return False, set()
    if not isinstance(raw, dict) or not raw.get('enabled'):
        return False, set()

    allowed = set()
    for v in (raw.get('allow_nodes') or []):
        try:
            allowed.add(int(v))
        except (TypeError, ValueError):
            continue          # 오타 한 줄이 목록 전체를 무효로 만들지 않게 한다
    return bool(allowed), allowed


def _seq_of(node_id: str, config_file=None) -> int:
    """발신 노드의 uuid → 명부 번호. 못 찾으면 0(=허용 안 됨).

    [제약] 명부 조회가 실패하면 0을 돌려 **주입을 막는 쪽**으로 넘어진다.
      조회 실패를 '일단 허용'으로 처리하면 게이트가 네트워크 상태에 따라 열린다.
    """
    try:
        from src.pg_central import list_node_refs
        for ref in list_node_refs(config_file):
            if str(ref.get('node_id')) == str(node_id):
                return int(ref.get('node_seq') or 0)
    except Exception:
        return 0
    return 0


def deliver_remote(msg: dict, pty_url: str, config_file=None) -> tuple[bool, str]:
    """다른 노드에서 온 메시지를 이 PC의 슬롯 CLI에 꽂는다. (성공여부, 사유).

    [🔴 게이트 4중 — 하나라도 막히면 화면 표시까지가 끝이다]
      ① 토글이 켜져 있고 허용 목록이 비어 있지 않은가
      ② 발신 노드가 그 허용 목록에 있는가
      ③ 수신 슬롯이 **명시**돼 있는가 — 브로드캐스트는 주입하지 않는다.
         받는 사람을 안 정한 말을 모든 슬롯에 꽂으면 노드 하나가 전 슬롯을 조종한다.
      ④ 상한(창당 _MAX_REMOTE_PER_WINDOW)을 넘지 않았는가
    [불변식] 실패해도 예외를 던지지 않는다 — 주입 실패가 수신 자체를 깨면 안 된다.
      화면 표시는 이 함수와 무관하게 이미 이뤄진다.
    """
    enabled, allowed = remote_gate(config_file)
    if not enabled:
        return False, 'remote_disabled'

    to_agent = str(msg.get('to_agent') or '')
    if not to_agent:
        return False, 'broadcast_not_injected'

    slot = _slot_no(to_agent)
    if not slot:
        return False, 'no_slot'
    if not pty_url:
        return False, 'no_pty_url'

    seq = _seq_of(msg.get('from_node') or '', config_file)
    if seq not in allowed:
        return False, f'node_not_allowed(seq={seq})'

    project_id = _find_slot_session(pty_url, slot)
    if not project_id:
        return False, 'slot_not_running'

    # [WHY 로컬과 다른 키를 쓰는가] 상한을 공유하면 원격 폭주가 로컬 대화까지 굶긴다.
    target = f'T{slot}@{project_id}'
    if not _rate_ok(f'remote:{target}', limit=_MAX_REMOTE_PER_WINDOW):
        return False, 'rate_limited'

    from_addr = f"{seq}-{_slot_no(msg.get('from_agent') or '') or '?'}"
    text = _format(from_addr, f'T{slot}', str(msg.get('content') or ''))
    url = f'{pty_url}/api/pty/write/T{slot}?project_id={quote(project_id)}'
    try:
        req = urllib.request.Request(
            url, data=json.dumps({'text': text}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=3)
        return True, target
    except Exception as e:
        return False, f'write_failed: {e}'


def deliver_local(to_agent: str, from_agent: str, content: str,
                  pty_url: str, from_addr: str = '', to_addr: str = '') -> tuple[bool, str]:
    """같은 노드의 슬롯 PTY에 메시지를 꽂는다. (성공여부, 사유) 반환.

    [불변식] 실패해도 예외를 던지지 않는다 — 발신은 이미 DB에 커밋됐고, 주입 실패로 발신
      응답을 500으로 만들면 '보내지긴 했는데 에러'라는 최악의 화면이 된다.
    """
    slot = _slot_no(to_agent)
    if not slot:
        return False, 'no_slot'
    if _slot_no(from_agent) == slot:
        return False, 'self'          # 자기 슬롯에 자기 말을 꽂으면 즉시 자가 루프
    if not pty_url:
        return False, 'no_pty_url'

    project_id = _find_slot_session(pty_url, slot)
    if not project_id:
        return False, 'slot_not_running'
    target = f'T{slot}@{project_id}'
    if not _rate_ok(target):
        return False, 'rate_limited'

    text = _format(from_addr or from_agent, to_addr or f'T{slot}', content)
    url = f'{pty_url}/api/pty/write/T{slot}?project_id={quote(project_id)}'
    try:
        req = urllib.request.Request(
            url, data=json.dumps({'text': text}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=3)
        return True, target
    except Exception as e:
        return False, f'write_failed: {e}'
