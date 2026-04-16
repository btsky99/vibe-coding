# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/wiki_generator.py
# 📝 설명: LLM 위키 자동생성 엔진 — code_nodes → 프롬프트 조립 → hive_tasks 등록
# 🕒 변경 이력:
# [2026-04-15] Claude — 신규 생성. Phase 3 LLM 위키 (Karpathy 패턴)
# ────────────────────────────────────────────────────────────────────────────
"""코드 노드 데이터를 기반으로 LLM 위키를 자동 생성하는 엔진.

파일/모듈/노드(함수·클래스) 3계층 위키를 지원.
에이전트(Claude/Gemini/Codex CLI)가 hive_tasks에서 체크아웃하여 위키를 작성하고,
결과를 PUT /api/codegraph/wiki로 저장하는 구조.
"""
import hashlib
import time
from pathlib import PurePosixPath

from src.pg_store import (
    ensure_schema,
    execute,
    query_rows,
    save_task,
    _sql_text,
    _sql_json,
    _now_iso,
)

# ── 프롬프트 템플릿 ─────────────────────────────────────────────────────────

_FILE_WIKI_PROMPT = """아래는 파일 `{file_path}`의 코드 분석 정보입니다.
이 파일에 대한 위키 문서를 한글 마크다운으로 작성해주세요.

## 요구 형식
- **개요**: 이 파일의 역할과 책임 (2~3문장)
- **주요 구성**: 함수/클래스 목록과 각각의 역할 (불릿 리스트)
- **의존 관계**: import하는 모듈과 이유
- **사용 예시**: 대표적 호출 패턴 (코드 블록)

## 코드 노드 정보
{nodes_info}
"""

_MODULE_WIKI_PROMPT = """아래는 모듈(폴더) `{dir_path}`에 속한 파일들의 위키 요약입니다.
이 모듈 전체를 설명하는 위키 문서를 한글 마크다운으로 작성해주세요.

## 요구 형식
- **모듈 개요**: 이 모듈의 전체 역할 (2~3문장)
- **파일 구성**: 각 파일의 역할 요약 (불릿 리스트)
- **아키텍처 흐름**: 파일 간 데이터/호출 흐름

## 하위 파일 위키 요약
{files_summary}
"""

_NODE_WIKI_PROMPT = """아래는 `{file_path}`에 정의된 {node_type} `{node_name}`의 코드입니다.
이 {node_type}에 대한 위키 문서를 한글 마크다운으로 작성해주세요.

## 요구 형식
- **목적**: 이 {node_type}이 하는 일 (1~2문장)
- **파라미터**: 각 파라미터의 타입과 역할 (테이블)
- **반환값**: 반환 타입과 의미
- **사용 예시**: 호출 패턴 (코드 블록)
- **주의사항**: 엣지 케이스나 제약 조건

## 코드
```
{signature}
```

{raw_content}
"""


# ── 해시 유틸 ────────────────────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    """콘텐츠 해시 생성 (변경 감지용)."""
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:16]


# ── 위키 생성 태스크 등록 ────────────────────────────────────────────────────

def generate_file_wiki(project_id: int, file_path: str) -> dict:
    """파일 단위 위키 생성 — hive_tasks에 태스크 등록."""
    ensure_schema()
    nodes = query_rows(
        f"SELECT id, node_type, name, signature, line_start, line_end, docstring, raw_content "
        f"FROM code_nodes WHERE project_id = {int(project_id)} "
        f"AND file_path = {_sql_text(file_path)} "
        f"ORDER BY line_start"
    )
    if not nodes:
        return {'status': 'skip', 'reason': '해당 파일에 코드 노드가 없음'}

    # 변경 감지 — source_hash 비교
    combined = '\n'.join(n.get('raw_content', '') for n in nodes)
    new_hash = _content_hash(combined)
    existing = query_rows(
        f"SELECT source_hash FROM code_wiki "
        f"WHERE project_id = {int(project_id)} AND file_path = {_sql_text(file_path)} "
        f"AND wiki_type = 'file' LIMIT 1"
    )
    if existing and existing[0].get('source_hash') == new_hash:
        return {'status': 'skip', 'reason': '변경 없음 (해시 동일)'}

    # 프롬프트 조립
    nodes_info = _format_nodes(nodes)
    prompt = _FILE_WIKI_PROMPT.format(file_path=file_path, nodes_info=nodes_info)

    # hive_tasks에 등록
    task_id = str(int(time.time() * 1000))
    task = {
        'id': task_id,
        'title': f'위키생성: {file_path}',
        'description': prompt,
        'status': 'pending',
        'assigned_to': 'all',
        'priority': 'low',
        'created_by': 'wiki_generator',
        'kanban_status': 'todo',
        'tags': ['wiki_generate', 'file'],
        'wiki_meta': {
            'project_id': project_id,
            'file_path': file_path,
            'wiki_type': 'file',
            'source_hash': new_hash,
        },
    }
    save_task(task)
    return {'status': 'queued', 'task_id': task_id, 'file_path': file_path}


