"""
FILE: scripts/harness_verify.py
DESCRIPTION: Vibe Coding 하네스 V2 검증 스크립트.
             Claude, Gemini, Codex 모든 에이전트가 공통 하네스 규칙을 준수하는지 기계적으로 검사한다.

             [V2 검사 항목 — 10개]
             1. required-doc        : 필수 문서 존재 확인
             2. agents-too-long     : AGENTS.md 120줄 제한
             3. agents-link-missing : 필수 참조 링크 확인
             4. guide-link-missing  : 에이전트 가이드 내 필수 링크
             5. runtime-path-missing: 핵심 런타임 스크립트 존재
             6. hot-file-large      : 주요 파일 크기 초과 경고
             7. feature-list        : feature_list.json 존재 및 스키마 검증
             8. progress-stale      : progress.md 갱신 주기 확인
             9. self-eval-detected  : Generator=Evaluator 동일 에이전트 탐지
             10. contract-missing   : P0/P1 활성 작업에 스프린트 계약 존재 확인

             [사용법]
             python scripts/harness_verify.py          # 일반 모드
             python scripts/harness_verify.py --ci     # CI 모드 (에러 시 exit 1)
             python scripts/harness_verify.py --json   # JSON 출력

REVISION HISTORY:
- 2026-03-29 Codex: 신규 생성 — V1 하네스 구조 검증 (5개 검사)
- 2026-03-30 Claude: V2 업그레이드 — Anthropic 블로그 기반 10개 검사로 확장
  - feature_list.json 스키마 검증 추가
  - progress.md 갱신 주기 검사 추가
  - Generator-Evaluator 분리 위반 탐지 추가
  - 스프린트 계약 존재 확인 추가
  - JSON 출력 모드 추가
- 2026-04-19 Claude: 어제 UI 대청소(커밋 37d8266, 83cee44) 반영
  - REQUIRED_RUNTIME_FILES에서 auto_dispatcher.py 제거 (디스패처 폐기)
  - HOT_FILE_THRESHOLDS에서 AgentPanel.tsx 제거 (AgentPanel 폐기)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── V1 검사 설정 (유지) ──────────────────────────────────────────

REQUIRED_DOCS = [
    "AGENTS.md",
    "RULES.md",
    "PROJECT_MAP.md",
    "docs/HARNESS_V2.md",
    "docs/HARNESS_CHECKS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CODEX_GUIDE.md",
]

AGENTS_REQUIRED_LINKS = [
    "RULES.md",
    "HARNESS_V2.md",
    "HARNESS_CHECKS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CODEX_GUIDE.md",
]

AGENT_GUIDE_REQUIREMENTS = {
    "CLAUDE.md": ["RULES.md", "HARNESS_V2.md"],
    "GEMINI.md": ["RULES.md", "HARNESS_V2.md"],
    "CODEX_GUIDE.md": ["HARNESS_V2.md"],
}

REQUIRED_RUNTIME_FILES = [
    "scripts/harness_verify.py",
    "scripts/itcp.py",
    "feature_list.json",
    "progress.md",
]

HOT_FILE_THRESHOLDS = {
    ".ai_monitor/server.py": 5000,
    ".ai_monitor/vibe-view/src/components/TerminalSlot.tsx": 1200,
    ".ai_monitor/vibe-view/src/App.tsx": 1200,
}

# ── V2 검사 설정 (신규) ──────────────────────────────────────────

# feature_list.json에서 각 feature 객체에 반드시 있어야 하는 필드
FEATURE_REQUIRED_FIELDS = [
    "id", "category", "priority", "description",
    "acceptance_criteria", "assigned_to", "evaluated_by", "passes",
]

# 유효한 category 값
VALID_CATEGORIES = {"functional", "visual", "performance", "security"}

# 유효한 priority 값
VALID_PRIORITIES = {"P0", "P1", "P2"}

# progress.md 최대 미갱신 허용 일수
PROGRESS_STALE_DAYS = 3


def _read_text(path: Path) -> str:
    """파일을 UTF-8로 읽어 텍스트 반환"""
    return path.read_text(encoding="utf-8")


def _line_count(path: Path) -> int:
    """파일의 줄 수 반환"""
    return len(_read_text(path).splitlines())


def _check_required_docs(root: Path, passes: list, errors: list) -> None:
    """[검사 1] 필수 문서 존재 확인"""
    for rel_path in REQUIRED_DOCS:
        path = root / rel_path
        if path.exists():
            passes.append(f"required-doc:{rel_path}")
        else:
            errors.append(f"required-doc-missing:{rel_path}")


def _check_agents_md(root: Path, passes: list, errors: list) -> None:
    """[검사 2, 3] AGENTS.md 줄 수 제한 + 필수 링크 확인"""
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        return

    line_count = _line_count(agents_path)
    if line_count > 120:
        errors.append(f"agents-too-long:{line_count}")
    else:
        passes.append(f"agents-line-count:{line_count}")

    agents_text = _read_text(agents_path)
    for token in AGENTS_REQUIRED_LINKS:
        if token in agents_text:
            passes.append(f"agents-link:{token}")
        else:
            errors.append(f"agents-link-missing:{token}")


def _check_guide_links(root: Path, passes: list, errors: list) -> None:
    """[검사 4] 에이전트 가이드 내 필수 링크 확인"""
    for rel_path, tokens in AGENT_GUIDE_REQUIREMENTS.items():
        guide_path = root / rel_path
        if not guide_path.exists():
            continue
        guide_text = _read_text(guide_path)
        for token in tokens:
            if token in guide_text:
                passes.append(f"guide-link:{rel_path}:{token}")
            else:
                errors.append(f"guide-link-missing:{rel_path}:{token}")


def _check_runtime_files(root: Path, passes: list, errors: list) -> None:
    """[검사 5] 핵심 런타임 스크립트 존재 확인"""
    for rel_path in REQUIRED_RUNTIME_FILES:
        path = root / rel_path
        if path.exists():
            passes.append(f"runtime-path:{rel_path}")
        else:
            errors.append(f"runtime-path-missing:{rel_path}")


def _check_hot_files(root: Path, passes: list, warnings: list) -> None:
    """[검사 6] 주요 파일 크기 초과 경고"""
    for rel_path, threshold in HOT_FILE_THRESHOLDS.items():
        path = root / rel_path
        if not path.exists():
            warnings.append(f"hot-file-missing:{rel_path}")
            continue
        count = _line_count(path)
        if count > threshold:
            warnings.append(f"hot-file-large:{rel_path}:{count}>{threshold}")
        else:
            passes.append(f"hot-file-ok:{rel_path}:{count}")


def _check_feature_list(root: Path, passes: list, warnings: list, errors: list) -> dict | None:
    """[검사 7] feature_list.json 존재 및 스키마 검증
    반환값: 파싱된 feature_list 딕셔너리 (다른 검사에서 재활용)
    """
    fl_path = root / "feature_list.json"
    if not fl_path.exists():
        errors.append("feature-list-missing")
        return None

    try:
        data = json.loads(_read_text(fl_path))
    except json.JSONDecodeError as e:
        errors.append(f"feature-list-invalid-json:{e}")
        return None

    # 최상위 필수 필드
    for field in ("version", "features"):
        if field not in data:
            errors.append(f"feature-list-missing-field:{field}")
            return data

    features = data.get("features", [])
    if not isinstance(features, list):
        errors.append("feature-list-features-not-array")
        return data

    schema_ok = True
    for i, feat in enumerate(features):
        for field in FEATURE_REQUIRED_FIELDS:
            if field not in feat:
                errors.append(f"feature-list-schema:{feat.get('id', f'index-{i}')}:missing-{field}")
                schema_ok = False

        # category 값 검증
        cat = feat.get("category", "")
        if cat and cat not in VALID_CATEGORIES:
            warnings.append(f"feature-list-category:{feat.get('id')}:{cat}")

        # priority 값 검증
        pri = feat.get("priority", "")
        if pri and pri not in VALID_PRIORITIES:
            warnings.append(f"feature-list-priority:{feat.get('id')}:{pri}")

    if schema_ok:
        passes.append(f"feature-list-schema:ok:{len(features)}-features")

    return data


def _check_progress_stale(root: Path, passes: list, warnings: list) -> None:
    """[검사 8] progress.md 갱신 주기 확인 (최대 3일)"""
    prog_path = root / "progress.md"
    if not prog_path.exists():
        warnings.append("progress-missing")
        return

    text = _read_text(prog_path)

    # "최종 업데이트: YYYY-MM-DD" 패턴에서 날짜 추출
    import re
    match = re.search(r"최종 업데이트:\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        warnings.append("progress-no-date")
        return

    try:
        last_date = datetime.strptime(match.group(1), "%Y-%m-%d")
        days_ago = (datetime.now() - last_date).days
        if days_ago > PROGRESS_STALE_DAYS:
            warnings.append(f"progress-stale:{days_ago}days")
        else:
            passes.append(f"progress-fresh:{days_ago}days")
    except ValueError:
        warnings.append("progress-invalid-date")


def _check_self_eval(feature_data: dict | None, passes: list, warnings: list) -> None:
    """[검사 9] Generator=Evaluator 동일 에이전트 탐지
    feature_list.json에서 assigned_to == evaluated_by인 경우를 찾는다.
    """
    if not feature_data or "features" not in feature_data:
        return

    for feat in feature_data["features"]:
        assigned = feat.get("assigned_to")
        evaluated = feat.get("evaluated_by")
        fid = feat.get("id", "?")

        # 둘 다 설정되어 있고, 동일 에이전트인 경우
        if assigned and evaluated and assigned == evaluated:
            warnings.append(f"self-eval-detected:{fid}:{assigned}")
        elif assigned and evaluated and assigned != evaluated:
            passes.append(f"eval-separated:{fid}:{assigned}->{evaluated}")


def _check_sprint_contracts(root: Path, feature_data: dict | None, passes: list, warnings: list) -> None:
    """[검사 10] P0/P1 활성(passes=false) 작업에 스프린트 계약 존재 확인"""
    if not feature_data or "features" not in feature_data:
        return

    contracts_dir = root / "sprint_contracts"
    has_contracts_dir = contracts_dir.exists() and contracts_dir.is_dir()

    for feat in feature_data["features"]:
        fid = feat.get("id", "?")
        priority = feat.get("priority", "P2")
        is_passing = feat.get("passes", False)

        # P0/P1이면서 아직 미완성인 기능만 검사
        if priority in ("P0", "P1") and not is_passing:
            if not has_contracts_dir:
                warnings.append(f"contract-missing:{fid}:no-contracts-dir")
                continue

            # sprint_FXXX_*.md 패턴 검색
            contracts = list(contracts_dir.glob(f"sprint_{fid}_*.md"))
            if contracts:
                passes.append(f"contract-exists:{fid}")
            else:
                warnings.append(f"contract-missing:{fid}")


def verify_repository(root: Path) -> dict[str, list[str]]:
    """프로젝트 루트를 기준으로 하네스 V2 검증을 수행한다.
    반환: {"passes": [...], "warnings": [...], "errors": [...]}
    """
    passes: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    # V1 검사 (1~6)
    _check_required_docs(root, passes, errors)
    _check_agents_md(root, passes, errors)
    _check_guide_links(root, passes, errors)
    _check_runtime_files(root, passes, errors)
    _check_hot_files(root, passes, warnings)

    # V2 검사 (7~10)
    feature_data = _check_feature_list(root, passes, warnings, errors)
    _check_progress_stale(root, passes, warnings)
    _check_self_eval(feature_data, passes, warnings)
    _check_sprint_contracts(root, feature_data, passes, warnings)

    return {
        "passes": passes,
        "warnings": warnings,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vibe Coding 하네스 V2 구조 검증")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI 모드. 에러 시 exit 1을 반환합니다.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="결과를 JSON으로 출력합니다.",
    )
    args = parser.parse_args(argv)

    result = verify_repository(PROJECT_ROOT)

    # JSON 출력 모드
    if args.json:
        output = {
            "harness_version": "2.0",
            "status": "ok" if not result["errors"] else "fail",
            "summary": {
                "passes": len(result["passes"]),
                "warnings": len(result["warnings"]),
                "errors": len(result["errors"]),
            },
            "details": result,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0

    # 일반 텍스트 출력 모드
    print("[HARNESS V2] passes")
    for item in result["passes"]:
        print(f"  OK   {item}")

    if result["warnings"]:
        print("[HARNESS V2] warnings")
        for item in result["warnings"]:
            print(f"  WARN {item}")

    if result["errors"]:
        print("[HARNESS V2] errors")
        for item in result["errors"]:
            print(f"  FAIL {item}")
        return 1

    print(f"[HARNESS V2] status=ok ({len(result['passes'])} checks passed)")
    if args.ci:
        print("[HARNESS V2] ci=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
