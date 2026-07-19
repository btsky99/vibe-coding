"""
FILE: .ai_monitor/soft_updater.py
DESCRIPTION: 경량 소스 업데이트 채널(A안)의 감지/적용 모듈.
  GitHub main 최신 커밋 SHA를 폴링해 로컬 체크아웃 HEAD와 비교하고,
  사용자가 버튼을 누르면 `git reset --hard origin/main` + 재시작으로 순수 .py 변경을 반영한다.
  EXE 풀빌드(updater.py)와 독립된 빠른 채널 — 의존성 변경은 min_exe 게이트로 차단된다.

REVISION HISTORY:
- 2026-07-03 Claude: dev 트리 보호 가드 2겹 추가 — 비frozen 채널 차단 + 로컬 전용 커밋 유실 방지.
  (사고: dev 트리에서 apply 실행 → reset --hard로 미푸시 커밋 4개 고아화, .soft_rollback로 복구)
- 2026-06-24 Claude: 최초 작성 — Task 4~5. boot.py가 만든 관리 체크아웃을 갱신한다.
  메모리 project_soft_update_channel / 계획 ai_monitor_plan.md 참조.
"""
import json
import os
import sys
import time
import shutil
import logging
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

REPO = "btsky99/vibe-coding"
BRANCH = "main"
REPO_URL = f"https://github.com/{REPO}.git"
COMMIT_API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ROLLBACK_FILE = ".soft_rollback"  # boot.py가 부팅 실패 시 읽는 직전 SHA 파일
READY_FILE = "soft_update_ready.json"

logger = logging.getLogger("soft_updater")


