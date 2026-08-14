"""
FILE: scripts/knowledge_extract.py
DESCRIPTION: 코드 안에 이미 적혀 있는 '진짜 지식'을 제텔카스텐으로 옮기는 추출기.
             `[WHY]` `[불변식]` `[제약]` `[과거사고]` `[함정]` 같은 규칙 3 주석 블록을
             **감싸는 심볼 단위로 묶어** zettel_notes에 멱등 upsert 한다.

  [WHY 이 파일이 필요한가 — 2026-08-14 실측]
    기존 제텔 파이프라인(zettel_capture/zettel_sync)은 파일 노트를 만들 때
    **헤더 첫 줄 + 파일 경로 + 커밋 제목**만 복사했다. 448건 중 74%가 500자 미만이고,
    내용이 전부 "git과 파일 헤더에 이미 있는 것"이었다. 그 결과 "그때 그 작업 어떻게
    했지?"를 물으면 세션요약(1578건, 61%)과 커밋 제목(552건, 21%)만 회상됐다.
    그런데 정작 **왜 그렇게 했는지·어디가 함정인지는 코드 주석에 862개나 쌓여 있었다**
    (규칙 3 덕분). 새로 쓸 게 아니라 옮기면 되는 상태였다 — 그 이송이 이 파일이다.

  [불변식] 노트 id는 source_ref의 해시로 **결정적**이다. 같은 (파일, 심볼)은 몇 번을
    돌려도 같은 노트를 갱신한다. 이게 깨지면 재실행마다 중복 노트가 쌓여 회상이
    같은 지식으로 도배된다(top10 점유율 폭증).

  [🔴 거짓 지식 방지] 코드가 바뀌었는데 노트가 남으면 회상이 **옛 사실**을 주입한다.
    ① 노트 본문에 `파일:줄번호`와 추출 시점 커밋 해시를 박아 대조 가능하게 하고
    ② 원본 파일이 사라지거나 블록이 없어지면 `--prune`이 archived=true로 내린다.
    삭제가 아니라 아카이브인 이유 — 오판이면 되돌려야 하는데 삭제는 되돌릴 수 없다.

REVISION HISTORY:
- 2026-08-14 Claude: 최초 작성 — 지식 파이프라인 재설계 축2.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
from infra.project_context import slugify
from src import zettelkasten as zk

# [제약] bin/pgsql·node_modules·dist는 수십만 파일이라 스캔하면 몇 분씩 걸린다.
#   .zettel-vault는 이 스크립트의 **출력물**이므로 입력으로 넣으면 자기 참조가 된다.
SKIP_DIRS = {
    'node_modules', 'dist', 'bin', '__pycache__', '.git', 'venv', '.venv',
    'pgsql', '_appseed', 'build', '%TEMP%', '.zettel-vault', 'ARCHIVE',
}
SCAN_SUFFIXES = ('.py', '.tsx', '.ts')

# [WHY 이 태그들만] CLAUDE.md 규칙 3이 "코드만 봐서는 알 수 없는 것"으로 규정한 범주와
#   1:1 대응한다. 일반 설명 주석(`# 결과를 반환`)은 코드를 자연어로 옮긴 것이라 지식이
#   아니다 — 그런 걸 넣으면 예전 파이프라인의 실패를 그대로 반복한다.
TAG_RE = re.compile(r'\[(WHY|불변식|제약|과거사고|함정|주의|설계|실측|의도적|규칙 \d+)[^\]]*\]')

# 블록이 이보다 짧으면 버린다 — `# [WHY] 성능` 같은 한 토막은 회상 가치가 없고
# 임베딩 공간의 중심 근처에 놓여 노이즈가 된다(2026-08-08 실측과 같은 현상).
MIN_BLOCK_CHARS = 60

# [WHY 보일러플레이트 제거] 표준 파일 헤더(규칙 5)의 REVISION HISTORY 안에도 [WHY]가
#   들어간다. 그 블록을 통째로 담으면 `-*- coding: utf-8 -*-`이나 구분선이 노트 제목이
#   되어 회상 결과가 읽을 수 없게 된다. 지식이 아닌 형식 줄만 걷어낸다.
_BOILERPLATE_RE = re.compile(
    r'^(?:[-=─━_*#\s]{3,}$|-\*-\s*coding|📄|📝|🕒|FILE:|DESCRIPTION:|REVISION HISTORY|'
    r'파일명\s*:|설명\s*:|변경 이력)'
)

_PY_DEF_RE = re.compile(r'^(\s*)(?:async\s+)?(?:def|class)\s+([A-Za-z_][\w]*)')
_TS_DEF_RE = re.compile(
    r'^(\s*)(?:export\s+)?(?:async\s+)?'
    r'(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let)\s+([A-Za-z_$][\w$]*)\s*[:=]|'
    r'class\s+([A-Za-z_$][\w$]*))'
)


def _git_head() -> str:
    """추출 시점 커밋. 노트와 코드가 어긋났는지 나중에 대조하는 유일한 기준점."""
    try:
        r = proc.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(_PROJECT_ROOT),
                     capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else '(unknown)'
    except Exception:
        return '(unknown)'


def iter_source_files(root: Path):
    for p in sorted(root.rglob('*')):
        if not p.is_file() or p.suffix not in SCAN_SUFFIXES:
            continue
        if set(p.relative_to(root).parts) & SKIP_DIRS:
            continue
        yield p


def prose_flags(lines: list[str], suffix: str) -> list[bool]:
    """각 줄이 '산문'(주석·독스트링)인지 판정.

    [WHY 상태 추적이 필요한가] 태그는 `#` 주석뿐 아니라 **독스트링 안에도** 많다
      (예: runtime.script_runner_cmd의 `[WHY 별도 함수]`). 줄 단위 정규식만으로는
      독스트링 본문을 코드로 오인해 블록이 첫 줄에서 잘린다.
    [제약] 완전한 파서가 아니다 — 한 줄 안에서 여는/닫는 삼중따옴표나 문자열 안의
      `#`은 정확히 못 본다. 지식 추출은 근사로 충분하고, 틀려도 노트 몇 개가
      길어질 뿐 오염은 아니다. 여기에 AST를 붙이는 건 과잉이다.
    """
    flags = [False] * len(lines)
    if suffix == '.py':
        in_doc = False
        quote = ''
        for i, ln in enumerate(lines):
            s = ln.strip()
            if in_doc:
                flags[i] = True
                if quote in s:
                    in_doc = False
                continue
            for q in ('"""', "'''"):
                if s.startswith(q):
                    flags[i] = True
                    # 같은 줄에서 닫히면(한 줄 독스트링) 상태를 열지 않는다.
                    if not (len(s) > len(q) and s.endswith(q)):
                        in_doc, quote = True, q
                    break
            else:
                flags[i] = s.startswith('#')
    else:
        in_block = False
        for i, ln in enumerate(lines):
            s = ln.strip()
            if in_block:
                flags[i] = True
                if '*/' in s:
                    in_block = False
                continue
            if s.startswith('/*'):
                flags[i] = True
                in_block = '*/' not in s
                continue
            flags[i] = s.startswith('//') or s.startswith('*')
    return flags


