"""
FILE: src/node_identity.py
DESCRIPTION: 이 PC(노드)의 영구 정체성. config.json에 node_id(uuid4, 최초 1회) + node_label을
             보관하고, 로컬 agent_id를 중앙 DB용 참조로 감싸는 node_ref()를 제공한다.
             아픽스 서버(중앙 대화 PG) 1차 — Task 3.

REVISION HISTORY:
- 2026-08-09 Claude: node_seq 추가 — uuid는 사람이 못 읽어 대화 화면의 발신자를 식별할 수
                     없었다. 호스트명 매핑으로 자동 배정(Phase 11 Task 32).
- 2026-08-08 Claude: 신규. 여러 PC의 claude:T1이 중앙에서 서로 구분되지 않던 선행 결함 해소.
"""
import json
import os
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path

# [WHY pg_base에서 DATA_DIR을 빌려오는가] frozen(EXE)에서는 %APPDATA%\VibeCoding,
#   개발 모드에서는 .ai_monitor/data 로 갈라진다. 이 분기를 여기서 다시 구현하면
#   설치본과 개발본이 서로 다른 config.json을 봐 node_id가 두 개 생긴다
#   (전례: project_installed_empty_panels — dev/설치 config 분리로 슬러그가 어긋난 사고).
from src.pg_base import DATA_DIR

CONFIG_FILE = DATA_DIR / 'config.json'

# [불변식] node_id는 uuid4().hex — 32자 소문자 16진수. 이 형식을 벗어난 값은
#   손상으로 보고 재발급한다. node_ref 파싱이 '/' 앞부분을 이 정규식으로 검증하기 때문에
#   형식을 바꾸면 이미 중앙 DB에 쌓인 참조가 전부 파싱 불가가 된다.
_NODE_ID_RE = re.compile(r'^[0-9a-f]{32}$')

# [주의: 이름 충돌] api/discord_config_api.py에도 'node_id'가 있지만 그것은
#   DPAPI로 암호화된 별도 secret 파일의 사용자 지정 슬러그(디스코드 채널 구분용)다.
#   여기의 node_id는 data/config.json의 자동 생성 UUID로, 저장소도 수명도 다르다.
#   둘을 합치지 말 것 — 사용자가 디스코드 라벨을 바꾸면 중앙 대화 정체성이 갈아엎힌다.

_lock = threading.Lock()
_cached_id: str | None = None
_cached_path: Path | None = None


def _load_config(config_file) -> tuple[dict, str]:
    """(설정, 상태) — 상태는 'ok' | 'missing' | 'corrupt' | 'restored'.

    [🔴 왜 '없음'과 '깨짐'을 갈라야 하는가 — 이 둘을 뭉개서 노드 하나를 통째로 잃었다]
      옛 구현은 모든 실패를 {}로 삼켰다. 그러면 호출부(get_node_id)가 '설정이 아직
      없구나'로 읽고 새 uuid를 발급해 **파일을 통째로 덮어쓴다**. 실제로는 파일이
      멀쩡히 있었고 BOM 한 개 때문에 못 읽었을 뿐인데, 그 한 번의 덮어쓰기로
      central_db·node_seq·슬롯 이름이 전부 사라지고 노드 정체성까지 갈렸다
      (2026-08-11 na2js). 읽기 실패는 '빈 설정'이 아니다 — 쓰기를 막아야 하는 신호다.

    [🔴 BOM 관용] PowerShell 5.1의 `Set-Content -Encoding utf8`, 메모장, 다수 편집기가
      BOM을 붙인다. 사용자가 손으로 한 줄 고치면 그것만으로 앱이 설정을 잃는 구조였다.
      utf-8-sig는 BOM이 없어도 정상 동작하므로 관용 쪽이 순손실 없이 안전하다.

    [자가복구] 깨졌으면 마지막 정상본(.bak)으로 되살린다. 사람이 스크립트를 돌려야만
      복구되는 구조는 제품이 아니다 — 앱이 스스로 이전 상태로 돌아와야 한다.
    """
    path = Path(config_file)          # [제약] str이 들어와도 죽지 않게 정규화(과거 함정)
    try:
        raw = path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        return {}, 'missing'
    except Exception:
        return {}, 'corrupt'

    if not raw.strip():
        # 빈 파일은 '없음'과 같다 — 덮어써도 잃을 것이 없다.
        return {}, 'missing'

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data, 'ok'
    except Exception:
        pass

    # 여기부터는 '파일은 있는데 못 읽는' 상태. 원본을 보존하고 백업에서 되살린다.
    _quarantine(path)
    backup, status = _load_backup(path)
    if status == 'ok':
        _write_config(path, backup, backup_after=False)   # 되살린 내용을 정본 자리에
        return backup, 'restored'
    return {}, 'corrupt'


