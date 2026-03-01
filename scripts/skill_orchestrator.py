# -*- coding: utf-8 -*-
"""
FILE: scripts/skill_orchestrator.py
DESCRIPTION: AI 오케스트레이터 스킬 체인 실행 상태 추적기.
             vibe-orchestrate.md 스킬이 실행 중인 스킬 체인의 상태를
             skill_chain.json에 영속화하여 대시보드에 실시간 표시합니다.

             [CLI 사용법]
             python skill_orchestrator.py plan "요청내용" skill1 skill2 ...
               → 새 체인 계획 생성 (기존 계획 덮어쓰기)

             python skill_orchestrator.py update <step번호> <status> [summary]
               → 특정 단계 상태 갱신
               status: running | done | failed | skipped

             python skill_orchestrator.py status
               → 현재 실행 상태 JSON 출력

             python skill_orchestrator.py done
               → 전체 체인 완료 처리

             python skill_orchestrator.py reset
               → 상태 초기화 (idle로 전환)

REVISION HISTORY:
- 2026-03-01 Claude: 스킬 결과 영구 저장 추가
  - cmd_done(): 완료 시 skill_results.jsonl에 session_id/request/results/completed_at append
- 2026-03-01 Claude: 최초 구현 — AI 오케스트레이터 B안 상태 추적기
  - skill_chain.json 읽기/쓰기로 실행 상태 영속화
  - frozen(배포)/개발 모드 자동 경로 구분
  - server.py /api/orchestrator/skill-chain 엔드포인트와 연동
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path


# ── 데이터 디렉토리 경로 결정 (frozen/개발 모드 자동 구분) ────────────────────
def _get_data_dir() -> Path:
    """frozen(배포) 모드와 개발 모드를 자동 구분하여 데이터 디렉토리 반환."""
    if getattr(sys, 'frozen', False):
        # 배포 버전: APPDATA\VibeCoding 또는 실행파일 옆 data/
        appdata = os.getenv('APPDATA', '')
        _appdata_dir = Path(appdata) / "VibeCoding"
        if _appdata_dir.exists():
            return _appdata_dir
        return Path(sys.executable).parent / "data"
    else:
        # 개발 버전: scripts/ 기준 상위/.ai_monitor/data/
        return Path(__file__).parent.parent / ".ai_monitor" / "data"


DATA_DIR = _get_data_dir()
CHAIN_FILE = DATA_DIR / "skill_chain.json"


def _now() -> str:
    """현재 시각을 ISO 8601 형식 문자열로 반환."""
    return datetime.now().isoformat(timespec='seconds')


def _load() -> dict:
    """skill_chain.json 읽기. 없으면 idle 상태 반환."""
    if CHAIN_FILE.exists():
        try:
            with open(CHAIN_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    # 파일 없거나 파싱 실패 시 기본값
    return {"status": "idle"}


def _save(data: dict) -> None:
    """skill_chain.json 저장. DATA_DIR 없으면 자동 생성."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    with open(CHAIN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _save_result_history(data: dict) -> None:
    """완료된 스킬 체인 결과를 skill_results.jsonl에 영구 누적 저장합니다.

    [저장 항목]
    - session_id: 세션 식별자
    - request: 사용자 원본 요청
    - results: 각 스킬 이름 + 상태 + 요약
    - completed_at: 완료 시각

    [파일 형식]
    JSON Lines (한 줄 = 한 세션 결과) — 쉽게 tail/grep 가능
    """
    results_file = DATA_DIR / "skill_results.jsonl"
    record = {
        "session_id": data.get("session_id", ""),
        "request": data.get("request", ""),
        "results": [
            {"skill": r.get("skill"), "status": r.get("status"), "summary": r.get("summary", "")}
            for r in data.get("results", [])
        ],
        "completed_at": data.get("completed_at", _now()),
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(results_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] 결과 저장 실패: {e}")


def cmd_plan(request: str, skills: list[str]) -> None:
    """새 스킬 체인 계획을 생성하고 저장합니다.

    [동작]
    - 기존 체인이 있어도 덮어씁니다 (새 요청 우선)
    - 각 스킬을 pending 상태로 초기화
    - status = "running"으로 시작

    Args:
        request: 사용자 원본 요청 문자열
        skills:  실행할 스킬 이름 목록 (예: ["vibe-debug", "vibe-tdd"])
    """
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "session_id": session_id,
        "request": request,
        "plan": skills,
        "current_step": 0,
        "results": [
            # 각 스킬을 pending 상태로 초기화
            {"skill": s, "status": "pending", "summary": ""}
            for s in skills
        ],
        "status": "running",
        "started_at": _now(),
        "updated_at": _now(),
    }
    _save(data)
    print(f"[OK] 스킬 체인 계획 저장: {' → '.join(skills)}")
    print(f"     세션 ID: {session_id}")


