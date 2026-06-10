# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_schema.py
# 📝 설명: PostgreSQL 스키마 DDL(ensure_schema) + 레거시 JSONL/JSON 마이그레이션
#          (pg_store.py 분할 2/6)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
#   - [불변식] _SCHEMA_READY 플래그는 이 모듈 내부 상태 — 외부에서 직접 대입 금지.
#     프로젝트 DB 전환 후 재초기화는 reset_schema_cache() 사용 (server.py 기동 2단계).
#   - [WHY] _migrate_* 가 도메인 함수(set_memory/save_task 등)를 지연 import —
#     pg_memory/pg_tasks가 pg_base→(지연)ensure_schema 경로로 이 모듈을 쓰므로
#     모듈 레벨 상호 import 시 순환 발생. 마이그레이션은 최초 1회만 실행되어
#     함수 내부 import 비용은 무시 가능.
# ────────────────────────────────────────────────────────────────────────────
import json
import threading
from pathlib import Path

from src.file_store import (
    ensure_legacy_store,
    load_memory_entries,
    load_session_logs,
    load_skill_chain_rows,
)
from src.pg_base import (
    DATA_DIR,
    _ensure_pg_running,
    _now_iso,
    _parse_json_text,
    _sql_text,
    execute,
    execute_raw,
    query_rows,
)

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_MIGRATION_DONE = False


def reset_schema_cache() -> None:
    """스키마 준비 플래그를 리셋한다 — set_project_db()로 DB가 바뀐 직후 호출.

    [WHY] server.py 기동 2단계에서 프로젝트 DB 전환 후 새 DB에 스키마를 다시
    배치해야 하는데, 분할 전에는 `pg_store._SCHEMA_READY = False` 직접 대입으로
    처리했다. 분할 후 플래그가 이 모듈 내부 상태가 되어 함수로 캡슐화.
    """
    global _SCHEMA_READY
    _SCHEMA_READY = False
    # vector 가용성도 DB 단위 상태 — 프로젝트 DB 전환 시 함께 재확인
    try:
        from src.pg_vector_search import reset_vector_cache
        reset_vector_cache()
    except Exception:
        pass


