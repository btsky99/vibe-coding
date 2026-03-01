"""
Auto-update module for vibe-coding.exe.
Checks GitHub Releases API and performs self-update on Windows.
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
    """릴리스 에셋에서 포터블 exe(설치 불필요) URL을 찾습니다.
    GitHub 릴리스 에셋명 패턴: vibe-coding-v3.6.x.exe (setup 제외)
    browser_download_url 사용 → Public 리포에서 인증 없이 직접 다운로드 가능.
    """
    assets = release.get("assets", [])

    # 1순위: 정확히 ASSET_NAME과 일치하는 것 (하위 호환)
    for asset in assets:
        name = asset.get("name", "")
        if name == ASSET_NAME:
            return asset.get("browser_download_url") or asset.get("url")

    # 2순위: vibe-coding-v*.exe 패턴 (setup 제외)
    for asset in assets:
        name = asset.get("name", "")
        if (
            name.startswith("vibe-coding-v")
            and name.endswith(".exe")
            and "setup" not in name.lower()
        ):
            logger.info("에셋 발견: %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    # 3순위: vibe-coding*.exe 중 setup 아닌 것
    for asset in assets:
        name = asset.get("name", "")
        if (
            name.startswith("vibe-coding")
            and name.endswith(".exe")
            and "setup" not in name.lower()
        ):
            logger.info("에셋 발견(3순위): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    return None


def _download_asset(url, dest, token):
    """릴리스 에셋을 dest 경로에 다운로드합니다.
    browser_download_url은 Public 리포에서 인증 없이 직접 다운로드 가능.
    API URL(api.github.com)인 경우 Accept: application/octet-stream 추가.
    """
    req = Request(url)
    req.add_header("User-Agent", "vibe-coding-updater")
    # API URL인 경우에만 octet-stream 헤더 필요
    if "api.github.com" in url:
        req.add_header("Accept", "application/octet-stream")
        if token:
            req.add_header("Authorization", f"token {token}")
    try:
        with urlopen(req, timeout=120) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
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

    # Step 1: 이전 .old 파일이 있으면 먼저 정리
    if old_path.exists():
        try:
            old_path.unlink()
        except OSError as e:
            logger.warning(".old 파일 삭제 실패 (배치 스크립트에서 정리 예정): %s", e)

    # Step 1: 실행 중인 exe → .old 로 이름 변경 (Windows는 실행 중 이름 변경 허용)
    os.rename(exe_path, old_path)
    logger.info("exe 이름 변경 완료: %s → %s", exe_path, old_path)

    # Step 2: 새 exe를 원래 위치로 이동
    shutil.move(str(new_exe), str(exe_path))
    logger.info("새 exe 배치 완료: %s", exe_path)

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


def check_and_update(data_dir):
    """
    Main entry point. Called from a background thread.
    Checks for updates, downloads if available, and applies.
    """
    # 체크 시작 상태 기록
    with open(data_dir / "update_ready.json", "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True}, f)

    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping update check.")
        try: (data_dir / "update_ready.json").unlink()
        except: pass
        return

    if not getattr(sys, "frozen", False):
        logger.info("Not running as frozen exe, skipping update check.")
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

    # Download to a temp file in the same directory (same filesystem for rename)
    exe_dir = Path(sys.executable).resolve().parent
    tmp_path = exe_dir / "vibe-coding.exe.new"

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
