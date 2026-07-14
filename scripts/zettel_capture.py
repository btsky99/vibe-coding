# -*- coding: utf-8 -*-
"""
FILE: scripts/zettel_capture.py
DESCRIPTION: 제텔카스텐 자동 캡처 엔진.
             에이전트 작업 이벤트(커밋, 버그수정, 설계결정, 세션종료)를 감지하여
             자동으로 zettel_notes에 지식 노트를 생성하고 Obsidian vault에 동기화한다.

REVISION HISTORY:
    2026-07-14 Claude: dedup LOOKUP을 슬러그 변종 관용(_project_match_sql)으로 근본수정 —
      dev/설치본 VIBE_PROJECT 불일치 재발해도 중복 노트 재축적 방지 (재점검 ④)
    2026-05-02 Codex: DEFAULT_PROJECT를 폴더명 대신 project_id 경로 slug로 변경
    - 서버/DB 표준(D--vibe-coding)과 캡처/Obsidian export 대상이 갈라지는 문제 수정
    2026-04-06 Claude: 초기 구현 — 이벤트별 자동 캡처 + 유사 노트 연결 + vault 동기화
"""

import argparse
import json
import os
import re
import sys
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows UTF-8 보정
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 프로젝트 경로 설정
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_MONITOR_DIR = _PROJECT_ROOT / '.ai_monitor'

sys.path.insert(0, str(_MONITOR_DIR))
sys.path.insert(0, str(_SCRIPT_DIR))

from src.pg_store import ensure_schema, query_rows, _sql_text
from src.zettelkasten import create_note, auto_link, find_similar


# ── 설정 ──────────────────────────────────────────────────────────────────

_appdata = os.environ.get('APPDATA') or str(Path.home())
_default_global_vault = Path(_appdata) / 'VibeCoding' / 'vault' if os.name == 'nt'     else Path.home() / '.vibe-coding' / 'vault'
DEFAULT_VAULT_DIR = Path(os.environ.get('VIBE_VAULT_DIR', str(_default_global_vault)))
_gdrive_env = os.environ.get('VIBE_GDRIVE_VAULT', '')
GDRIVE_VAULT_DIR = Path(_gdrive_env) if _gdrive_env else None
DEFAULT_PROJECT = os.environ.get(
    'VIBE_PROJECT',
    str(_PROJECT_ROOT).replace('\\', '/').replace(':', '').replace('/', '--').lstrip('-'),
)


def _project_slug_variants() -> list[str]:
    """[재발방지] dedup LOOKUP 전용 — 이 프로젝트를 가리키는 동치 슬러그 후보.

    [과거사고] 2026-04~05 슬러그 분열: 같은 파일 노트가 폴더명 슬러그('vibe-coding')와
      경로 슬러그('D--vibe-coding')로 갈려 source_ref dedup이 project_id 정확일치 조건에서
      실패 → 📄 hive_api.py x3 등 중복 축적 + 하이브 조회 고아 49건 (migrate_vault_consolidate로 청산).
    [WHY] 신규 write는 표준 DEFAULT_PROJECT만 쓰되, dedup LOOKUP은 변종까지 훑어야
      dev/설치본(config.json 분리, project_installed_empty_panels 사고) 간 VIBE_PROJECT 불일치가
      재발해도 중복이 다시 쌓이지 않음. source_ref(file-role:<경로>)가 파일 단위 식별자라
      타 프로젝트 오병합 위험 없음.
    """
    variants = {DEFAULT_PROJECT, _PROJECT_ROOT.name}
    return [v for v in variants if v]


def _project_match_sql(col: str = 'project_id') -> str:
    """dedup LOOKUP용 project_id 매칭 절 — 동치 슬러그 IN (...)."""
    return f"{col} IN ({', '.join(_sql_text(v) for v in _project_slug_variants())})"

