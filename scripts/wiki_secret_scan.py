# -*- coding: utf-8 -*-
"""
FILE: scripts/wiki_secret_scan.py
DESCRIPTION: 위키(.md)에 비밀 값이 섞여 들어가는 것을 커밋 전에 막는다.

             [🔴 왜 커밋 '전' 이어야 하나 — 2026-08-18 경량화 3단계]
               위키를 깃에 백업하기로 정했다(사장 지시). 그런데 깃은 **지운 것도 기억한다** —
               토큰이 한 번 들어가면 나중에 그 줄을 지워도 히스토리에 영원히 남고,
               되돌리려면 히스토리 재작성(--force)뿐인데 그건 이 저장소가 금지한 것이다.
               즉 **막을 수 있는 유일한 지점이 커밋 직전**이다.

             [WHY 정규식 몇 개뿐인가] 완벽한 탐지기를 만들려는 것이 아니다. 위키에 실제로
               섞일 만한 모양(토큰·키·비밀번호 줄)만 잡는다. 넓게 잡으면 오탐이 늘고,
               오탐이 늘면 사람이 --no-verify 로 우회하기 시작한다 — 그때부터 이 장치는 0이다.

             [사용]
               python scripts/wiki_secret_scan.py            # wiki/ 전체
               python scripts/wiki_secret_scan.py --staged   # 커밋 예정분만 (훅이 쓰는 길)
               종료코드 0=깨끗함, 1=의심 발견(커밋 중단)

REVISION HISTORY:
- 2026-08-18 Claude: 최초 작성 — 위키 깃 백업 결정(사장 지시)에 딸린 안전장치.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / 'wiki'

# [🔴 모양으로 잡는다, 이름으로 잡지 않는다] "password" 라는 낱말이 든 문장은 설명일 때가
#   훨씬 많다. 값처럼 생긴 것만 잡아야 오탐이 안 는다.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ('GitHub 토큰',      re.compile(r'\bgh[pousr]_[A-Za-z0-9]{16,}')),
    ('OpenAI 계열 키',   re.compile(r'\bsk-[A-Za-z0-9_-]{20,}')),
    ('Anthropic 키',     re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}')),
    ('AWS 액세스 키',    re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('Slack 토큰',       re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}')),
    ('Google API 키',    re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b')),
    # [🔴 줄 맨 앞에 있을 때만 — 2026-08-18 오탐 1건] 진짜 키 블록은 이 마커가 **제 줄**을
    #   차지한다. 문장 가운데 끼어 있으면 그건 설명이다(실제로 `wiki/시스템/다른 프로젝트.md`
    #   의 355자짜리 산문 한 줄이 걸렸다 — 뒤따르는 base64 본문이 없었다).
    #   오탐이 쌓이면 사람이 --no-verify 로 우회하기 시작하고, 그때부터 이 장치는 0이다.
    ('개인 키 블록',     re.compile(r'^\s*-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    # 값이 실제로 붙어 있는 줄만. 빈 값·자리표시자(<...>, ***, xxx)는 넘긴다.
    ('비밀번호/토큰 대입',
     re.compile(r'(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*'
                r'(?!["\']?(?:<|\*{3,}|x{3,}|여기|없음|\.\.\.)|["\']?\s*$)'
                r'["\']?[A-Za-z0-9_\-./+]{8,}')),
]


def _targets(staged: bool) -> list[Path]:
    if not staged:
        return sorted(WIKI.rglob('*.md')) if WIKI.is_dir() else []
    out = subprocess.run(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout
    files = []
    for rel in out.splitlines():
        rel = rel.strip()
        # [제약] 위키만 본다. 코드·설정은 이 훅의 몫이 아니다(각자 다른 검사가 있다).
        if rel.startswith('wiki/') and rel.endswith('.md'):
            p = ROOT / rel
            if p.is_file():
                files.append(p)
    return files


def scan(staged: bool = False) -> int:
    hits = []
    for path in _targets(staged):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pat in PATTERNS:
                if pat.search(line):
                    # [🔴 값 자체를 찍지 않는다] 화면·로그에 남기면 막으려던 것을 우리가 흘린다.
                    hits.append((path.relative_to(ROOT).as_posix(), lineno, label))
                    break
    if not hits:
        print(f'[wiki-secret] 깨끗함 ({len(_targets(staged))}개 파일 검사)')
        return 0
    print('[wiki-secret] 🔴 비밀 값으로 보이는 것이 있습니다 — 커밋을 멈춥니다.')
    print('  깃은 지운 것도 기억합니다. 지금 빼는 것이 유일한 기회입니다.')
    for f, ln, label in hits:
        print(f'   {f}:{ln}  ({label})')
    print('  오탐이면 그 줄을 바꿔 쓰거나(값 대신 "있음/없음"), 검사 규칙을 고치세요.')
    return 1


if __name__ == '__main__':
    sys.exit(scan(staged='--staged' in sys.argv))
