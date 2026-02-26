# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[('C:\\Users\\com\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\winpty/winpty.dll', 'winpty'), ('C:\\Users\\com\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\winpty/winpty-agent.exe', 'winpty'), ('C:\\Users\\com\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\winpty/conpty.dll', 'winpty'), ('C:\\Users\\com\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\winpty/OpenConsole.exe', 'winpty')],
    datas=[
        ('src', 'src'),
        ('bin', 'bin'),
        ('vibe-view/dist', 'dist'),
        ('../.gemini/skills', '.gemini/skills'),
        ('../skills/claude', 'skills/claude'),
        ('../GEMINI.md', '.'),
        ('../CLAUDE.md', '.'),
        ('../RULES.md', '.'),
        ('../scripts', 'scripts'),
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
    icon=['bin\\vibe_final.ico'],
)
