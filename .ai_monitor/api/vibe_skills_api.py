"""
FILE: api/vibe_skills_api.py
DESCRIPTION: Platform Phase 3 — .vibe/skills + .claude/skills 병합 스캐너.
             Layer 2 확장(프로젝트별 스킬)을 자동 로드해 UI 슬래시 팝업에
             통합 목록을 제공한다.

             [병합 규칙]
             - .claude/skills/ 를 먼저 스캔 (Claude CLI 전용)
             - .vibe/skills/ 를 덮어씀 (중복 이름 시 .vibe/ 우선, origin='vibe')
             - 각 스킬에 origin: "claude" | "vibe" 필드 부여

             [스캐너 파싱]
             - YAML 라이브러리 없이 frontmatter 파싱 (name, description,
               allowed-tools, user-invocable)
             - description의 > 멀티라인 + 단일라인 모두 지원

             규약: docs/VIBE_CONVENTIONS.md

REVISION HISTORY:
- 2026-04-19 Claude: 최초 작성 — Phase 3-2
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# YAML frontmatter 블록 구분자
_FRONT_RE = re.compile(r'^---\s*\r?\n(.*?)\r?\n---\s*\r?\n', re.DOTALL)

# 단순 "key: value" 라인 매처 (indent 허용 X — 최상위 키만)
_KV_RE = re.compile(r'^([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$')


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """SKILL.md 첫머리의 YAML frontmatter를 파싱.

    지원: 단순 키:값, 'key: >' 접기 스타일 멀티라인, comma 리스트
    지원 안 함: 중첩 dict, YAML 앵커, 들여쓰기 기반 list (Claude skills에선 불필요)
    """
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    block = m.group(1)

    result: dict[str, Any] = {}
    current_key: str | None = None
    current_folded: list[str] = []

    for raw_line in block.splitlines():
        # 접기 스타일 키 수집 중이면 들여쓴 라인을 계속 합침
        if current_key is not None:
            if raw_line.startswith(" ") or raw_line.startswith("\t"):
                current_folded.append(raw_line.strip())
                continue
            # 들여쓰기 끝 → flush
            result[current_key] = " ".join(current_folded).strip()
            current_key = None
            current_folded = []

        kv = _KV_RE.match(raw_line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2)

        # 접기 스타일 진입
        if value in (">", "|", ">-", "|-"):
            current_key = key
            current_folded = []
            continue

        result[key] = value

    # 마지막 접기 블록 flush
    if current_key is not None:
        result[current_key] = " ".join(current_folded).strip()

    return result


def _coerce_tools(value: Any) -> list[str]:
    """allowed-tools 값을 list[str]로 정규화 (comma-separated 문자열 허용)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "1", "on"):
            return True
        if v in ("false", "no", "0", "off"):
            return False
    return default


def _scan_skills_dir(skills_dir: Path, origin: str, project_root: Path) -> list[dict]:
    """해당 디렉토리의 <name>/SKILL.md 들을 스캔해 스킬 dict 리스트 반환."""
    if not skills_dir.exists() or not skills_dir.is_dir():
        return []

    out: list[dict] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        # SKILL.md 또는 skill.md (대소문자 혼용 허용)
        skill_md = None
        for candidate in ("SKILL.md", "skill.md"):
            p = entry / candidate
            if p.exists():
                skill_md = p
                break
        if skill_md is None:
            continue

        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue

        fm = _parse_frontmatter(text)
        if not fm:
            # frontmatter 없음 — 규약 위반이지만 파싱 가능하게 이름만 넣음
            fm = {"name": entry.name, "description": ""}

        name = str(fm.get("name", entry.name)).strip() or entry.name

        try:
            rel_path = str(skill_md.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            rel_path = str(skill_md).replace("\\", "/")

        out.append({
            "name": name,
            "description": str(fm.get("description", "")).strip(),
            "allowed_tools": _coerce_tools(fm.get("allowed-tools")),
            "user_invocable": _coerce_bool(fm.get("user-invocable"), True),
            "origin": origin,
            "path": rel_path,
            "dir_name": entry.name,  # 디렉토리명과 name 불일치 탐지용
        })

    return out


def list_claude_skills(project_root: Path) -> list[dict]:
    """프로젝트 루트의 .claude/skills/ 스캔."""
    return _scan_skills_dir(project_root / ".claude" / "skills", "claude", project_root)


def list_vibe_skills(project_root: Path) -> list[dict]:
    """프로젝트 루트의 .vibe/skills/ 스캔."""
    return _scan_skills_dir(project_root / ".vibe" / "skills", "vibe", project_root)


def merge_skills(claude_list: list[dict], vibe_list: list[dict]) -> tuple[list[dict], list[dict]]:
    """.claude + .vibe 병합. 중복 이름은 .vibe 우선, 충돌 로그 반환.

    반환: (merged_list, conflicts)
    conflicts 항목: {"name": ..., "winner": "vibe", "loser_origin": "claude"}
    """
    merged: dict[str, dict] = {s["name"]: s for s in claude_list}
    conflicts: list[dict] = []
    for s in vibe_list:
        name = s["name"]
        if name in merged:
            conflicts.append({
                "name": name,
                "winner": "vibe",
                "loser_origin": merged[name]["origin"],
            })
        merged[name] = s

    # 정렬: origin 우선(vibe 먼저) → 이름 알파벳
    result = sorted(
        merged.values(),
        key=lambda s: (0 if s["origin"] == "vibe" else 1, s["name"]),
    )
    return result, conflicts


def scan_project_skills(project_root: Path) -> dict:
    """프로젝트 루트를 받아 병합된 스킬 목록 + 메타 정보를 반환."""
    claude = list_claude_skills(project_root)
    vibe = list_vibe_skills(project_root)
    merged, conflicts = merge_skills(claude, vibe)
    return {
        "project_root": str(project_root).replace("\\", "/"),
        "counts": {
            "claude": len(claude),
            "vibe": len(vibe),
            "merged": len(merged),
        },
        "skills": merged,
        "conflicts": conflicts,
    }


def handle_get(handler, path: str, params: dict,
               PROJECT_ROOT: Path) -> bool:
    """server.py의 GET 라우터에서 호출. True 반환 시 처리됨."""
    if path != "/api/vibe/skills":
        return False

    raw = params.get("project_root", [""])[0].strip()
    if raw:
        root = Path(raw)
        if not root.is_absolute():
            handler.send_response(400)
            handler.send_header("Content-Type", "application/json;charset=utf-8")
            handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
            handler.end_headers()
            handler.wfile.write(json.dumps(
                {"error": "project_root must be absolute path"},
                ensure_ascii=False,
            ).encode("utf-8"))
            return True
        if not root.exists():
            handler.send_response(404)
            handler.send_header("Content-Type", "application/json;charset=utf-8")
            handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
            handler.end_headers()
            handler.wfile.write(json.dumps(
                {"error": f"project_root not found: {root}"},
                ensure_ascii=False,
            ).encode("utf-8"))
            return True
    else:
        root = PROJECT_ROOT

    payload = scan_project_skills(root)

    handler.send_response(200)
    handler.send_header("Content-Type", "application/json;charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return True