# 커밋 타입 → 노트 유형 매핑
_COMMIT_TYPE_MAP = {
    'feat':     'fleeting',
    'fix':      'permanent',    # 버그 수정은 영구 지식
    'refactor': 'literature',
    'docs':     'literature',
    'build':    'fleeting',
    'chore':    'fleeting',
    'test':     'fleeting',
}

# 커밋 타입 → 한글 태그 매핑
_COMMIT_TAG_KO = {
    'feat':     '기능',
    'fix':      '수정',
    'refactor': '리팩터링',
    'docs':     '문서',
    'build':    '빌드',
    'chore':    '잡일',
    'test':     '테스트',
}

# 영역 태그 한글 매핑
_AREA_TAG_KO = {
    'ui':       'UI',
    'backend':  '백엔드',
    'db':       'DB',
    'scripts':  '스크립트',
    'hooks':    '훅',
    'test':     '테스트',
}


# ── 캡처 함수 ─────────────────────────────────────────────────────────────

def capture_commit(commit_msg: str, files: list[str] | None = None,
                   agent: str = 'claude') -> dict | None:
    """git commit 감지 → 커밋 유형별 노트 자동 생성.

    커밋 메시지에서 타입(feat/fix/refactor)을 파싱하여 적절한 note_type으로 생성.
    """
    ensure_schema()
    if not commit_msg:
        return None

    # Conventional Commit 타입 파싱: feat(scope): 메시지
    m = re.match(r'^(\w+)(?:\([^)]*\))?[!]?:\s*(.+)', commit_msg.split('\n')[0])
    if m:
        commit_type = m.group(1).lower()
        title = m.group(2).strip()
    else:
        commit_type = 'chore'
        title = commit_msg.split('\n')[0][:80]

    note_type = _COMMIT_TYPE_MAP.get(commit_type, 'fleeting')
    files = files or []

    # 태그 생성 (한글)
    tags = [_COMMIT_TAG_KO.get(commit_type, commit_type)]
    if files:
        # 파일 경로에서 영역 태그 추출 (예: vibe-view → UI, api → 백엔드)
        tags.extend(_extract_area_tags(files))

    # 본문 생성
    content_lines = [f"## 커밋: {commit_type}"]
    content_lines.append(f"\n{commit_msg}")
    if files:
        content_lines.append("\n## 수정 파일")
        for f in files[:20]:  # 최대 20개
            content_lines.append(f"- `{f}`")
    content = '\n'.join(content_lines)

    # 노트 생성
    note = create_note(
        title=title,
        content=content,
        note_type=note_type,
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref=f"git-commit:{commit_type}",
    )

    if note:
        # 유사 노트 자동 연결
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 커밋 노트 생성: {note['id']} — {title} ({note_type})")

    # 변경 파일의 역할 카드 자동 생성/업데이트
    if files:
        capture_file_roles(commit_msg, files=files, agent=agent)

    return note


