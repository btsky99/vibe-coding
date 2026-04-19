"""
FILE: tests/test_harness_verify.py
DESCRIPTION: harness_verify.py V2 검증 스크립트의 단위 테스트.
             V1 검사(문서 구조)와 V2 검사(feature_list, progress, self-eval, contract)를 모두 커버.

REVISION HISTORY:
- 2026-03-29 Codex: 최초 생성 — V1 검사 3개 테스트
- 2026-03-30 Claude: V2 업그레이드 — V2 검사 항목 테스트 추가
"""

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import harness_verify


def _write(root: Path, rel_path: str, content: str = "") -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_minimal_repo(root: Path) -> None:
    """V2 하네스를 통과하는 최소 리포지토리 구조를 생성한다."""
    _write(
        root,
        "AGENTS.md",
        "\n".join([
            "# AGENTS",
            "RULES.md",
            "HARNESS_V2.md",
            "HARNESS_CHECKS.md",
            "CLAUDE.md",
            "GEMINI.md",
            "CODEX_GUIDE.md",
        ]),
    )
    _write(root, "RULES.md", "# rules")
    _write(root, "PROJECT_MAP.md", "# map")
    _write(root, "docs/HARNESS_V2.md", "# harness v2")
    _write(root, "docs/HARNESS_CHECKS.md", "# checks")
    _write(root, "CLAUDE.md", "RULES.md\nHARNESS_V2.md")
    _write(root, "GEMINI.md", "RULES.md\nHARNESS_V2.md")
    _write(root, "CODEX_GUIDE.md", "HARNESS_V2.md")
    _write(root, "scripts/harness_verify.py", "print('ok')\n")
    _write(root, "scripts/itcp.py", "print('ok')\n")
    _write(root, ".ai_monitor/server.py", "print('ok')\n")
    _write(root, ".ai_monitor/vibe-view/src/components/TerminalSlot.tsx", "export {};\n")
    _write(root, ".ai_monitor/vibe-view/src/App.tsx", "export {};\n")

    # V2 필수 파일
    _write(root, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {
                "id": "F001",
                "category": "functional",
                "priority": "P2",
                "description": "테스트 기능",
                "acceptance_criteria": ["동작한다"],
                "assigned_to": "claude",
                "evaluated_by": "gemini",
                "passes": True,
            }
        ]
    }, ensure_ascii=False))
    _write(root, "progress.md", "# Progress\n\n## 최종 업데이트: 2026-03-30 by Claude\n")


# ── V1 검사 테스트 ──────────────────────────────────────────────

def test_verify_passes_for_minimal_v2_repo(tmp_path):
    """최소 V2 리포지토리가 에러 없이 통과한다."""
    _seed_minimal_repo(tmp_path)
    result = harness_verify.verify_repository(tmp_path)
    assert result["errors"] == []


def test_verify_fails_when_guide_loses_harness_link(tmp_path):
    """에이전트 가이드에서 HARNESS_V2.md 링크가 빠지면 에러."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "CLAUDE.md", "RULES.md only")
    result = harness_verify.verify_repository(tmp_path)
    assert any(
        item == "guide-link-missing:CLAUDE.md:HARNESS_V2.md"
        for item in result["errors"]
    )


def test_verify_warns_for_large_hot_files(tmp_path):
    """핫 파일이 임계값을 초과하면 경고."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, ".ai_monitor/server.py", "\n".join(["x"] * 5001))
    result = harness_verify.verify_repository(tmp_path)
    assert any(
        item.startswith("hot-file-large:.ai_monitor/server.py:")
        for item in result["warnings"]
    )


# ── V2 검사 테스트 ──────────────────────────────────────────────

def test_verify_fails_when_feature_list_missing(tmp_path):
    """feature_list.json이 없으면 에러."""
    _seed_minimal_repo(tmp_path)
    (tmp_path / "feature_list.json").unlink()
    result = harness_verify.verify_repository(tmp_path)
    assert any("feature-list-missing" in item or "runtime-path-missing:feature_list.json" in item
               for item in result["errors"])


def test_verify_fails_when_feature_list_has_bad_schema(tmp_path):
    """feature_list.json에 필수 필드가 없으면 에러."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {"id": "F001", "description": "incomplete"}
            # category, priority, acceptance_criteria, assigned_to, evaluated_by, passes 누락
        ]
    }))
    result = harness_verify.verify_repository(tmp_path)
    assert any("feature-list-schema" in item for item in result["errors"])


def test_verify_warns_self_eval_detected(tmp_path):
    """Generator=Evaluator 동일하면 경고."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {
                "id": "F001",
                "category": "functional",
                "priority": "P1",
                "description": "테스트",
                "acceptance_criteria": ["ok"],
                "assigned_to": "claude",
                "evaluated_by": "claude",  # 자기 평가!
                "passes": False,
            }
        ]
    }))
    result = harness_verify.verify_repository(tmp_path)
    assert any("self-eval-detected" in item for item in result["warnings"])


def test_verify_passes_eval_separated(tmp_path):
    """Generator ≠ Evaluator이면 정상."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {
                "id": "F001",
                "category": "functional",
                "priority": "P1",
                "description": "테스트",
                "acceptance_criteria": ["ok"],
                "assigned_to": "claude",
                "evaluated_by": "gemini",  # 분리됨
                "passes": False,
            }
        ]
    }))
    result = harness_verify.verify_repository(tmp_path)
    assert any("eval-separated" in item for item in result["passes"])


def test_verify_warns_contract_missing_for_active_p0(tmp_path):
    """P0/P1 미완성 기능에 스프린트 계약이 없으면 경고."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {
                "id": "F001",
                "category": "functional",
                "priority": "P0",
                "description": "중요 기능",
                "acceptance_criteria": ["ok"],
                "assigned_to": "claude",
                "evaluated_by": "gemini",
                "passes": False,  # 미완성
            }
        ]
    }))
    result = harness_verify.verify_repository(tmp_path)
    assert any("contract-missing:F001" in item for item in result["warnings"])


def test_verify_passes_contract_exists(tmp_path):
    """스프린트 계약이 있으면 정상."""
    _seed_minimal_repo(tmp_path)
    _write(tmp_path, "feature_list.json", json.dumps({
        "version": "2.0",
        "features": [
            {
                "id": "F001",
                "category": "functional",
                "priority": "P0",
                "description": "중요 기능",
                "acceptance_criteria": ["ok"],
                "assigned_to": "claude",
                "evaluated_by": "gemini",
                "passes": False,
            }
        ]
    }))
    _write(tmp_path, "sprint_contracts/sprint_F001_20260330.md", "# Contract")
    result = harness_verify.verify_repository(tmp_path)
    assert any("contract-exists:F001" in item for item in result["passes"])
