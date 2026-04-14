# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/code_indexer.py
# 📝 설명: 코드 인텔리전스 인덱서 — tree-sitter AST 파싱으로 코드 노드/엣지 추출
# 🕒 변경 이력:
# [2026-04-14] Claude — 신규 생성. MindVault 영감 기반 코드 그래프 시스템
# ────────────────────────────────────────────────────────────────────────────
"""코드베이스를 tree-sitter로 파싱하여 PostgreSQL에 노드/엣지를 저장하는 인덱서.

지원 언어: Python, TypeScript, JavaScript, Go, Rust, Java
tree-sitter 없으면 정규식 기반 경량 fallback 사용.
"""
import os
import re
import threading
from pathlib import Path

from src.pg_store import execute, execute_raw, query_rows, ensure_schema

# ── tree-sitter 동적 로드 (설치 안 되어 있으면 fallback) ──
_HAS_TREE_SITTER = False
_PARSERS: dict = {}

try:
    from tree_sitter import Language, Parser
    _HAS_TREE_SITTER = True
except ImportError:
    pass

# 확장자 → 언어 매핑
_EXT_LANG_MAP = {
    '.py': 'python',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
}

# tree-sitter 언어 모듈 매핑
_TS_LANG_MODULES = {
    'python': 'tree_sitter_python',
    'javascript': 'tree_sitter_javascript',
    'typescript': 'tree_sitter_typescript',
    'tsx': 'tree_sitter_typescript',
    'go': 'tree_sitter_go',
    'rust': 'tree_sitter_rust',
    'java': 'tree_sitter_java',
}

# 무시할 디렉토리/파일 패턴
_IGNORE_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv', 'env',
    'dist', 'build', '.next', '.nuxt', 'target', '.tox',
    '.ai_monitor/vibe-view/node_modules', 'coverage', '.mypy_cache',
}

_IGNORE_FILES = {'.min.js', '.min.css', '.map', '.lock'}

# 인덱싱 진행 상태 (SSE 스트리밍용)
_indexing_status: dict = {}
_indexing_lock = threading.Lock()


def get_indexing_status(project_id: int) -> dict:
    """프로젝트 인덱싱 진행 상태 조회."""
    with _indexing_lock:
        return _indexing_status.get(project_id, {}).copy()


def _update_status(project_id: int, **kwargs):
    with _indexing_lock:
        if project_id not in _indexing_status:
            _indexing_status[project_id] = {}
        _indexing_status[project_id].update(kwargs)


# ── tree-sitter 파서 초기화 ──

def _get_parser(lang: str):
    """언어별 tree-sitter 파서를 가져온다. 캐시됨."""
    if not _HAS_TREE_SITTER:
        return None
    if lang in _PARSERS:
        return _PARSERS[lang]

    mod_name = _TS_LANG_MODULES.get(lang)
    if not mod_name:
        return None

    try:
        import importlib
        mod = importlib.import_module(mod_name)
        # typescript 모듈은 language_typescript / language_tsx 함수 제공
        if lang == 'tsx':
            lang_func = getattr(mod, 'language_tsx', None) or mod.language
        elif lang == 'typescript':
            lang_func = getattr(mod, 'language_typescript', None) or mod.language
        else:
            lang_func = mod.language
        ts_lang = Language(lang_func())
        parser = Parser(ts_lang)
        _PARSERS[lang] = parser
        return parser
    except Exception as e:
        print(f"[code_indexer] {lang} 파서 로드 실패: {e}")
        return None


# ── 파일 수집 ──

def _collect_files(root_path: str) -> list[tuple[str, str]]:
    """프로젝트 디렉토리에서 인덱싱 대상 파일을 수집한다.
    반환: [(상대경로, 언어), ...]
    """
    root = Path(root_path)
    results = []

    for dirpath, dirnames, filenames in os.walk(root):
        # 무시할 디렉토리 필터링
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [
            d for d in dirnames
            if d not in _IGNORE_DIRS
            and not d.startswith('.')
            and f"{rel_dir}/{d}" not in _IGNORE_DIRS
        ]

        for fname in filenames:
            ext = Path(fname).suffix.lower()
            # 무시 파일 체크
            if any(fname.endswith(ig) for ig in _IGNORE_FILES):
                continue
            lang = _EXT_LANG_MAP.get(ext)
            if lang:
                rel_path = Path(dirpath, fname).relative_to(root).as_posix()
                results.append((rel_path, lang))

    return results


# ── tree-sitter AST 노드 추출 ──

