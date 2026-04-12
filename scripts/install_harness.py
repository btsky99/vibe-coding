"""
FILE: scripts/install_harness.py
DESCRIPTION: 하네스 V2 경량판 설치 스크립트.
             프로젝트에 AI 에이전트 품질 관리 인프라를 세팅한다.
             --component 인자로 개별 컴포넌트 설치 가능.

             [컴포넌트]
             hooks  — .claude/settings.json에 UserPromptSubmit/Stop 훅 설정
             rules  — CLAUDE.md + .claude/rules/ 기본 규칙 파일 스캐폴딩
             verify — scripts/harness_verify.py 경량 검증 스크립트 설치
             all    — 위 3개 전부

REVISION HISTORY:
- 2026-04-12 Claude: 최초 생성 — AI 도구 목록에서 원클릭 하네스 설치 지원
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _print(msg: str) -> None:
    print(msg, flush=True)


# ═══════════════════════════════════════════════════════════════════════
#  컴포넌트 1: Claude Code 훅 설정
# ═══════════════════════════════════════════════════════════════════════

# 경량 훅 템플릿 — 프로젝트 경로를 동적으로 주입
_HOOKS_TEMPLATE: dict = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python {project_root}/scripts/harness_verify.py 2>&1 | head -5",
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo [하네스] 작업 완료",
                    }
                ],
            }
        ],
    }
}


def install_hooks(project_root: Path) -> bool:
    """Claude Code 훅을 .claude/settings.json에 설정한다."""
    claude_dir = project_root / ".claude"
    settings_path = claude_dir / "settings.json"

    claude_dir.mkdir(parents=True, exist_ok=True)

    # 기존 설정 로드 (있으면)
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # 이미 hooks가 있으면 스킵
    if "hooks" in existing and existing["hooks"]:
        hook_count = sum(len(v) for v in existing["hooks"].values())
        _print(f"[OK] 훅이 이미 설정되어 있습니다 ({hook_count}개). 건너뜁니다.")
        _print(f"     위치: {settings_path}")
        return True

    # 훅 템플릿 적용 (경로를 현재 프로젝트로 치환)
    root_str = str(project_root).replace("\\", "/")
    hooks_json = json.dumps(_HOOKS_TEMPLATE)
    hooks_json = hooks_json.replace("{project_root}", root_str)
    hooks_data = json.loads(hooks_json)

    existing.update(hooks_data)

    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print(f"[OK] Claude Code 훅 설정 완료")
    _print(f"     위치: {settings_path}")
    return True


# ═══════════════════════════════════════════════════════════════════════
#  컴포넌트 2: 프로젝트 규칙 파일
# ═══════════════════════════════════════════════════════════════════════

_CLAUDE_MD_TEMPLATE = """\
# CLAUDE.md

## 핵심 규칙

- **한글 필수**: 주석, 커밋 본문, 대화 출력 모두 한글
- **커밋**: Conventional Commits + 한글 본문

## 빌드 및 실행

```bash
# TODO: 프로젝트에 맞게 수정
pip install -e .
python -m pytest tests/
```

## 작업 완료 리포트 (필수)

- **수정/생성된 파일:** (경로 나열)
- **원인 (Why):** (1줄 요약)
- **수정 내용 (How):** (1~2줄 요약)
"""

_COMMIT_RULES_TEMPLATE = """\
## Git 커밋 메시지 규칙

Conventional Commits 형식 + 한글 본문 필수.

### 타입
| 타입 | 용도 |
|------|------|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 동작 변경 없는 구조 개선 |
| `docs` | 문서·주석 변경 |
| `chore` | 그 외 (설정, 의존성 등) |