def _quarantine(path: Path) -> None:
    """읽지 못한 원본을 남긴다. [WHY] 덮어쓰기 전에 바이트를 보존하지 않으면 사용자가
    손으로 적은 값(비밀번호·터널 포트)이 영구 소멸한다. 실패해도 무시한다 — 보존은
    복구의 보조 수단이지 전제조건이 아니다."""
    try:
        stamp = time.strftime('%Y%m%dT%H%M%S')
        path.replace(path.with_name(f'{path.name}.corrupt-{stamp}'))
    except Exception:
        pass


def _load_backup(path: Path) -> tuple[dict, str]:
    try:
        raw = path.with_name(path.name + '.bak').read_text(encoding='utf-8-sig')
        data = json.loads(raw)
        if isinstance(data, dict) and data:
            return data, 'ok'
    except Exception:
        pass
    return {}, 'missing'


def _read_config(config_file: Path) -> dict:
    """[호환] 상태가 필요 없는 호출부용 얇은 래퍼. 새 코드는 _load_config를 쓴다."""
    return _load_config(config_file)[0]


def _write_config(config_file: Path, cfg: dict, backup_after: bool = True) -> bool:
    """다른 키를 보존한 채 원자적으로 저장. 실패해도 예외를 던지지 않는다.

    [제약] config.json은 서버·훅·CLI가 각자 read-modify-write 한다. os.replace로
      '반쯤 쓰인 파일'은 막지만 프로세스 간 lost update까지는 막지 못한다.
      node_id는 최초 1회만 쓰이므로 실무상 충돌 창이 없다 — 고빈도 키를 여기에 얹지 말 것.

    [WHY 성공한 내용을 .bak으로 한 벌 더 두는가] 이것이 _load_config 자가복구의 유일한
      재료다. 백업이 없으면 파일이 깨진 순간 되돌릴 곳이 없어, 사람이 비밀번호를 다시
      받아 온보딩을 처음부터 돌리는 수밖에 없다.
    [제약] backup_after=False는 **복구가 스스로를 덮어쓰는 것을 막기 위해서다** — 복구
      직후 .bak을 다시 쓰면 방금 되살린 내용으로 백업이 갱신돼, 다음 사고 때 되돌릴
      '이전 정상본'이 사라진다.
    """
    config_file = Path(config_file)
    tmp = config_file.with_suffix('.json.tmp')
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, config_file)
        if backup_after:
            try:
                shutil.copyfile(config_file, config_file.with_name(config_file.name + '.bak'))
            except Exception:
                pass          # 백업 실패가 저장 실패로 번지면 안 된다
        return True
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        return False


