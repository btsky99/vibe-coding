"""
FILE: .ai_monitor/boot.py
DESCRIPTION: 경량 소스 업데이트 채널(A안)의 EXE 진입점 부트스트랩.
  앱 코드를 frozen PYZ에서 분리하고, 관리형 git 체크아웃(또는 번들 seed)의 .py를
  runpy로 실행하여 "git push → 버튼 클릭"만으로 설치본을 갱신 가능하게 한다.
  의존성(pywebview/psycopg/...)만 frozen 유지되고, 앱 .py는 항상 체크아웃에서 로드된다.

REVISION HISTORY:
- 2026-08-18 Claude: `vibe-coding.exe <script.py>` 의 예외가 PyInstaller 부트로더 창으로
  올라가 무인 설치를 멈추던 것 — 트레이스백을 파일로 남기고 종료 코드 1로 끝낸다.
- 2026-08-18 Claude: EXE 풀빌드도 '받아두면 다음 시작 때 자동 적용'으로 — 소스 채널만
  자동이던 비대칭 탓에 설치본이 일곱 판 뒤처져 있었다(_apply_staged_full_update).
- 2026-08-16 Claude: 표준 출력 인코딩 방어 — cp949 가 줄표를 못 담아 print 가 예외를 내고
  설치본이 보이지 않는 모달 대화상자에서 영구 정지하던 사고(_make_stdio_encoding_safe).
- 2026-07-29 Codex: Acquire an early Windows mutex before slow first-run boot work.
- 2026-07-29 Codex: Expose installer-bundled Node/npm and global AI CLI shims on PATH.
- 2026-06-24 Claude: 최초 작성 — 경량 소스 업데이트 채널(A안) Task 2~3.
  메모리 project_soft_update_channel / 계획 ai_monitor_plan.md 참조.
"""
# [핵심 불변식] 이 파일은 앱 모듈(api/src/infra/server)을 **정적 import 하지 않는다**.
#   → PyInstaller Analysis가 앱 코드를 PYZ에 안 넣음 → import가 체크아웃 PathFinder로 해결됨.
#   여기서 무심코 `from api ...` 등을 추가하면 frozen 우선순위가 부활해 A안 전체가 깨진다.
import os
import sys
import shutil
import runpy
import subprocess
from pathlib import Path

_EARLY_INSTANCE_MUTEX = None


def _acquire_early_windows_instance_mutex() -> None:
    """Prevent two frozen GUI instances from racing before server.py takes its lock."""
    global _EARLY_INSTANCE_MUTEX
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    import ctypes

    mutex = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Local\\VibeCoding.MainWindow"
    )
    if not mutex:
        return
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(mutex)
        os._exit(0)
    _EARLY_INSTANCE_MUTEX = mutex


