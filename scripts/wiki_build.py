"""
FILE: scripts/wiki_build.py
DESCRIPTION: 원료(코드 주석 · 사고 장부 · 세션 메모리)를 wiki/ 백과사전 페이지로 합성한다.
             knowledge_extract 는 주석을 뽑아 **DB 노트**를 만들지만, 이쪽은 같은 원료로
             **사람이 읽는 페이지**를 만든다 — 정본은 파일이고 DB 는 인덱스이기 때문이다.

REVISION HISTORY:
- 2026-08-15 Claude: 신설 — LLM 위키 전환 W2·W3·W4. 지식 창고를 로그 덤프에서
  백과사전으로 바꾸는 첫 산출 단계.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / '.ai_monitor'))

import knowledge_extract as ke  # noqa: E402  (경로 주입 후 import)

WIKI = ROOT / 'wiki'
TODAY = '2026-08-15'

# 주제 지도 — 파일명(basename) → 백과사전 항목명.
#
# [🔴 WHY 파일명으로 페이지를 만들지 않는가] 첫 구현은 파일당 1장이었고 결과가
#   `pg_vector_search.py.md`, `boot.py.md` 같은 71장이었다. 그건 백과사전이 아니라
#   **코드 트리를 마크다운으로 옮겨 적은 것**이다. 사람은 "회상이 어떻게 되더라"를
#   찾지 `pg_vector_search.py`를 찾지 않는다. LLM 위키의 요지도 "소스를 이해해서
#   **분류 체계를 만든다**"는 데 있다 — 원본 구조를 복사하면 그 단계를 건너뛴 것이다.
# [WHY basename 매칭인가] 경로가 아니라 파일명으로 건다. server.py 분할처럼 파일이
#   디렉토리를 옮겨도 주제는 그대로이기 때문이다(경로로 걸면 이동 때마다 지도가 썩는다).
# [불변식] 여기 없는 파일은 디렉토리 라벨로 폴백한다 — 빠뜨려도 지식이 사라지지 않고
#   '미분류' 페이지에 모인다(조용한 유실 방지). lint 가 미분류 누적을 경고한다.
TOPICS: dict[str, list[str]] = {
    '회상과 지식 창고': [
        'pg_vector_search.py', 'embed_service.py', 'knowledge_extract.py', 'wiki_build.py',
        'zettel_sync.py', 'zettel_capture.py', 'zettelkasten.py', 'recall_client.py',
        'heal_metrics.py', 'memory_api.py', 'fix_corrupted_titles.py', 'memory_watcher.py',
    ],
    '데몬과 콘솔 창': [
        'daemons.py', 'tools_api.py', 'console_scan.py', 'heartbeat_daemon.py',
        'proc.py', 'test_daemon_toggles.py',
    ],
    '터미널과 PTY': [
        'pty_process.py', 'pty_api.py', 'TerminalSlot.tsx', 'app_boot.py',
        'xtermSelection.ts', 'AgentSelectCards.tsx',
    ],
    '세션 연속성과 리사이클': [
        'session_recycle.py', 'recycle_api.py', 'session_binding.py',
        'hook_bridge.py', 'hive_hook.py', 'brief_limits.py',
    ],
    '업데이트와 배포': [
        'updater.py', 'update_api.py', 'soft_updater.py', 'boot.py',
        'make_source_package.py', 'smoke_test.py', 'create_shortcut.py',
    ],
    'LAN 브리지와 원격 실행': [
        'lan_api.py', 'lan_bridge.py', 'lan_sandbox.py', 'LanPanel.tsx', 'agent_api.py',
    ],
    '음성 입출력': [
        'voice_server.py', 'voice_api.py', 'voiceBus.ts', 'speech.ts',
        'audioCapture.ts', 'VoiceBar.tsx',
    ],
    'PostgreSQL 저장 계층': [
        'pg_base.py', 'pg_schema.py', 'pg_store.py', 'pg_office.py', 'db_helper.py',
    ],
    '프로젝트 경계와 식별': [
        'generate_project_map.py', 'env_path.py', 'instance_lock.py', 'projects_api.py',
    ],
    '설치와 환경 진단': [
        'setup_doctor.py', 'install_api.py', 'tool_install.py', 'setup_voice.py',
    ],
    '서버와 라우팅': [
        'server.py', 'test_route_table.py', 'hive_api.py', 'events_api.py',
    ],
    '프론트엔드 상태 관리': [
        'App.tsx', 'statusline.py', 'antigravity_adapter.py', 'tui.py',
    ],
}

# basename → 주제 (역인덱스). [제약] 같은 파일을 두 주제에 넣으면 뒤엣것이 이긴다 —
#   한 블록은 한 페이지에만 있어야 하므로(중복 임베딩 금지) 의도적으로 단일 매핑이다.
_FILE_TOPIC: dict[str, str] = {
    fname: topic for topic, files in TOPICS.items() for fname in files
}

# 디렉토리 → 사람이 읽는 이름. 주제 지도에 없는 파일의 폴백.
DIR_LABEL = {
    '.ai_monitor/api': 'API 계층',
    '.ai_monitor/src': '데이터 계층',
    '.ai_monitor/infra': '인프라 계층',
    '.ai_monitor/vibe-view': '프론트엔드',
    '.ai_monitor/voice-server': '음성 사이드카',
    '.ai_monitor/pty-server': 'PTY 서버',
    'scripts': '스크립트',
    'tests': '테스트',
}

_SAFE_RE = re.compile(r'[/\\:*?"<>|]')


def _safe_name(name: str) -> str:
    """파일명 금지문자 제거. [제약] 한글·공백은 남긴다 — 규약이 '사람 말과 일치하는
    파일명'을 요구한다(옵시디언 검색과 회상 제목이 같아야 사람이 찾을 수 있다)."""
    return _SAFE_RE.sub('-', name).strip() or 'untitled'


