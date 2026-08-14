"""
FILE: infra/instance_lock.py
DESCRIPTION: 단일 인스턴스 락 획득 + HTTP/WS 서버 포트 확정 로직.
             server.py main() 부팅 시퀀스에서 top-level 함수로 승격됨.
             락은 실행 환경(개발/frozen/smoke)별로 시드를 분리해 동시 기동을
             허용하고, 이미 실행 중이면 기존 창을 Win32 API로 포커스한 뒤
             os._exit(0)으로 새 인스턴스를 즉시 종료한다.

REVISION HISTORY:
- 2026-08-14 Claude: 좀비 락 회수 구현 — 락 bind 실패를 곧바로 '실행 중'으로 단정하던
                     경로가, 커널 대기(wait=Executive)에 갇혀 kill조차 안 먹는 좀비가
                     락 포트를 영구 점유하면 **개발 서버 영구 기동 불가**로 이어졌다.
                     2026-07-16에 smoke 경로만 PID 시드로 우회했고 dev/frozen은 미수정,
                     L97의 "좀비 회수" 주석은 구현이 없는 채였다 — 그 빈칸을 메운다.
- 2026-07-22 Claude: 멀티 인스턴스 포트 슬롯화 — (프로젝트×환경) 해시로 9000-9008 짝수
                     베이스를 결정적 배정. dev+설치본 + '서로 다른 프로젝트 설치본 2개'
                     동시 실행 시 둘 다 9000을 선호해 TOCTOU 경쟁→나중 인스턴스 PTY가
                     먼저 인스턴스 포트에 얹힘→먼저 창 닫으면 나머지 터미널 전멸하던 사고
                     수정. 폴백도 9010(오피스 침범)→대역 내(9000-9008) 한정.
- 2026-07-17 Claude: 포트 폴백 9010 하드코딩 수정 — VIBE_PORT_BASE 명시 시 대역 내(+1)
                     탐색. 좀비의 9100 점유 시 smoke 서버가 9010번대로 새어 스캔 실패하던
                     "무바인딩" 오판의 근본 원인.
- 2026-07-16 Claude: smoke 락 시드에 PID 추가 — 좀비 EXE의 고정 락 포트 영구 점유로
                     후속 smoke 전멸하는 사고 재발 방지 (사용자 싱글턴 의미 불변).
- 2026-07-08 Claude: server.py main() L1697~1779 인스턴스 락 + 포트 확정 블록 분리
                     (Phase 3 R17-2). 로직·주석 verbatim 유지.
                     [불변식] resolve_server_ports가 반환한 (http, ws)를 caller가
                     반드시 모듈 전역 HTTP_PORT/WS_PORT에 재대입해야 한다 — 모듈 스코프
                     소비자(_p_dashboard_launch/_cors_origin/fs_watcher/cleanup 등)가
                     stale 9000/9001을 참조하는 R14 이중전역 버그 재발 방지.
                     [제약] find_free_port는 caller(src.server_utils)가 주입 — infra가
                     server_utils를 역참조하면 import 사이클 위험.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import socket
import sys
import threading
from pathlib import Path

# [불변식] 락 소켓 핸드셰이크 배너. 살아있는 인스턴스만 이걸 보낸다 —
#   '포트가 잡혀 있다'와 '주인이 살아있다'를 가르는 유일한 신호다.
_LOCK_HELLO = b'VIBE-INSTANCE-ALIVE\n'

# 좀비 확정 시 다음 락 포트로 몇 칸까지 비켜갈지. 19001+479가 대역 끝이라
# 20칸은 항상 대역 안에 머문다(_LOCK_PORT 최대 19480 → 19500은 초과하나
# 락 대역은 우리만 쓰는 사설 구간이라 실害 없음 — 충돌 시 계속 +1 할 뿐).
_MAX_LOCK_HOP = 20


def _probe_lock_holder(port: int, timeout: float = 0.8) -> bool:
    """락 포트 점유자가 '살아있는 인스턴스'인지 핸드셰이크로 판정.

    [WHY 핸드셰이크] bind 실패만으로는 주인의 생사를 알 수 없다. 커널 대기에 갇힌
      좀비(wait=Executive — 관리자 kill도 안 먹는다)는 소켓을 계속 붙들지만 accept를
      못 한다. 연결이 거부/무응답이면 좀비, 배너가 오면 진짜 실행 중이다.
    [WHY HTTP가 아니라 여기부터] HTTP는 부팅 완료 후에야 뜬다 — 부팅 중인 정상
      인스턴스를 좀비로 오판해 중복 실행할 위험이 있다. 락 핸드셰이크는 부팅 최초
      단계에서 켜지므로 '부팅 중'도 살아있음으로 정확히 잡는다.
    """
    try:
        with contextlib.closing(socket.create_connection(('127.0.0.1', port),
                                                         timeout=timeout)) as s:
            s.settimeout(timeout)
            return s.recv(len(_LOCK_HELLO)).startswith(b'VIBE-INSTANCE')
    except OSError:
        return False


def _probe_http_holder(project_root: Path) -> bool:
    """[구버전 호환 보조] 이 프로젝트의 서버가 HTTP로 응답 중인가.

    [WHY] 핸드셰이크를 모르는 구버전 인스턴스가 락을 쥐고 있으면 위 판정이 좀비로
      오판한다. 그쪽은 HTTP가 이미 떠 있으므로 여기서 걸러진다. 이 보조선은 구버전이
      모두 교체되면 자연히 무용해진다(제거해도 안전).
    [제약] project_id 대조 필수 — 첫 응답 채택은 타 프로젝트 서버를 '내 인스턴스'로
      오인해 멀쩡한 기동을 막는다(server_locator 2026-07-16 사고와 같은 함정).
      슬러그 산출이 실패하면 보수적으로 '살아있음'(=기존 동작 유지) 쪽에 선다.
    [제약] 지연 import — infra가 src를 모듈 로드 시점에 참조하면 사이클 위험.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor

        from infra.project_context import slugify
        from src.server_locator import probe_port
    except Exception:
        return False
    try:
        want = slugify(project_root)
    except Exception:
        want = ''
    try:
        with ThreadPoolExecutor(max_workers=20) as ex:
            for r in ex.map(probe_port, range(9000, 9020)):
                if not r:
                    continue
                if not want or r[1] == want or r[1] == '':
                    return True
    except Exception:
        return False
    return False


