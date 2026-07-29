"""
FILE: .ai_monitor/boot.py
DESCRIPTION: 경량 소스 업데이트 채널(A안)의 EXE 진입점 부트스트랩.
  앱 코드를 frozen PYZ에서 분리하고, 관리형 git 체크아웃(또는 번들 seed)의 .py를
  runpy로 실행하여 "git push → 버튼 클릭"만으로 설치본을 갱신 가능하게 한다.
  의존성(pywebview/psycopg/...)만 frozen 유지되고, 앱 .py는 항상 체크아웃에서 로드된다.

REVISION HISTORY:
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
    import telegram           # python-telegram-bot 브릿지
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
        r = subprocess.run(["git"] + args, cwd=cwd and str(cwd),
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=no_win)
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
    src = _ensure_src(_managed_src_root())
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
    _runpy_entry(target, argv[1:])


def _selftest() -> int:
    """`boot.py --boot-selftest` — runpy 없이 경로/게이트 해석만 점검(앱 미기동)."""
    src = _managed_src_root()
    print(f"frozen={_is_frozen()}")
    print(f"managed_src={src}  checkout={_is_checkout(src)}")
    print(f"bundle_seed={_bundle_seed_root()}  checkout={_is_checkout(_bundle_seed_root())}")
    print(f"current_version={_load_current_version()}  gate_ok={_gate_ok(src)}")
    return 0 if _is_checkout(src) or _is_checkout(_bundle_seed_root()) else 1


def main() -> None:
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
    _run_main_app(args)


if __name__ == "__main__":
    main()
