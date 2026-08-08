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
- 2026-08-08 Claude: 볼트 복구 범위를 GDrive까지 확장 + 거대 title을 메모리로 안 끌어오게 수정.
                     로컬 볼트만 고치던 탓에 GDrive의 깨진 파일이 다시 import돼 되살아났다.
"""
from __future__ import annotations

import argparse
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))

from src.pg_base import execute_raw, query_rows, _sql_text  # noqa: E402

# 백슬래시가 3개 이상 연달아 붙은 제목 = 왕복 누적의 흔적.
# [WHY 3개인가] 정상 문자열에 백슬래시가 2개 연속인 경우는 있을 수 있으나(경로 등),
#   3개 이상은 이스케이프 누적 말고는 생기지 않는다.
CORRUPT_RE = r'\\{3,}'

# [WHY] 오염 제목은 115MB까지 자란 실측이 있다(vibe-2781, 2026-08-08). title을 통째로
#   SELECT하면 복구 스크립트 자신이 수백 MB를 힙에 올린다. 복구에 필요한 정보
#   (`📄 파일명 — ` 머리 + 오염 흔적)는 전부 앞부분에 있으므로 left()로 잘라 가져온다.
TITLE_PROBE = 300

# [WHY] 정상 노트는 실측상 전부 100KB 미만이다(1054개 합계 5.8MB). 1MB를 넘는 .md는
#   이스케이프 폭주 말고 다른 원인이 없다. 이 크기의 파일은 read_text 자체가 비싸므로
#   (228MB 파일 1개 = 9.2초) 내용을 읽지 않고 stat()만으로 판정한다.
HUGE_NOTE_BYTES = 1_000_000

# GDrive 볼트 자동 탐지 — PC마다 드라이브 레터와 언어가 달라 고정 경로를 쓸 수 없다.
# daemons.py의 _detect_gdrive_vault와 같은 규칙을 쓴다(양쪽이 어긋나면 복구가 빈다).
_VAULT_MARKER = Path('obsidian') / 'hive-zettel'
_DRIVE_ROOTS = ('내 드라이브', 'My Drive')


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
    """오염 노트를 찾는다. title은 앞 TITLE_PROBE자만 가져온다.

    [제약] 반환되는 'title'은 **잘린 앞부분**이다 — 복구에는 충분하지만 이 값을
      그대로 비교/저장에 쓰면 안 된다. 실제 길이는 title_len으로 따로 본다.
    """
    return query_rows(
        f"SELECT id, left(title, {TITLE_PROBE}) AS title, length(title) AS title_len, "
        "coalesce(content,'') AS content, coalesce(access_count,0) AS ref "
        f"FROM zettel_notes WHERE title ~ '{CORRUPT_RE}' "
        "ORDER BY length(title) DESC"
    ) or []


def vault_roots() -> list[Path]:
    """복구 대상 볼트 전부 — 로컬 + GDrive.

    [🔴 과거사고 2026-08-08] 이 함수가 없던 시절 fix_vault_files는 프로젝트 로컬
      `.zettel-vault`만 고쳤다. GDrive 볼트의 깨진 파일이 다음 동기화에서 그대로
      import돼 DB가 원상복구됐다 — "DB만 고치면 되돌아온다"의 진짜 범인은
      로컬만 본 이 복구 범위였다. 발견 시점 실측: 로컬 1631MB / GDrive 1627MB 양쪽 오염.
    """
    roots: list[Path] = []
    base = Path(__file__).resolve().parent.parent

    for cand in (base / '.zettel-vault',
                 Path.home() / 'AppData' / 'Roaming' / 'VibeCoding' / 'vault'):
        if cand.exists():
            roots.append(cand)

    for letter in string.ascii_uppercase:
        root = Path(f'{letter}:/')
        if not root.exists():
            continue
        for label in _DRIVE_ROOTS:
            cand = root / label / _VAULT_MARKER
            if cand.exists():
                roots.append(cand)

    # 같은 실경로가 여러 후보로 잡힐 수 있다(심볼릭 링크/중복 설정) — 한 번만 처리한다.
    seen: set[str] = set()
    uniq: list[Path] = []
    for r in roots:
        try:
            key = str(r.resolve()).lower()
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true', help='실제 복구 수행')
    args = ap.parse_args()

    rows = find_corrupted()
    if rows:
        total_mb = sum(r['title_len'] for r in rows) / 1048576
        print(f'깨진 제목 {len(rows)}건 — 제목에만 {total_mb:.1f}MB\n')
    else:
        print('DB에 깨진 제목 없음.\n')

    plans = []
    for r in rows:
        new = _restore_title(r['title'], r['content'])
        plans.append((r, new))
        print(f"  ref={r['ref']:>4}  제목길이={r['title_len']:,}자")
        print(f"    복구: {new[:78] if new else '(복구 불가)'}")

    if not args.run:
        print('\n[미리보기] 볼트 스캔:')
        f, d, freed = fix_vault_files(apply=False)
        print(f'  고칠 파일 {f}건 / 지울 거대 파일 {d}건 ({freed / 1048576:.0f}MB 회수)')
        print('\n--run 을 붙이면 실제로 복구한다.')
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

    # [🔴 필수] 볼트 파일도 함께 고친다 — 로컬과 GDrive **양쪽 다**.
    #   DB만 고치면 다음 동기화가 **깨진 볼트 파일을 다시 import**해 원상복구된다.
    #   실제로 DB만 고쳤을 때 8건이 그대로 되돌아왔다. 원본은 파일 쪽이다.
    n_fixed, n_deleted, freed = fix_vault_files(apply=True)
    print(f'볼트 파일 복구 {n_fixed}건 / 거대 파일 삭제 {n_deleted}건 '
          f'({freed / 1048576:.0f}MB 회수 — 다음 export가 정상 크기로 재생성)')
    print('다음: python scripts/reembed_all.py --run  (또는 백필 데몬이 자동 처리)')
    return 0


def fix_vault_files(*, apply: bool = True) -> tuple[int, int, int]:
    """모든 볼트(로컬 + GDrive)의 깨진 .md를 정리한다. (고침, 지움, 회수바이트)

    [복원 근거] 파일 **이름**에는 원문 제목이 살아 있다(파일명 생성은 이스케이프 경로를
      타지 않기 때문). 그래서 파일명을 원본으로 삼아 title을 되살린다.
    [제약] 파일명은 콜론 등 금지문자가 제거된 형태라 원문과 100% 같지는 않다.
      그래도 백슬래시 덩어리보다는 의미가 훨씬 잘 보존된다.
    [WHY 거대 파일은 고치지 않고 지우나] 228MB 파일은 title 한 줄이 파일의 99%다.
      read_text→치환→write_text는 그 자체로 수백 MB 할당에 파일당 9초가 든다.
      볼트는 PG의 파생물이므로 지우면 다음 export_to_vault가 정상 크기로 다시 만든다 —
      '고쳐 쓰기'보다 '버리고 재생성'이 싸고 확실하다.
    [순서 불변식] 반드시 **DB 복구 뒤에** 호출한다. 먼저 지우면 export가 아직 깨진
      DB 제목으로 파일을 재생성해 원위치한다.
    """
    fixed = deleted = freed = 0
    for root in vault_roots():
        print(f'  볼트: {root}')
        for md in root.rglob('*.md'):
            try:
                size = md.stat().st_size
            except OSError:
                continue

            # 내용을 읽지 않고 크기만으로 판정 — 거대 파일 read는 그 자체가 사고 비용이다.
            if size > HUGE_NOTE_BYTES:
                print(f'    [지움] {size / 1048576:.1f}MB  {md.name[:60]}')
                if apply:
                    try:
                        md.unlink()
                    except OSError as exc:
                        print(f'    삭제 실패: {exc}')
                        continue
                deleted += 1
                freed += size
                continue

            try:
                text = md.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            m = re.search(r'^title:\s*"(.*)"\s*$', text, re.MULTILINE)
            if not m or not re.search(CORRUPT_RE, m.group(1)):
                continue
            # 파일명에서 'vibe-123 ' 접두사를 떼면 원문 제목이 남는다
            stem = re.sub(r'^[a-z0-9]+-\d+\s+', '', md.stem).strip()
            if not stem:
                continue
            text2 = text[:m.start()] + f'title: "{stem}"' + text[m.end():]
            if apply:
                try:
                    md.write_text(text2, encoding='utf-8')
                except OSError:
                    continue
            fixed += 1
    return fixed, deleted, freed


if __name__ == '__main__':
    raise SystemExit(main())