def _strip_marker(line: str) -> str:
    s = line.strip()
    for m in ('#', '//', '*', '"""', "'''"):
        if s.startswith(m):
            s = s[len(m):]
            break
    return s.strip()


def _clean_body(body: str) -> str:
    """블록 본문에서 형식 줄(구분선·헤더 라벨)을 걷어낸다."""
    return '\n'.join(ln for ln in body.splitlines()
                     if ln.strip() and not _BOILERPLATE_RE.match(ln.strip()))


def _summary_line(body: str) -> str:
    """노트 제목에 쓸 한 줄 — **태그 뒤의 실제 문장**을 쓴다.

    [WHY] 블록 첫 줄을 그냥 쓰면 파일 헤더 블록에서 `-*- coding: utf-8 -*-`이 제목이
      된다. 태그가 붙은 줄이 그 블록에서 사람이 남긴 요지이므로 그쪽이 정확하다.
    """
    for ln in body.splitlines():
        m = TAG_RE.search(ln)
        if m:
            tail = ln[m.end():].strip(' -—:·')
            if len(tail) >= 8:
                return tail
    for ln in body.splitlines():
        s = TAG_RE.sub('', ln).strip(' -—:·')
        if len(s) >= 8:
            return s
    return body.strip()[:60]


def _enclosing_symbol(lines: list[str], start: int, suffix: str) -> str:
    """블록을 감싸는 함수/클래스 이름. 없으면 '(모듈)'.

    [WHY 들여쓰기 비교] 단순히 '위쪽의 가장 가까운 def'를 잡으면, 모듈 최상단의
      상수 주석이 **파일 끝 함수**에 붙는 역전이 생긴다. 블록보다 얕은 들여쓰기의
      def만 후보로 삼아야 실제로 그 블록을 감싸는 심볼이 된다.
    """
    indent = len(lines[start]) - len(lines[start].lstrip())
    pat = _PY_DEF_RE if suffix == '.py' else _TS_DEF_RE
    for i in range(start, -1, -1):
        m = pat.match(lines[i])
        if not m:
            continue
        if len(m.group(1)) < indent or (indent == 0 and i == start):
            name = next((g for g in m.groups()[1:] if g), None)
            if name:
                return name
    return '(모듈)'


