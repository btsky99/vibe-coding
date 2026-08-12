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
      ③ 꽂을 슬롯이 정해짐(미지정이면 대표 슬롯 1개 — broadcast_slot) ④ 창당 상한
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

# [🔴 배달 전용 커서] 화면 폴링의 커서(agent_id='')와 **분리**한다.
#   message_cursors 기본키가 (node_id, agent_id)라 원래부터 가능했는데, 옛 코드가
#   커서 선택과 수신자 필터를 agent_id 하나로 겸했던 탓에 "커서는 하나뿐"이라는
#   잘못된 전제가 굳어 있었다. 그 전제 때문에 주입을 화면 폴링에 얹었고, 결과적으로
#   **화면이 안 돌면 배달도 멈추는** 구조가 됐다(2026-08-12 na2js: 앱·터널·게이트가
#   전부 정상인데 UI 가 poll 을 안 불러 23시간 무배달, 미수신 1건 대기).
#   이름을 사람이 쓸 수 없는 형태로 둔다 — 슬롯 주소와 절대 충돌하면 안 된다.
_INJECT_CURSOR = '__inject__'

# 최근 배달 결과(화면 배너용). [WHY 큐인가] 배달은 이제 서버가 하므로 화면은 결과를
#   '나중에' 읽는다. 화면이 오래 안 열려도 메모리가 새지 않게 상한을 둔다 —
#   배너는 최신 몇 건만 보여주면 되고, 정확한 이력은 어차피 대화 목록에 남는다.
_results: list[dict] = []
_RESULTS_MAX = 20


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


def _reply_script() -> str:
    """이 PC 에서 central_say.py 의 **절대 경로**. 못 찾으면 빈 문자열.

    [🔴 왜 절대 경로여야 하는가 — 상대 CLI 의 작업 폴더를 가정하면 안 된다]
      주입문은 원래 `python scripts/central_say.py ...` 라는 **상대 경로**를 안내했다.
      그건 받는 CLI 가 바이브코딩 저장소 안에서 돌고 있을 때만 맞는 말이다.
      실측(2026-08-12): na2js 의 3-1 은 `D:\\CipherTrader` 에서 돌고 있었다. 메시지는
      정상 도착해 클로드가 읽었는데, 그 경로에 파일이 없어 **"답장 불가"** 로 끝났다.
      배달·게이트·엔터를 다 고쳐 놓고 마지막 한 줄에서 왕복이 끊긴 것이다.
      슬롯 CLI 는 어느 프로젝트에서든 열릴 수 있다 — cwd 를 가정하지 말 것.

    [제약] 설치본은 소스가 `_appseed` 아래에 있고, 개발본은 리포 루트에 있다. 둘 다
      확인하고 **실제로 존재하는** 것만 돌려준다 — 없는 경로를 안내하면 상대는
      "파일이 없다"는 오류만 보고 원인을 모른다.
    """
    import sys
    from pathlib import Path

    cands = []
    mei = getattr(sys, '_MEIPASS', '')
    if mei:
        cands.append(Path(mei) / '_appseed' / 'scripts' / 'central_say.py')
    if getattr(sys, 'frozen', False):
        # onedir 설치본: <설치폴더>\_internal\_appseed\scripts\
        cands.append(Path(sys.executable).parent / '_internal' / '_appseed'
                     / 'scripts' / 'central_say.py')
    # 개발/관리 체크아웃: src/central_inject.py → .ai_monitor → 리포 루트
    cands.append(Path(__file__).resolve().parents[2] / 'scripts' / 'central_say.py')

    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return ''


def _format(from_addr: str, to_addr: str, content: str) -> str:
    """주입될 한 줄. 발신자 주소와 답장 방법을 같이 실어야 왕복이 성립한다.

    [WHY 답장 방법을 매번 붙이는가] 수신 슬롯의 CLI는 이 버스의 존재를 모른다. 답하는 법을
      본문에 넣지 않으면 사람에게 답해버리고 대화가 버스에 안 남는다 — 양방향이 깨진다.

    [🔴 반드시 한 줄이어야 한다 — 개행 하나가 말을 두 동강 낸다]
      TUI 입력칸에 개행이 들어가면 거기서 먼저 제출돼, 뒷부분(답장 방법)이 다음
      프롬프트에 남는다. 수신 CLI 는 '답하는 법'을 못 본 채 반쪽짜리 말만 받는다.
      본문에 든 개행도 공백으로 접는다 — 사람이 여러 줄로 쓴 채팅도 한 마디로 다룬다.
      (pty-server 도 같은 정규화를 한다. 양쪽에 둔 이유: 이 함수를 안 거치는 주입
       경로가 생겨도 마지막 방어선이 남아야 한다.)
    """
    flat = ' '.join(str(content).split())
    script = _reply_script()
    how = (f'python "{script}" {from_addr} "답할 내용"' if script
           else '이 PC 바이브코딩 앱의 "서로 대화" 창에 직접 입력')
    return (f'[아픽스 {from_addr} → {to_addr}] {flat} '
            f'(이건 아픽스 중앙 대화로 온 말이야. 답장: {how})')


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


