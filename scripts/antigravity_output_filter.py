# -*- coding: utf-8 -*-
"""
FILE: scripts/antigravity_output_filter.py
DESCRIPTION: Gemini CLI 내부 진단 로그를 사용자 출력에서 걸러내는 보조 필터.

REVISION HISTORY:
- 2026-03-22 Codex: 최초 작성
  - Gemini CLI가 stderr로 출력하는 MCP/훅/텔레메트리 노이즈를 사용자 출력에서 제외
  - 실제 응답 본문은 유지하고, 디버그/상태 로그만 필터링
"""

from __future__ import annotations


class GeminiCliNoiseFilter:
    """Gemini CLI가 섞어 출력하는 내부 상태 로그를 줄 단위로 제거합니다."""

    _PREFIXES = (
        "Created execution plan for ",
        "Expanding hook command: ",
        "Hook execution for ",
        "Registering notification handlers for server ",
        "Server '",
        "Scheduling MCP context refresh...",
        "Executing MCP context refresh...",
        "MCP context refresh complete.",
        "Loaded cached credentials.",
        "Loading extension: ",
        "Session ID: ",
        "Flushing log events to Clearcut.",
        "ClearcutLogger:",
        "Error flushing log events: HTTP 400: Bad Request",
        "[DEBUG] ",
    )
    _INLINE_MARKERS = _PREFIXES + (
        "MCP context refresh complete.",
        "Scheduling MCP context refresh...",
        "Executing MCP context refresh...",
    )

    def __init__(self) -> None:
        self._skip_block_depth = 0

    def filter_line(self, line: str) -> str | None:
        text = line.rstrip()
        stripped = text.strip()

        if not stripped:
            return ""

        if self._skip_block_depth > 0:
            self._skip_block_depth += stripped.count("{")
            self._skip_block_depth -= stripped.count("}")
            return None

        if stripped.startswith("Experiments loaded {"):
            self._skip_block_depth = stripped.count("{") - stripped.count("}")
            if self._skip_block_depth <= 0:
                self._skip_block_depth = 0
            return None

        if ".geminiignore" in stripped and "Ignore file not found:" in stripped:
            return None

        if any(stripped.startswith(prefix) for prefix in self._PREFIXES):
            return None

        for marker in self._INLINE_MARKERS:
            idx = text.find(marker)
            if idx > 0:
                text = text[:idx].rstrip()
                stripped = text.strip()
                break

        if not stripped:
            return None

        return text
