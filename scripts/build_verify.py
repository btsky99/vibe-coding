"""
FILE: scripts/build_verify.py
DESCRIPTION: 빌드 전 필수 조건 검증 스크립트.
    PyInstaller EXE 빌드 전에 모든 의존성, 경로, 바이너리, 프론트엔드 빌드 상태를 검증합니다.
    검증 실패 시 exit(1)로 빌드를 중단하여, CI에서 에러 없는 빌드를 보장합니다.

    사용법:
      python scripts/build_verify.py          # 전체 검증 (CI + 로컬)
      python scripts/build_verify.py --ci      # CI 환경 전용 검증
      python scripts/build_verify.py --local   # 로컬 환경 전용 검증
      python scripts/build_verify.py --fix     # 자동 수정 가능한 문제는 수정 후 재검증

REVISION HISTORY:
- 2026-03-27 Claude: 최초 생성 — 빌드 에러 근본 방지를 위한 사전 검증 시스템
"""

import sys
import os
import re
import json
import subprocess
import importlib
import shutil
from pathlib import Path

# CI 환경(cp1252 등)에서 한글 출력 시 UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 프로젝트 루트 / 기준 경로 ────────────────────────────────────────────────
# 이 스크립트는 항상 프로젝트 루트(D:\vibe-coding)에서 실행된다고 가정
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
AI_MONITOR = PROJECT_ROOT / ".ai_monitor"
VIBE_VIEW = AI_MONITOR / "vibe-view"
PTY_SERVER = AI_MONITOR / "pty-server"
BIN_DIR = AI_MONITOR / "bin"

# ── 검증 결과 수집 ────────────────────────────────────────────────────────────
# 각 검증 함수는 (passed, message) 튜플을 반환. 최종 집계 후 성공/실패 판정.
_results: list[tuple[bool, str, str]] = []  # (passed, category, message)
_warnings: list[tuple[str, str]] = []       # (category, message)


def _pass(category: str, msg: str):
    """검증 통과 기록"""
    _results.append((True, category, msg))


def _fail(category: str, msg: str):
    """검증 실패 기록"""
    _results.append((False, category, msg))


def _warn(category: str, msg: str):
    """경고 기록 (빌드 중단하진 않지만 주의 필요)"""
    _warnings.append((category, msg))


