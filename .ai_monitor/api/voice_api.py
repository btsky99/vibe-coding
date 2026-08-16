# -*- coding: utf-8 -*-
"""
FILE: api/voice_api.py
DESCRIPTION: 음성 API — 턴 채널 조회 + 음성 사이드카(STT/TTS) 프록시.
             server.py가 /api/voice/* 요청을 이 모듈로 위임합니다.

             [엔드포인트]
             GET  /api/voice/turn?terminal=T1  → Stop 훅이 남긴 그 슬롯의 마지막 답
             GET  /api/voice/status            → 사이드카 준비 상태(없으면 기동 시도)
             POST /api/voice/stt   (audio/wav) → {text}
             POST /api/voice/tts   (json)      → audio/wav

             [🔴 왜 프록시인가] 실제 인식·합성은 voice-server 사이드카(별도 python·venv)가
             한다. 앱 서버가 직접 모델을 올리면 torch 의존성과 GPU 점유가 대시보드에
             들러붙는다(voice-server/voice_server.py 헤더 참조). 여기서는 바이트만 나른다.

             [🔴 사이드카를 여기서 켠다] 사용자가 음성을 켜는 순간이 곧 첫 /status 요청이다.
             그때 없으면 띄운다 — 앱 부팅 때 미리 띄우면 음성을 안 쓰는 사람도 모델 로딩
             비용을 낸다.

             [제약] 기동은 반드시 infra.proc 경유(규칙 10). 이 프로세스는 사람이 누른 적
             없는 자식이라 콘솔 창이 뜨면 그 자체가 사고다.

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — 턴 채널 + 로컬 음성 사이드카 프록시
- 2026-08-15 Claude: '음성 엔진 준비 중'에서 안 넘어가던 사고 — stdout=PIPE 를 아무도
  읽지 않아 자식이 멈췄다. 로그 파일로 돌리고, 죽은 자식을 다시 띄우게 판정을 실물화
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from api._common import json_response as _json_response

# 사이드카 포트.
# [🔴 과거사고 2026-08-15 — 9021 은 쓸 수 없다] 포트 지도(9000-9009 서버 / 9010+ 오피스 /
#   9019 heartbeat / 9020 LAN)를 보고 '다음 자리'인 9021 을 잡았는데, LAN 브리지는 한 자리가
#   아니라 인스턴스마다 9020,9021,… 로 번진다(실측: 두 인스턴스가 9020·9021 점유).
#   결과가 나쁜 쪽으로 조용했다 — 사이드카는 뜨지도 못하고, /status 요청은 LAN 브리지가
#   받아 404 를 돌려줘 '음성 엔진 준비 안 됨'으로만 보였다. 포트 지도의 '다음 자리'는
#   안전하지 않다. 대역을 띄워 잡는다.
VOICE_PORT = int(os.environ.get('VOICE_PORT', '9030'))
BASE_URL = f'http://127.0.0.1:{VOICE_PORT}'

_spawn_lock = threading.Lock()
# 음성 스택 자동 설치(setup_voice.ensure_env)의 진행 상태.
# [🔴 왜 상태를 들고 있나] 설치는 수백 MB·수 분이다. /status 는 4초마다 온다 —
#   상태가 없으면 매번 설치를 새로 걸거나, 반대로 '준비 중'만 무한히 돌려준다.
_setup_lock = threading.Lock()
_setup_thread = None                                        # threading.Thread | None
_setup_msg = ''                                             # 실패 사유(사람이 읽을 문장)
# [🔴 bool 이 아니라 Popen 을 들고 있는 이유] 예전엔 `_spawned = True` 한 장으로 판정했는데,
#   자식이 죽어도 플래그가 남아 두 번 다시 안 띄웠다 — 화면은 영구히 '준비 중'이 된다.
#   poll() 로 실물을 보면 죽은 뒤 첫 /status 요청이 곧 재기동이 된다.
_proc = None                                                # subprocess.Popen | None
_log_fp = None                                              # 자식 수명 동안 열려 있어야 한다


def _sidecar_log(project_root: Path):
    """사이드카 stdout/stderr 를 받을 파일을 연다(매 기동 덮어쓰기).

    [🔴 과거사고 2026-08-15 — PIPE 로 받으면 자식이 죽는다] stdout=PIPE 로 띄우고 부모가
      읽지 않으면 파이프 버퍼가 차서 자식이 write 에서 멈춘다. 실측 증상은 조용했다 —
      프로세스는 살아 있고(CPU 0.03초·리슨 0개) /status 는 영원히 '준비 중'이었으며,
      TTS 예열은 `[Errno 22] Invalid argument` 로 떨어졌다. 같은 결함을 이 리포가 이미
      두 번 고쳤다(postgres_runtime.py:212 PIPE 상속 버그, agent_api.py:18 stderr 데드락).
    [WHY DEVNULL 이 아니라 파일인가] 콘솔 없이 도는 자식이라(규칙 10) 버리면 실패 원인을
      볼 방법이 아예 없다. 위 진단도 로그를 파일로 돌린 뒤에야 5분 만에 끝났다.
    [WHY 덮어쓰기인가] 기동은 드물다. append 면 아무도 안 지워 무한히 자란다.
    """
    global _log_fp
    path = project_root / '.ai_monitor' / 'voice-server' / 'voice-server.log'
    try:
        if _log_fp and not _log_fp.closed:
            _log_fp.close()
        _log_fp = path.open('wb')
        return _log_fp
    except OSError:
        # 로그를 못 열었다고 음성을 포기하지는 않는다 — 조용히 버리는 쪽이 낫다.
        import subprocess
        return subprocess.DEVNULL


def _frozen_carries_voice() -> bool:
    """지금 이 EXE 번들 안에 음성 패키지가 **실제로** 실려 있는가.

    [🔴 왜 물어봐야 하나 — 2026-08-16 실측] 설치본은 EXE 안 소스가 아니라 관리형
      체크아웃을 실행하고, 소스는 경량 업데이트 채널로 혼자 최신이 된다. 그래서
      **새 소스 + 낡은 EXE** 조합이 흔하다. 사장님 PC 실측이 정확히 그것이었다 —
      체크아웃은 v3.7.340 인데 EXE 는 2026-07-23 자로 edge_tts·faster_whisper 가
      아예 없었다(_internal 에 두 패키지 모두 부재). 그 상태에서 EXE 를 실행기로
      내주면 사이드카는 뜨자마자 ImportError 로 죽고, 그 죽음은 별도 프로세스라
      조용하다 — 화면은 '준비 중'인 채 마이크만 안 먹는다.
    [WHY find_spec 인가] 사이드카는 이 프로세스와 같은 frozen 런타임으로 돈다.
      여기서 못 찾는 모듈은 거기서도 못 찾는다 — 경로를 추측하는 것보다 정확하다.
      (PyInstaller 는 순수 파이썬 패키지를 PYZ 에 넣으므로 폴더 존재 검사로는 못 본다.)
    """
    if not getattr(sys, 'frozen', False):
        return False
    try:
        from importlib.util import find_spec
        return bool(find_spec('faster_whisper')) and bool(find_spec('edge_tts'))
    except Exception:                                       # noqa: BLE001
        return False


def _sidecar_python(project_root: Path) -> str | None:
    """사이드카를 실행할 파이썬.

    [개발] 별도 환경(.ai_monitor/voice-server/.venv)을 쓴다. 앱 venv 와 섞지 않는 편이
      의존성 다툼이 없고, 음성을 안 쓰는 개발자는 아예 안 깔아도 된다.
    [🔴 설치본에는 그 .venv 가 없다 — 2026-08-16 사고] 그 환경을 만들어 주는 것은
      scripts/setup_voice.py 인데 **설치·최초실행 어디에서도 그걸 부르지 않았다.**
      그래서 설치본에서는 사이드카가 영영 못 떠서 마이크도 목소리 목록도 조용히 죽었다
      (단추는 눌리는데 전송이 안 되고, edge-tts 목소리가 안 보이는 증상).
      해결은 두 겹이다 — ① 번들이 음성을 싣고 있으면 EXE 자신을 실행기로 쓰고,
      ② 아니면 _ensure_voice_env() 가 venv 를 자동으로 깐다. ②가 없으면 낡은 EXE 를
      쓰는 사람은 새 소스를 받아도 영원히 안 된다.
    [불변식] EXE 폴백은 frozen + 번들 검증 통과 전용이다. 검증 없이 내주면 조용한
      ImportError 사망으로 되돌아간다.
    """
    candidates = [
        os.environ.get('VOICE_PYTHON', ''),
        str(project_root / '.ai_monitor' / 'voice-server' / '.venv' / 'Scripts' / 'python.exe'),
        str(project_root / '.ai_monitor' / 'voice-server' / '.venv' / 'bin' / 'python'),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    if _frozen_carries_voice():
        # boot.main() 이 첫 인자가 .py 면 runpy 로 받아 준다(창이 한 벌 더 뜨지 않는다).
        return sys.executable
    return None


def _ensure_voice_env(project_root: Path) -> str:
    """음성 스택이 없으면 백그라운드로 깐다. 진행 중이면 그 사실만 알린다.

    [🔴 왜 자동인가] 마이크 단추를 누른 것이 곧 '음성을 쓰겠다'는 의사표시다. 여기서
      멈추고 사용자에게 명령줄을 치라고 하면, 그게 바로 2026-08-16 사고의 모습이다
      (안내조차 화면에 안 떠서 사용자는 '단추가 안 먹는다'로만 겪었다).
    [🔴 규칙 10] 설치는 사람이 콘솔에서 부른 것이 아니다 — infra.proc 로 창 없이 돌리고
      진행은 voice-setup.log 로 본다. subprocess 직접 호출로 되돌리면 pip 가 도는
      수 분 동안 검은 창이 사장님 화면 위에 뜬다.
    [불변식] 스레드는 한 번에 하나. /status 는 4초마다 오므로 매번 걸면 pip 가 겹쳐
      돈다 — venv 가 반쯤 만들어진 채로 서로를 덮는다.
    """
    global _setup_thread, _setup_msg
    # [🔴 _spawn_lock 을 재사용하면 안 된다] 이 함수는 그 락을 쥔 _spawn_sidecar 안에서
    #   불린다. threading.Lock 은 재진입이 안 돼 같은 스레드가 그대로 굳는다(무한 대기).
    with _setup_lock:
        if _setup_thread is not None and _setup_thread.is_alive():
            return '음성 스택을 설치하는 중입니다(처음 한 번, 수백 MB — 몇 분 걸립니다)'
        if _setup_msg:
            return _setup_msg                               # 실패는 다시 두드려도 같다
        log_path = project_root / '.ai_monitor' / 'voice-server' / 'voice-setup.log'

        def _quiet(cmd, env):
            import subprocess

            from infra import proc
            with log_path.open('ab') as fp:
                fp.write(f'\n$ {" ".join(cmd)}\n'.encode('utf-8', 'replace'))
                fp.flush()
                return proc.run(cmd, cwd=str(project_root), env=env,
                                stdin=subprocess.DEVNULL, stdout=fp,
                                stderr=subprocess.STDOUT).returncode

        def _work():
            global _setup_msg
            try:
                sys.path.insert(0, str(project_root / 'scripts'))
                import setup_voice
                ok, msg = setup_voice.ensure_env(project_root, _quiet)
                _setup_msg = '' if ok else msg
            except Exception as e:                          # noqa: BLE001
                _setup_msg = f'음성 설치 실패: {type(e).__name__}: {e}'

        _setup_thread = threading.Thread(target=_work, name='voice-setup', daemon=True)
        _setup_thread.start()
        return '음성 스택을 설치하는 중입니다(처음 한 번, 수백 MB — 몇 분 걸립니다)'


def _spawn_sidecar(project_root: Path) -> str:
    """사이드카를 띄운다. 이미 살아 있으면 아무것도 하지 않는다."""
    global _proc
    with _spawn_lock:
        if _proc is not None and _proc.poll() is None:
            return ''
        py = _sidecar_python(project_root)
        if not py:
            # 실행기가 없다 = 아직 아무도 음성 스택을 깔지 않았다. 여기서 끝내지 않고
            # 깔기 시작한다 — 그 판단 근거는 _ensure_voice_env 주석 참조.
            return _ensure_voice_env(project_root)
        script = project_root / '.ai_monitor' / 'voice-server' / 'voice_server.py'
        if not script.exists():
            # [폴백 — 번들 동봉본] 게이트 실패로 seed 로 돌거나 체크아웃이 옛 소스라
            #   voice-server 가 없을 수 있다. frozen 번들에는 항상 실려 있으므로 그쪽을 쓴다
            #   (vibe-coding.spec datas 의 'voice-server' 항목과 한 쌍).
            # [불변식] engines/ 가 스크립트와 같은 폴더에 있어야 한다 —
            #   voice_server._engines_dir_on_path() 가 __file__ 기준으로 경로를 잡는다.
            bundled = Path(getattr(sys, '_MEIPASS', '')) / 'voice-server' / 'voice_server.py'
            if getattr(sys, 'frozen', False) and bundled.exists():
                script = bundled
            else:
                return f'사이드카 스크립트가 없습니다: {script}'
        try:
            import subprocess

            from infra import proc
            # [🔴 규칙 10] 사람이 누르지 않은 실행이다 — infra.proc 이 CREATE_NO_WINDOW 를
            #   붙여 준다. subprocess 를 직접 부르면 매 기동마다 콘솔이 번쩍인다.
            # [🔴 stdout 은 파일 — PIPE 금지] _sidecar_log 주석 참조. 부모(server.py)는
            #   이 자식을 읽어 주는 스레드가 없다.
            # [🔴 stdin=DEVNULL] 부모가 pythonw 라 stdin 핸들이 무효다. 그대로 상속시키면
            #   자식이 표준입력을 만지는 순간(일부 네이티브 라이브러리가 그런다) 터진다.
            _proc = proc.popen([py, str(script)],
                               cwd=str(script.parent),
                               stdin=subprocess.DEVNULL,
                               stdout=_sidecar_log(project_root),
                               stderr=subprocess.STDOUT,
                               env={**os.environ, 'VOICE_PORT': str(VOICE_PORT)})
            return ''
        except Exception as e:                              # noqa: BLE001
            return f'사이드카 기동 실패: {type(e).__name__}: {e}'


def _get(path: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(f'{BASE_URL}{path}', timeout=timeout) as r:
        return json.loads(r.read() or b'{}')


def _post(path: str, body: bytes, content_type: str, timeout: float) -> tuple[bytes, str]:
    req = urllib.request.Request(f'{BASE_URL}{path}', data=body,
                                 headers={'Content-Type': content_type})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get('Content-Type', 'application/json')


# ── 라우트 ────────────────────────────────────────────────────────────────

def handle_turn(handler, parsed_path, project_id: str) -> None:
    """GET /api/voice/turn?terminal=T1 — Stop 훅이 남긴 마지막 답.

    [WHY 404 가 아니라 200 + waiting 인가] 훅이 아직 한 번도 안 돈 상태는 장애가 아니라
      그냥 '아직'이다. 404 로 주면 화면이 이걸 고장으로 그린다.
    """
    from urllib.parse import parse_qs

    qs = parse_qs(parsed_path.query or '')
    terminal = (qs.get('terminal') or [''])[0]

    from infra import voice_turn
    _json_response(handler, voice_turn.read(project_id, terminal))


def _mic_permission() -> dict:
    """{ok, detail} — WebView2 마이크 권한 배선이 붙었나.

    [WHY 여기서 import 하나] 이 모듈은 헤드리스(창 없는 서버)에서도 돈다. 그때는
      webview 자체가 없으므로 최상단 import 로 두면 서버가 통째로 못 뜬다."""
    try:
        from infra.webview_permissions import status
        return status()
    except Exception:                                       # noqa: BLE001
        return {'ok': None, 'detail': '창이 없는 실행이라 해당 없음'}


def handle_status(handler, project_root: Path) -> None:
    """GET /api/voice/status — 사이드카가 준비됐는가. 없으면 기동을 시작한다."""
    try:
        d = _get('/status')
        # [🔴 마이크 권한 배선 결과를 같이 실어 보낸다 — 2026-08-17 사장 신고]
        #   "마이크 눌러도 입력이 안 뜬다" 인데 서버 칸은 실측으로 멀쩡했다
        #   (사이드카 /stt 2.6초 · 이 프록시 2.5초, 둘 다 글자까지 정상).
        #   남은 후보는 브라우저가 소리를 못 잡는 것뿐인데, 그 판정 근거가 앱 stdout 에만
        #   있어 **아무도 못 봤다.** 여기 얹으면 화면이 원인을 바로 말할 수 있다.
        #   [제약] 이 값은 앱 프로세스 안의 모듈 상태다 — 사이드카는 알 수 없다.
        if isinstance(d, dict):
            d['micPermission'] = _mic_permission()
        _json_response(handler, d)
        return
    except (urllib.error.URLError, OSError, ValueError):
        pass                                                # 아직 안 떠 있다 — 아래에서 띄운다

    err = _spawn_sidecar(project_root)
    # [🔴 '설치 중'은 실패가 아니다] loading=false 로 주면 화면이 빨간 오류로 그린다.
    #   사용자가 할 일은 기다리는 것뿐인데 고장으로 읽히면 앱을 껐다 켜게 된다.
    installing = _setup_thread is not None and _setup_thread.is_alive()
    _json_response(handler, {
        'ready': False,
        'loading': not err or installing,
        'detail': err or '음성 엔진을 준비하는 중입니다(첫 기동은 수십 초 걸립니다)',
    })


def handle_stt(handler, body: bytes) -> None:
    """POST /api/voice/stt — WAV 를 넘기고 받아쓴 텍스트를 돌려준다."""
    try:
        # [WHY 넉넉한 타임아웃인가] CPU 인식은 발화 길이에 비례한다. small 기준 3초 안팎이고
        #   첫 요청은 모델 로딩까지 걸린다. 여기서 끊으면 사용자는 '안 들었다'로 읽는다.
        raw, _ct = _post('/stt', body, 'audio/wav', timeout=120)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Content-Length', str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
    except Exception as e:                                  # noqa: BLE001
        _json_response(handler, {'text': '', 'error': f'{type(e).__name__}: {e}'})


def handle_tts(handler, body: bytes) -> None:
    """POST /api/voice/tts — 텍스트를 넘기고 WAV 를 돌려받는다."""
    try:
        raw, ct = _post('/tts', body, 'application/json', timeout=120)
    except Exception as e:                                  # noqa: BLE001
        _json_response(handler, {'error': f'{type(e).__name__}: {e}'}, 502)
        return
    handler.send_response(200)
    handler.send_header('Content-Type', ct or 'audio/wav')
    handler.send_header('Content-Length', str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def shutdown_sidecar() -> None:
    """앱이 내려갈 때 사이드카도 같이 내린다.

    [🔴 왜 필요한가] 이 프로세스는 콘솔이 없어 사람 눈에 안 보인다. 안 내리면 모델을
      물고 남아 다음 기동에서 포트 충돌이 나고, 사용자는 원인을 찾을 방법이 없다.
    """
    global _proc, _log_fp
    try:
        urllib.request.urlopen(f'{BASE_URL}/shutdown', data=b'{}', timeout=2).read()
    except Exception:                                       # noqa: BLE001
        pass
    _proc = None
    try:
        if _log_fp and not _log_fp.closed:
            _log_fp.close()
    except OSError:
        pass
    _log_fp = None
