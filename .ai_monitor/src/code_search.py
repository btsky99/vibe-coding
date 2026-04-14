# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/code_search.py
# 📝 설명: 코드 인텔리전스 검색 — PostgreSQL FTS 기반 BM25 검색 엔진
# 🕒 변경 이력:
# [2026-04-14] Claude — 신규 생성. MindVault 영감 기반 BM25 코드 검색
# ────────────────────────────────────────────────────────────────────────────
"""PostgreSQL Full-Text Search를 활용한 BM25 유사 코드 검색 엔진.

content_tsv (TSVECTOR) 컬럼의 GIN 인덱스를 활용하여
함수명, 시그니처, docstring, 코드 내용을 빠르게 검색한다.
"""
from src.pg_store import query_rows, ensure_schema


def _esc(s: str) -> str:
    """SQL 인젝션 방지를 위한 이스케이프."""
    return s.replace("'", "''").replace("\\", "\\\\")


def search_code(query: str, project_id: int | None = None,
                node_type: str | None = None,
                limit: int = 30) -> list[dict]:
    """BM25 기반 코드 검색.

    Args:
        query: 검색어 (함수명, 키워드 등)
        project_id: 특정 프로젝트만 검색 (None이면 전체)
        node_type: 'function', 'class', 'import' 등 필터
        limit: 최대 결과 수

    Returns:
        [{id, file_path, name, node_type, signature, snippet, score, project_id, line_start}, ...]
    """
    ensure_schema()

    if not query or not query.strip():
        return []

    # 쿼리 전처리 — plainto_tsquery는 특수문자를 자동 처리
    escaped_q = _esc(query.strip())

    # WHERE 조건 빌드
    conditions = []
    if project_id is not None:
        conditions.append(f"n.project_id = {int(project_id)}")
    if node_type:
        conditions.append(f"n.node_type = '{_esc(node_type)}'")

    where = ''
    if conditions:
        where = 'AND ' + ' AND '.join(conditions)

    sql = f"""
        SELECT
            n.id, n.file_path, n.name, n.node_type, n.signature,
            n.line_start, n.line_end, n.project_id,
            LEFT(n.raw_content, 200) AS snippet,
            ts_rank_cd(n.content_tsv, q) AS score
        FROM code_nodes n,
             plainto_tsquery('english', '{escaped_q}') q
        WHERE n.content_tsv @@ q
        {where}
        ORDER BY score DESC, n.name ASC
        LIMIT {int(limit)};
    """

    results = query_rows(sql)

    # FTS에서 결과 없으면 LIKE fallback (부분 일치)
    if not results:
        like_q = f"%{escaped_q}%"
        like_conditions = conditions.copy()

        fallback_sql = f"""
            SELECT
                n.id, n.file_path, n.name, n.node_type, n.signature,
                n.line_start, n.line_end, n.project_id,
                LEFT(n.raw_content, 200) AS snippet,
                0.5 AS score
            FROM code_nodes n
            WHERE (n.name ILIKE '{like_q}' OR n.signature ILIKE '{like_q}'
                   OR n.raw_content ILIKE '{like_q}')
            {where}
            ORDER BY
                CASE WHEN n.name ILIKE '{like_q}' THEN 1
                     WHEN n.signature ILIKE '{like_q}' THEN 2
                     ELSE 3 END,
                n.name ASC
            LIMIT {int(limit)};
        """
        results = query_rows(fallback_sql)

    return results


def get_graph_data(project_id: int) -> dict:
    """프로젝트의 코드 그래프 데이터를 반환한다.

    Returns:
        {
            nodes: [{id, name, node_type, file_path, line_start, ...}],
            edges: [{source, target, edge_type}],
            stats: {functions, classes, imports, files}
        }
    """
    ensure_schema()

    # 노드 조회 (import 제외 — 시각화에 노이즈)
    nodes = query_rows(f"""
        SELECT id, file_path, node_type, name, signature, line_start, line_end
        FROM code_nodes
        WHERE project_id = {int(project_id)} AND node_type != 'import'
        ORDER BY file_path, line_start;
    """)

    # 엣지 조회
    edges = query_rows(f"""
        SELECT source_id AS source, target_id AS target, edge_type
        FROM code_edges
        WHERE project_id = {int(project_id)};
    """)

    # 통계
    stats_rows = query_rows(f"""
        SELECT
            node_type,
            COUNT(*) AS cnt
        FROM code_nodes
        WHERE project_id = {int(project_id)}
        GROUP BY node_type;
    """)
    stats = {r['node_type']: r['cnt'] for r in stats_rows}

    file_count_rows = query_rows(f"""
        SELECT COUNT(DISTINCT file_path) AS cnt
        FROM code_nodes WHERE project_id = {int(project_id)};
    """)
    stats['files'] = file_count_rows[0]['cnt'] if file_count_rows else 0

    return {'nodes': nodes, 'edges': edges, 'stats': stats}


def get_impact_analysis(node_id: int, depth: int = 3) -> dict:
    """특정 노드를 변경할 때 영향받는 노드들을 재귀적으로 탐색한다.

    Args:
        node_id: 변경 대상 노드 ID
        depth: 최대 탐색 깊이

    Returns:
        {
            target: {id, name, file_path, ...},
            affected: [{id, name, file_path, distance, ...}],
            total: int
        }
    """
    ensure_schema()

    # 대상 노드 정보
    target_rows = query_rows(
        f"SELECT id, file_path, name, node_type, signature, line_start, project_id "
        f"FROM code_nodes WHERE id = {int(node_id)} LIMIT 1;"
    )
    if not target_rows:
        return {'target': None, 'affected': [], 'total': 0}

    target = target_rows[0]
    project_id = target['project_id']

    # 재귀적 영향 분석 (BFS)
    visited = {node_id}
    affected = []
    current_level = [node_id]

    for dist in range(1, depth + 1):
        if not current_level:
            break

        ids_str = ','.join(str(i) for i in current_level)

        # 이 노드들을 참조하는(target_id가 현재 노드인) 노드들 조회
        reverse_deps = query_rows(f"""
            SELECT DISTINCT e.source_id AS id, n.file_path, n.name, n.node_type, n.signature, n.line_start
            FROM code_edges e
            JOIN code_nodes n ON n.id = e.source_id
            WHERE e.target_id IN ({ids_str}) AND e.project_id = {int(project_id)};
        """)

        next_level = []
        for dep in reverse_deps:
            dep_id = dep['id']
            if dep_id not in visited:
                visited.add(dep_id)
                dep['distance'] = dist
                affected.append(dep)
                next_level.append(dep_id)

        current_level = next_level

    return {'target': target, 'affected': affected, 'total': len(affected)}
