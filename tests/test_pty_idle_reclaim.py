"""
FILE: tests/test_pty_idle_reclaim.py
DESCRIPTION: 유휴 claude 세션 회수(방법 A) 계약 검증 — pty-server.js 소스 정적 검사.
             node 런타임/PTY 없이 회귀를 막기 위해 소스 불변식을 문자열로 고정한다.

REVISION HISTORY:
- 2026-08-01 Claude: 신규 — 대기 중 claude 세션이 슬롯당 ~430MB를 점유하던 문제(실측 4개 중
                     3개가 유휴로 1.3GB)를 회수하는 기능. 잘못 죽이면 작업이 날아가므로
                     "기본 OFF"와 "입력·출력 둘 다 정지" 두 불변식을 테스트로 못 박는다.
"""

import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PTY = _PROJECT_ROOT / ".ai_monitor" / "pty-server" / "pty-server.js"


@pytest.fixture(scope="module")
def src() -> str:
    return _PTY.read_text(encoding="utf-8", errors="replace")


def test_reclaim_is_disabled_by_default(src):
    """[불변식] 기본 OFF — 진행 중 작업을 죽일 위험이 있어 명시적 opt-in이어야 한다."""
    m = re.search(r"PTY_RECLAIM_IDLE_MS\s*=\s*parseInt\(\s*process\.env\.PTY_RECLAIM_IDLE_MS\s*\|\|\s*'(\d+)'", src)
    assert m, "PTY_RECLAIM_IDLE_MS 기본값 선언을 찾을 수 없음"
    assert m.group(1) == '0', "기본값이 0(비활성)이 아니면 사용자 동의 없이 세션을 죽인다"


def test_reclaim_requires_both_input_and_output_idle(src):
    """[핵심 안전장치] 출력만 봐도, 입력만 봐도 안 된다.

    claude가 긴 답변을 생성 중이면 입력은 없지만 출력이 흐른다. 한쪽만 보면 작업 중인
    세션을 죽여 결과가 날아간다.
    """
    body = src[src.index('function isSessionIdleForReclaim'):]
    body = body[:body.index('function isSessionIdleForCleanup')]
    assert 'lastInputAt' in body and 'lastOutputAt' in body
    # 두 조건 모두 "최근이면 회수 안 함"으로 early-return 되어야 한다
    assert body.count('return false') >= 6, "안전 가드가 줄었다 — 조건별 early-return 확인 필요"
    assert re.search(r"now - lastIn\)\s*<=\s*PTY_RECLAIM_IDLE_MS[\s\S]*?return false", body)
    assert re.search(r"now - lastOut\)\s*<=\s*PTY_RECLAIM_IDLE_MS[\s\S]*?return false", body)


def test_reclaim_only_targets_attached_claude(src):
    """detach 건은 기존 TTL 경로 담당, 오피스 세션은 제외 — 책임 경계를 지킨다."""
    body = src[src.index('function isSessionIdleForReclaim'):]
    body = body[:body.index('function isSessionIdleForCleanup')]
    assert "agent !== 'claude'" in body, "claude 외 에이전트를 죽이면 안 됨"
    assert 'session.attached' in body, "detach 세션은 기존 TTL 경로가 처리해야 함"
    assert "startsWith('O')" in body, "오피스 세션 제외 가드 누락"


def test_session_id_captured_before_kill(src):
    """[순서 불변식] 죽인 뒤에는 어느 jsonl이 그 세션 것인지 판별할 근거가 사라진다."""
    block = src[src.index('isSessionIdleForReclaim(info, now)'):]
    block = block[:block.index("killSessionPty(key, 'idle_reclaim')")]
    assert 'findClaudeSessionId' in block, "kill 전에 세션 ID를 확보해야 함"


def test_resume_is_consumed_once(src):
    """복원 ID를 지우지 않으면 무관한 세션이 남의 대화를 이어받는다."""
    assert 'pendingResume.delete(sessionId)' in src
    assert '--resume ${resumeId}' in src or '--resume ' in src


def test_claimed_set_includes_pending(src):
    """회수됐지만 아직 재연결 안 된 배정분을 빼면 같은 UUID가 두 슬롯에 배정된다."""
    assert 'new Set(pendingResume.values())' in src


def test_slug_rule_matches_observed_layout(src):
    """~/.claude/projects 슬러그 규칙 — 실측(D:\\vibe-coding → D--vibe-coding)과 일치해야 한다."""
    assert re.search(r"replace\(/\[:\\\\\\\\/\]/g,\s*'-'\)", src) or "replace(/[:\\\\/]/g, '-')" in src, \
        "cwd → 슬러그 치환 규칙이 바뀌면 복원 ID를 영영 못 찾는다"


def test_reclaim_notifies_user(src):
    """조용히 죽으면 사용자는 세션이 왜 사라졌는지 알 수 없다."""
    block = src[src.index('isSessionIdleForReclaim(info, now)'):]
    block = block[:block.index("killSessionPty(key, 'idle_reclaim')")]
    assert 'HIVE' in block and '유휴' in block, "회수 사실을 터미널에 통지해야 함"