def get_node_id(config_file: Path | None = None) -> str:
    """이 PC의 영구 노드 ID를 반환한다. 없으면 최초 1회 발급 후 저장한다.

    [불변식] 같은 config.json에 대해 재호출/재시작해도 값이 같다. node_label을 바꿔도
      바뀌지 않는다 — 라벨은 사람이 읽는 표시용이고 ID는 데이터의 외래키다.
    [폴백] 저장에 실패해도(권한/디스크) 발급한 값을 그대로 반환한다. 이 프로세스 안에서는
      일관되며, 다음 부팅에 새 ID를 받는다. 대화가 조금 갈라지는 편이 앱이 죽는 것보다 낫다.

    [🔴 읽지 못한 설정 위에 새 ID를 쓰지 않는다] 과거에는 읽기 실패를 '설정 없음'으로 보고
      새 uuid를 담아 파일을 덮어썼다. 그 한 번의 쓰기가 central_db·node_seq·슬롯 이름을
      전부 지우고 노드를 중앙에서 미아로 만들었다(2026-08-11 na2js). 복구 불가는 '못 읽음'이
      아니라 '덮어씀'에서 왔다. 이제 상태가 corrupt면 **메모리에만** 발급하고 파일은 둔다.
    """
    global _cached_id, _cached_path
    path = Path(config_file) if config_file else CONFIG_FILE
    with _lock:
        if _cached_id is not None and _cached_path == path:
            return _cached_id

        cfg, status = _load_config(path)
        current = str(cfg.get('node_id') or '').strip().lower()
        if _NODE_ID_RE.fullmatch(current):
            _cached_id, _cached_path = current, path
            return current

        new_id = uuid.uuid4().hex
        if status == 'corrupt':
            # 되살릴 백업조차 없는 상태. 쓰기를 포기하는 편이 낫다 — 사람이 원본
            # (.corrupt-* 로 보존됨)에서 값을 되찾을 여지를 남긴다.
            print('[node_identity] 설정을 읽지 못해 임시 ID로 기동한다 — 파일은 건드리지 '
                  f'않았다. 보존본: {path.name}.corrupt-*', flush=True)
            _cached_id, _cached_path = new_id, path
            return new_id

        cfg['node_id'] = new_id
        if 'node_label' not in cfg:
            cfg['node_label'] = _default_label()
        _write_config(path, cfg)
        _cached_id, _cached_path = new_id, path
        return new_id


def _default_label() -> str:
    try:
        return socket.gethostname() or 'unknown'
    except Exception:
        return 'unknown'


def get_node_label(config_file: Path | None = None) -> str:
    """사람이 읽는 노드 이름. 미설정이면 호스트명."""
    path = Path(config_file) if config_file else CONFIG_FILE
    label = str(_read_config(path).get('node_label') or '').strip()
    return label or _default_label()


def set_node_label(label: str, config_file: Path | None = None) -> bool:
    """라벨만 교체한다. node_id는 절대 건드리지 않는다(위 불변식)."""
    path = Path(config_file) if config_file else CONFIG_FILE
    with _lock:
        cfg = _read_config(path)
        cfg['node_label'] = str(label or '').strip() or _default_label()
        return _write_config(path, cfg)


# ── 노드 번호(node_seq) ──────────────────────────────────────────────────────
# [WHY uuid가 있는데 번호를 또 두나] node_id는 32자 16진수라 사람이 못 읽는다. 대화 화면에
#   발신자를 'a3f9…' 로 그리면 누가 말했는지 알 수 없다. 번호는 **표시 전용 별명**이고
#   데이터의 외래키는 끝까지 node_id다 — 번호를 외래키로 쓰면 번호를 바꾸는 순간 과거
#   기록이 미아가 된다.
# [WHY 사람에게 묻지 않고 호스트명으로 배정하나] 번호는 이미 확정된 값이다(사용자 지정:
#   1=메인 2=크립토개발 3=na2js). 매번 물으면 PC 3대에 같은 질문을 3번 하게 되고, 오답이
#   들어오면 두 PC가 같은 번호를 갖는다. 호스트명은 그 PC가 스스로 아는 유일한 고정값이다.
# [제약] 여기 없는 호스트명(네 번째 PC)은 0을 받는다 — 0은 '아직 모름'이고, 그때만 UI가
#   1회 묻는다. 임의로 1을 기본값으로 주면 새 PC가 전부 메인 PC를 사칭한다.
# 🔴 2번은 결번이다 — 찾지 말 것. 설계 당시 '1=메인 2=크립토 3=na2js'로 적었으나,
#   크립토(CipherTrader) 노드는 별도 PC가 아니라 **이 개발 PC(yjscom) 자신**이다
#   (사용자 확인 2026-08-10). 즉 실재하는 노드는 1과 3 둘뿐이고, 2를 채우려고
#   호스트명을 뒤지면 없는 PC를 찾게 된다. 네 번째 PC가 붙으면 4를 준다.
# [추가 규칙] 새 항목은 소문자로 적는다 — 조회가 .lower()로 정규화된다.
_DEFAULT_SEQ: dict[str, int] = {
    'yjscom': 1,
    'na2js': 3,
}