### 필수 템플릿
```
<type>(<scope>): <한글 요약 — 50자 이내>

## 변경 이유 (Why)
배경과 근본 원인 설명.

## 변경 내용 (What)
- 파일명 — 구체적 변경 사항

## 영향 범위 (Impact)
다른 기능에 미치는 영향 (없으면 "없음" 명시)
```
"""


def install_rules(project_root: Path) -> bool:
    """CLAUDE.md + .claude/rules/ 규칙 파일을 스캐폴딩한다."""
    claude_md = project_root / "CLAUDE.md"
    rules_dir = project_root / ".claude" / "rules"

    # CLAUDE.md
    if claude_md.exists():
        _print(f"[OK] CLAUDE.md 이미 존재합니다. 건너뜁니다.")
    else:
        claude_md.write_text(_CLAUDE_MD_TEMPLATE, encoding="utf-8")
        _print(f"[OK] CLAUDE.md 생성 완료")

    # .claude/rules/
    rules_dir.mkdir(parents=True, exist_ok=True)

    commit_rules = rules_dir / "commit-rules.md"
    if commit_rules.exists():
        _print(f"[OK] commit-rules.md 이미 존재합니다. 건너뜁니다.")
    else:
        commit_rules.write_text(_COMMIT_RULES_TEMPLATE, encoding="utf-8")
        _print(f"[OK] .claude/rules/commit-rules.md 생성 완료")

    return True


# ═══════════════════════════════════════════════════════════════════════
#  컴포넌트 3: 검증 스크립트
# ═══════════════════════════════════════════════════════════════════════

_VERIFY_LITE_TEMPLATE = '''\
"""
FILE: scripts/harness_verify.py
DESCRIPTION: 하네스 경량 검증 스크립트. 프로젝트 기본 구조를 검사한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def verify() -> dict[str, list[str]]:
    passes, warnings, errors = [], [], []

    # 필수 문서
    for doc in ["CLAUDE.md"]:
        p = PROJECT_ROOT / doc
        if p.exists():
            passes.append(f"required-doc:{doc}")
        else:
            errors.append(f"required-doc-missing:{doc}")

    # .claude/settings.json 훅 확인
    settings = PROJECT_ROOT / ".claude" / "settings.json"
    if settings.exists():
        try:
            d = json.loads(settings.read_text(encoding="utf-8"))
            if d.get("hooks"):
                passes.append("hooks:configured")
            else:
                warnings.append("hooks:empty")
        except Exception:
            warnings.append("hooks:parse-error")
    else:
        warnings.append("hooks:missing")

    # .claude/rules/ 존재
    rules_dir = PROJECT_ROOT / ".claude" / "rules"
    if rules_dir.is_dir() and any(rules_dir.iterdir()):
        passes.append("rules:configured")
    else:
        warnings.append("rules:missing")

    return {"passes": passes, "warnings": warnings, "errors": errors}


def main() -> int:
    result = verify()
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
    total = len(result["passes"])
    print(f"[HARNESS V2] status=ok ({total} checks passed, {len(result[\\'warnings\\'])} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def install_verify(project_root: Path) -> bool:
    """경량 harness_verify.py를 scripts/에 설치한다."""
    scripts_dir = project_root / "scripts"
    verify_path = scripts_dir / "harness_verify.py"

    if verify_path.exists():
        _print(f"[OK] harness_verify.py 이미 존재합니다. 건너뜁니다.")
        return True

    scripts_dir.mkdir(parents=True, exist_ok=True)

    # 이스케이프 해제
    content = _VERIFY_LITE_TEMPLATE.replace("\\'", "'")
    verify_path.write_text(content, encoding="utf-8")
    _print(f"[OK] scripts/harness_verify.py 설치 완료 (경량판)")
    return True


# ═══════════════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description="하네스 V2 경량판 설치")
    parser.add_argument(
        "--component",
        choices=["hooks", "rules", "verify", "all"],
        default="all",
        help="설치할 컴포넌트 (기본: all)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="프로젝트 루트 경로 (기본: 스크립트 상위 디렉토리)",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    _print(f"")
    _print(f"═══ 하네스 V2 경량판 설치 ═══")
    _print(f"프로젝트: {root}")
    _print(f"컴포넌트: {args.component}")
    _print(f"")

    ok = True
    if args.component in ("hooks", "all"):
        ok = install_hooks(root) and ok
    if args.component in ("rules", "all"):
        ok = install_rules(root) and ok
    if args.component in ("verify", "all"):
        ok = install_verify(root) and ok

    _print(f"")
    if ok:
        _print(f"═══ 설치 완료 ═══")
    else:
        _print(f"═══ 일부 실패 — 위 로그를 확인하세요 ═══")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