def _serve_lock_hello(sock: socket.socket) -> None:
    """락 소켓을 listen 상태로 올리고 생존 배너를 응답하는 데몬 스레드를 붙인다.

    [제약] 이 스레드는 caller가 락 소켓을 close()하면 accept가 OSError로 깨져
      스스로 끝난다 — 별도 종료 신호가 없는 건 그 때문이다(daemon=True라 프로세스
      종료도 막지 않는다).
    """
    try:
        sock.listen(8)
    except OSError:
        return  # listen 실패해도 락(bind) 자체는 유효 — 기동을 막지 않는다

    def _loop() -> None:
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with contextlib.closing(conn):
                with contextlib.suppress(OSError):
                    conn.sendall(_LOCK_HELLO)

    threading.Thread(target=_loop, daemon=True, name='instance-lock-hello').start()


def _focus_existing_and_exit(project_root: Path, lock_port: int) -> None:
    """살아있는 기존 인스턴스를 확인한 경우 — 그 창을 포커스하고 즉시 종료(반환 없음)."""
    print(f"[*] 이미 실행 중인 인스턴스 감지 (락 포트 {lock_port})")
    if os.name == 'nt':
        try:
            import ctypes
            _win_title = f"바이브 코딩 [{project_root.name}]"
            _hwnd = ctypes.windll.user32.FindWindowW(None, _win_title)
            if _hwnd:
                # [과거사고 2026-07-25] 여기서 SW_RESTORE(9)를 무조건 걸어, 사용자가
                # 최대화해 둔 창이 메시지를 보낼 때마다 이전 크기로 줄어들었다.
                # SW_RESTORE는 '최소화 해제'가 아니라 '최대화/최소화 이전 크기로 복원'
                # 이라 최대화 창에 걸면 최대화가 풀린다. 유발 경로: hook_bridge가 살아있는
                # 서버를 오프라인으로 오판(.server.pid만 조회) → 매 메시지 server.py 재스폰
                # → 새 인스턴스가 락에 걸려 이 분기 진입 → 창 축소 → os._exit. 사용자 눈엔
                # "채팅 엔터 칠 때마다 창이 작아짐"으로만 보여 원인 추적이 오래 걸렸다.
                # [불변식] 창 크기/최대화 상태는 사용자 소유다 — 포커스 목적으로 건드리지
                # 않는다. 최소화(IsIconic)된 창만 화면에 되살리면 목적이 충족된다.
                if ctypes.windll.user32.IsIconic(_hwnd):
                    ctypes.windll.user32.ShowWindow(_hwnd, 9)    # SW_RESTORE — 최소화 해제용
                ctypes.windll.user32.SetForegroundWindow(_hwnd)
                print(f"[*] 기존 창 포커스 완료: {_win_title}")
            else:
                print(f"[*] 기존 창을 찾을 수 없습니다 (아직 로딩 중일 수 있음)")
        except Exception as e:
            print(f"[!] 창 포커스 실패: {e}")
    os._exit(0)


