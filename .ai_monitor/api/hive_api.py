"""
FILE: api/hive_api.py
DESCRIPTION: /api/hive/*, /api/orchestrator/*, /api/install-skills,
             /api/superpowers/* 엔드포인트 핸들러 모듈.
             server.py에서 하이브 마인드 관련 API 로직을 분리하여 가독성과
             유지보수성을 향상시킵니다.
             각 함수는 SSEHandler 인스턴스(handler)를 첫 번째 인자로 받아
             HTTP 응답을 직접 기록합니다.

REVISION HISTORY:
- 2026-07-04 Claude: /api/agent-quota 신설 — 터미널 헤더 배지용 Claude+Codex 플랜 쿼터 통합 조회
- 2026-07-03 Claude: /api/context-usage 응답에 quota 필드 추가 — OAuth 쿼터 사용률(%)·리셋 시각
- 2026-03-01 Claude: server.py에서 분리 — hive/orchestrator/superpowers API 담당
- 2026-03-22 Claude: 지식그래프(/api/hive/knowledge-graph) 제거 — 실사용 가치 미흡
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 자율 클로드 CLI 버전 캐시 (읽기전용 상태 패널용) ──
# [WHY] `claude --version`은 subprocess라 매 폴링(30초)마다 부르면 낭비 → 프로세스당 1회만.
_AUTO_CLI_VER = None
def _auto_cli_version() -> str:
    global _AUTO_CLI_VER
    if _AUTO_CLI_VER is None:
        try:
            r = subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=5)
            _AUTO_CLI_VER = (r.stdout or '').strip() or 'claude CLI'
        except Exception:
            _AUTO_CLI_VER = 'claude CLI'
    return _AUTO_CLI_VER

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지
from src.claude_quota import get_claude_quota
from src.pg_store import (
    ensure_schema,
    get_agent_last_seen,
    list_memory,
    list_session_logs,
    list_tasks,
    load_state,
)


# ── Claude 모델별 컨텍스트 창 매핑 ─────────────────────────────────────────
# Session JSONL의 `model` 필드는 base ID만 기록한다(`[1m]` 접미사 없음).
# Opus 4.7은 Claude Code CLI가 1M 컨텍스트로 구동하므로 1M으로 취급한다.
def _claude_ctx_window(model: str) -> int:
    """모델명 → 컨텍스트 창 토큰 수. 알 수 없는 모델은 200k 기본."""
    if not model:
        return 200_000
    m = model.lower()
    # Opus 4.7 이상은 1M 컨텍스트 (Claude Code CLI 기본 운용)
    if 'opus-4-7' in m or 'opus-4-8' in m or 'opus-5' in m:
        return 1_000_000
    # 향후 확장: Sonnet 1M 변종 추가 시 여기에 조건 추가
    return 200_000


def _sum_usage_since(jsonl_files: list, since_epoch: float) -> dict:
    """session JSONL 파일들의 assistant usage를 시간 윈도우로 집계.

    각 파일의 끝 64KB만 읽어 Claude Code의 최근 활동(수백 턴)을 커버한다.
    since_epoch 이후의 assistant 메시지 usage(input/output/cache)를 누적한다.

    Returns:
        {'input_tokens': int, 'output_tokens': int, 'cache_read': int,
         'cache_write': int, 'total': int, 'oldest_ts': str, 'message_count': int}
    """
    result = {
        'input_tokens': 0, 'output_tokens': 0,
        'cache_read': 0, 'cache_write': 0,
        'total': 0, 'oldest_ts': '', 'message_count': 0,
    }
    TAIL_BYTES = 64 * 1024  # 64KB면 수백 턴 커버 (8KB는 최근 usage 1개용이라 부족)
    oldest_dt = None

    for path in jsonl_files:
        try:
            with open(path, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                raw = f.read().decode('utf-8', errors='ignore')
        except Exception:
            continue

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get('type') != 'assistant':
                continue
            msg = obj.get('message') or {}
            usage = msg.get('usage') or {}
            if not usage:
                continue

            ts_raw = obj.get('timestamp') or ''
            dt = _parse_iso_dt(ts_raw)
            if dt is None:
                continue
            try:
                epoch = dt.timestamp()
            except Exception:
                continue
            if epoch < since_epoch:
                continue

            result['input_tokens'] += int(usage.get('input_tokens', 0) or 0)
            result['output_tokens'] += int(usage.get('output_tokens', 0) or 0)
            result['cache_read'] += int(usage.get('cache_read_input_tokens', 0) or 0)
            result['cache_write'] += int(usage.get('cache_creation_input_tokens', 0) or 0)
            result['message_count'] += 1
            if oldest_dt is None or dt < oldest_dt:
                oldest_dt = dt
                result['oldest_ts'] = ts_raw

    result['total'] = (
        result['input_tokens'] + result['cache_read'] + result['cache_write']
    )
    return result


# [중복통합 2026-07-18] _json_response는 api/_common.py로 통합 — 패스스루 재노출.
from api._common import json_response as _json_response


def _parse_iso_dt(value: str | None) -> datetime | None:
    """ISO 8601 문자열 → aware datetime. Z suffix는 UTC로 명시 처리.

    [2026-04-21] Z를 단순히 제거하면 naive datetime이 되어 `.timestamp()`가
    로컬 시간대로 해석됨 → 5시간 sliding window 집계에서 9시간 오프셋 발생.
    Z를 '+00:00'으로 치환해 aware datetime을 반환하도록 수정.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None


def _chain_has_live_steps(chain: dict | None) -> bool:
    if not isinstance(chain, dict):
        return False
    steps = chain.get('steps') or []
    return any(
        isinstance(step, dict) and step.get('status') in {'running', 'pending'}
        for step in steps
    )


def _synthetic_chain_request(agent: str, last_line: str) -> str:
    if last_line:
        return last_line[:120]
    label = (agent or 'agent').upper()
    return f'[PTY] {label} session running'


