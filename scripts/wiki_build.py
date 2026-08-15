"""
FILE: scripts/wiki_build.py
DESCRIPTION: 원료(코드 주석 · 사고 장부 · 세션 메모리)를 wiki/ 백과사전 페이지로 합성한다.
             knowledge_extract 는 주석을 뽑아 **DB 노트**를 만들지만, 이쪽은 같은 원료로
             **사람이 읽는 페이지**를 만든다 — 정본은 파일이고 DB 는 인덱스이기 때문이다.

REVISION HISTORY:
- 2026-08-15 Claude: W3·W4 — 원료에 사고 장부(incident_ledger)와 세션 메모리(memory/)를
  추가. 사고는 기존 함정 페이지에 **병합**한다(규칙 1: 추가가 아니라 덮어쓰기).
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


# ── 원료 2: 사고 장부 (incident_ledger) ─────────────────────────────────────
#
# [🔴 WHY 파일명 매핑만으로는 안 되는가 — 2026-08-15 실측] 사고 120건 중 `files` 컬럼이
#   채워진 건 **10건뿐**이다(incident.py record 가 --files 를 거의 안 받고 기록돼 왔다).
#   본문에서 `xxx.py` 를 긁어 TOPICS 로 보내도 37건밖에 안 붙는다. 나머지 83건은 파일명이
#   아니라 증상으로만 적혀 있어서("업데이트 후 DLL 로드 실패"), 키워드 라우터가 필수다.
# [불변식] 아래 목록은 위에서부터 첫 일치가 이긴다 — 좁은 주제를 먼저 둔다.
#   예: '설치'는 업데이트 사고에도 흔히 나오므로 '업데이트' 계열보다 뒤에 온다.
INCIDENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    # 타 프로젝트 사고 — 이 리포의 지식이 아니다. 아래 '격리' 주석 참조.
    ('다른 프로젝트', (
        '아픽스', 'apix', 'na2js', '중앙 대화', 'herdr', 'hbbs', 'rustdesk',
        'ciphertrader', 'build_unified', 'tpsl', 'rl_done', 'zig',
        'certbot', 'acme', 'admin.btsky', 'vps',
    )),
    ('음성 입출력', ('음성', '마이크', '목소리', 'tts', 'stt', '사이드카')),
    ('회상과 지식 창고', (
        '회상', 'recall', '볼트', '옵시디언', 'zettel', '제텔', '임베딩',
        '지식', '세션요약', 'ref_count', 'hive_memory',
    )),
    ('세션 연속성과 리사이클', ('리사이클', 'drain', 'active_session_context', '재정박')),
    ('업데이트와 배포', (
        'soft-update', 'soft update', 'soft 채널', 'reset --hard', '릴리즈', '태그',
        'python dll', 'temporary directory', '업데이트', 'auto_version', 'inno setup',
        '설치 마법사', '진행률', '경량 소스',
    )),
    ('설치와 환경 진단', (
        'deletefile', '액세스 거부', '레지스트리', '미설치', '설치팩', '설치 중',
        'msvcp140', 'libcrypto', '설치본', '설치 시', '설치 버전',
    )),
    ('LAN 브리지와 원격 실행', ('lan', '샌드박스', 'sandbox', 'ssh', '터널', '원격', '텔레그램')),
    ('데몬과 콘솔 창', (
        'heartbeat', '데몬', '콘솔 창', '콘솔창', '깜빡', 'enumwindows', 'conhost',
        '워치독', 'watchdog', '자율', 'hang', '오케스트레이션',
    )),
    ('터미널과 PTY', (
        'pty', '터미널', '슬롯', 'xterm', '드래그 선택', '우클릭', 'api_terminate',
    )),
    ('PostgreSQL 저장 계층', (
        'psql', 'pg_hba', 'postgres', 'notify', 'payload', '5433', 'psycopg',
    )),
    ('프로젝트 경계와 식별', (
        '프로젝트 폴더', '슬러그', 'project_id', '폴더 변경', '다른 프로젝트의',
        '활성 프로젝트', '폴더 선택',
    )),
    # [불변식] 주제명은 코드 주석 페이지가 이미 만든 이름과 **정확히 같아야** 한다.
    #   '테스트'로 쓰면 `테스트 함정`이 새로 생겨 `테스트 · 그 밖 함정`과 갈라진다 —
    #   같은 주제가 두 장이 되는 순간 둘 다 신뢰를 잃는다(규약 5절).
    ('테스트 · 그 밖', ('pytest', 'e2e', 'smoke', '테스트', 'capsys')),
    ('서버와 라우팅', ('서버', '포트', '라우트', 'http_port', '404', 'failed to fetch')),
    ('프론트엔드 상태 관리', ('상태줄', 'statusline', '위젯', 'ui ')),
]

# [WHY 지우지 않고 한 장에 격리하나] 아픽스·CipherTrader·RustDesk 사고는 이 리포의 지식이
#   아니다(계획서 '이 프로젝트에 넣지 않는 것'). 그렇다고 버리면 사고 장부의 재발 방지
#   기능이 조용히 사라진다. 12개 주제 페이지를 오염시키지 않으면서 유실도 없게 —
#   한 페이지에 몰아 격리하고, 경계 자체를 눈에 보이게 만든다.
_QUARANTINE = '다른 프로젝트'

_FN_RE = re.compile(r'[\w\-]+\.(?:py|tsx|ts|iss|spec|json|yml|yaml|sql|ps1|bat|cmd)')


def collect_incidents() -> list[dict]:
    """사고 장부를 읽어온다. DB 가 없으면 빈 목록 — 위키 빌드 자체는 계속돼야 한다.

    [제약] 이 스크립트는 설치본(W10 리셋 API)에서도 불린다. PG 가 아직 안 떴을 수 있어
      예외를 삼키고 원료 0건으로 진행한다 — 사고 섹션만 비고 코드 주석 페이지는 나온다.
    """
    try:
        from src.pg_base import query_rows
        rows = query_rows(
            "SELECT error_signature, error_text, root_cause, fix_description, "
            "fix_commit, files, recurrence_count, created_at, last_seen_at "
            "FROM incident_ledger ORDER BY recurrence_count DESC, created_at"
        )
    except Exception as exc:  # noqa: BLE001 — 원료 하나가 없다고 빌드를 죽이지 않는다
        print(f'  (사고 장부 건너뜀: {exc})')
        return []

    seen: set[str] = set()
    out = []
    for r in rows:
        sig = str(r.get('error_signature') or '')
        if sig and sig in seen:
            continue  # 같은 서명이 두 행이면 장부 쪽 중복 — recurrence_count 가 정본이다
        seen.add(sig)
        out.append(r)
    return out


def _incident_topic(inc: dict) -> str:
    """사고 1건이 어느 주제 페이지로 갈지. 파일명 우선 → 키워드 → '그 밖'."""
    files = inc.get('files')
    if isinstance(files, str):
        try:
            import json
            files = json.loads(files)
        except Exception:
            files = []
    text = ' '.join(str(inc.get(k) or '')
                    for k in ('error_text', 'root_cause', 'fix_description'))

    names = [str(f).split('/')[-1] for f in (files or [])] + _FN_RE.findall(text)
    # [불변식] 키워드보다 파일명이 강하다 — 파일명은 사람이 지목한 것이고
    #   키워드는 추론이다. 단 격리 대상 키워드는 파일명보다도 먼저 본다(아래).
    low = text.lower()
    if any(k in low for k in dict(INCIDENT_KEYWORDS)[_QUARANTINE]):
        return _QUARANTINE
    for n in names:
        if n in _FILE_TOPIC:
            return _FILE_TOPIC[n]
    for topic, keys in INCIDENT_KEYWORDS:
        if any(k in low for k in keys):
            return topic
    return '분류 미정'


def plan_incidents(incidents: list[dict]) -> dict[str, list[dict]]:
    """사고를 주제별로 묶는다. 키는 **함정 페이지 이름** — 코드 주석 페이지와 같은 키를
    쓰므로 한 파일 안에서 자연히 병합된다(규칙 1)."""
    out: dict[str, list[dict]] = defaultdict(list)
    for inc in incidents:
        out[f'{_incident_topic(inc)} 함정'].append(inc)
    return out


def _fmt_date(v) -> str:
    return str(v)[:10] if v else '?'


def render_incidents(incidents: list[dict]) -> list[str]:
    """사고를 증상/원인/수정 3단으로. 재발 건이 위로 온다(자주 밟은 것부터 읽게)."""
    incidents = sorted(
        incidents,
        key=lambda r: (-int(r.get('recurrence_count') or 1), str(r.get('created_at'))),
    )
    out = ['## 🔴 밟았던 것 (사고 장부)', '']
    repeats = [r for r in incidents if int(r.get('recurrence_count') or 1) > 1]
    if repeats:
        out += [f'> 재발 이력이 있는 사고 {len(repeats)}건이 맨 위에 있다 — '
                '한 번 더 밟기 전에 여기부터 읽을 것.', '']
    for r in incidents:
        n = int(r.get('recurrence_count') or 1)
        head = str(r.get('error_text') or '(증상 미기록)').strip().replace('\n', ' ')
        out.append(f'### {head[:110]}')
        out.append('')
        cause = str(r.get('root_cause') or '').strip()
        fix = str(r.get('fix_description') or '').strip()
        if cause:
            out.append(f'- **원인** — {cause}')
        if fix:
            commit = str(r.get('fix_commit') or '').strip()
            out.append(f'- **수정** — {fix}' + (f' (`{commit}`)' if commit else ''))
        meta = [f'재발 {n}회'] if n > 1 else []
        meta.append(f'최초 {_fmt_date(r.get("created_at"))}')
        if r.get('last_seen_at') and _fmt_date(r['last_seen_at']) != _fmt_date(r.get('created_at')):
            meta.append(f'최근 {_fmt_date(r["last_seen_at"])}')
        out.append(f'- 출처: `incident_ledger` · ' + ' · '.join(meta))
        out.append('')
    return out


def render_page(section: str, name: str, blocks: list[dict], head: str,
                incidents: list[dict] | None = None) -> str:
    """페이지 1장을 마크다운으로. 규약(.claude/rules/wiki.md) 4절 형식을 따른다.

    [불변식] 한 주제 = 한 파일이다. 코드 주석 원료와 사고 장부 원료가 **같은 페이지**에
      들어온다 — 원료가 늘었다고 페이지를 늘리면 규칙 1(추가가 아니라 덮어쓰기)이 깨진다.
    """
    incidents = incidents or []
    blocks = sorted(blocks, key=lambda b: (b['file'], b['line']))
    files = sorted({b['file'] for b in blocks})
    tags = sorted({t for b in blocks for t in b['tags']})

    # [WHY sources 를 20개로 자르나] 프론트매터가 본문보다 길어지면 사람이 못 읽고,
    #   wiki_lint 의 출처 검사도 느려진다. 전체 목록은 본문 각 항목에 그대로 남는다.
    src_lines = [f'  - {b["file"]}:{b["line"]}' for b in blocks[:20]]
    if len(blocks) > 20:
        src_lines.append(f'  # …외 {len(blocks) - 20}건 (본문 각 항목에 경로 표기)')
    if incidents:
        src_lines.append(f'  - incident_ledger  # 사고 {len(incidents)}건')
    if not src_lines:
        src_lines.append('  - incident_ledger')

    origin = []
    if blocks:
        origin.append(f'코드 주석 {len(blocks)}건 · 파일 {len(files)}개')
    if incidents:
        origin.append(f'사고 장부 {len(incidents)}건')

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
        _one_liner(blocks[0]['body']) if blocks
        else _one_liner(str(incidents[0].get('root_cause') or incidents[0].get('error_text') or '')),
        '',
        f'> 자동 합성 ({" · ".join(origin)} · 추출 {head}).',
        '> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — '
        '다음 빌드에 덮어써진다.',
        '',
    ]

    if incidents:
        out += render_incidents(incidents)

    by_file: dict[str, list[dict]] = defaultdict(list)
    for b in blocks:
        by_file[b['file']].append(b)

    if blocks:
        out += ['## 코드에 박힌 지식', '']
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

    incidents = collect_incidents()
    inc_pages = plan_incidents(incidents)
    # 사고만 있고 주석은 없는 주제도 페이지를 가져야 한다 — 없으면 그 사고는 사라진다.
    for iname in inc_pages:
        pages.setdefault(('함정', iname), [])

    written: dict[str, list[str]] = defaultdict(list)
    changed = kept = 0
    for (section, name), bs in pages.items():
        written[section].append(name)
        if dry_run:
            continue
        path = WIKI / section / f'{_safe_name(name)}.md'
        incs = inc_pages.get(name, []) if section == '함정' else []
        if write_if_changed(path, render_page(section, name, bs, head, incs)):
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
        'incidents': len(incidents),
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
    print(f"원료 — 코드 주석 {st['blocks']}건 · 사고 {st['incidents']}건 "
          f"→ 페이지 {st['pages']}장")
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
