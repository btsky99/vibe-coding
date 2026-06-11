"""
FILE: scripts/antigravity_session_repair.py
DESCRIPTION: Antigravity CLI 세션 히스토리 자동 수리 스크립트.
    Antigravity API 에러 "number of function response parts ≠ function call parts"의
    근본 원인을 수정합니다.

    [근본 원인]
    Antigravity CLI가 read_file로 이미지(PNG 등)를 읽으면 result에
    functionResponse + inlineData 2개 파트를 넣습니다.
    Antigravity API는 function call 1개당 function response 1개만 허용하므로
    result에 2개 파트가 들어가면 쌍이 깨져 400 에러가 발생합니다.

    [수리 방법]
    깨진 세션의 toolCall result에서 inlineData 파트를 제거하고
    functionResponse만 남깁니다.

    사용법:
      python scripts/antigravity_session_repair.py           # 스캔 + 자동 수리
      python scripts/antigravity_session_repair.py --scan     # 스캔만 (수정 안 함)
      python scripts/antigravity_session_repair.py --clean    # 깨진 세션 삭제

REVISION HISTORY:
- 2026-03-27 Claude: 최초 생성 — Gemini API function call/response 불일치 근본 수정
"""

import json
import os
import sys
import glob
import shutil
from pathlib import Path
from datetime import datetime


def _find_antigravity_chat_dirs() -> list[Path]:
    """Antigravity CLI 세션 저장 디렉터리 탐색"""
    home = Path.home()
    antigravity_tmp = home / ".gemini" / "tmp"
    dirs = []
    if antigravity_tmp.exists():
        for project_dir in antigravity_tmp.iterdir():
            chat_dir = project_dir / "chats"
            if chat_dir.exists():
                dirs.append(chat_dir)
    return dirs


def scan_session(filepath: Path) -> list[dict]:
    """세션 파일에서 function call/response 불일치 탐지

    Returns:
        불일치 정보 리스트. 각 항목: {msg_idx, tool_name, issue, result_parts}
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [{"msg_idx": -1, "tool_name": "?", "issue": "JSON 파싱 실패", "result_parts": 0}]

    messages = data.get("messages", [])
    issues = []

    for i, msg in enumerate(messages):
        tool_calls = msg.get("toolCalls", [])
        for tc in tool_calls:
            name = tc.get("name", "?")
            result = tc.get("result", [])

            if not isinstance(result, list):
                continue

            # 문제 1: result에 functionResponse 외의 파트(inlineData 등)가 섞여있음
            func_parts = [r for r in result if isinstance(r, dict) and "functionResponse" in r]
            non_func_parts = [r for r in result if isinstance(r, dict) and "functionResponse" not in r]

            if non_func_parts:
                for nfp in non_func_parts:
                    extra_keys = [k for k in nfp.keys() if k != "functionResponse"]
                    issues.append({
                        "msg_idx": i,
                        "tool_name": name,
                        "issue": f"result에 비-functionResponse 파트 포함: {extra_keys}",
                        "result_parts": len(result),
                        "func_parts": len(func_parts),
                        "non_func_parts": len(non_func_parts),
                    })

            # 문제 2: result가 비어있음 (tool call에 응답 없음)
            if len(result) == 0:
                issues.append({
                    "msg_idx": i,
                    "tool_name": name,
                    "issue": "result 비어있음",
                    "result_parts": 0,
                })

    return issues


def repair_session(filepath: Path) -> tuple[bool, int]:
    """세션 파일의 function call/response 불일치를 수리

    수리 방법:
    - toolCall result에서 inlineData 등 비-functionResponse 파트 제거
    - functionResponse만 남김

    Returns:
        (수리 여부, 수리된 항목 수)
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, 0

    messages = data.get("messages", [])
    repaired = 0

    for msg in messages:
        tool_calls = msg.get("toolCalls", [])
        for tc in tool_calls:
            result = tc.get("result", [])
            if not isinstance(result, list):
                continue

            # functionResponse만 남기고 나머지(inlineData 등) 제거
            func_only = [r for r in result if isinstance(r, dict) and "functionResponse" in r]
            non_func = [r for r in result if isinstance(r, dict) and "functionResponse" not in r]

            if non_func and func_only:
                tc["result"] = func_only
                repaired += 1

    if repaired > 0:
        # 백업 생성
        backup_path = filepath.with_suffix(".json.bak")
        if not backup_path.exists():
            shutil.copy2(filepath, backup_path)

        # 수리된 파일 저장
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return repaired > 0, repaired


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Antigravity 세션 히스토리 수리")
    parser.add_argument("--scan", action="store_true", help="스캔만 (수정 안 함)")
    parser.add_argument("--clean", action="store_true", help="깨진 세션 삭제")
    args = parser.parse_args()

    print("=" * 60)
    print("  Antigravity 세션 히스토리 수리 도구")
    print("=" * 60)

    chat_dirs = _find_antigravity_chat_dirs()
    if not chat_dirs:
        print("  Antigravity 세션 디렉터리를 찾을 수 없습니다.")
        return

    total_scanned = 0
    total_issues = 0
    total_repaired = 0

    for chat_dir in chat_dirs:
        project_name = chat_dir.parent.name
        sessions = sorted(glob.glob(str(chat_dir / "session-*.json")))

        if not sessions:
            continue

        print(f"\n  프로젝트: {project_name} ({len(sessions)}개 세션)")

        for spath in sessions:
            spath = Path(spath)
            total_scanned += 1
            issues = scan_session(spath)

            if not issues:
                continue

            total_issues += len(issues)
            fname = spath.name
            fsize = spath.stat().st_size // 1024

            print(f"\n    {fname} ({fsize}KB) — 문제 {len(issues)}건:")
            for issue in issues:
                print(f"      [{issue['msg_idx']}] {issue['tool_name']}: {issue['issue']}")

            if args.clean:
                # 깨진 세션 삭제
                backup = spath.with_suffix(".json.broken")
                shutil.move(str(spath), str(backup))
                print(f"      → 삭제됨 (백업: {backup.name})")
                total_repaired += len(issues)
            elif not args.scan:
                # 자동 수리
                was_repaired, count = repair_session(spath)
                if was_repaired:
                    print(f"      → 수리 완료 ({count}건, 백업: {spath.name}.bak)")
                    total_repaired += count
                else:
                    print(f"      → 수리 불가 (수동 확인 필요)")

    print(f"\n{'=' * 60}")
    print(f"  스캔: {total_scanned}개 세션")
    print(f"  문제: {total_issues}건")
    if not args.scan:
        print(f"  수리: {total_repaired}건")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
