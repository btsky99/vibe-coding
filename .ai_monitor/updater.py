"""
FILE: .ai_monitor/updater.py
DESCRIPTION: 자동 업데이트 모듈 — GitHub Releases API로 셀프 업데이트 수행 (Windows).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import json
import os
import sys
import subprocess
import logging
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from _version import __version__ as APP_VERSION

REPO = "btsky99/vibe-coding"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "vibe-coding.exe"

logger = logging.getLogger("updater")


def _get_token(data_dir):
    """GitHub 토큰 조회 — Public 리포이므로 토큰 없이도 동작.
    환경변수 또는 파일에 토큰이 있으면 사용 (rate limit 완화용).
    """
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    token_file = data_dir / "github_token.txt"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip().splitlines()[0]
    return None  # Public 리포 → 토큰 없이 API 호출 가능


def _fetch_latest_release(token):
    """Query GitHub API for the latest release. Returns parsed JSON or None."""
    req = Request(API_URL)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "vibe-coding-updater")
    if token:
        req.add_header("Authorization", f"token {token}")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError) as e:
        logger.warning("Update check failed: %s", e)
        return None


def _is_newer(latest_tag, current):
    """
    세마버(Semantic Versioning) 기준으로 버전을 비교합니다.
    형식: v3.4.1 또는 3.4.1 (v 접두사 무시)
    'dev' 빌드는 항상 업데이트 대상에서 제외합니다.
    """
    if current == "dev":
        return False  # 개발 빌드는 자동 업데이트 안 함

    def _parse(tag: str):
        """'v3.4.1' → (3, 4, 1) 형태의 정수 튜플로 변환"""
        clean = tag.lstrip("v").strip()
        parts = clean.split(".")
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(0)
        # 최소 3자리 보장
        while len(result) < 3:
            result.append(0)
        return tuple(result)

    try:
        return _parse(latest_tag) > _parse(current)
    except Exception:
        return False


def _find_asset_url(release):
    """릴리스 에셋에서 업데이트용 exe URL을 찾습니다.
    CI 빌드 에셋명: vibe-coding-update-X.Y.Z.exe (setup 제외)
    browser_download_url 사용 → Public 리포에서 인증 없이 직접 다운로드 가능.
    """
    assets = release.get("assets", [])

    # 1순위: vibe-coding-update-*.exe (현재 CI 표준 네이밍)
    for asset in assets:
        name = asset.get("name", "")
        if (
            name.startswith("vibe-coding-update-")
            and name.endswith(".exe")
        ):
            logger.info("에셋 발견(update): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    # 2순위: 정확히 ASSET_NAME(vibe-coding.exe)과 일치 (하위 호환)
    for asset in assets:
        name = asset.get("name", "")
        if name == ASSET_NAME:
            return asset.get("browser_download_url") or asset.get("url")

    # 3순위: vibe-coding-v*.exe 패턴 (구 네이밍 하위 호환, setup 제외)
    for asset in assets:
        name = asset.get("name", "")
        if (
            name.startswith("vibe-coding-v")
            and name.endswith(".exe")
            and "setup" not in name.lower()
        ):
            logger.info("에셋 발견(legacy): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    # 4순위: vibe-coding*.exe 중 setup/console 아닌 것 (최후 폴백)
    for asset in assets:
        name = asset.get("name", "")
        if (
            name.startswith("vibe-coding")
            and name.endswith(".exe")
            and "setup" not in name.lower()
            and "console" not in name.lower()
        ):
            logger.info("에셋 발견(fallback): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    logger.warning("업데이트 에셋 없음. 에셋 목록: %s", [a.get("name") for a in assets])
    return None


def _download_asset(url, dest, token):
    """릴리스 에셋을 dest 경로에 다운로드합니다.
    browser_download_url은 Public 리포에서 인증 없이 직접 다운로드 가능.
    API URL(api.github.com)인 경우 Accept: application/octet-stream 추가.
    """
    logger.info("다운로드 시작: %s → %s", url, dest)
    req = Request(url)
    req.add_header("User-Agent", "vibe-coding-updater")
    # API URL인 경우에만 octet-stream 헤더 필요
    if "api.github.com" in url:
        req.add_header("Accept", "application/octet-stream")
        if token:
            req.add_header("Authorization", f"token {token}")
    try:
        with urlopen(req, timeout=120) as resp:
            total = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
        # 다운로드 무결성 검증: EXE는 최소 1MB 이상이어야 정상
        if total < 1_000_000:
            logger.error("다운로드 파일 너무 작음 (%d bytes) — 손상 가능성", total)
            return False
        logger.info("다운로드 완료: %d bytes", total)
        return True
    except Exception as e:
        logger.error("Download failed: %s", e)
        return False


def apply_update_from_temp(new_exe):
    """현재 실행 중인 exe를 새 버전으로 교체하고 재시작합니다.

    Windows는 실행 중인 exe를 덮어쓸 수 없지만 이름 변경은 허용됩니다.
    전략:
      1. 실행 중인 exe를 .old로 이름 변경
      2. 다운로드된 새 exe를 원래 이름으로 이동
      3. 배치 스크립트를 생성하여:
         a. 현재 프로세스 종료 대기
         b. .old 파일 삭제
         c. 새 exe 실행
         d. 배치 스크립트 자기 삭제
      4. 현재 프로세스 종료
    """
    import shutil

    exe_path = Path(sys.executable).resolve()
    old_path = exe_path.with_suffix(".exe.old")

    logger.info("업데이트 적용 시작: %s → %s", new_exe, exe_path)
    logger.info("새 exe 크기: %d bytes", new_exe.stat().st_size if new_exe.exists() else -1)

    # Step 0: 새 exe 존재 여부 + 최소 크기 검증 (손상된 파일 방지)
    if not new_exe.exists():
        raise FileNotFoundError(f"새 exe 파일 없음: {new_exe}")
    if new_exe.stat().st_size < 1_000_000:
        raise ValueError(f"새 exe 파일 너무 작음 ({new_exe.stat().st_size} bytes) — 손상 의심")

    # Step 1: 이전 .old 파일이 있으면 먼저 정리
    if old_path.exists():
        try:
            old_path.unlink()
        except OSError as e:
            logger.warning(".old 파일 삭제 실패 (배치 스크립트에서 정리 예정): %s", e)

    # Step 2: 실행 중인 exe → .old 로 이름 변경 (Windows는 실행 중 이름 변경 허용)
    os.rename(exe_path, old_path)
    logger.info("exe 이름 변경 완료: %s → %s", exe_path, old_path)

    # Step 2: 새 exe를 원래 위치로 이동
    # rename 성공 후 move 실패 시 반드시 롤백하여 exe_path 복원 (앱 실행 불가 방지)
    try:
        shutil.move(str(new_exe), str(exe_path))
        logger.info("새 exe 배치 완료: %s", exe_path)
    except Exception as move_err:
        logger.error("새 exe 이동 실패 — 롤백 시작: %s", move_err)
        try:
            os.rename(old_path, exe_path)
            logger.info("롤백 완료: .old → %s", exe_path)
        except Exception as rb_err:
            logger.error("롤백 실패: %s", rb_err)
        raise RuntimeError(f"업데이트 이동 실패 (롤백 완료): {move_err}") from move_err

    # Step 3: 자기 삭제 배치 스크립트 작성
    # - 인코딩: mbcs (Windows ANSI) — 한국어 경로 포함 시에도 안전
    # - 경로는 큰따옴표로 감싸 공백 포함 경로 처리
    bat_path = exe_path.parent / "_update.bat"
    pid = os.getpid()
    bat_content = (
        "@echo off\n"
        ":wait\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n'
        "if not errorlevel 1 (\n"
        "    timeout /t 1 /nobreak >NUL\n"
        "    goto wait\n"
        ")\n"
        f'if exist "{old_path}" del /f /q "{old_path}"\n'
        # 이전 EXE 종료 후 PyInstaller 임시 폴더 정리 및 소켓 락 OS 해제 대기.
        # 즉시 재시작 시: _MEI임시폴더 충돌 → python311.dll 로드 실패 + 포트 충돌.
        "timeout /t 3 /nobreak >NUL\n"
        f'start "" "{exe_path}"\n'
        'del /f /q "%~f0"\n'
    )
    with open(bat_path, "w", encoding="mbcs", errors="replace") as f:
        f.write(bat_content)

    # Step 4: 배치 스크립트를 숨김 모드로 실행 후 현재 프로세스 종료
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=0x08000000,  # CREATE_NO_WINDOW
        close_fds=True,
    )
    logger.info("배치 스크립트 실행됨. 프로세스 종료 중...")
    # 배치 스크립트 시작 대기 후 종료
    time.sleep(0.8)
    os._exit(0)


def check_and_update_pip(data_dir):
    """pip install 모드용 자동 업데이트.
    GitHub API로 최신 태그 확인 → 새 버전이면 pip install --upgrade 실행.
    Claude Code / Gemini CLI처럼 실행 시 자동 업데이트 체크.
    """
    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping pip update check.")
        return

    # 체크 시작 상태 기록
    ready_file = data_dir / "update_ready.json"
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True, "pip_mode": True}, f)

    token = _get_token(data_dir)
    release = _fetch_latest_release(token)
    if release is None:
        try: ready_file.unlink()
        except: pass
        return

    latest_tag = release.get("tag_name", "")
    if not _is_newer(latest_tag, APP_VERSION):
        logger.info("Already up to date (%s).", APP_VERSION)
        try: ready_file.unlink()
        except: pass
        return

    logger.info("[pip] New version available: %s (current: %s)", latest_tag, APP_VERSION)

    # pip install --upgrade 실행 (백그라운드, 논블로킹)
    repo_url = f"git+https://github.com/{REPO}.git@{latest_tag}"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", repo_url],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            logger.info("[pip] 업데이트 완료: %s → %s. 재시작 시 적용됩니다.", APP_VERSION, latest_tag)
            with open(ready_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": latest_tag, "ready": True, "downloading": False,
                    "pip_mode": True, "message": f"v{latest_tag.lstrip('v')} 업데이트 완료. 재시작하면 적용됩니다."
                }, f)
        else:
            logger.warning("[pip] 업데이트 실패: %s", result.stderr[:500])
            try: ready_file.unlink()
            except: pass
    except Exception as e:
        logger.error("[pip] 업데이트 중 에러: %s", e)
        try: ready_file.unlink()
        except: pass


def check_and_update(data_dir):
    """
    Main entry point. Called from a background thread.
    Checks for updates, downloads if available, and applies.
    frozen(EXE) 모드: EXE 다운로드+교체, pip 모드: pip install --upgrade.
    """
    # pip 모드 분기 — frozen이 아니면 pip upgrade 방식 사용
    if not getattr(sys, "frozen", False):
        check_and_update_pip(data_dir)
        return

    # 체크 시작 상태 기록
    with open(data_dir / "update_ready.json", "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True}, f)

    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping update check.")
        try: (data_dir / "update_ready.json").unlink()
        except: pass
        return

    # Public 리포이므로 토큰 없이도 동작 (token=None 이어도 계속 진행)
    token = _get_token(data_dir)

    release = _fetch_latest_release(token)
    if release is None:
        try: (data_dir / "update_ready.json").unlink()
        except: pass
        return

    latest_tag = release.get("tag_name", "")
    if not _is_newer(latest_tag, APP_VERSION):
        logger.info("Already up to date (%s).", APP_VERSION)
        try: (data_dir / "update_ready.json").unlink()
        except: pass
        return

    logger.info("New version available: %s (current: %s)", latest_tag, APP_VERSION)

    asset_url = _find_asset_url(release)
    if not asset_url:
        logger.warning("Release %s has no %s asset.", latest_tag, ASSET_NAME)
        return

    # 즉시 "다운로드 중" 상태로 알림 — 다운로드 완료 전에도 UI에 표시
    update_info: dict = {"version": latest_tag, "ready": False, "downloading": True, "exe_path": ""}
    with open(data_dir / "update_ready.json", "w", encoding="utf-8") as f:
        json.dump(update_info, f)

    # [버그수정 2026-03-22] 다운로드 경로를 DATA_DIR(%APPDATA%\VibeCoding)로 변경.
    # 이전: exe_dir(설치 폴더, 예: C:\Program Files\VibeCoding)에 저장 시도
    # → Program Files 폴더는 관리자 권한 없이 쓰기 불가 → PermissionError 발생.
    # DATA_DIR은 사용자 폴더이므로 항상 쓰기 가능.
    tmp_path = data_dir / "vibe-coding.exe.new"

    if not _download_asset(asset_url, tmp_path, token):
        if tmp_path.exists():
            tmp_path.unlink()
        # 다운로드 실패 시 알림 파일 제거
        try:
            (data_dir / "update_ready.json").unlink()
        except OSError:
            pass
        return

    logger.info("Download complete. Waiting for user to apply update...")
    update_info = {"version": latest_tag, "ready": True, "downloading": False, "exe_path": str(tmp_path)}
    with open(data_dir / "update_ready.json", "w", encoding="utf-8") as f:
        json.dump(update_info, f)