def _dir_label(rel: str) -> str:
    parts = rel.split('/')
    for depth in (2, 1):
        key = '/'.join(parts[:depth])
        if key in DIR_LABEL:
            return DIR_LABEL[key]
    return '/'.join(parts[:2]) if len(parts) > 1 else parts[0]


def _one_liner(body: str, limit: int = 90) -> str:
    """페이지 맨 앞 '## 한 줄'용 요약. 회상에서 이 문장만 보고 열지 말지 결정된다."""
    first = ke._summary_line(body).replace('\n', ' ').strip()
    return first[:limit] + ('…' if len(first) > limit else '')


# ── 원료 1: 코드 주석 ────────────────────────────────────────────────────────

def collect_blocks() -> list[dict]:
    blocks: list[dict] = []
    for path in ke.iter_source_files(ROOT):
        blocks += ke.extract_blocks(path, ROOT)
    return blocks


def plan_pages(blocks: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """블록을 (섹션, 페이지명)으로 배치한다.

    [WHY 과거사고를 따로 빼나] '함정'은 조회 동기가 다르다 — 시스템 페이지는 "이게 어떻게
      도나"를 알고 싶을 때 열고, 함정 페이지는 "여기서 뭘 밟았었나"를 알고 싶을 때 연다.
      같은 페이지에 섞으면 사고 95건이 설명 601건에 묻혀 재발 방지 기능을 잃는다.
    [불변식] 한 블록은 정확히 한 페이지에만 들어간다. 중복 배치하면 같은 문장이 두 벌
      임베딩돼 회상 상위를 자기 자신으로 채운다.
    """
    pages: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for b in blocks:
        rel = b['file']
        topic = _FILE_TOPIC.get(Path(rel).name) or f'{_dir_label(rel)} · 그 밖'
        section = '함정' if '과거사고' in b['tags'] else '시스템'
        name = f'{topic} 함정' if section == '함정' else topic
        pages[(section, name)].append(b)
    return pages


def render_page(section: str, name: str, blocks: list[dict], head: str) -> str:
    """페이지 1장을 마크다운으로. 규약(.claude/rules/wiki.md) 4절 형식을 따른다."""
    blocks = sorted(blocks, key=lambda b: (b['file'], b['line']))
    files = sorted({b['file'] for b in blocks})
    tags = sorted({t for b in blocks for t in b['tags']})

    # [WHY sources 를 20개로 자르나] 프론트매터가 본문보다 길어지면 사람이 못 읽고,
    #   wiki_lint 의 출처 검사도 느려진다. 전체 목록은 본문 각 항목에 그대로 남는다.
    src_lines = [f'  - {b["file"]}:{b["line"]}' for b in blocks[:20]]
    if len(blocks) > 20:
        src_lines.append(f'  # …외 {len(blocks) - 20}건 (본문 각 항목에 경로 표기)')

    out = [
        '---',
        f'title: {name}',
        f'type: {section}',
        'sources:',
        *src_lines,
        'related: []',
        'confidence: high',
        f'updated: {TODAY}',
        '---',
        '',
        f'# {name}',
        '',
        '## 한 줄',
        '',
        _one_liner(blocks[0]['body']),
        '',
        f'> 코드 주석에서 자동 합성 (원료 {len(blocks)}건 · 파일 {len(files)}개 · 추출 {head}).',
        '> 🔴 **여기를 고치기 전에** 원본 주석을 먼저 고칠 것 — 다음 빌드에 덮어써진다.',
        '',
    ]

    by_file: dict[str, list[dict]] = defaultdict(list)
    for b in blocks:
        by_file[b['file']].append(b)

    for rel in files:
        bs = by_file[rel]
        out.append(f'## `{rel}`')
        out.append('')
        for b in bs:
            sym = b['symbol'] if b['symbol'] != '(모듈)' else '모듈 상단'
            tag_str = ' '.join(f'`[{t}]`' for t in b['tags'])
            out.append(f'### {sym} {tag_str}')
            out.append('')
            out.append(b['body'])
            out.append('')
            out.append(f'출처: `{rel}:{b["line"]}`')
            out.append('')

    out += [
        '## 확인법',
        '',
        '```bash',
        'python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지',
        'python scripts/wiki_build.py       # 원본 주석 변경분 재합성',
        '```',
        '',
        f'<!-- tags: {", ".join(tags)} -->',
        '',
    ]
    return '\n'.join(out)


# ── 쓰기 ────────────────────────────────────────────────────────────────────

def write_if_changed(path: Path, content: str) -> bool:
    """내용이 실제로 달라졌을 때만 쓴다.

    [🔴 과거사고 c7a42f2] 무조건 write_text 를 부르면 mtime 이 매번 갱신되고, 그걸 본
      GDrive/FS 워처가 전량 재복사를 돌아 3단 핑퐁이 생겼다(앱 상시 CPU 점유의 원인).
      해시 비교는 이 파이프라인 전체의 안전 장치다 — 허브 미러(W9)도 같은 규칙을 쓴다.
    """
    if path.exists():
        old = path.read_text(encoding='utf-8', errors='ignore')
        if hashlib.sha1(old.encode()).digest() == hashlib.sha1(content.encode()).digest():
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return True


def update_index(written: dict[str, list[str]]) -> bool:
    """INDEX.md 의 목차 4개 섹션을 갱신. 그 밖의 손으로 쓴 부분은 건드리지 않는다.

    [제약] 섹션 헤더(`### 개념 — …`) 사이 구간만 교체한다. 통째로 다시 쓰면 사람이
      INDEX 에 적어둔 안내문이 매 빌드마다 날아간다.
    """
    idx = WIKI / 'INDEX.md'
    text = idx.read_text(encoding='utf-8')
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.match(r'^### (개념|시스템|함정|결정) — ', line)
        if not m:
            i += 1
            continue
        section = m.group(1)
        i += 1
        while i < len(lines) and not lines[i].startswith('### ') and not lines[i].startswith('## '):
            i += 1
        entries = sorted(written.get(section, []))
        out.append('')
        if entries:
            for name in entries:
                out.append(f'- [{name}]({section}/{_safe_name(name)}.md)')
        else:
            out.append('_(아직 없음)_')
        out.append('')
    return write_if_changed(idx, '\n'.join(out) + '\n')


def build(dry_run: bool = False) -> dict:
    head = ke._git_head()
    blocks = collect_blocks()
    pages = plan_pages(blocks)

    written: dict[str, list[str]] = defaultdict(list)
    changed = kept = 0
    for (section, name), bs in pages.items():
        written[section].append(name)
        if dry_run:
            continue
        path = WIKI / section / f'{_safe_name(name)}.md'
        if write_if_changed(path, render_page(section, name, bs, head)):
            changed += 1
        else:
            kept += 1

    if not dry_run:
        update_index(written)
        # 첫 페이지가 들어온 섹션의 자리표시자는 역할이 끝났다.
        for section in written:
            ph = WIKI / section / '_placeholder.md'
            if ph.exists():
                ph.unlink()

    return {
        'blocks': len(blocks),
        'pages': sum(len(v) for v in written.values()),
        'changed': changed,
        'kept': kept,
        'by_section': {k: len(v) for k, v in written.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='원료 → wiki/ 페이지 합성')
    ap.add_argument('--dry-run', action='store_true', help='쓰지 않고 통계만')
    ap.add_argument('--stats', action='store_true', help='페이지 수/커버리지 출력')
    args = ap.parse_args()

    st = build(dry_run=args.dry_run or args.stats)
    print(f"원료 블록 {st['blocks']}건 → 페이지 {st['pages']}장")
    for sec, n in sorted(st['by_section'].items()):
        print(f"  {sec:6s} {n:3d}장")
    if not (args.dry_run or args.stats):
        print(f"변경 {st['changed']}장 / 그대로 {st['kept']}장")
    if st['pages'] > 150:
        print(f"🔴 150장 상한 초과({st['pages']}) — 규칙 2 위반. 합치거나 버릴 것")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
