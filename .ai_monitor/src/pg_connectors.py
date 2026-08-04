"""
FILE: src/pg_connectors.py
DESCRIPTION: 외부 connector 이벤트의 PostgreSQL 중복 방지와 감사 기록 저장소.

REVISION HISTORY:
- 2026-08-03 Codex: Discord Gateway용 connector_events 저장소 최초 구현
"""

from __future__ import annotations

import json

from src.pg_base import _sql_text, execute, query_rows


def ensure_connector_schema() -> bool:
    return execute("""
        CREATE TABLE IF NOT EXISTS connector_events (
            id BIGSERIAL PRIMARY KEY,
            platform TEXT NOT NULL,
            external_event_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            channel_id TEXT NOT NULL DEFAULT '',
            terminal_id TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'received',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (platform, external_event_id, direction)
        );
        CREATE INDEX IF NOT EXISTS idx_connector_events_created
            ON connector_events (created_at DESC);
    """)


def claim_event(platform: str, external_event_id: str, actor_id: str = '',
                channel_id: str = '', terminal_id: str = '', project_id: str = '',
                metadata: dict | None = None) -> bool:
    """새 inbound 이벤트면 기록하고 True, 이미 처리한 이벤트면 False를 반환한다."""
    ensure_connector_schema()
    result = query_rows(f"""
        INSERT INTO connector_events
            (platform, external_event_id, direction, actor_id, channel_id,
             terminal_id, project_id, status, metadata)
        VALUES ({_sql_text(platform)}, {_sql_text(external_event_id)}, 'inbound',
                {_sql_text(actor_id)}, {_sql_text(channel_id)}, {_sql_text(terminal_id)},
                {_sql_text(project_id)}, 'claimed',
                {_sql_text(json.dumps(metadata or {}, ensure_ascii=False))}::jsonb)
        ON CONFLICT (platform, external_event_id, direction) DO NOTHING
        RETURNING id;
    """)
    return bool(result)


def mark_event(platform: str, external_event_id: str, status: str,
               metadata: dict | None = None) -> bool:
    detail = json.dumps(metadata or {}, ensure_ascii=False)
    return execute(f"""
        UPDATE connector_events
        SET status = {_sql_text(status)}, metadata = metadata || {_sql_text(detail)}::jsonb
        WHERE platform = {_sql_text(platform)}
          AND external_event_id = {_sql_text(external_event_id)}
          AND direction = 'inbound';
    """)
