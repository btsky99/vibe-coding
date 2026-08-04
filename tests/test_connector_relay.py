# -*- coding: utf-8 -*-
"""
FILE: tests/test_connector_relay.py
DESCRIPTION: Discord 등 connector 턴을 헤드리스 claude로 돌리는 릴레이 회귀 테스트.

             [WHY 이 테스트가 존재하나 — 2026-08-04]
             이전 구현은 PTY(대화형 TUI) 화면을 정규식으로 긁어 답변을 복원했다. 실측에서
             cmd.exe 부팅 배너가 '답변'으로 전송되고 한글 공백이 소실됐다. 구조를 stream-json
             캡처로 바꿨으므로, 화면 스크레이프로 되돌아가는 회귀를 여기서 막는다.

REVISION HISTORY:
- 2026-08-04 Claude: 신규 — 화면 스크레이프 → stream-json 전환분 고정.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
sys.path.insert(0, str(_AI_MONITOR))

# agent_api(_build_chat_cmd)를 지연 import하므로 cli_agent 목이 필요하다.
_mock_cli_agent = MagicMock()
_mock_cli_agent._status_lock = threading.Lock()
sys.modules.setdefault("cli_agent", _mock_cli_agent)

from api import connector_relay


def _collect():
    published = []

    def bus_append(*args, **kwargs):
        published.append((args, kwargs))
        return 99
    return published, bus_append


def _reset_sessions(monkeypatch):
    monkeypatch.setattr(connector_relay, '_SESSIONS', {})


# ── stream-json 파싱 ────────────────────────────────────────────────────────

def test_extract_stream_text_keeps_korean_spacing():
    """[과거사고] 화면 스크레이프는 '안녕하세요! 무엇을'을 '안녕하세요!무엇을'로 뭉갰다."""
    line = ('{"type":"assistant","message":{"content":'
            '[{"type":"text","text":"안녕하세요! 무엇을 도와드릴까요?"}]}}')
    assert connector_relay.extract_stream_text(line) == '안녕하세요! 무엇을 도와드릴까요?'


def test_extract_stream_text_ignores_result_duplicate():
    assert connector_relay.extract_stream_text('{"type":"result","result":"전체 재전송"}') == ''


def test_extract_session_id():
    assert connector_relay.extract_session_id('{"type":"system","session_id":"abc-1"}') == 'abc-1'
    assert connector_relay.extract_session_id('그냥 텍스트') == ''


# ── 슬롯 → 프로젝트 폴더 해석 ────────────────────────────────────────────────

def test_resolve_cwd_maps_terminal_to_slot_project(tmp_path):
    """[제약] slot_projects는 0-based, 터미널은 1-based — T2는 슬롯 '1'이다."""
    target = tmp_path / 'ons'
    target.mkdir()
    cfg = tmp_path / 'config.json'
    cfg.write_text(f'{{"slot_projects": {{"1": "{target.as_posix()}"}}}}', encoding='utf-8')

    assert connector_relay.resolve_cwd('T2', cfg, 'FALLBACK') == target.as_posix()


def test_resolve_cwd_falls_back_when_slot_missing_or_gone(tmp_path):
    cfg = tmp_path / 'config.json'
    cfg.write_text('{"slot_projects": {"0": "D:/사라진폴더"}}', encoding='utf-8')

    assert connector_relay.resolve_cwd('T1', cfg, 'FALLBACK') == 'FALLBACK'   # 존재하지 않는 경로
    assert connector_relay.resolve_cwd('T3', cfg, 'FALLBACK') == 'FALLBACK'   # 미등록 슬롯
    assert connector_relay.resolve_cwd('T1', None, 'FALLBACK') == 'FALLBACK'  # 주입 전


# ── 릴레이 한 턴 ────────────────────────────────────────────────────────────

def test_relay_publishes_structured_answer(monkeypatch, tmp_path):
    _reset_sessions(monkeypatch)
    published, bus_append = _collect()
    monkeypatch.setattr(connector_relay, '_run_headless',
                        lambda cmd, cwd: ('정리했습니다.', 'sess-1', 0))

    connector_relay.relay_turn('T1', 'D--vibe-coding', '상태 알려줘', 7,
                               bus_append, None, str(tmp_path))

    args, kwargs = published[-1]
    assert args[2] == 'assistant' and args[3] == '정리했습니다.'
    assert kwargs['reply_to_seq'] == 7
    assert 'error' not in kwargs
    # 다음 턴이 같은 대화를 이어받도록 세션 ID가 남아야 한다
    assert connector_relay._SESSIONS['T1:D--vibe-coding'] == 'sess-1'


def test_relay_reuses_session_on_next_turn(monkeypatch, tmp_path):
    _reset_sessions(monkeypatch)
    _published, bus_append = _collect()
    seen = []

    def fake(cmd, cwd):
        seen.append(cmd)
        return ('ok', 'sess-1', 0)
    monkeypatch.setattr(connector_relay, '_run_headless', fake)

    for _ in range(2):
        connector_relay.relay_turn('T1', 'P', '안녕', 1, bus_append, None, str(tmp_path))

    assert '--resume' not in seen[0], '첫 턴은 새 세션이어야 한다'
    assert seen[1][seen[1].index('--resume') + 1] == 'sess-1'


def test_relay_retries_once_when_stored_session_is_dead(monkeypatch, tmp_path):
    """[WHY] 세션이 만료/삭제되면 --resume이 즉시 실패한다. 재시도가 없으면 그 채널은 영구히 죽는다."""
    _reset_sessions(monkeypatch)
    connector_relay._SESSIONS['T1:P'] = 'stale'
    published, bus_append = _collect()
    attempts = []

    def fake(cmd, cwd):
        attempts.append(cmd)
        if '--resume' in cmd:
            return ('', '', 1)
        return ('복구 후 응답', 'sess-new', 0)
    monkeypatch.setattr(connector_relay, '_run_headless', fake)

    connector_relay.relay_turn('T1', 'P', '안녕', 3, bus_append, None, str(tmp_path))

    assert len(attempts) == 2
    assert published[-1][0][3] == '복구 후 응답'
    assert 'error' not in published[-1][1]
    assert connector_relay._SESSIONS['T1:P'] == 'sess-new'


def test_relay_reports_failure_instead_of_silent_success(monkeypatch, tmp_path):
    """[불변식] 실패도 반드시 assistant 메시지를 남긴다 — 무음이면 Discord가 180초를 통째로 기다린다."""
    _reset_sessions(monkeypatch)
    published, bus_append = _collect()
    monkeypatch.setattr(connector_relay, '_run_headless', lambda cmd, cwd: ('', '', 2))

    connector_relay.relay_turn('T1', 'P', '안녕', 5, bus_append, None, str(tmp_path))

    assert published[-1][1]['error'] == 'exit_2'
    assert published[-1][1]['reply_to_seq'] == 5
    assert published[-1][0][3], '본문이 비면 사용자가 원인을 알 수 없다'


def test_relay_reports_exception(monkeypatch, tmp_path):
    _reset_sessions(monkeypatch)
    published, bus_append = _collect()

    def boom(cmd, cwd):
        raise OSError('실행 파일 없음')
    monkeypatch.setattr(connector_relay, '_run_headless', boom)

    connector_relay.relay_turn('T1', 'P', '안녕', 6, bus_append, None, str(tmp_path))

    assert published[-1][1]['error'] == 'OSError'
    assert published[-1][1]['reply_to_seq'] == 6


def test_relay_serializes_same_terminal(monkeypatch, tmp_path):
    """[불변식] 같은 세션에 두 턴이 동시에 들어가면 --resume 트랜스크립트가 꼬인다."""
    _reset_sessions(monkeypatch)
    _published, bus_append = _collect()
    overlap = {'inside': 0, 'max': 0}
    barrier = threading.Lock()

    def fake(cmd, cwd):
        with barrier:
            overlap['inside'] += 1
            overlap['max'] = max(overlap['max'], overlap['inside'])
        threading.Event().wait(0.05)
        with barrier:
            overlap['inside'] -= 1
        return ('ok', 'sess', 0)
    monkeypatch.setattr(connector_relay, '_run_headless', fake)

    threads = [threading.Thread(target=connector_relay.relay_turn,
                               args=('T1', 'P', '안녕', i, bus_append, None, str(tmp_path)))
               for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert overlap['max'] == 1, '터미널별 직렬화가 깨졌다'


def test_no_screen_scraping_helpers_remain():
    """화면 스크레이프로 되돌아가는 회귀 차단 — 정규식 필터는 부활시키지 않는다."""
    source = (_AI_MONITOR / 'api' / 'agent_api.py').read_text(encoding='utf-8')
    assert '_clean_connector_output' not in source
    assert '_CONNECTOR_TUI_NOISE' not in source
