"""
FILE: scripts/wiki_lint.py
DESCRIPTION: wiki/ 백과사전이 '늙었는지'를 기계적으로 검출한다 — 죽은 출처(사라진 파일·
             범위를 벗어난 줄번호·없는 커밋), 심볼 이동, 목차에서 끊긴 고아 페이지,
             출처 없는 주장, 150장 상한 초과. `.claude/rules/wiki.md` 규칙 2·3의 강제 지점.

REVISION HISTORY:
- 2026-08-15 Claude: 신설 — 위키 전환 W7. 규약(rules/wiki.md)과 wiki/INDEX.md 가 이미
  이 스크립트를 '확인법'으로 안내하고 있었는데 실체가 없었다. 즉 규칙 3(모든 주장에
  출처)이 사람 선의에만 기대던 상태였고, 출처가 썩어도 아무도 몰랐다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.ai_monitor'))

try:
    from infra.proc import run as _proc_run   # 규칙 10 — 데몬이 이 스크립트를 부를 수 있다
except Exception:                              # noqa: BLE001
    import subprocess

    def _proc_run(cmd, **kw):                  # 폴백: 개발 체크아웃 밖에서도 돌아야 한다
        return subprocess.run(cmd, **kw)

WIKI = ROOT / 'wiki'
MAX_PAGES = 150                                # 규칙 2 — 규약과 같은 값. 바꾸려면 양쪽 다
VALID_TYPES = {'개념', '시스템', '함정', '결정'}

_FRONT = re.compile(r'^---\n(.*?)\n---\n', re.S)
_H3 = re.compile(r'^### +(.+?)\s*$', re.M)
# 본문 인용은 `경로:줄번호` 또는 `경로` 형태의 인라인 코드로 박힌다(규칙 3).
_CODE_EXT = r'py|tsx|ts|jsx|js|md|json|sql|ps1|spec|yml|yaml|css|html|cmd|sh|toml|iss'
_BODY_REF = re.compile(rf'`([\w./\-]+\.(?:{_CODE_EXT}))(?::(\d+))?`')
_SRC_LINE = re.compile(rf'^([\w./\-]+\.(?:{_CODE_EXT}))(?::(\d+))?$')
_HASH = re.compile(r'^[0-9a-f]{7,40}$')
_INDEX_LINK = re.compile(r'^- \[.+?\]\((.+?\.md)\)', re.M)
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

ERROR, WARN, INFO = 'ERROR', 'WARN', 'INFO'

# 파일도 커밋도 아니지만 wiki_build 가 정식으로 쓰는 '창고' 출처 토큰.
# [불변식] wiki_build.render_page 가 적는 문자열과 **글자 그대로** 같아야 한다. 어긋나면
#   멀쩡한 출처가 전부 'source-unverifiable' INFO 로 쏟아져(페이지당 1건) 진짜 신호를
#   덮는다 — 2026-08-15 첫 실행에서 인라인 주석 미처리로 15건이 그렇게 났었다.
KNOWN_STORES = {
    'incident_ledger',   # PostgreSQL 사고 장부
    'session_memory',    # ~/.claude/projects/<슬러그>/memory/ — 리포 밖이라 경로 검증 불가
}


@dataclass
class Finding:
    level: str
    page: str
    kind: str
    msg: str


@dataclass
class Page:
    path: Path
    rel: str
    text: str
    fm: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)


# ─────────────────────────── 파싱 ───────────────────────────

def parse_front_matter(text: str) -> tuple[dict, list[str], list[str]]:
    """스칼라 키 + `sources`/`related` 리스트만 뽑는 관용 파서.

    [WHY 정식 YAML 파서를 안 쓰나] wiki_index._front_matter 와 같은 이유 — 의존성 회피보다
      **파싱 실패가 전체를 멈추면 안 된다**는 쪽이 크다. 사람이 옵시디언에서 손으로 고치다
      YAML 을 깨뜨렸을 때, 린트가 예외로 죽으면 정작 깨진 걸 못 알려준다. 여기서는 못 읽은
      키를 '없음'으로 취급하고 그 사실 자체를 finding 으로 올린다.
    [제약] 리스트 항목의 ` #` 이후는 YAML 인라인 주석으로 떼어낸다. 경로/해시에는 공백+`#`
      이 올 수 없어 안전하다. wiki_build 가 `incident_ledger  # 사고 7건` 형태로 남기므로
      떼지 않으면 멀쩡한 출처가 전부 '형식 오류'로 잡힌다(2026-08-15 첫 실행에서 15건).
    """
    m = _FRONT.match(text)
    if not m:
        return {}, [], []
    fm: dict = {}
    sources: list[str] = []
    related: list[str] = []
    bucket: list[str] | None = None
    for raw in m.group(1).splitlines():
        if not raw.strip():
            continue
        if raw.startswith((' ', '\t', '-')):
            item = raw.strip()
            if item.startswith('#'):            # YAML 주석 — '…외 52건' 등
                continue
            if item.startswith('- '):
                item = item[2:].strip()
            item = re.split(r'\s+#', item, maxsplit=1)[0].strip()
            if bucket is not None and item:
                bucket.append(item.strip('\'"'))
            continue
        key, _, val = raw.partition(':')
        key, val = key.strip(), val.strip()
        if key == 'sources':
            bucket = sources
        elif key == 'related':
            bucket = related
        else:
            bucket = None
        if val and val not in ('[]', '~', 'null'):
            if key in ('sources', 'related'):
                # 인라인 리스트 `sources: [a, b]`
                inner = val.strip('[]')
                bucket = sources if key == 'sources' else related
                bucket.extend(x.strip().strip('\'"') for x in inner.split(',') if x.strip())
            else:
                fm[key] = val
    return fm, sources, related


def load_pages() -> list[Page]:
    pages = []
    for p in sorted(WIKI.rglob('*.md')):
        text = p.read_text(encoding='utf-8', errors='ignore')
        fm, srcs, rels = parse_front_matter(text)
        pages.append(Page(p, p.relative_to(WIKI).as_posix(), text, fm, srcs, rels))
    return pages


# ─────────────────────────── 출처 검증 ───────────────────────────

_linecache: dict[str, int | None] = {}


def file_lines(rel: str) -> int | None:
    """리포 상대경로의 줄 수. 파일이 없으면 None. (페이지 수십 장이 같은 파일을 인용한다)"""
    if rel in _linecache:
        return _linecache[rel]
    target = (ROOT / rel)
    n: int | None = None
    if target.is_file():
        try:
            n = sum(1 for _ in target.open('rb'))
        except OSError:
            n = None
    _linecache[rel] = n
    return n


def verify_commits(hashes: set[str]) -> set[str]:
    """존재하지 않는 커밋 해시 집합을 돌려준다. git 이 없으면 빈 집합(=검사 포기).

    [WHY 한 번에 batch 로 묻나] 페이지당 커밋 인용이 여러 개이고 페이지는 수십 장이다.
      해시마다 git 프로세스를 띄우면 린트가 수 초 → 수십 초가 된다. `--batch-check` 는
      stdin 으로 전부 받아 한 프로세스로 답한다.
    """
    if not hashes:
        return set()
    try:
        r = _proc_run(['git', 'cat-file', '--batch-check'], cwd=str(ROOT),
                      input='\n'.join(sorted(hashes)), capture_output=True,
                      text=True, encoding='utf-8', errors='ignore', timeout=30)
    except Exception:                           # noqa: BLE001  git 미설치/타임아웃 — 검사 포기
        return set()
    if r.returncode not in (0, 1):
        return set()
    missing = set()
    for line in (r.stdout or '').splitlines():
        parts = line.split()
        # 없는 오브젝트는 `<입력> missing` 으로 나온다.
        if len(parts) >= 2 and parts[1] == 'missing':
            missing.add(parts[0])
    return missing


def check_sources(page: Page, pending_hashes: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for src in page.sources:
        if _HASH.match(src):
            pending_hashes.add(src)
            continue
        if src in KNOWN_STORES:
            continue
        m = _SRC_LINE.match(src)
        if not m:
            # [WHY INFO 인가] 파일도 커밋도 아니지만 정당한 근거가 있다. 기계가 못 미덥다고
            #   사람 근거를 경고로 올리면 경고가 흔해져서 진짜 죽은 출처가 묻힌다 —
            #   세되 재촉하지는 않는다.
            out.append(Finding(INFO, page.rel, 'source-unverifiable',
                               f'기계 검사 불가 출처: {src!r} (파일:줄번호/커밋이 아님)'))
            continue
        path, line = m.group(1), m.group(2)
        n = file_lines(path)
        if n is None:
            out.append(Finding(ERROR, page.rel, 'source-gone', f'사라진 파일: {src}'))
        elif line and int(line) > n:
            out.append(Finding(ERROR, page.rel, 'source-line',
                               f'줄번호 초과: {src} (현재 {n}줄)'))
    return out


def check_symbol_gone(page: Page) -> list[Finding]:
    """`### 심볼` 블록이 인용한 파일에 그 심볼이 아직 **존재**하는지.

    [WHY 줄번호 존재만으로는 부족한가] 파일이 안 지워지고 줄 수만 늘면 죽은 출처 검사를
      전부 통과한다. 위키가 실제로 썩는 결정적 방식은 **심볼이 사라지거나 이름이 바뀌는 것**
      이고, 그때 페이지는 없는 함수를 설명하는 거짓말이 된다.
    [🔴 과거사고 2026-08-15 — 첫 구현] 처음엔 '인용 줄 ±40줄 안에 심볼이 있나'로 판정했다가
      61건이 전부 거짓 경보였다. 원인: wiki_build 의 h3 제목은 **감싸는 함수명**인데 출처
      줄번호는 그 함수 **안쪽 주석 줄**이다(예: `handle_post` 정의 439줄, 출처 481줄 —
      lan_api.py). 긴 함수면 어떤 창 폭을 잡아도 빗나간다. 창 폭을 늘려 맞추려 들면 그건
      검사가 아니라 검사를 끄는 것이다. → **위치가 아니라 존재**로 기준을 바꿨다.
    [제약] WARN 이지 ERROR 가 아니다. 동명 심볼이 다른 파일로 옮겨간 경우 등 사람이 봐야
      아는 상황이 섞인다. 여기서 ERROR 를 내면 CI 가 상시 빨간불이 되어 신호가 죽는다.
    """
    out: list[Finding] = []
    marks = list(_H3.finditer(page.text))
    seen: set[tuple[str, str]] = set()          # 같은 (심볼, 파일)이 페이지에 여러 번 나온다
    for i, m in enumerate(marks):
        head = re.sub(r'`\[.+?\]`', '', m.group(1)).strip()
        if not _IDENT.match(head):              # '모듈 상단' 같은 서술형 제목은 대상 아님
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(page.text)
        ref = _BODY_REF.search(page.text[m.end():end])
        if not ref:
            continue
        path = ref.group(1)
        if (head, path) in seen:
            continue
        seen.add((head, path))
        target = ROOT / path
        if not target.is_file():
            continue                            # check_sources 가 이미 잡는다 — 중복 보고 금지
        try:
            src = target.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if not re.search(rf'\b{re.escape(head)}\b', src):
            out.append(Finding(WARN, page.rel, 'symbol-gone',
                               f'심볼이 사라짐(이름 변경 의심): `{head}` 가 {path} 에 없음'))
    return out


# ─────────────────────────── 구조 검증 ───────────────────────────

def check_shape(page: Page) -> list[Finding]:
    out: list[Finding] = []
    if not page.fm:
        out.append(Finding(ERROR, page.rel, 'no-front-matter', '프론트매터가 없거나 깨짐'))
        return out
    for key in ('title', 'type', 'confidence', 'updated'):
        if not page.fm.get(key):
            out.append(Finding(ERROR, page.rel, 'front-matter', f'프론트매터 `{key}` 누락'))
    ptype = page.fm.get('type', '')
    if ptype and ptype not in VALID_TYPES:
        out.append(Finding(ERROR, page.rel, 'bad-type',
                           f'type 값이 규약 밖: {ptype!r} (허용: {"|".join(sorted(VALID_TYPES))})'))
    if '## 한 줄' not in page.text:
        # 규약 4 — 회상에서 이 페이지를 만난 LLM 이 열지 말지 판단하는 유일한 줄이다.
        out.append(Finding(ERROR, page.rel, 'no-oneliner', '`## 한 줄` 섹션 없음 (규약 필수)'))
    if '## 확인법' not in page.text:
        out.append(Finding(INFO, page.rel, 'no-verify', '`## 확인법` 없음 — 늙었는지 판정 불가'))
    if not page.sources and not _BODY_REF.search(page.text):
        out.append(Finding(WARN, page.rel, 'no-source',
                           '출처가 하나도 없음 (규칙 3 — 검증 불가능한 전설이 된다)'))
    return out


def check_index(pages: list[Page]) -> list[Finding]:
    """목차 ↔ 실제 파일 양방향 대조."""
    out: list[Finding] = []
    idx = WIKI / 'INDEX.md'
    if not idx.is_file():
        return [Finding(ERROR, 'INDEX.md', 'no-index', 'wiki/INDEX.md 가 없다')]
    text = idx.read_text(encoding='utf-8', errors='ignore')
    linked = {m.group(1) for m in _INDEX_LINK.finditer(text)}
    on_disk = {p.rel for p in pages if p.rel != 'INDEX.md'}

    for rel in sorted(linked - on_disk):
        out.append(Finding(ERROR, 'INDEX.md', 'index-dead', f'목차가 없는 파일을 가리킴: {rel}'))
    for rel in sorted(on_disk - linked):
        # [WHY ERROR 가 아닌가] 회상(LLM)은 목차 없이도 찾는다. 못 찾는 건 사람뿐이라
        #   '지식 유실'이 아니라 '입구 누락'이다. wiki_build --stats 를 한 번 돌리면 낫는다.
        out.append(Finding(WARN, 'INDEX.md', 'orphan', f'목차에 없는 고아 페이지: {rel}'))
    return out


def check_budget(pages: list[Page]) -> list[Finding]:
    n = len([p for p in pages if p.rel != 'INDEX.md'])
    if n > MAX_PAGES:
        return [Finding(ERROR, '(전체)', 'over-budget',
                        f'{n}장 — 규칙 2 의 {MAX_PAGES}장 상한 초과. 합치거나 버릴 것')]
    if n > MAX_PAGES * 0.8:
        return [Finding(WARN, '(전체)', 'near-budget',
                        f'{n}장 — 상한 {MAX_PAGES}장의 80% 초과. 합칠 후보를 찾을 때')]
    return []


def check_unsorted(pages: list[Page]) -> list[Finding]:
    """'분류 미정' 페이지가 부푸는 것 = wiki_build.TOPICS 지도에 구멍이 났다는 뜻.

    [WHY 이걸 따로 보나] wiki_build 는 주제 지도에 없는 파일을 조용히 '분류 미정'으로
      떨군다(유실 방지). 조용하기 때문에 아무도 지도를 안 고치고, 그러면 목차가 서서히
      쓸모없어진다. 여기서 세어 주지 않으면 그 구멍은 영원히 안 메워진다.
    """
    out: list[Finding] = []
    for p in pages:
        if '분류 미정' not in p.rel:
            continue
        n = len(_H3.findall(p.text))
        if n:
            out.append(Finding(WARN, p.rel, 'unsorted',
                               f'미분류 지식 {n}건 — wiki_build.py 의 TOPICS 에 주제를 추가할 것'))
    return out


# 위키 규약을 **설명하는 글**이 예시로 쓴 대괄호들. 가리키는 대상이 원래 없다.
# [WHY 무시 목록이 필요한가] 규약 본문(rules/wiki.md)과 그걸 인용한 코드 주석이 위키에
#   합성돼 들어오면서 `[[링크]]` 같은 자리표시자가 매 빌드마다 dangling 으로 잡힌다.
#   진짜 오타와 섞이면 사람이 목록을 안 읽게 되고, 그러면 이 검사 자체가 죽는다.
_LINK_PLACEHOLDERS = {'링크', '위키링크', '슬러그', '없는 페이지', '이름', 'embed', 'name', '...'}


def check_related(pages: list[Page]) -> list[Finding]:
    """`related` 와 본문 `[[링크]]` 의 대상이 실제 페이지인지.

    [제약] INFO 다. 규약상 아직 없는 페이지를 가리키는 `[[링크]]` 는 **오류가 아니라
      '나중에 쓸 것' 표시**로 허용된다(rules/wiki.md). 그래도 세어서 보여는 준다 —
      오타와 예약을 사람이 가려야 하기 때문.
    """
    titles = {p.fm.get('title', p.path.stem) for p in pages} | {p.path.stem for p in pages}
    out: list[Finding] = []
    for p in pages:
        dangling = {r for r in p.related if r not in titles}
        dangling |= {m for m in re.findall(r'\[\[(.+?)\]\]', p.text) if m not in titles}
        dangling -= _LINK_PLACEHOLDERS
        for name in sorted(dangling):
            out.append(Finding(INFO, p.rel, 'dangling-link', f'아직 없는 페이지를 가리킴: [[{name}]]'))
    return out


# ─────────────────────────── 실행 ───────────────────────────

def lint() -> list[Finding]:
    if not WIKI.is_dir():
        return [Finding(ERROR, '(전체)', 'no-wiki', 'wiki/ 디렉토리가 없다')]
    pages = load_pages()
    findings: list[Finding] = []
    pending: set[str] = set()

    for p in pages:
        findings += check_shape(p)
        findings += check_sources(p, pending)
        findings += check_symbol_gone(p)

    missing = verify_commits(pending)
    if missing:
        for p in pages:
            for src in p.sources:
                if src in missing:
                    findings.append(Finding(ERROR, p.rel, 'commit-gone', f'없는 커밋: {src}'))

    findings += check_index(pages)
    findings += check_budget(pages)
    findings += check_unsorted(pages)
    findings += check_related(pages)
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description='wiki/ 백과사전 린트 — 죽은 출처·고아·상한 검사')
    ap.add_argument('--strict', action='store_true', help='경고도 실패로 취급')
    ap.add_argument('--json', action='store_true', help='기계 판독용 JSON 출력')
    ap.add_argument('--quiet', action='store_true', help='요약 한 줄만')
    args = ap.parse_args()

    findings = lint()
    counts = {lv: sum(1 for f in findings if f.level == lv) for lv in (ERROR, WARN, INFO)}

    if args.json:
        print(json.dumps({'counts': counts,
                          'findings': [f.__dict__ for f in findings]},
                         ensure_ascii=False, indent=2))
    elif args.quiet:
        print(f"오류 {counts[ERROR]} · 경고 {counts[WARN]} · 참고 {counts[INFO]}")
    else:
        icon = {ERROR: '🔴', WARN: '🟡', INFO: '  '}
        by_page: dict[str, list[Finding]] = {}
        for f in findings:
            by_page.setdefault(f.page, []).append(f)
        for page in sorted(by_page):
            print(f'\n{page}')
            for f in sorted(by_page[page], key=lambda x: (x.level != ERROR, x.kind)):
                print(f'  {icon[f.level]} [{f.kind}] {f.msg}')
        print(f"\n{'─' * 60}")
        print(f"오류 {counts[ERROR]} · 경고 {counts[WARN]} · 참고 {counts[INFO]}")
        if not findings:
            print('문제 없음.')

    if counts[ERROR]:
        return 1
    if args.strict and counts[WARN]:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
