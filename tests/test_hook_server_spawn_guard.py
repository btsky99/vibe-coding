"""
FILE: tests/test_hook_server_spawn_guard.py
DESCRIPTION: hook_bridge._start_server 스폰 가드 회귀 테스트 — 앱(GUI)이 살아있는 동안
             훅이 2번째 server.py 인스턴스를 절대 스폰하지 않는 불변식을 고정한다.

REVISION HISTORY:
- 2026-08-02 Claude: 신규. 앱이 타 프로젝트(D:/ons)를 열어둔 상태에서 vibe-coding 폴더의
                     Claude Code가 메시지를 보내면 슬러그 대조 실패로 '내 서버 없음' 판정 →
                     server.py 스폰. 단일 인스턴스 락은 project_root 시드라 슬러그가 다르면
                     걸리지 않아 2번째 인스턴스가 끝까지 부팅, 자체 PTY 서버가 9000번대 포트
                     슬롯을 경쟁하다 살아있는 터미널 세션이 통째로 죽었다. 실측 재현:
                     find_server_port('D--vibe-coding')=None인데 9000은 정상 응답.
"""

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import hook_bridge as hb


class _SpawnSpy:
    """subprocess.Popen 대역 — 호출되면 즉시 기록한다(실제 프로세스 생성 금지)."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        raise AssertionError("스폰 가드가 뚫렸다 — server.py가 실제로 실행될 뻔했다")


@pytest.fixture(autouse=True)
def _clean_hook_env(monkeypatch):
    """훅의 조기 종료 환경변수를 걷어낸다.

    [🔴 왜 필요한가] main()은 OFFICE_MODE / VIBE_CHILD_AGENT 가 세팅돼 있으면 아무것도
      출력하지 않고 sys.exit(0) 한다(캐스케이드 루프 방지). 그런데 이 테스트를 돌리는
      개발자의 셸이 cli_agent 가 띄운 자식 세션이면 VIBE_CHILD_AGENT=1 이 상속돼 있어,
      가드 분기를 한 줄도 타지 않은 채 "exit 0 · 폴백 0회"가 되어 **테스트가 통과처럼
      보인다**. 실제로 2026-08-09 이 환경에서 마지막 문구 단언만 깨져 발각됐다 —
      단언 하나가 없었으면 환경 의존 거짓 통과였다.
    [불변식] main()을 부르는 테스트는 환경변수를 상속하지 않는다. autouse 인 이유는
      새 테스트가 이 격리를 잊고 추가되는 것을 막기 위해서다.
    """
    monkeypatch.delenv("OFFICE_MODE", raising=False)
    monkeypatch.delenv("VIBE_CHILD_AGENT", raising=False)


@pytest.fixture
def spy(monkeypatch):
    s = _SpawnSpy()
    monkeypatch.setattr(hb.subprocess, "Popen", s)
    # SERVER_PY 존재 판정을 통과시켜야 가드까지 도달한다(파일 없으면 조기 return).
    monkeypatch.setattr(hb, "SERVER_PY", _ROOT / ".ai_monitor" / "server.py")
    return s


def test_app_alive_blocks_spawn_even_when_slug_mismatches(monkeypatch, spy):
    """[핵심] 앱이 살아있으면 슬러그 대조 실패해도 스폰하지 않는다.

    이 케이스가 실제 사고 조건이다 — 앱은 D:/ons를 열고 있고 훅은 D--vibe-coding을 찾는다.
    """
    monkeypatch.setattr(hb, "_is_server_alive", lambda pid="": False)
    monkeypatch.setattr(hb, "_is_app_server_running", lambda: True)

    assert hb._start_server("D--vibe-coding") is False
    assert spy.calls == []


def test_stale_server_pid_does_not_reopen_spawn_path(monkeypatch, spy, tmp_path):
    """[회귀] .server.pid가 죽은 PID여도 앱이 살아있으면 스폰 금지.

    가드 도입 전에는 이 조합(_is_server_alive False + .server.pid stale)이 정확히
    스폰 경로였다 — 가드가 _is_already_running보다 **앞**에 있어야 성립한다.
    """
    stale = tmp_path / ".server.pid"
    stale.write_text("999999 0", encoding="utf-8")  # 존재할 수 없는 PID
    monkeypatch.setattr(hb, "_SERVER_PID", stale)
    monkeypatch.setattr(hb, "_is_server_alive", lambda pid="": False)
    monkeypatch.setattr(hb, "_is_app_server_running", lambda: True)

    assert hb._start_server("D--vibe-coding") is False
    assert spy.calls == []


def test_app_dead_still_allows_spawn(monkeypatch, tmp_path):
    """[대칭] 앱이 정말 죽었으면 자동 시작 경로는 살아있어야 한다.

    가드가 과잉 차단하면 서버 없는 환경에서 훅의 자동 기동이 영구 무력화된다.
    """
    called = {"n": 0}

    class _Proc:
        pid = 4242

    def _fake_popen(*args, **kwargs):
        called["n"] += 1
        return _Proc()

    monkeypatch.setattr(hb, "SERVER_PY", _ROOT / ".ai_monitor" / "server.py")
    monkeypatch.setattr(hb.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(hb, "_SERVER_PID", tmp_path / ".server.pid")
    monkeypatch.setattr(hb, "_is_server_alive", lambda pid="": False)
    monkeypatch.setattr(hb, "_is_app_server_running", lambda: False)
    monkeypatch.setattr(hb, "_is_already_running", lambda p: False)
    monkeypatch.setattr(hb.time, "sleep", lambda s: None)  # 5초 대기 루프 단축

    hb._start_server("D--vibe-coding")
    assert called["n"] == 1


def test_app_pid_file_is_never_mutated(monkeypatch, tmp_path):
    """[불변식] .dev_server.pid는 server.py 소유 — 훅은 읽기만 한다.

    _is_already_running을 재사용하면 stale 판정 시 unlink + .lock 생성으로 남의 상태
    파일을 파괴한다. 그래서 전용 읽기 함수를 따로 둔 것이다.
    """
    devpid = tmp_path / ".dev_server.pid"
    devpid.write_text("999999", encoding="utf-8")  # 죽은 PID = stale 조건
    monkeypatch.setattr(hb, "_DEV_SERVER_PID", devpid)

    assert hb._is_app_server_running() is False
    assert devpid.exists(), "훅이 앱 소유 PID 파일을 삭제했다"
    assert not (tmp_path / ".dev_server.pid.lock").exists(), "훅이 앱 파일에 락을 만들었다"


def test_app_alive_skips_offline_fallback(monkeypatch, capsys):
    """[핵심] 앱이 살아있으면 오프라인 폴백(cli_agent)도 타지 않는다.

    폴백은 claude.exe를 하나 더 띄운다. 사용자는 이미 이 CLI 세션에서 같은 프롬프트로
    대화 중이므로 한 메시지가 API를 두 번 호출하게 되고(쿼터 이중 소모 + 429 유발),
    백그라운드 클로드가 전경 세션과 같은 파일을 동시에 고칠 수도 있다.
    """
    called = {"fallback": 0, "spawn": 0}
    monkeypatch.setattr(hb, "_fallback_subprocess",
                        lambda *a, **k: called.__setitem__("fallback", called["fallback"] + 1))
    monkeypatch.setattr(hb, "_start_server",
                        lambda *a, **k: called.__setitem__("spawn", called["spawn"] + 1) or False)
    monkeypatch.setattr(hb, "_call_api", lambda *a, **k: None)   # 자기 서버 없음
    monkeypatch.setattr(hb, "_is_app_server_running", lambda: True)
    monkeypatch.setattr(hb, "_inject_hive_context", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        '{"cwd": "D:/vibe-coding", "prompt": "테스트 프롬프트"}'))

    with pytest.raises(SystemExit) as exc:
        hb.main()

    assert exc.value.code == 0, "훅은 반드시 0으로 끝나야 한다(non-zero면 Claude 응답이 끊긴다)"
    assert called["fallback"] == 0, "앱이 살아있는데 폴백이 클로드를 또 띄웠다"
    assert called["spawn"] == 0, "앱이 살아있는데 server.py 스폰을 시도했다"
    # [WHY 이 단언] 위 두 카운터만 보면 main()이 다른 경로(SKIP 접두사 등)로 조기 종료해도
    # 통과한다 — 가드 분기를 실제로 통과했다는 증거로 안내 문구를 확인한다.
    assert '자율 에이전트 생략' in capsys.readouterr().out


def test_app_pid_file_accepts_both_formats(monkeypatch, tmp_path):
    """[형식] server.py는 'PID'만, 훅은 'PID 타임스탬프'로 쓴다 — 첫 토큰만 읽어야 한다."""
    devpid = tmp_path / ".dev_server.pid"
    monkeypatch.setattr(hb, "_DEV_SERVER_PID", devpid)
    monkeypatch.setattr(hb, "_is_process_alive", lambda pid: pid == 4324)

    devpid.write_text("4324", encoding="utf-8")
    assert hb._is_app_server_running() is True

    devpid.write_text("4324 1785598964.35", encoding="utf-8")
    assert hb._is_app_server_running() is True

    devpid.write_text("", encoding="utf-8")
    assert hb._is_app_server_running() is False