def broadcast_slot(config_file=None) -> int:
    """받는 슬롯을 안 정한 말을 꽂을 **대표 슬롯 하나**. 0이면 주입 안 함(옛 동작).

    [🔴 왜 생겼나 — '전달은 되는데 클로드가 인식을 못 한다'의 절반이 여기였다]
      초판은 브로드캐스트를 통째로 주입 대상에서 뺐다. 근거는 타당했다 —
      받는 사람을 안 정한 말을 **모든 슬롯**에 꽂으면 노드 하나가 전 슬롯을 조종한다.
      그런데 결과는 사람이 창에 그냥 한 줄 쓰면 **어느 CLI도 그 말을 못 보는** 것이었다.
      화면엔 뜨는데 상대 클로드는 침묵하니, 사용자에게는 '읽고 무시한다'로 보인다.

      금지의 진짜 대상은 '슬롯을 안 정했다'가 아니라 '전 슬롯 동시 도달'이었다.
      그래서 범위만 좁힌다 — **노드당 딱 한 슬롯**. 원래 불변식은 그대로 지켜지고,
      '@를 안 붙이면 아무도 못 듣는' 함정만 사라진다.
    [제약] 여전히 remote_gate(토글+허용 목록)를 먼저 통과해야 한다. 이 값은 '어디에
      꽂을지'만 정하지 '꽂아도 되는지'를 정하지 않는다.
    [제약] 0으로 두면 옛 동작(브로드캐스트 미주입)으로 되돌아간다 — 이 판단을 바꾸고
      싶은 사용자를 위해 설정으로 남긴다.
    """
    try:
        from src.node_identity import CONFIG_FILE, _read_config
        raw = _read_config(config_file or CONFIG_FILE).get('central_remote_inject')
    except Exception:
        return 1
    if not isinstance(raw, dict) or 'broadcast_slot' not in raw:
        return 1                      # 미설정 기본값 — 대표 슬롯 T1
    try:
        v = int(raw.get('broadcast_slot'))
    except (TypeError, ValueError):
        return 1                      # 오타 하나로 조용히 '아무도 못 들음'이 되지 않게
    return v if v >= 0 else 1


def _norm_dir(path: str) -> str:
    """비교용 정규화 경로. 실패하면 빈 문자열(= 어떤 화이트리스트와도 안 맞음).

    [🔴 왜 문자열 비교로 끝내면 안 되는가] `D:\\proj\\..\\other` 같은 경로가 문자열로는
      화이트리스트와 달라 보이지만 실제로는 다른 폴더를 가리킨다. 정규화 없이 비교하면
      게이트가 **막았다고 믿으면서 뚫린다** — 가장 나쁜 실패 모드다.
    [제약] 윈도우는 대소문자를 구분하지 않으므로 casefold 한다. 리눅스에서는 서로 다른
      두 경로가 같게 보일 수 있으나, 노드는 전부 윈도우라 실무상 문제가 없다.

    [🔴 빈 문자열을 먼저 걸러낸다] `Path('').resolve()` 는 예외가 아니라 **현재 작업
      폴더**를 돌려준다. 그대로 두면 work_dir 이 비었을 때 조용히 cwd 로 바뀌고,
      cwd 가 허용 폴더 안이면 게이트를 통과한다 — 막았다고 믿으면서 뚫리는 경우다.
      (Task 50 테스트가 실제로 이 구멍을 잡아냈다.)
    """
    from pathlib import Path
    raw = str(path or '').strip()
    if not raw:
        return ''
    try:
        return str(Path(raw).resolve()).casefold()
    except OSError:
        return ''


