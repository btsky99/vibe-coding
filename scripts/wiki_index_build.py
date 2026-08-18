# -*- coding: utf-8 -*-
"""
FILE: scripts/wiki_index_build.py
DESCRIPTION: LLM 위키 색인 생성기 — 낱말(FTS5) + 뜻(임베딩)을 **한 파일**에 만든다.

             [정본은 wiki/*.md 다] 이 색인은 파생물이라 언제든 지우고 다시 만든다.
             그래서 .gitignore 에 들어간다(정본이 둘이면 언젠가 어긋난다).

             [🔴 왜 벡터를 pgvector 가 아니라 이 파일에 두는가 — 2026-08-18 판단]
               결재 42 의 조건이 "Postgres 를 건드리지 마라 — 스키마도 데이터도 연결도" 다.
               위키용 표를 PG 에 새로 만드는 것은 그 문면을 넘는다. 그런데 벡터를 쓰는 데
               PG 가 꼭 필요하지는 않다 — **필요한 것은 임베딩 모델이고 그건 이미 있다**
               (infra/embed_service, e5-small-ml/384차원). 43장 규모에서 코사인 전수 계산은
               수 ms 라 인덱스 구조가 필요 없다.
               [불변식] 모델·차원은 **기존 것을 그대로** 쓴다(EMBED_SIGNATURE 를 함께 저장).
                 다른 모델로 구우면 zettel 5,206건과 섞이지 않는다.
               [나중에] 위키가 커져 zettel 창고와 합쳐질 때가 오면 그때 pgvector 로 옮긴다.
                 그 시점의 신호는 '전수 계산이 느려질 때'이고, 지금은 아니다.

             [🔴 낱말 쪽을 대충 만들지 않는다] 고유명사·파일명·오류 메시지
               (`voiceBus.ts:999`, `empty_note`)는 **벡터가 오히려 못 찾는다.** 그 자리를
               낱말이 맡아야 하이브리드가 성립한다. 그래서 FTS5 를 곁들이기가 아니라
               한 축으로 짠다.

             [사용]
               python scripts/wiki_index_build.py              # 색인 생성(전체 재작성)
               python scripts/wiki_index_build.py --search "질문"   # 찔러 보기
               python scripts/wiki_index_build.py --no-vector  # 낱말만(모델 없이)

REVISION HISTORY:
- 2026-08-18 Claude: 최초 작성 — 경량화 3단계. 낱말+뜻 하이브리드, 근거 표시, 빈 결과 허용.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / 'wiki'
INDEX_DIR = WIKI / '.index'
DB_PATH = INDEX_DIR / 'wiki.sqlite3'

# [🔴 문턱은 새로 정하지 않는다] pg_vector_search._FLOOR 와 같은 값이다. e5-small-ml 은
#   유사도가 0.8 근처 좁은 띠에 몰려서, 예전 MiniLM 시절 값(0.45~0.55)은 **아무것도 못 거른다**
#   (그 파일의 실측 주석 참조). 두 곳이 갈리면 같은 창고가 다른 기준으로 걸러진다.
VEC_FLOOR = 0.86

# 낱말 쪽 점수 하한. FTS5 bm25 는 낮을수록 좋은 값이라 부호를 뒤집어 쓴다.
LEX_FLOOR = 0.0


def _sections(md: Path) -> list[tuple[str, str]]:
    """문서를 `##` 제목 단위로 자른다. (제목, 본문)

    [WHY 문서 통째가 아닌가] 위키 한 장이 두꺼워지는 것을 규약이 권장한다(규칙 1·2).
      통째로 임베딩하면 긴 문서일수록 뜻이 뭉개져, 두껍게 쓸수록 안 걸리는 역설이 생긴다.
    [WHY `##` 인가] 규약이 `## 한 줄`·`## 🔴 함정`·`## 확인법` 을 쓰라고 정해 두었다 —
      사람이 나눈 경계가 이미 있는데 기계가 다시 나눌 이유가 없다.
    """
    text = md.read_text(encoding='utf-8', errors='replace')
    # 프론트매터 제거 — 검색 결과에 title/updated 가 섞여 나오면 사람이 못 읽는다.
    text = re.sub(r'\A---\n.*?\n---\n', '', text, flags=re.S)
    out, title, buf = [], '(머리말)', []
    for line in text.splitlines():
        m = re.match(r'^##\s+(.*)', line)
        if m:
            if ''.join(buf).strip():
                out.append((title, '\n'.join(buf).strip()))
            title, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if ''.join(buf).strip():
        out.append((title, '\n'.join(buf).strip()))
    return out


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f'{len(vec)}f', *vec)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f'{len(blob) // 4}f', blob))


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1e-9
    db = math.sqrt(sum(y * y for y in b)) or 1e-9
    return num / (da * db)


def _embedder():
    """기존 임베딩 서비스. 없으면 None — 낱말만으로도 색인은 성립해야 한다."""
    try:
        sys.path.insert(0, str(ROOT / '.ai_monitor'))
        from infra.embed_service import EMBED_SIGNATURE, embed_floats
        return embed_floats, EMBED_SIGNATURE
    except Exception as e:                                   # noqa: BLE001
        print(f'[wiki-index] 임베딩 모델 없음 — 낱말 색인만 만듭니다 ({type(e).__name__})')
        return None, ''


def build(use_vector: bool = True) -> int:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()                       # [불변식] 늘 통째로 다시 만든다 — 부분 갱신은
                                               #   '무엇이 최신인가'를 또 하나의 정본으로 만든다.
    embed, sig = _embedder() if use_vector else (None, '')
    con = sqlite3.connect(DB_PATH)
    con.execute('CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)')
    con.execute('CREATE TABLE sec(id INTEGER PRIMARY KEY, path TEXT, title TEXT, '
                'body TEXT, vec BLOB)')
    # unicode61 + remove_diacritics 0 — 한글이 깨지지 않게. tokenchars 로 `voiceBus.ts:999`
    # 같은 고유명사가 통째로 한 낱말이 되게 한다(벡터가 못 잡는 자리를 여기서 잡는다).
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(title, body, content='sec', "
                "content_rowid='id', tokenize=\"unicode61 remove_diacritics 0 "
                "tokenchars '._:-/'\")")
    n_sec = n_vec = 0
    for md in sorted(WIKI.rglob('*.md')):
        if INDEX_DIR in md.parents:
            continue
        rel = md.relative_to(ROOT).as_posix()
        for title, body in _sections(md):
            vec = None
            if embed is not None:
                try:
                    v = embed(f'{title}\n{body}', kind='passage')
                    if v:
                        vec, n_vec = _pack(v), n_vec + 1
                except Exception:                            # noqa: BLE001
                    vec = None                               # 한 조각 실패가 색인을 막지 않는다
            con.execute('INSERT INTO sec(path,title,body,vec) VALUES(?,?,?,?)',
                        (rel, title, body, vec))
            n_sec += 1
    con.execute("INSERT INTO fts(rowid,title,body) SELECT id,title,body FROM sec")
    con.executemany('INSERT INTO meta(k,v) VALUES(?,?)', [
        ('embed_signature', sig),
        ('sections', str(n_sec)),
        ('vectors', str(n_vec)),
        ('source_sha', hashlib.sha1(
            ''.join(sorted(p.as_posix() for p in WIKI.rglob('*.md'))).encode()).hexdigest()[:12]),
    ])
    con.commit()
    con.close()
    print(f'[wiki-index] 완료 — 조각 {n_sec}개 · 벡터 {n_vec}개 → {DB_PATH.relative_to(ROOT)}')
    return 0


def search(query: str, limit: int = 5) -> int:
    """낱말·뜻 두 순위를 RRF 로 합친다. **왜 나왔는지 함께 낸다.**

    [🔴 왜 근거를 보여 주나] 왜 걸렸는지 안 보이면 사람도 LLM 도 그 결과를 안 믿는다.
      믿지 못하는 회상은 안 쓰느니만 못하다 — 읽고 판단하는 비용만 든다.
    [🔴 빈 결과가 나올 수 있어야 한다] 벡터는 언제나 '가장 가까운 이웃'을 돌려주지 0점을
      못 낸다. 문턱(VEC_FLOOR) 아래는 버린다. 무관한 것을 주입하는 노이즈는 **놓치는 것보다
      비싸다** — 회상 전체의 신뢰가 무너지기 때문이다(이 저장소가 2026-08 에 겪은 그것).
    """
    if not DB_PATH.exists():
        print('[wiki-index] 색인이 없습니다 — 먼저 인자 없이 실행하세요')
        return 1
    con = sqlite3.connect(DB_PATH)
    rank: dict[int, dict] = {}

    # ── 낱말 ──────────────────────────────────────────────────────────────
    # [제약] FTS5 는 특수문자를 연산자로 읽는다. 통째 구문으로 감싸 그대로 찾게 한다.
    q = '"' + query.replace('"', ' ') + '"'
    try:
        for i, (sid, score) in enumerate(con.execute(
                'SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ? '
                'ORDER BY bm25(fts) LIMIT 20', (q,))):
            rank.setdefault(sid, {'why': [], 'rrf': 0.0})
            rank[sid]['why'].append('낱말')
            rank[sid]['rrf'] += 1.0 / (60 + i + 1)           # RRF, k=60
            rank[sid]['lex'] = -score
    except sqlite3.OperationalError as e:
        print(f'[wiki-index] 낱말 검색 건너뜀: {e}')

    # ── 뜻 ────────────────────────────────────────────────────────────────
    embed, _sig = _embedder()
    if embed is not None:
        qv = embed(query, kind='query')
        if qv:
            sims = []
            for sid, blob in con.execute('SELECT id, vec FROM sec WHERE vec IS NOT NULL'):
                s = _cos(qv, _unpack(blob))
                if s >= VEC_FLOOR:                            # 위 [빈 결과] 주석 참조
                    sims.append((s, sid))
            sims.sort(reverse=True)
            for i, (s, sid) in enumerate(sims[:20]):
                rank.setdefault(sid, {'why': [], 'rrf': 0.0})
                rank[sid]['why'].append('뜻')
                rank[sid]['rrf'] += 1.0 / (60 + i + 1)
                rank[sid]['sim'] = s

    if not rank:
        print('[wiki-index] 걸린 것 없음 — 위키에 그 얘기가 없습니다')
        return 0
    rows = sorted(rank.items(), key=lambda kv: -kv[1]['rrf'])[:limit]
    for sid, info in rows:
        path, title = con.execute('SELECT path,title FROM sec WHERE id=?', (sid,)).fetchone()
        why = '+'.join(dict.fromkeys(info['why']))            # 낱말 / 뜻 / 낱말+뜻
        extra = f" sim={info['sim']:.3f}" if 'sim' in info else ''
        print(f'  [{why}]{extra}  {path}  ## {title}')
    con.close()
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--search')
    ap.add_argument('--no-vector', action='store_true')
    a = ap.parse_args()
    sys.exit(search(a.search) if a.search else build(not a.no_vector))