def acquire_single_instance_lock(project_root: Path) -> socket.socket:
    """단일 인스턴스 락을 획득해 락 소켓을 반환한다.

    이미 실행 중이면 기존 창을 포커스하고 os._exit(0)으로 즉시 종료(반환하지 않음).
    반환된 소켓은 caller가 종료 시점에 close() 해야 한다(락 해제).
    """
    # ── 단일 인스턴스 락 (최우선 — ensure_postgres_running 이전) ───────────────
    # [v3.7.179] 단일 인스턴스 전면 전환 — _MAX_INSTANCES 4→1.
    # 더블클릭으로 2개 창이 뜨고, 하나를 닫으면 터미널이 죽는 치명적 UX 버그 해결.
    # 이미 실행 중이면 기존 창을 Win32 API로 포커스하고 새 인스턴스는 즉시 종료.
    # 같은 PROJECT_ROOT라도 개발 모드/설치 EXE/smoke test가 동시에 떠야 하므로
    # 락 시드를 실행 환경별로 분리한다 (v3.7.225)
    _lock_seed = str(project_root)
    if getattr(sys, 'frozen', False):
        _lock_seed = f"{_lock_seed}::frozen"
    if os.environ.get('VIBE_SMOKE_TEST', '').strip() in ('1', 'true', 'on'):
        # [과거사고 2026-07-16] smoke 시드가 고정이라 커널 좀비化된 smoke EXE 1개가
        # 락 포트를 영구 점유 → 이후 모든 smoke가 "이미 실행 중" exit 0으로 오판.
        # smoke는 일회성+포트 자동 스캔(9100~)이라 상호 배제 자체가 불필요 — PID를
        # 섞어 실행마다 고유 락으로 만들어 좀비 내성 확보 (사용자 싱글턴 의미는 불변).
        _lock_seed = f"{_lock_seed}::smoke::{os.getpid()}"
    _proj_hash    = int(hashlib.md5(_lock_seed.encode()).hexdigest()[:4], 16)
    _LOCK_PORT    = 19001 + (_proj_hash % 480)
    _proj_id      = f"{_proj_hash:04x}"

    # ── 락 획득 (+ 좀비 점유 시 회수) ────────────────────────────────────────
    # [🔴 과거사고 2026-08-14] 이 자리에서 bind 실패를 곧바로 '이미 실행 중'으로 단정하고
    #   os._exit(0)을 했다. 그런데 커널 대기(wait=Executive)에 갇혀 관리자 권한
    #   Stop-Process조차 튕겨내는 좀비가 락 포트를 붙들자, 새 서버가 매 시도마다 조용히
    #   즉사해 **재부팅 전까지 개발 서버 기동 불가**가 됐다. 증상이 "로그에 Server Started만
    #   찍히고 본문 0줄"이라 원인이 코드 수정 쪽으로 오인되기 쉽다.
    # [불변식] '포트가 잡혀 있다' ≠ '주인이 살아있다'. 생사는 반드시 핸드셰이크(+HTTP
    #   보조)로 확인하고, 좀비로 확인된 경우에만 옆 포트로 비켜간다. 확인 없이 비켜가면
    #   단일 인스턴스 보장이 깨져 v3.7.179 이전의 '창 2개' 버그로 되돌아간다.
    _lock_sock = None
    _port = _LOCK_PORT
    for _attempt in range(_MAX_LOCK_HOP):
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            _sock.bind(('127.0.0.1', _port))
            _lock_sock = _sock
            break
        except OSError:
            _sock.close()   # [제약] 실패 소켓을 닫지 않으면 hop마다 fd가 샌다
            if _probe_lock_holder(_port):
                _focus_existing_and_exit(project_root, _port)      # 살아있는 주인 확정
            # 핸드셰이크 무응답 — 좀비이거나, 핸드셰이크를 모르는 구버전이다.
            # HTTP 보조 판정은 20포트 스캔이라 비싸므로 첫 충돌에서 한 번만 쓴다.
            if _attempt == 0 and _probe_http_holder(project_root):
                _focus_existing_and_exit(project_root, _port)      # 구버전 주인 확정
            print(f"[!] 락 포트 {_port} 좀비 점유 감지 (응답 없음) → 다음 포트로 회수 시도")
            _port += 1

    if _lock_sock is None:
        # [WHY 종료] 20칸 연속 좀비는 정상 상황이 아니다 — 여기서 락 없이 진행하면
        #   단일 인스턴스 보장이 통째로 사라진다. 재부팅 안내가 정직한 실패다.
        print(f"[!] 락 포트 {_LOCK_PORT}~{_port - 1} 전부 점유 — 좀비 프로세스가 남아 있습니다.")
        print(f"[!] 재부팅하거나 남은 pythonw/python 프로세스를 정리한 뒤 다시 실행하세요.")
        os._exit(1)

    # [WHY] 락을 쥔 쪽이 배너를 응답해야 다음 인스턴스가 나를 '좀비 아님'으로 판정한다.
    #   bind만 하고 끝내면 위 _probe_lock_holder가 나를 좀비로 오인해 중복 실행된다.
    _serve_lock_hello(_lock_sock)

    if _port != _LOCK_PORT:
        print(f"[*] 인스턴스 락 확보 (포트 {_port} — 원래 슬롯 {_LOCK_PORT}는 좀비 점유)")
    else:
        print(f"[*] 인스턴스 락 확보 (포트 {_port})")
    return _lock_sock