def capture_fix(file_path: str, old_code: str, new_code: str,
                agent: str = 'claude') -> dict | None:
    """버그 수정 감지 → permanent 노트 (원인 + 해결법)."""
    ensure_schema()
    if not file_path:
        return None

    rel_path = _rel_path(file_path)
    title = f"버그 수정: {rel_path}"
    tags = ['수정', '버그']
    tags.extend(_extract_area_tags([file_path]))

    content = f"## 수정 파일\n`{rel_path}`\n\n"
    if old_code:
        content += f"## 변경 전\n```\n{old_code[:500]}\n```\n\n"
    if new_code:
        content += f"## 변경 후\n```\n{new_code[:500]}\n```\n"

    note = create_note(
        title=title,
        content=content,
        note_type='permanent',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref=f"fix:{rel_path}",
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 버그수정 노트 생성: {note['id']} — {title}")

    return note


def capture_decision(context: str, choice: str, reason: str,
                     agent: str = 'claude') -> dict | None:
    """설계/아키텍처 결정 → permanent 노트."""
    ensure_schema()
    if not choice:
        return None

    title = f"결정: {choice[:60]}"
    tags = ['결정', '아키텍처']

    content = f"## 맥락\n{context}\n\n## 선택\n{choice}\n\n## 이유\n{reason}"

    note = create_note(
        title=title,
        content=content,
        note_type='permanent',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref='decision',
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 결정 노트 생성: {note['id']} — {title}")

    return note


def capture_session(agent: str = 'claude') -> dict | None:
    """세션 종료 → pg_logs 요약 fleeting 노트.

    이번 세션(최근 활동)의 pg_logs를 분석하여 세션 요약 노트를 생성한다.
    """
    ensure_schema()

    # 최근 세션의 pg_logs 조회 (최근 3시간 기준)
    rows = query_rows(
        f"SELECT agent, task, status, created_at "
        f"FROM pg_logs "
        f"WHERE created_at > NOW() - INTERVAL '3 hours' "
        f"AND project_id = {_sql_text(DEFAULT_PROJECT)} "
        f"ORDER BY created_at ASC;"
    )

    if not rows:
        print("[zettel_capture] 세션 활동 없음 — 노트 생성 스킵")
        return None

    # 활동 요약 생성
    now = datetime.now(timezone(timedelta(hours=9)))
    title = f"세션 요약: {now.strftime('%Y-%m-%d %H:%M')}"

    # 활동 카테고리별 그룹핑
    categories = {}
    for row in rows:
        task = row.get('task', '')
        if '[생성 완료]' in task or '[수정 완료]' in task:
            categories.setdefault('파일 변경', []).append(task)
        elif '[커밋]' in task:
            categories.setdefault('커밋', []).append(task)
        elif '[빌드]' in task:
            categories.setdefault('빌드', []).append(task)
        elif '[작업 시작]' in task:
            categories.setdefault('작업 시작', []).append(task)
        elif '세션 종료' in task:
            pass  # 제외
        else:
            categories.setdefault('기타', []).append(task)

    content_lines = [f"## 세션 활동 요약 ({len(rows)}건)"]
    tags = ['세션']

    for cat, items in categories.items():
        content_lines.append(f"\n### {cat} ({len(items)}건)")
        for item in items[:10]:  # 카테고리당 최대 10건
            content_lines.append(f"- {item}")
        if len(items) > 10:
            content_lines.append(f"- ... 외 {len(items) - 10}건")

    content_lines.append(f"\n---\n에이전트: {agent} | 기간: 최근 3시간 | 총 {len(rows)}건 활동")
    content = '\n'.join(content_lines)

    note = create_note(
        title=title,
        content=content,
        note_type='fleeting',
        author=agent,
        project_id=DEFAULT_PROJECT,
        tags=tags,
        source_ref='session-summary',
    )

    if note:
        auto_link(note['id'], content=content, tags=tags, created_by=agent)
        _sync_vault()
        print(f"[zettel_capture] 세션 요약 노트 생성: {note['id']} — {title}")

    return note


def _extract_commit_why(commit_msg: str) -> str:
    """커밋 본문에서 '무엇을/왜' 핵심 1줄 추출 — '## 변경 이유' 우선, 없으면 '## 변경 내용'.

    [WHY] 파일 카드 '최근 변경'에 커밋 제목만 쌓으면 '뭘 왜 바꿨나'를 알 수 없다.
      commit-rules.md의 3섹션 본문에서 첫 유효 줄을 뽑아 변경의 지식성을 높인다.
    [폴백] 3섹션이 없는 커밋(제목만)이면 빈 문자열 → 호출부가 제목만 사용.
    """
    headers = ('## 변경 이유', '## 변경 내용', '## Why', '## What')
    lines = commit_msg.splitlines()
    for i, line in enumerate(lines):
        # 헤더 '줄'을 찾아 그 '다음 줄'부터 스캔 — 같은 줄의 '(Why)' 접미를 오추출하지 않도록.
        if any(line.strip().startswith(h) for h in headers):
            for nxt in lines[i + 1:]:
                s = nxt.strip().lstrip('-').strip()
                if s and not s.startswith('#'):
                    return s[:80]
    return ''


def capture_file_roles(commit_msg: str, files: list[str] | None = None,
                       agent: str = 'claude') -> list[dict]:
    """커밋 시 변경된 파일의 역할 카드를 자동 생성/업데이트한다.

    - 기존 역할 카드가 없는 파일 → 새 permanent 노트 생성
    - 기존 역할 카드가 있는 파일 → "최근 변경" 섹션에 커밋 기록 추가
    - 코드는 저장하지 않음 — 역할/맥락/변경 이력만 기록
    """
    ensure_schema()
    files = files or []
    if not files:
        return []

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=9)))
    today = now.strftime('%Y-%m-%d')
    results = []

    # [T4] 최근 변경 항목 = 커밋 제목 + '무엇을/왜'(본문에서 추출, 없으면 제목만).
    _subject = commit_msg.split(chr(10))[0][:80]
    _why = _extract_commit_why(commit_msg)
    _change_text = f"{_subject} — {_why}" if _why else _subject

    for file_path in files:
        rel = _rel_path(file_path)
        # 테스트/빌드 산출물 등 노이즈 파일은 스킵 (원본 경로도 함께 체크)
        if _is_noise_file(rel) or _is_noise_file(file_path):
            continue

        # source_ref로 기존 역할 카드 검색
        source_ref = f"file-role:{rel}"
        existing = query_rows(
            f"SELECT id, content FROM zettel_notes "
            f"WHERE source_ref = {_sql_text(source_ref)} "
            f"AND {_project_match_sql()} "
            f"ORDER BY updated_at DESC NULLS LAST LIMIT 1;"
        )

        if existing:
            # 기존 카드에 "최근 변경" 이력 추가
            note_id = existing[0]['id']
            old_content = existing[0].get('content', '')
            change_line = f"- [{today}] {_change_text}"

            if '## 최근 변경' in old_content:
                # 기존 변경 이력에 추가 (최대 10건 유지)
                parts = old_content.split('## 최근 변경')
                before = parts[0]
                after_lines = parts[1].strip().split('\n') if len(parts) > 1 else []
                # 기존 이력 항목만 필터 (- 로 시작하는 줄)
                history = [l for l in after_lines if l.strip().startswith('-')]
                history.insert(0, change_line)
                history = history[:10]  # 최신 10건만 유지
                new_content = before + '## 최근 변경\n' + '\n'.join(history)
            else:
                new_content = old_content + f"\n\n## 최근 변경\n{change_line}"

            from src.zettelkasten import update_note
            updated = update_note(note_id, content=new_content)
            if updated:
                results.append(updated)
        else:
            # 새 역할 카드 생성 — [T3] 역할은 파일 헤더 DESCRIPTION 실제 파싱(폴백: 경로 추측)
            role_desc = _read_file_description(file_path)
            tags = ['파일역할']
            tags.extend(_extract_area_tags([file_path]))

            content = f"## 역할\n{role_desc}\n\n"
            content += f"## 파일 경로\n`{rel}`\n\n"
            content += f"## 최근 변경\n- [{today}] {_change_text}"

            note = create_note(
                title=f"📄 {Path(rel).name} — {role_desc[:40]}",
                content=content,
                note_type='permanent',
                author=agent,
                project_id=DEFAULT_PROJECT,
                tags=tags,
                source_ref=source_ref,
            )
            if note:
                auto_link(note['id'], content=content, tags=tags, created_by=agent)
                results.append(note)

    if results:
        _sync_vault()
        print(f"[zettel_capture] 파일 역할 카드 {len(results)}건 생성/업데이트")

    return results


