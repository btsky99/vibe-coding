# -*- coding: utf-8 -*-
"""
FILE: scripts/drift_detector.py
DESCRIPTION: 계획 이탈 감지기 — 현재 작업이 ai_monitor_plan.md와 일치하는지 검증.

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAN_FILE = PROJECT_ROOT / "ai_monitor_plan.md"

TASK_RE = re.compile(r"^\[(?P<done>[ xX])\]\s*Task\s*(?P<number>\d+):\s*(?P<title>.+?)\s*$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
PATH_RE = re.compile(r"[A-Za-z0-9_.\\/:-]+\.[A-Za-z0-9_]+")


@dataclass
class PlanTask:
    number: int
    title: str
    done: bool
    details: list[str] = field(default_factory=list)
    section: str = ""

    @property
    def path_hints(self) -> set[str]:
        hints: set[str] = set()
        for block in [self.title, *self.details]:
            for match in PATH_RE.findall(block):
                normalized = _normalize_path(match)
                if normalized:
                    hints.add(normalized)
                    hints.add(Path(normalized).name.lower())
        return hints

    @property
    def tokens(self) -> set[str]:
        tokens = _extract_tokens(self.title)
        for detail in self.details:
            tokens.update(_extract_tokens(detail))
        return tokens


def _normalize_path(value: str) -> str:
    return value.strip().strip("`'\"").replace("\\", "/").lower()


def _extract_tokens(text: str) -> set[str]:
    tokens = {token.lower() for token in TOKEN_RE.findall(text)}
    for match in PATH_RE.findall(text):
        normalized = _normalize_path(match)
        parts = re.split(r"[/._:-]+", normalized)
        tokens.update(part for part in parts if len(part) >= 3)
    return tokens


def parse_plan_tasks() -> list[PlanTask]:
    if not PLAN_FILE.exists():
        return []

    lines = PLAN_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    tasks: list[PlanTask] = []
    current: PlanTask | None = None
    current_section = ""

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            continue

        task_match = TASK_RE.match(stripped)
        if task_match:
            current = PlanTask(
                number=int(task_match.group("number")),
                title=task_match.group("title").strip(),
                done=task_match.group("done").lower() == "x",
                section=current_section,
            )
            tasks.append(current)
            continue

        if current and (line.startswith("    ") or line.startswith("\t") or stripped.startswith("- ")):
            if stripped:
                current.details.append(stripped)
            continue

        current = None

    return tasks


def get_open_tasks() -> list[PlanTask]:
    return [task for task in parse_plan_tasks() if not task.done]


def get_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        payload = line[3:] if len(line) > 3 else ""
        if "->" in payload:
            payload = payload.split("->", 1)[1]
        normalized = _normalize_path(payload)
        if normalized:
            changed.append(normalized)

    return sorted(dict.fromkeys(changed))


def _score_task(task: PlanTask, changed_files: list[str]) -> tuple[int, list[str], list[str]]:
    score = 0
    matched_files: list[str] = []
    unmatched_files: list[str] = []

    for changed_file in changed_files:
        path_tokens = _extract_tokens(changed_file)
        basename = Path(changed_file).name.lower()
        file_score = 0

        for hint in task.path_hints:
            if hint == changed_file or hint == basename:
                file_score += 8
            elif hint and hint in changed_file:
                file_score += 5

        overlap = task.tokens.intersection(path_tokens)
        file_score += len(overlap) * 2

        if task.section and any(token in changed_file for token in _extract_tokens(task.section)):
            file_score += 1

        if file_score > 0:
            score += file_score
            matched_files.append(changed_file)
        else:
            unmatched_files.append(changed_file)

    return score, matched_files, unmatched_files


def build_report() -> dict:
    open_tasks = get_open_tasks()
    changed_files = get_changed_files()

    report = {
        "state": "clean",
        "summary": "No workspace changes detected.",
        "changed_files": changed_files,
        "current_task": None,
        "relevant_files": [],
        "unplanned_files": [],
        "open_task_count": len(open_tasks),
    }

    if not changed_files:
        return report

    if not open_tasks:
        sample = ", ".join(changed_files[:5])
        remainder = "" if len(changed_files) <= 5 else f" (+{len(changed_files) - 5} more)"
        report.update(
            {
                "state": "unplanned",
                "summary": (
                    "Plan has no open tasks, but the workspace still has changes: "
                    f"{sample}{remainder}. Update ai_monitor_plan.md if this work is intentional."
                ),
                "unplanned_files": changed_files,
            }
        )
        return report

    best_task: PlanTask | None = None
    best_score = -1
    best_matches: list[str] = []

    for task in open_tasks:
        score, matched, _ = _score_task(task, changed_files)
        if score > best_score:
            best_task = task
            best_score = score
            best_matches = matched

    if not best_task or best_score <= 0:
        sample = ", ".join(changed_files[:5])
        remainder = "" if len(changed_files) <= 5 else f" (+{len(changed_files) - 5} more)"
        report.update(
            {
                "state": "drift",
                "summary": (
                    "Changed files do not map to any open plan task. "
                    f"Current changes: {sample}{remainder}."
                ),
                "unplanned_files": changed_files,
            }
        )
        return report

    unplanned = [path for path in changed_files if path not in best_matches]
    aligned_summary = (
        f"Current work aligns best with Task {best_task.number}: {best_task.title}. "
        f"Matched files: {', '.join(best_matches[:5]) or 'none'}."
    )
    if unplanned:
        preview = ", ".join(unplanned[:5])
        extra = "" if len(unplanned) <= 5 else f" (+{len(unplanned) - 5} more)"
        aligned_summary += f" Unmatched changes still present: {preview}{extra}."

    report.update(
        {
            "state": "aligned" if not unplanned else "mixed",
            "summary": aligned_summary,
            "current_task": {
                "number": best_task.number,
                "title": best_task.title,
                "section": best_task.section,
                "details": best_task.details,
            },
            "relevant_files": best_matches,
            "unplanned_files": unplanned,
        }
    )
    return report


def check_drift() -> str:
    return build_report()["summary"]


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    report = build_report()
    if args and args[0] == "--json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
