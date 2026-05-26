"""
FILE: scripts/install_hive_hooks.py
DESCRIPTION:
    외부(또는 자기) 프로젝트의 .claude/settings.local.json에 비이브 코딩 하이브 훅을
    멱등 주입한다. ⑤ 하이브 훅 설치 프롬프트가 이 스크립트를 호출한다.

    [지원 형식]
      A) 개발 체크아웃 / 설치 EXE 옆에 scripts/가 풀려있는 경우
         → `python "<scripts>/hive_hook.py"` 형태로 명령 등록
      B) 설치 EXE 단독 (Inno Setup) PC — scripts/ 폴더가 외부에 없는 경우
         → `"<vibe-coding.exe>" hook` 서브커맨드 형태로 등록 (B3)

    동작:
      1) 비이브 코딩 hook 진입점을 우선순위로 자동 탐색
         (a) 환경변수 VIBE_HIVE_HOOK — .py 파일/디렉토리 또는 .exe 파일 허용
         (b) PATH의 vibe-coding[.exe] (EXE 형식)
         (c) PATH의 vibe-coding[.exe] 옆/부모의 scripts/ (PY 형식)
         (d) 표준 설치 경로 후보 순회 — .exe + scripts/ 양쪽 모두 검사
      2) 대상 settings.local.json 백업 후 hooks 키 머지 (덮어쓰기 금지)
      3) 같은 hook 진입점을 가리키는 명령은 따옴표/슬래시 차이를 무시하고 중복 제거
         (PY 형식과 EXE 형식은 서로 다른 키로 취급 — 정상)
      4) 결과 요약 출력 (성공 시 exit 0)

    사용:
      python install_hive_hooks.py --target D:/ons
      python install_hive_hooks.py --target . --dry-run

REVISION HISTORY:
    2026-05-26 [Claude] B3: 설치 EXE 단독 PC 호환 — vibe-coding.exe hook 서브커맨드 지원
    2026-05-10 [Claude] 최초 작성 — 다른 PC/설치 EXE 환경 호환성 확보
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional


HOOK_SCRIPTS = ("hive_hook.py", "hook_bridge.py", "claude_hook.py")


# ─────────────────────────────────────────────────────────
# 1. 자동 탐색 — PY(scripts/) 또는 EXE(vibe-coding.exe hook) 형식
# ─────────────────────────────────────────────────────────
def find_hook_entry() -> tuple[str, Optional[Path], str]:
    """hook 진입점을 우선순위로 탐색.

    Returns:
        ("py", scripts_dir, source) — scripts/ 디렉토리가 외부에 있는 경우
        ("exe", exe_path,    source) — 설치 EXE 단독인 경우 (vibe-coding.exe hook)
        ("none", None,       "NOT_FOUND")
    """
    env = os.environ.get("VIBE_HIVE_HOOK")
    if env:
        p = Path(env)
        # PY 형식: 파일은 hive_hook.py, 디렉토리는 scripts/
        if p.is_file() and p.name == "hive_hook.py":
            return "py", p.parent, f"env:VIBE_HIVE_HOOK={env}"
        if p.is_dir() and (p / "hive_hook.py").is_file():
            return "py", p, f"env:VIBE_HIVE_HOOK={env}"
        # EXE 형식: vibe-coding.exe 직접 지정
        if p.is_file() and p.suffix.lower() == ".exe":
            return "exe", p, f"env:VIBE_HIVE_HOOK={env}"

    # PATH 검색 — scripts/가 옆에 있으면 PY, 없으면 EXE 폴백
    exe = shutil.which("vibe-coding") or shutil.which("vibe-coding.exe")
    if exe:
        for cand in (Path(exe).parent / "scripts", Path(exe).parent.parent / "scripts"):
            if (cand / "hive_hook.py").is_file():
                return "py", cand, f"PATH:{exe}"
        # scripts/ 없음 → EXE 서브커맨드로 폴백 (설치 EXE 단독 PC)
        if Path(exe).is_file():
            return "exe", Path(exe), f"PATH:{exe} (EXE 서브커맨드)"

    # 표준 설치 경로 — EXE 후보와 scripts/ 후보를 함께 탐색
    exe_candidates = [
        Path("C:/Program Files/VibeCoding/vibe-coding.exe"),
        Path("C:/Program Files (x86)/VibeCoding/vibe-coding.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/VibeCoding/vibe-coding.exe",
    ]
    scripts_candidates = [
        Path("C:/Program Files/vibe-coding/scripts"),
        Path("C:/Program Files (x86)/vibe-coding/scripts"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/vibe-coding/scripts",
        Path("D:/vibe-coding/scripts"),
        Path("C:/vibe-coding/scripts"),
    ]
    for c in scripts_candidates:
        if (c / "hive_hook.py").is_file():
            return "py", c, f"std:{c}"
    for c in exe_candidates:
        if c.is_file():
            return "exe", c, f"std:{c}"

    return "none", None, "NOT_FOUND"


# ─────────────────────────────────────────────────────────
# 2. command 정규화 (멱등성용)
# ─────────────────────────────────────────────────────────
_PY_CMD_RE = re.compile(
    r'''^\s*(?:python|python3|py)\s+(?:["']([^"']+)["']|(\S+))(?:\s+(.*))?$''',
    re.IGNORECASE,
)
# EXE 서브커맨드 형식: `"...vibe-coding.exe" hook [suffix]`
_EXE_CMD_RE = re.compile(
    r'''^\s*(?:["']([^"']+\.exe)["']|(\S+\.exe))\s+(hook)(?:\s+(.*))?$''',
    re.IGNORECASE,
)


def normalize_command(cmd: str) -> Optional[tuple[str, str]]:
    """명령에서 (정규화된 경로, suffix)를 추출. 매칭 실패 시 None.

    예) `python "D:/x/hive_hook.py"`        → ("d:/x/hive_hook.py", "")
        `python D:\\x\\claude_hook.py stop` → ("d:/x/claude_hook.py", "stop")
        `"C:/Program Files/.../vibe-coding.exe" hook`
                                            → ("c:/program files/.../vibe-coding.exe", "hook")
        `"...vibe-coding.exe" hook stop`    → ("...vibe-coding.exe", "hook stop")
    """
    m = _EXE_CMD_RE.match(cmd or "")
    if m:
        path = (m.group(1) or m.group(2) or "").replace("\\", "/").strip().lower()
        sub = (m.group(3) or "").strip()
        extra = (m.group(4) or "").strip()
        suffix = f"{sub} {extra}".strip() if extra else sub
        return path, suffix
    m = _PY_CMD_RE.match(cmd or "")
    if not m:
        return None
    path = (m.group(1) or m.group(2) or "").replace("\\", "/").strip().lower()
    suffix = (m.group(3) or "").strip()
    return path, suffix


def make_command(script_path: Path, suffix: str = "", *, kind: str = "py") -> str:
    """hooks에 박을 정규화된 command 문자열을 생성.

    kind="py"  → `python "<scripts>/xxx.py" [suffix]`
    kind="exe" → `"<vibe-coding.exe>" hook [suffix]`
    """
    p = str(script_path).replace("\\", "/")
    if kind == "exe":
        base = f'"{p}" hook'
    else:
        base = f'python "{p}"'
    return f"{base} {suffix}".strip() if suffix else base


# ─────────────────────────────────────────────────────────
# 3. 멱등 머지
# ─────────────────────────────────────────────────────────
def merge_event(
    existing_groups: list,
    matcher: str,
    desired_commands: list[str],
    desired_keys: list[tuple[str, str]],
) -> tuple[list, int]:
    """이벤트 한 개에 대해 hooks 그룹 머지. (새 그룹 리스트, 추가된 hook 수) 반환.

    desired_keys: 정규화된 (path, suffix) 키. existing의 어떤 hook이 같은 키면 중복으로 간주.
    """
    groups = list(existing_groups or [])

    # 기존 정규화 키 수집
    existing_keys: set[tuple[str, str]] = set()
    for g in groups:
        for h in g.get("hooks", []) or []:
            if h.get("type") == "command":
                norm = normalize_command(h.get("command", ""))
                if norm:
                    existing_keys.add(norm)

    # 누락된 hook만 추가
    new_hooks = []
    added = 0
    for cmd, key in zip(desired_commands, desired_keys):
        if key in existing_keys:
            continue
        new_hooks.append({"type": "command", "command": cmd})
        added += 1

    if new_hooks:
        groups.append({"matcher": matcher, "hooks": new_hooks})

    return groups, added


# ─────────────────────────────────────────────────────────
# 4. 메인
# ─────────────────────────────────────────────────────────
def install(target_root: Path, dry_run: bool = False) -> int:
    settings_path = target_root / ".claude" / "settings.local.json"
    if not settings_path.is_file():
        # 없으면 빈 골격 생성
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            settings_path.write_text("{}\n", encoding="utf-8")
        print(f"[정보] 새 settings.local.json 생성 예정: {settings_path}")

    kind, hook_entry, source = find_hook_entry()
    print(f"[자동 탐색] source = {source}")
    if kind == "none" or hook_entry is None:
        print("[중단] hook 진입점을 찾지 못함. VIBE_HIVE_HOOK 환경변수를 설정하거나 vibe-coding을 설치하세요.")
        return 2
    print(f"[자동 탐색] kind={kind}, entry={hook_entry}")

    # 이벤트 정의 — 형식별 분기
    if kind == "exe":
        # 설치 EXE 단독 PC: vibe-coding.exe hook 서브커맨드 하나가 모든 이벤트 처리.
        # claude_hook.py(stop) / hook_bridge.py 같은 보조 스크립트는 EXE 내부에서
        # hive_hook이 직접 호출하므로 별도 등록 불필요.
        events = [
            ("UserPromptSubmit", "", [(hook_entry, "")]),
            ("PreToolUse", "Edit|Write|Bash", [(hook_entry, "")]),
            ("PostToolUse", "Edit|Write|Bash|NotebookEdit", [(hook_entry, "")]),
            ("Stop", "", [(hook_entry, "")]),
        ]
        print("  hive_hook(EXE)    : OK (서브커맨드)")
    else:
        # PY 형식 — 기존 동작 그대로
        hook_dir = hook_entry
        available: dict[str, Optional[Path]] = {}
        for name in HOOK_SCRIPTS:
            p = hook_dir / name
            available[name] = p if p.is_file() else None
            print(f"  {name:18s}: {'OK' if available[name] else 'MISSING'}")

        if available["hive_hook.py"] is None:
            print("[중단] hive_hook.py가 없음.")
            return 3

        events = [
            ("UserPromptSubmit", "", [
                (available["hive_hook.py"], ""),
                *([(available["hook_bridge.py"], "")] if available["hook_bridge.py"] else []),
            ]),
            ("PreToolUse", "Edit|Write|Bash", [
                (available["hive_hook.py"], ""),
            ]),
            ("PostToolUse", "Edit|Write|Bash|NotebookEdit", [
                (available["hive_hook.py"], ""),
            ]),
            ("Stop", "", [
                (available["hive_hook.py"], ""),
                *([(available["claude_hook.py"], "stop")] if available["claude_hook.py"] else []),
            ]),
        ]

    # 백업
    raw = settings_path.read_text(encoding="utf-8") if settings_path.is_file() else "{}"
    if not dry_run:
        ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        backup = settings_path.with_suffix(f".json.bak.{ts}")
        backup.write_text(raw, encoding="utf-8")
        print(f"[백업] {backup}")

    data = json.loads(raw or "{}")
    hooks = dict(data.get("hooks", {}))

    print("\n[멱등 머지]")
    total_added = 0
    for event, matcher, items in events:
        desired_commands = [make_command(p, s, kind=kind) for p, s in items]
        desired_keys = [normalize_command(c) for c in desired_commands]
        new_groups, added = merge_event(hooks.get(event, []), matcher, desired_commands, desired_keys)
        hooks[event] = new_groups
        total_added += added
        print(f"  {event:18s} | 추가 {added}개")

    data["hooks"] = hooks

    if dry_run:
        print("\n[DRY-RUN] 파일 미수정. 변경될 hooks:")
        print(json.dumps(hooks, ensure_ascii=False, indent=2))
        return 0

    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n[완료] {settings_path}")
    print(f"       총 {total_added}개 hook 신규 등록 (이미 있던 것은 유지)")
    print("       Claude Code 재시작 후 적용됨.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="외부 프로젝트에 비이브 코딩 하이브 훅 설치")
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