def generate_module_wiki(project_id: int, dir_path: str) -> dict:
    """모듈(폴더) 단위 위키 생성 — 하위 파일 위키 요약 기반."""
    ensure_schema()
    # dir_path 패턴 매칭 (LIKE 'dir_path/%' AND NOT LIKE 'dir_path/%/%')
    like_pattern = dir_path.rstrip('/') + '/%'
    file_wikis = query_rows(
        f"SELECT file_path, title, content FROM code_wiki "
        f"WHERE project_id = {int(project_id)} AND wiki_type = 'file' "
        f"AND file_path LIKE {_sql_text(like_pattern)} "
        f"ORDER BY file_path"
    )
    if not file_wikis:
        return {'status': 'skip', 'reason': '하위 파일 위키가 없음 — 파일 위키를 먼저 생성하세요'}

    # 요약 조립
    files_summary = '\n\n'.join(
        f"### {w['file_path']}\n{w.get('content', '')[:500]}"
        for w in file_wikis
    )
    new_hash = _content_hash(files_summary)
    prompt = _MODULE_WIKI_PROMPT.format(dir_path=dir_path, files_summary=files_summary)

    task_id = str(int(time.time() * 1000))
    task = {
        'id': task_id,
        'title': f'위키생성: 모듈 {dir_path}',
        'description': prompt,
        'status': 'pending',
        'assigned_to': 'all',
        'priority': 'low',
        'created_by': 'wiki_generator',
        'kanban_status': 'todo',
        'tags': ['wiki_generate', 'module'],
        'wiki_meta': {
            'project_id': project_id,
            'file_path': dir_path,
            'wiki_type': 'module',
            'source_hash': new_hash,
        },
    }
    save_task(task)
    return {'status': 'queued', 'task_id': task_id, 'dir_path': dir_path}


def generate_node_wiki(project_id: int, node_id: int) -> dict:
    """개별 함수/클래스 위키 생성."""
    ensure_schema()
    rows = query_rows(
        f"SELECT id, file_path, node_type, name, signature, raw_content, docstring "
        f"FROM code_nodes WHERE id = {int(node_id)} LIMIT 1"
    )
    if not rows:
        return {'status': 'skip', 'reason': '노드를 찾을 수 없음'}

    node = rows[0]
    raw = node.get('raw_content', '')
    new_hash = _content_hash(raw)

    existing = query_rows(
        f"SELECT source_hash FROM code_wiki "
        f"WHERE project_id = {int(project_id)} AND node_id = {int(node_id)} "
        f"AND wiki_type = 'node' LIMIT 1"
    )
    if existing and existing[0].get('source_hash') == new_hash:
        return {'status': 'skip', 'reason': '변경 없음'}

    prompt = _NODE_WIKI_PROMPT.format(
        file_path=node['file_path'],
        node_type=node['node_type'],
        node_name=node['name'],
        signature=node.get('signature', ''),
        raw_content=raw[:3000],
    )

    task_id = str(int(time.time() * 1000))
    task = {
        'id': task_id,
        'title': f"위키생성: {node['node_type']} {node['name']}",
        'description': prompt,
        'status': 'pending',
        'assigned_to': 'all',
        'priority': 'low',
        'created_by': 'wiki_generator',
        'kanban_status': 'todo',
        'tags': ['wiki_generate', 'node'],
        'wiki_meta': {
            'project_id': project_id,
            'file_path': node['file_path'],
            'wiki_type': 'node',
            'node_id': node_id,
            'source_hash': new_hash,
        },
    }
    save_task(task)
    return {'status': 'queued', 'task_id': task_id, 'node_name': node['name']}


WIKI_BATCH_SIZE = 5  # 한 번에 큐잉할 최대 위키 태스크 수


def generate_all_file_wikis(project_id: int, batch_size: int = WIKI_BATCH_SIZE) -> dict:
    """프로젝트 전체 파일 위키 일괄 생성 — 배치 제한 + 백프레셔.

    한 번에 최대 batch_size건만 큐잉하고, 나머지는 'deferred'로 표시.
    이미 pending인 위키 태스크가 있으면 추가 큐잉하지 않는다 (백프레셔).
    """
    ensure_schema()

    # 백프레셔: 아직 처리 안 된 wiki 태스크가 있으면 추가 큐잉 차단
    pending_wiki_tasks = query_rows(
        f"SELECT COUNT(*) as cnt FROM hive_tasks "
        f"WHERE status IN ('pending', 'dispatched') "
        f"AND tags::text LIKE '%%wiki_generate%%'"
    )
    pending_count = (pending_wiki_tasks[0]['cnt'] if pending_wiki_tasks else 0)
    if pending_count >= batch_size:
        return {
            'queued': 0, 'skipped': 0, 'deferred': 0,
            'backpressure': True,
            'pending_tasks': pending_count,
            'message': f'위키 태스크 {pending_count}건 처리 대기 중 — 완료 후 재시도',
            'files': [],
        }

    # 큐잉 가능 슬롯 계산
    available_slots = max(0, batch_size - pending_count)

    files = query_rows(
        f"SELECT DISTINCT file_path FROM code_nodes "
        f"WHERE project_id = {int(project_id)} ORDER BY file_path"
    )
    results = {'queued': 0, 'skipped': 0, 'deferred': 0, 'files': []}
    for f in files:
        fp = f['file_path']
        if results['queued'] >= available_slots:
            results['deferred'] += 1
            results['files'].append({'file_path': fp, 'status': 'deferred'})
            continue
        r = generate_file_wiki(project_id, fp)
        if r['status'] == 'queued':
            results['queued'] += 1
        else:
            results['skipped'] += 1
        results['files'].append({'file_path': fp, **r})
    return results