# 파일 지도에 포함할 코드/문서 확장자 화이트리스트 (바이너리/에셋 제외).
_MAP_EXTS = {'.py', '.ts', '.tsx', '.js', '.jsx', '.md', '.sql', '.css', '.html'}


def _list_project_files(base: Path) -> list[str]:
    """프로젝트의 '진짜 파일' 목록(루트 기준 상대경로, POSIX 슬래시)을 반환한다.

    [1순위] `git ls-files` — gitignore가 정의한 경계를 그대로 신뢰(venv/dist/temp/pgsql 자동 제외).
      이식성: 어느 git 프로젝트에서든 자기 추적 파일만 나온다. 절대경로 하드코딩 없음.
    [폴백] git 미설치/비-git 디렉토리 → rglob + _is_noise_file(벤더/빌드 배제).
    """
    try:
        import subprocess
        out = subprocess.run(
            ['git', 'ls-files'], cwd=str(base), capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=15,
        )
        if out.returncode == 0 and out.stdout.strip():
            return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        pass
    # 폴백: 파일시스템 순회 (git 없을 때)
    rels = []
    for path in base.rglob('*'):
        if not path.is_file():
            continue
        try:
            rels.append(str(path.relative_to(base)).replace('\\', '/'))
        except ValueError:
            continue
    return rels


