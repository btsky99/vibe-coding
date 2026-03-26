# -*- coding: utf-8 -*-
"""
FILE: scripts/auto_dispatcher.py
DESCRIPTION: 자율 멀티-LLM 태스크 디스패처 — 에이전트 역량 기반 자동 작업 분배 + 크로스 검증 시스템.

    [핵심 설계 원칙]
    - 에이전트별 역량 프로필(capability profile)을 기반으로 최적 에이전트에 작업 할당
    - 크로스 검증(cross-validation): 한 에이전트가 작성하면 다른 에이전트가 검증
    - Fan-Out/Fan-In 패턴: 독립 작업은 병렬 분배, 의존 작업은 순차 파이프라인
    - PostgreSQL pg_messages(ITCP) + hive_tasks로 비동기 통신 및 상태 추적

    [아키텍처 참고 — 2026 최신 트렌드]
    - LangGraph의 Reducer 패턴: 중앙 상태 저장소(PG)에서 동시 업데이트 병합
    - CrewAI의 Role-Playing 패턴: 에이전트별 역할/전문성 명시
    - Google A2A 프로토콜: 에이전트 간 표준화된 메시지 교환
    - UC Berkeley A3 패턴: 적대적 검증 루프 (Red Team/Blue Team)
    - Microsoft BlueCodeAgent: 크로스 에이전트 코드 검증

    [에이전트 역량 프로필]
    | Agent  | 강점                              | 약점                    |
    |--------|-----------------------------------|-------------------------|
    | Claude | 정밀 로직, 코드 리뷰, 보안 검증    | 웹 검색 불가             |
    | Gemini | 웹 검색, 광범위 분석, 아키텍처 설계  | 세밀한 코드 수정 부정확   |
    | Codex  | 빠른 코드 생성, 샌드박스 실행       | 컨텍스트 제한적           |

    [작업 흐름]
    1. dispatch(task) → 역량 매칭 → 최적 에이전트 선택 → ITCP 메시지 전송
    2. 에이전트가 작업 완료 → 결과를 pg_messages로 반환
    3. verify(task_id) → 다른 에이전트에게 검증 요청 → 크로스 검증 결과 기록
    4. report() → 전체 진행 상황 보고

    [사용법]
    python scripts/auto_dispatcher.py dispatch "서버 성능 최적화" --type perf
    python scripts/auto_dispatcher.py dispatch "프론트엔드 UI 개선" --type frontend --to gemini
    python scripts/auto_dispatcher.py status
    python scripts/auto_dispatcher.py verify <task_id>
    python scripts/auto_dispatcher.py fan-out "보안 점검" "성능 테스트" "UI 리뷰"

REVISION HISTORY:
- 2026-03-17 Claude: 최초 구현 — 역량 기반 자동 분배 + 크로스 검증 시스템
  - 에이전트 역량 프로필 기반 자동 매칭 알고리즘 구현
  - Fan-Out/Fan-In 병렬 분배 패턴 지원
  - ITCP 통합으로 실시간 비동기 태스크 전달
  - 크로스 검증 루프: 작성자 ≠ 검증자 강제
- 2026-03-19 Claude: hive_tasks 테이블 기록 누락 버그 수정
  - dispatch() 호출 시 hive_tasks에 레코드를 INSERT하도록 _save_dispatch_to_hive_tasks() 추가
  - 대시보드 "최근 디스패치" 패널이 비어있던 근본 원인 해결
  - pg_store.save_task()를 통해 PostgreSQL에 직접 기록 (ITCP만으로는 대시보드 조회 불가)
"""

from __future__ import annotations

import json
import os
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_MONITOR_DIR = _PROJECT_ROOT / ".ai_monitor"
if getattr(sys, 'frozen', False):
    _DATA_DIR = Path(os.environ.get('APPDATA', Path.home())) / "VibeCoding"
else:
    _DATA_DIR = _PROJECT_ROOT / ".ai_monitor" / "data"
_CONFIG_FILE = _DATA_DIR / "config.json"
_LEGACY_CONFIG_FILE = _PROJECT_ROOT / ".ai_monitor" / "config.json"

if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(_MONITOR_DIR))

# ITCP 통신 모듈
import itcp

