#!/usr/bin/env python3
"""
FILE: scripts/fix_corrupted_titles.py
DESCRIPTION: YAML 이스케이프 누적으로 백슬래시가 뭉개진 제텔 노트 제목을 복구한다.
             제목만 손상되고 본문(content)에는 원문이 남아 있는 성질을 이용해 되살린다.

             [🔴 사고 2026-08-08] zettel_sync의 export(_escape_yaml)가 백슬래시를 먼저
             이스케이프하지 않고, import(_parse_frontmatter)에 unescape가 없어서
             export↔import 왕복마다 따옴표 앞 백슬래시가 누적됐다.
             그 결과 제목이 의미를 잃고, 해당 노트의 임베딩이 **아무 질의에나 0.6대로
             매칭되는 회상 노이즈**가 됐다(최악 1건 참조 309회).
             근본 수정은 zettel_sync.py에 있고, 이 스크립트는 이미 오염된 데이터 복구용이다.

사용:
  python scripts/fix_corrupted_titles.py --check   # 대상만 보기
  python scripts/fix_corrupted_titles.py --run     # 복구 + 재임베딩

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 회상 노이즈의 직접 원인 제거.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from src.pg_base import execute_raw, query_rows, _sql_text  # noqa: E402

# 백슬래시가 3개 이상 연달아 붙은 제목 = 왕복 누적의 흔적.
# [WHY 3개인가] 정상 문자열에 백슬래시가 2개 연속인 경우는 있을 수 있으나(경로 등),
#   3개 이상은 이스케이프 누적 말고는 생기지 않는다.
CORRUPT_RE = r'\\{3,}'


def _restore_title(title: str, content: str) -> str | None:
    """깨진 제목을 본문에서 복원한다. 복원 불가면 None.

    [전략] 파일 역할 카드는 제목이 `📄 {파일명} — {설명앞40자}` 이고
      본문 `## 역할` 절에 같은 설명의 **원문**이 남아 있다. 그 원문으로 다시 만든다.
      역할 카드가 아니면 백슬래시만 접어서(연속 → 없음) 최소 복구한다.
    """
    # 1) 파일 역할 카드 — 본문의 '## 역할' 절에서 원문 확보
    m = re.search(r'##\s*역할\s*\n(.+?)(?:\n\n|\Z)', content, re.DOTALL)
    if m and title.startswith('📄'):
        role = ' '.join(m.group(1).split())
        # 제목 앞부분(📄 파일명 — )은 살리고 뒤쪽 설명만 원문으로 교체
        head = title.split('—')[0].rstrip()
        if head and role:
            return f'{head} — {role[:40]}'

    # 2) 그 외 — 누적된 백슬래시만 제거 (원문 복원은 불가하나 노이즈는 사라진다)
    cleaned = re.sub(r'\\{2,}', '', title)
    cleaned = cleaned.replace('\\"', '"').strip()
    cleaned = ' '.join(cleaned.split())
    return cleaned or None


def find_corrupted() -> list[dict]:
    return query_rows(
        "SELECT id, title, coalesce(content,'') AS content, "
        "coalesce(access_count,0) AS ref "
        f"FROM zettel_notes WHERE title ~ '{CORRUPT_RE}' "
        "ORDER BY access_count DESC NULLS LAST"
    ) or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true', help='실제 복구 수행')
    args = ap.parse_args()

    rows = find_corrupted()
    if not rows:
        print('깨진 제목 없음.')
        return 0

    print(f'깨진 제목 {len(rows)}건\n')
    plans = []
    for r in rows:
        new = _restore_title(r['title'], r['content'])
        plans.append((r, new))
        print(f"  ref={r['ref']:>4}")
        print(f"    현재: {r['title'][:78]}")
        print(f"    복구: {new[:78] if new else '(복구 불가)'}")
        print()

    if not args.run:
        print('--run 을 붙이면 실제로 복구한다.')
        return 0

    # 복구 + 임베딩 무효화(NULL) — 백필/재임베딩이 새 제목으로 다시 만들게 한다.
    # [WHY NULL로 두나] 제목이 바뀌었는데 옛 임베딩이 남아 있으면 검색은 여전히
    #   깨진 제목 기준으로 매칭된다. 값이 바뀌면 벡터도 반드시 함께 무효화해야 한다.
    done = 0
    for r, new in plans:
        if not new:
            continue
        ok = execute_raw(
            f"UPDATE zettel_notes SET title = {_sql_text(new)}, embedding = NULL "
            f"WHERE id = {_sql_text(str(r['id']))}"
        )
        done += 1 if ok else 0
    print(f'DB 복구 {done}건 — 임베딩은 NULL로 비웠다.')

    # [🔴 필수] 볼트 파일도 함께 고친다.
    #   DB만 고치면 다음 동기화가 **깨진 볼트 파일을 다시 import**해 원상복구된다.
    #   실제로 DB만 고쳤을 때 8건이 그대로 되돌아왔다. 원본은 파일 쪽이다.
    n_files = fix_vault_files()
    print(f'볼트 파일 복구 {n_files}건')
    print('다음: python scripts/reembed_all.py --run  (또는 백필 데몬이 자동 처리)')
    return 0


def fix_vault_files() -> int:
    """볼트 .md의 프론트매터 title에 누적된 백슬래시를 걷어낸다.

    [복원 근거] 파일 **이름**에는 원문 제목이 살아 있다(파일명 생성은 이스케이프 경로를
      타지 않기 때문). 그래서 파일명을 원본으로 삼아 title을 되살린다.
    [제약] 파일명은 콜론 등 금지문자가 제거된 형태라 원문과 100% 같지는 않다.
      그래도 백슬래시 덩어리보다는 의미가 훨씬 잘 보존된다.
    """
    root = Path(__file__).resolve().parent.parent / '.zettel-vault'
    if not root.exists():
        return 0
    fixed = 0
    for md in root.rglob('*.md'):
        try:
            text = md.read_text(encoding='utf-8')
        except OSError:
            continue
        m = re.search(r'^title:\s*"(.*)"\s*$', text, re.MULTILINE)
        if not m or not re.search(CORRUPT_RE, m.group(1)):
            continue
        # 파일명에서 'vibe-123 ' 접두사를 떼면 원문 제목이 남는다
        stem = re.sub(r'^[a-z0-9]+-\d+\s+', '', md.stem).strip()
        if not stem:
            continue
        new_line = f'title: "{stem}"'
        text2 = text[:m.start()] + new_line + text[m.end():]
        try:
            md.write_text(text2, encoding='utf-8')
            fixed += 1
        except OSError:
            continue
    return fixed


if __name__ == '__main__':
    raise SystemExit(main())