def launch_gate(config_file=None) -> tuple[bool, list[str]]:
    """기동 게이트 상태 — (켜졌는가, 허용 폴더 목록).

    [🔴 왜 remote_gate 와 별도인가 — 대화 허용이 실행 허용을 뜻하면 안 된다]
      원격 주입(remote_gate)은 '떠 있는 CLI 에 말 걸기'다. 기동은 **없던 프로세스를
      만들고 작업 폴더를 지정**하는 것이라 한 단계 더 세다. 두 개를 한 토글로 묶으면
      대화를 열어준 순간 임의 폴더에서의 실행까지 열린다 — 사용자가 동의한 적 없는 권한이다.
      `central_api.py` 헤더가 경고한 "중앙 DB 계정 하나가 모든 노드에 대한 RCE" 가
      정확히 그 상태다.
    [불변식] 기본은 꺼짐. allow_dirs 가 비면 꺼진 것과 같다 — 명시적 허용만 인정한다.
    """
    try:
        from src.node_identity import CONFIG_FILE, _read_config
        raw = _read_config(config_file or CONFIG_FILE).get('central_remote_launch')
    except Exception:
        return False, []
    if not isinstance(raw, dict) or not raw.get('enabled'):
        return False, []
    dirs = [str(d) for d in (raw.get('allow_dirs') or []) if str(d).strip()]
    return bool(dirs), dirs


def launch_allowed(work_dir: str, config_file=None) -> tuple[bool, str]:
    """이 폴더에서 CLI 를 띄워도 되는가. (허용여부, 사유).

    [제약] 하위 폴더는 허용한다 — 저장소 루트를 허용했는데 하위 패키지에서 못 돌면
      쓸모가 없다. 상위로 거슬러 올라가는 것은 당연히 막힌다.
    [WHY 사유를 문자열로 돌려주나] 'needs_approval' 은 사용자가 버튼 하나로 풀 수 있는
      상태이고 'launch_disabled' 는 아니다. 둘을 같은 실패로 뭉개면 화면이 무엇을
      제안해야 할지 모른다 — 오늘 주입 게이트에서 겪은 문제와 같다.
    """
    enabled, dirs = launch_gate(config_file)
    if not enabled:
        return False, 'launch_disabled'

    target = _norm_dir(work_dir)
    if not target:
        return False, 'bad_work_dir'

    from pathlib import Path
    for d in dirs:
        base = _norm_dir(d)
        if not base:
            continue
        if target == base:
            return True, ''
        try:
            if Path(target).is_relative_to(Path(base)):
                return True, ''
        except (ValueError, OSError):
            continue
    return False, 'needs_approval'


def allow_launch_dir(work_dir: str, config_file=None) -> tuple[bool, str]:
    """그 폴더에서의 기동을 허용 목록에 넣고 게이트를 켠다. (성공여부, 사유).

    [불변식] **더하기만** 한다(allow_node 와 같은 이유). 목록을 교체하면 다른 프로젝트의
      허용이 조용히 취소돼, 왜 갑자기 안 되는지 알 수 없게 된다.
    [제약] 존재하지 않는 폴더는 거절한다 — 오타로 적은 경로를 허용해두면 나중에 그 이름의
      폴더가 생기는 순간 의도치 않게 열린다.
    """
    from pathlib import Path

    from src.node_identity import CONFIG_FILE, _load_config, _write_config

    raw_path = str(work_dir or '').strip()
    if not raw_path:
        return False, 'empty_path'
    try:
        resolved = Path(raw_path).resolve()
        if not resolved.is_dir():
            return False, 'not_a_directory'
    except OSError:
        return False, 'bad_work_dir'

    path = config_file or CONFIG_FILE
    cfg, status = _load_config(path)
    if status == 'corrupt':
        return False, 'config_unreadable'    # 읽지 못한 설정에 쓰면 나머지 키가 사라진다

    raw = cfg.get('central_remote_launch')
    raw = raw if isinstance(raw, dict) else {}
    dirs = [str(d) for d in (raw.get('allow_dirs') or []) if str(d).strip()]
    if not any(_norm_dir(d) == _norm_dir(str(resolved)) for d in dirs):
        dirs.append(str(resolved))

    cfg['central_remote_launch'] = {'enabled': True, 'allow_dirs': dirs}
    if not _write_config(path, cfg):
        return False, 'write_failed'
    return True, ''


