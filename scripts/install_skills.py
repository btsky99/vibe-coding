"""
FILE: scripts/install_skills.py
DESCRIPTION:
    외부(또는 자기) 프로젝트의 .claude/skills/, .claude/agents/에
    비이브 코딩의 vibe-* 슬래시 명령과 subagent들을 복사한다.
    ⑨ 스킬/Subagent 설치 프롬프트가 이 스크립트를 호출한다.

    동작:
      1) 비이브 코딩 저장소 루트를 우선순위로 자동 탐색
         (a) 환경변수 VIBE_HOME — 디렉토리 (.claude/skills/ 포함)
         (b) PATH의 vibe-coding[.exe] 옆/부모/조부모의 .claude/skills/
         (c) 표준 설치 경로 후보 순회
      2) 대상 프로젝트의 .claude/skills/, .claude/agents/ 백업 (다른 내용 있을 때만)
      3) 소스 → 대상 디렉토리 복사 (shutil.copytree dirs_exist_ok)
      4) 결과 요약 출력 (성공 시 exit 0)

    사용:
      python install_skills.py --target D:/ons
      python install_skills.py --target . --dry-run

REVISION HISTORY:
    2026-06-07 [Claude] 최초 작성 — ⑨ skills-install 세팅 프롬프트 동반.
                다른 프로젝트에서도 vibe-* 슬래시 명령과 subagent를 그대로 쓰기 위함.
                install_hive_hooks.py 자동 탐색 패턴 복제.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import filecmp
import os
import shutil
import sys
from pathlib import Path
from typing import Optional


# 복사 대상 — vibe-coding 저장소 안에서 외부 프로젝트로 옮길 .claude/ 하위 디렉토리
TARGET_DIRS = ("skills", "agents")


# ─────────────────────────────────────────────────────────
# 1. 비이브 코딩 저장소 자동 탐색
# ─────────────────────────────────────────────────────────
def find_vibe_home() -> tuple[Optional[Path], str]:
    """비이브 코딩 저장소 루트를 탐색해서 (.claude 부모 디렉토리, 출처 문자열) 반환.

    Returns:
        (Path, source) — 발견. .claude/skills/ + .claude/agents/ 둘 다 있어야 OK.
        (None, "NOT_FOUND")
    """
    def _ok(root: Path) -> bool:
        # skills/ 또는 agents/ 둘 중 하나만 있어도 의미는 있지만 — 둘 다 있어야 정식.
        return (root / ".claude" / "skills").is_dir() and (root / ".claude" / "agents").is_dir()

    env = os.environ.get("VIBE_HOME")
    if env:
        p = Path(env)
        if p.is_dir() and _ok(p):
            return p, f"env:VIBE_HOME={env}"

    # PATH 검색 — vibe-coding[.exe] 옆/부모/조부모
    exe = shutil.which("vibe-coding") or shutil.which("vibe-coding.exe")
    if exe:
        ep = Path(exe).parent
        for cand in (ep, ep.parent, ep.parent.parent):
            if _ok(cand):
                return cand, f"PATH:{exe}"

    # 표준 설치 경로
    std_candidates = [
        Path("C:/Program Files/vibe-coding"),
        Path("C:/Program Files (x86)/vibe-coding"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/vibe-coding",
        Path("D:/vibe-coding"),
        Path("C:/vibe-coding"),
    ]
    for c in std_candidates:
        if _ok(c):
            return c, f"std:{c}"

    return None, "NOT_FOUND"


# ─────────────────────────────────────────────────────────
# 2. 디렉토리 비교 — 내용 동일 여부
# ─────────────────────────────────────────────────────────
def dirs_differ(a: Path, b: Path) -> bool:
    """두 디렉토리 내용이 다른지 재귀 확인. b가 없으면 True(=다름)."""
    if not b.exists():
        return True
    cmp = filecmp.dircmp(str(a), str(b), ignore=[])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    # subdir 재귀
    for sub in cmp.common_dirs:
        if dirs_differ(a / sub, b / sub):
            return True
    return False


# ─────────────────────────────────────────────────────────
# 3. 백업
# ─────────────────────────────────────────────────────────
def backup_dir(target: Path, ts: str) -> Optional[Path]:
    """target 디렉토리를 옆에 .bak.<ts>로 복사. 존재 안 하면 None 반환."""
    if not target.exists():
        return None
    backup = target.with_name(f"{target.name}.bak.{ts}")
    shutil.copytree(str(target), str(backup), dirs_exist_ok=False)
    return backup


# ─────────────────────────────────────────────────────────
# 4. 메인 설치
# ─────────────────────────────────────────────────────────
def install(target_root: Path, dry_run: bool = False) -> int:
    src_root, source = find_vibe_home()
    print(f"[자동 탐색] source = {source}")
    if src_root is None:
        print("[중단] 비이브 코딩 저장소를 찾지 못함. VIBE_HOME 환경변수를 설정하거나 설치 경로 확인.")
        return 2
    print(f"[자동 탐색] vibe-coding root = {src_root}")

    # 자기 자신을 자기 자신에 설치하려는 경우 — no-op
    if src_root.resolve() == target_root.resolve():
        print("[정보] 대상이 비이브 코딩 저장소 자체 — 설치 불필요 (스킬/agents가 이미 그곳에 있음).")
        return 0

    dest_claude = target_root / ".claude"
    dest_claude.mkdir(parents=True, exist_ok=True)

    ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    total_copied = 0
    total_skipped = 0
    total_backed_up = 0

    for name in TARGET_DIRS:
        src = src_root / ".claude" / name
        dest = dest_claude / name

        if not src.is_dir():
            print(f"  {name:8s}: SOURCE_MISSING ({src}) — 건너뜀")
            continue

        # 멱등: 내용 동일하면 skip
        if dest.is_dir() and not dirs_differ(src, dest):
            print(f"  {name:8s}: SKIP (이미 최신)")
            total_skipped += 1
            continue

        # 다른 내용이 있으면 백업
        if dest.is_dir():
            if dry_run:
                print(f"  {name:8s}: WOULD_BACKUP → {dest.name}.bak.{ts}")
            else:
                bk = backup_dir(dest, ts)
                if bk:
                    print(f"  {name:8s}: BACKUP   → {bk.name}")
                    total_backed_up += 1
            if not dry_run:
                shutil.rmtree(str(dest))

        # 복사
        if dry_run:
            n_files = sum(1 for _ in src.rglob("*") if _.is_file())
            print(f"  {name:8s}: WOULD_COPY {n_files}개 파일 → {dest}")
        else:
            shutil.copytree(str(src), str(dest), dirs_exist_ok=False)
            n_files = sum(1 for _ in dest.rglob("*") if _.is_file())
            print(f"  {name:8s}: COPIED   {n_files}개 파일 → {dest}")
            total_copied += 1

    print(f"\n[완료] {target_root / '.claude'}")
    print(f"       복사 {total_copied} / 건너뜀 {total_skipped} / 백업 {total_backed_up}")
    print("       Claude Code 재시작 후 slash 명령(/vibe-*)이 이 프로젝트에서 동작한다.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="외부 프로젝트에 비이브 코딩 스킬/Subagent 설치")
    ap.add_argument("--target", default=".", help="대상 프로젝트 루트 (기본: 현재 디렉토리)")
    ap.add_argument("--dry-run", action="store_true", help="실제 수정 없이 변경 예정만 출력")
    args = ap.parse_args()

    target_root = Path(args.target).resolve()
    if not target_root.is_dir():
        print(f"[오류] 대상 디렉토리가 없음: {target_root}")
        return 1

    return install(target_root, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