def _server_port_slot_base(project_root: Path | None) -> int:
    """(프로젝트 × 실행환경)마다 9000-9008 대역의 고유 짝수 베이스를 결정적으로 배정.

    [WHY] 서로 다른 프로젝트의 설치본(frozen) 2개를 동시에 켜는 게 실제 목표인데,
      둘 다 frozen이라 같은 9000을 선호하면 test-bind→close→real-bind TOCTOU 경쟁으로
      같은 http/ws를 골라 나중 인스턴스 PTY가 먼저 인스턴스 포트에 얹히고 → 먼저 창을
      닫으면 나머지 터미널이 통째로 죽는다(2026-07-22 사고). 인스턴스 락과 동일 시드로
      해시해 슬롯을 미리 갈라두면 경쟁 자체가 성립하지 않는다.
    [불변식/대역] 5슬롯(9000/9002/9004/9006/9008) — http=짝수, ws=http+1(홀수)이라 쌍이
      모두 9000-9009 안. 오피스(9010~9018)·heartbeat 싱글턴(9019)과 비충돌이고
      server_locator 스캔(9000-9019)이 project_id 대조로 자기 서버만 골라낸다.
    [한계] 5슬롯 mod 해시라 서로 다른 프로젝트가 같은 슬롯에 떨어질 확률 1/5 — 그 경우엔
      아래 fallback(대역 내 재탐색)이 흡수한다. 6개 이상 동시 실행은 대역 포화라 미지원.
    """
    if project_root is None:
        return 9000
    _seed = str(project_root)
    if getattr(sys, 'frozen', False):
        _seed += '::frozen'
    _h = int(hashlib.md5(_seed.encode()).hexdigest()[:4], 16)
    return 9000 + (_h % 5) * 2