def cmd_update(step: int, status: str, summary: str = "") -> None:
    """특정 단계의 실행 상태를 갱신합니다.

    [동작]
    - step번째 results 항목의 status와 summary를 업데이트
    - status가 "running"이면 current_step을 해당 step으로 설정

    Args:
        step:    0-based 단계 인덱스
        status:  "running" | "done" | "failed" | "skipped"
        summary: 완료 결과 한 줄 요약 (선택)
    """
    data = _load()
    if data.get("status") == "idle":
        print("[WARN] 활성 체인 없음 — plan 먼저 실행하세요")
        sys.exit(1)

    results = data.get("results", [])
    if step < 0 or step >= len(results):
        print(f"[ERROR] 유효하지 않은 step: {step} (총 {len(results)}단계)")
        sys.exit(1)

    # 상태 및 요약 갱신
    results[step]["status"] = status
    if summary:
        results[step]["summary"] = summary

    # 현재 실행 단계 추적
    if status == "running":
        data["current_step"] = step
    elif status in ("done", "skipped"):
        # 다음 pending 단계로 current_step 이동
        for i, r in enumerate(results):
            if i > step and r["status"] == "pending":
                data["current_step"] = i
                break

    data["results"] = results
    _save(data)

    skill_name = results[step]["skill"]
    icon = {"running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "❓")
    print(f"[OK] {icon} {skill_name}: {status}" + (f" — {summary}" if summary else ""))


def cmd_status() -> None:
    """현재 스킬 체인 실행 상태를 JSON으로 출력합니다."""
    data = _load()
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_done() -> None:
    """전체 스킬 체인을 완료 처리합니다.

    [동작]
    - 아직 pending인 결과를 skipped로 처리 (실행 안 된 것)
    - status = "done"으로 설정
    """
    data = _load()
    if data.get("status") == "idle":
        print("[WARN] 활성 체인 없음")
        return

    results = data.get("results", [])
    for r in results:
        if r["status"] == "pending":
            r["status"] = "skipped"

    data["results"] = results
    data["status"] = "done"
    data["completed_at"] = datetime.now().isoformat()
    _save(data)

    # 완료 결과를 skill_results.jsonl에 영구 저장 (세션 기록 누적)
    _save_result_history(data)

    # 완료 요약 출력
    print("[OK] ✅ 오케스트레이터 체인 완료")
    for r in results:
        icon = {"done": "✅", "failed": "❌", "skipped": "⏭️", "running": "🔄"}.get(r["status"], "❓")
        summary = f" — {r['summary']}" if r.get("summary") else ""
        print(f"     {icon} {r['skill']}{summary}")


def cmd_reset() -> None:
    """스킬 체인 상태를 초기화합니다 (idle로 전환)."""
    _save({"status": "idle"})
    print("[OK] 스킬 체인 상태 초기화 완료 (idle)")


def main():
    """CLI 진입점 — 서브커맨드를 파싱하여 해당 함수 호출."""
    args = sys.argv[1:]
    if not args:
        print("사용법:")
        print("  python skill_orchestrator.py plan <요청> <skill1> [skill2 ...]")
        print("  python skill_orchestrator.py update <step> <status> [summary]")
        print("  python skill_orchestrator.py status")
        print("  python skill_orchestrator.py done")
        print("  python skill_orchestrator.py reset")
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "plan":
        if len(args) < 3:
            print("[ERROR] 사용법: plan <요청> <skill1> [skill2 ...]")
            sys.exit(1)
        request = args[1]
        skills = args[2:]
        cmd_plan(request, skills)

    elif cmd == "update":
        if len(args) < 3:
            print("[ERROR] 사용법: update <step번호> <status> [summary]")
            sys.exit(1)
        step = int(args[1])
        status = args[2]
        summary = args[3] if len(args) > 3 else ""
        cmd_update(step, status, summary)

    elif cmd == "status":
        cmd_status()

    elif cmd == "done":
        cmd_done()

    elif cmd == "reset":
        cmd_reset()

    else:
        print(f"[ERROR] 알 수 없는 커맨드: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
