"""
FILE: src/wiki_index.py
DESCRIPTION: wiki/ 마크다운(정본)을 zettel_notes(검색 인덱스)로 밀어 넣는다.
             3층 구조에서 ① 파일 → ② DB 방향의 유일한 통로다. 반대 방향은 없다 —
             DB 를 고쳐도 다음 인덱싱에 덮어써진다(규약 .claude/rules/wiki.md 0절).

REVISION HISTORY:
- 2026-08-15 Claude: 신설 — LLM 위키 전환 W5. 위키를 만들어도 회상이 못 읽던
  '만들었는데 안 읽힘' 상태를 끝내는 단계.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    from src import zettelkasten as zk
    from src.pg_base import query_rows
except ImportError:  # 스크립트 단독 실행 경로
    import zettelkasten as zk  # type: ignore
    from pg_base import query_rows  # type: ignore

AUTHOR = 'wiki_index'

# [🔴 WHY 페이지가 아니라 섹션 단위로 인덱싱하나] 임베딩 대상 텍스트는
#   `title || LEFT(content, 400)` 이다(pg_vector_search._TABLES). 그런데 주제 페이지는
#   최대 43KB 다 — 페이지를 통째로 한 노트로 넣으면 **앞 400자만 검색에 들어가고
#   나머지 99%는 존재하지 않는 것과 같아진다.** 페이지는 사람이 읽는 단위,
#   인덱스는 검색 단위 — 둘을 분리한다.
# [불변식] 섹션 경계는 h3(`### `). wiki_build 의 render_page 가 지식 블록 1개를
#   h3 하나로 쓴다. 그쪽 렌더 형식을 바꾸면 여기도 같이 바꿔야 한다.
_H3 = re.compile(r'^### +(.+?)\s*$', re.M)
# [🔴 과거사고 2026-08-15] 처음엔 h3 제목만으로 id 를 만들었다가 270건이 키 충돌로
#   실패했다. 한 주제 페이지 안에는 파일이 여러 개 들어가고, 그 파일마다 "모듈 상단"
#   같은 **같은 이름의 h3 가 반복**되기 때문이다. h2(소속 파일)까지 넣어야 유일해진다.
_H2 = re.compile(r'^## +`(.+?)`\s*$', re.M)
_FRONT = re.compile(r'^---\n(.*?)\n---\n', re.S)
_TAGCOMMENT = re.compile(r'<!--\s*tags:\s*(.+?)\s*-->')


def _front_matter(text: str) -> dict:
    """프론트매터에서 title/type 만 뽑는다.

    [WHY 정식 YAML 파서를 안 쓰나] 의존성을 늘리지 않으려는 것도 있지만, 더 중요한 건
      **파싱 실패가 인덱싱 전체를 멈추면 안 된다**는 점이다. 사람이 옵시디언에서 손으로
      고치다 YAML 을 깨뜨릴 수 있고, 그때 조용히 회상이 비는 것이 최악이다.
      여기서는 필요한 두 줄만 정규식으로 줍고 나머지는 무시한다.
    """
    m = _FRONT.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ':' not in line or line.startswith((' ', '-', '#')):
            continue
        k, _, v = line.partition(':')
        out[k.strip()] = v.strip()
    return out


def iter_sections(path: Path, wiki_root: Path) -> list[dict]:
    """페이지 1장을 섹션 노트 여러 건으로 쪼갠다."""
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return []

    fm = _front_matter(text)
    page = fm.get('title') or path.stem
    ptype = fm.get('type') or path.parent.name
    tag_m = _TAGCOMMENT.search(text)
    page_tags = [t.strip() for t in tag_m.group(1).split(',')] if tag_m else []
    rel = path.relative_to(wiki_root).as_posix()

    # h3 각각이 어느 h2(파일) 아래인지 — 위치 비교로 직전 h2 를 찾는다.
    h2s = [(m.start(), m.group(1)) for m in _H2.finditer(text)]

    def _owner(pos: int) -> str:
        owner = ''
        for start, name in h2s:
            if start < pos:
                owner = name
            else:
                break
        return owner

    marks = list(_H3.finditer(text))
    notes: list[dict] = []
    # [🔴 과거사고 2026-08-15 — 2차] h2(파일)를 넣어도 178건이 또 충돌했다. 한 파일의
    #   **같은 심볼에 지식 블록이 여러 개** 있으면 wiki_build 가 같은 h3 를 반복해서
    #   찍기 때문이다(`### 모듈 상단` × 3). 등장 순번까지 넣어야 비로소 유일하다.
    #   순번은 그 (파일, 심볼) 안에서의 순서라, 뒤쪽 블록이 추가돼도 앞쪽 id 는 안 변한다.
    seen: dict[tuple[str, str], int] = {}
    for i, m in enumerate(marks):
        head = m.group(1)
        owner = _owner(m.start())
        body = text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip()
        if len(body) < 30:      # 빈 섹션 — 인덱스에 넣어봐야 노이즈다
            continue
        # h3 제목에 붙은 `[태그]` 표기를 태그로 승격. 제목에서는 지운다(검색 텍스트 정리).
        inline_tags = re.findall(r'`\[(.+?)\]`', head)
        clean_head = re.sub(r'`\[.+?\]`', '', head).strip()

        # [WHY 제목에 페이지명을 넣나] 회상 결과는 제목 한 줄로 보인다. 섹션 제목만
        #   쓰면 "모듈 상단" 같은 게 수십 개 떠서 어느 주제의 것인지 분간이 안 된다.
        # 제목에 소속 파일명을 넣는다 — 회상 결과에서 "모듈 상단"만 여러 개 뜨면
        # 어느 파일 이야기인지 분간이 안 된다.
        owner_short = Path(owner).name if owner else ''
        title = f'📖 {page} · {owner_short} · {clean_head}'.replace(' ·  · ', ' · ')[:120]
        # [WHY 순서를 지키며 중복 제거하나] dict.fromkeys 는 삽입 순서를 보존한다.
        #   set() 을 쓰면 태그 순서가 실행마다 달라져, 내용이 그대로인데도 update 가
        #   발생하고 재임베딩이 돈다(sync 의 해시 판정이 무력화된다).
        tags = list(dict.fromkeys(['wiki', ptype] + inline_tags + page_tags[:4]))
        key = (owner, clean_head)
        seen[key] = seen.get(key, 0) + 1
        anchor = f'{rel}#{owner}#{clean_head}#{seen[key]}'
        notes.append({
            'id': 'w-' + hashlib.sha1(anchor.encode()).hexdigest()[:12],
            'title': title,
            'content': body,
            'source_ref': f'wiki:{anchor}',
            'tags': tags,
        })
    return notes


def collect(wiki_root: Path) -> list[dict]:
    notes: list[dict] = []
    for path in sorted(wiki_root.rglob('*.md')):
        if path.name in ('INDEX.md', '_placeholder.md'):
            continue
        notes += iter_sections(path, wiki_root)
    return notes


def sync(wiki_root: Path, project_id: str, dry_run: bool = False) -> dict:
    """위키 → 인덱스 동기화. 새 섹션은 생성, 바뀐 섹션은 갱신, 사라진 섹션은 아카이브.

    [WHY 해시로 변경 판정하나] 5169건 재임베딩이 몇 분 걸린다. 내용이 그대로인데
      update_note 를 부르면 updated_at 이 밀리고 백필 데몬이 임베딩을 다시 만든다 —
      c7a42f2 볼트 핑퐁과 같은 형태의 낭비다. 바뀐 것만 건드린다.
    """
    notes = collect(wiki_root)
    existing = {
        r['id']: r for r in query_rows(
            "SELECT id, content FROM zettel_notes WHERE author = %s AND archived = false",
            (AUTHOR,),
        )
    }

    created = updated = kept = failed = 0
    for nt in notes:
        old = existing.get(nt['id'])
        if old is not None:
            if (old.get('content') or '').strip() == nt['content'].strip():
                kept += 1
                continue
            if dry_run:
                updated += 1
                continue
            ok = zk.update_note(nt['id'], title=nt['title'], content=nt['content'],
                                tags=nt['tags'], source_ref=nt['source_ref'],
                                note_type='permanent', archived=False)
            updated += 1 if ok else 0
            failed += 0 if ok else 1
        else:
            if dry_run:
                created += 1
                continue
            ok = zk.create_note(
                title=nt['title'], content=nt['content'], note_type='permanent',
                author=AUTHOR, project_id=project_id, tags=nt['tags'],
                source_ref=nt['source_ref'], custom_id=nt['id'])
            created += 1 if ok else 0
            failed += 0 if ok else 1

    # 위키에서 사라진 섹션 정리.
    # [🔴 아카이브지 삭제가 아니다] 오판이면 되돌려야 한다. 그리고 사라진 지식이 회상에
    #   남으면 다음 세션이 없는 코드를 전제로 판단한다 — 노이즈보다 나쁘다.
    live = {n['id'] for n in notes}
    stale = [nid for nid in existing if nid not in live]
    if not dry_run:
        for nid in stale:
            zk.update_note(nid, archived=True)

    return {'sections': len(notes), 'created': created, 'updated': updated,
            'kept': kept, 'archived': len(stale), 'failed': failed}


# ── 구글 드라이브 허브 미러 ──────────────────────────────────────────────────

# [WHY 드라이브 레터를 훑나] PC 마다 구글 드라이브가 잡히는 문자(I:/G:/H:…)와 언어
#   ('내 드라이브' / 'My Drive')가 다르다. 고정 경로를 박으면 이 PC 에서만 동작한다.
#   같은 이유로 zettel_sync 도 같은 방식을 쓴다 — 규칙을 바꾸면 양쪽을 같이 바꿀 것.
_DRIVE_LABELS = ('내 드라이브', 'My Drive')
HUB_FOLDER = 'vibe-wiki'


def detect_gdrive_hub() -> Path | None:
    """구글 드라이브의 위키 허브 폴더를 찾는다. 없으면 None(미러 건너뜀)."""
    import string
    for letter in string.ascii_uppercase:
        root = Path(f'{letter}:/')
        try:
            if not root.exists():
                continue
        except OSError:      # 연결 끊긴 네트워크 드라이브 — 조회 자체가 던진다
            continue
        for label in _DRIVE_LABELS:
            base = root / label
            if base.is_dir():
                return base / HUB_FOLDER
    return None


def mirror_to_hub(wiki_root: Path, project_name: str, hub: Path | None = None) -> dict:
    """위키를 구글 드라이브 허브의 프로젝트별 폴더로 복사한다.

    [WHY API 가 아니라 폴더 복사인가] 구글 드라이브 데스크톱 앱이 이미 그 폴더를
      동기화하고 있다. 우리가 API 로 올리면 인증·할당량·충돌 처리를 다 떠안게 되고,
      정작 사용자는 같은 파일을 두 경로로 갖게 된다. 파일만 쓰고 업로드는 맡긴다.
    [🔴 과거사고 c7a42f2] 내용이 같아도 write 하면 mtime 이 바뀌고, 구글 드라이브가
      그걸 변경으로 보고 전량 재업로드한다(볼트 핑퐁 3단 고리의 시작점이었다).
      반드시 해시 비교 후 변경분만 쓴다.
    [WHY 프로젝트별 하위 폴더인가] 섞이면 CipherTrader 지식이 vibe-coding 회상에
      튀어나온다. 허브는 '모아 두는 곳'이지 '합치는 곳'이 아니다.
    """
    hub = hub or detect_gdrive_hub()
    if hub is None:
        return {'status': 'skipped', 'reason': '구글 드라이브를 찾지 못함'}

    target = hub / project_name
    written = kept = removed = 0
    try:
        target.mkdir(parents=True, exist_ok=True)
        live: set[Path] = set()
        for src in wiki_root.rglob('*.md'):
            rel = src.relative_to(wiki_root)
            dst = target / rel
            live.add(dst)
            body = src.read_bytes()
            if dst.exists() and hashlib.sha1(dst.read_bytes()).digest() == hashlib.sha1(body).digest():
                kept += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(body)
            written += 1
        # 위키에서 사라진 파일은 허브에서도 지운다 — 안 그러면 옛 페이지가 다른 PC 에
        # 영원히 남아 '두 버전의 진실'이 생긴다.
        for old in target.rglob('*.md'):
            if old not in live:
                old.unlink()
                removed += 1
    except OSError as exc:
        # [WHY 예외를 삼키나] 드라이브가 잠시 끊기거나 동기화 중 잠금이 걸릴 수 있다.
        #   미러는 부가 기능이라 여기서 데몬을 죽이면 인덱싱까지 멈춘다.
        return {'status': 'error', 'reason': str(exc), 'written': written}
    return {'status': 'ok', 'hub': str(target), 'written': written,
            'kept': kept, 'removed': removed}


def retire_legacy(dry_run: bool = False) -> int:
    """정본이 wiki/ 로 옮겨간 옛 지식 노트(knowledge_extract)를 아카이브.

    [🔴 왜 지금 필요한가] 같은 코드 주석이 wiki 노트와 knowledge_extract 노트 양쪽에
      들어가면 **같은 문장이 두 벌 임베딩된다.** 회상 상위가 자기 복제본으로 채워져
      다른 지식이 밀려난다. 정본은 하나여야 한다.
    """
    rows = query_rows(
        "SELECT id FROM zettel_notes WHERE archived = false AND author = 'knowledge_extract'"
    )
    if not dry_run:
        for r in rows:
            zk.update_note(r['id'], archived=True)
    return len(rows)