def _git(args, cwd=None, timeout=300):
    """git 실행 → (ok, stdout). git 미설치/실패는 (False, '')."""
    if not shutil.which("git"):
        return False, ""
    try:
        r = proc.run(["git"] + args, cwd=cwd and str(cwd),
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", timeout=timeout)
        return r.returncode == 0, (r.stdout or "").strip()
    except Exception as e:
        logger.warning("git %s 실패: %s", args[:1], e)
        return False, ""


def _is_checkout(src: Path) -> bool:
    return (src / ".git").exists() and (src / ".ai_monitor" / "server.py").exists()


def _channel_block_reason():
    """soft 채널 활성 자격 검사 — 차단 사유 문자열, 통과면 None.
    [과거사고 2026-07-03] dev 트리(비frozen)도 git 체크아웃이라 _is_checkout을 통과 →
      미푸시 커밋 때문에 local≠remote → ready=true 배너 → apply가 dev 트리를
      reset --hard → 커밋 4개 고아화(.soft_rollback로 복구). 채널은 boot.py가 만든
      frozen 관리 체크아웃(%LOCALAPPDATA%\\VibeCoding\\app) 전용이다.
    [예외] VIBE_SRC_DIR 오버라이드는 명시적 opt-in(E2E 테스트/특수 배치) — 허용.
    """
    if os.environ.get("VIBE_SRC_DIR", "").strip():
        return None
    if not getattr(sys, "frozen", False):
        return "dev 실행(비frozen) — soft 채널 비활성 (dev 트리 reset 보호)"
    return None


def _local_head(src: Path):
    ok, out = _git(["rev-parse", "HEAD"], cwd=src)
    return out if ok and out else None


def _remote_head():
    """GitHub API로 main 최신 커밋 SHA. 토큰 불필요(public)지만 rate-limit 완화용으로 사용.
    [과거사고 updater.py:57] 만료 토큰(401/403) 시 토큰 없이 1회 재시도 — 무음 실패 방지.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None

    def _req(use_token):
        req = Request(COMMIT_API)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "vibe-coding-soft-updater")
        if use_token and token:
            req.add_header("Authorization", f"token {token}")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("sha")

    try:
        return _req(True)
    except HTTPError as e:
        if token and e.code in (401, 403):
            try:
                return _req(False)
            except (URLError, HTTPError, TimeoutError) as e2:
                logger.warning("remote head 조회 실패(tokenless): %s", e2)
                return None
        logger.warning("remote head 조회 실패: %s", e)
        return None
    except (URLError, TimeoutError, Exception) as e:
        logger.warning("remote head 조회 실패: %s", e)
        return None


def _exe_version() -> str:
    """현재 EXE(번들)의 _version — min_exe 게이트 비교 기준.
    [불변식] SRC가 아니라 번들 버전. frozen은 MEIPASS, dev는 옆 _version.py.
    """
    for c in (Path(getattr(sys, "_MEIPASS", "")) / "_version.py",
              Path(getattr(sys, "_MEIPASS", "")) / "_appseed" / ".ai_monitor" / "_version.py",
              Path(__file__).resolve().parent / "_version.py"):
        try:
            if c.exists():
                ns: dict = {}
                exec(c.read_text(encoding="utf-8"), ns)  # noqa: S102
                if ns.get("__version__"):
                    return str(ns["__version__"])
        except Exception:
            continue
    return "0.0.0"


def _ver_tuple(tag):
    out = []
    for p in str(tag).lstrip("v").strip().split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _gate_block_reason(src: Path):
    """min_exe 게이트 위반 시 사유 문자열, 통과면 None.
    [목적] 의존성/부트스트랩이 바뀐 원격 소스를 옛 EXE가 받지 못하게 — 풀빌드 안내."""
    manifest = src / "soft_manifest.json"
    try:
        if not manifest.exists():
            return None
        min_exe = json.loads(manifest.read_text(encoding="utf-8")).get("min_exe", "0.0.0")
        if _ver_tuple(_exe_version()) < _ver_tuple(min_exe):
            return f"이 소스는 EXE v{min_exe}+ 필요 (현재 v{_exe_version()}) — 풀빌드 업데이트 필요"
        return None
    except Exception:
        return None


def _write_ready(data_dir: Path, payload: dict):
    try:
        (data_dir / READY_FILE).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("%s 기록 실패: %s", READY_FILE, e)


def check_soft_update(data_dir: Path, src_dir: Path) -> dict:
    """원격/로컬 SHA 비교 → soft_update_ready.json 기록 후 반환.
    백그라운드 스레드 또는 /api/soft-update/check 에서 호출.
    """
    data_dir = Path(data_dir)
    src_dir = Path(src_dir)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    blocked = _channel_block_reason()
    if blocked:
        result = {"ready": False, "channel": BRANCH, "last_check": now, "reason": blocked}
        _write_ready(data_dir, result)
        return result

    if not _is_checkout(src_dir):
        # seed로 부팅된(=.git 없는) 설치본 — apply 시 clone 승격 필요.
        result = {"ready": False, "channel": BRANCH, "last_check": now,
                  "reason": "git 체크아웃 아님(seed 부팅) — 적용 시 clone 승격"}
        _write_ready(data_dir, result)
        return result

    local = _local_head(src_dir)
    remote = _remote_head()
    if not remote:
        result = {"ready": False, "channel": BRANCH, "last_check": now,
                  "local_sha": local, "reason": "원격 SHA 조회 실패(네트워크/rate-limit)"}
        _write_ready(data_dir, result)
        return result

    gate = _gate_block_reason(src_dir)
    ready = bool(local and remote and local != remote and not gate)
    result = {"ready": ready, "channel": BRANCH, "last_check": now,
              "local_sha": local, "remote_sha": remote}
    if gate:
        result["reason"] = gate
        result["needs_full_build"] = True
    _write_ready(data_dir, result)
    return result


def apply_soft_update(src_dir: Path) -> dict:
    """origin/main으로 reset --hard + 재시작. 직전 SHA를 .soft_rollback에 백업.
    seed 부팅(.git 없음)이면 fresh clone으로 승격.
    """
    src_dir = Path(src_dir)

    blocked = _channel_block_reason()
    if blocked:
        return {"ok": False, "error": blocked}

    if not _is_checkout(src_dir):
        # seed 상태 → clone 승격: 임시로 받아 교체.
        if not shutil.which("git"):
            return {"ok": False, "error": "git 미설치 — 소스 업데이트 불가(풀빌드 사용)"}
        tmp = src_dir.parent / (src_dir.name + ".clone_tmp")
        try:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            ok, _ = _git(["clone", "--depth", "50", REPO_URL, str(tmp)])
            if not ok or not (tmp / ".ai_monitor" / "server.py").exists():
                return {"ok": False, "error": "clone 승격 실패"}
            # 기존 seed 트리 제거 후 교체
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)
            shutil.move(str(tmp), str(src_dir))
        except Exception as e:
            return {"ok": False, "error": f"clone 승격 예외: {e}"}
        return _restart(src_dir)

    prev = _local_head(src_dir)
    if prev:
        try:
            (src_dir / ROLLBACK_FILE).write_text(prev, encoding="utf-8")
        except Exception:
            pass

    ok_fetch, _ = _git(["fetch", "origin", BRANCH], cwd=src_dir)
    if not ok_fetch:
        return {"ok": False, "error": "git fetch 실패(네트워크 확인)"}
    # [유실 방지 불변식] HEAD가 origin/BRANCH의 조상일 때만 reset 허용.
    #   관리 체크아웃은 로컬 커밋이 없어야 정상 — 조상이 아니면 이 트리에 원격에 없는
    #   커밋이 있다는 뜻(2026-07-03 dev 트리 사고 유형)이라 reset 시 고아화된다.
    ok_anc, _ = _git(["merge-base", "--is-ancestor", "HEAD", f"origin/{BRANCH}"], cwd=src_dir)
    if not ok_anc:
        return {"ok": False,
                "error": "로컬 전용 커밋 감지 — 유실 방지를 위해 soft 업데이트 차단(수동 정리 필요)"}
    ok_reset, _ = _git(["reset", "--hard", f"origin/{BRANCH}"], cwd=src_dir)
    if not ok_reset:
        return {"ok": False, "error": "git reset --hard 실패"}
    new_head = _local_head(src_dir)
    logger.info("soft update 적용: %s → %s", prev, new_head)
    return _restart(src_dir, new_head)


def _restart(src_dir: Path, new_head: str = "") -> dict:
    """현재 프로세스 종료 후 EXE 재실행 — boot.py가 갱신된 SRC를 다시 runpy 한다.
    [제약] updater.apply_update_from_temp 와 동일하게 PID 종료 대기 .bat 사용 —
      Windows에서 실행 중 프로세스를 깔끔히 보낸 뒤 재기동해야 핸들 충돌이 없음.
    frozen이 아니면(dev) 재시작 .bat 대신 안내만 — 개발 중 임의 재실행 방지.
    """
    if not getattr(sys, "frozen", False):
        return {"ok": True, "new_head": new_head, "restart": False,
                "note": "dev 모드 — 수동 재시작 필요"}
    exe = Path(sys.executable).resolve()
    bat = exe.parent / "_soft_restart.bat"
    pid = os.getpid()
    content = (
        "@echo off\n"
        ":wait\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n'
        "if not errorlevel 1 (\n"
        "    timeout /t 1 /nobreak >NUL\n"
        "    goto wait\n"
        ")\n"
        "timeout /t 2 /nobreak >NUL\n"
        f'start "" "{exe}"\n'
        'del /f /q "%~f0"\n'
    )
    try:
        with open(bat, "w", encoding="mbcs", errors="replace") as f:
            f.write(content)
        proc.popen(["cmd.exe", "/c", str(bat)], close_fds=True)
        time.sleep(0.6)
    except Exception as e:
        return {"ok": False, "error": f"재시작 스크립트 실패: {e}", "new_head": new_head}
    os._exit(0)
