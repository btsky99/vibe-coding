"""
FILE: infra/cli_commands.py
DESCRIPTION: server.py 진입 시 CLI 인자(--install / --uninstall / --create-shortcut)
             처리 로직. 바탕화면 바로가기 생성/삭제와 설치 시 node-pty 네이티브 모듈
             빌드를 담당한다. server.py main() 최상단 nested 블록에서 top-level 함수로
             승격됨 — pty-server 경로 계산에 쓰던 __file__ 기준을 server_dir 인자로
             명시 주입받는다.

REVISION HISTORY:
- 2026-07-08 Claude: server.py main() L1676~1732 CLI 인자 처리 블록 분리 (Phase 3 R17).
                     로직·주석 verbatim 유지. [제약] server_dir는 반드시 caller(server.py)
                     기준 Path(__file__).resolve().parent를 주입 — 여기서 __file__로
                     계산하면 infra/ 경로가 되어 pty-server를 못 찾음.
                     create_shortcut은 .ai_monitor 최상위 모듈 → 패키지 상대(..) 우선,
                     실패 시 sys.path 절대 import로 폴백(개발/EXE 양쪽 호환).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def handle_cli_command(argv: list, server_dir: Path) -> bool:
    """--install / --uninstall / --create-shortcut 처리.

    처리한 명령이 있으면 True(→ caller는 즉시 return), CLI 명령이 없으면 False.
    server_dir: pty-server 하위 경로 계산 기준 (server.py의 __file__ 부모).
    """
    if len(argv) <= 1:
        return False

    cmd = argv[1]

    # --install: 바탕화면 바로가기 생성 + PTY 네이티브 모듈 빌드 (원스톱 설치)
    if cmd in ('--install', '--create-shortcut'):
        # PTY 서버 네이티브 모듈 빌드 (node-pty — 터미널 기능 핵심)
        # node -e "require('node-pty')"로 실제 로드 가능 여부 검증 후 필요시만 빌드
        if cmd == '--install':
            import shutil as _shutil
            pty_dir = server_dir / 'pty-server'
            _need_build = True
            _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            if (pty_dir / 'package.json').exists() and _shutil.which('node'):
                try:
                    chk = subprocess.run(['node', '-e', "require('node-pty')"],
                                         cwd=str(pty_dir), capture_output=True, timeout=10,
                                         creationflags=_no_win)
                    if chk.returncode == 0:
                        _need_build = False
                        print("[*] 터미널 네이티브 모듈 정상 확인!")
                except Exception:
                    pass

            if _need_build and (pty_dir / 'package.json').exists() and _shutil.which('npm'):
                print("[*] 터미널 네이티브 모듈 빌드 중... (1~2분 소요)")
                # shell=True: Windows에서 npm은 npm.cmd이므로 shell 경유 필요
                r = subprocess.run('npm install', cwd=str(pty_dir), shell=True,
                                   capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=300, creationflags=_no_win)
                if r.returncode == 0:
                    print("[*] 터미널 네이티브 모듈 빌드 완료!")
                else:
                    print(f"[!] npm install 실패: {r.stderr[:300]}")
            elif _need_build and not _shutil.which('npm'):
                print("[!] Node.js가 설치되지 않았습니다. 터미널 기능에 필요합니다.")
        try:
            from ..create_shortcut import create_shortcut
        except ImportError:
            from create_shortcut import create_shortcut
        create_shortcut()
        if cmd == '--install':
            print("\n✅ Vibe Coding 설치가 완료되었습니다!")
            print("   실행: vibe-coding")
            print("   제거: vibe-coding --uninstall")
        return True

    # --uninstall: 바탕화면 바로가기 삭제 + pip uninstall 안내
    if cmd == '--uninstall':
        try:
            from ..create_shortcut import remove_shortcut
        except ImportError:
            from create_shortcut import remove_shortcut
        remove_shortcut()
        print("\n🗑️  바로가기를 삭제했습니다.")
        print("   패키지 완전 제거: pip uninstall vibe-coding -y")
        return True

    return False
