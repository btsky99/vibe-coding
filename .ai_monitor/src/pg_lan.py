"""
FILE: src/pg_lan.py
DESCRIPTION: LAN 브리지 채팅 이력(lan_messages) CRUD. 기기간 채팅을 현재 프로젝트 컨텍스트로
             영구 저장한다. 브리지가 아니라 server.py(lan_api)가 호출 — 브리지는 project_id 무지.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 브리지 Phase 2 Task 1. office_chat과 별도(혼용 금지).
"""
# [불변식] 1:1 대화 = (from=self AND to=peer) OR (from=peer AND to=self) 양방향. self_id를
#   인자로 받아 정확히 두 방향만 조회 — peer만으로 필터하면 제3자 대화가 섞일 수 있음.
# [보안] content는 _sql_text 파라미터 바인딩(인젝션 차단). since_id는 int() 강제.
from infra.project_context import assert_project_id
from src.pg_base import _sql_text, execute, query_rows


def save_lan_message(from_peer: str, to_peer: str, content: str,
                     project_id: str = '') -> bool:
    """채팅 1건 저장. 진입부 project_id 가드(빈 값 dev 경고)."""
    project_id = assert_project_id(project_id, 'save_lan_message')
    return execute(
        f"INSERT INTO lan_messages (from_peer, to_peer, content, project_id) "
        f"VALUES ({_sql_text(from_peer)}, {_sql_text(to_peer)}, "
        f"{_sql_text(content)}, {_sql_text(project_id)});"
    )


def get_lan_messages(self_id: str, peer_id: str, since_id: int = 0,
                     project_id: str = '') -> list[dict]:
    """나(self_id)↔peer_id 대화를 id>since_id로 증분 조회(id ASC). 폴링 커서용."""
    try:
        since = int(since_id)
    except (TypeError, ValueError):
        since = 0
    return query_rows(
        f"SELECT id, from_peer, to_peer, content, "
        f"to_char(ts, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS ts "
        f"FROM lan_messages "
        f"WHERE project_id = {_sql_text(project_id)} AND id > {since} AND ("
        f"(from_peer = {_sql_text(self_id)} AND to_peer = {_sql_text(peer_id)}) OR "
        f"(from_peer = {_sql_text(peer_id)} AND to_peer = {_sql_text(self_id)})) "
        f"ORDER BY id ASC LIMIT 500;"
    )
