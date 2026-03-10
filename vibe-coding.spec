# -*- mode: python ; coding: utf-8 -*-
# ────────────────────────────────────────────────────────────────────────────
# 📦 파일명: vibe-coding.spec
# 📝 설명: PyInstaller 패키징 스펙.
#          server.py를 진입점으로 하는 단일 EXE를 생성합니다.
#          출력 파일명: vibe-coding-vX.Y.Z.exe (버전 자동 포함)
#
# 🕒 변경 이력:
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

a = Analysis(
    ['.ai_monitor\\server.py'],
    pathex=[],
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
        # 프론트엔드 빌드 결과물 (React/Vite)
        ('.ai_monitor/vibe-view/dist', 'vibe-view/dist'),
        # 서버 보조 스크립트 (워치독, 브릿지, 메모리, 오케스트레이터 등)
        # → 배포 버전 SCRIPTS_DIR = sys._MEIPASS/scripts
        ('scripts', 'scripts'),
        # 내부 Python 모듈 (db_helper, db, logger, secure, view)
        ('.ai_monitor/src', 'src'),
        # Claude 스킬 템플릿 파일 (vibe-*.md)
        # → /api/superpowers/install 시 현재 프로젝트 .claude/commands/ 에 복사
        ('.claude/commands', '.claude/commands'),
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
    ],
    hiddenimports=['websockets', 'winpty'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=_EXE_NAME,  # 예: vibe-coding-v3.6.5
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['.ai_monitor\\bin\\app_icon.ico'],
)