def _extract_nodes_treesitter(source: bytes, lang: str, parser) -> list[dict]:
    """tree-sitter로 파싱하여 함수/클래스/import 노드를 추출한다."""
    tree = parser.parse(source)
    nodes = []

    # 언어별 노드 타입 매핑
    func_types = {
        'python': ['function_definition'],
        'javascript': ['function_declaration', 'arrow_function', 'method_definition'],
        'typescript': ['function_declaration', 'arrow_function', 'method_definition'],
        'tsx': ['function_declaration', 'arrow_function', 'method_definition'],
        'go': ['function_declaration', 'method_declaration'],
        'rust': ['function_item', 'impl_item'],
        'java': ['method_declaration', 'constructor_declaration'],
    }
    class_types = {
        'python': ['class_definition'],
        'javascript': ['class_declaration'],
        'typescript': ['class_declaration', 'interface_declaration', 'type_alias_declaration'],
        'tsx': ['class_declaration', 'interface_declaration', 'type_alias_declaration'],
        'go': ['type_declaration'],
        'rust': ['struct_item', 'enum_item', 'trait_item'],
        'java': ['class_declaration', 'interface_declaration'],
    }
    import_types = {
        'python': ['import_statement', 'import_from_statement'],
        'javascript': ['import_statement'],
        'typescript': ['import_statement'],
        'tsx': ['import_statement'],
        'go': ['import_declaration'],
        'rust': ['use_declaration'],
        'java': ['import_declaration'],
    }

    def _walk(node, depth=0):
        ntype = node.type

        # 함수
        if ntype in func_types.get(lang, []):
            name_node = node.child_by_field_name('name')
            name = name_node.text.decode('utf-8') if name_node else '(anonymous)'
            # 시그니처: 함수 첫 줄
            lines = source[node.start_byte:node.end_byte].decode('utf-8', errors='replace').split('\n')
            sig = lines[0].strip() if lines else ''
            # docstring (Python)
            doc = ''
            if lang == 'python' and node.child_count > 0:
                body = node.child_by_field_name('body')
                if body and body.child_count > 0:
                    first_stmt = body.children[0]
                    if first_stmt.type == 'expression_statement':
                        expr = first_stmt.children[0] if first_stmt.child_count > 0 else None
                        if expr and expr.type == 'string':
                            doc = expr.text.decode('utf-8', errors='replace').strip('"\'')

            nodes.append({
                'node_type': 'function',
                'name': name,
                'signature': sig[:500],
                'line_start': node.start_point[0] + 1,
                'line_end': node.end_point[0] + 1,
                'docstring': doc[:1000],
                'raw_content': source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')[:2000],
            })

        # 클래스/인터페이스
        elif ntype in class_types.get(lang, []):
            name_node = node.child_by_field_name('name')
            name = name_node.text.decode('utf-8') if name_node else '(anonymous)'
            lines = source[node.start_byte:node.end_byte].decode('utf-8', errors='replace').split('\n')
            sig = lines[0].strip() if lines else ''

            nodes.append({
                'node_type': 'class',
                'name': name,
                'signature': sig[:500],
                'line_start': node.start_point[0] + 1,
                'line_end': node.end_point[0] + 1,
                'docstring': '',
                'raw_content': source[node.start_byte:min(node.start_byte + 2000, node.end_byte)].decode('utf-8', errors='replace'),
            })

        # import
        elif ntype in import_types.get(lang, []):
            text = source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
            nodes.append({
                'node_type': 'import',
                'name': text.strip()[:200],
                'signature': '',
                'line_start': node.start_point[0] + 1,
                'line_end': node.end_point[0] + 1,
                'docstring': '',
                'raw_content': text[:500],
            })

        # 자식 노드 재귀 탐색
        for child in node.children:
            _walk(child, depth + 1)

    _walk(tree.root_node)
    return nodes


# ── 정규식 fallback 파서 ──

