"""
FILE: .ai_monitor/updater.py
DESCRIPTION: 자동 업데이트 모듈 — GitHub Releases API로 셀프 업데이트 수행 (Windows).
  서버 시작 시 백그라운드 스레드에서 최신 릴리즈 확인 후 EXE 다운로드.
  EXE 모드(frozen)에서만 자동 업데이트 실행, 개발 모드에서는 스킵.

REVISION HISTORY:
- 2026-08-01 Claude: [업데이트 미감지 근본수정] 버전 비교 기준을 모듈 상수 APP_VERSION →
  bundle_version()(번들 _version.py)로 교체. boot.py가 체크아웃을 sys.path 최우선으로 넣어
  `from _version import ...`이 소스 버전을 주던 탓에, soft 채널이 소스만 최신으로 당기면
  "소스 버전 == 최신 태그"가 되어 EXE 풀빌드 업데이트가 영구 미감지(설치본 3.7.286 정지).
- 2026-07-12 Claude: [코드32 사고 근본수정] setup 인스톨러가 앱 exe로 스왑되던 버그 수정.
  다운로드 tmp를 항상 vibe-coding.exe.new로 저장 → is_installer_asset이 'setup' 미검출 →
  onefile로 오판 → apply_update_from_temp가 인스톨러를 {app}\vibe-coding.exe로 스왑 →
  실행 시 자기 자신 덮어쓰기로 "DeleteFile 실패; 코드32(사용 중)". 수정: _find_asset(dict 반환)로
  원본 에셋명 판정 + tmp를 vibe-coding-setup.exe.new로 이름지어 인스톨러 여부 보존 +
  update_ready.json에 is_installer 명시 저장(apply 단계 확정 분기).
- 2026-07-09 Claude: 업데이트 재발 사고 근본수정 (v3.7.248) — ① _update.bat이 구 프로세스 사망 후
  새 EXE 기동 전에 runtime의 고아 node kill + 깨진 _MEI(python DLL 누락) 삭제 → setup 새설치와
  동일한 깨끗한 상태 보장(Failed to load Python DLL 원천 차단). ② 다운로드 진행률(percent)을
  update_ready.json에 기록 → 프론트 진행바.
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


def bundle_version() -> str:
    """실제 EXE 번들의 버전 — 풀빌드 업데이트 판단의 **유일한** 기준.

    [WHY 모듈 상수 APP_VERSION과 분리] boot.py(경량 소스 채널 A안)가 관리 체크아웃의 .py를
      runpy로 실행하며 sys.path 최우선을 체크아웃으로 잡는다 → 위쪽 `from _version import ...`은
      번들이 아니라 **소스 버전**을 준다. soft 채널이 소스를 최신으로 당겨오면
      소스 버전 == 최신 릴리즈 태그가 되어 _is_newer가 항상 False → EXE 풀빌드 업데이트가
      영구히 안 뜬다(번들 의존성은 옛 버전에 멈춘 채로).
      [과거사고 2026-08-01] 설치본 EXE 3.7.286 + 체크아웃 소스 3.7.313 → "이미 최신"으로
      오판해 v3.7.313 배너 미표시. 소스만 갱신되는 구조에서는 두 버전이 상시 갈린다.
    [불변식] frozen이면 _MEIPASS(onedir은 `_internal/`)의 _version.py가 진짜 번들 버전.
      __file__ 기준 후보는 체크아웃 소스를 가리키므로 **반드시 마지막**에 온다.
      _MEIPASS가 없으면(비frozen) 후보에서 제외 — Path("")/"_version.py"는 cwd 상대경로가 되어
      엉뚱한 파일을 읽을 수 있다.
    """
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
                exec(c.read_text(encoding="utf-8"), ns)  # noqa: S102 — 신뢰된 번들 파일
                if ns.get("__version__"):
                    return str(ns["__version__"])
        except Exception:
            continue
    return APP_VERSION


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


def _find_asset(release):
    """릴리스 에셋에서 업데이트용 EXE 에셋 dict를 우선순위대로 선택해 반환.

    [WHY 반환값 = dict] url뿐 아니라 **에셋 이름**이 apply 단계 분기에 필수다. 다운로드 임시
      파일명은 항상 vibe-coding(-setup).exe.new로 고정되므로, is_installer_asset을 tmp 파일명이
      아닌 '원본 에셋명'으로 판정해야 setup 인스톨러를 onefile로 오판하지 않는다.
      (v3.7.252 사고: setup 자산을 vibe-coding.exe.new로 저장 → "setup" 미포함으로 오판 →
       apply_update_from_temp가 인스톨러를 앱 exe로 스왑 → 실행 시 자기 자신 덮어쓰기 코드32.)
    CI 빌드 에셋명: vibe-coding-setup-X.Y.Z.exe(onedir) 또는 vibe-coding-update-X.Y.Z.exe(구 onefile)."""
    assets = release.get("assets", [])

    # [전략 #2a / onedir] 1순위: vibe-coding-setup-*.exe — 업데이트를 "Inno 인스톨러 /SILENT 실행"
    #   모델로 전환(exe-swap 폐기). onedir은 추출/_MEI가 없어 좀비/DLL로드실패 버그 클래스가 사라진다.
    #   Inno CloseApplications=yes가 실행 중 앱을 닫고 파일 교체+재시작을 담당.
    #   [폴백] 아래 update-*.exe(구 onefile)는 유지 — setup 자산이 없으면 구 exe-swap 경로로 동작.
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("vibe-coding-setup-") and name.endswith(".exe"):
            logger.info("에셋 발견(setup/onedir): %s", name)
            return asset

    # 2순위: vibe-coding-update-*.exe (구 onefile CI 네이밍 — 폴백/점진 전환)
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("vibe-coding-update-") and name.endswith(".exe"):
            logger.info("에셋 발견(update): %s", name)
            return asset

    # 3순위: 정확히 ASSET_NAME과 일치
    for asset in assets:
        name = asset.get("name", "")
        if name == ASSET_NAME:
            return asset

    # 4순위: vibe-coding*.exe 중 setup/console 아닌 것
    for asset in assets:
        name = asset.get("name", "")
        if (name.startswith("vibe-coding") and name.endswith(".exe")
                and "setup" not in name.lower() and "console" not in name.lower()):
            logger.info("에셋 발견(fallback): %s", name)
            return asset

    logger.warning("업데이트 에셋 없음. 에셋 목록: %s", [a.get("name") for a in assets])
    return None


def _find_asset_url(release):
    """_find_asset의 URL만 필요한 호출부용 얇은 래퍼 (기존 계약 유지)."""
    asset = _find_asset(release)
    if not asset:
        return None
    return asset.get("browser_download_url") or asset.get("url")


def _download_asset(url, dest, token, progress_cb=None):
    """릴리스 에셋을 dest 경로에 다운로드합니다.

    progress_cb(downloaded_bytes, total_bytes)가 주어지면 청크마다 호출한다.
    total_bytes는 Content-Length가 없으면 0(진행률 미상) — caller가 방어한다.
    """
    logger.info("다운로드 시작: %s → %s", url, dest)
    req = Request(url)
    req.add_header("User-Agent", "vibe-coding-updater")
    if "api.github.com" in url:
        req.add_header("Accept", "application/octet-stream")
        if token:
            req.add_header("Authorization", f"token {token}")
    try:
        with urlopen(req, timeout=120) as resp:
            # [진행률] S3 리다이렉트 후 최종 응답의 Content-Length. 없으면 0(미상).
            try:
                total_size = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total_size = 0
            total = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
                    if progress_cb is not None:
                        try:
                            progress_cb(total, total_size)
                        except Exception:
                            pass  # 진행률 기록 실패는 다운로드를 막지 않음
        if total < 1_000_000:
            logger.error("다운로드 파일 너무 작음 (%d bytes) — 손상 가능성", total)
            return False
        logger.info("다운로드 완료: %d bytes", total)
        return True
    except Exception as e:
        logger.error("Download failed: %s", e)
        return False


def build_update_bat(exe_path, old_path, pid, runtime_dir) -> str:
    """_update.bat 내용을 생성하는 순수 함수 (테스트 가능 — 부수효과 없음).

    [v3.7.248 근본수정] 구 프로세스 완전 사망 후, 새 EXE 기동 '전에' runtime 폴더를 청소한다.
    setup 새설치는 멀쩡한데 업데이트 버튼만 "Failed to load Python DLL"로 깨지던 원인:
      인수인계 중 이전 인스턴스의 node PTY 서버가 채 안 죽고 남아 자기 _MEI\\pty-server를 잠그면,
      새 EXE onefile 부트로더의 추출이 잠긴 잔여물과 충돌 → python DLL 부분 추출 → 부팅 실패 +
      "Failed to remove temporary directory" 경고. 부트로더는 Python보다 먼저라 앱 내부 정리로
      원천 차단 불가 → '교체되는 쪽'이 죽고 난 뒤 bat이 정리해 setup 새설치와 같은 깨끗한 상태를 만든다.
    [안전] node kill은 runtime\\_MEI 경로 + '부모 죽음(고아)'만 대상 → dev/글로벌 node,
      동시 실행 중인 다른 설치 인스턴스의 살아있는 PTY 서버는 절대 안 건드림(v3.7.122 무차별kill 재발 방지).
      폴더 삭제도 python*.dll 없는 '깨진 _MEI'만 → 정상 인스턴스(항상 DLL 존재)는 보호.
    [불변식/테스트 계약] 반환 bat은 순서가 고정: ①구 PID 사망 대기 → ②.old 삭제 →
      ③runtime 청소(powershell) → ④새 EXE start. ③이 ④보다 먼저여야 깨끗한 추출이 보장된다.
    """
    _ps_clean = (
        f"$rt='{runtime_dir}'; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -eq 'node.exe' -and $_.ExecutablePath -like ($rt + '\\_MEI*') "
        "-and -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Start-Sleep -Milliseconds 400; "
        "Get-ChildItem -LiteralPath $rt -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue | "
        "Where-Object { -not (Test-Path (Join-Path $_.FullName 'python*.dll')) } | "
        "ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }"
    )
    return (
        "@echo off\n"
        ":wait\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\n'
        "if not errorlevel 1 (\n"
        "    timeout /t 1 /nobreak >NUL\n"
        "    goto wait\n"
        ")\n"
        f'if exist "{old_path}" del /f /q "{old_path}"\n'
        f'powershell -NoProfile -Command "{_ps_clean}" >NUL 2>&1\n'
        "timeout /t 3 /nobreak >NUL\n"
        f'start "" "{exe_path}"\n'
        'del /f /q "%~f0"\n'
    )


def _looks_like_installer(path) -> bool:
    """[최후방어선] 파일의 PE 버전정보(FileDescription/ProductName)에 'setup'이 있으면 Inno
    인스톨러로 간주. 분류 로직(is_installer_asset)이 어떻게 오판하든, onefile 스왑 경로가
    실수로 인스톨러를 앱 exe로 덮어쓰는 브릭 사고(v3.7.252 코드32 — 실행 시 자기 자신
    덮어쓰기)를 원천 차단한다. 읽기 실패는 전부 안전하게 False(정상 스왑 경로 유지).
    [제약] Windows version.dll 전용 — 다른 플랫폼/실패 시 False라 무해."""
    try:
        import ctypes
        from ctypes import wintypes
        p = str(path)
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(p, None)
        if not size:
            return False
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(p, 0, size, buf):
            return False
        lplp = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                                  ctypes.byref(lplp), ctypes.byref(length)) or not length.value:
            return False
        lang, cp = ctypes.cast(lplp, ctypes.POINTER(wintypes.WORD * 2)).contents[:]
        for field in ("FileDescription", "ProductName"):
            sub = "\\StringFileInfo\\%04x%04x\\%s" % (lang, cp, field)
            val = ctypes.c_void_p()
            vlen = wintypes.UINT()
            if ver.VerQueryValueW(buf, sub, ctypes.byref(val), ctypes.byref(vlen)) and vlen.value:
                if "setup" in ctypes.wstring_at(val, vlen.value - 1).lower():
                    return True
        return False
    except Exception:
        return False


def apply_update_from_temp(new_exe):
    """현재 실행 중인 exe를 새 버전으로 교체하고 재시작합니다.
    Windows는 실행 중인 exe를 덮어쓸 수 없지만 이름 변경은 허용됩니다.
    """
    exe_path = Path(sys.executable).resolve()
    old_path = exe_path.with_suffix(".exe.old")

    logger.info("업데이트 적용 시작: %s → %s", new_exe, exe_path)

    # [최후방어선 v3.7.252] 넘겨받은 파일이 실제 Inno 인스톨러면 절대 앱 exe로 스왑하지 않는다.
    #   (스왑하면 {app}\vibe-coding.exe가 인스톨러가 되어 실행마다 자기 자신 덮어쓰기 코드32로 브릭.)
    #   분류가 어떤 이유로든 여기로 인스톨러를 보내더라도 인스톨러 경로로 우회해 사고를 막는다.
    if new_exe.exists() and _looks_like_installer(new_exe):
        logger.warning("스왑 대상이 Inno 인스톨러로 판별됨 → 인스톨러 경로로 우회: %s", new_exe)
        apply_update_via_installer(new_exe)
        return

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
    runtime_dir = Path(sys._MEIPASS).parent  # %APPDATA%\VibeCoding\runtime — 아래 청소/kill 공용
    bat_content = build_update_bat(exe_path, old_path, pid, runtime_dir)
    with open(bat_path, "w", encoding="mbcs", errors="replace") as f:
        f.write(bat_content)

    # [v3.7.244 사고 방지] 바로 아래 os._exit(0)는 atexit 정리(cleanup_child_procs/
    # cleanup_pyinstaller_temp)를 통째로 건너뛴다 → 이 인스턴스의 node PTY 서버가 좀비로 남아
    # 자기 _MEI\pty-server를 잠그고, _update.bat이 띄우는 새 EXE의 onefile 추출이 잠긴 잔여
    # _MEI와 충돌해 "Failed to load Python DLL"로 부팅 실패한다. 부트로더는 Python보다 먼저라
    # 새 인스턴스 내부 정리로는 못 막으므로, 교체되는 '이 프로세스'가 종료 직전 반드시 정리한다.
    # install 전체가 교체되므로 exclude 없이(자기 _MEI 소속 node 포함) 정리.
    try:
        from infra.pty_process import kill_runtime_mei_orphans
        kill_runtime_mei_orphans(runtime_dir)  # 위에서 계산한 runtime_dir 재사용
    except Exception as _e:
        logger.warning("runtime _MEI 좀비 정리 실패 (무시, 업데이트는 계속): %s", _e)

    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=0x08000000,
        close_fds=True,
    )
    time.sleep(0.8)
    os._exit(0)


def build_installer_cmd(installer_path) -> list:
    """setup EXE를 사일런트로 실행하는 명령을 만드는 순수 함수 (테스트 가능).

    [WHY / 전략 #2a] onedir 전환 후 업데이트 = Inno setup /SILENT 실행. .iss의
    CloseApplications=yes가 실행 중 vibe-coding을 닫고 파일 교체 후 재시작(RestartApplications
    기본 yes)을 담당 → _update.bat·_MEI 청소·좀비 처리가 통째로 불필요해진다.
    [플래그] /SILENT(진행창만, 대화상자 없음)·/SUPPRESSMSGBOXES(확인/오류 자동)·/NOCANCEL(중단 방지).
    /VERYSILENT는 진행창까지 숨김 — 사용자에게 최소 피드백을 주려 /SILENT를 택함.
    """
    return [str(installer_path), "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL"]


def is_installer_asset(path) -> bool:
    """다운로드 자산이 Inno setup 인스톨러인지(파일명에 'setup' 포함) 판별.
    [계약] setup 자산 → 인스톨러 /SILENT 경로, 그 외(update-*.exe) → 구 exe-swap 폴백."""
    return "setup" in Path(path).name.lower()


def apply_update_via_installer(installer_path):
    """setup EXE를 사일런트 실행 후 현재 프로세스를 종료한다. Inno가 앱 교체+재시작 담당.

    [불변식] Popen(detached) → 짧은 대기 → os._exit(0). 우리(vibe-coding)가 살아있으면 Inno
    CloseApplications가 우리를 닫아야 하는데, 먼저 스스로 빠져 파일 잠금을 풀어주면 교체가 매끄럽다.
    [미결] admin 인스톨러라 /SILENT라도 UAC 가능 — Phase C/D에서 per-user 설치로 무프롬프트 검토.
    """
    installer_path = Path(installer_path)
    if not installer_path.exists():
        raise FileNotFoundError(f"인스톨러 파일 없음: {installer_path}")
    if installer_path.stat().st_size < 1_000_000:
        raise ValueError(f"인스톨러 너무 작음 ({installer_path.stat().st_size} bytes) — 손상 의심")
    cmd = build_installer_cmd(installer_path)
    logger.info("인스톨러 사일런트 실행: %s", cmd)
    subprocess.Popen(cmd, creationflags=0x08000000, close_fds=True)
    time.sleep(0.8)
    os._exit(0)


def apply_downloaded_update(asset_path, is_installer=None):
    """다운로드된 업데이트 자산을 적용하는 디스패처.

    setup 인스톨러면 /SILENT 실행(onedir 모델), 아니면 구 exe-swap(onefile 폴백).
    [WHY 디스패처] 점진 전환 — CI가 setup을 update 자산으로 내보내기 전(구 릴리즈)에도, 이후에도
    같은 코드가 자산 종류만 보고 올바른 경로를 택해 호환성을 유지한다.
    [불변식] is_installer가 주어지면 그 값을 신뢰(update_ready.json의 명시 플래그). None이면
      파일명으로 폴백 판정 — 단, 다운로드 파일명이 인스톨러 여부를 보존하도록 이미 이름지어져 있어
      폴백도 정확하다. (v3.7.252: tmp를 vibe-coding.exe.new로 고정해 setup을 onefile로 오판 →
      인스톨러가 앱 exe로 스왑되어 실행 시 코드32 사고. 명시 플래그 + 파일명 보존 이중 방어.)
    """
    if is_installer is None:
        is_installer = is_installer_asset(asset_path)
    if is_installer:
        apply_update_via_installer(asset_path)
    else:
        apply_update_from_temp(Path(asset_path))


def check_and_update(data_dir):
    """메인 엔트리포인트 — 백그라운드 스레드에서 호출.
    EXE(frozen) 모드에서만 동작. 개발 모드에서는 스킵.
    """
    ready_file = data_dir / "update_ready.json"

    # [불변식] 비교 기준은 **번들 버전**뿐 — APP_VERSION(모듈 import)은 boot.py 체크아웃 소스를
    #   가리킬 수 있어 soft 채널 적용 후 항상 "최신"으로 오판한다. bundle_version() 참조.
    cur_ver = bundle_version()

    if cur_ver == "dev":
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
    if not _is_newer(latest_tag, cur_ver):
        logger.info("Already up to date (bundle=%s, module=%s).", cur_ver, APP_VERSION)
        try:
            ready_file.unlink()
        except Exception:
            pass
        return

    logger.info("New version available: %s (bundle: %s, module: %s)",
                latest_tag, cur_ver, APP_VERSION)

    asset = _find_asset(release)
    if not asset:
        logger.warning("Release %s has no update asset.", latest_tag)
        with open(ready_file, "w", encoding="utf-8") as f:
            json.dump({"ready": False, "downloading": False,
                       "last_error": f"릴리즈 {latest_tag}에 업데이트 에셋 없음",
                       "last_check": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
        return
    asset_url = asset.get("browser_download_url") or asset.get("url")
    asset_name = asset.get("name", "")

    # 다운로드 중 상태 알림
    with open(ready_file, "w", encoding="utf-8") as f:
        json.dump({"version": latest_tag, "ready": False, "downloading": True}, f)

    # [불변식] 임시 파일명이 인스톨러 여부를 보존해야 apply 단계가 오판하지 않는다.
    #   is_installer_asset은 파일명의 'setup' 포함 여부로만 갈리므로, setup 자산은 반드시
    #   'setup'을 포함한 이름으로 저장한다. (v3.7.252 코드32 사고 근본수정 — 자산명은
    #   원본 asset_name으로 판정하고, 최종 update_ready.json에도 is_installer를 명시 저장.)
    is_installer = is_installer_asset(asset_name)
    tmp_name = "vibe-coding-setup.exe.new" if is_installer else "vibe-coding.exe.new"
    tmp_path = data_dir / tmp_name

    # [진행률] 다운로드 중 update_ready.json에 percent를 기록 → 프론트 진행바.
    # 매 청크마다 파일을 쓰면 과도하므로 1% 단위 변화 또는 0.5초 간격으로 스로틀.
    _prog_state = {"pct": -1, "ts": 0.0}

    def _write_progress(done, total_bytes):
        pct = int(done * 100 / total_bytes) if total_bytes else -1
        now = time.time()
        if pct == _prog_state["pct"] and (now - _prog_state["ts"]) < 0.5:
            return
        _prog_state["pct"] = pct
        _prog_state["ts"] = now
        try:
            with open(ready_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": latest_tag, "ready": False, "downloading": True,
                    "percent": pct,  # -1이면 총 크기 미상(진행바 대신 스피너)
                    "downloaded_mb": round(done / 1_048_576, 1),
                    "total_mb": round(total_bytes / 1_048_576, 1) if total_bytes else 0,
                }, f)
        except Exception:
            pass

    if not _download_asset(asset_url, tmp_path, token, progress_cb=_write_progress):
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
            "exe_path": str(tmp_path),
            # apply 단계가 파일명 추측 대신 이 플래그로 인스톨러/exe-swap을 확정 분기.
            "is_installer": is_installer,
        }, f)