# ══════════════════════════════════════════════════════════════════════════════
# 1. 버전 파일 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_version():
    """_version.py 파일 형식 및 버전 문자열 유효성 검증"""
    cat = "VERSION"
    vfile = AI_MONITOR / "_version.py"

    if not vfile.exists():
        _fail(cat, f"_version.py 파일 없음: {vfile}")
        return

    content = vfile.read_text(encoding="utf-8").strip()

    # __version__ = "X.Y.Z" 형식 검증
    match = re.search(r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', content)
    if not match:
        _fail(cat, f"_version.py 형식 오류 — 'X.Y.Z' 패턴 불일치: {content[:100]}")
        return

    version = match.group(1)
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        _fail(cat, f"버전 형식 오류 (X.Y.Z 필요): {version}")
        return

    _pass(cat, f"v{version} 정상")

    # package.json 버전과 동기화 확인
    pkg_json = VIBE_VIEW / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            pkg_ver = pkg.get("version", "")
            if pkg_ver != version:
                _warn(cat, f"package.json 버전({pkg_ver}) ≠ _version.py({version}) — 빌드 시 auto_version.py가 동기화합니다")
        except (json.JSONDecodeError, KeyError):
            _warn(cat, "package.json 파싱 실패")

    # setup.iss 버전 확인
    iss_file = PROJECT_ROOT / "vibe-coding-setup.iss"
    if iss_file.exists():
        iss_content = iss_file.read_text(encoding="utf-8")
        iss_match = re.search(r'#define\s+MyAppVersion\s+"(\d+\.\d+\.\d+)"', iss_content)
        if iss_match and iss_match.group(1) != version:
            _warn(cat, f"setup.iss 버전({iss_match.group(1)}) ≠ _version.py({version}) — CI가 /DMyAppVersion으로 오버라이드합니다")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Python 의존성 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_python_deps():
    """requirements.txt에 명시된 핵심 패키지 import 가능 여부 검증"""
    cat = "PYTHON_DEPS"

    # 빌드에 반드시 필요한 핵심 패키지만 검증 (선택적 ML 패키지 제외)
    critical_packages = {
        "pywebview": "webview",           # GUI 프레임워크
        "pywinpty": "winpty",             # PTY 터미널
        "websockets": "websockets",       # WebSocket
        "aiohttp": "aiohttp",             # Async HTTP
        "psycopg2-binary": "psycopg2",    # PostgreSQL
        "PySide6": "PySide6",             # 대시보드 GUI
        "pyinstaller": "PyInstaller",     # 빌드 도구
    }

    for pkg_name, import_name in critical_packages.items():
        try:
            importlib.import_module(import_name)
            _pass(cat, f"{pkg_name} 설치됨")
        except ImportError:
            _fail(cat, f"{pkg_name} 미설치 — pip install {pkg_name}")

    # PyInstaller 버전 범위 검증 (>=6.0, <7.0)
    try:
        import PyInstaller
        pi_ver = PyInstaller.__version__
        major = int(pi_ver.split(".")[0])
        if major < 6 or major >= 7:
            _fail(cat, f"PyInstaller {pi_ver} — 6.x 필요 (현재 {major}.x)")
        else:
            _pass(cat, f"PyInstaller {pi_ver} 버전 범위 정상")
    except (ImportError, AttributeError):
        pass  # 이미 위에서 실패 기록됨


# ══════════════════════════════════════════════════════════════════════════════
# 3. server.py 구문 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_server_syntax():
    """server.py Python 구문 검증 (SyntaxError 사전 탐지)"""
    cat = "SYNTAX"
    server_py = AI_MONITOR / "server.py"

    if not server_py.exists():
        _fail(cat, f"server.py 없음: {server_py}")
        return

    try:
        # py_compile로 구문 오류 검사
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(server_py)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            _fail(cat, f"server.py 구문 오류:\n{result.stderr[:500]}")
        else:
            _pass(cat, "server.py 구문 정상")
    except subprocess.TimeoutExpired:
        _fail(cat, "server.py 구문 검사 타임아웃 (30초)")
    except Exception as e:
        _fail(cat, f"server.py 구문 검사 실패: {e}")

    # ruff 린트 (설치되어 있을 때만)
    ruff_path = shutil.which("ruff")
    if ruff_path:
        try:
            result = subprocess.run(
                [ruff_path, "check", str(server_py), "--select", "E9,F821,F823"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                _fail(cat, f"ruff 린트 실패:\n{result.stdout[:500]}")
            else:
                _pass(cat, "ruff 린트 통과 (E9, F821, F823)")
        except Exception:
            _warn(cat, "ruff 실행 실패 — 건너뜀")
    else:
        _warn(cat, "ruff 미설치 — 린트 건너뜀 (pip install ruff)")


# ══════════════════════════════════════════════════════════════════════════════
# 4. 프론트엔드 빌드 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_frontend(fix: bool = False):
    """vibe-view/dist 프론트엔드 빌드 결과물 존재 및 무결성 검증"""
    cat = "FRONTEND"
    dist_dir = VIBE_VIEW / "dist"

    if not VIBE_VIEW.exists():
        _fail(cat, f"vibe-view 폴더 없음: {VIBE_VIEW}")
        return

    pkg_json = VIBE_VIEW / "package.json"
    if not pkg_json.exists():
        _fail(cat, f"vibe-view/package.json 없음")
        return

    if not dist_dir.exists() or not any(dist_dir.iterdir()):
        if fix:
            print("  [FIX] 프론트엔드 빌드 실행 중...")
            try:
                subprocess.run(["npm", "ci"], cwd=str(VIBE_VIEW), check=True,
                               capture_output=True, timeout=120)
                subprocess.run(["npm", "run", "build"], cwd=str(VIBE_VIEW), check=True,
                               capture_output=True, timeout=120)
                if dist_dir.exists() and any(dist_dir.iterdir()):
                    _pass(cat, "프론트엔드 빌드 성공 (자동 수정)")
                    return
            except Exception as e:
                _fail(cat, f"프론트엔드 자동 빌드 실패: {e}")
                return
        _fail(cat, f"vibe-view/dist 비어있음 — 'cd .ai_monitor/vibe-view && npm ci && npm run build' 실행 필요")
        return

    # index.html 존재 확인
    index_html = dist_dir / "index.html"
    if not index_html.exists():
        _fail(cat, "dist/index.html 없음 — 프론트엔드 빌드 불완전")
        return

    # JS/CSS 에셋 존재 확인
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        js_files = list(assets_dir.glob("*.js"))
        css_files = list(assets_dir.glob("*.css"))
        if not js_files:
            _fail(cat, "dist/assets/*.js 없음 — 빌드 불완전")
        elif not css_files:
            _warn(cat, "dist/assets/*.css 없음 — CSS 누락 가능성")
        else:
            total_size = sum(f.stat().st_size for f in js_files + css_files)
            _pass(cat, f"dist 정상 (JS {len(js_files)}개, CSS {len(css_files)}개, 총 {total_size // 1024}KB)")
    else:
        _warn(cat, "dist/assets 폴더 없음 — Vite 빌드 구조 확인 필요")


# ══════════════════════════════════════════════════════════════════════════════
# 5. winpty 바이너리 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_winpty():
    """winpty 바이너리(DLL, EXE) 존재 및 접근 가능 여부 검증"""
    cat = "WINPTY"

    try:
        import winpty
        winpty_dir = Path(winpty.__file__).parent
    except ImportError:
        _fail(cat, "pywinpty 미설치 — pip install pywinpty==3.0.3")
        return

    # PyInstaller --add-binary에 포함되는 필수 파일 4개
    required_files = [
        "winpty.dll",
        "winpty-agent.exe",
        "conpty.dll",
        "OpenConsole.exe",
    ]

    for fname in required_files:
        fpath = winpty_dir / fname
        if fpath.exists():
            size_kb = fpath.stat().st_size // 1024
            _pass(cat, f"{fname} 존재 ({size_kb}KB)")
        else:
            _fail(cat, f"{fname} 없음: {fpath}")
            _fail(cat, f"  → PTY 터미널 기능 사용 불가. pywinpty 재설치 필요")


# ══════════════════════════════════════════════════════════════════════════════
# 6. PTY 서버 (node-pty) 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_pty_server(is_ci: bool = False):
    """pty-server 디렉터리, node_modules, node-pty 네이티브 바이너리 검증"""
    cat = "PTY_SERVER"

    if not PTY_SERVER.exists():
        _fail(cat, f"pty-server 폴더 없음: {PTY_SERVER}")
        return

    pkg_json = PTY_SERVER / "package.json"
    if not pkg_json.exists():
        _fail(cat, "pty-server/package.json 없음")
        return

    node_modules = PTY_SERVER / "node_modules"
    if not node_modules.exists():
        _fail(cat, "pty-server/node_modules 없음 — 'cd .ai_monitor/pty-server && npm ci' 실행 필요")
        return

    # node-pty 네이티브 바이너리 확인
    node_pty_dir = node_modules / "node-pty"
    if not node_pty_dir.exists():
        _fail(cat, "node-pty 미설치 — npm ci 실행 필요")
        return

    # .node 네이티브 바이너리 존재 확인
    node_files = list(node_pty_dir.rglob("*.node"))
    if not node_files:
        _fail(cat, "node-pty 네이티브 바이너리(.node) 없음 — npm rebuild 필요")
    else:
        _pass(cat, f"node-pty 네이티브 바이너리 {len(node_files)}개 정상")

    # CI에서는 node.exe 번들 확인
    if is_ci:
        node_exe = PTY_SERVER / "node.exe"
        if not node_exe.exists():
            _warn(cat, "pty-server/node.exe 없음 — CI에서 'cp $(which node) ./node.exe' 필요")

    # Node.js 버전 확인
    node_path = shutil.which("node")
    if node_path:
        try:
            result = subprocess.run([node_path, "--version"], capture_output=True, text=True, timeout=10)
            node_ver = result.stdout.strip()
            _pass(cat, f"Node.js {node_ver} 설치됨")
        except Exception:
            _warn(cat, "Node.js 버전 확인 실패")
    else:
        _fail(cat, "Node.js 미설치")


# ══════════════════════════════════════════════════════════════════════════════
# 7. PostgreSQL 바이너리 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_postgres_binaries(is_ci: bool = False):
    """PostgreSQL 포터블 바이너리 존재 여부 검증 (설치 패키지 포함용)"""
    cat = "POSTGRESQL"
    pg_dir = BIN_DIR / "pgsql"

    if is_ci:
        # CI에서는 다운로드 스텝이 별도로 있으므로, 디렉터리 구조만 확인 안내
        _warn(cat, "CI 환경 — PostgreSQL은 'Download PostgreSQL portable' 스텝에서 다운로드됩니다")
        return

    if not pg_dir.exists():
        _warn(cat, f"pgsql 폴더 없음: {pg_dir} — 설치 패키지에 PG 미포함")
        return

    required_subdirs = ["bin", "lib", "share"]
    for subdir in required_subdirs:
        subpath = pg_dir / subdir
        if subpath.exists():
            count = len(list(subpath.rglob("*")))
            _pass(cat, f"pgsql/{subdir} 정상 ({count}개 파일)")
        else:
            _fail(cat, f"pgsql/{subdir} 없음")

    # psql.exe 존재 확인
    psql = pg_dir / "bin" / "psql.exe"
    if psql.exists():
        _pass(cat, "psql.exe 존재")
    else:
        _fail(cat, "psql.exe 없음 — PostgreSQL 바이너리 불완전")


# ══════════════════════════════════════════════════════════════════════════════
# 8. 아이콘 및 에셋 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_assets():
    """빌드에 필요한 아이콘 및 에셋 파일 존재 확인"""
    cat = "ASSETS"

    icon_files = [
        (BIN_DIR / "app_icon.ico", "앱 아이콘"),
        (BIN_DIR / "vibe_final.ico", "최종 아이콘"),
    ]

    for fpath, desc in icon_files:
        if fpath.exists():
            _pass(cat, f"{desc} 존재: {fpath.name}")
        else:
            # 원본 아이콘에서 복사 시도
            src_icon = PROJECT_ROOT / "assets" / "vibe_coding_icon.ico"
            if src_icon.exists():
                _warn(cat, f"{desc} 없음 — assets/vibe_coding_icon.ico에서 복사 필요")
            else:
                _fail(cat, f"{desc} 없음: {fpath}")


# ══════════════════════════════════════════════════════════════════════════════
# 9. spec 파일 데이터 경로 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_spec_data_paths():
    """vibe-coding.spec의 datas/binaries에 명시된 소스 경로 존재 여부 검증"""
    cat = "SPEC_PATHS"
    spec_file = PROJECT_ROOT / "vibe-coding.spec"

    if not spec_file.exists():
        _warn(cat, "vibe-coding.spec 없음 — CI는 인라인 PyInstaller 명령 사용")
        return

    content = spec_file.read_text(encoding="utf-8")

    # datas 항목에서 소스 경로 추출
    # 패턴: ('소스경로', '대상경로'),
    datas_matches = re.findall(r"\('([^']+)',\s*'[^']+'\)", content)

    for src in datas_matches:
        # winpty 동적 경로는 건너뜀
        if "_winpty_dir" in src or "str(" in src:
            continue

        # 상대 경로 → 절대 경로 변환 (spec은 프로젝트 루트에서 실행)
        full_path = PROJECT_ROOT / src
        if full_path.exists():
            _pass(cat, f"spec datas 경로 존재: {src}")
        else:
            _fail(cat, f"spec datas 경로 없음: {src} → {full_path}")


# ══════════════════════════════════════════════════════════════════════════════
# 10. CI 워크플로 데이터 경로 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_ci_add_data_paths():
    """build-release.yml의 --add-data/--add-binary 경로 검증
    CI에서는 .ai_monitor/ 디렉토리를 cwd로 사용하므로 상대 경로 기준이 다름"""
    cat = "CI_PATHS"

    yml_file = PROJECT_ROOT / ".github" / "workflows" / "build-release.yml"
    if not yml_file.exists():
        _fail(cat, "build-release.yml 없음")
        return

    content = yml_file.read_text(encoding="utf-8")

    # --add-data "src;src" 패턴 (bash에서 ; 구분자)
    add_data_matches = re.findall(r'--add-data\s+"([^;]+);', content)
    # 중복 제거
    add_data_matches = list(set(add_data_matches))

    for src in add_data_matches:
        # 동적 변수($WINPTY 등)는 건너뜀
        if "$" in src or "{" in src:
            continue

        # CI에서 cwd는 .ai_monitor/
        full_path = AI_MONITOR / src
        if full_path.exists():
            _pass(cat, f"add-data 소스 존재: {src}")
        else:
            _fail(cat, f"add-data 소스 없음: {src} → {full_path}")


# ══════════════════════════════════════════════════════════════════════════════
# 11. server.py 내부 import 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_server_imports():
    """server.py의 핵심 내부 모듈(src/db.py, src/db_helper.py, api/) import 경로 검증"""
    cat = "IMPORTS"

    # src 디렉터리 내부 모듈
    src_dir = AI_MONITOR / "src"
    required_src = ["db.py", "db_helper.py"]
    for fname in required_src:
        fpath = src_dir / fname
        if fpath.exists():
            _pass(cat, f"src/{fname} 존재")
        else:
            _fail(cat, f"src/{fname} 없음 — server.py import 실패 예상")

    # api 디렉터리
    api_dir = AI_MONITOR / "api"
    if api_dir.exists():
        api_files = list(api_dir.glob("*.py"))
        if api_files:
            _pass(cat, f"api/ 모듈 {len(api_files)}개 존재")
        else:
            _warn(cat, "api/ 폴더에 .py 파일 없음")
    else:
        _fail(cat, "api/ 폴더 없음 — server.py의 API 모듈 import 실패 예상")


# ══════════════════════════════════════════════════════════════════════════════
# 12. 디스크 공간 검증
# ══════════════════════════════════════════════════════════════════════════════
def verify_disk_space():
    """빌드에 필요한 최소 디스크 공간 확인 (EXE ~100MB + 임시 파일)"""
    cat = "DISK"
    try:
        import shutil as _sh
        usage = _sh.disk_usage(str(PROJECT_ROOT))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            _fail(cat, f"디스크 여유 공간 부족: {free_gb:.1f}GB (최소 1GB 필요)")
        elif free_gb < 2.0:
            _warn(cat, f"디스크 여유 공간 주의: {free_gb:.1f}GB (2GB 이상 권장)")
        else:
            _pass(cat, f"디스크 여유 공간: {free_gb:.1f}GB")
    except Exception as e:
        _warn(cat, f"디스크 공간 확인 실패: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 13. dashboard_window.py 존재 검증 (서브창 EXE 빌드용)
# ══════════════════════════════════════════════════════════════════════════════
def verify_sub_window_sources():
    """서브창 EXE 빌드에 필요한 소스 파일 존재 확인"""
    cat = "SUB_WINDOW"

    dashboard_py = AI_MONITOR / "dashboard_window.py"
    if dashboard_py.exists():
        _pass(cat, "dashboard_window.py 존재")
    else:
        _fail(cat, f"dashboard_window.py 없음: {dashboard_py}")


# ══════════════════════════════════════════════════════════════════════════════
# 14. statusline.py 존재 검증 (설치 패키지 포함)
# ══════════════════════════════════════════════════════════════════════════════
def verify_installer_files():
    """Inno Setup 설치 패키지에 포함되는 파일 존재 확인"""
    cat = "INSTALLER"

    statusline = PROJECT_ROOT / "statusline.py"
    if statusline.exists():
        _pass(cat, "statusline.py 존재")
    else:
        _warn(cat, "statusline.py 없음 — 설치 패키지 빌드 시 경고 발생 가능")

    iss_file = PROJECT_ROOT / "vibe-coding-setup.iss"
    if iss_file.exists():
        _pass(cat, "vibe-coding-setup.iss 존재")
    else:
        _warn(cat, "vibe-coding-setup.iss 없음 — 설치 패키지 빌드 불가")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════════════════════════
def run_all(is_ci: bool = False, fix: bool = False, phase: str = "all"):
    """모든 검증 실행 및 결과 출력

    phase 옵션:
      - "all": 전체 검증 (기본값, 로컬 용)
      - "pre": Phase 1 — Python/소스 검증만 (CI: 프론트엔드 빌드 전)
      - "post": Phase 2 — 빌드 산출물 포함 전체 검증 (CI: PyInstaller 빌드 직전)
    """
    phase_label = {"all": "전체", "pre": "Phase 1 (소스 검증)", "post": "Phase 2 (빌드 직전 최종)"}
    print("=" * 70)
    print("  Vibe Coding 빌드 전 검증 (Build Pre-flight Check)")
    print("=" * 70)
    print(f"  환경: {'CI' if is_ci else '로컬'}")
    print(f"  단계: {phase_label.get(phase, phase)}")
    print(f"  프로젝트: {PROJECT_ROOT}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  자동 수정: {'ON' if fix else 'OFF'}")
    print("=" * 70)
    print()

    # Phase 1 (pre): Python 의존성, 구문, 버전 — 프론트엔드 빌드 전에 빠르게 확인
    if phase in ("all", "pre"):
        verify_version()
        verify_python_deps()
        verify_server_syntax()
        verify_server_imports()
        verify_disk_space()
        verify_sub_window_sources()

    # Phase 2 (post) 또는 all: 프론트엔드/PTY/에셋 등 빌드 산출물 검증
    if phase in ("all", "post"):
        if phase == "post":
            # post에서도 기본 검증은 다시 실행 (안전망)
            verify_version()
            verify_python_deps()
        verify_frontend(fix=fix)
        verify_winpty()
        verify_pty_server(is_ci=is_ci)
        verify_postgres_binaries(is_ci=is_ci)
        verify_assets()
        verify_spec_data_paths()
        verify_ci_add_data_paths()
        verify_installer_files()

    # ── 결과 출력 ─────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  검증 결과")
    print("=" * 70)

    passed = [r for r in _results if r[0]]
    failed = [r for r in _results if not r[0]]

    if failed:
        print(f"\n  FAIL ({len(failed)}건):")
        for _, cat, msg in failed:
            print(f"    [{cat}] {msg}")

    if _warnings:
        print(f"\n  WARN ({len(_warnings)}건):")
        for cat, msg in _warnings:
            print(f"    [{cat}] {msg}")

    print(f"\n  PASS: {len(passed)}건")
    print(f"  FAIL: {len(failed)}건")
    print(f"  WARN: {len(_warnings)}건")
    print()

    if failed:
        print("  *** 빌드 중단: 위 FAIL 항목을 먼저 해결하세요 ***")
        print("=" * 70)
        return False
    else:
        print("  *** 모든 검증 통과 — 빌드 진행 가능 ***")
        print("=" * 70)
        return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Vibe Coding 빌드 전 검증")
    parser.add_argument("--ci", action="store_true", help="CI 환경 전용 검증")
    parser.add_argument("--local", action="store_true", help="로컬 환경 전용 검증")
    parser.add_argument("--fix", action="store_true", help="자동 수정 가능한 문제 수정")
    parser.add_argument("--phase", choices=["all", "pre", "post"], default="all",
                        help="검증 단계: pre(소스만), post(빌드 직전 전체), all(전부)")
    args = parser.parse_args()

    is_ci = args.ci or os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

    success = run_all(is_ci=is_ci, fix=args.fix, phase=args.phase)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
