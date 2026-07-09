# -*- coding: utf-8 -*-
"""
FILE: tests/test_updater_release_path.py
DESCRIPTION: 업데이트/패키징 경로 회귀 테스트 — 릴리즈 크리티컬 핫스팟 방어.
             방금 계속 재발한 "Failed to load Python DLL" 사고(v3.7.244/247/248)의
             수정 로직을 순수 함수/격리 fs 단위로 고정한다. 이 경로는 EXE 업데이트 시에만
             실행돼 개발/CI에서 눈에 안 띄므로, 여기서 상시 게이트한다.

             [테스트 전략]
             - build_update_bat: 부수효과 없는 순수 함수 → bat 문자열 계약 검증(청소가 start보다 먼저).
             - heal_broken_mei_at_startup: sys.frozen/_MEIPASS 모킹 + tmp runtime 격리 →
               깨진 _MEI(python DLL 없음)만 삭제, 정상/현재 폴더는 보존.
             - kill 로직(wmic/CIM)은 OS 의존이라 모킹으로 대체(여기선 삭제 판정만 검증).

REVISION HISTORY:
- 2026-07-09 Claude: 최초 작성 — 전략 #1(릴리즈 경로 안전망) 1단계.
"""

import sys
from pathlib import Path

import pytest

# ── 프로젝트 경로 설정 (기존 테스트 관례와 동일) ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
sys.path.insert(0, str(_AI_MONITOR))

import updater  # noqa: E402
import infra.lifecycle as lifecycle  # noqa: E402
import infra.pty_process as pty_process  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# build_update_bat — _update.bat 생성 순수 함수 계약
# ═══════════════════════════════════════════════════════════════════════════

def _make_bat():
    return updater.build_update_bat(
        exe_path=Path(r"C:\Apps\VibeCoding\vibe-coding.exe"),
        old_path=Path(r"C:\Apps\VibeCoding\vibe-coding.exe.old"),
        pid=12345,
        runtime_dir=Path(r"C:\Users\x\AppData\Roaming\VibeCoding\runtime"),
    )


def test_bat_waits_for_old_pid_before_anything():
    """구 프로세스(PID) 사망을 먼저 대기해야 파일 핸들이 풀린다."""
    bat = _make_bat()
    assert ':wait' in bat
    assert 'PID eq 12345' in bat


def test_bat_cleans_runtime_before_starting_new_exe():
    """[불변식] runtime 청소(powershell)가 새 EXE start보다 '먼저' 와야
    깨끗한 상태에서 부트로더 추출이 일어난다. 순서가 뒤집히면 사고 재발."""
    bat = _make_bat()
    clean_idx = bat.find('powershell -NoProfile')
    start_idx = bat.find('start "" ')
    assert clean_idx != -1, "runtime 청소 라인 누락 — 사고 재발 위험"
    assert start_idx != -1, "새 EXE start 라인 누락"
    assert clean_idx < start_idx, "청소가 start보다 뒤 — 순서 역전(사고 재발)"


def test_bat_cleanup_targets_only_orphan_node_and_broken_mei():
    """[안전 계약] node kill은 runtime\\_MEI + 부모 죽음(고아)만, 폴더 삭제는
    python*.dll 없는 깨진 _MEI만. 정상 인스턴스/글로벌 node 보호 조건이 bat에 박혀 있어야."""
    bat = _make_bat()
    # 고아 판정: 부모 프로세스가 살아있으면 제외
    assert 'Get-Process -Id $_.ParentProcessId' in bat
    # runtime\_MEI 경로 필터
    assert "_MEI*" in bat
    # 깨진 폴더 판정: python*.dll 없는 것만 삭제
    assert "python*.dll" in bat
    # node.exe 만 대상
    assert "node.exe" in bat


def test_bat_self_deletes():
    """실행 후 자기 자신 삭제 — _update.bat 잔재 누적 방지."""
    bat = _make_bat()
    assert 'del /f /q "%~f0"' in bat


# ═══════════════════════════════════════════════════════════════════════════
# heal_broken_mei_at_startup — 부팅 자가치유 격리 fs 검증
# ═══════════════════════════════════════════════════════════════════════════

def _mk_mei(runtime: Path, name: str, with_dll: bool, dll="python311.dll"):
    d = runtime / name
    d.mkdir(parents=True)
    (d / "pty-server").mkdir()  # 항상 존재(깨진 폴더 특징: pty-server만 있음)
    if with_dll:
        (d / dll).write_bytes(b"MZ")  # DLL 존재 표식
        (d / "base_library.zip").write_bytes(b"PK")
    return d


def test_heal_removes_broken_mei_keeps_healthy_and_current(tmp_path, monkeypatch):
    """깨진 _MEI(python DLL 없음)는 삭제, 정상(DLL 있음)·현재(_MEIPASS)는 보존."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    current = _mk_mei(runtime, "_MEI_CURRENT", with_dll=True)
    healthy = _mk_mei(runtime, "_MEI_HEALTHY", with_dll=True, dll="python312.dll")
    broken1 = _mk_mei(runtime, "_MEI_BROKEN1", with_dll=False)
    broken2 = _mk_mei(runtime, "_MEI_BROKEN2", with_dll=False)

    # frozen 모드 + 현재 _MEIPASS 모킹
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(current), raising=False)
    # OS 의존 kill은 no-op으로 대체 (여기선 폴더 삭제 판정만 검증)
    monkeypatch.setattr(pty_process, "kill_runtime_mei_orphans",
                        lambda *a, **k: [], raising=True)

    lifecycle.heal_broken_mei_at_startup()

    assert current.exists(), "현재 실행 인스턴스 _MEI를 삭제하면 안 됨(치명적)"
    assert healthy.exists(), "정상 _MEI(다른 살아있는 인스턴스 가능)를 보호해야 함"
    assert not broken1.exists(), "깨진 _MEI(DLL 없음)는 제거돼야 함"
    assert not broken2.exists(), "깨진 _MEI(DLL 없음)는 제거돼야 함"


def test_heal_noop_in_dev_mode(tmp_path, monkeypatch):
    """개발 모드(frozen=False)에는 runtime _MEI 개념이 없으므로 아무것도 안 함."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    broken = _mk_mei(runtime, "_MEI_BROKEN", with_dll=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(runtime / "_MEI_BROKEN"), raising=False)

    lifecycle.heal_broken_mei_at_startup()  # 예외 없이 즉시 반환

    assert broken.exists(), "dev 모드에서는 삭제하지 않아야 함"


def test_heal_never_raises_on_bad_runtime(monkeypatch):
    """runtime 경로가 이상해도 부팅을 막으면 안 됨 — 전체 방어 계약."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", r"Z:\does\not\exist\_MEI999", raising=False)
    monkeypatch.setattr(pty_process, "kill_runtime_mei_orphans",
                        lambda *a, **k: [], raising=True)
    # 예외를 던지지 않아야 한다 (server.py 부팅에서 호출됨)
    lifecycle.heal_broken_mei_at_startup()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
