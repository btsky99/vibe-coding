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
PROGRESS_FILE = "soft_update_progress.json"  # data_dir — UI가 폴링하는 진행률
STAGED_FILE = ".soft_staged"  # SRC — boot.py가 읽는 "받아둔 SHA"

# [설계 핵심 — 왜 받기(fetch)와 적용(reset)을 쪼갰나]
#   사용자 요구는 "재시작하면 알아서 최신" + "% 진행률". 이 둘은 같은 구간에서 만족될 수 없다.
#   느린 건 네트워크(fetch)인데 그걸 부팅 때 하면 (a) 부팅이 느려지고 (b) 그 시점엔 창이 없어
#   진행률을 그릴 데가 없다. boot.py에 UI를 넣는 길은 이미 막혀 있다 — tkinter는 로컬 onedir
#   빌드가 pyi_rth__tkinter에서 깨져 vibe-coding.spec에서 의도적으로 excludes 됐다(2026-08-01).
#   → 그래서 **앱이 떠 있는 동안 미리 fetch**(화면이 있으니 % 표시 가능)하고, 부팅 때는
#     로컬 reset만 한다(네트워크 0, 수십 ms). 결과적으로 "앱 뜨기 전에 최신 코드"가 되고
#     추가 재시작도 없다.
# [불변식] fetch는 워킹트리를 건드리지 않는다 — 받아만 두고 HEAD는 그대로. 그래서 앱이
#   돌아가는 중에 코드가 발밑에서 바뀌는 사고가 없다. 트리 이동은 오직 boot.py(또는 버튼)에서.

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
    [중복 제거 2026-08-01] 같은 로직이 updater.bundle_version()에도 있어 한쪽만 고쳐지는
      사고가 실제로 났다(updater가 소스 버전을 번들로 오인해 업데이트 영구 미감지).
      updater를 정본으로 위임하고, import 실패 시에만 아래 로컬 폴백을 쓴다.
      [예외] boot.py는 앱 모듈을 import하면 안 되므로(PyInstaller가 PYZ에 넣어버려
      run-from-source 전제가 깨짐) 자체 구현을 유지한다 — 의도된 3번째 사본이다.
    """
    try:
        from updater import bundle_version
        return bundle_version()
    except Exception:
        pass
    # ── 폴백 ──
    # [버그수정] _MEIPASS가 없을 때(비frozen) Path("")/"_version.py"는 **cwd 상대경로**가 되어
    #   작업 디렉토리에 우연히 있는 _version.py를 번들 버전으로 읽는다. VIBE_SRC_DIR opt-in
    #   경로(E2E 테스트)가 정확히 비frozen이라 실제로 노출되는 결함이었다.
    candidates = []
    mei = getattr(sys, "_MEIPASS", "")
    if mei:
        candidates.append(Path(mei) / "_version.py")
        candidates.append(Path(mei) / "_appseed" / ".ai_monitor" / "_version.py")
    candidates.append(Path(__file__).resolve().parent / "_version.py")
    for c in candidates:
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


def write_progress(data_dir: Path, phase: str, percent: int, detail: str = "") -> None:
    """진행률을 파일로 남긴다 — UI가 /api/soft-update/progress 로 폴링한다.

    [WHY 파일인가] fetch는 별도 스레드에서 돌고 UI는 HTTP 폴링이라 프로세스 내 공유 상태로는
      SSE 없이 못 넘긴다. 파일 한 장이 가장 단순하고, 앱이 죽어도 마지막 상태가 남아
      "받다 만" 상태를 다음 기동에서 그대로 이어 판단할 수 있다.
    """
    try:
        payload = {"phase": phase, "percent": max(0, min(100, int(percent))),
                   "detail": detail, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (Path(data_dir) / PROGRESS_FILE).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("진행률 기록 실패: %s", e)


def read_progress(data_dir: Path) -> dict:
    try:
        f = Path(data_dir) / PROGRESS_FILE
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"phase": "idle", "percent": 0, "detail": ""}


# git이 --progress로 흘리는 단계별 비중. 합이 100이 되도록 구간을 배분한다.
# [WHY 가중치인가] git은 단계마다 0→100%를 반복해서 뱉는다. 그대로 쓰면 진행바가
#   네 번 처음부터 다시 차 사용자가 "멈췄나?"로 읽는다. 단일 축으로 눌러 펴야 한다.
# [비중 근거] 관리 체크아웃은 shallow(depth 50)라 실제 시간의 대부분이 Receiving에 몰린다.
# [🔴 실측 2026-08-07] Enumerating과 Counting에 같은 구간을 주면 진행바가 **뒤로 간다** —
#   git은 "Enumerating 100%" 를 먼저 끝내고 "Counting 50%" 를 시작하므로 8%→4%로 역행했다.
#   구간을 겹치지 않게 쪼개고, 그래도 남는 순서 뒤바뀜은 아래 단조 클램프가 흡수한다.
_PROGRESS_PHASES = (
    ("Enumerating objects", 0, 4),
    ("Counting objects", 4, 8),
    ("Compressing objects", 8, 22),
    ("Receiving objects", 22, 90),
    ("Resolving deltas", 90, 99),
)


def _parse_git_progress(line: str):
    """git --progress 한 줄 → (표시용 문구, 전체 대비 %) 또는 None.

    [제약] git은 진행 갱신을 개행이 아니라 **캐리지리턴(\\r)** 으로 구분한다.
      readline으로 읽으면 fetch가 끝날 때까지 한 줄도 안 나온다 — 반드시 \\r 기준으로 쪼갤 것.
    """
    for name, lo, hi in _PROGRESS_PHASES:
        if name in line:
            try:
                pct = int(line.split(name, 1)[1].split("%", 1)[0].strip().lstrip(":").strip())
            except (ValueError, IndexError):
                return None
            return name, lo + (hi - lo) * pct / 100.0
    return None


def _fetch_with_progress(src: Path, data_dir: Path) -> bool:
    """git fetch --progress 실행하며 진행률을 파일로 흘린다. 성공 여부 반환.

    [제약] proc.run은 완료까지 블로킹이라 진행률을 못 뽑는다 → popen + stderr 스트리밍.
      git은 진행 상황을 stdout이 아니라 **stderr**로 보낸다.
    """
    if not shutil.which("git"):
        write_progress(data_dir, "error", 0, "git 미설치")
        return False
    try:
        p = proc.popen(
            ["git", "fetch", "--progress", "origin", BRANCH],
            cwd=str(src), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except Exception as e:
        write_progress(data_dir, "error", 0, f"fetch 기동 실패: {e}")
        return False

    write_progress(data_dir, "fetching", 1, "연결 중")
    buf = ""
    last_written = -1
    try:
        while True:
            ch = p.stderr.read(1) if p.stderr else ""
            if not ch:
                break
            if ch in ("\r", "\n"):
                parsed = _parse_git_progress(buf)
                if parsed:
                    label, pct = parsed
                    # [단조 클램프] git 단계 순서는 버전·서버 구현에 따라 뒤바뀔 수 있다.
                    #   구간 배분만으로는 역행을 다 못 막으므로 최댓값으로 눌러 고정한다.
                    #   진행바가 뒤로 가면 사용자는 실패로 읽는다 — 정확도보다 단조성이 중요하다.
                    cur = max(int(pct), last_written)
                    # 같은 정수 %를 반복해서 쓰면 디스크만 때린다 — 변할 때만 기록.
                    if cur != last_written:
                        last_written = cur
                        write_progress(data_dir, "fetching", cur, label)
                buf = ""
            else:
                buf += ch
        p.wait(timeout=300)
    except Exception as e:
        logger.warning("fetch 스트리밍 중단: %s", e)
        try:
            p.kill()
        except Exception:
            pass
        write_progress(data_dir, "error", 0, f"fetch 중단: {e}")
        return False

    if p.returncode != 0:
        write_progress(data_dir, "error", 0, "git fetch 실패(네트워크 확인)")
        return False
    return True


def _staged_sha(src: Path):
    """SRC에 예약된 대상 SHA. 없거나 깨졌으면 None."""
    try:
        f = Path(src) / STAGED_FILE
        if f.exists():
            sha = json.loads(f.read_text(encoding="utf-8")).get("sha")
            return sha or None
    except Exception:
        pass
    return None


def clear_staged(src: Path) -> None:
    try:
        (Path(src) / STAGED_FILE).unlink()
    except Exception:
        pass


def auto_update_enabled(data_dir: Path) -> bool:
    """재시작 시 자동 적용 토글. config.json의 soft_auto_update, 기본 켬.

    [WHY 기본 켬] 이 채널의 존재 이유가 "풀빌드 없이 항상 최신"이다. 기본이 꺼져 있으면
      아무도 안 켜서 채널이 사실상 죽는다. 안전망(.soft_rollback 자동 롤백 + ancestor 가드 +
      min_exe 게이트)이 이미 3중이라 기본 켬의 위험이 낮다.
    [불변식] 토글은 **예약 시점에만** 평가된다. boot.py는 config를 읽지 않고 예약 파일만 본다
      (앱 모듈 import 금지 불변식). 즉 토글을 끄면 예약이 안 생겨 부팅 적용도 자연히 멈춘다.
    """
    try:
        cfg = json.loads((Path(data_dir) / "config.json").read_text(encoding="utf-8"))
        return bool(cfg.get("soft_auto_update", True))
    except Exception:
        return True


def stage_soft_update(data_dir: Path, src_dir: Path) -> dict:
    """원격 커밋을 **받아만 둔다**(워킹트리 불변). 다음 부팅 때 boot.py가 즉시 적용한다.

    자동 경로의 본체 — 앱이 떠 있는 동안 백그라운드로 호출된다.
    [불변식] 여기서 reset을 하지 않는다. 실행 중인 앱의 코드가 발밑에서 바뀌면
      import 캐시와 디스크가 어긋나 진단 불가능한 오류가 난다.
    """
    data_dir, src_dir = Path(data_dir), Path(src_dir)

    blocked = _channel_block_reason()
    if blocked:
        return {"ok": False, "error": blocked}
    if not _is_checkout(src_dir):
        return {"ok": False, "error": "git 체크아웃 아님(seed 부팅) — 버튼으로 clone 승격 필요"}

    if not _fetch_with_progress(src_dir, data_dir):
        return {"ok": False, "error": "fetch 실패"}

    ok, target = _git(["rev-parse", f"origin/{BRANCH}"], cwd=src_dir)
    if not ok or not target:
        write_progress(data_dir, "error", 0, "원격 SHA 확인 실패")
        return {"ok": False, "error": "origin/main SHA 확인 실패"}

    local = _local_head(src_dir)
    if local == target:
        write_progress(data_dir, "idle", 0, "이미 최신")
        clear_staged(src_dir)
        return {"ok": True, "staged": False, "reason": "이미 최신"}

    # [유실 방지] 예약 단계에서 미리 막는다. 부팅 때 발견하면 그때는 사용자에게 알릴 화면이 없다.
    ok_anc, _ = _git(["merge-base", "--is-ancestor", "HEAD", target], cwd=src_dir)
    if not ok_anc:
        write_progress(data_dir, "error", 0, "로컬 전용 커밋 감지 — 수동 정리 필요")
        return {"ok": False, "error": "로컬 전용 커밋 감지 — 유실 방지를 위해 예약 차단"}

    gate = _gate_block_reason(src_dir)
    if gate:
        write_progress(data_dir, "error", 0, gate)
        return {"ok": False, "error": gate, "needs_full_build": True}

    try:
        (src_dir / STAGED_FILE).write_text(
            json.dumps({"sha": target, "prev": local,
                        "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False),
            encoding="utf-8")
    except Exception as e:
        write_progress(data_dir, "error", 0, f"예약 기록 실패: {e}")
        return {"ok": False, "error": f"예약 기록 실패: {e}"}

    write_progress(data_dir, "staged", 100, "재시작하면 적용됩니다")
    logger.info("soft update 예약: %s → %s", local, target)
    return {"ok": True, "staged": True, "sha": target}


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
    # 이미 받아둔(예약된) 업데이트가 있으면 UI가 "재시작하면 적용"으로 안내해야 한다.
    staged = _staged_sha(src_dir)
    if staged:
        result["staged_sha"] = staged
        result["staged"] = (staged == remote)
    if gate:
        result["reason"] = gate
        result["needs_full_build"] = True
    _write_ready(data_dir, result)
    return result


def apply_soft_update(src_dir: Path, data_dir: Path = None) -> dict:
    """origin/main으로 reset --hard + 재시작 (버튼 = '지금 적용').
    직전 SHA를 .soft_rollback에 백업. seed 부팅(.git 없음)이면 fresh clone으로 승격.

    [자동 경로와의 관계] 자동은 stage_soft_update로 받아만 두고 boot.py가 적용한다.
      이쪽은 "기다리기 싫다"는 사용자를 위한 즉시 경로 — 이미 예약돼 있으면 fetch를 건너뛴다.
    [호환] data_dir는 진행률 기록용 선택 인자. 옛 호출부(위치 인자 1개)를 깨지 않는다.
    """
    src_dir = Path(src_dir)
    _pd = Path(data_dir) if data_dir else None

    def _prog(phase, pct, detail=""):
        if _pd:
            write_progress(_pd, phase, pct, detail)

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

    # 자동 경로가 이미 받아뒀으면 네트워크를 다시 타지 않는다(버튼 반응이 즉각적이어야 한다).
    staged = _staged_sha(src_dir)
    if staged:
        _prog("applying", 95, "받아둔 업데이트 적용 중")
    elif _pd:
        if not _fetch_with_progress(src_dir, _pd):
            return {"ok": False, "error": "git fetch 실패(네트워크 확인)"}
    else:
        ok_fetch, _ = _git(["fetch", "origin", BRANCH], cwd=src_dir)
        if not ok_fetch:
            return {"ok": False, "error": "git fetch 실패(네트워크 확인)"}

    target = staged or f"origin/{BRANCH}"
    # [유실 방지 불변식] HEAD가 대상의 조상일 때만 reset 허용.
    #   관리 체크아웃은 로컬 커밋이 없어야 정상 — 조상이 아니면 이 트리에 원격에 없는
    #   커밋이 있다는 뜻(2026-07-03 dev 트리 사고 유형)이라 reset 시 고아화된다.
    ok_anc, _ = _git(["merge-base", "--is-ancestor", "HEAD", target], cwd=src_dir)
    if not ok_anc:
        _prog("error", 0, "로컬 전용 커밋 감지")
        return {"ok": False,
                "error": "로컬 전용 커밋 감지 — 유실 방지를 위해 soft 업데이트 차단(수동 정리 필요)"}
    ok_reset, _ = _git(["reset", "--hard", target], cwd=src_dir)
    if not ok_reset:
        _prog("error", 0, "reset 실패")
        return {"ok": False, "error": "git reset --hard 실패"}
    clear_staged(src_dir)
    new_head = _local_head(src_dir)
    _prog("restarting", 100, "재시작 중")
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
