# -*- mode: python ; coding: utf-8 -*-
# ────────────────────────────────────────────────────────────────────────────
# 📦 파일명: vibe-coding.spec
# 📝 설명: PyInstaller 패키징 스펙.
#          server.py를 진입점으로 하는 단일 EXE를 생성합니다.
#          출력 파일명: vibe-coding-vX.Y.Z.exe (버전 자동 포함)
#
# 🕒 변경 이력:
# [2026-06-10] Claude — 자가 치유 2.0 ④: fastembed/onnxruntime hiddenimports + 데이터 수집
#   - embed_service가 함수 내부에서 from fastembed import — 정적 분석 누락 대비 명시
#   - [과거사고 v3.7.215~218] spec ↔ CI(build-release.yml) 양쪽 동시 갱신 필수.
#     누락 시 EXE에서 모델 로드 실패 → 회상 v2 무음 비활성 (ILIKE 폴백이라 부팅은 됨)
# [2026-05-05] Claude — datas 보강: .ai_monitor/infra 추가
#   - Phase 2-3에서 infra/project_context.py 분리 후 spec 미반영 → frozen 모드에서
#     ModuleNotFoundError: No module named 'infra' 발생하여 EXE 부팅 실패
#   - server.py / pg_store.py / zettelkasten.py가 'from infra.xxx' import하므로 필수
# [2026-03-16] Claude — runtime_tmpdir 설정: None→%APPDATA%\VibeCoding\runtime
#   - None이면 Windows Temp에 추출 → 백신이 삭제하여 "Not Found" 에러 발생
#   - APPDATA 고정 경로로 변경하여 안정적 추출 보장
# [2026-03-01] Claude — EXE 파일명에 버전 자동 포함
#   - _version.py에서 버전 읽어 name='vibe-coding-vX.Y.Z'로 설정
#   - 이전 버전과 동시에 보관 가능 / 다운로드 시 버전 식별 용이
# [2026-03-01] Claude — datas 보강: scripts/, src/, skills/claude/, .gemini/skills/
#   - 배포 버전에서 스킬 설치/인식 실패 버그 수정
# [2026-03-11] Claude — binaries 보강: winpty-agent.exe, OpenConsole.exe 추가
#   - 이 파일들이 없으면 PtyProcess.spawn() 실패 → PTY Init Error → WS 즉시 닫힘
#   - winpty.dll/conpty.dll은 자동 감지되나 .exe 파일은 수동으로 포함해야 함
# [2026-03-08] Claude — datas 보강: .claude/commands/, AGENTS.md 추가
#   - .claude/commands/ 주석엔 있었지만 실제 datas에 누락되어 있던 버그 수정
#   - AGENTS.md(Codex 지침) 추가 — 다른 PC 설치 시 Codex 오케스트레이션 규칙 포함
# [2026-03-01] Claude — datas 보강: 루트 지침 파일(GEMINI.md, CLAUDE.md, RULES.md, PROJECT_MAP.md)
#   - 스킬 복구 시 이 파일들을 타겟 프로젝트에 복사할 수 있도록 번들에 포함
# ────────────────────────────────────────────────────────────────────────────

import re as _re
import sys as _sys
from pathlib import Path as _Path
import winpty as _winpty_mod

# fastembed 패키지 내 모델 레지스트리 JSON — 없으면 TextEmbedding() 생성 자체가 실패
# [WHY] 일반 hiddenimport는 .py만 수집 — 패키지 데이터는 collect_data_files 필수
from PyInstaller.utils.hooks import collect_data_files as _collect_data_files
try:
    _fastembed_datas = _collect_data_files('fastembed')
except Exception:
    _fastembed_datas = []  # fastembed 미설치 빌드 환경 — 회상 v2 없이 빌드 (폴백 동작)