def allow_node(seq: int, config_file=None) -> tuple[bool, str]:
    """발신 노드 번호를 허용 목록에 넣고 게이트를 켠다. (성공여부, 사유).

    [🔴 왜 API로 여는가 — 사용자가 설정 파일을 손대게 하면 안 된다]
      이 값을 넣으려고 사람에게 PowerShell 한 줄을 시켰다가 노드 하나가 통째로 죽었다
      (BOM 한 개로 config.json 파싱 실패 → 설정 전체 소멸, 2026-08-11). 비개발자가
      쓰는 제품에서 '설정 파일을 열어 JSON을 고치세요'는 해법이 아니라 사고 유발기다.
      여는 판단은 여전히 사람이 하되, **쓰는 일은 앱이** 한다.
    [불변식] 이 함수는 allow_nodes에 **더하기만** 한다. 목록을 통째로 교체하면 다른
      노드의 허용이 조용히 취소돼, 왜 갑자기 안 되는지 알 수 없게 된다.
    [제약] 0은 거절한다 — 명부에 없는 노드(seq=0)를 허용하면 '알 수 없는 발신자 전부'를
      허용하는 것과 같다. 게이트의 목적이 정확히 그것을 막는 것이다.
    """
    try:
        value = int(seq)
    except (TypeError, ValueError):
        return False, 'invalid_seq'
    if value <= 0:
        return False, 'unknown_node'

    from src.node_identity import CONFIG_FILE, _load_config, _write_config
    path = config_file or CONFIG_FILE
    cfg, status = _load_config(path)
    if status == 'corrupt':
        # 읽지 못한 설정에 쓰면 나머지 키가 사라진다. 쓰기를 거절하는 편이 낫다.
        return False, 'config_unreadable'

    raw = cfg.get('central_remote_inject')
    raw = raw if isinstance(raw, dict) else {}
    nodes = []
    for v in (raw.get('allow_nodes') or []):
        try:
            nodes.append(int(v))
        except (TypeError, ValueError):
            continue
    if value not in nodes:
        nodes.append(value)

    cfg['central_remote_inject'] = {'enabled': True, 'allow_nodes': sorted(nodes)}
    if not _write_config(path, cfg):
        return False, 'write_failed'
    return True, ''