def extract_blocks(path: Path, root: Path) -> list[dict]:
    """한 파일에서 지식 주석 블록을 뽑는다. 블록 = 태그를 포함한 연속 산문 줄 묶음."""
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []
    lines = text.splitlines()
    flags = prose_flags(lines, path.suffix)
    rel = path.relative_to(root).as_posix()

    blocks, i, n = [], 0, len(lines)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < n and flags[j]:
            j += 1
        chunk = lines[i:j]
        tags = sorted({m.group(1) for ln in chunk for m in TAG_RE.finditer(ln)})
        if tags:
            body = _clean_body('\n'.join(_strip_marker(c) for c in chunk))
            if len(body) >= MIN_BLOCK_CHARS:
                # 코드 앵커 — 이 주석이 지키고 있는 실제 코드 3줄. 주석만 있으면
                # 회상 결과를 보고도 어디를 봐야 할지 모른다.
                # [제약] **연속된** 줄만 담는다 — 띄엄띄엄 주우면 실제로 붙어 있지 않은
                #   코드가 한 덩어리처럼 보여 다음 세션이 오독한다.
                anchor = []
                for k in range(j, min(j + 8, n)):
                    if flags[k]:
                        break
                    if lines[k].strip():
                        anchor.append(lines[k].rstrip())
                    if len(anchor) >= 3:
                        break
                blocks.append({
                    'file': rel, 'line': i + 1, 'tags': tags, 'body': body,
                    'anchor': anchor,
                    'symbol': _enclosing_symbol(lines, i, path.suffix),
                })
        i = j
    return blocks


def build_notes(blocks: list[dict], head: str) -> list[dict]:
    """(파일, 심볼) 단위로 블록을 묶어 노트 1건을 만든다.

    [WHY 블록 하나당 노트가 아닌가] 862개를 그대로 노트로 만들면 한 함수의 지식이
      3~4조각으로 흩어져, 회상이 그중 하나만 물어오면 맥락이 끊긴다. 심볼 단위로
      묶으면 "이 함수에 대해 알아야 할 전부"가 한 노트에 들어온다.
    [WHY 파일 단위가 아닌가] server.py는 지식 주석이 64개다. 파일 하나로 묶으면
      노트가 거대해져 임베딩이 뭉개지고(주제 혼합) 회상 정확도가 떨어진다.
    """
    groups: dict[tuple, list[dict]] = {}
    for b in blocks:
        groups.setdefault((b['file'], b['symbol']), []).append(b)

    notes = []
    for (rel, symbol), bs in groups.items():
        bs.sort(key=lambda x: x['line'])
        all_tags = sorted({t for b in bs for t in b['tags']})
        first = _summary_line(bs[0]['body']).replace('\n', ' ')
        stem = Path(rel).name

        sym_label = symbol if symbol != '(모듈)' else '모듈 상단'
        title = f"🧠 {stem} · {sym_label} — {first[:52]}"

        # [🔴 순서가 검색을 결정한다 — 2026-08-14 실측] pg_vector_search가 임베딩하는 텍스트는
        #   `title || LEFT(content, 400)`이다. 처음엔 "## 어디 / 파일경로 / 추출 시점"을 앞에
        #   뒀는데, 그 머리말이 400자의 절반을 먹어 **지식 본문이 임베딩에 거의 안 들어갔다.**
        #   그 결과 관련 질의 최고 유사도가 0.465에 그쳐 임계 0.58에 전부 걸러졌다(회상 0건).
        #   지식을 맨 앞에, 위치·앵커 같은 메타데이터를 뒤로 보낸다. 사람이 읽는 순서와도 같다.
        parts = []
        for b in bs:
            parts.append(f"### {' '.join('[' + t + ']' for t in b['tags'])}")
            parts.append(b['body'])
            parts.append("")
        parts += ["---", f"📍 `{rel}:{bs[0]['line']}` · `{sym_label}`  (추출 시점 {head})"]
        anchors = [a for b in bs for a in b['anchor']][:6]
        if anchors:
            lang = 'python' if rel.endswith('.py') else 'ts'
            parts += ["", f"```{lang}", *anchors, "```"]

        source_ref = f"code:{rel}#{symbol}"
        notes.append({
            'id': 'k-' + hashlib.sha1(source_ref.encode('utf-8')).hexdigest()[:12],
            'title': title,
            'content': '\n'.join(parts).strip(),
            'source_ref': source_ref,
            'tags': ['knowledge', 'code'] + all_tags + [Path(rel).stem],
        })
    return notes


