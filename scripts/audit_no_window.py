# -*- coding: utf-8 -*-
"""
FILE: scripts/audit_no_window.py
DESCRIPTION: 규칙 10 정적 감사 — "사람이 안 시킨 실행"이 콘솔 창을 띄울 수 있는 지점을 찾는다.
             infra.proc 를 거치지 않은 subprocess 직접 호출과 shell=True 를 AST 로 훑는다.

             [🔴 왜 grep 이 아니라 AST 인가] `subprocess.run(` 을 grep 하면 주석·문자열·
               변수명까지 걸려 노이즈가 절반이다. 더 나쁜 건 반대 방향인데, 인자가 여러 줄로
               나뉜 호출에서 `creationflags=` 가 다음 줄에 있으면 grep 은 '위반'으로 오판한다.
               AST 는 호출 노드 하나로 보므로 줄바꿈에 영향받지 않는다.

             [🔴 utf-8-sig 로 읽는다 — 과거사고] 예전 스캐너를 utf-8 로 열었더니 BOM 붙은
               파일에서 첫 줄이 깨져 SyntaxError 로 떨어졌고, 그 파일들이 '검사 통과'로
               조용히 빠졌다. 빠진 줄도 몰랐던 게 진짜 문제다.

             [WHY 자동/수동을 가르나] 규칙 10 의 대상은 '사람이 누르지 않은 실행'이다.
               빌드 스크립트나 CLI 도구는 사람이 직접 띄우므로 창이 떠도 사고가 아니다.
               섞어서 보고하면 진짜 위반이 노이즈에 묻힌다.

             사용법:
               python scripts/audit_no_window.py           # 자동 실행 경로만 (기본)
               python scripts/audit_no_window.py --all     # 수동 실행 스크립트까지

REVISION HISTORY:
- 2026-08-15 Claude: 최초 작성 — "콘솔 창이 자꾸 뜬다" 조사 중 바이브 코딩 쪽 결백 검증용
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 창 없이 도는 것이 보장돼야 하는 경로.
# [WHY 경로로 가르나] '자동 실행'은 코드만 봐서는 판정할 수 없다 — 데몬 스레드에서 불리는지
#   사람이 CLI 로 부르는지는 호출자 쪽 사실이다. 디렉토리 관례가 가장 싼 근사치다.
AUTO_PATHS = (
    '.ai_monitor/infra/',
    '.ai_monitor/api/',
    '.ai_monitor/src/',
    '.ai_monitor/server.py',
    'scripts/hive_hook.py',
    'scripts/claude_hook.py',
    'scripts/antigravity_hook.py',
    'scripts/hive_watchdog.py',
    'scripts/claude_watchdog.py',
    'scripts/orchestrator.py',
    'scripts/codex_pg_watcher.py',
)

SKIP_DIRS = {'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__',
             '.git', 'vibe-view', 'voice-server'}

# [🔴 래퍼 자신은 대상이 아니다] infra/proc.py 는 subprocess 를 직접 부르는 것이 존재 이유다.
#   빼지 않으면 감사 결과에 영구 오탐 2건이 박혀, 보는 사람이 '원래 그런가 보다' 하고
#   목록 전체를 안 믿게 된다. 오탐 하나가 도구 전체의 신뢰를 깎는다.
SKIP_FILES = {'.ai_monitor/infra/proc.py'}

DANGEROUS = {'run', 'Popen', 'call', 'check_call', 'check_output'}

# 사람이 보라고 일부러 여는 터미널. [WHY 가르나] `start "제목" cmd.exe /k` 는 설치 진행이나
#   CLI 실행을 사용자에게 보여주는 창이라, 창이 뜨는 것이 곧 기능이다. 규칙 10 의 대상은
#   '사람이 누르지 않은 실행'이므로 이건 위반이 아니다 — 섞으면 진짜 위반이 묻힌다.
INTENTIONAL_MARKERS = ('start "', 'cmd.exe /k', 'cmd /k')


def _is_auto(rel: str) -> bool:
    return any(rel.replace('\\', '/').startswith(p) for p in AUTO_PATHS)


def _looks_intentional(node: ast.Call, src_lines: list[str]) -> bool:
    """이 호출이 '사람에게 보여주려고 여는 터미널'인가."""
    lo = max(0, node.lineno - 12)
    hi = min(len(src_lines), (node.end_lineno or node.lineno) + 1)
    chunk = '\n'.join(src_lines[lo:hi])
    return any(m in chunk for m in INTENTIONAL_MARKERS)


class Visitor(ast.NodeVisitor):
    """[등급] 🔴 위반 / 🟡 확인 / ⚪ 의도적 — 셋을 섞지 않는다."""

    def __init__(self, rel: str, src_lines: list[str]) -> None:
        self.rel = rel
        self.src_lines = src_lines
        self.hits: list[tuple[int, str, str, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        f = node.func
        target = ''
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == 'subprocess' and f.attr in DANGEROUS:
                target = f'subprocess.{f.attr}'
        kw = {k.arg for k in node.keywords if k.arg}
        shell_true = any(
            k.arg == 'shell' and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in node.keywords
        )
        intentional = _looks_intentional(node, self.src_lines)
        name = target or (f.attr if isinstance(f, ast.Attribute) else '?')

        if intentional and (target or shell_true):
            self.hits.append(('⚪', node.lineno, name, '사람에게 보여주는 터미널 — 규칙 10 대상 아님'))
        elif target and 'creationflags' not in kw:
            self.hits.append(('🔴', node.lineno, name, 'infra.proc 미경유 + creationflags 없음'))
        elif shell_true:
            # [🔴 왜 shell=True 가 따로 걸리나] CREATE_NO_WINDOW 는 **자식에게 상속되지 않는다**.
            #   cmd.exe 창은 막히지만 그 안에서 실행되는 말단(git·psql·ssh)은 새 콘솔을 받는다.
            #   과거 사고 2건이 정확히 이 지점이었다(d423a7d, 2026-08-14).
            self.hits.append(('🟡', node.lineno, name,
                              'shell=True — 말단 자식은 CREATE_NO_WINDOW 를 못 물려받는다'))
        elif target and _is_auto(self.rel):
            self.hits.append(('⚪', node.lineno, name, 'creationflags 직접 지정'))
        self.generic_visit(node)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='수동 실행 스크립트까지 포함')
    args = ap.parse_args()

    findings: list[tuple[str, str, int, str, str]] = []
    unreadable: list[str] = []
    scanned = 0

    for path in ROOT.rglob('*.py'):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(ROOT)).replace('\\', '/')
        if rel in SKIP_FILES:
            continue
        if not args.all and not _is_auto(rel):
            continue
        try:
            src = path.read_text(encoding='utf-8-sig')   # [🔴] BOM 파일을 빠뜨리지 않는다
            tree = ast.parse(src)
        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            unreadable.append(f'{rel}: {type(e).__name__}')
            continue
        scanned += 1
        v = Visitor(rel, src.splitlines())
        v.visit(tree)
        for grade, lineno, target, why in v.hits:
            findings.append((grade, rel, lineno, target, why))

    print(f'검사한 파일: {scanned}개'
          f"{'  (자동 실행 경로만)' if not args.all else '  (전체)'}")
    if unreadable:
        # [🔴 조용히 빠뜨리지 않는다] 못 읽은 파일을 안 알리면 '위반 0건'이 거짓말이 된다.
        print(f'읽지 못한 파일 {len(unreadable)}개: ' + ', '.join(unreadable[:5]))

    for grade, title in (('🔴', '위반'), ('🟡', '확인 필요'), ('⚪', '의도적 — 문제 없음')):
        rows = [f for f in findings if f[0] == grade]
        print(f'\n{grade} {title}: {len(rows)}건')
        for _g, rel, lineno, target, why in sorted(rows, key=lambda r: (r[1], r[2])):
            print(f'  {rel}:{lineno}  {target}  — {why}')

    return 1 if any(f[0] == '🔴' for f in findings) else 0


if __name__ == '__main__':
    sys.exit(main())