# ── 에이전트 역량 프로필 ──────────────────────────────────────────────────────
# 각 에이전트의 전문 분야와 가중치 (0.0 ~ 1.0)
# 가중치가 높을수록 해당 분야에 더 적합
AGENT_CAPABILITIES = {
    "claude": {
        "display_name": "Claude (T1)",
        "terminal": "T1",
        "strengths": {
            "code_review": 0.95,        # 코드 리뷰 최강
            "security": 0.95,           # 보안 분석 최강
            "precision_logic": 0.9,     # 정밀 로직 구현
            "debugging": 0.9,           # 디버깅
            "refactoring": 0.85,        # 리팩토링
            "testing": 0.85,            # 테스트 작성
            "frontend": 0.8,            # 프론트엔드
            "documentation": 0.8,       # 문서화
            "architecture": 0.7,        # 아키텍처 (Gemini가 더 강함)
            "research": 0.3,            # 웹 검색 불가
        },
        "max_concurrent": 2,            # 동시 처리 가능 태스크 수
        "avg_latency_ms": 3000,         # 평균 응답 시간
    },
    "gemini": {
        "display_name": "Gemini (T2)",
        "terminal": "T2",
        "strengths": {
            "research": 0.95,           # 웹 검색/조사 최강
            "architecture": 0.9,        # 아키텍처 설계 최강
            "documentation": 0.9,       # 문서 작성
            "code_review": 0.8,         # 코드 리뷰 (Claude보다 약간 낮음)
            "frontend": 0.75,           # 프론트엔드
            "debugging": 0.7,           # 디버깅
            "precision_logic": 0.65,    # 정밀 로직 (Claude보다 약함)
            "security": 0.7,            # 보안
            "refactoring": 0.7,         # 리팩토링
            "testing": 0.65,            # 테스트
        },
        "max_concurrent": 2,
        "avg_latency_ms": 2500,
    },
    "codex": {
        "display_name": "Codex (T3)",
        "terminal": "T3",
        "strengths": {
            "precision_logic": 0.9,     # 코드 생성 최강
            "testing": 0.9,             # 테스트 생성 최강
            "refactoring": 0.85,        # 리팩토링
            "debugging": 0.8,           # 디버깅
            "frontend": 0.7,            # 프론트엔드
            "code_review": 0.6,         # 코드 리뷰 (컨텍스트 제한)
            "architecture": 0.5,        # 아키텍처 (컨텍스트 제한)
            "security": 0.6,            # 보안
            "documentation": 0.5,       # 문서화
            "research": 0.2,            # 웹 검색 불가
        },
        "max_concurrent": 3,            # 샌드박스 병렬 실행 가능
        "avg_latency_ms": 2000,
    },
}

# ── 태스크 유형 → 필요 역량 매핑 ──────────────────────────────────────────────
# 각 태스크 유형이 요구하는 역량과 가중치
TASK_TYPE_REQUIREMENTS = {
    "bug_fix": {"debugging": 0.4, "precision_logic": 0.3, "testing": 0.2, "code_review": 0.1},
    "feature": {"precision_logic": 0.3, "architecture": 0.2, "frontend": 0.2, "testing": 0.2, "documentation": 0.1},
    "security": {"security": 0.5, "code_review": 0.3, "testing": 0.2},
    "perf": {"precision_logic": 0.3, "debugging": 0.2, "code_review": 0.2, "refactoring": 0.2, "testing": 0.1},
    "frontend": {"frontend": 0.4, "precision_logic": 0.2, "code_review": 0.2, "testing": 0.2},
    "refactor": {"refactoring": 0.3, "code_review": 0.3, "precision_logic": 0.2, "testing": 0.2},
    "test": {"testing": 0.4, "precision_logic": 0.3, "debugging": 0.2, "code_review": 0.1},
    "docs": {"documentation": 0.4, "architecture": 0.3, "research": 0.3},
    "research": {"research": 0.5, "architecture": 0.3, "documentation": 0.2},
    "review": {"code_review": 0.4, "security": 0.3, "precision_logic": 0.2, "testing": 0.1},
    "architecture": {"architecture": 0.4, "research": 0.2, "documentation": 0.2, "precision_logic": 0.2},
}
HIGH_CONTEXT_TASK_TYPES = {"architecture", "research", "docs", "review", "security"}

