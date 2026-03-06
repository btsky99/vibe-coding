# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/safety_guard.py
# 📝 설명: Bounded Autonomy — 위험 명령 탐지 엔진.
#          에이전트가 실행하려는 명령을 사전에 검사하여 위험 동작을 차단합니다.
#          PreToolUse 훅에서 호출됩니다.
#
# 🕒 변경 이력 (History):
# [2026-03-06] Claude: 최초 생성 — MetaSwarm/ccswarm 패턴 참고
# ------------------------------------------------------------------------
import re

# ── 위험 명령 패턴 목록 ──────────────────────────────────────────────────────
# 각 항목: (regex_패턴, 사람이 읽을 수 있는 이유)
DANGER_PATTERNS: list[tuple[str, str]] = [
    # 파일시스템 파괴
    (r"rm\s+-[rf]+\s+/",        "루트 디렉토리 삭제 시도"),
    (r"rm\s+-[rf]+\s+\*",       "와일드카드 전체 삭제 시도"),
    (r"rm\s+-rf",               "강제 재귀 삭제 (rm -rf)"),
    (r"del\s+/[fsq]",           "Windows 강제 삭제 (del /f)"),
    (r"format\s+[a-zA-Z]:",     "디스크 포맷 시도"),
    # Git 파괴적 명령
    (r"git\s+push\s+.*--force", "Git 강제 푸시 (--force)"),
    (r"git\s+push\s+-f\b",      "Git 강제 푸시 (-f)"),
    (r"git\s+reset\s+--hard",   "Git 하드 리셋 (커밋 유실 위험)"),
    (r"git\s+clean\s+-[fd]",    "Git 미추적 파일 강제 삭제"),
    (r"git\s+branch\s+-[Dd]",   "Git 브랜치 삭제"),
    # 데이터베이스 파괴
    (r"DROP\s+TABLE",           "테이블 삭제 (DROP TABLE)"),
    (r"DROP\s+DATABASE",        "데이터베이스 삭제 (DROP DATABASE)"),
    (r"TRUNCATE\s+TABLE",       "테이블 전체 삭제 (TRUNCATE)"),
    # 시스템 위험
    (r"shutdown\s+/[sr]",       "Windows 시스템 종료/재시작"),
    (r":\(\)\{.*\};:",          "Fork 폭탄 패턴"),
]

# ── 경고 패턴 (차단하지 않고 경고만) ─────────────────────────────────────────
WARN_PATTERNS: list[tuple[str, str]] = [
    (r"git\s+push\s+origin\s+main", "main 브랜치 직접 푸시"),
    (r"pip\s+install\s+--upgrade",  "패키지 업그레이드 (호환성 주의)"),
    (r"npm\s+install\s+--legacy",   "레거시 의존성 설치"),
]


def check(command: str) -> tuple[bool, str]:
    """명령어의 안전성을 검사합니다.

    Args:
        command: 실행하려는 쉘 명령어 문자열

    Returns:
        (safe, reason):
            safe=True  → 안전, reason=""
            safe=False → 위험, reason=차단 이유 문자열
    """
    if not command or not command.strip():
        return True, ""

    cmd_lower = command.strip()
    for pattern, reason in DANGER_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            return False, reason

    return True, ""


def warn(command: str) -> str | None:
    """명령어에 대한 경고 메시지를 반환합니다 (차단하지 않음).

    Returns:
        경고 메시지 문자열 또는 None (경고 없음)
    """
    if not command or not command.strip():
        return None

    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, command.strip(), re.IGNORECASE):
            return reason

    return None


if __name__ == "__main__":
    # 간단 테스트
    test_cases = [
        ("rm -rf /tmp/test", False),
        ("git push --force origin main", False),
        ("git reset --hard HEAD~1", False),
        ("DROP TABLE users;", False),
        ("python scripts/memory.py list", True),
        ("git status", True),
        ("npm run build", True),
    ]
    print("=== safety_guard.py 테스트 ===")
    all_pass = True
    for cmd, expected_safe in test_cases:
        safe, reason = check(cmd)
        status = "PASS" if safe == expected_safe else "FAIL"
        if status == "FAIL":
            all_pass = False
        flag = "SAFE" if safe else f"BLOCKED: {reason}"
        print(f"  [{status}] '{cmd[:40]}' → {flag}")
    print(f"\n{'모든 테스트 통과' if all_pass else '일부 테스트 실패'}")