def _extract_nodes_regex(source: str, lang: str) -> list[dict]:
    """tree-sitter 없을 때 정규식으로 함수/클래스/import를 추출하는 경량 파서."""
    nodes = []
    lines = source.split('\n')

    # Python
    if lang == 'python':
        for i, line in enumerate(lines):
            m = re.match(r'^(\s*)def\s+(\w+)\s*\(', line)
            if m:
                nodes.append({
                    'node_type': 'function', 'name': m.group(2),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^(\s*)class\s+(\w+)', line)
            if m:
                nodes.append({
                    'node_type': 'class', 'name': m.group(2),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^(from\s+\S+\s+import|import)\s+', line)
            if m:
                nodes.append({
                    'node_type': 'import', 'name': line.strip()[:200],
                    'signature': '', 'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })

    # JS/TS
    elif lang in ('javascript', 'typescript', 'tsx'):
        for i, line in enumerate(lines):
            m = re.match(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)', line)
            if m:
                nodes.append({
                    'node_type': 'function', 'name': m.group(1),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:\(|async)', line)
            if m:
                nodes.append({
                    'node_type': 'function', 'name': m.group(1),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^\s*(?:export\s+)?(?:class|interface|type)\s+(\w+)', line)
            if m:
                nodes.append({
                    'node_type': 'class', 'name': m.group(1),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^\s*import\s+', line)
            if m:
                nodes.append({
                    'node_type': 'import', 'name': line.strip()[:200],
                    'signature': '', 'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })

    # Go/Rust/Java — 기본 패턴
    else:
        for i, line in enumerate(lines):
            m = re.match(r'^\s*(?:pub\s+)?(?:fn|func)\s+(\w+)', line)
            if m:
                nodes.append({
                    'node_type': 'function', 'name': m.group(1),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^\s*(?:pub\s+)?(?:struct|enum|trait|class|interface|type)\s+(\w+)', line)
            if m:
                nodes.append({
                    'node_type': 'class', 'name': m.group(1),
                    'signature': line.strip()[:500],
                    'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })
            m = re.match(r'^\s*(?:import|use|package)\s+', line)
            if m:
                nodes.append({
                    'node_type': 'import', 'name': line.strip()[:200],
                    'signature': '', 'line_start': i + 1, 'line_end': i + 1,
                    'docstring': '', 'raw_content': line.strip()[:500],
                })

    return nodes


# ── 엣지(의존관계) 추출 ──

def _build_edges(project_id: int, file_nodes: dict[str, list[int]]):
    """import 노드를 분석하여 파일 간 의존관계 엣지를 생성한다.

    file_nodes: {file_path: [node_id, ...]}
    """
    # 모든 import 노드 조회
    import_rows = query_rows(
        "SELECT id, file_path, name FROM code_nodes "
        f"WHERE project_id = {project_id} AND node_type = 'import';"
    )

    # 파일명 → 파일 첫 번째 노드 ID 매핑 (모듈 레벨)
    file_first_node: dict[str, int] = {}
    for fp, nids in file_nodes.items():
        if nids:
            file_first_node[fp] = nids[0]

    # 파일 basename/stem → path 매핑
    basename_map: dict[str, str] = {}
    stem_map: dict[str, str] = {}
    for fp in file_nodes:
        basename_map[Path(fp).name] = fp
        stem_map[Path(fp).stem] = fp

    edges_sql = []
    for row in import_rows:
        import_name = row.get('name', '')
        source_file = row.get('file_path', '')
        source_id = row.get('id')

        # import에서 모듈명 추출하여 파일 매칭
        # Python: "from foo.bar import baz" → "foo/bar.py" or "foo/bar/__init__.py"
        # JS/TS: "import { x } from './foo'" → "foo.ts" or "foo.js"
        target_file = None

        # 상대 경로 매칭
        for pattern in [r"from\s+['\"]\.?/?(\S+?)['\"]", r"from\s+(\S+)\s+import",
                        r"import\s+(\S+)"]:
            m = re.search(pattern, import_name)
            if m:
                mod = m.group(1).strip("'\"").replace('.', '/').replace('\\', '/')
                # 파일명 후보
                candidates = [
                    f"{mod}.py", f"{mod}.ts", f"{mod}.tsx", f"{mod}.js", f"{mod}.jsx",
                    f"{mod}/index.ts", f"{mod}/index.tsx", f"{mod}/index.js",
                    f"{mod}/__init__.py",
                ]
                for c in candidates:
                    if c in file_nodes:
                        target_file = c
                        break
                # stem 매칭
                if not target_file:
                    base = mod.split('/')[-1] if '/' in mod else mod
                    if base in stem_map:
                        target_file = stem_map[base]
                break

        if target_file and target_file in file_first_node and source_id:
            target_id = file_first_node[target_file]
            edges_sql.append(
                f"INSERT INTO code_edges (project_id, source_id, target_id, edge_type) "
                f"VALUES ({project_id}, {source_id}, {target_id}, 'imports') "
                f"ON CONFLICT DO NOTHING;"
            )

    if edges_sql:
        # 배치 실행
        execute_raw('\n'.join(edges_sql))


# ── 프로젝트 등록/조회 ──

def register_project(name: str, root_path: str) -> int | None:
    """프로젝트를 등록하고 ID를 반환한다. 이미 있으면 기존 ID."""
    ensure_schema()
    root_path = Path(root_path).resolve().as_posix()
    rows = query_rows(
        f"SELECT id FROM code_projects WHERE root_path = '{root_path}' LIMIT 1;"
    )
    if rows:
        return rows[0]['id']

    execute(
        "INSERT INTO code_projects (name, root_path) "
        f"VALUES ('{_esc(name)}', '{_esc(root_path)}') "
        "ON CONFLICT (root_path) DO UPDATE SET name = EXCLUDED.name;"
    )
    rows = query_rows(
        f"SELECT id FROM code_projects WHERE root_path = '{_esc(root_path)}' LIMIT 1;"
    )
    return rows[0]['id'] if rows else None


def list_projects() -> list[dict]:
    """등록된 프로젝트 목록 조회."""
    ensure_schema()
    return query_rows("SELECT * FROM code_projects ORDER BY last_indexed_at DESC NULLS LAST;")


def _esc(s: str) -> str:
    """SQL 인젝션 방지를 위한 이스케이프."""
    return s.replace("'", "''").replace("\\", "\\\\")


# ── 메인 인덱싱 함수 ──

def index_project(project_id: int, root_path: str, background: bool = True):
    """프로젝트 코드를 인덱싱한다. background=True면 별도 스레드에서 실행."""
    if background:
        t = threading.Thread(
            target=_index_project_sync,
            args=(project_id, root_path),
            daemon=True,
        )
        t.start()
        return {'status': 'started', 'project_id': project_id}
    else:
        return _index_project_sync(project_id, root_path)


def _index_project_sync(project_id: int, root_path: str) -> dict:
    """동기적으로 프로젝트를 인덱싱한다."""
    _update_status(project_id, status='scanning', progress=0, total=0)

    # 1. 기존 데이터 삭제 (re-index)
    execute_raw(f"DELETE FROM code_edges WHERE project_id = {project_id};")
    execute_raw(f"DELETE FROM code_nodes WHERE project_id = {project_id};")

    # 2. 파일 수집
    files = _collect_files(root_path)
    total = len(files)
    _update_status(project_id, status='indexing', progress=0, total=total)

    if total == 0:
        _update_status(project_id, status='done', progress=0, total=0)
        return {'status': 'done', 'files': 0, 'nodes': 0}

    # 3. 파일별 파싱 + 노드 저장
    file_nodes: dict[str, list[int]] = {}
    total_nodes = 0
    langs_found = set()

    for idx, (rel_path, lang) in enumerate(files):
        abs_path = Path(root_path) / rel_path
        try:
            source_bytes = abs_path.read_bytes()
            source_text = source_bytes.decode('utf-8', errors='replace')
        except Exception:
            continue

        langs_found.add(lang)

        # tree-sitter 또는 regex fallback
        parser = _get_parser(lang)
        if parser:
            nodes = _extract_nodes_treesitter(source_bytes, lang, parser)
        else:
            nodes = _extract_nodes_regex(source_text, lang)

        # DB 저장
        node_ids = []
        for n in nodes:
            execute(
                "INSERT INTO code_nodes "
                "(project_id, file_path, node_type, name, signature, "
                "line_start, line_end, docstring, raw_content) VALUES ("
                f"{project_id}, '{_esc(rel_path)}', '{_esc(n['node_type'])}', "
                f"'{_esc(n['name'])}', '{_esc(n['signature'])}', "
                f"{n['line_start']}, {n['line_end']}, "
                f"'{_esc(n['docstring'])}', '{_esc(n['raw_content'])}');"
            )
            # ID 조회 (마지막 삽입)
            id_rows = query_rows(
                f"SELECT id FROM code_nodes WHERE project_id = {project_id} "
                f"AND file_path = '{_esc(rel_path)}' AND name = '{_esc(n['name'])}' "
                f"AND line_start = {n['line_start']} ORDER BY id DESC LIMIT 1;"
            )
            if id_rows:
                node_ids.append(id_rows[0]['id'])
            total_nodes += 1

        file_nodes[rel_path] = node_ids

        if (idx + 1) % 10 == 0 or idx == total - 1:
            _update_status(project_id, progress=idx + 1)

    # 4. 엣지(의존관계) 생성
    _update_status(project_id, status='building_edges')
    _build_edges(project_id, file_nodes)

    # 5. 프로젝트 메타 업데이트
    lang_str = ','.join(sorted(langs_found))
    execute(
        f"UPDATE code_projects SET "
        f"file_count = {total}, node_count = {total_nodes}, "
        f"language = '{_esc(lang_str)}', last_indexed_at = NOW() "
        f"WHERE id = {project_id};"
    )

    _update_status(project_id, status='done', progress=total, total=total,
                   files=total, nodes=total_nodes)

    return {'status': 'done', 'files': total, 'nodes': total_nodes, 'languages': lang_str}
