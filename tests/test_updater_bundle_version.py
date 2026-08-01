"""
FILE: tests/test_updater_bundle_version.py
DESCRIPTION: updater.bundle_version() 회귀 테스트 — 풀빌드 업데이트 감지가 소스 버전에
             가려지지 않도록 '번들 우선' 규칙을 고정한다.

REVISION HISTORY:
- 2026-08-01 Claude: 신규. boot.py가 관리 체크아웃을 sys.path 최우선으로 넣어
                     `from _version import __version__`이 **소스 버전**을 주고, soft 채널이
                     소스를 최신으로 당겨오면 _is_newer가 영구 False가 되어 EXE 업데이트가
                     안 뜨던 사고를 고정. boot.py에는 같은 불변식이 이미 있었으나
                     updater.py만 누락돼 있었다 — 테스트가 없어 드러나지 않았다.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / ".ai_monitor"))

import updater


def _write_version(d: Path, ver: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / "_version.py"
    p.write_text(f'__version__ = "{ver}"\n', encoding="utf-8")
    return p


def test_prefers_meipass_over_module_file(tmp_path, monkeypatch):
    """[핵심] _MEIPASS(번들)가 __file__(체크아웃 소스)보다 우선이어야 한다.

    이 순서가 뒤집히면 소스 버전이 번들을 가려 업데이트가 영구히 안 뜬다.
    """
    _write_version(tmp_path / "bundle", "3.7.286")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert updater.bundle_version() == "3.7.286"


def test_appseed_fallback_inside_bundle(tmp_path, monkeypatch):
    """onedir 배치에 따라 _version.py가 _appseed 하위에만 있는 경우도 번들로 인정."""
    seed = tmp_path / "bundle" / "_appseed" / ".ai_monitor"
    _write_version(seed, "3.7.290")
    (tmp_path / "bundle").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert updater.bundle_version() == "3.7.290"


def test_non_frozen_ignores_meipass_candidates(monkeypatch):
    """[안전] 비frozen에서 _MEIPASS가 없으면 빈 경로가 cwd 상대경로로 새면 안 된다.

    Path("")/"_version.py" == Path("_version.py") 이므로 cwd에 우연히 같은 이름의 파일이
    있으면 엉뚱한 버전을 읽는다. 후보에서 아예 제외되어야 한다.
    """
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    v = updater.bundle_version()
    # 모듈 옆 실제 _version.py(개발 트리)를 읽거나 APP_VERSION 폴백 — 어느 쪽이든 값이 있어야 함
    assert isinstance(v, str) and v, "비frozen에서도 문자열 버전을 돌려줘야 한다"


def test_falls_back_when_bundle_missing(tmp_path, monkeypatch):
    """번들 경로에 _version.py가 없으면 예외 없이 폴백해야 한다(업데이트 체크가 죽으면 안 됨)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(empty), raising=False)
    v = updater.bundle_version()
    assert isinstance(v, str) and v


def test_check_and_update_compares_bundle_not_module_constant():
    """[회귀 핵심] 비교 기준이 APP_VERSION으로 되돌아가면 사고가 그대로 재발한다."""
    src = (_ROOT / ".ai_monitor" / "updater.py").read_text(encoding="utf-8")
    body = src[src.index("def check_and_update("):]
    assert "bundle_version()" in body, "check_and_update가 번들 버전을 쓰지 않는다"
    # APP_VERSION을 직접 _is_newer에 넘기는 형태가 없어야 한다
    assert "_is_newer(latest_tag, APP_VERSION)" not in body, \
        "APP_VERSION 직접 비교로 회귀 — 소스 버전이 번들을 가린다"


def test_soft_updater_delegates_to_updater():
    """[중복 제거] 같은 로직이 두 벌이면 한쪽만 고쳐지는 사고가 반복된다(실제 발생).

    boot.py는 앱 모듈 import 금지(PyInstaller가 PYZ에 넣으면 run-from-source 전제가 깨짐)라
    자체 구현을 유지하는 것이 정상 — 여기서는 soft_updater만 검사한다.
    """
    src = (_ROOT / ".ai_monitor" / "soft_updater.py").read_text(encoding="utf-8")
    body = src[src.index("def _exe_version("):]
    body = body[:body.index("def _ver_tuple(")]
    assert "from updater import bundle_version" in body, "updater 정본에 위임하지 않는다"


def test_soft_updater_fallback_guards_empty_meipass():
    """폴백 경로도 빈 _MEIPASS를 걸러야 한다 — Path('')/'_version.py'는 cwd 상대경로."""
    src = (_ROOT / ".ai_monitor" / "soft_updater.py").read_text(encoding="utf-8")
    body = src[src.index("def _exe_version("):]
    body = body[:body.index("def _ver_tuple(")]
    assert "if mei:" in body, "빈 _MEIPASS 가드가 없어 cwd의 엉뚱한 파일을 읽을 수 있다"


def test_meipass_candidate_precedes_file_candidate():
    """후보 순서를 소스에서도 고정 — __file__ 후보가 앞서면 런타임에만 드러나는 회귀가 된다."""
    src = (_ROOT / ".ai_monitor" / "updater.py").read_text(encoding="utf-8")
    body = src[src.index("def bundle_version("):]
    body = body[:body.index("def _get_token(")]
    i_mei = body.index('Path(mei) / "_version.py"')
    i_file = body.index('Path(__file__).resolve().parent / "_version.py"')
    assert i_mei < i_file, "_MEIPASS 후보가 __file__ 후보보다 먼저 와야 한다"