_SEQ_MIN, _SEQ_MAX = 1, 99


def get_node_seq(config_file: Path | None = None) -> int:
    """이 PC의 표시 번호. config → 호스트명 매핑 → 0(미지) 순으로 본다.

    [부수효과 의도됨] 매핑으로 처음 결정되면 config에 1회 기록한다. 호스트명은 사용자가
      언제든 바꿀 수 있는 값이라, 한 번 정해진 뒤에는 config가 정본이어야 번호가 안 흔들린다.
    """
    path = Path(config_file) if config_file else CONFIG_FILE
    cfg = _read_config(path)
    try:
        saved = int(cfg.get('node_seq') or 0)
    except (TypeError, ValueError):
        saved = 0
    if _SEQ_MIN <= saved <= _SEQ_MAX:
        return saved

    guess = _DEFAULT_SEQ.get(_default_label().strip().lower(), 0)
    if guess:
        set_node_seq(guess, config_file)
    return guess


def set_node_seq(seq: int, config_file: Path | None = None) -> bool:
    """번호를 저장한다. 범위 밖이면 저장하지 않는다(node_id는 건드리지 않음)."""
    try:
        value = int(seq)
    except (TypeError, ValueError):
        return False
    if not (_SEQ_MIN <= value <= _SEQ_MAX):
        return False
    path = Path(config_file) if config_file else CONFIG_FILE
    with _lock:
        cfg = _read_config(path)
        cfg['node_seq'] = value
        return _write_config(path, cfg)


def node_ref(agent_id: str, config_file: Path | None = None) -> str:
    """로컬 agent_id('claude:T1')를 중앙 DB용 전역 참조로 감싼다.

    [🔴 로컬 식별자를 바꾸지 않는다] pg_logs·hive_tasks·agent_heartbeats는 계속
      'claude:T1'을 쓴다. 감싸는 것은 중앙으로 나갈 때뿐이다 — 로컬 스키마에 node_id가
      새어 들어가면 기존 조회/조인이 전부 깨진다.
    """
    return f"{get_node_id(config_file)}/{agent_id}"


def parse_node_ref(ref: str) -> tuple[str, str]:
    """'<node_id>/<agent_id>' → (node_id, agent_id).

    node_id 부분이 형식에 맞지 않으면 ('', 원본)을 돌려준다 — 감싸지 않은 레거시 값이
    중앙에 섞여 들어와도 호출부가 KeyError 없이 로컬 참조로 다룰 수 있게 한다.
    agent_id 자체가 'claude:T1'처럼 ':'를 포함하므로 구분자는 '/' 하나뿐이고,
    첫 '/'에서만 나눈다(라벨/경로가 뒤에 붙어도 안전).
    """
    text = str(ref or '')
    head, sep, tail = text.partition('/')
    if sep and _NODE_ID_RE.fullmatch(head.lower()):
        return head.lower(), tail
    return '', text


def is_local_ref(ref: str, config_file: Path | None = None) -> bool:
    """이 PC가 보낸 참조인가. 중앙에서 받은 메시지의 에코를 걸러낼 때 쓴다."""
    node, _ = parse_node_ref(ref)
    return bool(node) and node == get_node_id(config_file)


def reset_cache() -> None:
    """테스트 전용 — 모듈 캐시를 비운다. 운영 코드에서 호출하지 말 것."""
    global _cached_id, _cached_path
    with _lock:
        _cached_id = None
        _cached_path = None
