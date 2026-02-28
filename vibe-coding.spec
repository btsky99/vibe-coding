# -*- mode: python ; coding: utf-8 -*-
# ────────────────────────────────────────────────────────────────────────────
# 📦 파일명: vibe-coding.spec
# 📝 설명: PyInstaller 패키징 스펙.
#          server.py를 진입점으로 하는 단일 EXE를 생성합니다.
#
# 🕒 변경 이력:
# [2026-03-01] Claude — datas 보강: scripts/, src/, skills/claude/, .gemini/skills/
#   - 배포 버전에서 스킬 설치/인식 실패 버그 수정
#   - scripts/ 없으면 SCRIPTS_DIR 참조 실패 → 워치독/memory.py/hive_bridge 미동작
#   - skills/claude/ 없으면 /api/superpowers/install Claude 설치 불가
#   - .gemini/skills/ 없으면 /api/superpowers/install Gemini 설치 불가
#   - src/ 없으면 db_helper, db, logger import 실패
# ────────────────────────────────────────────────────────────────────────────

a = Analysis(
    ['.ai_monitor\\server.py'],
    pathex=[],
    binaries=[],
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
        ('skills/claude', 'skills/claude'),
        # Gemini 스킬 템플릿 파일 (SKILL.md 디렉터리 구조 유지)
        # → /api/superpowers/install 시 현재 프로젝트 .gemini/skills/ 에 복사
        ('.gemini/skills', '.gemini/skills'),
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
    name='vibe-coding',
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