def capture_project_map(root: str | None = None, agent: str = 'system',
                        max_files: int = 400) -> dict | None:
    """프로젝트 전체 파일 트리 + 파일별 DESCRIPTION 한 줄을 단일 노트로 upsert한다.

    [WHY] 다른 프로젝트가 GDrive 허브에서 이 프로젝트의 구조/파일 역할을 파악할 수 있게,
      커밋마다 자동 갱신되는 '파일 지도'를 만든다. 수동 PROJECT_MAP.md와 달리 실제 파일 헤더
      DESCRIPTION에서 생성 → 드리프트 없이 항상 최신. source_ref='project-map' 단일 노트를 upsert.
    [이식성] root 미지정 시 VIBE_PROJECT_ROOT env → 없으면 이 스크립트의 _PROJECT_ROOT.
      절대경로 하드코딩 없음. 어느 프로젝트에서 돌려도 자기 트리를 스캔한다.
    [비대 방지] max_files 상한 + _is_noise_file(dist/vendor 등) 제외 + 코드/문서 확장자만 +
      디렉토리(최상위)별 그룹 + 파일당 한 줄.
    """
    ensure_schema()
    base = Path(root) if root else Path(
        os.environ.get('VIBE_PROJECT_ROOT', str(_PROJECT_ROOT)))
    if not base.is_dir():
        return None

    # [WHY git ls-files] '프로젝트 파일'의 정답은 git 추적 파일 = 사람이 커밋한 것.
    #   rglob는 venv/dist/%TEMP%/pgsql 등 벤더·빌드·임시를 쓸어담아 지도를 오염시킨다.
    #   gitignore가 이미 그 경계를 정의하므로 그대로 신뢰. git 없거나 실패 시 rglob+노이즈필터 폴백.
    rels = _list_project_files(base)
    groups: dict[str, list[str]] = {}
    count = 0
    for rel in rels:
        if count >= max_files:
            break
        if Path(rel).suffix.lower() not in _MAP_EXTS or _is_noise_file(rel):
            continue
        desc = _read_file_description(str(base / rel))
        top = rel.split('/')[0] if '/' in rel else '(루트)'
        groups.setdefault(top, []).append(f"- `{rel}` — {desc}")
        count += 1

    if not groups:
        return None

    now = datetime.now(timezone(timedelta(hours=9)))
    lines = [f"프로젝트 파일 구조 지도 — 자동 생성 "
             f"({now.strftime('%Y-%m-%d %H:%M')}, {count}개 파일)", ""]
    for top in sorted(groups):
        lines.append(f"## {top}")
        lines.extend(groups[top])
        lines.append("")
    content = '\n'.join(lines)

    source_ref = 'project-map'
    existing = query_rows(
        f"SELECT id FROM zettel_notes WHERE source_ref = {_sql_text(source_ref)} "
        f"AND {_project_match_sql()} ORDER BY updated_at DESC NULLS LAST LIMIT 1;"
    )
    if existing:
        from src.zettelkasten import update_note
        note = update_note(existing[0]['id'], content=content)
    else:
        note = create_note(
            title='🗂️ 프로젝트 파일 지도',
            content=content,
            note_type='permanent',
            author=agent,
            project_id=DEFAULT_PROJECT,
            tags=['파일지도', '프로젝트구조'],
            source_ref=source_ref,
        )
        if note:
            auto_link(note['id'], content=content, tags=['파일지도'], created_by=agent)
    if note:
        print(f"[zettel_capture] 파일 지도 노트 upsert: {count}개 파일")
    return note


