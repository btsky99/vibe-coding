"""
FILE: tests/test_shutdown_marker.py
DESCRIPTION: '사람이 껐다' 표식과 워치독의 복구 게이트 회귀 테스트.
             지키는 계약 2개 — ① 사장이 끄면 꺼진 채 있는다 ② 진짜 죽으면 되살아난다.

REVISION HISTORY:
- 2026-08-16 Claude: 신설 — 고아 워치독이 앱을 되살리던 사고(껐는데 자꾸 살아남)의
  재발 방지. 이 파일이 깨지면 둘 중 하나가 무너진 것이므로 어느 쪽인지부터 볼 것.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MONITOR = ROOT / '.ai_monitor'
if str(MONITOR) not in sys.path:
    sys.path.insert(0, str(MONITOR))

from infra import shutdown_marker  # noqa: E402


def test_표식이_없으면_되살릴_대상이다(tmp_path):
    """크래시/강제종료는 표식을 남길 수 없다 → 자동 복구는 살아 있어야 한다."""
    assert shutdown_marker.was_intentional(tmp_path, time.time() - 10) is None


def test_사람이_끈_종료는_표식으로_증명된다(tmp_path):
    started = time.time() - 10
    shutdown_marker.mark(tmp_path, 'window_closed')
    intent = shutdown_marker.was_intentional(tmp_path, started)
    assert intent is not None
    assert intent['reason'] == 'window_closed'


def test_앱이_다시_뜨면_표식이_사라진다(tmp_path):
    """[WHY 중요] 표식이 남아 있으면 '다음번 진짜 크래시'까지 복구를 포기하게 된다."""
    shutdown_marker.mark(tmp_path, 'window_closed')
    shutdown_marker.clear(tmp_path)
    assert shutdown_marker.was_intentional(tmp_path, time.time() - 10) is None
    shutdown_marker.clear(tmp_path)   # 두 번 지워도 예외 없어야 함(부팅 경로에서 무조건 호출)


def test_내가_태어나기_전의_표식은_남의_것이다(tmp_path):
    """워치독은 앱과 함께 태어난다 — 그보다 오래된 표식은 이전 세대의 종료 기록이다.

    clear() 를 어딘가에서 놓쳐도 이 대조가 옛 표식의 영구 복구 차단을 막는다.
    """
    shutdown_marker.mark(tmp_path, 'window_closed')
    assert shutdown_marker.was_intentional(tmp_path, time.time() + 60) is None


def test_깨진_표식은_없는_것으로_본다(tmp_path):
    """[안전 방향] 판독 불가 = 복구 허용. 반대로 하면 파일 한 줄 깨짐이 자동 복구를 죽인다."""
    shutdown_marker.path(tmp_path).write_text('{{{ 깨진 json', encoding='utf-8')
    assert shutdown_marker.was_intentional(tmp_path, 0) is None


# ── 워치독 게이트 ────────────────────────────────────────────────────────────
def _watchdog(monkeypatch, tmp_path, *, parent_alive: bool, started_at: float):
    """hive_watchdog 을 테스트용 상수로 갈아끼워 인스턴스를 만든다.

    [제약] hive_watchdog 은 모듈 전역(DATA_DIR/PARENT_PID/STARTED_AT)을 import 시점에
      argv 로 굳힌다 — 그래서 인자 파싱이 아니라 모듈 속성을 직접 갈아끼운다.
    """
    sys.path.insert(0, str(ROOT / 'scripts'))
    import hive_watchdog as hw
    monkeypatch.setattr(hw, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(hw, 'STARTED_AT', started_at)
    monkeypatch.setattr(hw, 'PARENT_PID', 1234)
    monkeypatch.setattr(hw, 'CHECK_MODE', False)
    monkeypatch.setattr(hw, '_pid_alive', lambda pid: parent_alive)
    return hw.HiveWatchdog(interval=60)


@pytest.mark.parametrize('reason', ['window_closed', 'api_shutdown', 'headless_sigint'])
def test_사장이_끄면_되살리지_않는다(monkeypatch, tmp_path, reason):
    started = time.time() - 10
    shutdown_marker.mark(tmp_path, reason)
    wd = _watchdog(monkeypatch, tmp_path, parent_alive=False, started_at=started)
    wd.is_running = True                # start_loop 가동 중 상태를 흉내
    assert wd.should_restart() is False
    # 되살리지 않을 뿐 아니라 감시자 자신도 내려가야 한다(고아가 남아 다음 판정을 하면 안 됨)
    assert wd.is_running is False


def test_진짜_죽었으면_되살린다(monkeypatch, tmp_path):
    """감시자를 통째로 없애지 않았다는 증거 — 표식 없는 죽음은 복구 대상이다."""
    wd = _watchdog(monkeypatch, tmp_path, parent_alive=False, started_at=time.time() - 10)
    assert wd.should_restart() is True


def test_앱이_살아있으면_두번째_인스턴스를_띄우지_않는다(monkeypatch, tmp_path):
    """부팅 중(HTTP 미개통)을 '죽음'으로 오판하면 새 인스턴스가 락에 걸려 기존 창을
    포커스한다 — 사용자 눈엔 '창이 자꾸 튀어나옴'."""
    wd = _watchdog(monkeypatch, tmp_path, parent_alive=True, started_at=time.time() - 10)
    wd.is_running = True                # start_loop 가동 중 상태를 흉내
    assert wd.should_restart() is False
    assert wd.is_running is True        # 보류일 뿐 감시는 계속한다(자기 종료 금지)


def test_진단모드는_앱을_띄우지_않는다(monkeypatch, tmp_path):
    """--check 는 UI 헬스체크 버튼(/api/hive/health/repair)이 부르는 1회성 진단이다.
    진단이 앱을 띄우면 버튼 한 번에 창이 하나 더 뜬다."""
    wd = _watchdog(monkeypatch, tmp_path, parent_alive=False, started_at=time.time() - 10)
    sys.path.insert(0, str(ROOT / 'scripts'))
    import hive_watchdog as hw
    monkeypatch.setattr(hw, 'CHECK_MODE', True)
    assert wd.should_restart() is False


def test_실제_포트가_주입되면_그_포트만_본다(monkeypatch, tmp_path):
    """[사고 원인] 옛 코드는 9000~9005 만 봐서 9006·9008 슬롯 인스턴스를 항상 죽은 걸로 봤다."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import hive_watchdog as hw
    monkeypatch.setattr(hw, 'INSTANCE_PORT', 9008)
    wd = hw.HiveWatchdog(interval=60)
    probed = []
    monkeypatch.setattr(wd, '_probe', lambda port, timeout: probed.append(port) or True)
    assert wd.check_server() is True
    assert probed == [9008]
