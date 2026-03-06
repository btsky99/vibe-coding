# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 파일명: scripts/plan_validator.py
# 설명: Harness 패턴 계획 검증 엔진 (V1-V5).
#       ai_monitor_plan.md를 파싱하여 실행 전 계획 품질을 자동 검사합니다.
#       Claude Code Harness의 Task Validation 시스템을 Vibe Coding에 이식.
#
# 검증 규칙:
#   V1: 파일 경로 명시 여부 — 범위 명확성 (파일: 필드)
#   V2: 방법 필드 존재 여부 — 모호성 제거 (방법: 필드)
#   V3: 같은 파일이 2개 이상 태스크에 중복 등장 여부 — 겹침 검사
#   V4: 의존성 태스크가 실제 존재하는지 — 순서 검증
#   V5: 완료 조건 필드 존재 여부 — Done When 명시
#
# 사용법:
#   python scripts/plan_validator.py                     # ai_monitor_plan.md 검사
#   python scripts/plan_validator.py path/to/plan.md    # 특정 파일 검사
#
# 종료 코드:
#   0 = 모든 검증 통과
#   1 = 경고(비치명적 실패) — 계속 진행 가능하지만 주의 필요
#   2 = 오류(치명적 실패) — 계획 수정 없이 실행 금지
#
# 변경 이력:
# [2026-03-07] Claude: 최초 구현 — Harness V1-V5 검증 패턴 이식
# ------------------------------------------------------------------------
"""

import sys
import re
from pathlib import Path

# ── 색상 출력 헬퍼 (Windows 터미널 호환) ─────────────────────────────────────
def _green(s: str) -> str:  return f"\033[32m{s}\033[0m"
def _yellow(s: str) -> str: return f"\033[33m{s}\033[0m"
def _red(s: str) -> str:    return f"\033[31m{s}\033[0m"
def _bold(s: str) -> str:   return f"\033[1m{s}\033[0m"


def parse_tasks(content: str) -> list[dict]:
    """plan 파일에서 태스크 목록을 파싱합니다.

    태스크 형식:
        ### Task N: 설명
            파일: 경로
            방법: 설명
            완료 조건: 조건
            의존성: Task N 완료 후 시작

    또는 단순 형식:
        - [ ] Task N: 설명
            파일: 경로
    """
    tasks = []

    # ### Task N: 또는 [ ] Task N: 패턴으로 태스크 블록 추출
    # 태스크 헤더 패턴: ### Task N 또는 - [ ] Task N 또는 - [x] Task N
    task_header_re = re.compile(
        r'^(?:###\s+|\-\s+\[[ xX]\]\s+)(Task\s+\d+[:\s].+)$',
        re.MULTILINE
    )

    # 파일 내 각 필드 추출 패턴
    field_re = {
        'file':      re.compile(r'^\s+파일:\s*(.+)$', re.MULTILINE),
        'method':    re.compile(r'^\s+방법:\s*(.+)$', re.MULTILINE),
        'done_when': re.compile(r'^\s+(?:완료 조건|Done When|검증):\s*(.+)$', re.MULTILINE),
        'depends':   re.compile(r'^\s+의존성:\s*(.+)$', re.MULTILINE),
    }

    # 태스크 번호 추출 (의존성 검증용)
    task_num_re = re.compile(r'Task\s+(\d+)', re.IGNORECASE)

    # 태스크 블록을 위치 기반으로 분할
    matches = list(task_header_re.finditer(content))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block = content[start:end]

        # 태스크 번호 추출
        num_match = task_num_re.search(m.group(1))
        task_num = int(num_match.group(1)) if num_match else (i + 1)

        task = {
            'num':       task_num,
            'title':     m.group(1).strip(),
            'raw':       block,
            'file':      [],
            'method':    None,
            'done_when': None,
            'depends':   [],
        }

        # 각 필드 추출
        for field, pattern in field_re.items():
            found = pattern.findall(block)
            if found:
                if field == 'file':
                    # 파일 필드: 쉼표/줄바꿈으로 구분된 여러 경로 허용
                    for item in found:
                        paths = [p.strip() for p in re.split(r'[,\n]', item) if p.strip()]
                        task['file'].extend(paths)
                elif field == 'depends':
                    # 의존성: "Task 3 완료 후" 에서 번호 추출
                    dep_nums = task_num_re.findall(found[0])
                    task['depends'] = [int(n) for n in dep_nums]
                else:
                    task[field] = found[0].strip()

        tasks.append(task)

    return tasks


def validate(plan_path: Path) -> tuple[int, list[str]]:
    """계획 파일을 V1-V5로 검증합니다.

    Returns:
        (exit_code, messages): exit_code 0=통과, 1=경고, 2=오류
    """
    if not plan_path.exists():
        return 2, [_red(f"오류: 계획 파일을 찾을 수 없습니다: {plan_path}")]

    content = plan_path.read_text(encoding='utf-8')
    tasks = parse_tasks(content)

    if not tasks:
        return 1, [_yellow("경고: 태스크가 없습니다. 계획 파일을 확인하세요.")]

    messages = []
    exit_code = 0
    task_nums = {t['num'] for t in tasks}

    messages.append(_bold(f"\n[Plan Validator] {plan_path.name} — {len(tasks)}개 태스크 검사 중\n"))

    # ── V1: 파일 경로 명시 여부 ────────────────────────────────────────────────
    v1_fails = [t for t in tasks if not t['file']]
    if v1_fails:
        exit_code = max(exit_code, 1)
        for t in v1_fails:
            messages.append(_yellow(f"  [V1 경고] Task {t['num']}: '파일:' 필드 없음 — 범위가 불명확합니다"))
    else:
        messages.append(_green(f"  [V1 통과] 파일 경로 명시 — {len(tasks)}개 태스크 모두 확인됨"))

    # ── V2: 방법 필드 존재 여부 ───────────────────────────────────────────────
    v2_fails = [t for t in tasks if not t['method']]
    if v2_fails:
        exit_code = max(exit_code, 1)
        for t in v2_fails:
            messages.append(_yellow(f"  [V2 경고] Task {t['num']}: '방법:' 필드 없음 — 구현 방법이 모호합니다"))
    else:
        messages.append(_green(f"  [V2 통과] 방법 필드 명시 — {len(tasks)}개 태스크 모두 확인됨"))

    # ── V3: 파일 중복 검사 ────────────────────────────────────────────────────
    file_to_tasks: dict[str, list[int]] = {}
    for t in tasks:
        for fp in t['file']:
            # 신규/레거시 표시 제거하고 경로만 비교
            clean = re.sub(r'\s*\(.*?\)', '', fp).strip()
            if clean and clean != '?':
                file_to_tasks.setdefault(clean, []).append(t['num'])

    v3_dups = {fp: nums for fp, nums in file_to_tasks.items() if len(nums) > 1}
    if v3_dups:
        exit_code = max(exit_code, 1)
        for fp, nums in v3_dups.items():
            messages.append(_yellow(
                f"  [V3 경고] '{fp}' 가 Task {', '.join(map(str, nums))}에 중복 등장 "
                f"— 충돌 가능성이 있습니다"
            ))
    else:
        messages.append(_green(f"  [V3 통과] 파일 중복 없음"))

    # ── V4: 의존성 태스크 존재 여부 ───────────────────────────────────────────
    v4_fails = []
    for t in tasks:
        for dep in t['depends']:
            if dep not in task_nums:
                v4_fails.append((t['num'], dep))

    if v4_fails:
        exit_code = max(exit_code, 2)  # V4는 치명적 오류
        for task_num, missing_dep in v4_fails:
            messages.append(_red(
                f"  [V4 오류] Task {task_num}: 의존 Task {missing_dep}가 존재하지 않습니다"
            ))
    else:
        messages.append(_green(f"  [V4 통과] 의존성 순서 검증됨"))

    # ── V5: 완료 조건 필드 존재 여부 ─────────────────────────────────────────
    v5_fails = [t for t in tasks if not t['done_when']]
    if v5_fails:
        exit_code = max(exit_code, 1)
        for t in v5_fails:
            messages.append(_yellow(
                f"  [V5 경고] Task {t['num']}: '완료 조건:' 필드 없음 "
                f"— 언제 끝나는지 알 수 없습니다"
            ))
    else:
        messages.append(_green(f"  [V5 통과] 완료 조건 명시 — {len(tasks)}개 태스크 모두 확인됨"))

    # ── 최종 결과 ─────────────────────────────────────────────────────────────
    messages.append("")
    if exit_code == 0:
        messages.append(_green(_bold("✓ 모든 검증 통과 — 계획 실행 가능합니다")))
    elif exit_code == 1:
        messages.append(_yellow(_bold("⚠ 경고 있음 — 진행 가능하나 계획 보완을 권장합니다")))
    else:
        messages.append(_red(_bold("✗ 치명적 오류 — 계획을 수정한 후 재실행하세요")))

    return exit_code, messages


def check_all_done(plan_path: Path) -> bool:
    """계획 파일의 모든 태스크가 완료([x]) 상태인지 확인합니다.

    hive_hook.py Stop 이벤트에서 자동 중지 신호 판단에 사용합니다.

    Returns:
        True = 모든 태스크 완료 → {"continue": false} 신호 가능
        False = 미완료 태스크 있음 → 계속 진행
    """
    if not plan_path.exists():
        return False

    content = plan_path.read_text(encoding='utf-8')

    # [ ] 형식의 미완료 태스크가 있는지 검사
    # [x] 또는 [X]는 완료, [ ]는 미완료
    incomplete = re.findall(r'-\s+\[ \]', content)
    complete   = re.findall(r'-\s+\[[xX]\]', content)

    # 완료된 태스크가 하나라도 있고, 미완료 태스크가 없으면 True
    return bool(complete) and not bool(incomplete)


def main():
    # 인자로 파일 경로 받기 (기본값: 프로젝트 루트의 ai_monitor_plan.md)
    if len(sys.argv) > 1:
        plan_path = Path(sys.argv[1])
    else:
        # 이 스크립트 위치 기준으로 상위 폴더의 ai_monitor_plan.md
        plan_path = Path(__file__).resolve().parent.parent / "ai_monitor_plan.md"

    exit_code, messages = validate(plan_path)
    print('\n'.join(messages))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
