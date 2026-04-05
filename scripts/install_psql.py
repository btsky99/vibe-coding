"""
FILE: scripts/install_psql.py
DESCRIPTION: PostgreSQL CLI(psql) PATH 등록 스크립트.
             이 프로젝트는 포터블 PostgreSQL 18을 내장하고 있으므로
             별도 설치 없이 내장 psql.exe를 시스템 PATH에 등록한다.
             시스템 PATH에 없으면 사용자 환경변수 PATH에 추가.

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — 내장 PostgreSQL psql PATH 자동 등록
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path


def _find_psql() -> Path | None:
    """내장 또는 시스템 PostgreSQL에서 psql.exe 경로를 찾는다.

    Why: 이 프로젝트는 .ai_monitor/bin/pgsql/에 포터블 PG 18을 내장하므로
    별도 설치 없이 해당 경로의 psql을 활용할 수 있다.
    """
    # 프로젝트 내장 PostgreSQL 우선
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe",
        project_root / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql",
    ]

    # 시스템 PostgreSQL 폴백
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    for ver in ["18", "17", "16", "15"]:
        candidates.append(Path(program_files) / "PostgreSQL" / ver / "bin" / "psql.exe")

    for path in candidates:
        if path.exists():
            return path

    return None


def _is_in_path(dir_path: str) -> bool:
    """주어진 디렉토리가 현재 PATH에 포함되어 있는지 확인."""
    current_path = os.environ.get("PATH", "")
    normalized = dir_path.replace("/", "\\").rstrip("\\").lower()
    for entry in current_path.split(os.pathsep):
        if entry.replace("/", "\\").rstrip("\\").lower() == normalized:
            return True
    return False


def _add_to_user_path(dir_path: str) -> bool:
    """Windows 사용자 환경변수 PATH에 디렉토리를 영구 추가.

    Why: 시스템 PATH는 관리자 권한이 필요하므로, 사용자 PATH에 추가하여
    권한 문제 없이 psql을 어디서든 사용할 수 있게 한다.
    """
    try:
        # 사용자 환경변수 레지스트리 열기
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )

        try:
            current_value, reg_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current_value = ""
            reg_type = winreg.REG_EXPAND_SZ

        # 이미 포함되어 있는지 확인
        normalized = dir_path.replace("/", "\\").rstrip("\\").lower()
        existing_entries = [e.replace("/", "\\").rstrip("\\").lower() for e in current_value.split(";")]
        if normalized in existing_entries:
            print(f"[psql] 이미 사용자 PATH에 등록됨: {dir_path}")
            winreg.CloseKey(key)
            return True

        # PATH에 추가
        new_value = current_value.rstrip(";") + ";" + dir_path if current_value else dir_path
        winreg.SetValueEx(key, "Path", 0, reg_type, new_value)
        winreg.CloseKey(key)

        # 현재 프로세스의 PATH에도 즉시 반영
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + dir_path

        # 다른 프로세스에 환경변수 변경 알림 (WM_SETTINGCHANGE)
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                "Environment", SMTO_ABORTIFHUNG, 5000, ctypes.byref(ctypes.c_ulong())
            )
        except Exception:
            pass  # 알림 실패해도 레지스트리 등록은 완료됨

        print(f"[psql] 사용자 PATH에 추가 완료: {dir_path}")
        return True

    except Exception as e:
        print(f"[오류] PATH 등록 실패: {e}")
        return False


def verify_psql(psql_path: Path) -> str | None:
    """psql 실행 가능 여부를 검증하고 버전 반환."""
    try:
        result = subprocess.run(
            [str(psql_path), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def main() -> None:
    print("=" * 50)
    print("  PostgreSQL CLI (psql) 설치 스크립트")
    print("=" * 50)

    # 1단계: PATH에서 이미 사용 가능한지 확인
    if shutil.which("psql"):
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True)
        print(f"[정보] psql이 이미 PATH에 있습니다: {result.stdout.strip()}")
        print("[완료] 추가 설정이 필요 없습니다.")
        return

    # 2단계: 내장/시스템 psql 검색
    psql_path = _find_psql()
    if not psql_path:
        print("[오류] psql.exe를 찾을 수 없습니다.")
        print("  이 프로젝트의 내장 PostgreSQL이 설치되지 않았을 수 있습니다.")
        print("  수동 다운로드: https://www.postgresql.org/download/")
        sys.exit(1)

    # 3단계: 검증
    version = verify_psql(psql_path)
    if not version:
        print(f"[오류] psql 실행 실패: {psql_path}")
        sys.exit(1)

    print(f"[발견] {version}")
    print(f"       경로: {psql_path}")

    psql_dir = str(psql_path.parent)

    # 4단계: PATH에 이미 있는지 확인
    if _is_in_path(psql_dir):
        print(f"[정보] {psql_dir}이(가) 이미 PATH에 있습니다.")
        print("[완료] psql을 사용할 수 있습니다.")
        return

    # 5단계: 사용자 PATH에 영구 등록
    print(f"\n[설정] 사용자 PATH에 등록 중: {psql_dir}")
    if _add_to_user_path(psql_dir):
        # 최종 검증
        print(f"\n[검증] psql 접근 테스트...")
        test_result = subprocess.run(
            [str(psql_path), "--version"],
            capture_output=True, text=True,
        )
        if test_result.returncode == 0:
            print(f"[성공] {test_result.stdout.strip()}")
            print(f"\n[완료] psql이 PATH에 등록되었습니다.")
            print(f"  새 터미널에서 'psql --version'으로 확인하세요.")
            print(f"  접속 예시: psql -h 127.0.0.1 -p 5433 -U postgres")
        else:
            print("[주의] PATH 등록은 완료되었지만 새 터미널에서 확인 필요합니다.")
    else:
        print(f"\n[실패] PATH 등록에 실패했습니다.")
        print(f"  수동으로 추가하세요: {psql_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
