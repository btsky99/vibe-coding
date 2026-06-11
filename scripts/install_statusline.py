#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/install_statusline.py
DESCRIPTION:
    Claude Code 커스텀 상태줄을 현재 PC의 사용자 전역 설정에 멱등 설치한다.
    install_hive_hooks.py와 같은 이식성 패턴 — 저장소가 원본, ~/.claude는 배포처.

    동작:
      1) scripts/statusline.py → ~/.claude/statusline.py 복사 (항상 최신으로 덮어씀)
      2) ~/.claude/settings.json 백업 후 statusLine 키 멱등 머지
         - 키 없음        → 추가
         - 이 스크립트를 가리킴 → 경로만 현 PC 기준으로 갱신
         - 다른 커스텀 설정    → 보존 (--force 시에만 교체)

    사용:
      python scripts/install_statusline.py            # 설치
      python scripts/install_statusline.py --dry-run  # 변경 예정만 출력
      python scripts/install_statusline.py --force    # 기존 다른 statusLine도 교체

REVISION HISTORY:
- 2026-06-11 Claude: 최초 작성 — settings.json 덮어쓰기로 statusLine 유실됐던 사고 재발 방지
                     + 다른 PC 이식성 확보 (hive_hooks/skills_install 패턴 준수)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

# [WHY] 사용자 전역 settings.json 대상 — statusLine은 프로젝트가 아니라 PC(터미널) 단위 설정.
# hive_hooks가 프로젝트별 settings.local.json을 만지는 것과 구분되는 지점.
SOURCE = Path(__file__).resolve().parent / "statusline.py"
DEST_DIR = Path.home() / ".claude"
DEST_SCRIPT = DEST_DIR / "statusline.py"
SETTINGS = DEST_DIR / "settings.json"


def desired_command() -> str:
    # [호환성] 역슬래시는 settings.json 안에서 이스케이프 지옥 — 슬래시로 통일 (Windows도 동작)
    return f'python "{str(DEST_SCRIPT).replace(chr(92), "/")}"'


def is_our_statusline(entry: dict) -> bool:
    """기존 statusLine이 (경로가 달라도) statusline.py를 가리키면 우리 것으로 간주."""
    cmd = (entry or {}).get("command", "")
    return "statusline.py" in cmd.replace("\\", "/").lower()


def install(dry_run: bool = False, force: bool = False) -> int:
    if not SOURCE.is_file():
        print(f"[중단] 원본 없음: {SOURCE}")
        return 2

    # 1) 스크립트 복사 — 저장소 버전이 항상 원본 (수동 편집분은 덮어씀)
    print(f"[복사] {SOURCE} → {DEST_SCRIPT}")
    if not dry_run:
        DEST_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE, DEST_SCRIPT)

    # 2) settings.json 머지
    raw = SETTINGS.read_text(encoding="utf-8") if SETTINGS.is_file() else "{}"
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        print(f"[중단] settings.json 파싱 실패 — 수동 확인 필요: {SETTINGS}")
        return 3

    existing = data.get("statusLine")
    desired = {"type": "command", "command": desired_command()}

    if existing == desired:
        print("[멱등] statusLine 이미 최신 — 변경 없음")
        return 0

    if existing and not is_our_statusline(existing) and not force:
        print(f"[보존] 다른 커스텀 statusLine 감지 — 교체하려면 --force:")
        print(f"       {json.dumps(existing, ensure_ascii=False)}")
        return 0

    action = "갱신" if existing else "추가"
    print(f"[{action}] statusLine = {desired['command']}")

    if dry_run:
        print("[DRY-RUN] 파일 미수정")
        return 0

    if SETTINGS.is_file():
        ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        backup = SETTINGS.with_suffix(f".json.bak.{ts}")
        backup.write_text(raw, encoding="utf-8")
        print(f"[백업] {backup}")

    data["statusLine"] = desired
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[완료] {SETTINGS} — Claude Code 재시작 후 적용")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Claude Code 커스텀 상태줄 설치 (PC 간 이식)")
    ap.add_argument("--dry-run", action="store_true", help="실제 수정 없이 변경 예정만 출력")
    ap.add_argument("--force", action="store_true", help="기존 다른 statusLine 설정도 교체")
    args = ap.parse_args()
    return install(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
