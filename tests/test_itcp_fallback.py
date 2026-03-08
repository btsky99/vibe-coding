# -*- coding: utf-8 -*-
"""
FILE: tests/test_itcp_fallback.py
DESCRIPTION: ITCP 폴백 로직 단위 테스트.
             PostgreSQL 없이도 동작해야 하는 파일 기반 폴백(_fallback_file_send/receive)을
             순수 Python으로 검증합니다.

             [테스트 전략]
             - _ensure_pg_running()을 False로 모킹 → 폴백 경로 강제 진입
             - 임시 파일(tmp_path)을 사용하여 실제 data/ 디렉토리 오염 방지
             - 각 테스트는 독립적으로 실행 가능 (픽스처로 격리)

REVISION HISTORY:
- 2026-03-09 Claude: 최초 작성 — ITCP v1 신규 구현 후 폴백 로직 커버리지 확보
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 프로젝트 루트를 sys.path에 추가 (itcp 모듈 임포트용)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import itcp


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_pg_down(monkeypatch):
    """모든 테스트에서 PostgreSQL을 사용 불가로 모킹.

    [설계 의도]
    폴백 경로만 테스트하기 위해 _ensure_pg_running을 항상 False로 패치합니다.
    실제 PostgreSQL 서버나 psql.exe 없이도 CI 환경에서 실행 가능합니다.
    """
    monkeypatch.setattr(itcp, "_ensure_pg_running", lambda: False)


@pytest.fixture()
def fallback_file(tmp_path, monkeypatch):
    """임시 messages.jsonl 경로를 FALLBACK_FILE로 교체하는 픽스처.

    [설계 의도]
    실제 .ai_monitor/data/messages.jsonl 오염 방지.
    각 테스트마다 새 빈 파일 경로를 제공합니다.
    """
    fake_file = tmp_path / "messages.jsonl"
    monkeypatch.setattr(itcp, "_FALLBACK_FILE", fake_file)
    return fake_file


# ── _fallback_file_send 테스트 ────────────────────────────────────────────────

class TestFallbackFileSend:
    """_fallback_file_send: PostgreSQL 불가 시 JSONL 파일 저장 검증."""

    def test_send_pg없을때_폴백파일에_저장됨(self, fallback_file):
        """send() 호출 시 PG 불가 상태에서 messages.jsonl에 기록되는지 확인."""
        result = itcp.send("claude", "gemini", "서버 버그 발견", channel="debug")

        assert result is True
        assert fallback_file.exists()

        lines = fallback_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        msg = json.loads(lines[0])
        assert msg["from_agent"] == "claude"
        assert msg["to_agent"] == "gemini"
        assert msg["content"] == "서버 버그 발견"
        assert msg["channel"] == "debug"
        assert msg["is_read"] is False

    def test_send_연속_2개_메시지_순서_유지됨(self, fallback_file):
        """두 번 send() 시 파일에 순서대로 두 줄이 기록되는지 확인."""
        itcp.send("claude", "gemini", "첫 번째")
        itcp.send("gemini", "claude", "두 번째")

        lines = fallback_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["content"] == "첫 번째"
        assert second["content"] == "두 번째"

    def test_send_한글_특수문자_저장됨(self, fallback_file):
        """한글과 특수문자가 깨지지 않고 저장되는지 확인."""
        content = "버그 수정 완료 🎉 <script>alert('xss')</script>"
        itcp.send("claude", "all", content, channel="broadcast")

        msg = json.loads(fallback_file.read_text(encoding="utf-8").strip())
        assert msg["content"] == content

    def test_send_빈_컨텐츠도_저장됨(self, fallback_file):
        """빈 문자열도 유효한 메시지로 저장되는지 확인."""
        result = itcp.send("claude", "gemini", "")
        assert result is True

    def test_broadcast_to_agent가_all로_저장됨(self, fallback_file):
        """broadcast()는 to_agent='all'로 저장되어야 함."""
        itcp.broadcast("claude", "배포 완료 v3.7.5")

        msg = json.loads(fallback_file.read_text(encoding="utf-8").strip())
        assert msg["to_agent"] == "all"
        assert msg["channel"] == "broadcast"


# ── _fallback_file_receive 테스트 ─────────────────────────────────────────────

class TestFallbackFileReceive:
    """_fallback_file_receive: 미읽음 메시지 조회 및 읽음 처리 검증."""

    def _write_messages(self, fallback_file, messages: list[dict]):
        """테스트용 헬퍼: messages.jsonl에 메시지 목록 직접 기록."""
        with open(fallback_file, "w", encoding="utf-8") as f:
            for m in messages:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def test_receive_내게온_미읽음_반환됨(self, fallback_file):
        """to_agent='claude'이고 is_read=False인 메시지만 반환되는지 확인."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "gemini", "to_agent": "claude",
             "channel": "debug", "msg_type": "info", "content": "버그 발견", "is_read": False},
            {"id": "2", "from_agent": "gemini", "to_agent": "gemini",  # 다른 수신자
             "channel": "general", "msg_type": "info", "content": "내꺼", "is_read": False},
        ])

        msgs = itcp.receive("claude")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "버그 발견"

    def test_receive_이미읽은_메시지_제외됨(self, fallback_file):
        """is_read=True인 메시지는 receive()에서 반환되지 않아야 함."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "gemini", "to_agent": "claude",
             "channel": "general", "msg_type": "info", "content": "읽은 메시지", "is_read": True},
            {"id": "2", "from_agent": "gemini", "to_agent": "claude",
             "channel": "general", "msg_type": "info", "content": "안읽은 메시지", "is_read": False},
        ])

        msgs = itcp.receive("claude")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "안읽은 메시지"

    def test_receive_broadcast_all_메시지_수신됨(self, fallback_file):
        """to_agent='all' (브로드캐스트)는 모든 터미널이 수신해야 함."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "claude", "to_agent": "all",
             "channel": "broadcast", "msg_type": "broadcast",
             "content": "전체 공지", "is_read": False},
        ])

        msgs = itcp.receive("gemini")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "전체 공지"

    def test_receive_mark_read_true이면_읽음처리됨(self, fallback_file):
        """mark_read=True(기본값) 시 반환된 메시지가 is_read=True로 업데이트되어야 함."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "gemini", "to_agent": "claude",
             "channel": "task", "msg_type": "request", "content": "작업 요청", "is_read": False},
        ])

        msgs = itcp.receive("claude", mark_read=True)
        assert len(msgs) == 1

        # 파일에서 다시 읽어 읽음 처리 확인
        saved = json.loads(fallback_file.read_text(encoding="utf-8").strip())
        assert saved["is_read"] is True

    def test_receive_mark_read_false이면_읽음처리_안됨(self, fallback_file):
        """mark_read=False 시 메시지를 읽어도 is_read 상태가 변하지 않아야 함."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "gemini", "to_agent": "claude",
             "channel": "general", "msg_type": "info", "content": "엿보기", "is_read": False},
        ])

        msgs = itcp.receive("claude", mark_read=False)
        assert len(msgs) == 1

        # 파일 상태 불변 확인
        saved = json.loads(fallback_file.read_text(encoding="utf-8").strip())
        assert saved["is_read"] is False

    def test_receive_두번째_호출시_이미읽음_반환안됨(self, fallback_file):
        """같은 메시지를 두 번 receive()하면 두 번째에는 빈 목록 반환."""
        self._write_messages(fallback_file, [
            {"id": "1", "from_agent": "gemini", "to_agent": "claude",
             "channel": "general", "msg_type": "info", "content": "한번만", "is_read": False},
        ])

        first = itcp.receive("claude", mark_read=True)
        second = itcp.receive("claude", mark_read=True)

        assert len(first) == 1
        assert len(second) == 0

    def test_receive_파일없으면_빈목록_반환됨(self, fallback_file):
        """messages.jsonl이 없으면 빈 목록을 반환해야 함 (예외 발생 금지)."""
        assert not fallback_file.exists()
        msgs = itcp.receive("claude")
        assert msgs == []

    def test_receive_빈파일이면_빈목록_반환됨(self, fallback_file):
        """messages.jsonl이 비어 있으면 빈 목록 반환 (예외 발생 금지)."""
        fallback_file.write_text("", encoding="utf-8")
        msgs = itcp.receive("claude")
        assert msgs == []

    def test_receive_손상된_줄_있어도_나머지_정상처리됨(self, fallback_file):
        """JSON 파싱 실패 줄이 섞여 있어도 정상 메시지는 처리되어야 함."""
        fallback_file.write_text(
            '{"broken": json line}\n'
            '{"id":"2","from_agent":"gemini","to_agent":"claude","channel":"general","msg_type":"info","content":"정상 메시지","is_read":false}\n',
            encoding="utf-8"
        )
        msgs = itcp.receive("claude")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "정상 메시지"