def _is_noise_file(rel_path: str) -> bool:
    """노이즈 파일 필터 — 역할 카드 생성 대상에서 제외."""
    noise_patterns = [
        'dist/', 'node_modules/', '__pycache__/', '.pyc',
        'package-lock.json', 'yarn.lock', '.spec.',
        '_version.py', '.gitignore', '.env',
    ]
    rel_lower = rel_path.lower().replace('\\', '/')
    return any(p in rel_lower for p in noise_patterns)


def _read_file_description(file_path: str) -> str:
    """파일 표준 헤더의 DESCRIPTION 값을 실제로 읽어 역할 설명으로 반환한다.

    [WHY] _guess_file_role은 경로 패턴 추측이라 얕다. CLAUDE.md 규칙5로 모든 코드/문서 파일
      상단에 DESCRIPTION 헤더가 있으므로 이를 1차 소스로 쓴다(항상 최신 + 저자 의도 반영).
    [폴백] 헤더 없음/읽기 실패 → _guess_file_role(rel) 경로 추측으로 안전 복귀.
    [이식성] 절대경로 하드코딩 없음 — 상대 경로면 _PROJECT_ROOT 기준 해석, 절대면 그대로.
    """
    rel = _rel_path(file_path)
    try:
        p = Path(file_path)
        if not p.is_absolute():
            p = _PROJECT_ROOT / file_path
        if not p.is_file():
            return _guess_file_role(rel)
        head = p.read_text(encoding='utf-8', errors='replace').splitlines()[:40]
    except Exception:
        return _guess_file_role(rel)

    desc_lines = []
    capturing = False
    for line in head:
        s = line.strip()
        m = re.search(r'DESCRIPTION\s*[:：]\s*(.*)', s)
        if m:
            capturing = True
            if m.group(1).strip():
                desc_lines.append(m.group(1).strip())
            continue
        if capturing:
            # 다음 표준 섹션(REVISION HISTORY 등)·헤더 종료 마커에서 중단
            if (not s or s in ('"""', "'''", '*/', '-->')
                    or re.match(r'^[#*/\'"\s]*[A-Z][A-Z _-]{2,}\s*[:：]', s)):
                break
            cleaned = re.sub(r'^[#*/\s]+', '', line).strip()  # 주석 접두 제거
            if cleaned:
                desc_lines.append(cleaned)
    if not desc_lines:
        return _guess_file_role(rel)
    # 첫 문장(마침표 기준) + 80자로 정규화
    desc = re.split(r'(?<=[.。])\s', ' '.join(desc_lines))[0]
    return desc[:80].strip() or _guess_file_role(rel)


def _guess_file_role(rel_path: str) -> str:
    """파일 경로에서 역할을 추측한다. 코드를 읽지 않고 경로 패턴만으로 판단.
    [폴백 전용] 표준 헤더가 없는 파일에 대해서만 _read_file_description이 호출한다."""
    p = rel_path.lower().replace('\\', '/')
    if 'server.py' in p:
        return 'HTTP 서버 — 라우팅, SSE, WebSocket, 정적 파일 서빙'
    if '/api/' in p:
        name = Path(rel_path).stem
        return f'API 모듈 — {name} 관련 엔드포인트'
    if 'pg_store' in p:
        return 'PostgreSQL 데이터 계층 — 스키마 + CRUD'
    if 'zettelkasten' in p:
        return '제텔카스텐 지식 관리 모듈'
    if '.tsx' in p or '.ts' in p:
        name = Path(rel_path).stem
        return f'React 컴포넌트/모듈 — {name}'
    if '/scripts/' in p:
        name = Path(rel_path).stem
        return f'유틸리티 스크립트 — {name}'
    if 'hook' in p:
        return 'Claude Code 훅 핸들러'
    if 'test' in p:
        return '테스트 코드'
    return f'프로젝트 파일 — {Path(rel_path).name}'