def seq_of(node_id: str, config_file=None) -> int:
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
      ③ 꽂을 슬롯이 정해지는가 — 명시됐으면 그 슬롯, 없으면 **대표 슬롯 하나**
         (broadcast_slot). 금지 대상은 '슬롯 미지정'이 아니라 '전 슬롯 동시 도달'이다.
      ④ 상한(창당 _MAX_REMOTE_PER_WINDOW)을 넘지 않았는가
    [불변식] 실패해도 예외를 던지지 않는다 — 주입 실패가 수신 자체를 깨면 안 된다.
      화면 표시는 이 함수와 무관하게 이미 이뤄진다.
    """
    enabled, allowed = remote_gate(config_file)
    if not enabled:
        return False, 'remote_disabled'

    to_agent = str(msg.get('to_agent') or '')
    if to_agent:
        slot = _slot_no(to_agent)
        if not slot:
            return False, 'no_slot'       # 슬롯을 적었는데 못 읽는다 — 추측하지 않는다
    else:
        # 받는 슬롯 미지정 → 대표 슬롯 하나로. 상세는 broadcast_slot() 참조.
        slot = broadcast_slot(config_file)
        if not slot:
            return False, 'broadcast_not_injected'
    if not pty_url:
        return False, 'no_pty_url'

    seq = seq_of(msg.get('from_node') or '', config_file)
    if seq not in allowed:
        return False, f'node_not_allowed(seq={seq})'

    # [🔴 발신 슬롯을 몰라도 주입한다 — 옛 하드 거부는 오판이었다]
    #   주입문은 "답장: central_say.py {발신자주소}"를 싣는다. 옛 구현은 발신 슬롯을
    #   모르면 주소가 '1-?'가 되어 답장이 실패한다고 보고 주입 자체를 거부했다.
    #   그런데 central_say.py `_resolve` 는 **슬롯 없는 노드 주소('1')를 이미 받는다** —
    #   답장은 처음부터 가능했고, 거부할 이유가 없었다.
    #   이 오판의 대가가 컸다: `from_agent` 를 안 실은 발신(스크립트·외부 커넥터·서버
    #   기본값 'claude')은 **전부 조용히 버려졌다.** 화면에는 멀쩡히 뜨므로 사용자에게는
    #   '상대 클로드가 읽고 무시한다'로 보인다(2026-08-11 na2js 왕복 실패의 절반).
    from_slot = _slot_no(msg.get('from_agent') or '')
    reply_addr = f'{seq}-{from_slot}' if from_slot else f'{seq}'

    project_id = _find_slot_session(pty_url, slot)
    if not project_id:
        return False, 'slot_not_running'

    # [WHY 로컬과 다른 키를 쓰는가] 상한을 공유하면 원격 폭주가 로컬 대화까지 굶긴다.
    target = f'T{slot}@{project_id}'
    if not _rate_ok(f'remote:{target}', limit=_MAX_REMOTE_PER_WINDOW):
        return False, 'rate_limited'

    text = _format(reply_addr, f'T{slot}', str(msg.get('content') or ''))
    url = f'{pty_url}/api/pty/write/T{slot}?project_id={quote(project_id)}'
    try:
        req = urllib.request.Request(
            url, data=json.dumps({'text': text}, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=3)
        return True, target
    except Exception as e:
        return False, f'write_failed: {e}'


def deliver_pending(config_file=None) -> int:
    """중앙에서 이 노드 앞으로 온 새 메시지를 **서버가 직접** 슬롯 CLI에 배달한다.
    배달한(또는 막힌) 건수를 돌려준다. 리스너가 NOTIFY를 받을 때마다 부른다.

    [🔴 왜 화면(poll)이 아니라 서버가 배달하는가 — 2026-08-12 구조 변경]
      옛 구조는 '조회하는 곳이 곧 소비자'라는 불변식 때문에 주입을 화면 폴링에 얹었다.
      그래서 **React 훅이 안 돌면 그 PC 는 아무 말도 못 받는다.** 실측: na2js 는 앱·터널·
      리스너·게이트가 전부 정상인데 UI 가 poll 을 부르지 않아 23시간 동안 한 건도 배달되지
      않았고, 미수신 1건이 그대로 대기 중이었다. 사람에게는 '상대 클로드가 무시한다'로만
      보인다 — 에이전트 간 배달이 화면 렌더링에 인질로 잡혀 있으면 안 된다.
      이제 커서를 분리(_INJECT_CURSOR)해 배달과 표시가 서로를 기다리지 않는다.

    [🔴 실패해도 커서를 되돌리지 않는다 — 재시도가 더 나쁘다]
      슬롯이 안 떠 있어 못 꽂은 메시지를 몇 시간 뒤 터미널을 열자마자 쏟아 넣으면,
      그 CLI 는 이미 지나간 맥락으로 움직인다. 대화는 화면에 그대로 남아 있으므로
      '한 번만 시도'가 안전하다. 실패 사유는 _results 에 남아 화면이 이유를 말해준다.
    [불변식] 예외를 밖으로 내지 않는다 — 배달 실패가 리스너 루프를 죽이면 그 PC 는
      알림 자체를 잃는다. 배달은 부가 기능이고 수신 신호는 기반이다.
    """
    try:
        from src import pg_central
        from api import pty_api
    except Exception:
        return 0

    try:
        rows = pg_central.fetch_new(agent_id='', limit=20, advance=True,
                                    config_file=config_file,
                                    cursor_key=_INJECT_CURSOR)
    except Exception as exc:
        print(f'[central] 배달 조회 실패: {exc}')
        return 0
    if not rows:
        return 0

    out = process_rows(rows, pty_api.get_pty_rest_url(), config_file)
    if out:
        with _lock:
            _results.extend(out)
            del _results[:-_RESULTS_MAX]
    return len(out)


def process_rows(rows: list, pty_url: str, config_file=None) -> list[dict]:
    """메시지 목록을 슬롯 CLI에 꽂고 건별 결과를 돌려준다.

    [제약] 반환값은 관측용이다. 실패 사유를 남겨야 '왜 답이 안 오지'를 화면에서 가릴 수
      있다 — 조용히 버리면 게이트가 막은 것인지 슬롯이 죽은 것인지 구분 불가다.
    [WHY 게이트가 꺼져 있어도 목록을 만드나] 가장 흔한 실패(꺼짐)가 화면에 아무 흔적도
      남기지 않으면, 원인을 알려면 그 PC 에서 설정 파일을 열어야 한다. 막혔다는 사실과
      발신 번호를 실어 보내면 UI 가 [허용] 버튼 하나로 끝낼 수 있다.
    """
    if not rows:
        return []
    enabled = remote_gate(config_file)[0]
    out = []
    for msg in rows:
        if not enabled:
            # PTY 조회는 하지 않는다 — 막힌 게 확정이라 물어볼 이유가 없다.
            ok, why = False, 'remote_disabled'
        else:
            ok, why = deliver_remote(msg, pty_url, config_file)
        if not ok and why in ('broadcast_not_injected', 'no_slot'):
            continue          # 설정상 '주입 대상 아님' — 사유로 알릴 것이 없다
        out.append({'id': msg.get('id'), 'ok': ok, 'why': why,
                    'from_seq': seq_of(msg.get('from_node') or '', config_file)})
    return out


def take_results() -> list[dict]:
    """쌓인 배달 결과를 꺼내 비운다(화면이 배너를 그리는 재료).

    [WHY 꺼내면 비우나] 같은 막힘을 매 폴링마다 다시 올리면 [나중에]로 닫은 배너가
      3초 뒤 되살아난다 — 사용자가 끌 수 없는 알림은 알림이 아니라 소음이다.
    """
    with _lock:
        out = list(_results)
        _results.clear()
    return out


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