# ── 키워드 → 태스크 유형 자동 감지 ──────────────────────────────────────────────
_TYPE_KEYWORDS = {
    "bug_fix": ["버그", "에러", "오류", "수정", "fix", "bug", "error", "debug", "고쳐"],
    "feature": ["기능", "추가", "구현", "만들어", "feature", "implement", "create", "add"],
    "security": ["보안", "취약점", "OWASP", "security", "vulnerability", "injection"],
    "perf": ["성능", "최적화", "느림", "빠르게", "performance", "optimize", "slow", "fast"],
    "frontend": ["UI", "프론트", "화면", "디자인", "CSS", "React", "frontend", "컴포넌트"],
    "refactor": ["리팩", "정리", "클린", "refactor", "clean", "reorganize"],
    "test": ["테스트", "TDD", "test", "검증", "assert", "coverage"],
    "docs": ["문서", "README", "주석", "설명", "document", "comment"],
    "research": ["조사", "검색", "분석", "research", "search", "analyze", "트렌드"],
    "review": ["리뷰", "검토", "점검", "review", "audit", "inspect"],
    "architecture": ["아키텍처", "설계", "구조", "architecture", "design", "structure"],
}


def _load_runtime_config() -> dict:
    """Load per-PC runtime config with legacy fallback."""
    for candidate in (_CONFIG_FILE, _LEGACY_CONFIG_FILE):
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding='utf-8'))
        except Exception:
            continue
    return {}


def is_codex_enabled() -> bool:
    """Return whether Codex should be eligible for automatic dispatch on this PC."""
    config = _load_runtime_config()
    return bool(config.get("codex_enabled", True))


