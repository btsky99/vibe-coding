"""
FILE: infra/env_path.py
DESCRIPTION: 실행 중인 프로세스의 PATH를 Windows 레지스트리 + 알려진 CLI bin 디렉토리 기준으로
             다시 읽어 병합한다. CLI 자동 설치(npm -g / agy 공식 인스톨러 / claude 네이티브
             인스톨러) 직후 서버가 재시작 없이 새 명령을 인식하게 하는 것이 유일한 목적.

             외부 공개 API:
               - refresh_path(force=False) : PATH 재병합(TTL 캐시). 갱신했으면 True
               - known_cli_dirs()          : 설치기가 PATH에 추가하는 디렉토리 목록

REVISION HISTORY:
- 2026-08-05 Claude: 신규 — 설치가 실제로 성공해도 배너가 '설치 필요'에 고착되던 결함 수정.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# [핵심 WHY — 이 모듈이 존재하는 이유]
#   Windows 설치기(npm -g, agy install.ps1, claude 네이티브 인스톨러)는 **사용자 레지스트리
#   PATH만** 갱신한다. 반면 이미 떠 있는 프로세스의 os.environ['PATH']는 프로세스 생성 시점의
#   스냅샷이라 영원히 낡은 값을 본다. 그 결과 설치가 실제로 성공해도 서버 쪽 shutil.which()가
#   계속 None을 반환 → SetupBanner가 '설치 필요'에 고착되고 3초 폴링이 auto-install을 무한
#   재시도했다. "앱을 재시작해야만 인식된다"는 증상의 정체가 이것이다.
# [제약] 설치기를 띄우는 쪽(새 콘솔 프로세스)은 이 문제가 없다 — 새 프로세스는 최신 PATH를
#   상속받기 때문. 고쳐야 하는 곳은 **감지하는 쪽(서버 프로세스)**뿐이다.

# [WHY TTL] 감지 API는 3초 폴링으로 불리고 도구마다 호출된다. 레지스트리 읽기는 싸지만
#   호출 횟수가 N배라 짧은 캐시를 둔다. 폴링 주기(3s)보다 커야 매 폴링당 1회로 수렴한다.
_TTL_SECONDS = 5.0
_last_refresh = 0.0


def known_cli_dirs() -> list[str]:
    """설치기가 PATH에 새로 추가하는 디렉토리 중 **실제로 존재하는 것**만 반환한다.

    [WHY 레지스트리만으로 부족한가] 인스톨러가 PATH 레지스트리 쓰기에 실패하거나(권한/정책),
      setx 반영이 늦어도 바이너리는 이미 디스크에 있다. 이 보강이 그 간극을 덮는다.
    [실측 근거 2026-08-05] claude=~/.local/bin, agy=%LOCALAPPDATA%/agy/bin, npm -g=%APPDATA%/npm.
      셋 다 이 PC에서 확인함. npm -g는 claude/codex 양쪽의 산출물 위치이기도 하다.
    [불변식] 존재하지 않는 경로는 넣지 않는다 — PATH 오염 방지. 설치 직후 생성되는 경로는
      다음 refresh(최대 TTL 뒤)에 자연히 잡히므로 손해가 없다.
    """
    home = Path.home()
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")

    if os.name == "nt":
        raw: list[Path | None] = [
            Path(program_files) / "nodejs",
            Path(appdata) / "npm" if appdata else None,
            Path(localappdata) / "agy" / "bin" if localappdata else None,
            home / ".local" / "bin",
        ]
    else:
        raw = [
            home / ".local" / "bin",
            home / ".npm-global" / "bin",
            Path("/usr/local/bin"),
        ]

    dirs: list[str] = []
    for path in raw:
        if path is None:
            continue
        try:
            if path.is_dir():
                dirs.append(str(path))
        except OSError:
            # [제약] 네트워크 드라이브/권한 오류로 is_dir()이 던질 수 있다. 감지 실패는
            #   치명적이지 않으므로 조용히 건너뛴다(설치 자체를 막으면 안 됨).
            continue
    return dirs


def _registry_paths() -> list[str]:
    """HKLM(시스템) + HKCU(사용자) 레지스트리의 Path 값을 읽어 항목 리스트로 반환.

    [제약] Windows 전용. 비Windows에서는 빈 리스트 — POSIX는 부모 셸 PATH가 곧 진실이라
      다시 읽을 원천이 없다(known_cli_dirs 보강으로 충분).
    [WHY expandvars] 레지스트리 PATH는 %SystemRoot% 같은 미확장 변수를 그대로 담는다.
      확장하지 않으면 shutil.which가 해당 항목을 통째로 놓친다.
    """
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    entries: list[str] = []
    for hive, key_name in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        entries.extend(os.path.expandvars(value).split(os.pathsep))
    return entries


def refresh_path(force: bool = False) -> bool:
    """os.environ['PATH']에 레지스트리 PATH와 알려진 CLI bin 디렉토리를 병합한다.

    Returns: 실제로 갱신했으면 True, TTL 내라 건너뛰었으면 False.

    [불변식] **기존 PATH 항목이 항상 앞에 온다.** dict.fromkeys는 순서 보존 dedup이므로
      current를 먼저 넣으면 기존 명령 해석 결과가 절대 바뀌지 않는다. 이 순서를 뒤집으면
      번들 node(boot.py가 앞에 주입)보다 시스템 node가 먼저 잡혀 버전이 뒤바뀐다.
    [제약] 이 함수는 프로세스 전역 상태(os.environ)를 바꾼다. 락은 걸지 않는다 — 병합 결과가
      멱등이라 경합해도 최종 값이 같기 때문. 대신 _last_refresh 갱신은 병합 **전에** 해서
      동시 진입 시 중복 레지스트리 읽기를 줄인다.
    """
    global _last_refresh
    now = time.monotonic()
    if not force and (now - _last_refresh) < _TTL_SECONDS:
        return False
    _last_refresh = now

    current = os.environ.get("PATH", "").split(os.pathsep)
    merged = [part for part in (current + _registry_paths() + known_cli_dirs()) if part]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(merged))
    return True
