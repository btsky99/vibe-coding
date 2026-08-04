# -*- coding: utf-8 -*-
"""
FILE: tests/test_agent_api.py
DESCRIPTION: agent_api.py 단위 테스트.
             최근 버그픽스(Codex 슬롯 오류, activeAgent 동기화) 재발 방지 및
             핵심 로직(handle_stage_update, _merge_live_file_status)
             의 정확성을 검증합니다.

             [테스트 전략]
             - cli_agent 의존성은 모킹 (실제 CLI 실행 없이 API 레이어만 테스트)
             - 파일 I/O는 tmp_path로 격리
             - HTTP 핸들러는 간단한 Mock 객체로 대체

REVISION HISTORY:
- 2026-08-04 Codex: connector PTY의 Claude TUI 재그리기 노이즈 정제 회귀 테스트 추가.
- 2026-08-03 Codex: Discord connector의 버스 전용 양방향 relay 회귀 테스트 추가.
- 2026-07-26 Codex: 프로젝트 스코프 PTY 선택 회귀 테스트 추가.
- 2026-06-11 Claude: gemini→antigravity 식별자 스윕 (agy 마이그레이션 Task 8)
- 2026-06-11 Claude: TestGetGeminiLastTask 삭제 — agy 전환으로 대상 함수 제거 (비공개 포맷)
- 2026-03-09 Claude: 최초 작성 — 버그픽스 a6bd38a, 6f05536 재발 방지 커버리지
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest


# 프로젝트 루트 경로 설정
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"

# cli_agent를 모킹한 뒤 agent_api 임포트 (실제 CLI 없이도 임포트 가능하도록)
sys.path.insert(0, str(_AI_MONITOR))
sys.path.insert(0, str(_AI_MONITOR / "api"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

# cli_agent mock을 sys.modules에 미리 주입
_mock_cli_agent = MagicMock()
_mock_cli_agent._status_lock = __import__("threading").Lock()
_mock_cli_agent._run_status = "idle"
_mock_cli_agent._current_run = None
sys.modules.setdefault("cli_agent", _mock_cli_agent)

import agent_api


def test_clean_connector_output_removes_claude_tui_redraw_noise():
    chunks = [
        '0; Claude Code', '안녕', 'Gusting    for agents', 'i', '*tg', 'ui',
        'Discombobulating',
        'Discombobulatingrunning stop hooks 0/2  7s  51 tokens)',
        'Discombobulating76', '(2s  2 tokens)', '*55', 'n30', 'i64', 'tg7',
        '안녕! 뭐 도와줄까?',
        '57.7k / 1M (6%) In 57.7k Out 254 캐시저장 31.4k',
        'Brewed for 10s', '0; Claude Code',
    ]

    assert agent_api._clean_connector_output(chunks, '안녕') == '안녕! 뭐 도와줄까?'


def test_clean_connector_output_deduplicates_redrawn_answer():
    chunks = ['답변 본문', '답변 본문', '\x1b]0; Claude Code\x07', '0; Claude Code']

    assert agent_api._clean_connector_output(chunks, '질문') == '답변 본문'


def test_connector_bus_relay_publishes_correlated_response(monkeypatch):
    calls = []
    ticks = iter(range(1000))

    def node(method, path, payload=None, timeout=5.0):
        calls.append((method, path, payload))
        if method == 'POST':
            return {'status': 'ok'}
        if 'since=0' in path:
            return {'latest_seq': 10, 'entries': []}
        if len([call for call in calls if call[0] == 'GET']) == 2:
            return {'latest_seq': 11, 'entries': [{'text': 'bus response'}]}
        return {'latest_seq': 11, 'entries': []}

    published = []
    monkeypatch.setattr(agent_api, '_node_json', node)
    monkeypatch.setattr(agent_api.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(agent_api.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(
        agent_api, '_bus_append',
        lambda *args, **kwargs: published.append((args, kwargs)) or 99,
    )

    agent_api._relay_connector_turn('T1', 'D--vibe-coding', 'hello', 7)

    assert [call for call in calls if call[0] == 'POST'] == [(
        'POST', '/api/pty/write/1?project_id=D--vibe-coding',
        {'target': 'T1', 'text': 'hello', 'project_id': 'D--vibe-coding'},
    )]
    assert published[-1][0][2] == 'assistant'
    assert 'bus response' in published[-1][0][3]
    assert published[-1][1]['reply_to_seq'] == 7


def test_connector_bus_relay_marks_not_running_as_error(monkeypatch):
    published = []
    monkeypatch.setattr(
        agent_api, '_node_json',
        lambda method, *_args, **_kwargs: (
            {'error': 'not_running'} if method == 'POST' else {'latest_seq': 0}),
    )
    monkeypatch.setattr(
        agent_api, '_bus_append',
        lambda *args, **kwargs: published.append((args, kwargs)) or 1,
    )

    agent_api._relay_connector_turn('T2', 'D--ons', 'hello', 8)

    assert published[-1][1]['reply_to_seq'] == 8
    assert published[-1][1]['error'] == 'not_running'


class TestProjectScopedPtyIdentity:
    def test_prefers_requested_project(self):
        snapshot = {
            "T1": {"running": False, "agent": ""},
            "T1@D--old": {"running": True, "agent": "claude", "last_input_at": 10},
            "T1@D--vibe-coding": {
                "running": True, "agent": "codex", "last_input_at": 20,
            },
        }
        selected = agent_api._running_pty_for_slot(snapshot, "T1", "D--vibe-coding")
        assert selected["agent"] == "codex"

    def test_falls_back_to_latest_running_project(self):
        snapshot = {
            "T3": {"running": False, "agent": ""},
            "T3@D--old": {
                "running": True, "agent": "antigravity", "last_input_at": 10,
            },
            "T3@D--CipherTrader": {
                "running": True, "agent": "claude", "last_input_at": 30,
            },
        }
        selected = agent_api._running_pty_for_slot(snapshot, "T3", "D--missing")
        assert selected["agent"] == "claude"


# ── handle_stage_update 테스트 ────────────────────────────────────────────────

class TestHandleStageUpdate:
    """POST /api/agent/stage 핸들러 — terminal_id 정규화 및 stage 저장 검증.

    [핵심 버그 재발 방지]
    커밋 6f05536: TERMINAL_ID 미설정 시 숫자 "2"가 오는 경우 "T2"로 자동 변환 필요.
    """

    def _make_handler(self, body: dict) -> MagicMock:
        """HTTP 핸들러 Mock 생성 헬퍼."""
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        handler = MagicMock()
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile.read.return_value = body_bytes
        return handler

    def setup_method(self):
        """각 테스트 전 _interactive_stages 초기화."""
        agent_api._interactive_stages.clear()

    def test_stage_update_정상_저장됨(self):
        """유효한 요청 시 _interactive_stages에 저장되어야 함."""
        handler = self._make_handler({
            "terminal_id": "T2",
            "stage": "analyzing",
            "task": "버그 수정 중"
        })
        agent_api.handle_stage_update(handler)

        assert "T2" in agent_api._interactive_stages
        assert agent_api._interactive_stages["T2"]["pipeline_stage"] == "analyzing"
        assert agent_api._interactive_stages["T2"]["task"] == "버그 수정 중"

    def test_stage_update_숫자_tid_T접두사_자동추가됨(self):
        """terminal_id가 숫자 "2"이면 "T2"로 정규화되어야 함 (버그 재발 방지)."""
        handler = self._make_handler({
            "terminal_id": "2",   # ← 숫자만 오는 경우 (hook_bridge TERMINAL_ID 미설정 시)
            "stage": "modifying",
            "task": "코드 수정"
        })
        agent_api.handle_stage_update(handler)

        # "2"가 아닌 "T2"로 저장되어야 함
        assert "T2" in agent_api._interactive_stages
        assert "2" not in agent_api._interactive_stages

    def test_stage_update_ok_응답_반환됨(self):
        """성공 시 {"ok": true} 응답이 반환되어야 함."""
        handler = self._make_handler({"terminal_id": "T1", "stage": "done", "task": ""})
        agent_api.handle_stage_update(handler)

        # wfile.write가 호출되었는지 확인
        handler.wfile.write.assert_called_once()
        response = json.loads(handler.wfile.write.call_args[0][0].decode("utf-8"))
        assert response == {"ok": True}

    def test_stage_update_ts_현재시간_저장됨(self):
        """저장된 ts는 현재 시간과 거의 같아야 함 (10초 이내)."""
        handler = self._make_handler({"terminal_id": "T3", "stage": "verifying", "task": ""})
        before = time.time()
        agent_api.handle_stage_update(handler)
        after = time.time()

        ts = agent_api._interactive_stages["T3"]["ts"]
        assert before <= ts <= after


# ── _merge_live_file_status 테스트 ────────────────────────────────────────────

class TestMergeLiveFileStatus:
    """agent_live.jsonl 이벤트 기반 터미널 상태 병합 로직 검증.

    [패치 전략]
    _merge_live_file_status()는 Path(__file__) 기반으로 live_file 경로를 내부에서 생성합니다.
    모듈 속성이 아니므로 monkeypatch.setattr 불가 → pathlib.Path.read_text 와 exists를
    Path 인스턴스별로 패치하거나, 실제 경로에 임시 파일을 쓰는 방식을 사용합니다.
    여기서는 실제 .ai_monitor/data/ 경로에 임시 파일을 쓰고 테스트 후 복원합니다.
    """

    # 실제 live_file 경로 (.ai_monitor/data/agent_live.jsonl)
    _REAL_LIVE_FILE = _AI_MONITOR / "data" / "agent_live.jsonl"

    def _make_event(self, terminal_id: str, ev_type: str, task: str = "작업", cli: str = "claude",
                    seconds_ago: int = 30) -> dict:
        """테스트용 이벤트 딕셔너리 생성 헬퍼."""
        import datetime
        ts = datetime.datetime.fromtimestamp(time.time() - seconds_ago).isoformat()
        return {
            "type": ev_type,
            "terminal_id": terminal_id,
            "task": task,
            "cli": cli,
            "run_id": f"run-{terminal_id}-{ev_type}",
            "ts": ts,
        }

    @pytest.fixture(autouse=True)
    def backup_restore_live_file(self):
        """테스트 전후 agent_live.jsonl 백업/복원 픽스처."""
        old_content = None
        if self._REAL_LIVE_FILE.exists():
            old_content = self._REAL_LIVE_FILE.read_text(encoding="utf-8")
        yield
        # 복원
        if old_content is None:
            self._REAL_LIVE_FILE.unlink(missing_ok=True)
        else:
            self._REAL_LIVE_FILE.write_text(old_content, encoding="utf-8")

    def _write_events(self, events: list):
        """실제 경로에 테스트 이벤트 기록."""
        self._REAL_LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self._REAL_LIVE_FILE, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def test_started_후_done없으면_running으로_병합됨(self):
        """started 이벤트 이후 done이 없으면 해당 터미널을 running으로 표시해야 함."""
        self._write_events([
            self._make_event("T2", "started", task="코드 리뷰 중"),
        ])
        terminals = {f"T{i}": {"status": "idle", "task": "", "cli": "", "run_id": "", "ts": "", "last_line": ""} for i in range(1, 9)}

        agent_api._merge_live_file_status(terminals)

        assert terminals["T2"]["status"] == "running"
        assert terminals["T2"]["task"] == "코드 리뷰 중"

    def test_started_후_done있으면_running으로_전환안됨(self):
        """done 이벤트가 started보다 나중이면 running으로 전환되지 않아야 함."""
        import datetime
        t_started = datetime.datetime.fromtimestamp(time.time() - 60).isoformat()
        t_done = datetime.datetime.fromtimestamp(time.time() - 10).isoformat()

        self._write_events([
            {"type": "started", "terminal_id": "T3", "task": "완료된 작업",
             "cli": "claude", "run_id": "r1", "ts": t_started},
            {"type": "done", "terminal_id": "T3", "task": "",
             "cli": "claude", "run_id": "r1", "ts": t_done},
        ])
        terminals = {f"T{i}": {"status": "idle", "task": "", "cli": "", "run_id": "", "ts": "", "last_line": "", "pipeline_stage": ""} for i in range(1, 9)}

        agent_api._merge_live_file_status(terminals)

        assert terminals["T3"]["status"] != "running"

    def test_10분_초과_이벤트_무시됨(self):
        """10분(600초) 이전의 이벤트는 병합 대상에서 제외되어야 함."""
        import datetime
        old_ts = datetime.datetime.fromtimestamp(time.time() - 700).isoformat()  # 11분 전

        self._write_events([
            {"type": "started", "terminal_id": "T4", "task": "오래된 작업",
             "cli": "antigravity", "run_id": "r_old", "ts": old_ts},
        ])
        terminals = {f"T{i}": {"status": "idle", "task": "", "cli": "", "run_id": "", "ts": "", "last_line": ""} for i in range(1, 9)}

        agent_api._merge_live_file_status(terminals)

        assert terminals["T4"]["status"] == "idle"

    def test_파일없으면_조용히_무시됨(self):
        """agent_live.jsonl이 없어도 예외 없이 terminals가 그대로 유지되어야 함."""
        # 파일이 없는 상태 보장 (backup 픽스처가 테스트 후 복원함)
        if self._REAL_LIVE_FILE.exists():
            self._REAL_LIVE_FILE.unlink()

        terminals = {f"T{i}": {"status": "idle"} for i in range(1, 9)}
        agent_api._merge_live_file_status(terminals)  # 예외 발생 금지

        assert terminals["T1"]["status"] == "idle"


# ── interactive_stages cli 타입 추론 테스트 ────────────────────────────────────

class TestInteractiveStageCLIType:
    """handle_terminals에서 cli 타입이 올바르게 추론되는지 검증.

    [핵심 버그 재발 방지]
    커밋 6f05536: agent를 항상 'claude'로 하드코딩하던 버그 수정.
    hook이 보낸 'cli' 필드를 사용해야 함.
    """

    def setup_method(self):
        agent_api._interactive_stages.clear()
        agent_api._pty_sessions_getter = None

    def test_codex_stage_codex_cli_타입으로_표시됨(self, monkeypatch):
        """cli='codex'로 stage 업데이트 시 terminals에 cli='codex'로 표시되어야 함."""
        # Codex가 stage 업데이트 시 cli 정보를 포함하여 전송
        agent_api._interactive_stages["T3"] = {
            "pipeline_stage": "analyzing",
            "task": "Codex 작업 중",
            "cli": "codex",  # ← codex가 보낸 cli 타입
            "ts": time.time(),
        }

        # cli_agent.get_terminals()가 T1~T8 idle 반환하도록 모킹
        mock_terminals = {
            f"T{i}": {"status": "idle", "task": "", "cli": "", "run_id": "", "ts": "", "last_line": ""}
            for i in range(1, 9)
        }
        monkeypatch.setattr(
            sys.modules["cli_agent"], "get_terminals", lambda: dict(mock_terminals)
        )
        monkeypatch.setattr(agent_api, "_CLI_AGENT_AVAILABLE", True)

        # _merge_live_file_status와 _detect_external_antigravity는 빈 결과 반환
        monkeypatch.setattr(agent_api, "_merge_live_file_status", lambda t: None)
        monkeypatch.setattr(agent_api, "_detect_external_antigravity", lambda: [])
        # [테스트 격리] _merge_pty_heartbeats는 실제 agent_heartbeats(로컬 DB)를 읽어 cli를 덮으므로
        # 모킹하지 않으면 stale 하트비트(codex:T3→antigravity)에 의존해 결과가 비결정적이 됨.
        monkeypatch.setattr(agent_api, "_merge_pty_heartbeats", lambda t: None)

        handler = MagicMock()
        handler.wfile.write = MagicMock()
        agent_api.handle_terminals(handler)

        response_bytes = handler.wfile.write.call_args[0][0]
        result = json.loads(response_bytes.decode("utf-8"))

        # T3 슬롯에 codex cli 타입이 반영되어야 함 (과거 버그: 항상 'claude' 반환)
        assert result["T3"]["cli"] == "codex"
        assert result["T3"]["status"] == "running"

    def test_claude_stage_claude_cli_타입으로_표시됨(self, monkeypatch):
        """cli='claude'로 stage 업데이트 시 terminals에 cli='claude'로 표시되어야 함."""
        agent_api._interactive_stages["T1"] = {
            "pipeline_stage": "modifying",
            "task": "Claude 작업 중",
            "cli": "claude",
            "ts": time.time(),
        }

        mock_terminals = {
            f"T{i}": {"status": "idle", "task": "", "cli": "", "run_id": "", "ts": "", "last_line": ""}
            for i in range(1, 9)
        }
        monkeypatch.setattr(
            sys.modules["cli_agent"], "get_terminals", lambda: dict(mock_terminals)
        )
        monkeypatch.setattr(agent_api, "_CLI_AGENT_AVAILABLE", True)
        monkeypatch.setattr(agent_api, "_merge_live_file_status", lambda t: None)
        monkeypatch.setattr(agent_api, "_detect_external_antigravity", lambda: [])

        handler = MagicMock()
        agent_api.handle_terminals(handler)

        response_bytes = handler.wfile.write.call_args[0][0]
        result = json.loads(response_bytes.decode("utf-8"))

        assert result["T1"]["cli"] == "claude"