# 음성 스택(av/ctranslate2)의 네이티브 바이너리 수집.
# [WHY collect_dynamic_libs 인가 — 2026-08-16] 이 둘은 순수 파이썬이 아니라 .pyd 옆에
#   .dll 을 끼고 산다(av 는 FFmpeg, ctranslate2 는 자체 런타임). hiddenimport 는 .py 만
#   챙기므로 dll 이 빠지고, 그러면 frozen 에서 `import av` 가 ImportError 로 떨어진다.
#   그 실패는 사이드카 안에서 나므로 **앱은 멀쩡하고 음성만 조용히 죽는** 형태가 된다 —
#   이번 사고와 똑같은 모양이라 여기서 확실히 막는다.
# [폴백] 미설치 빌드 환경에서도 빌드는 계속된다(음성 없는 EXE). 음성은 선택 기능이고
#   빌드 자체를 세우면 릴리즈 파이프라인 전체가 멈춘다.
from PyInstaller.utils.hooks import collect_dynamic_libs as _collect_dynamic_libs
_voice_binaries = []
# [🔴 여기는 반드시 리스트 — CI 차단 실측 2026-08-16] scripts/build_verify.py 는 이 spec 을
#   **텍스트 정규식**으로 훑어, 따옴표 문자열 두 개를 괄호로 묶은 꼴이면 무엇이든 datas
#   항목(앞=소스경로, 뒤=대상경로)으로 간주한다. 그래서 패키지 이름 두 개를 괄호로 묶으면
#   "spec datas 경로 없음: av" 로 판정해 빌드가 Phase 2 게이트에서 멈춘다.
#   대괄호는 그 패턴에 안 걸린다. **이 주석에도 그 꼴을 적지 말 것** — 주석까지 훑는다.
# [🔴 조용히 넘어가지 않는다 — 2026-08-16 사고의 교훈] 음성 스택이 빌드 인터프리터에
#   없으면 hiddenimports 가 조용히 무시되고 **앱은 멀쩡하되 음성만 죽은 설치본**이 그대로
#   출고된다. 사장이 겪은 것이 정확히 그것이고 발견까지 3주가 걸렸다. 빌드를 세우는 쪽이
#   훨씬 싸다.
# [🔴 판정 기준은 '임포트 가능한가'다] collect_dynamic_libs 의 결과 개수로 판정하면 안 된다 —
#   av 는 PyInstaller 기본 훅이 dll 을 챙기므로 정상인데도 0 개를 돌려준다(실측).
#   그걸 실패로 보면 멀쩡한 빌드를 세운다.
import importlib.util as _ilu
_missing = [m for m in ['edge_tts', 'faster_whisper', 'ctranslate2', 'av']
            if _ilu.find_spec(m) is None]
if _missing:
    raise SystemExit(
        '[spec] 중단: 음성 스택이 빌드 파이썬에 없다 -> ' + ', '.join(_missing) + '\n'
        '        이대로 구우면 앱은 뜨는데 마이크와 목소리만 죽은 설치본이 나간다.\n'
        '        해결: pip install -r .ai_monitor/requirements.txt 를 **pyinstaller 가 쓰는\n'
        '        바로 그 파이썬**에 실행할 것. venv 와 다를 수 있다(실제로 그래서 한 번 헛빌드했다).')

for _vpkg in ['av', 'ctranslate2']:
    try:
        _voice_binaries += _collect_dynamic_libs(_vpkg)
    except Exception:
        pass                       # 훅이 이미 챙기는 패키지는 0 개가 정상 — 위에서 걸렀다

# faster-whisper 패키지 데이터(silero VAD 모델 .onnx).
# [🔴 실측 2026-08-16] 이게 빠지면 STT 가 **로딩까지는 성공**하고(stt=True) 받아쓰기
#   요청에서만 터진다: NoSuchFile ... faster_whisper/assets/silero_vad_v6.onnx.
#   transcribe(vad_filter=True) 가 앞뒤 무음을 자를 때 쓰는 모델이다. 화면에는 빈 문자열이
#   돌아가 '말했는데 아무 글자도 안 나옴'으로 보인다 — fastembed 와 같은 함정
#   (hiddenimport 는 .py 만 수집한다).
try:
    _voice_datas = _collect_data_files('faster_whisper')
except Exception:
    _voice_datas = []

# winpty 실행 파일 경로 (winpty-agent.exe, OpenConsole.exe)
# 이 파일들이 EXE 번들에 없으면 PtyProcess.spawn() 실패 → PTY 터미널 불가
_winpty_dir = _Path(_winpty_mod.__file__).parent

# _version.py에서 버전 자동 읽기 — EXE 파일명에 포함
with open('.ai_monitor/_version.py', 'r', encoding='utf-8') as _vf:
    _ver_content = _vf.read()
_ver_match = _re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _ver_content)
_APP_VERSION = _ver_match.group(1) if _ver_match else '0.0.0'
_EXE_NAME = f'vibe-coding-v{_APP_VERSION}'

print(f'[spec] 빌드 버전: {_APP_VERSION}  →  {_EXE_NAME}.exe')