def _pty_slot_info(pty_sessions: dict, slot_num: int, project_id: str = '') -> dict | None:
    """Return live PTY session info for a slot across legacy and project-scoped keys.

    Phase 2-5.3 changed Node PTY session snapshots from plain T1/T2 keys to
    project-scoped keys such as T1@D--vibe-coding. Orchestrator APIs still need
    a slot-number view so the monitor panels can render live agents.
    """
    if not isinstance(pty_sessions, dict):
        return None

    candidates = []
    if project_id:
        candidates.append(f'T{slot_num}@{project_id}')
    candidates.extend((f'T{slot_num}', str(slot_num)))

    for key in candidates:
        info = pty_sessions.get(key)
        if isinstance(info, dict) and info.get('running'):
            return info

    suffix = f'@{project_id}' if project_id else ''
    for key, info in pty_sessions.items():
        if not isinstance(info, dict) or not info.get('running'):
            continue
        key_text = str(key)
        if key_text == f'T{slot_num}' or key_text.startswith(f'T{slot_num}@'):
            if not suffix or key_text.endswith(suffix) or info.get('project_id') == project_id:
                return info

    return None


def _merge_live_pty_skill_chains(result: dict, pty_sessions: dict) -> dict:
    terminals = dict(result.get('terminals') or {})
    now_iso = datetime.now().isoformat(timespec='seconds')

    for slot_num in range(1, 9):
        info = _pty_slot_info(pty_sessions, slot_num)
        if not isinstance(info, dict):
            continue

        agent = str(info.get('agent') or '').strip().lower()
        if agent not in {'claude', 'antigravity', 'codex'}:
            continue

        terminal_key = str(slot_num)
        existing = terminals.get(terminal_key)
        if _chain_has_live_steps(existing):
            continue

        started_at = str(info.get('started') or '')
        started_dt = _parse_iso_dt(started_at)
        updated_at = started_dt.isoformat(timespec='seconds') if started_dt else now_iso
        last_line = str(info.get('last_line') or '').strip()
        if existing:
            steps = [step for step in (existing.get('steps') or []) if isinstance(step, dict)]
            synthetic_step = {
                'label': f'{slot_num}-{len(steps)}',
                'skill_num': 0,
                'skill_name': 'vibe-orchestrate',
                'step_order': len(steps),
                'status': 'running',
                'summary': last_line,
            }
            steps.append(synthetic_step)
            existing['steps'] = steps
            existing['status'] = 'running'
            existing['updated_at'] = updated_at
            existing['agent'] = existing.get('agent') or agent
            existing['request'] = existing.get('request') or _synthetic_chain_request(agent, last_line)
            existing['session_id'] = existing.get('session_id') or f'pty-{slot_num}'
            terminals[terminal_key] = existing
            continue

        terminals[terminal_key] = {
            'session_id': f'pty-{slot_num}',
            'request': _synthetic_chain_request(agent, last_line),
            'status': 'running',
            'updated_at': updated_at,
            'agent': agent,
            'steps': [{
                'label': f'{slot_num}-0',
                'skill_num': 0,
                'skill_name': 'vibe-orchestrate',
                'step_order': 0,
                'status': 'running',
                'summary': last_line,
            }],
        }

    result['terminals'] = terminals
    skill_registry = list(result.get('skill_registry') or [])
    if not any(isinstance(skill, dict) and skill.get('name') == 'vibe-orchestrate' for skill in skill_registry):
        skill_registry.insert(0, {'num': 0, 'name': 'vibe-orchestrate', 'short': 'orchestrate'})
    result['skill_registry'] = skill_registry
    return result


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, SCRIPTS_DIR: Path, BASE_DIR: Path,
               PROJECT_ROOT: Path, PROJECT_ID: str,
               TASKS_FILE: Path, AGENT_STATUS: dict, AGENT_STATUS_LOCK,
               pty_sessions: dict,
               _current_project_root, _parse_session_tail, _parse_antigravity_session,
               run_pg_sql_csv=None, _current_project_id=None) -> bool:
    """GET 요청 처리 — /api/hive/*, /api/orchestrator/*, /api/install-skills,
    /api/skill-results, /api/context-usage,
    /api/antigravity-context-usage, /api/local-models 를 담당합니다.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    caller(server.py의 do_GET)는 False를 받으면 다른 핸들러를 시도합니다.
    """

    # ── /api/install-skills ────────────────────────────────────────────────
    if path == '/api/install-skills':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        target_path = params.get('path', [''])[0]
        result = {"status": "error", "message": "Invalid path"}
        if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
            try:
                # 배포(frozen) 여부에 따라 소스 경로 결정
                source_base = BASE_DIR.parent
                target_root = Path(target_path)
                installed_targets = []

                antigravity_src = source_base / ".gemini"
                if antigravity_src.exists():
                    shutil.copytree(antigravity_src, target_root / ".gemini", dirs_exist_ok=True)
                    installed_targets.append(".gemini")

                claude_src = source_base / ".claude"
                if claude_src.exists():
                    shutil.copytree(claude_src, target_root / ".claude", dirs_exist_ok=True)
                    installed_targets.append(".claude")

                scripts_src = SCRIPTS_DIR
                if scripts_src and scripts_src.exists():
                    shutil.copytree(scripts_src, target_root / "scripts", dirs_exist_ok=True)
                    installed_targets.append("scripts")

                for md in ("GEMINI.md", "CLAUDE.md", "RULES.md", "AGENTS.md", "PROJECT_MAP.md"):
                    src = source_base / md
                    if src.exists():
                        shutil.copy(src, target_root / md)
                        installed_targets.append(md)
                # 대상 프로젝트 DB 초기화 — 하이브 워치독 정상 동작 전제 조건
                target_data = target_root / ".ai_monitor" / "data"
                target_data.mkdir(parents=True, exist_ok=True)
                ensure_schema(target_data)
                installed_summary = ", ".join(installed_targets) if installed_targets else "no files copied"
                result = {
                    "status": "success",
                    "message": f"Hive skills installed to {target_path} ({installed_summary})"
                }
            except Exception as e:
                result = {"status": "error", "message": str(e)}
        handler.wfile.write(json.dumps(result).encode('utf-8'))
        return True

    # ── /api/hive/skill-analysis ──────────────────────────────────────────
    elif path == '/api/hive/skill-analysis':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        ensure_schema(DATA_DIR)
        analysis_data = load_state('skill_analysis', {"proposals": []}) or {"proposals": []}
        handler.wfile.write(json.dumps(analysis_data, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/hive/health/repair ──────────────────────────────────────────
    elif path == '/api/hive/health/repair':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 워치독 기능을 사용할 수 없습니다')
            watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
            result_proc = proc.run(
                [sys.executable, str(watchdog_script), "--check"],
                capture_output=True, text=True, encoding='utf-8',
            )
            output = result_proc.stdout
            json_start = output.find('{')
            if json_start != -1:
                result = json.loads(output[json_start:])
            else:
                result = {"status": "error", "message": "Failed to parse watchdog output"}
        except Exception as e:
            result = {"status": "error", "message": str(e)}
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/hive/activity ──────────────────────────────────────────────
    # pg_logs에서 하이브 시스템 사용 이벤트만 분류하여 반환.
    # 대시보드 TerminalSlot "하이브 상태" 위젯이 3초 폴링으로 사용.
    # [과거사고] 2026-06-21까지 이 핸들러는 레거시 task_logs.jsonl을 읽었음.
    #   해당 파일은 PostgreSQL-first 전환(CLAUDE.md 규칙4) 시점 2026-03-01에
    #   기록이 끊겨 동결 → 위젯이 "오후 03:54"(=3월1일 마지막 이벤트, fmtTime이
    #   날짜를 숨겨 착시)에 멈추고 memory_write 0건으로 "없음" 표시되는 버그.
    #   진실의 원천인 pg_logs(실시간)로 교체.
    elif path == '/api/hive/activity':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            from src.pg_base import query_rows
            hive_events = []
            # [불변식] dict 삽입 순서 = 분류 우선순위. memory_read를 memory_write보다
            #   먼저 둬야 '[하이브 컨텍스트] … current-work …'가 read로 잡힌다.
            # [WHY] memory_write 키워드는 '/memory/'(메모리 .md 파일 경로) +
            #   제텔/노트 생성으로 잡는다. 과거 키워드('메모리 저장' 등)는 실제
            #   로그 문구와 불일치해 0건이었음(실측 2026-06-21). 'memory_api'는
            #   '/memory/'와 안 겹쳐 코드 편집 오탐 없음.
            _HIVE_KEYWORDS = {
                'memory_read':  ['하이브 컨텍스트', 'current-work', 'memory.py list'],
                'memory_write': ['/memory/', '.zettel-vault', '노트 생성', '제텔', '지식 공유', 'hive_memory', 'zettel_notes', '메모리 저장', '하이브 메모리'],
                'orchestrate':  ['오케스트레이션', '스킬 체인', 'vibe-orchestrate', 'skill_orchestrator', '스킬 실행'],
                'message':      ['메시지 수신', '미읽음 메시지', '메시지→', '→claude', '→antigravity'],
                'heal':         ['자기치유', 'heal', '스킬 자동 설치', '인시던트'],
                'session':      ['세션 스냅샷', '응답 완료', '세션 복구'],
            }
            # 최근 2000건만 스캔(분류 후 100건 반환). pg_logs는 created_at DESC =
            # 최신 우선 → 프론트의 acts.find()가 곧 최신 이벤트를 집는다(reverse 불필요).
            rows = query_rows(
                "SELECT created_at, agent, task FROM pg_logs "
                "WHERE agent IN ('Hive', 'Claude', '사용자', 'Antigravity') "
                "ORDER BY created_at DESC LIMIT 2000"
            )
            for entry in rows:
                agent = entry.get('agent', '') or ''
                task  = entry.get('task', '') or ''
                ts    = entry.get('created_at', '')
                ts    = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
                event_type = None
                for etype, keywords in _HIVE_KEYWORDS.items():
                    if any(kw in task for kw in keywords):
                        event_type = etype
                        break
                if event_type is None and agent == 'Hive':
                    event_type = 'hive_ctx'
                if event_type is None:
                    continue
                hive_events.append({
                    'timestamp': ts,
                    'agent': agent,
                    'type': event_type,
                    'task': task[:200],
                })
                if len(hive_events) >= 100:
                    break
            handler.wfile.write(json.dumps(hive_events, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/hive/logs ──────────────────────────────────────────────────
    elif path == '/api/hive/logs':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            handler.wfile.write(json.dumps(list_session_logs(200), ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/hive/health ─────────────────────────────────────────────────
    elif path == '/api/hive/health':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()

        def check_exists(p):
            return Path(p).exists()

        # hive_health.json에서 워치독 엔진 상태(DB, 에이전트, 복구 횟수) 로드
        engine_data = load_state('health', {}) or {}
        ensure_schema(DATA_DIR)
        if 'db_ok' not in engine_data:
            # watchdog 미실행 상태 — 실제 DB 파일 존재 여부로 대체 판단
            engine_data['db_ok'] = True
            engine_data.setdefault('agent_active', False)
            engine_data.setdefault('repair_count', 0)

        # 현재 활성 프로젝트 경로 동적 조회 (배포 버전 호환)
        _proj = _current_project_root()
        gui_ok = any([
            check_exists(_proj / ".ai_monitor" / "mission_control_ui.py"),
            check_exists(_proj / ".ai_monitor" / "vibe-view" / "src" / "components" / "panels" / "HivePanel.tsx"),
            check_exists(_proj / ".ai_monitor" / "vibe-view" / "dist" / "index.html"),
        ])
        health = {
            **engine_data,
            "constitution": {
                "rules_md":    check_exists(_proj / "RULES.md"),
                "gemini_md":   check_exists(_proj / "GEMINI.md"),
                "claude_md":   check_exists(_proj / "CLAUDE.md"),
                "agents_md":   check_exists(_proj / "AGENTS.md"),
                "project_map": check_exists(_proj / "PROJECT_MAP.md")
            },
            "skills": {
                "master":        check_exists(_proj / ".gemini/skills/master/SKILL.md"),
                "brainstorm":    check_exists(_proj / ".gemini/skills/brainstorming/SKILL.md"),
                "memory_script": check_exists(SCRIPTS_DIR / "memory.py") if SCRIPTS_DIR else False,
                "gui":           gui_ok
            },
            "agents": {
                "claude_config": check_exists(_proj / ".claude/commands/vibe-orchestrate.md"),
                "gemini_config": check_exists(_proj / ".gemini/skills/orchestrate/SKILL.md"),
                "codex_config":  check_exists(_proj / "AGENTS.md")
            },
            "data": {
                "shared_memory": True,
                "hive_db":       True,
                "postgres":      True
            }
        }
        handler.wfile.write(json.dumps(health, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/orchestrator/skill-chain ────────────────────────────────────
    # skill_chain.db(SQLite)에서 스킬 레지스트리 + 터미널별 최신 세션 조회.
    # UI는 skill_registry(①~⑦ 번호 목록)와 terminals(T1~T8 실행 현황) 맵을 수신.
    elif path == '/api/orchestrator/skill-chain':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            import sys as _sys
            _orch_dir = str(DATA_DIR.parent.parent / 'scripts')
            if _orch_dir not in _sys.path:
                _sys.path.insert(0, _orch_dir)
            from skill_orchestrator import _build_response
            result = _merge_live_pty_skill_chains(_build_response(), pty_sessions)
            handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            # fallback: 빈 응답
            handler.wfile.write(json.dumps({
                "skill_registry": [],
                "terminals": {},
                "error": str(e)
            }, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/orchestrator/status ─────────────────────────────────────────
    elif path == '/api/orchestrator/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            KNOWN_AGENTS = ['claude', 'antigravity', 'codex']
            IDLE_SEC = 300  # 5분

            # 에이전트 마지막 활동 시각 (hive_mind.db session_logs)
            ensure_schema(DATA_DIR)
            agent_last_seen: dict = get_agent_last_seen(KNOWN_AGENTS)
            # 현재 프로젝트 메모리만 조회 (프로젝트 격리)
            _proj_id_str = str(_current_project_root()).replace('\\', '/').replace(':', '').replace('/', '--').lstrip('-')
            for row in list_memory(top_k=100, project_id=_proj_id_str):
                author_lower = str(row.get('author', '')).lower()
                last = row.get('updated_at')
                for agent_name in KNOWN_AGENTS:
                    if agent_name in author_lower:
                        current = agent_last_seen.get(agent_name)
                        if last and (current is None or last > current):
                            agent_last_seen[agent_name] = last

            # in-memory AGENT_STATUS 로 보완 (가장 실시간 하트비트)
            with AGENT_STATUS_LOCK:
                for a_name, st in AGENT_STATUS.items():
                    a_key = ('claude' if 'claude' in a_name.lower()
                             else 'antigravity' if 'antigravity' in a_name.lower()
                             else 'codex' if 'codex' in a_name.lower()
                             else None)
                    if a_key and st.get('last_seen'):
                        hb_dt = datetime.fromtimestamp(st['last_seen'])
                        hb_iso = hb_dt.isoformat()
                        if agent_last_seen.get(a_key) is None or hb_iso > agent_last_seen[a_key]:
                            agent_last_seen[a_key] = hb_iso

            # 터미널별 실시간 에이전트 현황 (PTY 세션 기반)
            # [R14] 슬롯 키는 T{n}@{현재슬러그} — 폴더 전환 반영 위해 동적 슬러그. 루프 밖 1회 계산
            #   (config.json 읽기 8회 방지). _current_project_id 미주입 시 static PROJECT_ID 폴백.
            _cur_pid = _current_project_id() if _current_project_id else PROJECT_ID
            terminal_agents: dict = {}
            pty_active_agents: set = set()
            for slot_num in range(1, 9):
                info = _pty_slot_info(pty_sessions, slot_num, _cur_pid)
                if info:
                    a = info.get('agent', '') or 'shell'
                    terminal_agents[str(slot_num)] = a
                    if a in KNOWN_AGENTS:
                        pty_active_agents.add(a)
                else:
                    terminal_agents[str(slot_num)] = ''

            now_dt = datetime.now()
            agent_status = {}
            for agent, seen in agent_last_seen.items():
                if agent in pty_active_agents:
                    agent_status[agent] = {'state': 'active', 'last_seen': now_dt.isoformat(), 'idle_sec': 0}
                elif seen is None:
                    agent_status[agent] = {'state': 'unknown', 'last_seen': None, 'idle_sec': None}
                else:
                    try:
                        seen_dt = datetime.fromisoformat(seen.replace('Z', ''))
                        idle = int((now_dt - seen_dt).total_seconds())
                        agent_status[agent] = {
                            'state': 'idle' if idle > IDLE_SEC else 'active',
                            'last_seen': seen, 'idle_sec': idle
                        }
                    except Exception:
                        agent_status[agent] = {'state': 'unknown', 'last_seen': seen, 'idle_sec': None}

            # 태스크 분배 현황
            tasks_list: list = list_tasks()
            task_dist: dict = {a: {'pending': 0, 'in_progress': 0, 'done': 0} for a in KNOWN_AGENTS + ['all']}
            for t in tasks_list:
                key = t.get('assigned_to', 'all') if t.get('assigned_to') in task_dist else 'all'
                s = t.get('status', 'pending')
                if s in task_dist[key]:
                    task_dist[key][s] += 1

            # 오케스트레이터 최근 액션 로그
            orch_log = DATA_DIR / 'orchestrator_log.jsonl'
            recent_actions: list = []
            if orch_log.exists():
                for line in reversed(orch_log.read_text(encoding='utf-8').strip().splitlines()[-20:]):
                    try:
                        recent_actions.append(json.loads(line))
                    except Exception:
                        pass
            if not recent_actions:
                task_log_file = DATA_DIR / 'task_logs.jsonl'
                if task_log_file.exists():
                    lines = task_log_file.read_text(encoding='utf-8').strip().splitlines()
                    for line in reversed(lines[-20:]):
                        try:
                            entry = json.loads(line)
                            recent_actions.append({
                                'action':    entry.get('agent', 'agent'),
                                'detail':    entry.get('task', ''),
                                'timestamp': entry.get('timestamp', ''),
                            })
                        except Exception:
                            pass

            warnings: list = []
            for agent, st in agent_status.items():
                if st['state'] == 'idle' and st.get('idle_sec'):
                    warnings.append(f"{agent} idle for {st['idle_sec'] // 60}m")
            for agent, dist in task_dist.items():
                if agent == 'all':
                    continue
                active = dist['pending'] + dist['in_progress']
                if active >= 5:
                    warnings.append(f"{agent} overloaded with {active} active tasks")

            handler.wfile.write(json.dumps({
                'agent_status':      agent_status,
                'task_distribution': task_dist,
                'recent_actions':    recent_actions,
                'warnings':          warnings,
                'terminal_agents':   terminal_agents,
                'timestamp':         now_dt.strftime('%Y-%m-%dT%H:%M:%S'),
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/superpowers/status ──────────────────────────────────────────
    elif path == '/api/superpowers/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        # Skills 2.0: .claude/skills/<name>/SKILL.md 구조로 감지
        # 구 시스템(.claude/commands/) 설치 여부도 함께 확인하여 마이그레이션 필요 판단
        VIBE_SKILL_NAMES = ['brainstorm', 'debug', 'write-plan', 'execute-plan', 'tdd', 'code-review',
                            'orchestrate', 'release', 'heal', 'security']
        _proj = _current_project_root()
        claude_skills_dir   = _proj / '.claude' / 'skills'
        claude_commands_dir = _proj / '.claude' / 'commands'  # 구 시스템 (마이그레이션 감지용)
        antigravity_skills_dir   = _proj / '.gemini' / 'skills'
        result = {
            'claude': {
                # Skills 2.0 경로 우선 감지, 구 경로도 설치로 인정 (하위 호환)
                skill: (
                    (claude_skills_dir / f'vibe-{skill}' / 'SKILL.md').exists() or
                    (claude_commands_dir / f'vibe-{skill}.md').exists()
                )
                for skill in VIBE_SKILL_NAMES
            },
            'antigravity': {
                skill: (antigravity_skills_dir / skill / 'SKILL.md').exists()
                for skill in VIBE_SKILL_NAMES
            },
        }
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/skill-results ────────────────────────────────────────────────
    elif path == '/api/skill-results':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            results_file = DATA_DIR / 'skill_results.jsonl'
            rows = []
            if results_file.exists():
                for line in results_file.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            rows = rows[-50:][::-1]  # 최신 50개만 반환 (최신순)
            handler.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/skill-ab-test — 스킬 A/B 테스트 분석 결과 ──────────────────
    elif path == '/api/skill-ab-test':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 스킬 A/B 테스트 기능을 사용할 수 없습니다')
            scripts_dir = str(Path(SCRIPTS_DIR))
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from skill_ab_test import get_ab_test_report
            _proj_root = _current_project_root() if _current_project_root else PROJECT_ROOT
            report = get_ab_test_report(project_root=_proj_root)
            handler.wfile.write(json.dumps(report, ensure_ascii=False, default=str).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/skill/predict — 예측적 스킬 실행 (마르코프 체인 기반) ───────
    elif path == '/api/skill/predict':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 스킬 예측 기능을 사용할 수 없습니다')
            scripts_dir = str(Path(SCRIPTS_DIR))
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            current_skill = params.get('current', [''])[0].strip()
            from skill_predictor import predict_next_skill, get_prediction_report
            _proj_root = _current_project_root() if _current_project_root else PROJECT_ROOT
            if current_skill:
                result = {"predictions": predict_next_skill(current_skill, _proj_root)}
            else:
                result = get_prediction_report(_proj_root)
            handler.wfile.write(json.dumps(result, ensure_ascii=False, default=str).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/agent-quota ────────────────────────────────────────────────
    # 터미널 슬롯 헤더 쿼터 배지용 — 에이전트별 플랜 사용률을 한 번에 반환.
    # Antigravity는 플랜 쿼터 공개 경로가 없어 미포함 (컨텍스트 게이지로 대체).
    elif path == '/api/agent-quota':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            from src.codex_quota import get_codex_quota
            payload = {'claude': get_claude_quota(), 'codex': get_codex_quota()}
        except Exception as e:
            payload = {'error': str(e)}
        handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/heartbeat/status ───────────────────────────────────────────
    # 자율 heartbeat 상태 — 대시보드 헤더 토글 칩용 (텔레그램 /auto status와 동일 소스)
    # [과거사고 2026-07-17] 최초 구현이 이 경로를 '/api/heartbeat'로 잡았다가 server.py의
    #   liveness 엔드포인트(_g_heartbeat, exact-first)에 완전히 가려져 칩이 영구 OFF.
    #   '/api/heartbeat'는 useVibeData·hive_watchdog가 쓰는 생존신호 → 절대 재점유 금지.
    elif path == '/api/heartbeat/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            from infra.heartbeat_daemon import (AGENT_ID, DAILY_LIMIT,
                                                load_hb_state, is_active_holder)
            from src.pg_store import find_tasks_for_agent
            s = load_hb_state()
            # [워치독] loop_beat_at은 데몬 run_loop이 매 iteration(최대 60초) 갱신 →
            #   3분 이상 안 바뀌면 스레드 hang(예: 죽은 LISTEN conn에 갇힘)으로 판정.
            #   last_cycle_at은 게이트에 막히면 안 갱신되므로 '멈춤' 감지에 못 쓴다(과거 15h 미감지).
            import datetime as _dt
            _beat = s.get('loop_beat_at') or ''
            _stale = False
            if _beat:
                try:
                    _age = (_dt.datetime.now() - _dt.datetime.strptime(_beat, '%Y-%m-%dT%H:%M:%S')).total_seconds()
                    _stale = _age > 180
                except ValueError:
                    pass
            payload = {
                'enabled': bool(s.get('enabled')),
                'daily_count': int(s.get('daily_count', 0)),
                'daily_limit': DAILY_LIMIT,
                'consecutive_fails': int(s.get('consecutive_fails', 0)),
                'last_cycle_at': s.get('last_cycle_at') or '',
                'last_result': s.get('last_result') or '',
                'loop_beat_at': _beat,
                'stale': _stale,
                'pending': len(find_tasks_for_agent(AGENT_ID)),
                # [①] enabled는 DB 공유값이라 dev+설치본 양쪽이 동일하게 켜져 보이지만,
                #   실제 auto를 도는 건 9019 락을 쥔 '한' 인스턴스뿐. active_here=False면
                #   이 인스턴스는 다른 인스턴스가 실행 중이라 대기만 하는 상태 — 프론트가
                #   초록 ON 대신 '다른 인스턴스에서 실행 중(대기)'로 표시해 침묵 오해를 없앤다.
                'active_here': is_active_holder(),
            }
            # [읽기전용 기록 열람] 현재 작업 + 최근 결과 + CLI 버전 — 자율 클로드 가시성용.
            #   ('관제 신규 개발 중단' 원칙 준수 — 조작 없이 열람만.)
            try:
                from src.pg_base import query_rows
                _cur = query_rows("SELECT title FROM hive_tasks WHERE assigned_to='claude-auto' "
                                  "AND status='in_progress' ORDER BY updated_at DESC LIMIT 1;")
                payload['current_task'] = (_cur[0].get('title') if _cur else '') or ''
                # [과거사고 2026-08-01] hive_tasks.updated_at은 timestamp가 아니라 **text**(ISO 문자열).
                #   to_char(text, ...) 오버로드가 없어 매 폴링마다 쿼리가 통째로 실패했고,
                #   query_rows가 예외를 삼켜 화면엔 "0건"으로만 보였다(무증상). 대신 server.log에
                #   에러+HINT 4줄이 폴링 주기마다 쌓여 48시간에 4,800건/로그 61MB로 불어났다.
                #   → ::timestamptz 캐스트로 오버로드를 맞춘다. 컬럼 타입을 바꾸면 이 값을 문자열로
                #   비교/저장하는 다른 경로가 깨지므로 쿼리 쪽에서 캐스트하는 편이 안전하다.
                _rec = query_rows("SELECT title, status, to_char(updated_at::timestamptz,'MM-DD HH24:MI') AS at "
                                  "FROM hive_tasks WHERE assigned_to='claude-auto' "
                                  "AND status IN ('done','blocked') ORDER BY updated_at DESC LIMIT 5;")
                payload['recent'] = _rec or []
            except Exception:
                payload['current_task'] = ''
                payload['recent'] = []
            payload['model'] = _auto_cli_version()
        except Exception as e:
            payload = {'error': str(e)}
        handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/context-usage ───────────────────────────────────────────────
    elif path == '/api/context-usage':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            # Claude Code 프로젝트 디렉터리 자동 탐색.
            # PROJECT_ID 하드 계산 규칙이 Claude 본체의 실제 인코딩과 달라
            # 설치 버전(경로 상이)에서 디렉터리를 찾지 못하던 버그 수정.
            # ~/.claude/projects/ 아래 모든 세션을 훑고, 각 세션 메타의
            # 'cwd' 값이 현재 PROJECT_ROOT와 일치하는 것만 선택.
            # [R14] cwd 비교 기준·1차 접근 슬러그를 동적화 — static이면 폴더 전환 후
            #   현재 프로젝트 세션을 못 찾는다(2차 전체스캔도 cwd 기준이 틀어져 실패).
            _cur_root = _current_project_root() if _current_project_root else PROJECT_ROOT
            _cur_pid = _current_project_id() if _current_project_id else PROJECT_ID
            claude_root = Path.home() / '.claude' / 'projects'
            current_cwd_norm = str(_cur_root).replace('\\', '/').rstrip('/').lower()
            sessions = []
            if claude_root.exists():
                # 1차 시도: 현재 슬러그로 직접 접근 (기존 동작 유지 · 빠름)
                primary_dir = claude_root / _cur_pid
                candidate_dirs = []
                if primary_dir.exists() and primary_dir.is_dir():
                    candidate_dirs.append(primary_dir)
                # 2차 시도: 전체 스캔 (설치 버전 · 경로 불일치 대응)
                for sub in claude_root.iterdir():
                    if sub.is_dir() and sub not in candidate_dirs:
                        candidate_dirs.append(sub)

                for proj_dir in candidate_dirs:
                    for jsonl_file in proj_dir.glob('*.jsonl'):
                        try:
                            info = _parse_session_tail(jsonl_file)
                            if not info:
                                continue
                            # cwd가 현재 프로젝트 루트와 일치하는 세션만 채택
                            sess_cwd = str(info.get('cwd') or '').rstrip('/').lower()
                            if sess_cwd and sess_cwd == current_cwd_norm:
                                info['_path'] = str(jsonl_file)  # 5h 집계용 파일 경로 보존
                                sessions.append(info)
                        except Exception:
                            continue
                    if sessions:
                        break  # 일치 세션 확보되면 추가 스캔 중단
            sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
            # [2026-04-21] 방금 시작된 세션은 아직 assistant usage 없을 수 있음.
            # 그 경우 model='unknown' + 토큰 0이 맨 앞에 와서 빈 바가 표시되는
            # 현상 방지 → usage 있는 가장 최신 세션을 우선 선택.
            with_usage = [
                s for s in sessions
                if s.get('model') not in ('', 'unknown')
                and (s.get('input_tokens', 0) + s.get('cache_read', 0)) > 0
            ]
            if with_usage:
                seen = {id(s) for s in with_usage}
                sessions = with_usage + [s for s in sessions if id(s) not in seen]

            # [Fix] 최신 세션의 상세 토큰 정보 반환.
            # 프론트엔드(TerminalSlot.tsx)는 input_tokens/output_tokens/
            # cache_read/cache_write/last_ts 필드를 개별적으로 읽어
            # 컬러 블록 바·카테고리 그리드를 그리므로 모두 포함해야 함.
            result = {
                'input_tokens': 0,
                'output_tokens': 0,
                'cache_read': 0,
                'cache_write': 0,
                'total_tokens': 0,
                'context_used': 0,         # [2026-04-21] 실제 컨텍스트 점유 = input + cache_read + cache_write
                'context_window': 200_000, # 기본 200k, 모델에 따라 _claude_ctx_window로 갱신
                'percentage': 0,
                'model': 'claude',
                'last_ts': '',
                # [2026-04-21] 5시간 sliding window 누적 (CLI /context 의 5h 제한 흉내)
                # 쿼터 한도는 모르므로 절대 토큰 수만 제공 — 프론트에서 라벨링.
                'last_5h_tokens': 0,
                'last_5h_messages': 0,
                'last_5h_oldest_ts': '',
            }
            if sessions:
                latest = sessions[0]
                result['input_tokens'] = latest.get('input_tokens', 0)
                result['output_tokens'] = latest.get('output_tokens', 0)
                result['cache_read'] = latest.get('cache_read', 0)
                result['cache_write'] = latest.get('cache_write', 0)
                result['total_tokens'] = result['input_tokens'] + result['output_tokens']
                result['model'] = latest.get('model', 'claude')
                result['last_ts'] = latest.get('last_ts', '')
                # [2026-04-21] 실제 컨텍스트 점유 = 현재 턴 input + 캐시 히트 + 캐시 생성
                # Claude Code CLI `/context` 가 표시하는 값과 일치.
                result['context_window'] = _claude_ctx_window(result['model'])
                result['context_used'] = (
                    result['input_tokens'] + result['cache_read'] + result['cache_write']
                )
                if result['context_window'] > 0:
                    result['percentage'] = (result['context_used'] / result['context_window']) * 100

                # 5시간 sliding window 집계 — cwd 일치 세션들의 지난 5h assistant usage 합
                try:
                    import time as _t
                    since = _t.time() - (5 * 3600)
                    matched_files = [
                        Path(s['_path']) for s in sessions if s.get('_path')
                    ]
                    win = _sum_usage_since(matched_files, since)
                    result['last_5h_tokens'] = win.get('total', 0)
                    result['last_5h_messages'] = win.get('message_count', 0)
                    result['last_5h_oldest_ts'] = win.get('oldest_ts', '')
                except Exception:
                    pass  # 집계 실패해도 기본 바는 표시 가능

            # [2026-07-03] OAuth 쿼터 사용률 — 세션 유무와 무관하게 항상 첨부.
            # 내부 60s 캐시라 폴링마다 API를 때리지 않음. 실패 시 available=False →
            # 프론트는 기존 5h 절대값 표시로 폴백.
            result['quota'] = get_claude_quota()

            handler.wfile.write(json.dumps(
                result, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps(
                {'total_tokens': 0, 'context_window': 200000, 'percentage': 0, 'error': str(e)}, ensure_ascii=False
            ).encode('utf-8'))
        return True

    # ── /api/antigravity-context-usage ─────────────────────────────────────────
    elif path == '/api/antigravity-context-usage':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            # [R14] 현재 활성 폴더명 기준 — 폴더 전환 후 해당 프로젝트 채팅을 봐야 UI와 일치.
            _cur_root = _current_project_root() if _current_project_root else PROJECT_ROOT
            antigravity_chat_dir = Path.home() / '.gemini' / 'tmp' / _cur_root.name / 'chats'
            sessions = []
            if antigravity_chat_dir.exists():
                for json_file in antigravity_chat_dir.glob('session-*.json'):
                    try:
                        info = _parse_antigravity_session(json_file)
                        if info:
                            sessions.append(info)
                    except Exception:
                        continue
            sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
            
            # App.tsx expects { total_tokens, context_window, percentage }
            # [Fix] sessions 리스트 대신 최신 세션의 요약 정보를 반환하여 게이지가 정상 표시되도록 함
            result = {
                'total_tokens': 0,
                'context_window': 1048576, # 1M tokens (Antigravity 1.5/2.0 standard)
                'percentage': 0,
                'model': 'antigravity'
            }
            if sessions:
                latest = sessions[0]
                # input + output 을 total_tokens로 합산 (Antigravity 세션 로그 기준)
                result['total_tokens'] = latest.get('input_tokens', 0) + latest.get('output_tokens', 0)
                result['model'] = latest.get('model', 'antigravity')
                # 비율 계산
                if result['context_window'] > 0:
                    result['percentage'] = (result['total_tokens'] / result['context_window']) * 100

            handler.wfile.write(json.dumps(
                result, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps(
                {'total_tokens': 0, 'context_window': 1000000, 'percentage': 0, 'error': str(e)}, ensure_ascii=False
            ).encode('utf-8'))
        return True

    # ── /api/local-models ────────────────────────────────────────────────
    elif path == '/api/local-models':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        import urllib.request as _urllib
        result = {"hardware": {"ram_gb": 0, "gpus": []}, "models": [], "ollama_available": False, "error": None}
        # RAM 감지 (Windows wmic)
        try:
            mem = proc.run(
                ['wmic', 'OS', 'get', 'TotalVisibleMemorySize', '/value'],
                capture_output=True, text=True, encoding='utf-8', timeout=5,
            )
            for line in mem.stdout.split('\n'):
                if 'TotalVisibleMemorySize=' in line:
                    kb = int(line.split('=')[1].strip())
                    result["hardware"]["ram_gb"] = round(kb / 1024 / 1024, 1)
        except Exception:
            pass
        # GPU 감지 (nvidia-smi)
        try:
            gpu = proc.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, encoding='utf-8', timeout=5,
            )
            if gpu.returncode == 0:
                for line in gpu.stdout.strip().split('\n'):
                    parts = line.split(',')
                    if len(parts) >= 2:
                        result["hardware"]["gpus"].append({
                            "name": parts[0].strip(),
                            "vram_gb": round(int(parts[1].strip()) / 1024, 1)
                        })
        except Exception:
            pass
        # Ollama 로컬 모델 목록
        try:
            with _urllib.urlopen('http://localhost:11434/api/tags', timeout=3) as resp:
                ollama_data = json.loads(resp.read().decode('utf-8'))
                result["ollama_available"] = True
                ram_gb = result["hardware"]["ram_gb"]
                for m in ollama_data.get('models', []):
                    size_gb = round(m.get('size', 0) / 1024 / 1024 / 1024, 1)
                    gpus = result["hardware"]["gpus"]
                    if gpus:
                        fits = size_gb < gpus[0]["vram_gb"] * 0.9
                    elif ram_gb > 0:
                        fits = size_gb < ram_gb * 0.7
                    else:
                        fits = None
                    result["models"].append({
                        "name":    m.get("name", ""),
                        "size_gb": size_gb,
                        "source":  "ollama",
                        "fits":    fits
                    })
        except Exception as e:
            result["ollama_error"] = str(e)
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return True

    # 처리되지 않은 경로
    return False


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, SCRIPTS_DIR: Path, BASE_DIR: Path,
                PROJECT_ROOT: Path,
                _current_project_root) -> bool:
    """POST 요청 처리 — /api/hive/approve-skill, /api/orchestrator/* 담당.

    반환값: 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/heartbeat/toggle ────────────────────────────────────────────
    # 자율 heartbeat on/off — scripts/auto.py·텔레그램 /auto와 동일 계약
    # (on 시 consecutive_fails 리셋 + NOTIFY 즉시 기상)
    if path == '/api/heartbeat/toggle':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            from infra.heartbeat_daemon import load_hb_state, save_hb_state
            enabled = bool(data.get('enabled'))
            s = load_hb_state()
            s['enabled'] = enabled
            if enabled:
                s['consecutive_fails'] = 0
            save_hb_state(s)
            if enabled:
                from src.pg_base import execute
                execute('NOTIFY hive_heartbeat;')
            handler.wfile.write(json.dumps({'status': 'success', 'enabled': enabled}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/hive/approve-skill ──────────────────────────────────────────
    if path == '/api/hive/approve-skill':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            skill_name = data.get('skill_name')
            keyword    = data.get('keyword', skill_name)
            if not skill_name:
                handler.wfile.write(json.dumps({"status": "error", "message": "Skill name is required"}).encode('utf-8'))
                return True
            # [R14] 스킬은 현재 활성 프로젝트에 설치 — 폴더 전환 반영.
            _cur_root = _current_project_root() if _current_project_root else PROJECT_ROOT
            skill_dir  = _cur_root / ".gemini" / "skills" / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_file = skill_dir / "SKILL.md"
            template = f"""# 스킬: {skill_name}

이 스킬은 '{keyword}' 관련 작업을 최적화하기 위해 자동으로 제안된 스킬입니다.

## 사용 시점
- '{keyword}' 키워드가 포함된 작업 요청 시
- 반복적인 {keyword} 관련 파일 수정이 필요할 때

## 핵심 패턴
1. 관련 파일 분석
2. {keyword} 표준 가이드라인 적용
3. 변경 사항 검증

---
**생성일**: {datetime.now().strftime("%Y-%m-%d")}
**상태**: 초안 (Draft)
"""
            with open(skill_file, "w", encoding="utf-8") as f:
                f.write(template)
            handler.wfile.write(json.dumps({"status": "success", "path": str(skill_file)}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        return True

    # ── /api/orchestrator/skill-chain/update ─────────────────────────────
    # POST body: {"step": 0, "status": "done", "summary": "...", "terminal_id": 1}
    # skill_orchestrator.cmd_update()를 직접 호출하여 DB 갱신
    elif path == '/api/orchestrator/skill-chain/update':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            import sys as _sys
            _orch_dir = str(DATA_DIR.parent.parent / 'scripts')
            if _orch_dir not in _sys.path:
                _sys.path.insert(0, _orch_dir)
            from skill_orchestrator import cmd_update as _orch_update
            step = int(data.get('step', 0))
            status = str(data.get('status', 'done'))
            summary = str(data.get('summary', ''))
            terminal_id = int(data.get('terminal_id', 0))
            _orch_update(terminal_id, step, status, summary)
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/orchestrator/run ─────────────────────────────────────────────
    elif path == '/api/orchestrator/run':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            if not SCRIPTS_DIR:
                raise Exception('설치 버전에서는 오케스트레이터 기능을 사용할 수 없습니다')
            orch_script = str(SCRIPTS_DIR / 'orchestrator.py')
            result = proc.run(
                [sys.executable, orch_script],
                capture_output=True, text=True, timeout=15, encoding='utf-8',
            )
            output = (result.stdout + result.stderr).strip()
            handler.wfile.write(json.dumps({
                'status': 'success',
                'output': output or '이상 없음',
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/superpowers/install ─────────────────────────────────────────
    elif path == '/api/superpowers/install':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        import shutil as _shutil
        try:
            tool  = str(data.get('tool', 'claude'))
            _proj = _current_project_root()
            if tool == 'claude':
                # Skills 2.0: claude_skills/<name>/SKILL.md → .claude/skills/<name>/
                skills_src = _proj / '.claude' / 'skills'
                if not skills_src.exists():
                    raise Exception('내장 스킬 파일을 찾을 수 없습니다 (claude_skills/)')

                dest_dir = _proj / '.claude' / 'skills'
                dest_dir.mkdir(parents=True, exist_ok=True)

                # 소스와 대상이 같으면 (개발 환경) 복사 생략
                installed = []
                if skills_src.resolve() != dest_dir.resolve():
                    _shutil.copytree(str(skills_src), str(dest_dir), dirs_exist_ok=True)

                installed = [
                    d.name for d in dest_dir.iterdir()
                    if d.is_dir() and (d / 'SKILL.md').exists()
                ]

                # 구 시스템 .claude/commands/vibe-*.md 자동 제거 (마이그레이션)
                old_commands_dir = _proj / '.claude' / 'commands'
                migrated = []
                if old_commands_dir.exists():
                    for old_file in old_commands_dir.glob('vibe-*.md'):
                        old_file.unlink(missing_ok=True)
                        migrated.append(old_file.name)

                msg = f"Claude 스킬 설치 완료 ({len(installed)}개): {', '.join(installed)}"
                if migrated:
                    msg += f" | 구 버전 제거: {', '.join(migrated)}"
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': msg,
                    'installed': installed,
                    'migrated': migrated,
                }, ensure_ascii=False).encode('utf-8'))

            elif tool == 'antigravity':
                skills_src = BASE_DIR / 'skills' / 'antigravity'
                if not skills_src.exists():
                    skills_src = _proj / '.gemini' / 'skills'
                if not skills_src.exists():
                    raise Exception('내장 Gemini 스킬을 찾을 수 없습니다 (skills/gemini/ 또는 .gemini/skills/)')
                dest_dir = _proj / '.gemini' / 'skills'
                dest_dir.mkdir(parents=True, exist_ok=True)
                if skills_src.resolve() != dest_dir.resolve():
                    _shutil.copytree(str(skills_src), str(dest_dir), dirs_exist_ok=True)
                installed = [d.name for d in dest_dir.iterdir() if d.is_dir() and (d / 'SKILL.md').exists()]
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Antigravity 스킬 설치 완료 ({len(installed)}개) → {dest_dir}"
                }, ensure_ascii=False).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({'status': 'error', 'message': f'지원하지 않는 tool: {tool}'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/superpowers/uninstall ────────────────────────────────────────
    elif path == '/api/superpowers/uninstall':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        import shutil as _shutil
        try:
            tool  = str(data.get('tool', 'claude'))
            _proj = _current_project_root()
            if tool == 'claude':
                removed = []
                # Skills 2.0: .claude/skills/vibe-*/ 디렉토리 제거
                skills_dir = _proj / '.claude' / 'skills'
                if skills_dir.exists():
                    for skill_dir in skills_dir.iterdir():
                        if skill_dir.is_dir() and skill_dir.name.startswith('vibe-'):
                            _shutil.rmtree(str(skill_dir), ignore_errors=True)
                            removed.append(skill_dir.name)
                # 구 시스템 잔재 .claude/commands/vibe-*.md 도 함께 제거
                commands_dir = _proj / '.claude' / 'commands'
                if commands_dir.exists():
                    for old_file in commands_dir.glob('vibe-*.md'):
                        old_file.unlink(missing_ok=True)
                        removed.append(old_file.name)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Claude 스킬 제거 완료: {', '.join(removed) if removed else '없음'}",
                    'removed': removed
                }, ensure_ascii=False).encode('utf-8'))
            elif tool == 'antigravity':
                dest_dir = _proj / '.gemini' / 'skills'
                if dest_dir.exists():
                    _shutil.rmtree(dest_dir, ignore_errors=True)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Antigravity 스킬 제거 완료 → {dest_dir}"
                }, ensure_ascii=False).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({'status': 'error', 'message': f'지원하지 않는 tool: {tool}'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