# ── 위키 CRUD ────────────────────────────────────────────────────────────────

def save_wiki(project_id: int, file_path: str, wiki_type: str,
              content: str, title: str = '', node_id: int | None = None,
              source_hash: str = '') -> dict:
    """위키 저장 (UPSERT)."""
    ensure_schema()
    if not title:
        title = PurePosixPath(file_path).name if file_path else wiki_type
    node_val = str(int(node_id)) if node_id else 'NULL'
    coalesce_val = str(int(node_id)) if node_id else '-1'
    execute(
        f"INSERT INTO code_wiki (project_id, file_path, title, content, source_hash, wiki_type, node_id, generated_at) "
        f"VALUES ({int(project_id)}, {_sql_text(file_path)}, {_sql_text(title)}, "
        f"{_sql_text(content)}, {_sql_text(source_hash)}, {_sql_text(wiki_type)}, {node_val}, NOW()) "
        f"ON CONFLICT (project_id, file_path, wiki_type, COALESCE(node_id, -1)) "
        f"DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content, "
        f"source_hash = EXCLUDED.source_hash, generated_at = NOW()"
    )
    return {'status': 'saved', 'file_path': file_path, 'wiki_type': wiki_type}


def get_wiki(project_id: int, file_path: str | None = None,
             wiki_type: str | None = None, node_id: int | None = None) -> list[dict]:
    """위키 조회."""
    ensure_schema()
    conditions = [f"project_id = {int(project_id)}"]
    if file_path is not None:
        conditions.append(f"file_path = {_sql_text(file_path)}")
    if wiki_type:
        conditions.append(f"wiki_type = {_sql_text(wiki_type)}")
    if node_id is not None:
        conditions.append(f"node_id = {int(node_id)}")
    where = ' AND '.join(conditions)
    return query_rows(
        f"SELECT id, project_id, file_path, title, content, source_hash, "
        f"wiki_type, node_id, generated_at FROM code_wiki WHERE {where} "
        f"ORDER BY file_path, wiki_type"
    )


def get_wiki_tree(project_id: int) -> dict:
    """파일 트리 + 위키 존재 여부 반환."""
    ensure_schema()
    # 인덱싱된 모든 파일
    all_files = query_rows(
        f"SELECT DISTINCT file_path FROM code_nodes "
        f"WHERE project_id = {int(project_id)} ORDER BY file_path"
    )
    # 위키가 있는 파일
    wiki_files = query_rows(
        f"SELECT file_path, wiki_type, generated_at FROM code_wiki "
        f"WHERE project_id = {int(project_id)} ORDER BY file_path"
    )
    wiki_map = {}
    for w in wiki_files:
        fp = w['file_path']
        if fp not in wiki_map:
            wiki_map[fp] = []
        wiki_map[fp].append({
            'wiki_type': w['wiki_type'],
            'generated_at': str(w.get('generated_at', '')),
        })

    # 트리 구성
    tree = []
    dirs_seen = set()
    for f in all_files:
        fp = f['file_path']
        # 상위 디렉토리 노드 추가
        parts = PurePosixPath(fp).parts
        for i in range(1, len(parts)):
            dir_path = '/'.join(parts[:i])
            if dir_path not in dirs_seen:
                dirs_seen.add(dir_path)
                tree.append({
                    'path': dir_path,
                    'type': 'directory',
                    'has_wiki': dir_path in wiki_map,
                    'wikis': wiki_map.get(dir_path, []),
                })
        tree.append({
            'path': fp,
            'type': 'file',
            'has_wiki': fp in wiki_map,
            'wikis': wiki_map.get(fp, []),
        })
    return {'project_id': project_id, 'tree': tree, 'total_files': len(all_files)}


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _format_nodes(nodes: list[dict]) -> str:
    """code_nodes 목록을 프롬프트용 텍스트로 포맷."""
    parts = []
    for n in nodes:
        header = f"### {n.get('node_type', '?')} `{n.get('name', '?')}` (L{n.get('line_start', '?')}~L{n.get('line_end', '?')})"
        sig = f"**시그니처:** `{n.get('signature', '')}`" if n.get('signature') else ''
        doc = f"**독스트링:** {n.get('docstring', '')}" if n.get('docstring') else ''
        raw = n.get('raw_content', '')
        code = f"```\n{raw[:1500]}\n```" if raw else ''
        parts.append('\n'.join(filter(None, [header, sig, doc, code])))
    return '\n\n'.join(parts)
