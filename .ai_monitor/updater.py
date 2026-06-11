"""
FILE: .ai_monitor/updater.py
DESCRIPTION: 자동 업데이트 모듈 — GitHub Releases API로 셀프 업데이트 수행 (Windows).
  서버 시작 시 백그라운드 스레드에서 최신 릴리즈 확인 후 EXE 다운로드.
  EXE 모드(frozen)에서만 자동 업데이트 실행, 개발 모드에서는 스킵.

REVISION HISTORY:
- 2026-03-26 Claude: EXE 업데이트 방식으로 복원 (pip 방식 폐기)
  → pip 배포 시 pythonnet/브라우저 폴백 등 호환성 문제 다수 발생하여 EXE로 회귀
  → import 경로는 pip/dev 양쪽 호환 유지
- 2026-03-25 Claude: EXE → pip upgrade 전용으로 전환 (실패 — 되돌림)
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import json
import os
import sys
import subprocess
import logging
import time
import shutil
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# 버전 로드: 패키지/개발/PyInstaller 빌드 환경 모두 대응
try:
    from ._version import __version__ as APP_VERSION
except ImportError:
    try:
        from _version import __version__ as APP_VERSION
    except ImportError:
        APP_VERSION = "0.0.0-unknown"

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
    return None


def _fetch_latest_release(token):
    """GitHub Releases API에서 최신 릴리즈 정보를 가져옵니다.

    [과거사고 2026-06-11] private 리포 시절 발급한 토큰이 설치 PC의
    github_token.txt / GITHUB_TOKEN에 남아 만료(401/403)되면 업데이트 감지가
    영구 무음 실패 → "설치 버전에서 업데이트가 안 뜸". 공개 리포는 토큰이
    필요 없으므로 인증 실패 시 반드시 토큰 없이 1회 재시도한다.
    """
    def _request(use_token):
        req = Request(API_URL)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "vibe-coding-updater")
        if use_token and token:
            req.add_header("Authorization", f"token {token}")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return _request(use_token=True)
    except HTTPError as e:
        if token and e.code in (401, 403):
            logger.warning("토큰 인증 실패(%s) — 만료/회수된 토큰 추정, 토큰 없이 재시도", e.code)
            try:
                return _request(use_token=False)
            except (URLError, HTTPError, TimeoutError) as e2:
                logger.warning("Update check failed (tokenless retry): %s", e2)
                return None
        logger.warning("Update check failed: %s", e)
        return None
    except (URLError, TimeoutError) as e:
        logger.warning("Update check failed: %s", e)
        return None


def _is_newer(latest_tag, current):
    """세마버(Semantic Versioning) 기준으로 버전을 비교합니다."""
    if current == "dev":
        return False

    def _parse(tag: str):
        clean = tag.lstrip("v").strip()
        parts = clean.split(".")
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(0)
        while len(result) < 3:
            result.append(0)
        return tuple(result)

    try:
        return _parse(latest_tag) > _parse(current)
    except Exception:
        return False


def _find_asset_url(release):
    """릴리스 에셋에서 업데이트용 EXE URL을 찾습니다.
    CI 빌드 에셋명: vibe-coding-update-X.Y.Z.exe (setup 제외)
    """
    assets = release.get("assets", [])

    # 1순위: vibe-coding-update-*.exe (현재 CI 표준 네이밍)
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("vibe-coding-update-") and name.endswith(".exe"):
            logger.info("에셋 발견(update): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    # 2순위: 정확히 ASSET_NAME과 일치
    for asset in assets:
        name = asset.get("name", "")
        if name == ASSET_NAME:
            return asset.get("browser_download_url") or asset.get("url")

    # 3순위: vibe-coding*.exe 중 setup/console 아닌 것
    for asset in assets:
        name = asset.get("name", "")
        if (name.startswith("vibe-coding") and name.endswith(".exe")
                and "setup" not in name.lower() and "console" not in name.lower()):
            logger.info("에셋 발견(fallback): %s", name)
            return asset.get("browser_download_url") or asset.get("url")

    logger.warning("업데이트 에셋 없음. 에셋 목록: %s", [a.get("name") for a in assets])
    return None


def _download_asset(url, dest, token):
    """릴리스 에셋을 dest 경로에 다운로드합니다."""
    logger.info("다운로드 시작: %s → %s", url, dest)
    req = Request(url)
    req.add_header("User-Agent", "vibe-coding-updater")
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
    """
    exe_path = Path(sys.executable).resolve()
    old_path = exe_path.with_suffix(".exe.old")

    logger.info("업데이트 적용 시작: %s → %s", new_exe, exe_path)

    if not new_exe.exists():
        raise FileNotFoundError(f"새 exe 파일 없음: {new_exe}")
    if new_exe.stat().st_size < 1_000_000:
        raise ValueError(f"새 exe 파일 너무 작음 ({new_exe.stat().st_size} bytes) — 손상 의심")

    if old_path.exists():
        try:
            old_path.unlink()
        except OSError as e:
            logger.warning(".old 파일 삭제 실패: %s", e)

    os.rename(exe_path, old_path)

    try:
        shutil.move(str(new_exe), str(exe_path))
    except Exception as move_err:
        logger.error("새 exe 이동 실패 — 롤백: %s", move_err)
        try:
            os.rename(old_path, exe_path)
        except Exception as rb_err:
            logger.error("롤백 실패: %s", rb_err)
        raise RuntimeError(f"업데이트 이동 실패: {move_err}") from move_err

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
        "timeout /t 3 /nobreak >NUL\n"
        f'start "" "{exe_path}"\n'
        'del /f /q "%~f0"\n'
    )
    with open(bat_path, "w", encoding="mbcs", errors="replace") as f:
        f.write(bat_content)

    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=0x08000000,
        close_fds=True,
    )
    time.sleep(0.8)
    os._exit(0)


