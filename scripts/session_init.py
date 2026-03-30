# -*- coding: utf-8 -*-
"""
FILE: scripts/session_init.py
DESCRIPTION: 모든 에이전트(Claude, Gemini, Codex)의 세션 시작 프로토콜 실행 스크립트.
             HARNESS_V2 세션 시작 프로토콜의 5단계를 자동 수행하고 결과를 stdout에 출력한다.
             Claude는 hive_hook.py 훅이 자동 실행하므로, 이 스크립트는 주로 Gemini/Codex용.

             [사용법]
             python scripts/session_init.py                    # 전체 프로토콜 실행
             python scripts/session_init.py --agent gemini     # Gemini 전용 추가 프로토콜 포함
             python scripts/session_init.py --agent codex      # Codex 전용 추가 프로토콜 포함
             python scripts/session_init.py --json             # JSON 출력 (대시보드 연동)

             [5단계 세션 프로토콜 — HARNESS_V2.md 참조]
             Step 1: 작업 디렉토리 확인
             Step 2: 하이브 컨텍스트 로드 (memory.py, ITCP 미읽음)
             Step 3: 진행 상황 파악 (feature_list.json, git log)
             Step 4: 환경 검증 (harness_verify.py)
             Step 5: 다음 작업 선택 (feature_list에서 passes=false 첫 항목)

REVISION HISTORY:
- 2026-03-30 Claude: 최초 생성 — HARNESS_V2 세션 프로토콜 구현
  - Gemini/Codex 에이전트도 세션 시작 시 동일한 프로토콜을 수행할 수 있도록
  - 5단계 자동 실행 + 결과를 구조화된 형태로 출력
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# Windows UTF-8 보정
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _run(cmd: list[str], timeout: int = 10) -> str:
    """서브프로세스를 실행하고 stdout을 반환한다. 실패 시 에러 메시지 반환."""
    try:
        no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout, cwd=str(ROOT),
            creationflags=no_win,
        )
        return r.stdout.strip() if r.returncode == 0 else f"[오류] {r.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired:
        return "[오류] 타임아웃"
    except Exception as e:
        return f"[오류] {e}"


def step1_cwd() -> dict:
    """Step 1: 작업 디렉토리 확인"""
    return {
        "step": 1,
        "name": "작업 디렉토리",
        "result": str(ROOT),
        "ok": ROOT.exists(),
    }


def step2_hive_context(agent: str) -> dict:
    """Step 2: 하이브 컨텍스트 로드"""
    # 하이브 메모리에서 최근 항목 조회
    memory_out = _run([sys.executable, str(SCRIPTS / "memory.py"), "list"])
    memory_lines = [l for l in memory_out.split("\n") if l.strip()][:5]

    # ITCP 미읽음 메시지 확인
    itcp_out = ""
    try:
        sys.path.insert(0, str(SCRIPTS))
        import itcp
        unread = itcp.receive(agent, mark_read=False)  # 읽기만 하고 마킹은 안 함
        if unread:
            itcp_out = f"{len(unread)}개 미읽음 메시지"
            for m in unread[:3]:
                itcp_out += f"\n  [{m.get('from_agent','?')} → {agent}] {m.get('content','')[:60]}"
        else:
            itcp_out = "미읽음 메시지 없음"
    except Exception as e:
        itcp_out = f"ITCP 확인 실패: {e}"

    return {
        "step": 2,
        "name": "하이브 컨텍스트",
        "memory_count": len(memory_lines),
        "memory_preview": memory_lines[:3],
        "itcp": itcp_out,
        "ok": True,
    }


def step3_progress() -> dict:
    """Step 3: 진행 상황 파악"""
    # feature_list.json 읽기
    fl_path = ROOT / "feature_list.json"
    features_summary = []
    next_task = None
    if fl_path.exists():
        try:
            data = json.loads(fl_path.read_text(encoding="utf-8"))
            for f in data.get("features", []):
                status = "✅" if f.get("passes") else "❌"
                features_summary.append(f"{status} {f['id']} [{f['priority']}] {f['description'][:40]}")
                if not f.get("passes") and next_task is None:
                    next_task = f
        except Exception:
            features_summary = ["feature_list.json 파싱 실패"]

    # git log 최근 5개
    git_log = _run(["git", "log", "--oneline", "-5"])

    return {
        "step": 3,
        "name": "진행 상황",
        "features": features_summary,
        "next_task": next_task,
        "git_log": git_log.split("\n")[:5],
        "ok": True,
    }


def step4_harness() -> dict:
    """Step 4: 환경 검증 (harness_verify.py)"""
    raw = _run([sys.executable, str(SCRIPTS / "harness_verify.py"), "--json"])
    try:
        data = json.loads(raw)
        return {
            "step": 4,
            "name": "하네스 검증",
            "status": data.get("status", "unknown"),
            "passes": data.get("summary", {}).get("passes", 0),
            "warnings": data.get("summary", {}).get("warnings", 0),
            "errors": data.get("summary", {}).get("errors", 0),
            "error_details": data.get("details", {}).get("errors", []),
            "ok": data.get("status") == "ok",
        }
    except json.JSONDecodeError:
        return {
            "step": 4,
            "name": "하네스 검증",
            "status": "parse_error",
            "raw": raw[:300],
            "ok": False,
        }


def step5_recommendation(progress: dict) -> dict:
    """Step 5: 다음 작업 추천"""
    next_task = progress.get("next_task")
    if next_task:
        return {
            "step": 5,
            "name": "다음 작업 추천",
            "recommended": f"{next_task['id']}: {next_task['description']}",
            "priority": next_task.get("priority", "?"),
            "assigned_to": next_task.get("assigned_to", "미배정"),
            "ok": True,
        }
    return {
        "step": 5,
        "name": "다음 작업 추천",
        "recommended": "모든 기능 완료! 🎉",
        "ok": True,
    }


def run_protocol(agent: str = "claude", as_json: bool = False) -> int:
    """5단계 세션 프로토콜을 실행한다."""
    results = []

    results.append(step1_cwd())
    results.append(step2_hive_context(agent))
    progress = step3_progress()
    results.append(progress)
    results.append(step4_harness())
    results.append(step5_recommendation(progress))

    all_ok = all(r.get("ok", False) for r in results)

    if as_json:
        print(json.dumps({
            "session_protocol": "v2",
            "agent": agent,
            "all_ok": all_ok,
            "steps": results,
        }, ensure_ascii=False, indent=2))
    else:
        # 사람이 읽기 좋은 형태로 출력
        print(f"{'═' * 60}")
        print(f"🚀 세션 시작 프로토콜 (HARNESS V2) — {agent.upper()}")
        print(f"{'═' * 60}")

        for r in results:
            icon = "✅" if r.get("ok") else "❌"
            print(f"\n{icon} Step {r['step']}: {r['name']}")

            if r["step"] == 1:
                print(f"   CWD: {r['result']}")
            elif r["step"] == 2:
                print(f"   하이브 메모리: {r['memory_count']}개 항목")
                print(f"   ITCP: {r['itcp']}")
            elif r["step"] == 3:
                for f in r.get("features", []):
                    print(f"   {f}")
                print(f"   최근 커밋:")
                for g in r.get("git_log", [])[:3]:
                    print(f"     {g}")
            elif r["step"] == 4:
                print(f"   상태: {r.get('status')} | 통과: {r.get('passes')} | 경고: {r.get('warnings')} | 에러: {r.get('errors')}")
                for err in r.get("error_details", []):
                    print(f"   ❌ {err}")
            elif r["step"] == 5:
                print(f"   👉 {r.get('recommended', '없음')}")
                if r.get("priority"):
                    print(f"   우선순위: {r.get('priority')} | 배정: {r.get('assigned_to', '미배정')}")

        print(f"\n{'═' * 60}")
        status_msg = "🟢 세션 준비 완료" if all_ok else "🔴 문제 발견 — 위 에러를 먼저 수정하세요"
        print(f"{status_msg}")
        print(f"{'═' * 60}")

    return 0 if all_ok else 1


def main():
    parser = argparse.ArgumentParser(description="HARNESS V2 세션 시작 프로토콜")
    parser.add_argument("--agent", default="claude", choices=["claude", "gemini", "codex"],
                        help="에이전트 이름 (기본: claude)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()
    return run_protocol(agent=args.agent, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