def _try_bind(port: int) -> bool:
    """해당 포트가 지금 비어있는지 실제 bind로 확인(즉시 close). TOCTOU 有 — 확정 아님."""
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _s.bind(('127.0.0.1', port))
        _s.close()
        return True
    except OSError:
        return False


def resolve_server_ports(find_free_port, project_root: Path | None = None) -> tuple[int, int]:
    """HTTP/WS 서버 포트를 확정해 (http_port, ws_port)를 반환한다.

    find_free_port: 빈 포트 탐색 함수 (caller가 src.server_utils에서 주입).
    project_root: 슬롯 해시용. 생략 시 9000 고정(하위호환).
    """
    # ── 포트 확정: (프로젝트×환경) 고유 슬롯 우선 + 충돌 시 대역 내 대체 탐색 ────────
    # VIBE_PORT_BASE 환경변수가 있으면 그 값이 '항상' 우선 (smoke test 격리 계약 불변).
    if 'VIBE_PORT_BASE' in os.environ:
        _preferred_http = int(os.environ['VIBE_PORT_BASE'])
    else:
        # [멀티 인스턴스] dev+설치본 + '서로 다른 프로젝트 설치본 2개'까지 각자 다른 포트를
        #   선점하도록 프로젝트별 결정적 슬롯 사용 (_server_port_slot_base 참조).
        _preferred_http = _server_port_slot_base(project_root)

    if _try_bind(_preferred_http):
        http_port = _preferred_http
    elif 'VIBE_PORT_BASE' in os.environ:
        # [과거사고 2026-07-17] 폴백이 9010 하드코딩이라 smoke(VIBE_PORT_BASE=9100)에서
        # 9100이 좀비 EXE에 점유되면 서버가 9010번대로 새어 나가 기동 — smoke_test는
        # 9100~9120만 스캔하므로 "무바인딩"으로 오판. 명시 대역 안(+1부터)에서 탐색해 격리 유지.
        http_port = find_free_port(_preferred_http + 1, max_tries=40)
        print(f"[!] 포트 {_preferred_http} 사용 중 → 대체 포트 {http_port} 사용")
    else:
        # [슬롯 충돌 흡수] 선호 슬롯이 점유됨(같은 슬롯 해시 or 외부 점유) → 서버 대역
        #   9000-9008 짝수만 재탐색. 기존 9010 하드코딩 폴백은 오피스 대역(9010~)을 침범해
        #   두 번째 설치본이 오피스와 충돌하던 문제가 있어 대역 내로 한정한다.
        http_port = next((p for p in range(9000, 9009, 2) if _try_bind(p)), 0)
        if not http_port:
            http_port = find_free_port(9000, max_tries=10)  # 대역 포화 — 최후 수단
        print(f"[!] 슬롯 {_preferred_http} 사용 중 → 대역 내 대체 포트 {http_port} 사용")

    _preferred_ws = http_port + 1
    if _try_bind(_preferred_ws):
        ws_port = _preferred_ws
    else:
        ws_port = find_free_port(_preferred_ws + 1, max_tries=40)
        print(f"[!] WS 포트 {_preferred_ws} 사용 중 → 대체 포트 {ws_port} 사용")

    print(f"[*] 서버 포트 확정 — HTTP:{http_port}, WS:{ws_port}")
    return http_port, ws_port
