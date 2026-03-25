"""
FILE: .ai_monitor/updater.py
DESCRIPTION: 자동 업데이트 모듈 — pip install --upgrade 방식 셀프 업데이트.
  서버 시작 시 백그라운드 스레드에서 GitHub API로 최신 버전 확인 후 자동 업그레이드.
  Claude Code / Gemini CLI와 동일한 방식 — 재시작하면 새 버전 적용.

REVISION HISTORY:
- 2026-03-25 Claude: EXE 업데이트 로직 제거, pip upgrade 전용으로 전환
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import json
import os
import sys
import subprocess
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from _version import __version__ as APP_VERSION

REPO = "btsky99/vibe-coding"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

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
    """GitHub API에서 최신 릴리스 정보를 조회합니다."""
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


def check_and_update(data_dir):
    """메인 엔트리포인트 — 백그라운드 스레드에서 호출.
    GitHub API로 최신 태그 확인 → 새 버전이면 pip install --upgrade 실행.
    """
    if APP_VERSION == "dev":
        logger.info("Dev build detected, skipping update check.")
        return

    ready_file = data_dir / "update_ready.json"
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"ready": False, "downloading": False, "checking": True}, f)

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

    # pip install --upgrade 실행
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
                    "message": f"v{latest_tag.lstrip('v')} 업데이트 완료. 재시작하면 적용됩니다."
                }, f)
        else:
            logger.warning("[pip] 업데이트 실패: %s", result.stderr[:500])
            try: ready_file.unlink()
            except: pass
    except Exception as e:
        logger.error("[pip] 업데이트 중 에러: %s", e)
        try: ready_file.unlink()
        except: pass
