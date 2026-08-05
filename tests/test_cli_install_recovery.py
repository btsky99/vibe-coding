"""
FILE: tests/test_cli_install_recovery.py
DESCRIPTION: CLI 자동 설치가 "성공했는데도 미설치로 보이던" 결함(2026-08-05)의 회귀 방지.
             두 축을 검증한다 —
               ① PATH 재병합(infra/env_path): 설치기가 레지스트리에만 쓴 bin 디렉토리를
                  실행 중 프로세스가 재시작 없이 인식하는가
               ② Antigravity 설치 경로: npm(@google/gemini-cli)으로 새지 않고 공식
                  인스톨러(`agy`)로 가는가

             [WHY 이 파일이 필요한가] 결함 당시 기존 설치 테스트 23개가 **전부 통과**했다.
             npm 호출 순서만 보고 "설치 성공 판정"과 "명령 이름 정합성"을 아무도 안 봤기 때문.
             여기서는 그 두 가지를 직접 겨냥한다.

REVISION HISTORY:
- 2026-08-05 Claude: 최초 작성 — 설치 성공 오판정 + Antigravity npm 오등록 회귀 방지.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".ai_monitor"))
sys.path.insert(0, str(ROOT / "scripts"))

from infra import env_path  # noqa: E402
from infra import tool_install  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
#  ① PATH 재병합 — 결함의 근본 원인
# ═══════════════════════════════════════════════════════════════════════

def test_refresh_path_recovers_installer_added_dirs(tmp_path, monkeypatch):
    """설치기가 만든 bin 디렉토리가 PATH에서 빠져 있어도 refresh 후 복구돼야 한다.

    [재현] 서버가 뜬 뒤 설치기가 %APPDATA%/npm 등을 레지스트리 PATH에 추가한 상황 =
      서버 프로세스 PATH에는 그 항목이 없는 상태. 이때 shutil.which()가 계속 None을
      반환해 UI가 '설치 필요'에 고착됐다.
    """
    fake_bin = tmp_path / "npm"
    fake_bin.mkdir()

    monkeypatch.setenv("PATH", str(tmp_path / "unrelated"))
    monkeypatch.setattr(env_path, "_registry_paths", lambda: [str(fake_bin)])
    monkeypatch.setattr(env_path, "known_cli_dirs", lambda: [])

    assert str(fake_bin) not in os.environ["PATH"]
    assert env_path.refresh_path(force=True) is True
    assert str(fake_bin) in os.environ["PATH"].split(os.pathsep)


def test_refresh_path_keeps_existing_entries_first(monkeypatch):
    """[불변식] 기존 PATH 항목이 항상 앞에 온다 — 명령 해석 결과가 바뀌면 안 된다.

    이 순서가 뒤집히면 boot.py가 앞에 주입한 번들 node보다 시스템 node가 먼저 잡혀
    런타임 버전이 조용히 바뀐다.
    """
    monkeypatch.setenv("PATH", os.pathsep.join(["FIRST", "SECOND"]))
    monkeypatch.setattr(env_path, "_registry_paths", lambda: ["THIRD", "FIRST"])
    monkeypatch.setattr(env_path, "known_cli_dirs", lambda: ["FOURTH"])

    env_path.refresh_path(force=True)
    assert os.environ["PATH"].split(os.pathsep) == ["FIRST", "SECOND", "THIRD", "FOURTH"]


def test_refresh_path_honours_ttl(monkeypatch):
    """TTL 안에서는 재병합을 건너뛴다 — 3초 폴링 × 도구 수만큼 레지스트리를 읽지 않도록."""
    monkeypatch.setattr(env_path, "_registry_paths", lambda: [])
    monkeypatch.setattr(env_path, "known_cli_dirs", lambda: [])

    assert env_path.refresh_path(force=True) is True
    assert env_path.refresh_path() is False


def test_detection_paths_call_refresh():
    """감지 3경로가 모두 PATH를 갱신해야 한다 — 하나라도 빠지면 그 경로만 고착된다."""
    sources = {
        "tool_install.tool_status": ROOT / ".ai_monitor" / "infra" / "tool_install.py",
        "tools_api._check_tool_installed": ROOT / ".ai_monitor" / "api" / "tools_api.py",
        "setup_doctor.check_cli_agents": ROOT / ".ai_monitor" / "setup_doctor.py",
    }
    for label, path in sources.items():
        text = path.read_text(encoding="utf-8")
        assert "refresh_path()" in text or "_refresh_env_path()" in text, (
            f"{label}이 PATH를 갱신하지 않는다 — 설치 성공을 재시작 전까지 못 본다."
        )


# ═══════════════════════════════════════════════════════════════════════
#  ② Antigravity 설치 경로 — npm으로 새면 영구 실패
# ═══════════════════════════════════════════════════════════════════════

def test_antigravity_target_is_not_npm():
    """🔴 Antigravity는 npm 배포가 없다. package를 채우면 영구 실패로 되돌아간다.

    [실측 2026-08-05] `npm view @google/gemini-cli bin` → {gemini: ...} 하나뿐.
      즉 그 패키지를 깔아도 `agy`/`antigravity` 실행 파일은 생기지 않는다.
    """
    target = tool_install.TOOL_INSTALL_TARGETS["antigravity"]
    assert target["command"] == "agy", "Antigravity의 실행 명령은 `agy`다"
    assert not target["package"], "Antigravity를 npm 패키지로 등록하면 안 된다"
    assert target["install_script"] == "install_antigravity.py"


def test_start_tool_install_refuses_non_npm_tool():
    """npm 전용 상태 머신이 Antigravity를 받으면 설치를 시작하지 말고 되돌려보내야 한다."""
    result = tool_install.start_tool_install("antigravity")
    assert result["status"] == "error"
    assert result["install_script"] == "install_antigravity.py"


@pytest.mark.parametrize("tool_id,expected_command", [("claude", "claude"), ("codex", "codex")])
def test_npm_targets_command_matches_package_bin(tool_id, expected_command):
    """npm 도구는 패키지가 만드는 bin 이름과 command가 일치해야 한다.

    불일치하면 npm이 exit 0으로 끝나도 _watch_install이 installed=False로 보고
    'failed'가 된다 — Antigravity에서 실제로 터졌던 실패 모드다.
    """
    target = tool_install.TOOL_INSTALL_TARGETS[tool_id]
    assert target["package"], f"{tool_id}는 npm 패키지가 있어야 한다"
    assert target["command"] == expected_command


def test_install_antigravity_fails_when_agy_missing():
    """인스톨러가 exit 0이어도 `agy`가 없으면 실패로 보고해야 한다.

    [과거사고] returncode만 믿고 '완료'를 찍어, 다음 진단에서 미설치로 돌아오는데도
      설치 로그는 성공으로 남아 원인 추적이 막혔다.
    """
    import install_antigravity

    with (
        patch.object(install_antigravity, "_refresh_path"),
        patch.object(install_antigravity, "_agy_present", return_value=False),
        patch.object(
            install_antigravity.subprocess, "run",
            return_value=type("R", (), {"returncode": 0})(),
        ),
        pytest.raises(SystemExit) as excinfo,
    ):
        install_antigravity.main()

    assert excinfo.value.code == 1


def test_install_antigravity_succeeds_when_agy_appears():
    """설치 후 `agy`가 잡히면 정상 종료(SystemExit 없음)."""
    import install_antigravity

    present = iter([False, True])  # 설치 전 미검출 → 설치 후 검출
    with (
        patch.object(install_antigravity, "_refresh_path"),
        patch.object(install_antigravity, "_agy_present", side_effect=lambda: next(present)),
        patch.object(
            install_antigravity.subprocess, "run",
            return_value=type("R", (), {"returncode": 0})(),
        ),
    ):
        install_antigravity.main()  # 예외 없이 끝나야 한다


def test_npm_install_route_excludes_antigravity():
    """npm 설치 라우트 맵에 antigravity가 다시 섞이지 않게 막는다."""
    source = (ROOT / ".ai_monitor" / "api" / "install_api.py").read_text(encoding="utf-8")
    npm_map_start = source.index("_install_map = {")
    npm_map_end = source.index("}", npm_map_start)
    npm_map = source[npm_map_start:npm_map_end]
    assert "antigravity" not in npm_map.lower()
    assert "def install_antigravity(" in source, "Antigravity 전용 라우트가 있어야 한다"