def check_and_update(data_dir):
    """메인 엔트리포인트 — 백그라운드 스레드에서 호출.
    EXE(frozen) 모드에서만 동작. 개발 모드에서는 스킵.
    """
    ready_file = data_dir / "update_ready.json"

    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping update check.")
        return

    if not getattr(sys, "frozen", False):
        logger.info("Not running as frozen exe, skipping update check.")
        try:
            ready_file.unlink(missing_ok=True)
        except Exception:
            pass
        return

    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True}, f)

    token = _get_token(data_dir)
    release = _fetch_latest_release(token)
    if release is None:
        # [진단] 무음 실패 금지 — 설치 PC에서 "업데이트 안 뜸" 원인 추적용 상태 기록.
        # /api/check-update-ready가 version 없는 파일은 삭제하지 않고 그대로 반환한다.
        with open(ready_file, "w", encoding="utf-8") as f:
            json.dump({"ready": False, "downloading": False,
                       "last_error": "릴리즈 조회 실패 — 네트워크 또는 토큰 문제 (cli 로그 참조)",
                       "last_check": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
        return

    latest_tag = release.get("tag_name", "")
    if not _is_newer(latest_tag, APP_VERSION):
        logger.info("Already up to date (%s).", APP_VERSION)
        try:
            ready_file.unlink()
        except Exception:
            pass
        return

    logger.info("New version available: %s (current: %s)", latest_tag, APP_VERSION)

    asset_url = _find_asset_url(release)
    if not asset_url:
        logger.warning("Release %s has no update asset.", latest_tag)
        with open(ready_file, "w", encoding="utf-8") as f:
            json.dump({"ready": False, "downloading": False,
                       "last_error": f"릴리즈 {latest_tag}에 업데이트 에셋 없음",
                       "last_check": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
        return

    # 다운로드 중 상태 알림
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"version": latest_tag, "ready": False, "downloading": True}, f)

    tmp_path = data_dir / "vibe-coding.exe.new"
    if not _download_asset(asset_url, tmp_path, token):
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            ready_file.unlink()
        except Exception:
            pass
        return

    logger.info("Download complete. Waiting for user to apply update...")
    print(f"[*] 새 버전 v{latest_tag} 다운로드 완료. 업데이트 버튼을 눌러주세요.")
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({
            "version": latest_tag, "ready": True, "downloading": False,
            "exe_path": str(tmp_path)
        }, f)
