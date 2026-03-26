"""
FILE: .ai_monitor/updater.py
DESCRIPTION: 자동 업데이트 모듈 — pip install --upgrade 방식 셀프 업데이트.
  서버 시작 시 백그라운드 스레드에서 GitHub raw 파일로 최신 버전 확인 후 자동 업그레이드.
  GitHub Releases/태그 없이도 동작 — _version.py의 __version__을 직접 비교합니다.

REVISION HISTORY:
- 2026-03-26 Claude: Release API → raw _version.py 직접 비교 방식으로 전환
  → GitHub Release/태그 생성 없이도 커밋 푸시만으로 업데이트 감지 가능
  → import 경로를 try/except로 pip/dev 양쪽 호환
- 2026-03-25 Claude: EXE 업데이트 로직 제거, pip upgrade 전용으로 전환
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import json
import os
import re
import sys
import subprocess
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# pip 설치 환경/개발 환경 양쪽에서 import 가능하도록 try/except
try:
    from ._version import __version__ as APP_VERSION
except ImportError:
    from _version import __version__ as APP_VERSION

REPO = "btsky99/vibe-coding"
# GitHub raw 파일에서 _version.py를 직접 읽어 최신 버전 추출
# Releases API와 달리 Release/태그 생성 없이 커밋 푸시만으로 버전 감지 가능
VERSION_RAW_URL = f"https://raw.githubusercontent.com/{REPO}/main/.ai_monitor/_version.py"

logger = logging.getLogger("updater")


def _fetch_latest_version():
    """GitHub의 main 브랜치 _version.py에서 최신 __version__ 값을 추출합니다.
    Releases API와 달리 태그/릴리즈가 없어도 커밋만 푸시하면 바로 감지됩니다.
    """
    req = Request(VERSION_RAW_URL)
    req.add_header("User-Agent", "vibe-coding-updater")
    # 캐시 방지 — GitHub CDN이 raw 파일을 5분가량 캐시하므로 no-cache 헤더 추가
    req.add_header("Cache-Control", "no-cache")
    try:
        with urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            # __version__ = "3.7.123" 패턴 추출
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
    except (URLError, HTTPError, TimeoutError) as e:
        logger.warning("Update check failed: %s", e)
    return None


def _is_newer(latest, current):
    """세마버(Semantic Versioning) 기준으로 버전을 비교합니다."""
    if current == "dev":
        return False

    def _parse(ver: str):
        clean = ver.lstrip("v").strip()
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
        return _parse(latest) > _parse(current)
    except Exception:
        return False


def check_and_update(data_dir):
    """메인 엔트리포인트 — 백그라운드 스레드에서 호출.
    GitHub raw에서 최신 버전 확인 → 새 버전이면 pip install --upgrade 실행.
    """
    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping update check.")
        return

    ready_file = data_dir / "update_ready.json"
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True}, f)

    latest_ver = _fetch_latest_version()
    if latest_ver is None:
        try: ready_file.unlink()
        except: pass
        return

    if not _is_newer(latest_ver, APP_VERSION):
        logger.info("Already up to date (%s).", APP_VERSION)
        try: ready_file.unlink()
        except: pass
        return

    logger.info("[pip] New version available: %s (current: %s)", latest_ver, APP_VERSION)
    print(f"[*] 새 버전 감지: {APP_VERSION} → {latest_ver}, 업데이트 중...")

    # pip install --upgrade (태그 없이 main 브랜치 최신 커밋 기준 설치)
    repo_url = f"git+https://github.com/{REPO}.git"
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", repo_url],
            capture_output=True, text=True, timeout=300,
            creationflags=_no_window,
        )
        if result.returncode == 0:
            msg = f"v{latest_ver} 업데이트 완료. 재시작하면 적용됩니다."
            logger.info("[pip] %s", msg)
            print(f"[*] {msg}")
            # 업데이트 후 바탕화면 바로가기를 자동 재생성
            # — 이전 버전이 콘솔(vibe-coding.exe)을 가리키고 있을 수 있으므로
            #   GUI(vibe-coding-gui.exe)로 갱신
            try:
                try:
                    from .create_shortcut import create_shortcut
                except ImportError:
                    from create_shortcut import create_shortcut
                create_shortcut()
                logger.info("[pip] 바로가기 재생성 완료")
            except Exception as e:
                logger.warning("[pip] 바로가기 재생성 실패: %s", e)
            with open(ready_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": latest_ver, "ready": True, "downloading": False,
                    "message": msg
                }, f)
        else:
            logger.warning("[pip] 업데이트 실패: %s", result.stderr[:500])
            try: ready_file.unlink()
            except: pass
    except Exception as e:
        logger.error("[pip] 업데이트 중 에러: %s", e)
        try: ready_file.unlink()
        except: pass
