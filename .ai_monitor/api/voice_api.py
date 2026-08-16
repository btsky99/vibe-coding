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


def _sidecar_python(project_root: Path) -> str | None:
    """사이드카를 실행할 파이썬.

    [개발] 별도 환경(.ai_monitor/voice-server/.venv)을 쓴다. 앱 venv 와 섞지 않는 편이
      의존성 다툼이 없고, 음성을 안 쓰는 개발자는 아예 안 깔아도 된다.
    [🔴 설치본에는 그 .venv 가 없다 — 2026-08-16 사고] 그 환경을 만들어 주는 것은
      scripts/setup_voice.py 인데 **설치·최초실행 어디에서도 그걸 부르지 않았다.**
      그래서 설치본에서는 사이드카가 영영 못 떠서 마이크도 목소리 목록도 조용히 죽었다
      (단추는 눌리는데 전송이 안 되고, edge-tts 목소리가 안 보이는 증상).
      이제 frozen 이면 **앱 EXE 자신을 실행기로 쓴다** — boot.main() 이 첫 인자가 .py 면
      runpy 로 받아 주고(무한 창 생성 없음), 음성 패키지는 번들에 동봉돼 있다
      (requirements.txt 의 edge-tts/faster-whisper ↔ spec hiddenimports 와 한 쌍).
    [불변식] 이 폴백은 frozen 전용이다. 개발에서 앱 venv 를 실행기로 내주면 음성 패키지가
      없는 환경에서 사이드카가 ImportError 로 죽으며, 그 실패가 별도 프로세스라 조용하다.
    """
    candidates = [
        os.environ.get('VOICE_PYTHON', ''),
        str(project_root / '.ai_monitor' / 'voice-server' / '.venv' / 'Scripts' / 'python.exe'),
        str(project_root / '.ai_monitor' / 'voice-server' / '.venv' / 'bin' / 'python'),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    if getattr(sys, 'frozen', False):
        return sys.executable
    return None


def _spawn_sidecar(project_root: Path) -> str:
    """사이드카를 띄운다. 이미 살아 있으면 아무것도 하지 않는다."""
    global _proc
    with _spawn_lock:
        if _proc is not None and _proc.poll() is None:
            return ''
        py = _sidecar_python(project_root)
        if not py:
            return '음성 스택이 설치되지 않았습니다(voice-server/.venv 없음)'
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


def handle_status(handler, project_root: Path) -> None:
    """GET /api/voice/status — 사이드카가 준비됐는가. 없으면 기동을 시작한다."""
    try:
        _json_response(handler, _get('/status'))
        return
    except (urllib.error.URLError, OSError, ValueError):
        pass                                                # 아직 안 떠 있다 — 아래에서 띄운다

    err = _spawn_sidecar(project_root)
    _json_response(handler, {
        'ready': False,
        'loading': not err,
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