def ensure_schema(data_dir: Path | None = None) -> bool:
    global _SCHEMA_READY, _MIGRATION_DONE
    if _SCHEMA_READY:
        return True
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        if not _ensure_pg_running():
            return False
        schema_sql = """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        CREATE TABLE IF NOT EXISTS pg_logs (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            agent TEXT NOT NULL DEFAULT 'unknown',
            terminal_id TEXT DEFAULT '',
            task TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'success',
            project_id TEXT DEFAULT '',
            metadata JSONB DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_pg_logs_project_id ON pg_logs (project_id);
        CREATE INDEX IF NOT EXISTS idx_pg_logs_ts ON pg_logs (ts DESC);
        CREATE TABLE IF NOT EXISTS pg_messages (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            from_agent TEXT DEFAULT '',
            to_agent TEXT DEFAULT '',
            msg_type TEXT DEFAULT 'info',
            content TEXT DEFAULT '',
            is_read BOOLEAN DEFAULT FALSE,
            channel TEXT DEFAULT 'general',
            metadata JSONB DEFAULT '{}'::jsonb,
            terminal_id TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_pg_messages_unread
            ON pg_messages (to_agent, is_read, ts DESC);

        CREATE TABLE IF NOT EXISTS hive_memory (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            author TEXT NOT NULL DEFAULT 'unknown',
            project_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT DEFAULT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hive_memory_updated ON hive_memory (updated_at DESC);
        -- idx_hive_memory_project_id: Phase 2 단계 2 RENAME 이후 execute_raw로 생성

        CREATE TABLE IF NOT EXISTS hive_sessions (
            id BIGSERIAL PRIMARY KEY,
            legacy_source TEXT,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id TEXT DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            agent TEXT DEFAULT '',
            trigger_msg TEXT DEFAULT '',
            status TEXT DEFAULT '',
            commit_hash TEXT DEFAULT '',
            files_changed JSONB NOT NULL DEFAULT '[]'::jsonb,
            ts_start TEXT NOT NULL DEFAULT '',
            ts_end TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_sessions_legacy
            ON hive_sessions (legacy_source, legacy_id)
            WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_sessions_start ON hive_sessions (ts_start DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_sessions_project_id ON hive_sessions (project_id);

        CREATE TABLE IF NOT EXISTS hive_tasks (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            assigned_to TEXT NOT NULL DEFAULT 'all',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_by TEXT NOT NULL DEFAULT 'user',
            kanban_status TEXT NOT NULL DEFAULT 'todo',
            role TEXT NOT NULL DEFAULT '',
            claimed_by TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb,
            project_id TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_updated ON hive_tasks (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_assigned ON hive_tasks (assigned_to, status);
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_project ON hive_tasks (project_id);

        CREATE TABLE IF NOT EXISTS hive_state (
            state_key TEXT PRIMARY KEY,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS hive_skill_chains (
            id BIGSERIAL PRIMARY KEY,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id INTEGER NOT NULL DEFAULT 0,
            agent TEXT DEFAULT '',
            request TEXT DEFAULT '',
            skill_num INTEGER DEFAULT 0,
            skill_name TEXT DEFAULT '',
            step_order INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            summary TEXT DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_skill_chains_legacy
            ON hive_skill_chains (legacy_id)
            WHERE legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_skill_chains_terminal
            ON hive_skill_chains (terminal_id, session_id, step_order);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_skill_chains_legacy_id
            ON hive_skill_chains (legacy_id)
            WHERE legacy_id IS NOT NULL;
        """
        if not execute_raw(schema_sql, timeout=30):
            return False
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS agent TEXT NOT NULL DEFAULT 'unknown';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS terminal_id TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS task TEXT NOT NULL DEFAULT '';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'success';")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS project_id TEXT DEFAULT '';")
        # Phase 2-2 (2026-04-30) — 빈 값 backfill 후 NOT NULL 강제
        execute_raw("UPDATE pg_logs SET project_id = '' WHERE project_id IS NULL;")
        execute_raw("ALTER TABLE pg_logs ALTER COLUMN project_id SET NOT NULL;")
        execute_raw("ALTER TABLE pg_logs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;")
        execute_raw("UPDATE pg_logs SET created_at = COALESCE(created_at, ts, NOW()) WHERE created_at IS NULL;")
        execute_raw("UPDATE pg_logs SET ts = COALESCE(ts, created_at, NOW()) WHERE ts IS NULL;")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_project_id ON pg_logs (project_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_ts ON pg_logs (ts DESC);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_logs_created_at ON pg_logs (created_at DESC);")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ DEFAULT NOW();")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS from_agent TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS to_agent TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS msg_type TEXT DEFAULT 'info';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS content TEXT DEFAULT '';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS channel TEXT DEFAULT 'general';")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;")
        execute_raw("ALTER TABLE pg_messages ADD COLUMN IF NOT EXISTS terminal_id TEXT DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_pg_messages_unread ON pg_messages (to_agent, is_read, ts DESC);")
        # 기존 테이블에 project_id 컬럼 없으면 추가 (마이그레이션)
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_project ON hive_tasks (project_id);")
        # 기존 hive_memory 테이블에 expires_at 컬럼 없으면 추가 (TTL 만료 정책)
        execute_raw("ALTER TABLE hive_memory ADD COLUMN IF NOT EXISTS expires_at TEXT DEFAULT NULL;")

        # [2026-03-29] 하이브 메모리 실시간 채팅 통합 — LISTEN/NOTIFY 트리거
        # hive_memory에 INSERT/UPDATE 시 'hive_realtime' 채널로 NOTIFY 발생
        # 그룹챗 브릿지와 대시보드가 LISTEN으로 실시간 수신
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_hive_realtime()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('hive_realtime',
                    json_build_object(
                        'key', NEW.key,
                        'title', NEW.title,
                        'content', NEW.content,
                        'tags', NEW.tags,
                        'author', NEW.author,
                        'updated_at', NEW.updated_at
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_hive_realtime') THEN
                    CREATE TRIGGER trg_hive_realtime
                    AFTER INSERT OR UPDATE ON hive_memory
                    FOR EACH ROW EXECUTE FUNCTION notify_hive_realtime();
                END IF;
            END;
            $$;
        """)

        # ── [2026-03-30] Paperclip 스타일 오케스트레이션 전환 ──────────────
        # Task 1: hive_tasks 확장 — 계층 구조 + 원자적 체크아웃 + 결과 기록
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS parent_id TEXT DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS checkout_by TEXT DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS checkout_at TIMESTAMPTZ DEFAULT NULL;")
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS result TEXT DEFAULT '';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_parent ON hive_tasks (parent_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_checkout ON hive_tasks (checkout_by);")

        # Task 2: 태스크 코멘트 — 에이전트 간 비동기 통신 (그룹 채팅 대체)
        execute_raw("""
            CREATE TABLE IF NOT EXISTS task_comments (
                id SERIAL PRIMARY KEY,
                task_id TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments (task_id, created_at);")

        # Task 3: 에이전트 하트비트 상태 — 자율 실행 모니터링
        execute_raw("""
            CREATE TABLE IF NOT EXISTS agent_heartbeats (
                agent_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'offline',
                last_beat TIMESTAMPTZ DEFAULT now(),
                current_task TEXT DEFAULT NULL,
                beat_count INT NOT NULL DEFAULT 0,
                config JSONB NOT NULL DEFAULT '{}'::jsonb
            );
        """)

        # Task 4: NOTIFY 트리거 — 태스크 할당 시 에이전트 자동 깨우기
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_task_assigned()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.assigned_to IS DISTINCT FROM OLD.assigned_to
                   AND NEW.assigned_to IS NOT NULL
                   AND NEW.assigned_to != '' THEN
                    PERFORM pg_notify('task_assigned',
                        json_build_object(
                            'task_id', NEW.id,
                            'agent', NEW.assigned_to,
                            'title', NEW.title,
                            'priority', NEW.priority
                        )::text
                    );
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_task_assigned') THEN
                    CREATE TRIGGER trg_task_assigned
                    AFTER UPDATE ON hive_tasks
                    FOR EACH ROW EXECUTE FUNCTION notify_task_assigned();
                END IF;
            END;
            $$;
        """)

        # ── [2026-04-05] Hive Zettelkasten — 카파시 + 루만 메모 시스템 ──────
        # 원자 노트 테이블: 하나의 노트 = 하나의 아이디어
        execute_raw("""
            CREATE TABLE IF NOT EXISTS zettel_notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                note_type TEXT NOT NULL DEFAULT 'fleeting',
                author TEXT NOT NULL DEFAULT 'unknown',
                project_id TEXT NOT NULL DEFAULT '',
                tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                source_ref TEXT DEFAULT '',
                access_count INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_rescued_at TIMESTAMPTZ,
                archived BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_type ON zettel_notes (note_type);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_author ON zettel_notes (author);")
        # idx_zettel_notes_project_id: Phase 2 단계 2 RENAME 이후 execute_raw로 생성
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_updated ON zettel_notes (updated_at DESC);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_rescued ON zettel_notes (last_rescued_at DESC NULLS LAST);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_archived ON zettel_notes (archived, updated_at DESC);")

        # 백링크 테이블: 노트 간 양방향 연결
        execute_raw("""
            CREATE TABLE IF NOT EXISTS zettel_links (
                id SERIAL PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES zettel_notes(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES zettel_notes(id) ON DELETE CASCADE,
                link_type TEXT NOT NULL DEFAULT 'relates_to',
                created_by TEXT NOT NULL DEFAULT 'system',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(source_id, target_id, link_type)
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_source ON zettel_links (source_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_target ON zettel_links (target_id);")

        # NOTIFY 트리거 — 노트 변경 시 실시간 알림
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_zettel_change()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('zettel_change',
                    json_build_object(
                        'id', NEW.id,
                        'title', NEW.title,
                        'note_type', NEW.note_type,
                        'author', NEW.author,
                        'updated_at', NEW.updated_at
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_zettel_change') THEN
                    CREATE TRIGGER trg_zettel_change
                    AFTER INSERT OR UPDATE ON zettel_notes
                    FOR EACH ROW EXECUTE FUNCTION notify_zettel_change();
                END IF;
            END;
            $$;
        """)

        # ── [2026-04-09] 클래식/오피스 워커 네임스페이스 분리 ──
        # hive_tasks, agent_heartbeats에 source/namespace 컬럼을 추가해
        # 두 모드의 실행 상태가 섞이지 않도록 한다.
        execute_raw("ALTER TABLE hive_tasks ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'classic';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_tasks_source ON hive_tasks (source, status);")
        execute_raw("ALTER TABLE agent_heartbeats ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'classic';")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_ns ON agent_heartbeats (namespace);")

        # ── [2026-04-09] 오피스 프로필 중앙화 — localStorage → PostgreSQL SSOT ──
        # 창(pywebview/QWebEngine)이 여러 개라 localStorage를 공유할 수 없고
        # 브라우저별 영구 저장 정책이 달라 데이터 유실이 발생하므로
        # 서버 단일 진실의 원천(SSOT)으로 프로필을 이동한다.
        execute_raw("""
            CREATE TABLE IF NOT EXISTS office_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_office_profiles_updated ON office_profiles (updated_at DESC);")

        # 활성 프로필 포인터 — 싱글톤 레코드 (id=1 고정)
        execute_raw("""
            CREATE TABLE IF NOT EXISTS office_profile_state (
                id INT PRIMARY KEY DEFAULT 1,
                active_profile_id TEXT NOT NULL DEFAULT 'default',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT office_profile_state_singleton CHECK (id = 1)
            );
        """)
        execute_raw("INSERT INTO office_profile_state (id, active_profile_id) VALUES (1, 'default') ON CONFLICT (id) DO NOTHING;")

        # NOTIFY 트리거 — 프로필 변경 시 'office_profiles_changed' 채널로 알림
        # 모든 창(메인/오피스)의 SSE 구독자가 즉시 반영
        execute_raw("""
            CREATE OR REPLACE FUNCTION notify_office_profiles_changed()
            RETURNS TRIGGER AS $$
            DECLARE
                payload TEXT;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    payload := json_build_object('op', 'delete', 'id', OLD.id)::text;
                ELSE
                    payload := json_build_object('op', TG_OP, 'id', NEW.id)::text;
                END IF;
                PERFORM pg_notify('office_profiles_changed', payload);
                RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_office_profiles_changed') THEN
                    CREATE TRIGGER trg_office_profiles_changed
                    AFTER INSERT OR UPDATE OR DELETE ON office_profiles
                    FOR EACH ROW EXECUTE FUNCTION notify_office_profiles_changed();
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_office_profile_state_changed') THEN
                    CREATE TRIGGER trg_office_profile_state_changed
                    AFTER UPDATE ON office_profile_state
                    FOR EACH ROW EXECUTE PROCEDURE notify_office_profiles_changed();
                END IF;
            END;
            $$;
        """)

        # ── [2026-04-10] 진화하는 LLM — 에이전트 경험/성장 시스템 ──
        execute_raw("""
            CREATE TABLE IF NOT EXISTS agent_experience (
                id BIGSERIAL PRIMARY KEY,
                agent_id TEXT NOT NULL,
                session_id TEXT DEFAULT '',
                task_type TEXT NOT NULL DEFAULT 'feat',
                domain TEXT NOT NULL DEFAULT 'general',
                file_patterns JSONB DEFAULT '[]'::jsonb,
                duration_sec INTEGER DEFAULT 0,
                outcome TEXT NOT NULL DEFAULT 'success',
                xp_earned INTEGER NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_agent_exp_agent ON agent_experience (agent_id, created_at DESC);")
        execute_raw("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_exp_session ON agent_experience (agent_id, session_id) WHERE session_id != '';")

        # ── [2026-04-14] 활성 세션 컨텍스트 — 크래시 복구용 ──
        # 매 UserPromptSubmit마다 현재 작업 상태를 기록.
        # Stop 이벤트 시 status='done'으로 갱신.
        # 앱 비정상 종료 시 status='active'인 레코드가 남아 → 다음 세션에서 복구 브리핑.
        execute_raw("""
            CREATE TABLE IF NOT EXISTS active_session_context (
                id BIGSERIAL PRIMARY KEY,
                terminal_id TEXT NOT NULL DEFAULT 'T0',
                agent_id TEXT NOT NULL DEFAULT 'claude',
                task_summary TEXT NOT NULL DEFAULT '',
                modified_files JSONB NOT NULL DEFAULT '[]'::jsonb,
                status TEXT NOT NULL DEFAULT 'active',
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_active_session_status ON active_session_context (status, terminal_id);")
        # [2026-06-10 자가 치유 2.0 ②] 의도 단위 체크포인트 — 복구 브리핑을
        # "파일 목록"에서 "왜/어디까지 결정/다음 뭐" 수준으로 격상하는 3컬럼
        execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS intent TEXT NOT NULL DEFAULT '';")
        execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS decisions JSONB NOT NULL DEFAULT '[]'::jsonb;")
        execute_raw("ALTER TABLE active_session_context ADD COLUMN IF NOT EXISTS next_step TEXT NOT NULL DEFAULT '';")

        execute_raw("""
            CREATE TABLE IF NOT EXISTS agent_stats (
                agent_id TEXT PRIMARY KEY,
                total_xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                task_count INTEGER NOT NULL DEFAULT 0,
                skill_map JSONB NOT NULL DEFAULT '{}'::jsonb,
                streak_days INTEGER NOT NULL DEFAULT 0,
                last_active TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # ── [2026-04-14] 코드 인텔리전스 — MindVault 영감 기반 코드 그래프 ──
        # tree-sitter AST 파싱 결과를 저장하여 BM25 검색 + 의존관계 그래프 제공
        execute_raw("""
            CREATE TABLE IF NOT EXISTS code_projects (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                root_path TEXT NOT NULL UNIQUE,
                language TEXT NOT NULL DEFAULT '',
                file_count INTEGER NOT NULL DEFAULT 0,
                node_count INTEGER NOT NULL DEFAULT 0,
                last_indexed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        execute_raw("""
            CREATE TABLE IF NOT EXISTS code_nodes (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES code_projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                node_type TEXT NOT NULL DEFAULT 'function',
                name TEXT NOT NULL DEFAULT '',
                signature TEXT DEFAULT '',
                line_start INTEGER NOT NULL DEFAULT 0,
                line_end INTEGER NOT NULL DEFAULT 0,
                docstring TEXT DEFAULT '',
                raw_content TEXT DEFAULT '',
                content_tsv TSVECTOR
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_nodes_project ON code_nodes (project_id, node_type);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_nodes_file ON code_nodes (project_id, file_path);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_nodes_name ON code_nodes (name);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_nodes_tsv ON code_nodes USING GIN (content_tsv);")

        # content_tsv 자동 업데이트 트리거
        execute_raw("""
            CREATE OR REPLACE FUNCTION code_nodes_tsv_update()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.content_tsv := to_tsvector('english',
                    COALESCE(NEW.name, '') || ' ' ||
                    COALESCE(NEW.signature, '') || ' ' ||
                    COALESCE(NEW.docstring, '') || ' ' ||
                    COALESCE(NEW.raw_content, '')
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        execute_raw("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_code_nodes_tsv') THEN
                    CREATE TRIGGER trg_code_nodes_tsv
                    BEFORE INSERT OR UPDATE ON code_nodes
                    FOR EACH ROW EXECUTE FUNCTION code_nodes_tsv_update();
                END IF;
            END;
            $$;
        """)

        execute_raw("""
            CREATE TABLE IF NOT EXISTS code_edges (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES code_projects(id) ON DELETE CASCADE,
                source_id INTEGER NOT NULL REFERENCES code_nodes(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES code_nodes(id) ON DELETE CASCADE,
                edge_type TEXT NOT NULL DEFAULT 'imports'
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_edges_source ON code_edges (source_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_edges_target ON code_edges (target_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_edges_project ON code_edges (project_id, edge_type);")

        execute_raw("""
            CREATE TABLE IF NOT EXISTS code_wiki (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES code_projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                source_hash TEXT DEFAULT '',
                wiki_type TEXT NOT NULL DEFAULT 'file',
                node_id INTEGER REFERENCES code_nodes(id) ON DELETE CASCADE,
                generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_code_wiki_project ON code_wiki (project_id);")
        execute_raw("CREATE UNIQUE INDEX IF NOT EXISTS idx_code_wiki_compound ON code_wiki (project_id, file_path, wiki_type, COALESCE(node_id, -1));")
        # 기존 DB 마이그레이션 — wiki_type, node_id 컬럼 추가
        execute_raw("ALTER TABLE code_wiki ADD COLUMN IF NOT EXISTS wiki_type TEXT NOT NULL DEFAULT 'file';")
        execute_raw("ALTER TABLE code_wiki ADD COLUMN IF NOT EXISTS node_id INTEGER REFERENCES code_nodes(id) ON DELETE CASCADE;")

        # ── [2026-04-19] Platform Phase 2 단계 2 — project → project_id 컬럼 RENAME ──
        # hive_memory, hive_sessions, zettel_notes 3개 테이블의 구 컬럼 'project'를
        # 'project_id'로 통일. 멱등: 이미 바뀐 DB에서는 no-op.
        _rename_pairs = [
            ("hive_memory",   "idx_hive_memory_project"),
            ("hive_sessions", None),
            ("zettel_notes",  "idx_zettel_notes_project"),
        ]
        for _tbl, _old_idx in _rename_pairs:
            execute_raw(f"""
                DO $$ BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='{_tbl}' AND column_name='project'
                  ) THEN
                    ALTER TABLE {_tbl} RENAME COLUMN project TO project_id;
                  END IF;
                END $$;
            """)
            if _old_idx:
                execute_raw(f"DROP INDEX IF EXISTS {_old_idx};")
        # RENAME 후 새 인덱스 생성 — 구 스키마에서도 안전하게 실행 가능
        execute_raw("CREATE INDEX IF NOT EXISTS idx_hive_memory_project_id ON hive_memory (project_id);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_notes_project_id ON zettel_notes (project_id);")

        # ── [2026-04-19] Platform Phase 2 단계 3 — Layer 1 project_id 스코프 강제 ──
        # 모든 Layer 1 테이블이 project_id TEXT NOT NULL DEFAULT ''를 갖도록 업그레이드.
        # 데이터 backfill은 scripts/migrate_project_id_backfill.py가 담당.
        # 상위 문서: docs/PLATFORM_LAYERS.md
        _layer1_project_id_tables = [
            "zettel_links",
            "agent_experience",
            "agent_heartbeats",
            "agent_stats",
            "active_session_context",
            "hive_skill_chains",
            "hive_state",
            "office_profile_state",
            "office_profiles",
            "pg_messages",
            "task_comments",
        ]
        for _tbl in _layer1_project_id_tables:
            execute_raw(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';")
            execute_raw(f"CREATE INDEX IF NOT EXISTS idx_{_tbl}_project_id ON {_tbl} (project_id);")

        # ── [2026-06-10] 자가 치유 2.0 ① — 사고 장부 ──
        # 고친 에러를 기억: 동일 시그니처 재발 시 과거 수정법을 훅이 주입.
        # 시그니처 = pg_incidents.normalize_signature (경로/줄번호/주소/시각 제거 해시)
        execute_raw("""
            CREATE TABLE IF NOT EXISTS incident_ledger (
                id BIGSERIAL PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                error_signature TEXT NOT NULL,
                error_text TEXT NOT NULL DEFAULT '',
                root_cause TEXT NOT NULL DEFAULT '',
                fix_description TEXT NOT NULL DEFAULT '',
                fix_commit TEXT DEFAULT '',
                files JSONB NOT NULL DEFAULT '[]'::jsonb,
                recurrence_count INT NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (project_id, error_signature)
            );
        """)
        execute_raw("CREATE INDEX IF NOT EXISTS idx_incident_sig ON incident_ledger (error_signature);")
        execute_raw("CREATE INDEX IF NOT EXISTS idx_incident_project ON incident_ledger (project_id, last_seen_at DESC);")

        _SCHEMA_READY = True

        # ── [2026-06-10] 자가 치유 2.0 ④ — pgvector 회상 스키마 (선택적) ──
        # [제약] 반드시 _SCHEMA_READY=True 이후 — pg_vector_search가 query_rows를
        # 쓰므로 그 전에 부르면 ensure_schema 재진입(_SCHEMA_LOCK 데드락).
        # 확장 미설치 DB에서는 내부적으로 무음 비활성 (ILIKE 회상 폴백 유지).
        try:
            from src.pg_vector_search import ensure_vector_schema
            ensure_vector_schema()
        except Exception as _ve:
            print(f"[pg_schema] vector 스키마 스킵: {_ve}")

        if not _MIGRATION_DONE:
            # DB에 마이그레이션 완료 플래그 확인 — 프로세스 재시작 시 재실행 방지
            _mig_check = query_rows(
                "SELECT payload FROM hive_state WHERE state_key = 'migration_done' LIMIT 1;"
            )
            if not _mig_check:
                migrate_legacy_data(data_dir or DATA_DIR)
                execute("INSERT INTO hive_state (state_key, payload, updated_at) "
                        f"VALUES ('migration_done', '{{\"v\":1}}'::jsonb, {_sql_text(_now_iso())}) "
                        "ON CONFLICT (state_key) DO NOTHING;")
            _MIGRATION_DONE = True
        return True

def migrate_legacy_data(data_dir: Path | None = None) -> None:
    data_dir = data_dir or DATA_DIR
    ensure_legacy_store(data_dir)
    _migrate_memory(data_dir)
    _migrate_sessions(data_dir)
    _migrate_tasks(data_dir / 'tasks.json')
    _migrate_state_file(data_dir / 'hive_health.json', 'health')
    _migrate_state_file(data_dir / 'skill_analysis.json', 'skill_analysis')
    _migrate_skill_chains(data_dir)


def _migrate_memory(data_dir: Path) -> None:
    from src.pg_memory import set_memory  # 순환 import 방지 지연 import (헤더 참고)
    rows = load_memory_entries(data_dir)
    for row in rows:
        set_memory(
            key=row.get('key', ''),
            content=row.get('content', ''),
            title=row.get('title', '') or row.get('key', ''),
            tags=_parse_json_text(row.get('tags'), []),
            author=row.get('author', 'unknown'),
            project_id=row.get('project', ''),
            created_at=row.get('created_at') or row.get('updated_at') or '',
            updated_at=row.get('updated_at') or row.get('created_at') or '',
        )


def _migrate_sessions(data_dir: Path) -> None:
    from src.pg_memory import upsert_session_log  # 순환 import 방지 지연 import
    rows = list(reversed(load_session_logs(data_dir)))
    for row in rows:
        upsert_session_log(
            session_id=row.get('session_id', ''),
            terminal_id=row.get('terminal_id', ''),
            project_id=row.get('project', ''),
            agent=row.get('agent', ''),
            trigger_msg=row.get('trigger_msg', ''),
            status=row.get('status', ''),
            commit_hash=row.get('commit_hash', ''),
            files_changed=_parse_json_text(row.get('files_changed'), []),
            ts_start=row.get('ts_start', ''),
            ts_end=row.get('ts_end', ''),
            legacy_source='session_logs.jsonl',
            legacy_id=row.get('id'),
        )


def _migrate_tasks(path: Path) -> None:
    if not path.exists():
        return
    try:
        tasks = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    if not isinstance(tasks, list):
        return
    from src.pg_tasks import save_task  # 순환 import 방지 지연 import
    for task in tasks:
        if isinstance(task, dict):
            save_task(task)


def _migrate_state_file(path: Path, state_key: str) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    from src.pg_tasks import save_state  # 순환 import 방지 지연 import
    save_state(state_key, payload)


def _migrate_skill_chains(data_dir: Path) -> None:
    from src.pg_tasks import upsert_skill_chain_row  # 순환 import 방지 지연 import
    rows = load_skill_chain_rows(data_dir)
    for row in rows:
        upsert_skill_chain_row(row, legacy_id=row.get('id'))

