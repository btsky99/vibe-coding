"""
FILE: tests/test_lan_exec_gate.py
DESCRIPTION: LAN 원격실행 게이트 E2E — 미등록 폴더 요청이 claude를 띄우지 못하는지, 허용 요청이
             yolo 없이 사본 작업공간에서 도는지, target_dir 변조가 토큰 서명에 걸리는지 검증.

REVISION HISTORY:
- 2026-07-30 Claude: 신규 — Phase A. '3중 게이트는 누가만 막고 무엇을은 무제한'이던 구멍의
                     회귀 방지. 단위 검증(test_lan_sandbox)이 통과해도 배선이 틀리면 무의미하므로
                     실제 실행 경로(_run_remote_exec)를 직접 태운다.
"""

import hashlib
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

import api.lan_api as lan_api
from infra import proc as _proc


class _FakeProc:
    """claude 대신 즉시 성공 종료하는 스텁 — 실제 CLI 설치/네트워크에 의존하지 않게."""

    def __init__(self):
        self.stdout = iter([b''])
        self.returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _setup(tmp_path, monkeypatch, allowed: list):
    """config.json + DB/네트워크 차단 스텁. 반환: (emitted 리스트, popen 호출 리스트)"""
    (tmp_path / 'config.json').write_text(
        json.dumps({'lan_exec_allowed_dirs': allowed}), encoding='utf-8')
    emitted: list = []
    calls: list = []
    monkeypatch.setattr(lan_api, '_proxy',
                        lambda dd, method, path, body=None: emitted.append((path, body)) or {})
    monkeypatch.setattr(lan_api, 'update_lan_exec_status', lambda *a, **k: None)
    monkeypatch.setattr(_proc, 'popen',
                        lambda cmd, **kw: (calls.append((cmd, kw)), _FakeProc())[1])
    return emitted, calls


def test_unlisted_dir_never_spawns_claude(tmp_path, monkeypatch):
    """[핵심] 화이트리스트에 없는 폴더 요청은 실행 없이 거부되고 사유가 요청자에게 전달된다."""
    (tmp_path / 'ok').mkdir()
    secret = tmp_path / 'secret'
    secret.mkdir()
    emitted, calls = _setup(tmp_path, monkeypatch, [{'path': str(tmp_path / 'ok')}])

    lan_api._run_remote_exec(tmp_path, 'peer1', 'exec1', '작업해', 'proj', str(secret))

    assert calls == [], 'claude가 실행되면 안 됨 — 폴더 게이트가 뚫렸다'
    assert any('폴더 거부' in str(body) for _, body in emitted), '거부 사유가 통지되지 않음'


def test_missing_target_dir_is_rejected(tmp_path, monkeypatch):
    """target_dir 없는 요청(구버전/우회 시도)도 거부 — 과거엔 프로젝트 루트로 실행됐다."""
    (tmp_path / 'ok').mkdir()
    emitted, calls = _setup(tmp_path, monkeypatch, [{'path': str(tmp_path / 'ok')}])

    lan_api._run_remote_exec(tmp_path, 'peer1', 'exec2', '작업해', 'proj', '')

    assert calls == []
    assert any('폴더 거부' in str(body) for _, body in emitted)


def test_allowed_copy_mode_runs_sandboxed(tmp_path, monkeypatch):
    """허용 폴더 요청은 실행되지만 ①원본이 아닌 사본 cwd ②yolo 없음 ③deny 프로파일 주입."""
    origin = tmp_path / 'proj'
    origin.mkdir()
    (origin / 'main.py').write_text('print(1)', encoding='utf-8')
    emitted, calls = _setup(tmp_path, monkeypatch, [{'path': str(origin), 'mode': 'copy'}])

    lan_api._run_remote_exec(tmp_path, 'peer1', 'exec3', '작업해', 'proj', str(origin))

    assert len(calls) == 1, 'claude가 실행되지 않았다'
    cmd, kw = calls[0]
    cwd = Path(kw['cwd']).resolve()
    assert cwd != origin.resolve(), '사본 모드인데 원본에서 실행됨'
    assert (cwd / 'main.py').exists(), '작업공간에 원본 내용이 없음'
    assert '--dangerously-skip-permissions' not in cmd, 'yolo가 되살아났다 — 격리 무의미'
    assert '--settings' in cmd, 'deny 프로파일이 주입되지 않음'
    profile = json.loads(Path(cmd[cmd.index('--settings') + 1]).read_text(encoding='utf-8'))
    assert profile['permissions']['defaultMode'] != 'bypassPermissions'


def test_allowed_direct_mode_uses_origin(tmp_path, monkeypatch):
    """direct 모드는 사용자가 명시 등록한 경우에만 원본 cwd를 쓴다(요구사항: 폴더 직접 편집)."""
    origin = tmp_path / 'proj'
    origin.mkdir()
    emitted, calls = _setup(tmp_path, monkeypatch, [{'path': str(origin), 'mode': 'direct'}])

    lan_api._run_remote_exec(tmp_path, 'peer1', 'exec4', '작업해', 'proj', str(origin))

    cmd, kw = calls[0]
    assert Path(kw['cwd']).resolve() == origin.resolve()
    assert '--dangerously-skip-permissions' not in cmd, 'direct 모드도 yolo는 금지'


def test_target_dir_is_covered_by_token_signature():
    """[보안] target_dir 변조 시 서명이 달라져야 한다 — 서명 밖이면 폴더 바꿔치기가 가능했다."""
    sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'lan_bridge_mod', _PROJECT_ROOT / '.ai_monitor' / 'lan_bridge.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    base = mod._exec_body_hash('작업', 'D:/allowed')
    assert base != mod._exec_body_hash('작업', 'D:/secret'), 'target_dir이 서명에 포함되지 않음'
    assert base != mod._exec_body_hash('다른작업', 'D:/allowed')
    # NUL 구분자 — 연접 모호성(task='a',dir='b' vs task='ab',dir='')이 같은 해시가 되면 안 된다
    assert mod._exec_body_hash('a', 'b') != mod._exec_body_hash('ab', '')
    # 구버전 규약(sha256(task)만)과 달라야 한다 = 와이어 변경이 실제로 적용됨
    assert base != hashlib.sha256('작업'.encode()).hexdigest()


# ── stream-json 파서 (2026-08-14 connector_relay에서 이관) ──────────────────
# 원래 tests/test_connector_relay.py 소유였다. Discord 커넥터 계층을 걷어내며
# 유일한 소비자가 LAN 원격 실행이 되어 파서와 함께 여기로 옮겼다.

def test_스트림_파서가_한글_간격을_보존한다():
    line = json.dumps({'type': 'assistant',
                       'message': {'content': [{'type': 'text',
                                                'text': '안녕하세요! 무엇을 도와드릴까요?'}]}})
    assert lan_api._extract_stream_text(line) == '안녕하세요! 무엇을 도와드릴까요?'


def test_스트림_파서가_result_중복을_버린다():
    """result는 전체 재전송이라 그대로 이으면 응답이 두 번 나간다."""
    assert lan_api._extract_stream_text('{"type":"result","result":"전체 재전송"}') == ''


def test_스트림_파서가_비JSON을_폴백으로_흘린다():
    assert lan_api._extract_stream_text('그냥 텍스트') == '그냥 텍스트\n'
    assert lan_api._extract_stream_text('   ') == ''


def test_스트림_파서가_도구_호출을_표시한다():
    line = json.dumps({'type': 'assistant',
                       'message': {'content': [{'type': 'tool_use', 'name': 'Read'}]}})
    assert '[도구: Read]' in lan_api._extract_stream_text(line)