# ── 유틸리티 ──────────────────────────────────────────────────────────────

def _extract_area_tags(files: list[str]) -> list[str]:
    """파일 경로에서 영역 태그를 추출한다."""
    tags = set()
    for f in files:
        f_lower = f.lower().replace('\\', '/')
        if 'vibe-view' in f_lower or '.tsx' in f_lower or '.ts' in f_lower:
            tags.add(_AREA_TAG_KO.get('ui', 'UI'))
        if '/api/' in f_lower:
            tags.add(_AREA_TAG_KO.get('backend', '백엔드'))
        if 'pg_store' in f_lower or 'zettelkasten' in f_lower:
            tags.add(_AREA_TAG_KO.get('db', 'DB'))
        if '/scripts/' in f_lower:
            tags.add(_AREA_TAG_KO.get('scripts', '스크립트'))
        if 'hook' in f_lower:
            tags.add(_AREA_TAG_KO.get('hooks', '훅'))
        if 'test' in f_lower:
            tags.add(_AREA_TAG_KO.get('test', '테스트'))
    return list(tags)


def _rel_path(file_path: str) -> str:
    """절대 경로를 프로젝트 루트 기준 상대 경로로 변환."""
    try:
        return str(Path(file_path).relative_to(_PROJECT_ROOT))
    except ValueError:
        return Path(file_path).name


def _sync_vault():
    """Obsidian vault에 동기화 (로컬 + Google Drive, 에러 무시)."""
    try:
        from zettel_sync import export_to_vault
        export_to_vault(DEFAULT_VAULT_DIR, project_id=DEFAULT_PROJECT)
        # Google Drive vault도 동기화 (존재할 때만)
        if GDRIVE_VAULT_DIR and GDRIVE_VAULT_DIR.exists():
            export_to_vault(GDRIVE_VAULT_DIR, project_id=DEFAULT_PROJECT)
    except Exception as e:
        print(f"[zettel_capture] vault 동기화 실패 (무시): {e}")


# ── CLI 엔트리포인트 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='제텔카스텐 자동 캡처 엔진')
    parser.add_argument('--mode', required=True,
                        choices=['commit', 'fix', 'decision', 'session',
                                 'file-roles', 'project-map'],
                        help='캡처 모드')
    parser.add_argument('--agent', default='claude', help='에이전트 이름')
    parser.add_argument('--data', default='{}', help='이벤트 데이터 (JSON 문자열)')
    args = parser.parse_args()

    try:
        data = json.loads(args.data)
    except json.JSONDecodeError:
        data = {}

    if args.mode == 'commit':
        capture_commit(
            commit_msg=data.get('message', ''),
            files=data.get('files', []),
            agent=args.agent,
        )
    elif args.mode == 'fix':
        capture_fix(
            file_path=data.get('file_path', ''),
            old_code=data.get('old_code', ''),
            new_code=data.get('new_code', ''),
            agent=args.agent,
        )
    elif args.mode == 'decision':
        capture_decision(
            context=data.get('context', ''),
            choice=data.get('choice', ''),
            reason=data.get('reason', ''),
            agent=args.agent,
        )
    elif args.mode == 'session':
        capture_session(agent=args.agent)
    elif args.mode == 'file-roles':
        capture_file_roles(
            commit_msg=data.get('message', ''),
            files=data.get('files', []),
            agent=args.agent,
        )
    elif args.mode == 'project-map':
        capture_project_map(
            root=data.get('root'),
            agent=args.agent,
        )


if __name__ == '__main__':
    main()
