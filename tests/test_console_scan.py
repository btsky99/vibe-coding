"""
FILE: tests/test_console_scan.py
DESCRIPTION: 콘솔 창 식별(infra/console_scan) + 상태판 라우트(api/nodes_api) 회귀 테스트.
  실제 프로세스 스냅샷 대신 합성 데이터를 주입해 판정 규칙만 검증한다 — 실행 환경에
  어떤 프로그램이 떠 있든 결과가 흔들리지 않아야 한다.

[WHY 이 테스트가 필요한가] 판정 규칙은 실측으로 두 번 뒤집혔다.
  ① conhost 존재만으로 필터하면 서비스/트레이 앱이 절반(실측 19건 중 16건 노이즈)
  ② conhost의 '부모'만 보면 부모가 죽은 콘솔(pg_ctl이 남긴 cmd)을 통째로 놓친다
  둘 다 조용한 오작동이라 테스트 없이는 재발을 못 잡는다.

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 상태판 기능 회귀 방어.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.ai_monitor'))

from infra import console_scan  # noqa: E402


def _proc(pid, ppid, name, cmdline='', exe='', created='20260802120000'):
    return {'pid': pid, 'ppid': ppid, 'name': name, 'cmdline': cmdline,
            'exe': exe, 'created': created}


@pytest.fixture
def fake_procs():
    """실측 구조를 그대로 옮긴 합성 스냅샷.

    pg_ctl(34196)은 start 직후 죽어 스냅샷에 없다 — 살아남은 건 형제 cmd(18520)와
    conhost(22600)뿐이고 둘의 ppid만 34196을 가리킨다. 이게 실제로 놓쳤던 구조다.
    """
    rows = [
        _proc(100, 1, 'python.exe', 'python server.py', r'D:\vibe-coding\.ai_monitor\venv\Scripts\python.exe'),
        _proc(101, 100, 'node.exe', r'node D:\vibe-coding\.ai_monitor\pty-server\pty-server.js', r'D:\node.exe'),
        # 슬롯 안 ConPTY — 창이 없어야 한다
        _proc(102, 101, 'conhost.exe', 'conhost.exe --headless --width 98 --height 64'),
        _proc(103, 101, 'cmd.exe', 'cmd.exe', r'C:\WINDOWS\system32\cmd.exe'),
        # 앱 데몬(조상 체인이 끊긴 상태) — 경로로 owned 판정돼야 한다
        _proc(200, 9999, 'python.exe', 'python daemon.py', r'D:\vibe-coding\.ai_monitor\venv\Scripts\python.exe'),
        _proc(201, 200, 'conhost.exe', 'conhost.exe 0x4'),
        # pg_ctl이 남긴 외부 콘솔 — 부모(34196)는 이미 죽었다
        _proc(18520, 34196, 'cmd.exe',
              r'"C:\WINDOWS\system32\cmd.exe" /C ""C:/CipherTraderPG/bin/postgres.exe" -D "D:/x" >> "pg.log" 2>&1"',
              r'C:\WINDOWS\system32\cmd.exe'),
        _proc(22600, 34196, 'conhost.exe', 'conhost.exe 0x4'),
        # 숨은 서비스 콘솔 — 보이는 창이 없으므로 제외돼야 한다
        _proc(300, 1, 'java.exe', 'java -jar svc.jar', r'C:\jre\bin\java.exe'),
        _proc(301, 300, 'conhost.exe', 'conhost.exe 0x4'),
    ]
    return {p['pid']: p for p in rows}


def _scan_with(monkeypatch, procs, visible, server_pid):
    monkeypatch.setattr(console_scan, 'IS_WINDOWS', True)
    monkeypatch.setattr(console_scan, 'snapshot', lambda force=False: procs)
    monkeypatch.setattr(console_scan, 'visible_windows', lambda: visible)
    monkeypatch.setattr(console_scan, '_app_roots', lambda: [os.path.normcase(r'D:\vibe-coding')])
    return {c['pid']: c for c in console_scan.scan(server_pid=server_pid)}


def test_dead_parent_console_is_found(monkeypatch, fake_procs):
    """[과거사고] pg_ctl이 죽어도 형제 cmd가 붙든 콘솔 창은 반드시 잡혀야 한다."""
    visible = {18520: r'C:\CipherTraderPG\bin\pg_ctl.exe', 200: 'daemon'}
    found = _scan_with(monkeypatch, fake_procs, visible, server_pid=100)
    assert 18520 in found, 'conhost 부모가 죽은 콘솔을 놓쳤다'
    assert found[18520]['title'] == r'C:\CipherTraderPG\bin\pg_ctl.exe'
    assert found[18520]['owner'] == 'foreign'


def test_hidden_service_console_excluded(monkeypatch, fake_procs):
    """보이는 창이 없는 콘솔(서비스/트레이)은 목록에 나오면 안 된다."""
    visible = {18520: 'pg_ctl', 200: 'daemon'}
    found = _scan_with(monkeypatch, fake_procs, visible, server_pid=100)
    assert 300 not in found, '숨은 서비스 콘솔이 목록에 섞였다'


def test_conpty_slot_excluded(monkeypatch, fake_procs):
    """--headless conhost(터미널 슬롯 내부)는 창이 아니므로 제외."""
    visible = {103: 'cmd', 18520: 'pg_ctl'}
    found = _scan_with(monkeypatch, fake_procs, visible, server_pid=100)
    assert 103 not in found, 'ConPTY 슬롯이 떠 있는 창으로 잡혔다'


def test_app_daemon_is_owned_by_path(monkeypatch, fake_procs):
    """조상 체인이 끊겨도 실행 경로가 앱 트리 안이면 owned — 실측 오판 재발 방지."""
    visible = {200: '데몬 콘솔'}
    found = _scan_with(monkeypatch, fake_procs, visible, server_pid=100)
    assert found[200]['owner'] == 'owned'
    assert '다른 인스턴스' in found[200]['label']


def test_describe_unwraps_cmd_and_shows_script():
    """cmd 래퍼를 걷어내고 실제 실행 대상을 뽑아야 한다."""
    pg = _proc(1, 0, 'cmd.exe',
               r'"C:\WINDOWS\system32\cmd.exe" /C ""C:/PG/bin/postgres.exe" -D "D:/x" >> "log" 2>&1"')
    assert 'postgres.exe' in console_scan._describe(pg)

    py = _proc(2, 0, 'cmd.exe',
               r'cmd.exe /c ""D:\CipherTrader\venv\Scripts\python.exe" -u .cache\train_monitor.py > "out""')
    desc = console_scan._describe(py)
    assert 'python.exe' in desc and 'train_monitor.py' in desc, desc


def test_kill_rejects_pid_reuse(monkeypatch, fake_procs):
    """[블로커 방어] created/exe가 어긋나면 절대 종료하지 않는다."""
    monkeypatch.setattr(console_scan, 'IS_WINDOWS', True)
    monkeypatch.setattr(console_scan, 'snapshot', lambda force=False: fake_procs)
    called = []
    monkeypatch.setattr(console_scan.proc, 'run', lambda *a, **k: called.append(a))

    res = console_scan.kill(18520, created='19990101000000', exe=r'C:\WINDOWS\system32\cmd.exe')
    assert res['ok'] is False and res['reason'] == 'mismatch'
    assert not called, 'PID 재사용 의심 상황에서 taskkill이 실행됐다'


def test_kill_rejects_missing_process(monkeypatch, fake_procs):
    monkeypatch.setattr(console_scan, 'IS_WINDOWS', True)
    monkeypatch.setattr(console_scan, 'snapshot', lambda force=False: fake_procs)
    res = console_scan.kill(77777, created='20260802120000', exe='x')
    assert res['ok'] is False and res['reason'] == 'gone'


def test_ancestors_survives_pid_cycle():
    """PID 재사용으로 부모 체인에 사이클이 생겨도 무한 루프에 빠지면 안 된다."""
    procs = {1: _proc(1, 2, 'a.exe'), 2: _proc(2, 1, 'b.exe')}
    assert console_scan._ancestors(1, procs) == [2]


def test_non_windows_returns_empty(monkeypatch):
    monkeypatch.setattr(console_scan, 'IS_WINDOWS', False)
    assert console_scan.scan() == []
    assert console_scan.kill(1, '', '')['ok'] is False


# ── 라우트 계약 ──────────────────────────────────────────────────────────────
class _FakeHandler:
    """nodes_api가 기대하는 최소 인터페이스만 흉내낸 핸들러."""

    def __init__(self, body: dict | None = None):
        raw = json.dumps(body or {}).encode('utf-8')
        self.headers = {'Content-Length': str(len(raw))}
        self._raw = raw
        self.chunks: list[bytes] = []

        class _RFile:
            def __init__(self, data): self.data = data
            def read(self, n): return self.data[:n]

        class _WFile:
            def __init__(self, sink): self.sink = sink
            def write(self, b): self.sink.append(b)

        self.rfile = _RFile(raw)
        self.wfile = _WFile(self.chunks)

    def send_response(self, code): pass
    def send_header(self, k, v): pass
    def end_headers(self): pass
    def _cors_origin(self): return '*'

    @property
    def payload(self) -> dict:
        return json.loads(b''.join(self.chunks).decode('utf-8'))


def test_consoles_route_shape(monkeypatch):
    from api import nodes_api
    monkeypatch.setattr(console_scan, 'scan', lambda server_pid=None: [
        {'pid': 1, 'title': 't', 'name': 'cmd.exe', 'exe': 'e', 'created': 'c',
         'cmdline': '', 'summary': 's', 'owner': 'foreign', 'label': 'x', 'ancestry': []},
    ])
    h = _FakeHandler()
    nodes_api.consoles(h)
    body = h.payload
    assert body['counts'] == {'owned': 0, 'slot': 0, 'foreign': 1}
    assert body['consoles'][0]['pid'] == 1


def test_kill_route_requires_pid():
    from api import nodes_api
    h = _FakeHandler({'created': 'x', 'exe': 'y'})
    nodes_api.console_kill(h)
    assert h.payload['ok'] is False
    assert h.payload['reason'] == 'bad_request'


def test_check_cli_rejects_unknown_alias(monkeypatch):
    """[보안] ssh config에 없는 별칭으로는 ssh를 부르지 않는다."""
    from api import nodes_api, pty_api
    monkeypatch.setattr(pty_api, '_node_get', lambda path, timeout=3.0: {'hosts': [{'alias': 'lenovo', 'aliases': ['lenovo']}]})
    called = []
    from infra import node_status
    monkeypatch.setattr(node_status, 'check_remote_clis', lambda alias, timeout=12: called.append(alias) or {})

    h = _FakeHandler({'alias': 'evil; rm -rf /'})
    nodes_api.check_cli(h)
    assert h.payload['ok'] is False
    assert not called, '화이트리스트에 없는 별칭으로 ssh가 실행됐다'
