"""
FILE: tests/test_smoke_isolation.py
DESCRIPTION: smoke_test의 데이터 디렉토리 격리 계약 검증 — 설치본 %APPDATA%\\VibeCoding 오염 방지.

REVISION HISTORY:
- 2026-08-01 Claude: 신규 — smoke가 설치본과 데이터 디렉토리를 공유해 pid/업데이트 상태 파일을
                     덮어쓰던 문제(오진까지 유발) 재발 방지.
"""

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SMOKE = _ROOT / "scripts" / "smoke_test.py"
_SERVER = _ROOT / ".ai_monitor" / "server.py"


@pytest.fixture(scope="module")
def smoke_src() -> str:
    return _SMOKE.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def server_src() -> str:
    return _SERVER.read_text(encoding="utf-8", errors="replace")


def test_server_honors_data_dir_override(server_src):
    """VIBE_DATA_DIR이 없으면 smoke가 다시 설치본 디렉토리를 쓴다."""
    assert "VIBE_DATA_DIR" in server_src, "DATA_DIR 오버라이드 수단이 사라졌다"


def test_override_takes_priority_over_appdata(server_src):
    """[순서 불변식] 오버라이드가 frozen 분기보다 **먼저** 평가돼야 한다.

    frozen 분기가 먼저면 EXE에서는 오버라이드가 무시돼 격리가 무력화된다
    (smoke는 frozen EXE를 띄우므로 정확히 그 경로를 탄다).
    """
    # [주의] 첫 'VIBE_DATA_DIR' 등장은 설명 주석이다 — 실제 대입문을 앵커로 잡아야
    #   구조를 검사할 수 있다(주석을 앵커로 삼으면 창이 코드에 닿지 않아 오탐).
    idx = server_src.index("_data_override = os.environ.get('VIBE_DATA_DIR'")
    block = server_src[idx:idx + 400]
    assert "if _data_override:" in block, "오버라이드가 최우선 분기여야 한다"
    assert "elif getattr(sys, 'frozen', False)" in block, \
        "오버라이드가 frozen 분기보다 앞선 if/elif 구조여야 한다"
    assert block.index("if _data_override:") < block.index("elif getattr(sys, 'frozen'"), \
        "frozen 분기가 먼저 평가되면 EXE에서 격리가 무력화된다"


def test_smoke_injects_isolated_data_dir(smoke_src):
    assert "VIBE_DATA_DIR" in smoke_src, "smoke가 격리 디렉토리를 주입하지 않는다"
    assert "tempfile" in smoke_src, "격리 경로는 임시 디렉토리 기반이어야 한다"


def test_smoke_does_not_point_at_appdata(smoke_src):
    """격리 경로가 %APPDATA%를 가리키면 격리가 아니다."""
    m = re.search(r"VIBE_DATA_DIR'\]\s*=\s*str\((\w+)\)", smoke_src)
    assert m, "VIBE_DATA_DIR 주입 형태가 바뀌었다 — 격리 대상 경로를 확인할 것"
    var = m.group(1)
    assign = re.search(rf"{var}\s*=\s*(.+)", smoke_src)
    assert assign and 'APPDATA' not in assign.group(1), "격리 경로가 설치본 디렉토리를 가리킨다"


def test_smoke_still_isolates_ports(smoke_src):
    """포트 격리는 기존 보호장치 — 데이터 격리를 넣으면서 잃으면 안 된다."""
    assert "VIBE_PORT_BASE" in smoke_src


def test_pgdata_intentionally_shared(smoke_src):
    """[의도된 비격리] PG는 설치본과 공유가 정상 — 분리하면 빈 DB 생성으로 기동이 느려진다.

    이 결정이 사고로 오해돼 나중에 '격리 누락'으로 수정되는 것을 막기 위해 근거를 고정한다.
    """
    assert 'pgdata' in smoke_src, "pgdata를 격리하지 않는 이유가 주석에서 사라졌다"