def _make_stdio_encoding_safe() -> None:
    """표준 출력이 한글·줄표를 못 담는 인코딩이어도 print 가 앱을 죽이지 않게 한다.

    [🔴 과거사고 2026-08-16 — 이것 때문에 설치본이 통째로 안 떴다] boot.py 의 안내 문구에
      줄표(—)가 들어 있는데, 부모가 stdout 을 파이프·파일로 넘기면 그 스트림이 시스템
      기본 인코딩(한국어 윈도우 = cp949)으로 잡힌다. cp949 는 U+2014 를 못 담아
      **print 한 줄이 UnicodeEncodeError 를 던지고, GUI 모드라 그 예외가 화면 없는
      모달 대화상자('Unhandled exception in script')로 떠서 프로세스가 영원히 멈춘다.**
      로그도 안 남는다 — 실패 지점이 로깅 초기화보다 앞이기 때문이다.
    [🔴 왜 '문구에서 — 를 빼기'가 답이 아닌가] 그건 이번 한 줄만 막는다. 이 파일은
      앱 전체의 진입점이고 앞으로도 한글 안내를 계속 찍는다. 스트림 자체를 안전하게
      만들어야 다음 문장이 같은 함정을 밟지 않는다.
    [제약] GUI(windowed) 프로즌 실행에서는 sys.stdout 이 None 이거나 reconfigure 가
      없을 수 있다 — 그때는 조용히 넘어간다. 여기서 예외가 나면 본말전도다.
    [불변식] 어떤 print 보다도 먼저 불려야 한다. main() 첫 줄인 이유다.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, AttributeError):
            pass                                   # 못 바꿔도 부팅은 계속한다


def _inject_bundled_node_path() -> None:
    """Expose bundled Node/npm and npm global command shims to the installed app."""
    if not getattr(sys, "frozen", False):
        return
    app_dir = Path(sys.executable).resolve().parent
    candidates = [app_dir / "nodejs", Path(os.environ.get("APPDATA", "")) / "npm"]
    current = os.environ.get("PATH", "").split(os.pathsep)
    additions = [str(path) for path in candidates if path.is_dir()]
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(additions + current))

REPO_URL = "https://github.com/btsky99/vibe-coding.git"
APP_REL = os.path.join(".ai_monitor", "server.py")  # 체크아웃 기준 메인 엔트리 상대경로
ROLLBACK_FILE = ".soft_rollback"  # soft_updater가 apply 직전 직전 SHA를 여기에 기록
STAGED_FILE = ".soft_staged"  # soft_updater가 미리 받아둔(fetch만 끝난) 대상 SHA
FULL_READY_FILE = "update_ready.json"          # updater가 받아 둔 setup 인스톨러 기록(앱 데이터 폴더)
FULL_ATTEMPT_FILE = "update_apply_attempt.json"  # 같은 판을 몇 번 시도했나 — 무한 재설치 방지
FULL_ATTEMPT_MAX = 2                           # 이 횟수를 넘으면 자동 적용을 포기하고 그냥 뜬다
SCRIPT_ERROR_LOG = "daemon_script_errors.log"  # `vibe-coding.exe <script.py>` 가 터진 기록(append)


# [PyInstaller 의존성 노출] boot.py가 진입점이 되면 앱 코드를 정적 import 하지 않으므로
#   server.py가 끌어오던 3rd-party 자동탐색이 끊긴다. 아래 `if False:` 블록은 **실행되지 않지만**
#   PyInstaller modulegraph가 AST에서 import문을 수집 → 해당 패키지+transitive를 PYZ에 번들한다.
#   (실제 import와 동일 효과, 단 런타임 비용/실행 없음.) 앱 .py만 SRC에서 로드되고 의존성은 frozen.
# [불변식] 여기에는 **3rd-party만** 나열한다(앱 모듈 금지 — 넣으면 frozen 우선순위 부활).
# [제외] PySide6/textual은 dashboard_window/TUI가 별도 python 서브프로세스로만 쓰므로
#   현재 frozen 클로저에 없음(설치본은 python 있을 때만 동작) → 의도적으로 제외(Qt 대용량 회피).
# [동기화 의무] 이 목록을 바꾸면 vibe-coding.spec hiddenimports / build-release.yml --hidden-import도
#   함께 갱신(과거사고 v3.7.215~218: 한쪽만 바꿔 EXE 런타임 ImportError).
if False:  # noqa: SIM223 — 의도적 정적-탐색 전용 블록 (런타임 미실행)
    import webview            # pywebview — 데스크톱 UI 코어
    import clr                # pythonnet — pywebview EdgeChromium 백엔드(Windows)
    import psycopg2           # PostgreSQL
    import watchdog           # 파일 감시
    import dotenv             # .env 로드
    import rich               # 콘솔 출력
    import websockets         # WS PTY
    import winpty             # 터미널 PTY
    import win32com           # pywin32 — 바로가기/COM
    import win32api           # pywin32
    import win32con           # pywin32
    import pythoncom          # pywin32
    import numpy              # fastembed 의존
    import fastembed          # 회상 v2 임베딩
    import onnxruntime        # fastembed 런타임
    import tokenizers         # fastembed 토크나이저
    import filelock           # 파일 락(일부 스크립트)
    import PIL                # Pillow(아이콘/이미지 처리)
    # [음성 2026-08-16] 사이드카(voice-server/voice_server.py)가 쓰는 것들. 사이드카는 별도
    #   프로세스지만 frozen 에서는 **이 EXE 가 그 스크립트의 실행기**다
    #   (api/voice_api._sidecar_python → boot.main() 의 .py 분기). 그래서 이 클로저 안에
    #   있어야 import 된다. 빠지면 앱은 멀쩡한 채 음성만 조용히 죽는다.
    import edge_tts           # 낭독 TTS — 유일한 낭독 엔진
    import faster_whisper     # 받아쓰기 STT
    import ctranslate2        # faster-whisper 런타임(네이티브)
    import av                 # faster-whisper 오디오 디코딩(FFmpeg 바인딩)
    import aiohttp            # edge-tts 가 MS 서버와 통신
    import huggingface_hub    # whisper 모델 내려받기


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _bundle_seed_root() -> Path:
    """EXE에 동봉된 소스 스냅샷(= 이 EXE가 빌드될 때의 .py 트리) 루트.
    [제약] frozen: spec datas의 `_appseed/`. dev: 리포 루트(boot.py의 상위의 상위).
    게이트 실패/오프라인 최초부팅 시 이 트리에서 실행하거나 SRC로 복사한다.
    """
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", "")) / "_appseed"
    return Path(__file__).resolve().parent.parent


def _managed_src_root() -> Path:
    """앱이 실제로 실행될 소스 체크아웃 위치.
    [제약] dev(비frozen)는 리포 자체를 in-place 사용 — LOCALAPPDATA로 클론하지 않음
      (개발 중 두 트리 분기/혼동 방지). frozen은 dev 트리와 분리된 전용 관리 경로.
    VIBE_SRC_DIR 환경변수로 강제 오버라이드 가능(테스트/특수 배치용).
    """
    override = os.environ.get("VIBE_SRC_DIR")
    if override:
        return Path(override)
    if not _is_frozen():
        return Path(__file__).resolve().parent.parent
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "VibeCoding" / "app"


def _is_checkout(root: Path) -> bool:
    return (root / ".ai_monitor" / "server.py").exists()


def _load_current_version() -> str:
    """현재 EXE(번들)의 _version. 게이트 비교 기준 = "이 EXE가 실행 가능한 코드 한도".
    [불변식] SRC가 아닌 **번들** 버전을 읽어야 함 — SRC는 더 최신일 수 있고,
      게이트의 목적이 바로 'SRC가 이 EXE보다 너무 앞서면 차단'이기 때문.
    """
    candidates = [
        _bundle_seed_root() / ".ai_monitor" / "_version.py",
        Path(getattr(sys, "_MEIPASS", "")) / "_version.py",
        Path(__file__).resolve().parent / "_version.py",
    ]
    for c in candidates:
        try:
            if c.exists():
                ns: dict = {}
                exec(c.read_text(encoding="utf-8"), ns)  # noqa: S102 — 신뢰된 번들 파일
                v = ns.get("__version__")
                if v:
                    return str(v)
        except Exception:
            continue
    return "0.0.0"


def _ver_tuple(tag: str) -> tuple:
    out = []
    for p in str(tag).lstrip("v").strip().split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _gate_ok(src: Path) -> bool:
    """SRC의 soft_manifest.min_exe 가 현재 EXE 버전보다 높으면 차단(False).
    [과거사고 방지] 의존성/C확장/부트스트랩이 바뀐 소스를 옛 EXE가 받아 실행하면
      ImportError/크래시 → min_exe 게이트로 풀빌드를 강제한다.
    manifest 없거나 파싱 실패 시엔 통과(게이트는 명시적 차단만) — 구버전 소스 호환.
    """
    manifest = src / "soft_manifest.json"
    try:
        if not manifest.exists():
            return True
        import json
        min_exe = json.loads(manifest.read_text(encoding="utf-8")).get("min_exe", "0.0.0")
        return _ver_tuple(_load_current_version()) >= _ver_tuple(min_exe)
    except Exception:
        return True


def _git(args: list, cwd=None, timeout=300) -> bool:
    """git 서브커맨드 실행. git 미설치/실패는 False(예외 전파 안 함)."""
    if not shutil.which("git"):
        return False
    # [macOS 즉사 방지 2026-07-24] 폴백이 0x08000000이라 POSIX에서도 0이 아닌 값이
    # creationflags로 전달됐다. POSIX subprocess는 creationflags != 0이면
    # ValueError를 던지므로, frozen 맥 앱은 부팅 중 이 함수에서 바로 죽는다.
    # 비윈도우는 반드시 0. (proc.py:18과 동일 관용구 — 새 subprocess 호출 시 재사용할 것)
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        # [버그수정 2026-08-07] encoding 미지정이면 text=True가 **로케일 인코딩**(한국어 Windows는
        #   cp949)으로 디코드한다. git이 한글 메시지나 UTF-8 파일명을 뱉는 순간 리더 스레드가
        #   UnicodeDecodeError로 죽고, 그 예외를 아래 except가 삼켜 False를 반환한다.
        #   → 정상 실행된 git이 '실패'로 보여 예약 업데이트가 조용히 건너뛰어진다.
        #   실제로 E2E 검증 중 재현됐다. soft_updater._git과 같은 규약(utf-8/replace)으로 맞춘다.
        r = subprocess.run(["git"] + args, cwd=cwd and str(cwd),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=no_win)
        return r.returncode == 0
    except Exception:
        return False


def _seed_into(src: Path) -> bool:
    """번들 seed → SRC 복사(오프라인 최초부팅 폴백). .git 없는 working tree가 됨.
    [제약] 이렇게 만든 SRC는 git 체크아웃이 아니므로 soft 업데이트(apply)는
      soft_updater가 clone으로 승격하기 전까지 비활성. 부팅 자체는 보장된다.
    """
    seed = _bundle_seed_root()
    if not _is_checkout(seed):
        return False
    try:
        src.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seed, src, dirs_exist_ok=True)
        return _is_checkout(src)
    except Exception:
        return False


def _ensure_src(src: Path) -> Path:
    """메인 앱용 SRC 보장: 있으면 그대로, 없으면 clone, 실패 시 seed 복사.
    최후엔 번들 seed 경로를 그대로 반환(in-place 실행)한다.
    """
    if _is_checkout(src):
        return src
    if _is_frozen() and not src.exists() and _git(["clone", "--depth", "50", REPO_URL, str(src)]):
        if _is_checkout(src):
            return src
    if _seed_into(src):
        return src
    seed = _bundle_seed_root()
    return seed if _is_checkout(seed) else src


def _app_data_dir() -> Path:
    """앱 데이터 폴더(%APPDATA%/VibeCoding). updater 가 update_ready.json 을 두는 곳.

    [WHY 직접 계산하나] boot.py 는 앱 모듈을 import 하지 않는다(파일 최상단 핵심 불변식).
      server.DATA_DIR 을 쓰려면 server 를 import 해야 하는데, 그러면 PyInstaller Analysis 가
      앱 코드를 PYZ 에 넣어 A안 전체가 깨진다. json 파일 경로 하나라 베끼는 값이 싸다.
    [불변식] server.py 의 DATA_DIR 규칙과 같아야 한다 — 어긋나면 받아 둔 것을 못 찾는다.
    """
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "VibeCoding"
    return Path.home() / ".vibe-coding"


def _apply_staged_full_update() -> None:
    """받아 둔 setup 인스톨러가 있으면 **앱을 띄우기 전에** 조용히 깔고 빠진다.

    [WHY 이걸 만들었나 — 2026-08-18 사장 결재 34] 소스 채널(_apply_staged_update)은 이미
      "받아두면 다음 시작 때 자동 적용"인데 EXE 채널만 사람이 단추를 눌러야 했다. 그 비대칭의
      대가를 실측으로 봤다 — 사장님 PC 는 EXE v3.7.341 인데 소스만 v3.7.348 로 혼자 최신이었고,
      그 사이 일곱 판이 나갔다. 단추를 안 누르면 영원히 뒤처진다.
    [WHY 부팅 시점인가] 이때는 앱이 아직 파일을 안 잡고 있어 Inno 가 교체하기 가장 쉽다.
      앱이 뜬 뒤에 깔면 사용자가 또 한 번 껐다 켜야 해서 반쪽짜리다.
    [🔴 불변식 — 여기서 실패해도 앱은 반드시 뜬다] 예외를 밖으로 던지지 않는다.
      사장님 PC 가 안 뜨면 그날 일이 통째로 멈춘다. 적용이 안 되면 옛 판으로 그냥 뜨고
      사유만 update_ready.json 에 남긴다(화면이 그 값을 읽어 띄운다).
    [🔴 불변식 — 무한 재설치 금지] 설치가 실패했는데(UAC 취소·권한·손상) 판이 그대로면
      다음 부팅에서 또 깔려 든다. 그러면 앱이 영영 안 뜬다. 그래서 시도 횟수를 **띄우기
      전에** 기록하고, FULL_ATTEMPT_MAX 를 넘으면 자동 적용을 포기한다 — 단추는 남겨 둔다.
      기록을 나중에 하면 설치 중 프로세스가 죽었을 때 횟수가 안 늘어 같은 루프에 갇힌다.
    """
    if not _is_frozen():
        return
    try:
        import json

        data_dir = _app_data_dir()
        ready_file = data_dir / FULL_READY_FILE
        if not ready_file.exists():
            return
        info = json.loads(ready_file.read_text(encoding="utf-8")) or {}
        if not info.get("ready"):
            return
        # [WHY 토글을 읽나] 소스 채널은 '예약을 안 만드는' 방식으로 토글을 걸지만, EXE 채널은
        #   받아두기가 토글과 무관하게 돈다. 그래서 끄는 자리가 여기밖에 없다.
        #   config.json 은 그냥 json 파일이라 읽어도 앱 모듈 import 가 아니다(불변식 유지).
        try:
            cfg = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        if not bool(cfg.get("full_auto_update", True)):
            return

        target = str(info.get("version", "")).lstrip("v").strip()
        attempt_file = data_dir / FULL_ATTEMPT_FILE
        if not target or _ver_tuple(target) <= _ver_tuple(_load_current_version()):
            # 깔 것이 없다 = 지난번 시도가 결국 성공했거나 다른 길로 깔렸다.
            # 시도 기록을 지워야 **다음 판**이 처음부터 두 번의 기회를 갖는다.
            try:
                attempt_file.unlink(missing_ok=True)
            except OSError:
                pass
            return
        exe_path = Path(str(info.get("exe_path") or ""))
        if not exe_path.exists() or exe_path.stat().st_size < 1_000_000:
            return                                  # 없거나 잘린 파일 — updater 가 다시 받는다
        # [불변식] setup 인스톨러만 이 길로 보낸다. onefile 자산의 exe-swap 은 updater 쪽
        #   경로라 여기서 흉내 내지 않는다(v3.7.252 코드32 사고를 다시 부르지 않기 위해).
        is_installer = info.get("is_installer")
        if is_installer is None:
            is_installer = "setup" in exe_path.name.lower()
        if not is_installer:
            return

        tried = 0
        try:
            prev = json.loads(attempt_file.read_text(encoding="utf-8")) or {}
            if str(prev.get("version", "")).lstrip("v") == target:
                tried = int(prev.get("count") or 0)
        except Exception:
            tried = 0
        if tried >= FULL_ATTEMPT_MAX:
            # [🔴 update_ready.json 에 적으면 안 된다 — 2026-08-18 실측] 그 파일의 주인은
            #   updater 다. 앱이 뜨자마자(10분 주기의 첫 회) check_and_update 가 통째로
            #   덮어써서 사유가 **몇 초 만에 사라졌다.** 실측으로 그 덮어쓰기를 봤다.
            #   그래서 내가 소유한 이 파일에 적고, api/update_api.py 가 응답에 얹어 준다.
            try:
                attempt_file.write_text(json.dumps({
                    "version": target, "count": tried, "gave_up": True,
                    "detail": (f"새 판 {target} 자동 설치가 {tried}번 실패했습니다. "
                               "옛 판으로 실행합니다 — '지금 업데이트'를 눌러 직접 깔아 주세요"),
                }, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return

        # [순서 불변식] 기록이 먼저다. 위 주석 참조.
        try:
            attempt_file.write_text(
                json.dumps({"version": target, "count": tried + 1}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return                                  # 횟수를 못 세면 시도하지 않는다(루프 위험)

        print(f"[boot] 받아 둔 새 판 {target} 을(를) 조용히 설치합니다(시도 {tried + 1}).")
        # [규칙 10] 사람이 누른 실행이 아니다 — CREATE_NO_WINDOW(0x08000000) 필수.
        #   플래그는 updater.build_installer_cmd 와 같은 값을 쓴다(양쪽 수동 동기).
        subprocess.Popen(
            [str(exe_path), "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL"],
            creationflags=0x08000000,
            close_fds=True,
        )
        # Inno 의 CloseApplications 가 우리를 닫기 전에 스스로 빠져 파일 잠금을 풀어 준다.
        import time as _t

        _t.sleep(0.8)
        os._exit(0)
    except Exception as e:                          # noqa: BLE001
        # 여기서 죽으면 앱이 안 뜬다. 사유만 남기고 옛 판으로 계속 간다.
        print(f"[boot] 새 판 자동 설치 건너뜀: {type(e).__name__}: {e}")


def _apply_staged_update(src: Path) -> str:
    """앱을 띄우기 **전에** 미리 받아둔 업데이트를 적용한다. 적용한 SHA 또는 "".

    [WHY 여기인가] 사용자가 원한 건 "재시작하면 알아서 최신". 앱이 뜬 뒤에 적용하면
      또 한 번 껐다 켜야 해서 반쪽짜리다. 그래서 server.py를 runpy 하기 전에 트리를 옮긴다.
    [WHY 네트워크를 안 타나] 무거운 fetch는 앱이 떠 있는 동안 soft_updater.stage_soft_update가
      이미 끝내 뒀다. 여기 남은 건 로컬 reset뿐이라 수십 ms — 부팅 체감이 없다.
      부팅 경로에 네트워크를 넣으면 오프라인/느린 회선에서 매번 앱 실행이 지연된다.
    [WHY 토글을 안 읽나] 자동 적용 on/off는 **예약 시점**(서버, config 접근 가능)에서 이미
      걸린다. 꺼져 있으면 예약 파일 자체가 생기지 않는다 → 부팅 경로는 설정을 몰라도 된다.
      boot.py가 앱 모듈을 import 못 하는 A안 불변식과도 맞는다.
    [불변식] 여기서 실패해도 절대 예외를 밖으로 던지지 않는다 — 업데이트 실패가 앱 실행
      자체를 막으면 사용자는 복구 수단을 잃는다. 실패 시 조용히 현재 트리로 진행한다.
    """
    marker = src / STAGED_FILE
    if not marker.exists():
        return ""
    # dev 트리 보호 — soft_updater._channel_block_reason과 같은 기준.
    # (dev 리포에 예약 파일이 잘못 생겨도 D:\vibe-coding을 reset 하지 않는다)
    if not _is_frozen() and not os.environ.get("VIBE_SRC_DIR", "").strip():
        return ""
    try:
        import json
        sha = (json.loads(marker.read_text(encoding="utf-8")) or {}).get("sha") or ""
    except Exception:
        sha = ""
    if not sha:
        try:
            marker.unlink()
        except Exception:
            pass
        return ""

    # [유실 방지] 예약 시점에도 검사했지만 그 사이 트리가 바뀌었을 수 있어 직전에 한 번 더 본다.
    #   HEAD가 대상의 조상이 아니면 = 원격에 없는 로컬 커밋이 있다 → reset 시 고아화(2026-07-03 사고).
    if not _git(["merge-base", "--is-ancestor", "HEAD", sha], cwd=src):
        print("[boot] 예약 업데이트에 로컬 전용 커밋 충돌 — 적용 건너뜀")
        try:
            marker.unlink()
        except Exception:
            pass
        return ""

    # 롤백 지점 기록 — 새 코드로 부팅하다 죽으면 _run_main_app이 이 SHA로 되돌린다.
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(src), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30,
                           creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                          if sys.platform == "win32" else 0))
        prev = (r.stdout or "").strip()
        if prev:
            (src / ROLLBACK_FILE).write_text(prev, encoding="utf-8")
    except Exception:
        pass

    if not _git(["reset", "--hard", sha], cwd=src):
        print("[boot] 예약 업데이트 reset 실패 — 현재 코드로 계속 진행")
        return ""
    try:
        marker.unlink()
    except Exception:
        pass
    print(f"[boot] 소스 업데이트 적용됨 → {sha[:7]}")
    return sha


def _inject_paths(src: Path) -> None:
    """체크아웃이 frozen 번들보다 먼저 잡히도록 sys.path 최우선 삽입.
    [불변식] .ai_monitor 가 index 0 — server.py가 `from api/src/infra`를 여기서 해결.
      src(리포 루트)도 추가 — 일부 도구가 `from scripts...`/패키지 경로를 기대할 때 대비.
    """
    for p in (str(src), str(src / ".ai_monitor")):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)


def _runpy_entry(entry: Path, argv: list) -> None:
    sys.argv = [str(entry)] + list(argv)
    runpy.run_path(str(entry), run_name="__main__")


def _run_main_app(passthrough: list) -> None:
    """메인 앱(인자 없음 또는 --install 등 서브커맨드) 실행 경로."""
    # [순서] 풀빌드(EXE) 적용이 **가장 먼저**다. 성공하면 이 프로세스는 여기서 끝나므로
    #   아래 clone/fetch 비용을 아예 안 낸다. 그리고 새 EXE 가 뜬 뒤에 소스 채널이 돈다.
    _apply_staged_full_update()
    src = _ensure_src(_managed_src_root())
    # [순서 불변식] 게이트 검사보다 **먼저** 적용해야 한다. 적용 후의 트리가 곧 실행 대상이고,
    #   게이트는 "이 EXE가 그 트리를 실행해도 되는가"를 묻기 때문. 반대로 하면 새 소스의
    #   min_exe가 아니라 옛 소스의 min_exe로 판정해 위반 소스를 그대로 실행하게 된다.
    _apply_staged_update(src)
    if not _gate_ok(src):
        # SRC가 이 EXE보다 너무 최신 → 번들 seed(이 EXE의 동봉 소스)로 폴백 실행.
        print("[boot] soft_manifest.min_exe > 현재 EXE 버전 — 풀빌드 업데이트 필요. 번들 소스로 실행.")
        src = _bundle_seed_root()
    _inject_paths(src)
    entry = src / ".ai_monitor" / "server.py"
    try:
        _runpy_entry(entry, passthrough)
    except SystemExit:
        raise
    except Exception as e:
        # [롤백] soft 업데이트 직후 부팅 실패 추정 → 직전 SHA로 reset 후 1회 재시도.
        print(f"[boot] 메인 앱 부팅 실패: {e}. 롤백 시도.")
        rb = src / ROLLBACK_FILE
        prev = rb.read_text(encoding="utf-8").strip() if rb.exists() else ""
        if prev and _git(["reset", "--hard", prev], cwd=src):
            try:
                rb.unlink()
            except Exception:
                pass
            _runpy_entry(entry, passthrough)
            return
        # 그래도 실패 → 번들 seed로 최종 폴백
        seed = _bundle_seed_root()
        if _is_checkout(seed) and seed != src:
            _inject_paths(seed)
            _runpy_entry(seed / ".ai_monitor" / "server.py", passthrough)
            return
        raise


def _run_hook(argv: list) -> None:
    """`vibe-coding.exe hook` 빠른 경로 — clone 금지, 번들 seed에서 즉시 실행.
    [제약] 매 훅 호출당 startup 비용이 커지면 안 됨 → 네트워크/clone 절대 금지.
      server.py 최상단의 hook 디스패치가 MEIPASS/scripts를 직접 써서 즉시 종료한다.
    """
    seed = _bundle_seed_root()
    entry = seed / ".ai_monitor" / "server.py"
    if not entry.exists():
        entry = _managed_src_root() / ".ai_monitor" / "server.py"  # dev 폴백
    _runpy_entry(entry, argv)


def _log_script_failure(target: Path, argv: list) -> None:
    """스크립트가 터졌을 때 **전체 트레이스백**을 파일에 남긴다.

    [🔴 왜 이 함수가 생겼나 — 2026-08-18 아픽스3 실측] frozen 에서 이 경로의 예외는
      PyInstaller 부트로더까지 올라가 "Unhandled exception in script" 창을 띄운다.
      그 창은 **Inno 가 만든 것이 아니라서** `/SILENT`·`/SUPPRESSMSGBOXES`·
      `SuppressibleMsgBox` 어느 것도 닿지 않는다. 무인 설치와 부팅 자동 설치
      (`_apply_staged_full_update`)가 거기서 사람이 누를 때까지 멈췄다.
    [🔴 창은 없애되 사실은 없애지 않는다] 예외를 삼키면 오늘 하루 우리가 싸운 병
      그대로다(값은 성공이라 말하고 화면은 침묵). 그래서 ①전체 트레이스백을 남기고
      ②0 이 아닌 종료 코드로 끝낸다 — 부르는 쪽(Inno [Run] / CurStepChanged)이
      실패를 실패로 읽고, 부팅 자동 설치의 시도 횟수 기록도 그대로 동작한다.
    [🔴 append 다 — 덮어쓰지 않는다] `voice-server.log` 가 기동마다 통째로 덮어써지는
      바람에 오늘 진단이 한 번 어긋났다("마지막 줄이 기동 메시지"를 죽음으로 오독).
      여기서 같은 실수를 반복하지 않는다. 대신 1MB 를 넘으면 .old 로 한 번만 밀어
      무한히 자라지 않게 한다 — 기록을 지우는 것이 아니라 세대를 하나 두는 것이다.
    [불변식] 이 함수는 절대 예외를 내지 않는다. 로그를 못 써서 종료 코드를 못 내면
      본래 막으려던 창이 다시 뜬다.
    """
    try:
        import time
        import traceback

        d = _app_data_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / SCRIPT_ERROR_LOG
        try:
            if path.exists() and path.stat().st_size > 1_000_000:
                old = d / (SCRIPT_ERROR_LOG + ".old")
                if old.exists():
                    old.unlink()
                path.rename(old)
        except OSError:
            pass
        with path.open("a", encoding="utf-8", errors="replace") as fp:
            # [WHY print(file=) 인가] 문자열에 개행 이스케이프를 쓰지 않으려는 것뿐이다.
            #   이 파일은 여러 도구를 거쳐 편집되는데 그때 이스케이프가 가장 잘 깨진다.
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print("", file=fp)
            print("===== {0}  {1}".format(stamp, " ".join(str(a) for a in argv)), file=fp)
            print("target={0}  frozen={1}".format(target, _is_frozen()), file=fp)
            print(traceback.format_exc(), file=fp)
    except Exception:                                        # noqa: BLE001
        pass                                                 # 위 [불변식] 참조


def _run_daemon_script(argv: list) -> None:
    """`vibe-coding.exe <script.py> [args]` — 데몬/도구 재실행 경로.
    [과거사고/제약] frozen에서 server.py가 일부 데몬을 `[sys.executable, <script>, ...]`로
      띄움 → sys.executable=EXE라 인자로 스크립트가 들어온다. 여기서 runpy로 받지 않으면
      EXE가 다시 부팅 시퀀스를 타며 무한 창 생성(v3.7.47 유형) 사고가 난다.
      clone 금지(부모 메인앱이 이미 SRC 보장). 절대경로면 그대로, 상대면 SRC 기준.
    """
    target = Path(argv[0])
    if not target.is_absolute():
        target = _managed_src_root() / argv[0]
    if not target.exists():
        seed = _bundle_seed_root()
        alt = seed / argv[0]
        if alt.exists():
            target = alt
    # 스크립트 임포트 루트: scripts/ 형제 import + .ai_monitor(api/src/infra) 양쪽.
    scripts_dir = target.parent
    src_root = scripts_dir.parent if scripts_dir.name == "scripts" else scripts_dir.parent
    for p in (str(scripts_dir), str(src_root / ".ai_monitor"), str(src_root)):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    try:
        _runpy_entry(target, argv[1:])
    except SystemExit:
        # 스크립트가 스스로 낸 종료 코드다 — 그대로 흘려보낸다(성공 0 포함).
        raise
    except BaseException:                                    # noqa: BLE001
        # [WHY BaseException 인가] 부트로더 창을 띄우는 것은 '전파된 예외'이지
        #   Exception 만이 아니다. KeyboardInterrupt 도 여기서는 창이 된다.
        _log_script_failure(target, argv)
        raise SystemExit(1)


def _selftest() -> int:
    """`boot.py --boot-selftest` — runpy 없이 경로/게이트 해석만 점검(앱 미기동)."""
    src = _managed_src_root()
    print(f"frozen={_is_frozen()}")
    print(f"managed_src={src}  checkout={_is_checkout(src)}")
    print(f"bundle_seed={_bundle_seed_root()}  checkout={_is_checkout(_bundle_seed_root())}")
    print(f"current_version={_load_current_version()}  gate_ok={_gate_ok(src)}")
    return 0 if _is_checkout(src) or _is_checkout(_bundle_seed_root()) else 1


def main() -> None:
    _make_stdio_encoding_safe()                    # [불변식] 첫 print 보다 먼저
    _inject_bundled_node_path()
    args = sys.argv[1:]
    if args and args[0] == "--boot-selftest":
        raise SystemExit(_selftest())
    if args and args[0] == "hook":
        _run_hook(args)
        return
    if args and str(args[0]).endswith(".py"):
        _run_daemon_script(args)
        return
    _acquire_early_windows_instance_mutex()
    _run_main_app(args)


if __name__ == "__main__":
    main()
