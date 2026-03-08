# -*- coding: utf-8 -*-
"""
FILE: tests/test_agent_api.py
DESCRIPTION: agent_api.py 단위 테스트.
             최근 버그픽스(Codex 슬롯 오류, activeAgent 동기화) 재발 방지 및
             핵심 로직(_get_gemini_last_task, handle_stage_update, _merge_live_file_status)
             의 정확성을 검증합니다.

             [테스트 전략]
             - cli_agent 의존성은 모킹 (실제 CLI 실행 없이 API 레이어만 테스트)
             - 파일 I/O는 tmp_path로 격리
             - HTTP 핸들러는 간단한 Mock 객체로 대체

REVISION HISTORY:
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


# ── _get_gemini_last_task 테스트 ───────────────────────────────────────────────

class TestGetGeminiLastTask:
    """Gemini 세션 JSON에서 마지막 사용자 메시지 추출 로직 검증."""

    def _write_session(self, path: Path, messages: list) -> Path:
        """테스트용 Gemini 세션 JSON 파일 생성 헬퍼."""
        session_file = path / "session-test.json"
        session_file.write_text(
            json.dumps({"messages": messages}, ensure_ascii=False),
            encoding="utf-8"
        )
        return session_file

    def test_정상_사용자_메시지_반환됨(self, tmp_path):
        """type='user'인 마지막 메시지의 텍스트가 반환되어야 함."""
        sf = self._write_session(tmp_path, [
            {"type": "user", "content": [{"text": "버그 수정해줘"}]},
            {"type": "assistant", "content": [{"text": "알겠습니다"}]},
        ])
        result = agent_api._get_gemini_last_task(sf)
        assert result == "버그 수정해줘"

    def test_여러_메시지중_마지막_사용자_메시지_반환됨(self, tmp_path):
        """여러 메시지가 있을 때 가장 최근(마지막) 사용자 메시지가 반환되어야 함."""
        sf = self._write_session(tmp_path, [
            {"type": "user", "content": [{"text": "첫 번째 지시"}]},
            {"type": "assistant", "content": [{"text": "완료"}]},
            {"type": "user", "content": [{"text": "두 번째 지시"}]},
            {"type": "assistant", "content": [{"text": "완료"}]},
        ])
        result = agent_api._get_gemini_last_task(sf)
        assert result == "두 번째 지시"

    def test_80자_초과_텍스트_잘려서_반환됨(self, tmp_path):
        """80자를 넘는 텍스트는 80자로 잘려야 함."""
        long_text = "가" * 100  # 100자
        sf = self._write_session(tmp_path, [
            {"type": "user", "content": [{"text": long_text}]},
        ])
        result = agent_api._get_gemini_last_task(sf)
        assert len(result) == 80

    def test_줄바꿈이_공백으로_치환됨(self, tmp_path):
        """메시지 내 줄바꿈(\n)은 공백으로 치환되어야 함."""
        sf = self._write_session(tmp_path, [
            {"type": "user", "content": [{"text": "줄1\n줄2\n줄3"}]},
        ])
        result = agent_api._get_gemini_last_task(sf)
        assert "\n" not in result
        assert "줄1 줄2 줄3" == result

    def test_파일없으면_빈문자열_반환됨(self, tmp_path):
        """존재하지 않는 파일 경로 → 빈 문자열 반환 (예외 없음)."""
        fake_path = tmp_path / "nonexistent.json"
        result = agent_api._get_gemini_last_task(fake_path)
        assert result == ""

    def test_메시지없는_세션_빈문자열_반환됨(self, tmp_path):
        """messages 키가 비어있으면 빈 문자열 반환."""
        sf = self._write_session(tmp_path, [])
        result = agent_api._get_gemini_last_task(sf)
        assert result == ""

    def test_assistant메시지만_있으면_빈문자열_반환됨(self, tmp_path):
        """user 메시지 없이 assistant만 있으면 빈 문자열 반환."""
        sf = self._write_session(tmp_path, [
            {"type": "assistant", "content": [{"text": "도움이 필요하신가요?"}]},
        ])
        result = agent_api._get_gemini_last_task(sf)
        assert result == ""

    def test_content가_string_타입이어도_처리됨(self, tmp_path):
        """content가 list가 아닌 string 타입일 때도 처리되어야 함."""
        session_file = tmp_path / "session-str.json"
        session_file.write_text(
            json.dumps({"messages": [{"type": "user", "content": "문자열 컨텐츠"}]}),
            encoding="utf-8"
        )
        result = agent_api._get_gemini_last_task(session_file)
        assert result == "문자열 컨텐츠"

    def test_손상된_json_파일_빈문자열_반환됨(self, tmp_path):
        """JSON 파싱 불가 파일 → 빈 문자열 반환 (예외 없음)."""
        broken = tmp_path / "broken.json"
        broken.write_text("{broken json content", encoding="utf-8")
        result = agent_api._get_gemini_last_task(broken)
        assert result == ""


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
             "cli": "gemini", "run_id": "r_old", "ts": old_ts},
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

        # _merge_live_file_status와 _detect_external_gemini는 빈 결과 반환
        monkeypatch.setattr(agent_api, "_merge_live_file_status", lambda t: None)
        monkeypatch.setattr(agent_api, "_detect_external_gemini", lambda: [])

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
        monkeypatch.setattr(agent_api, "_detect_external_gemini", lambda: [])

        handler = MagicMock()
        agent_api.handle_terminals(handler)

        response_bytes = handler.wfile.write.call_args[0][0]
        result = json.loads(response_bytes.decode("utf-8"))

        assert result["T1"]["cli"] == "claude"