def upsert_notes(notes: list[dict], project_id: str, dry_run: bool) -> dict:
    """멱등 저장. 같은 id가 있으면 갱신, 없으면 생성."""
    created = updated = failed = 0
    for nt in notes:
        if dry_run:
            created += 1
            continue
        existing = zk._get_note_raw(nt['id'])
        if existing:
            ok = zk.update_note(nt['id'], title=nt['title'], content=nt['content'],
                                tags=nt['tags'], source_ref=nt['source_ref'],
                                note_type='permanent', archived=False)
            updated += 1 if ok else 0
            failed += 0 if ok else 1
        else:
            ok = zk.create_note(
                title=nt['title'], content=nt['content'], note_type='permanent',
                author='knowledge_extract', project_id=project_id,
                tags=nt['tags'], source_ref=nt['source_ref'], custom_id=nt['id'])
            created += 1 if ok else 0
            failed += 0 if ok else 1
    return {'created': created, 'updated': updated, 'failed': failed}


def prune_stale(live_ids: set, project_id: str, dry_run: bool) -> int:
    """원본이 사라진 지식 노트를 아카이브(삭제 아님).

    [🔴 왜 필요한가] 2026-08-14 실측: 이미 철거된 아픽스 파일(jobs_api·central_e2e 등)의
      노트 18건이 살아서 회상에 섞이고 있었다. 없는 파일의 지식이 검색되면 다음 세션이
      존재하지 않는 코드를 전제로 판단한다 — 노이즈보다 나쁘다.
    """
    from src.pg_base import query_rows
    rows = query_rows(
        "SELECT id FROM zettel_notes WHERE archived = false "
        "AND author = 'knowledge_extract'"
    )
    stale = [r['id'] for r in rows if r['id'] not in live_ids]
    if not dry_run:
        for sid in stale:
            zk.update_note(sid, archived=True)
    return len(stale)


def main() -> int:
    ap = argparse.ArgumentParser(
        description='코드 주석의 지식([WHY]/[불변식]/[제약]/[과거사고])을 제텔카스텐으로 이송')
    ap.add_argument('--dry-run', action='store_true', help='DB에 쓰지 않고 통계만')
    ap.add_argument('--prune', action='store_true', help='원본이 사라진 지식 노트 아카이브')
    ap.add_argument('--project', default='', help='project_id (기본: 현재 프로젝트)')
    ap.add_argument('--show', type=int, default=0, help='샘플 노트 N건 출력')
    args = ap.parse_args()

    project_id = args.project or slugify(_PROJECT_ROOT)
    head = _git_head()

    blocks = []
    for f in iter_source_files(_PROJECT_ROOT):
        blocks.extend(extract_blocks(f, _PROJECT_ROOT))
    notes = build_notes(blocks, head)

    print(f"스캔 완료 — 지식 블록 {len(blocks)}개 → 노트 {len(notes)}건 "
          f"(project={project_id}, HEAD={head})")
    if args.show:
        for nt in notes[:args.show]:
            print('\n' + '=' * 70)
            print(nt['title'])
            print('-' * 70)
            print(nt['content'][:900])

    res = upsert_notes(notes, project_id, args.dry_run)
    print(f"{'[dry-run] ' if args.dry_run else ''}저장 — 생성 {res['created']} / "
          f"갱신 {res['updated']} / 실패 {res['failed']}")

    if args.prune:
        n = prune_stale({nt['id'] for nt in notes}, project_id, args.dry_run)
        print(f"{'[dry-run] ' if args.dry_run else ''}아카이브(원본 소멸) — {n}건")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