# [경량 소스 업데이트 채널 A안 — 2026-06-24] 진입점을 server.py → boot.py로 전환.
#   boot.py가 앱 .py를 frozen 대신 관리형 git 체크아웃에서 runpy 실행한다.
#   [필수동기] boot.py의 `if False:` 의존성 노출 블록 ↔ 아래 hiddenimports ↔ build-release.yml --hidden-import.
#   [검증불가 경고] 이 전환은 PyInstaller 빌드로만 검증 가능 — CI(workflow_dispatch) 또는 로컬 빌드로
#   생성 EXE가 정상 부팅(SRC clone/seed + 데몬 + UI)하는지 확인 후에 사용자 배포할 것.
a = Analysis(
    ['.ai_monitor\\boot.py'],
    pathex=['.ai_monitor'],
    binaries=[
        # winpty 실행 파일 — PtyProcess.spawn()이 내부적으로 이 파일들을 필요로 함
        # winpty.dll/conpty.dll은 PyInstaller가 자동 감지하나 .exe는 수동 포함 필수
        # 'winpty' 서브디렉터리에 배치: server.py가 os.add_dll_directory(BASE_DIR/'winpty') 호출함
        (str(_winpty_dir / 'winpty-agent.exe'), 'winpty'),
        (str(_winpty_dir / 'OpenConsole.exe'), 'winpty'),
        (str(_winpty_dir / 'winpty.dll'), 'winpty'),
        (str(_winpty_dir / 'conpty.dll'), 'winpty'),
    ] + _voice_binaries,
    datas=[
        # 프론트엔드 빌드 결과물 (React/Vite) — vite 기본 outDir = vibe-view/dist
        ('.ai_monitor/vibe-view/dist', 'vibe-view/dist'),
        # [2026-07-09 드리프트 수정] Node PTY 서버 — CI(build-release.yml)는 --add-data "pty-server;pty-server"로
        #   담는데 spec엔 빠져 있었다(spec↔CI 불일치). onedir 전환(Phase C2)에서 CI가 spec을 쓰게 되면
        #   이게 없으면 설치본 터미널 불능 → 반드시 포함. node_modules 포함(런타임 필수).
        ('.ai_monitor/pty-server', 'pty-server'),
        # 서버 보조 스크립트 (워치독, 브릿지, 메모리, 오케스트레이터 등)
        # → 배포 버전 SCRIPTS_DIR = sys._MEIPASS/scripts
        ('scripts', 'scripts'),
        # 내부 Python 모듈 (db_helper, db, logger, secure)
        # [2026-07-18] view.py(textual TUI) 은퇴 제거 — sessions.jsonl 유일 reader였고
        #   라이브 대시보드는 dashboard_window.py(PySide6). 디렉토리 통째 번들이라 datas 무변경.
        ('.ai_monitor/src', 'src'),
        # Claude 스킬 템플릿 파일 (vibe-*.md)
        # → /api/superpowers/install 시 현재 프로젝트 .claude/skills/ 에 복사
        # [2026-03-15] .claude/commands → .claude/skills 로 경로 변경 (Skills 2.0 마이그레이션)
        ('.claude/skills', '.claude/skills'),
        # Gemini 스킬 템플릿 파일 (SKILL.md 디렉터리 구조 유지)
        # → /api/superpowers/install 시 현재 프로젝트 .gemini/skills/ 에 복사
        ('.gemini/skills', '.gemini/skills'),
        # 루트 지침 파일 — 스킬 복구(/api/install-skills) 시 타겟 프로젝트에 복사
        # 배포 버전에서 이 파일들이 없으면 하이브 진단 빨간불 발생하므로 번들에 포함
        ('GEMINI.md', '.'),
        ('CLAUDE.md', '.'),
        ('RULES.md', '.'),
        ('PROJECT_MAP.md', '.'),
        # Codex 지침 파일 — 다른 PC에서 Codex가 하이브 오케스트레이션 규칙을 인식하도록 포함
        ('AGENTS.md', '.'),
        # API 모듈 (hive_api, git_api 등)
        ('.ai_monitor/api', 'api'),
        # 인프라 모듈 (project_context, postgres_runtime, lifecycle 등)
        # → server.py / src/pg_store.py / src/zettelkasten.py에서 'from infra.xxx' import
        # 누락 시 frozen 모드에서 ModuleNotFoundError: No module named 'infra' 발생
        ('.ai_monitor/infra', 'infra'),
        # 버전 정보 파일 — frozen 모드에서 server.py가 MEIPASS 루트에서 import함
        # 없으면 ImportError → __version__ = "0.0.0-unknown" → 상단 버전 미표시
        ('.ai_monitor/_version.py', '.'),
        # [과거사고 v3.7.~240] updater.py 누락 → frozen에서 `from updater import` ImportError →
        # 자동 업데이트(시작 루프 4053 + 수동 트리거 2016) 전부 조용히 무력화 = "업데이트 안 뜸".
        # api/src/infra/_version과 동일하게 MEIPASS 루트에 소스를 실어야 sys.path(=MEIPASS) import 성공.
        ('.ai_monitor/updater.py', '.'),
        # [필수] lan_bridge.py는 daemons.run_lan_bridge가 subprocess로 실행하는 스크립트 —
        #   import 그래프에 없어 PyInstaller 정적분석이 못 잡는다. 개별 datas로 실어야
        #   frozen에서 base_dir/lan_bridge.py 실행 가능(누락 시 브리지 조용히 미기동).
        #   [동기] build-release.yml --add-data "lan_bridge.py;." 도 함께 갱신.
        ('.ai_monitor/lan_bridge.py', '.'),
        # [A안 seed] boot.py가 (a)오프라인 최초부팅 시 SRC로 복사, (b)min_exe 게이트 실패 시
        #   in-place 실행, (c)`hook` 빠른경로 실행에 쓰는 앱 .py 스냅샷. 리포 레이아웃(.ai_monitor/...)
        #   을 그대로 재현해야 boot가 유효한 체크아웃으로 인식한다. dist/binaries는 MEIPASS 루트에서
        #   BASE_DIR로 접근하므로 seed에 불포함(순수 .py만 — soft 채널 범위와 일치).
        ('.ai_monitor/server.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/lan_bridge.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/soft_updater.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/boot.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/updater.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/_version.py', '_appseed/.ai_monitor'),
        ('.ai_monitor/api', '_appseed/.ai_monitor/api'),
        ('.ai_monitor/src', '_appseed/.ai_monitor/src'),
        ('.ai_monitor/infra', '_appseed/.ai_monitor/infra'),
        ('scripts', '_appseed/scripts'),
        ('soft_manifest.json', '_appseed'),
        # min_exe 게이트 비교 기준(현재 EXE 버전)을 boot/soft_updater가 읽는 위치.
        ('soft_manifest.json', '.'),
        # [음성 사이드카 — 2026-08-16 사고 수정] voice_server.py 는 subprocess 로 띄우는
        #   스크립트라 import 그래프에 없다(lan_bridge.py 와 같은 부류) → 개별 datas 필수.
        # [🔴 .venv / cache / models 를 통째로 싣지 말 것] 하위 폴더를 통으로 지정하면
        #   개발 PC 의 .venv(246MB)까지 딸려 들어가는데, venv 의 python.exe 는 pyvenv.cfg 가
        #   가리키는 원본 파이썬이 있어야 도는 물건이라 다른 PC 에서 쓸모가 없다.
        #   그래서 **소스만** 싣고, 실행기는 앱 EXE 자신을 쓴다(api/voice_api._sidecar_python).
        ('.ai_monitor/voice-server/voice_server.py', 'voice-server'),
        ('.ai_monitor/voice-server/engines', 'voice-server/engines'),
        ('.ai_monitor/voice-server/requirements.txt', 'voice-server'),
        # seed 에도 같이 — min_exe 게이트 실패나 오프라인 최초부팅에서 seed 로 도는데,
        # 거기 음성이 없으면 그 경로에서만 또 조용히 죽는다.
        ('.ai_monitor/voice-server/voice_server.py', '_appseed/.ai_monitor/voice-server'),
        ('.ai_monitor/voice-server/engines', '_appseed/.ai_monitor/voice-server/engines'),
        # [🔴 사장님 목소리 살림 — 2026-08-17] 일꾼·그래프·참조·참조원문 네 개. 다 합쳐
        #   620KB 라 싣는다. 모델(2.4GB)과 CUDA 토치(~3GB)는 깃허브 릴리즈가 파일당 2GB
        #   한도라 못 싣는다 → 첫 실행 때 받는다(scripts/setup_qwen.py 헤더).
        # [🔴 폴더를 통째로 지정하면 안 된다] 개발 PC 의 qwen/.venv 와 qwen/models(수 GB)가
        #   딸려 들어간다. 위 voice-server 주석과 같은 사고다 — **파일을 하나씩** 적는다.
        # [🔴 참조가 빠지면 목소리가 달라진다] boss_pick.wav 와 ref_text.json 은 소리의
        #   정체 그 자체다. 모델만 받아 오고 이 둘이 없으면 남의 목소리가 난다.
        ('.ai_monitor/voice-server/qwen/worker.py', 'voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/qgraph.py', 'voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/ref_text.json', 'voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/boss_pick.wav', 'voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/worker.py', '_appseed/.ai_monitor/voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/qgraph.py', '_appseed/.ai_monitor/voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/ref_text.json', '_appseed/.ai_monitor/voice-server/qwen'),
        ('.ai_monitor/voice-server/qwen/boss_pick.wav', '_appseed/.ai_monitor/voice-server/qwen'),
    ] + _fastembed_datas + _voice_datas,
    # hive_hook이 사용하는 stdlib 모듈: server.py가 직접 import 하지 않는 것까지 명시 보강
    # (런타임 동적 import는 PyInstaller 정적 분석에서 누락 가능 → hook EXE 모드에서 ImportError 위험)
    # fastembed/onnxruntime/tokenizers: embed_service가 함수 내부 import — 회상 v2 필수
    # [A안] boot.py 진입 시 server.py 자동탐색이 끊기므로 frozen 클로저를 명시 보강.
    #   boot.py의 `if False:` 블록과 중복이지만 belt+suspenders로 양쪽 유지.
    #   PySide6/textual은 의도적 제외(dashboard/TUI는 별도 python 서브프로세스 전용).
    # [음성 2026-08-16] 아래 4개는 voice_server.py 가 **함수 안에서** import 한다(지연 로딩).
    #   PyInstaller 정적분석은 그걸 못 잡고, 사이드카는 별도 프로세스라 실패해도 앱은
    #   멀쩡하다 — 즉 빠뜨리면 '앱은 되는데 음성만 조용히 죽는' 형태가 된다.
    hiddenimports=['websockets', 'winpty', 'urllib.request', 'runpy',
                   'fastembed', 'onnxruntime', 'tokenizers', 'updater', 'soft_updater',
                   'webview', 'clr', 'psycopg2', 'watchdog', 'dotenv', 'rich',
                   'win32com', 'win32api', 'win32con', 'pythoncom', 'numpy', 'filelock', 'PIL',
                   'edge_tts', 'faster_whisper', 'ctranslate2', 'av', 'aiohttp',
                   'huggingface_hub'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # [2026-08-01] tkinter 제외 — 로컬 onedir 빌드가 pyi_rth__tkinter에서
    #   "Tcl data directory _tcl_data not found"로 기동조차 못 하던 문제 해소.
    #   [근거] 앱 코드는 tkinter를 **모듈 레벨에서 import하지 않는다**. 폴더 다이얼로그는
    #   infra/runtime.py가 별도 파이썬 프로세스로 실행한다(pywebview GUI 스레드에서
    #   tkinter를 직접 호출하면 충돌한다고 그 파일 주석에 명시). 즉 frozen 프로세스 안에서
    #   tkinter가 필요한 경로가 없다. 딸려온 경로는 hiddenimports의 PIL → PIL.ImageTk 뿐이고
    #   ImageTk/tqdm.tk 사용처는 코드베이스에 없음(검색 확인).
    #   [부수효과] Tcl/Tk 미포함으로 배포 용량이 줄어든다.
    #   [제약] CI(build-release.yml)는 spec이 아니라 --onefile 명령을 쓰므로 이 excludes가
    #   적용되지 않는다. CI 빌드는 현재 정상이라 그대로 두되, CI를 spec 기반으로 바꾸면
    #   여기 값도 함께 옮겨야 한다.
    excludes=['tkinter', '_tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# [2026-07-09 전략 #2a] onefile → onedir 전환.
#   [WHY] onefile은 매 부팅 전체를 runtime_tmpdir(\_MEI)에 추출하는데, 번들 내 node PTY 서버가
#     그 폴더를 잡은 채 오래 살아 → 좀비/DLL로드실패/temp정리실패 버그 클래스의 뿌리(v3.7.244~248).
#     onedir은 안정된 설치 폴더에서 그대로 실행 → 추출/_MEI/좀비가 구조적으로 불가능.
#   [불변식] onedir은 EXE(exclude_binaries=True) + COLLECT 조합. runtime_tmpdir 삭제(추출 없음).
#   [배포] 결과는 dist/<_EXE_NAME>/ 폴더 — 인스톨러(.iss)가 폴더 전체를 담아 배포(Phase C).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: 바이너리/데이터는 아래 COLLECT가 폴더로 수집
    name=_EXE_NAME,  # 예: vibe-coding-v3.6.5
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['.ai_monitor\\bin\\app_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=_EXE_NAME,  # 출력 폴더: dist/<_EXE_NAME>/
)