def _generate_task_id() -> str:
    """고유 태스크 ID 생성 (타임스탬프 + 해시)"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    h = hashlib.md5(f"{ts}{time.time()}".encode()).hexdigest()[:6]
    return f"TASK-{ts}-{h}"


def _save_dispatch_to_hive_tasks(task_payload: dict) -> None:
    """디스패치된 태스크를 hive_tasks 테이블에 기록합니다.

    [설계 의도]
    기존에는 ITCP(pg_messages)에만 기록하고 hive_tasks에는 기록하지 않았기 때문에
    대시보드 "최근 디스패치" 패널이 항상 비어있었습니다.
    pg_store.save_task()를 호출하여 hive_tasks 테이블에 직접 INSERT합니다.

    [데이터 매핑]
    auto_dispatcher의 task_payload 필드 → hive_tasks 컬럼:
      task_id       → id
      description   → title, description
      type          → tags (리스트 형태)
      assigned_to   → assigned_to
      priority      → priority
      status        → status (dispatched)
      dispatched_at → timestamp
      verifier      → extra.verifier (JSON 확장 필드)
      scores        → extra.scores (JSON 확장 필드)
      parent_task_id→ extra.parent_task_id (JSON 확장 필드)

    [에러 처리]
    pg_store 임포트 실패 또는 DB 연결 불가 시에도 dispatch() 자체는 실패하지 않습니다.
    (ITCP 전송은 이미 완료된 상태이므로, hive_tasks 기록은 "최선 노력" 정책)
    """
    try:
        sys.path.insert(0, str(_MONITOR_DIR))
        from src.pg_store import save_task, ensure_schema

        # DB 스키마가 준비되었는지 확인 (최초 1회)
        ensure_schema()

        now_iso = task_payload.get("dispatched_at", datetime.now().isoformat(timespec="seconds"))

        # PROJECT_ID 결정: 서버와 동일한 인코딩 규칙 적용
        # (드라이브 문자 + 경로를 '--'로 치환, 예: D--vibe-coding)
        proj_id = str(_PROJECT_ROOT).replace("\\", "/").replace(":", "").replace("/", "--").lstrip("-") or "default"

        task_record = {
            "id": task_payload["task_id"],
            "timestamp": now_iso,
            "updated_at": now_iso,
            "title": f"[DISPATCH] {task_payload.get('description', '')[:80]}",
            "description": task_payload.get("description", ""),
            "status": "dispatched",
            "assigned_to": task_payload.get("assigned_to", "all"),
            "priority": task_payload.get("priority", "medium"),
            "created_by": "dispatcher",
            "kanban_status": "claimed",  # 디스패치됨 = 에이전트가 claim한 상태
            "role": task_payload.get("type", ""),
            "claimed_by": task_payload.get("assigned_to", ""),
            "tags": ["dispatch", task_payload.get("type", "general")],
            # extra 필드에 디스패치 고유 메타데이터 저장
            "verifier": task_payload.get("verifier", ""),
            "scores": task_payload.get("scores", {}),
            "parent_task_id": task_payload.get("parent_task_id", ""),
            "dispatch_source": "auto_dispatcher",
        }
        save_task(task_record, project_id=proj_id)
        print(f"   💾 hive_tasks 기록 완료: {task_payload['task_id']}")
    except Exception as e:
        # hive_tasks 기록 실패해도 dispatch 자체는 성공으로 처리
        # (ITCP 전송은 이미 완료됨 — "최선 노력" 정책)
        print(f"   ⚠️ hive_tasks 기록 실패 (dispatch는 정상 수행됨): {e}")


def detect_task_type(description: str) -> str:
    """태스크 설명에서 유형을 자동 감지합니다.

    [동작] 키워드 매칭 점수가 가장 높은 유형 반환.
    동점 시 리스트 순서(우선순위) 적용.
    """
    scores = {}
    desc_lower = description.lower()
    for task_type, keywords in _TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in desc_lower)
        if score > 0:
            scores[task_type] = score

    if not scores:
        return "feature"  # 기본값

    return max(scores, key=scores.get)


def score_agent(agent_name: str, task_type: str) -> float:
    """에이전트의 태스크 유형별 적합도 점수를 계산합니다.

    [알고리즘]
    태스크 유형의 역량 요구사항 × 에이전트의 역량 점수를 가중합산.
    예: security 태스크 → security(0.5) × claude.security(0.95) + code_review(0.3) × claude.code_review(0.95) + ...
    """
    if agent_name not in AGENT_CAPABILITIES:
        return 0.0

    requirements = TASK_TYPE_REQUIREMENTS.get(task_type, TASK_TYPE_REQUIREMENTS["feature"])
    agent = AGENT_CAPABILITIES[agent_name]

    score = 0.0
    for capability, weight in requirements.items():
        agent_score = agent["strengths"].get(capability, 0.0)
        score += weight * agent_score

    return round(score, 4)


def select_best_agent(task_type: str, exclude: Optional[list[str]] = None) -> str:
    """태스크 유형에 가장 적합한 에이전트를 선택합니다.

    [동작]
    1. 모든 에이전트의 적합도 점수 계산
    2. exclude 목록의 에이전트 제외 (크로스 검증 시 작성자 제외용)
    3. 최고 점수 에이전트 반환

    [크로스 검증 원칙]
    작성자와 검증자는 반드시 다른 에이전트여야 합니다.
    exclude=["claude"]로 호출하면 claude를 제외하고 최적 검증자를 선택합니다.
    """
    exclude = list(exclude or [])
    if not is_codex_enabled() and "codex" not in exclude:
        exclude.append("codex")
    candidates = {
        name: score_agent(name, task_type)
        for name in AGENT_CAPABILITIES
        if name not in exclude
    }

    if not candidates:
        return "claude"  # fallback

    return max(candidates, key=candidates.get)


def should_avoid_codex(task_type: str) -> bool:
    """Return True for tasks that need stronger repo context than Codex usually gets."""
    return task_type in HIGH_CONTEXT_TASK_TYPES


def dispatch(
    description: str,
    task_type: Optional[str] = None,
    assigned_to: Optional[str] = None,
    priority: str = "medium",
    require_verification: bool = True,
    parent_task_id: Optional[str] = None,
) -> dict:
    """태스크를 분석하고 최적 에이전트에 ITCP로 전달합니다.

    [반환값]
    {
        "task_id": "TASK-20260317-abc123",
        "assigned_to": "gemini",
        "task_type": "research",
        "score": 0.85,
        "verifier": "claude",        # 크로스 검증 담당
        "status": "dispatched",
        "scores": {"claude": 0.7, "gemini": 0.85, "codex": 0.5}
    }
    """
    # 1. 태스크 유형 자동 감지
    if not task_type:
        task_type = detect_task_type(description)

    # 2. 에이전트 점수 계산
    all_scores = {name: score_agent(name, task_type) for name in AGENT_CAPABILITIES}

    # 3. 에이전트 지정 또는 자동 선택
    if assigned_to and assigned_to in AGENT_CAPABILITIES:
        agent = assigned_to
    else:
        exclude_agents = ["codex"] if should_avoid_codex(task_type) else []
        agent = select_best_agent(task_type, exclude=exclude_agents)

    # 4. 크로스 검증 담당 선택 (작성자 제외)
    verifier = None
    if require_verification:
        verifier_exclude = [agent]
        if should_avoid_codex(task_type):
            verifier_exclude.append("codex")
        verifier = select_best_agent(task_type, exclude=verifier_exclude)

    # 5. 태스크 ID 생성
    task_id = _generate_task_id()

    # 6. ITCP 메시지로 에이전트에 태스크 전달
    task_payload = {
        "task_id": task_id,
        "type": task_type,
        "description": description,
        "priority": priority,
        "assigned_to": agent,
        "verifier": verifier,
        "parent_task_id": parent_task_id,
        "dispatched_at": datetime.now().isoformat(timespec="seconds"),
        "scores": all_scores,
    }

    # ── [P6 MUX 우선] 에이전트가 MUX에 등록되어 있으면 Named Pipe로 직접 주입 ──
    # [설계 의도] 기존 ITCP는 "다음 호출 시 수신"이라는 딜레이가 있지만,
    # MUX send_text는 Named Pipe를 통해 즉시 전달됩니다.
    # MUX 서버가 미실행이거나 대상 터미널이 미등록이면 기존 ITCP 폴백.
    mux_sent = False
    try:
        from vibe_mux import send_text as mux_send_text, is_server_running as mux_running
        if mux_running():
            # 에이전트 이름 → 터미널 ID 매핑 (역량 프로필에서 조회)
            target_terminal = AGENT_CAPABILITIES.get(agent, {}).get("terminal", "")
            if target_terminal:
                mux_result = mux_send_text(
                    target_terminal,
                    description,
                    from_agent='dispatcher',
                    metadata=task_payload,
                )
                if mux_result.get("ok"):
                    mux_sent = True
                    print(f"   📡 MUX 직접 주입 성공 → {target_terminal} ({agent})")
    except Exception as mux_err:
        pass  # MUX 실패 시 ITCP 폴백

    # ITCP 메시지 전송 — task 채널로 에이전트에게 작업 지시
    # MUX로 이미 전송한 경우에도 ITCP는 기록용으로 전송 (히스토리 추적)
    message_content = (
        f"[AUTO-DISPATCH] 새 작업이 할당되었습니다.\n"
        f"🆔 Task: {task_id}\n"
        f"📋 유형: {task_type} (적합도: {all_scores[agent]:.2f})\n"
        f"📝 내용: {description}\n"
        f"⚡ 우선순위: {priority}\n"
    )
    if mux_sent:
        message_content += f"📡 전달: MUX Named Pipe 직접 주입 완료\n"
    if verifier:
        message_content += f"🔍 검증: 완료 후 {verifier}가 크로스 검증 예정\n"
    if parent_task_id:
        message_content += f"🔗 상위 태스크: {parent_task_id}\n"

    itcp.send(
        from_terminal="dispatcher",
        to_terminal=agent,
        content=message_content,
        channel="task",
        msg_type="request",
        metadata=task_payload,
    )

    # 전체 브로드캐스트 (다른 에이전트도 진행 상황 인지)
    # [2026-03-27 Claude] 할당 대상 에이전트는 이미 직접 send로 수신했으므로
    # broadcast에서 제외하여 중복 수신 → 무한루프 방지
    _other_agents = [a for a in AGENT_CAPABILITIES if a != agent]
    for _other in _other_agents:
        itcp.send(
            from_terminal="dispatcher",
            to_terminal=_other,
            content=f"[DISPATCH] {task_id} → {agent} ({task_type}, 우선순위:{priority})",
            channel="hive",
            msg_type="info",
        )

    # ── [2026-03-19 수정] hive_tasks 테이블에 디스패치 레코드 저장 ──
    # [근본 원인] 기존에는 ITCP(pg_messages)에만 기록하고 hive_tasks에는 미기록.
    # 대시보드의 "최근 디스패치" 패널은 hive_tasks를 조회하므로 항상 빈 화면이었음.
    _save_dispatch_to_hive_tasks(task_payload)

    result = {
        "task_id": task_id,
        "assigned_to": agent,
        "task_type": task_type,
        "score": all_scores[agent],
        "verifier": verifier,
        "status": "dispatched",
        "scores": all_scores,
    }

    print(f"✅ 태스크 디스패치 완료")
    print(f"   ID: {task_id}")
    print(f"   유형: {task_type}")
    print(f"   할당: {agent} (점수: {all_scores[agent]:.2f})")
    print(f"   점수: claude={all_scores['claude']:.2f}, gemini={all_scores['gemini']:.2f}, codex={all_scores['codex']:.2f}")
    if verifier:
        print(f"   검증: {verifier}")

    return result


def fan_out(*descriptions: str, task_type: Optional[str] = None) -> list[dict]:
    """여러 독립 태스크를 병렬로 에이전트에 분배합니다 (Fan-Out 패턴).

    [사용법]
    fan_out("보안 점검", "성능 테스트", "UI 리뷰")
    → 각각 최적 에이전트에 동시 분배

    [설계 원칙]
    - 동일 에이전트에 과도한 할당 방지 (라운드로빈 밸런싱)
    - 각 태스크의 검증자는 실행자와 반드시 다른 에이전트
    """
    results = []
    agent_load = {name: 0 for name in AGENT_CAPABILITIES}  # 현재 부하 추적

    for desc in descriptions:
        t_type = task_type or detect_task_type(desc)

        # 부하 고려한 에이전트 선택: 점수에 부하 패널티 적용
        adjusted_scores = {}
        for name in AGENT_CAPABILITIES:
            if name == "codex" and not is_codex_enabled():
                continue
            base_score = score_agent(name, t_type)
            # 이미 할당된 태스크가 많으면 패널티 (max_concurrent 대비)
            load_ratio = agent_load[name] / AGENT_CAPABILITIES[name]["max_concurrent"]
            penalty = min(load_ratio * 0.3, 0.5)  # 최대 50% 패널티
            adjusted_scores[name] = max(base_score - penalty, 0.0)

        best_agent = max(adjusted_scores, key=adjusted_scores.get)
        agent_load[best_agent] += 1

        result = dispatch(desc, task_type=t_type, assigned_to=best_agent)
        results.append(result)

    print(f"\n📊 Fan-Out 결과: {len(results)}개 태스크 분배 완료")
    for r in results:
        print(f"   {r['task_id']} → {r['assigned_to']} ({r['task_type']})")

    return results


def request_verification(task_id: str, result_summary: str, author: str) -> dict:
    """완료된 태스크의 크로스 검증을 요청합니다.

    [크로스 검증 원칙]
    - 작성자 ≠ 검증자 (자기 검증 금지)
    - 검증자는 코드 리뷰 역량이 높은 에이전트 우선
    - 검증 결과: approved / rejected / needs_revision

    [동작]
    1. 작성자를 제외한 에이전트 중 review 역량 최고를 검증자로 선택
    2. ITCP review 채널로 검증 요청 전송
    3. 검증 메타데이터 반환
    """
    if str(task_id).startswith("AUTO-"):
        return {"task_id": task_id, "verifier": "", "author": author, "status": "ignored"}

    verifier = select_best_agent("review", exclude=[author])

    verify_msg = (
        f"[CROSS-VERIFY] 크로스 검증 요청\n"
        f"🆔 Task: {task_id}\n"
        f"✍️ 작성자: {author}\n"
        f"📋 결과 요약:\n{result_summary}\n\n"
        f"다음 관점에서 검증해 주세요:\n"
        f"1. 코드 정확성 — 로직 오류, 엣지 케이스 누락\n"
        f"2. 보안 — SQL 인젝션, XSS, 경로 순회 등 OWASP Top 10\n"
        f"3. 성능 — 불필요한 반복, 메모리 누수, N+1 쿼리\n"
        f"4. 호환성 — 기존 코드와의 충돌, API 변경 영향\n\n"
        f"검증 완료 후 결과를 [VERIFY-RESULT] 형식으로 반환해 주세요."
    )

    itcp.send(
        from_terminal="dispatcher",
        to_terminal=verifier,
        content=verify_msg,
        channel="review",
        msg_type="request",
        metadata={
            "task_id": task_id,
            "author": author,
            "type": "cross_verification",
        },
    )

    print(f"🔍 크로스 검증 요청 전송: {task_id} → {verifier} (작성자: {author})")
    return {"task_id": task_id, "verifier": verifier, "author": author, "status": "verification_requested"}


def report_task_completion(
    task_id: str,
    author: str,
    result_summary: str,
    *,
    request_verify: bool = True,
) -> dict:
    """Report a task result and optionally trigger cross-verification."""
    message = (
        f"[TASK-RESULT] 작업 완료\n"
        f"🆔 Task: {task_id}\n"
        f"✍️ 작성자: {author}\n"
        f"📝 결과 요약:\n{result_summary}"
    )
    itcp.send(
        from_terminal=author,
        to_terminal="dispatcher",
        content=message,
        channel="task",
        msg_type="response",
        metadata={
            "task_id": task_id,
            "author": author,
            "type": "task_result",
        },
    )

    verification = None
    if request_verify:
        verification = request_verification(task_id=task_id, result_summary=result_summary, author=author)

    return {
        "task_id": task_id,
        "author": author,
        "status": "completed",
        "verification": verification,
    }


def report_verification_result(
    task_id: str,
    reviewer: str,
    summary: str,
    *,
    verdict: str = "approved",
    author: str = "",
) -> dict:
    """Report a verification result back to dispatcher and the original author."""
    message = (
        f"[VERIFY-RESULT] 검증 완료\n"
        f"🆔 Task: {task_id}\n"
        f"🧪 Reviewer: {reviewer}\n"
        f"✅ Verdict: {verdict}\n"
        f"📝 Summary:\n{summary}"
    )
    metadata = {
        "task_id": task_id,
        "reviewer": reviewer,
        "author": author,
        "verdict": verdict,
        "type": "verify_result",
    }
    itcp.send(
        from_terminal=reviewer,
        to_terminal="dispatcher",
        content=message,
        channel="review",
        msg_type="response",
        metadata=metadata,
    )
    if author and author != reviewer:
        itcp.send(
            from_terminal=reviewer,
            to_terminal=author,
            content=message,
            channel="review",
            msg_type="response",
            metadata=metadata,
        )
    return {
        "task_id": task_id,
        "reviewer": reviewer,
        "verdict": verdict,
        "status": "verified",
    }


def status() -> dict:
    """현재 디스패치 현황을 조회합니다.

    [조회 내용]
    - pg_messages에서 task 채널의 최근 메시지 (미완료 포함)
    - 에이전트별 부하 상태
    - 미처리/진행중/완료 태스크 수
    """
    messages = itcp.history(limit=50, channel="task")
    review_msgs = itcp.history(limit=20, channel="review")

    # 통계 집계
    stats = {
        "dispatched": 0,
        "completed": 0,
        "verified": 0,
        "pending_verification": 0,
        "agent_load": {name: 0 for name in AGENT_CAPABILITIES},
    }

    for msg in messages:
        content = msg.get("content", "")
        to = msg.get("to_agent", "")
        if "[AUTO-DISPATCH]" in content:
            stats["dispatched"] += 1
            if to in stats["agent_load"]:
                stats["agent_load"][to] += 1
        if "[TASK-RESULT]" in content:
            stats["completed"] += 1
        if "[VERIFY-RESULT]" in content:
            stats["verified"] += 1

    for msg in review_msgs:
        if "[CROSS-VERIFY]" in msg.get("content", ""):
            stats["pending_verification"] += 1
        if "[VERIFY-RESULT]" in msg.get("content", "") and stats["pending_verification"] > 0:
            stats["pending_verification"] -= 1

    print(f"\n📊 디스패처 현황")
    print(f"   전체 디스패치: {stats['dispatched']}건")
    print(f"   검증 완료: {stats['verified']}건")
    print(f"   검증 대기: {stats['pending_verification']}건")
    print(f"   에이전트별 부하:")
    for name, load in stats["agent_load"].items():
        cap = AGENT_CAPABILITIES[name]
        print(f"     {cap['display_name']}: {load}/{cap['max_concurrent']}")

    return stats


def dispatch_multi_terminal_tasks(tasks_for_agents: dict[str, list[str]]) -> list[dict]:
    """각 터미널(T1/T2/T3)에 직접 작업 목록을 전달합니다.

    [사용법]
    dispatch_multi_terminal_tasks({
        "gemini": ["프론트엔드 UI 점검", "문서 업데이트"],
        "codex": ["테스트 코드 작성", "리팩토링"],
    })

    [설계 의도]
    사용자가 "T2는 이거, T3는 이거 해"라고 지시할 때 사용.
    각 에이전트의 다음 UserPromptSubmit 훅에서 ITCP 메시지를 자동 주입받아 실행.
    """
    all_results = []

    for agent, task_list in tasks_for_agents.items():
        for task_desc in task_list:
            result = dispatch(task_desc, assigned_to=agent)
            all_results.append(result)

    return all_results


# ── CLI 인터페이스 ────────────────────────────────────────────────────────────
def main():
    """커맨드라인 인터페이스.

    [사용법]
    python scripts/auto_dispatcher.py dispatch "태스크 설명" [--type TYPE] [--to AGENT] [--priority PRIO]
    python scripts/auto_dispatcher.py fan-out "태스크1" "태스크2" "태스크3"
    python scripts/auto_dispatcher.py verify TASK_ID "결과 요약" --author claude
    python scripts/auto_dispatcher.py status
    python scripts/auto_dispatcher.py score "태스크 설명"  # 에이전트별 점수만 확인
    """
    import argparse

    parser = argparse.ArgumentParser(description="자율 멀티-LLM 태스크 디스패처")
    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # dispatch 서브커맨드
    p_dispatch = subparsers.add_parser("dispatch", help="태스크를 최적 에이전트에 분배")
    p_dispatch.add_argument("description", help="태스크 설명")
    p_dispatch.add_argument("--type", dest="task_type", help="태스크 유형 (자동 감지)")
    p_dispatch.add_argument("--to", dest="assigned_to", help="강제 에이전트 지정")
    p_dispatch.add_argument("--priority", default="medium", help="우선순위 (low/medium/high/critical)")
    p_dispatch.add_argument("--no-verify", action="store_true", help="크로스 검증 생략")

    # fan-out 서브커맨드
    p_fanout = subparsers.add_parser("fan-out", help="여러 태스크를 병렬 분배")
    p_fanout.add_argument("descriptions", nargs="+", help="태스크 설명들")
    p_fanout.add_argument("--type", dest="task_type", help="태스크 유형 (전체 적용)")

    # verify 서브커맨드
    p_verify = subparsers.add_parser("verify", help="크로스 검증 요청")
    p_verify.add_argument("task_id", help="태스크 ID")
    p_verify.add_argument("summary", help="결과 요약")
    p_verify.add_argument("--author", required=True, help="작성 에이전트")

    # status 서브커맨드
    subparsers.add_parser("status", help="디스패치 현황 조회")

    # score 서브커맨드 (점수만 확인)
    p_score = subparsers.add_parser("score", help="에이전트별 적합도 점수 조회")
    p_score.add_argument("description", help="태스크 설명")
    p_score.add_argument("--type", dest="task_type", help="태스크 유형")

    args = parser.parse_args()

    if args.command == "dispatch":
        dispatch(
            args.description,
            task_type=args.task_type,
            assigned_to=args.assigned_to,
            priority=args.priority,
            require_verification=not args.no_verify,
        )
    elif args.command == "fan-out":
        fan_out(*args.descriptions, task_type=args.task_type)
    elif args.command == "verify":
        request_verification(args.task_id, args.summary, args.author)
    elif args.command == "status":
        status()
    elif args.command == "score":
        task_type = args.task_type or detect_task_type(args.description)
        print(f"\n📊 태스크 유형: {task_type}")
        print(f"   설명: {args.description}")
        print(f"\n   에이전트별 적합도:")
        for name in AGENT_CAPABILITIES:
            s = score_agent(name, task_type)
            cap = AGENT_CAPABILITIES[name]
            print(f"     {cap['display_name']}: {s:.4f}")
        best = select_best_agent(task_type)
        print(f"\n   🏆 최적 에이전트: {AGENT_CAPABILITIES[best]['display_name']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
