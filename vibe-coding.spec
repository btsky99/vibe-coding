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
    ],
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
    ] + _fastembed_datas,
    # hive_hook이 사용하는 stdlib 모듈: server.py가 직접 import 하지 않는 것까지 명시 보강
    # (런타임 동적 import는 PyInstaller 정적 분석에서 누락 가능 → hook EXE 모드에서 ImportError 위험)
    # fastembed/onnxruntime/tokenizers: embed_service가 함수 내부 import — 회상 v2 필수
    # [A안] boot.py 진입 시 server.py 자동탐색이 끊기므로 frozen 클로저를 명시 보강.
    #   boot.py의 `if False:` 블록과 중복이지만 belt+suspenders로 양쪽 유지.
    #   PySide6/textual은 의도적 제외(dashboard/TUI는 별도 python 서브프로세스 전용).
    hiddenimports=['websockets', 'winpty', 'urllib.request', 'runpy',
                   'fastembed', 'onnxruntime', 'tokenizers', 'updater', 'soft_updater',
                   'webview', 'clr', 'psycopg2', 'watchdog', 'dotenv', 'rich', 'telegram',
                   'win32com', 'win32api', 'win32con', 'pythoncom', 'numpy', 'filelock', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
