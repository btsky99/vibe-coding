# -*- mode: python ; coding: utf-8 -*-
import os
import winpty

winpty_dir = os.path.dirname(winpty.__file__)
winpty_binaries = [
    (os.path.join(winpty_dir, 'winpty.dll'), 'winpty'),
    (os.path.join(winpty_dir, 'winpty-agent.exe'), 'winpty'),
    (os.path.join(winpty_dir, 'conpty.dll'), 'winpty'),
    (os.path.join(winpty_dir, 'OpenConsole.exe'), 'winpty'),
]

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=winpty_binaries,
    # [2026-03-24] 배포 범용화: 개발 전용 파일 제거
    # 제거됨: .gemini/skills, GEMINI.md, CLAUDE.md, RULES.md, PROJECT_MAP.md, scripts
    # 설치 버전은 대시보드 GUI + 터미널 + PostgreSQL만 포함
    datas=[
        ('src', 'src'),
        ('bin', 'bin'),
        ('vibe-view/dist', 'vibe-view/dist'),
        ('api', 'api'),
        ('pty-server', 'pty-server'),
    ],
    # [2026-03-24] chromadb, pysqlite3 제거 (미사용)
    hiddenimports=['websockets', 'winpty', 'psycopg2'],
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
    # [v3.7.65 버그수정] runtime_tmpdir=None → %TEMP% 사용 → Windows/백신이 _MEI* 폴더 삭제
    # → "Failed to load Python DLL" 오류 발생. APPDATA 고정 경로로 변경하면
    # 시스템 Temp 청소에도 영향받지 않음.
    runtime_tmpdir='%APPDATA%\\VibeCoding\\runtime',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['bin\\vibe_final.ico'],
)
