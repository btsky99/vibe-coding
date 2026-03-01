"""
FILE: api/hive_api.py
DESCRIPTION: /api/hive/*, /api/orchestrator/*, /api/install-skills,
             /api/superpowers/* 엔드포인트 핸들러 모듈.
             server.py에서 하이브 마인드 관련 API 로직을 분리하여 가독성과
             유지보수성을 향상시킵니다.
             각 함수는 SSEHandler 인스턴스(handler)를 첫 번째 인자로 받아
             HTTP 응답을 직접 기록합니다.

REVISION HISTORY:
- 2026-03-01 Claude: server.py에서 분리 — hive/orchestrator/superpowers API 담당
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _json_response(handler, data: dict | list, status: int = 200) -> None:
    """JSON 응답을 전송하는 공통 헬퍼 함수.

    매 핸들러에서 반복되는 응답 헤더 작성 코드를 단순화합니다.
    ensure_ascii=False로 한글 깨짐 방지.
    """
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, SCRIPTS_DIR: Path, BASE_DIR: Path,
               PROJECT_ROOT: Path, PROJECT_ID: str,
               TASKS_FILE: Path, AGENT_STATUS: dict, AGENT_STATUS_LOCK,
               pty_sessions: dict,
               _current_project_root, _parse_session_tail, _parse_gemini_session) -> bool:
    """GET 요청 처리 — /api/hive/*, /api/orchestrator/*, /api/superpowers/status,
    /api/install-skills, /api/skill-results, /api/context-usage,
    /api/gemini-context-usage, /api/local-models 를 담당합니다.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    caller(server.py의 do_GET)는 False를 받으면 다른 핸들러를 시도합니다.
    """

    # ── /api/install-skills ────────────────────────────────────────────────
    if path == '/api/install-skills':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        import shutil
        target_path = params.get('path', [''])[0]
        result = {"status": "error", "message": "Invalid path"}
        if target_path and os.path.exists(target_path) and os.path.isdir(target_path):
            try:
                # 배포(frozen) 여부에 따라 소스 경로 결정
                source_base = BASE_DIR if getattr(sys, 'frozen', False) else BASE_DIR.parent
                gemini_src = source_base / ".gemini"
                if gemini_src.exists():
                    shutil.copytree(gemini_src, Path(target_path) / ".gemini", dirs_exist_ok=True)
                scripts_src = SCRIPTS_DIR
                if scripts_src.exists():
                    shutil.copytree(scripts_src, Path(target_path) / "scripts", dirs_exist_ok=True)
                for md in ("GEMINI.md", "CLAUDE.md", "RULES.md", "PROJECT_MAP.md"):
                    src = source_base / md
                    if src.exists():
                        shutil.copy(src, Path(target_path) / md)
                # 대상 프로젝트 DB 초기화 — 하이브 워치독 정상 동작 전제 조건
                target_data = Path(target_path) / ".ai_monitor" / "data"
                target_data.mkdir(parents=True, exist_ok=True)
                for db_name in ("shared_memory.db", "hive_mind.db"):
                    db_path = target_data / db_name
                    if not db_path.exists():
                        conn = sqlite3.connect(str(db_path))
                        if db_name == "shared_memory.db":
                            conn.execute("""CREATE TABLE IF NOT EXISTS memory (
                                key TEXT PRIMARY KEY, title TEXT, content TEXT,
                                tags TEXT, author TEXT, project TEXT,
                                created_at TEXT, updated_at TEXT)""")
                        conn.commit()
                        conn.close()
                result = {"status": "success", "message": f"Skills installed to {target_path}"}
            except Exception as e:
                result = {"status": "error", "message": str(e)}
        handler.wfile.write(json.dumps(result).encode('utf-8'))
        return True

    # ── /api/hive/skill-analysis ──────────────────────────────────────────
    elif path == '/api/hive/skill-analysis':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        analysis_file = DATA_DIR / "skill_analysis.json"
        analysis_data = {"proposals": []}
        if analysis_file.exists():
            try:
                with open(analysis_file, 'r', encoding='utf-8') as f:
                    analysis_data = json.load(f)
            except Exception:
                pass
        handler.wfile.write(json.dumps(analysis_data, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/hive/health/repair ──────────────────────────────────────────
    elif path == '/api/hive/health/repair':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            watchdog_script = SCRIPTS_DIR / "hive_watchdog.py"
            # CREATE_NO_WINDOW: Python 서브프로세스 콘솔 창 방지
            _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            result_proc = subprocess.run(
                [sys.executable, str(watchdog_script), "--check"],
                capture_output=True, text=True, encoding='utf-8',
                creationflags=_no_window
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

    # ── /api/hive/logs ──────────────────────────────────────────────────
    elif path == '/api/hive/logs':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            conn_h = sqlite3.connect(str(DATA_DIR / 'hive_mind.db'), timeout=5, check_same_thread=False)
            conn_h.row_factory = sqlite3.Row
            logs = conn_h.execute(
                "SELECT * FROM session_logs ORDER BY ts_start DESC LIMIT 200"
            ).fetchall()
            conn_h.close()
            handler.wfile.write(json.dumps([dict(r) for r in logs], ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    # ── /api/hive/health ─────────────────────────────────────────────────
    elif path == '/api/hive/health':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()

        def check_exists(p):
            return Path(p).exists()

        # hive_health.json에서 워치독 엔진 상태(DB, 에이전트, 복구 횟수) 로드
        engine_data = {}
        health_file = DATA_DIR / "hive_health.json"
        if health_file.exists():
            try:
                with open(health_file, 'r', encoding='utf-8') as f:
                    engine_data = json.load(f)
            except Exception:
                pass
        if 'db_ok' not in engine_data:
            # watchdog 미실행 상태 — 실제 DB 파일 존재 여부로 대체 판단
            engine_data['db_ok'] = (
                (DATA_DIR / 'shared_memory.db').exists() and
                (DATA_DIR / 'hive_mind.db').exists()
            )
            engine_data.setdefault('agent_active', False)
            engine_data.setdefault('repair_count', 0)

        # 현재 활성 프로젝트 경로 동적 조회 (배포 버전 호환)
        _proj = _current_project_root()
        health = {
            **engine_data,
            "constitution": {
                "rules_md":    check_exists(_proj / "RULES.md"),
                "gemini_md":   check_exists(_proj / "GEMINI.md"),
                "claude_md":   check_exists(_proj / "CLAUDE.md"),
                "project_map": check_exists(_proj / "PROJECT_MAP.md")
            },
            "skills": {
                "master":        check_exists(_proj / ".gemini/skills/master/SKILL.md"),
                "brainstorm":    check_exists(_proj / ".gemini/skills/brainstorming/SKILL.md"),
                "memory_script": check_exists(SCRIPTS_DIR / "memory.py")
            },
            "agents": {
                "claude_config": check_exists(_proj / ".claude/commands/vibe-master.md"),
                "gemini_config": check_exists(_proj / ".gemini/settings.json")
            },
            "data": {
                "shared_memory": check_exists(DATA_DIR / "shared_memory.db"),
                "hive_db":       check_exists(DATA_DIR / "hive_mind.db")
            }
        }
        handler.wfile.write(json.dumps(health, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/orchestrator/skill-chain ────────────────────────────────────
    elif path == '/api/orchestrator/skill-chain':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        chain_file = DATA_DIR / 'skill_chain.json'
        if chain_file.exists():
            try:
                with open(chain_file, 'r', encoding='utf-8') as f:
                    handler.wfile.write(f.read().encode('utf-8'))
            except Exception:
                handler.wfile.write(json.dumps({"status": "idle"}).encode('utf-8'))
        else:
            handler.wfile.write(json.dumps({"status": "idle"}).encode('utf-8'))
        return True

    # ── /api/orchestrator/status ─────────────────────────────────────────
    elif path == '/api/orchestrator/status':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            KNOWN_AGENTS = ['claude', 'gemini']
            IDLE_SEC = 300  # 5분

            # 에이전트 마지막 활동 시각 (hive_mind.db session_logs)
            agent_last_seen: dict = {a: None for a in KNOWN_AGENTS}
            try:
                conn_h = sqlite3.connect(str(DATA_DIR / 'hive_mind.db'), timeout=5, check_same_thread=False)
                conn_h.row_factory = sqlite3.Row
                for row in conn_h.execute(
                    "SELECT agent, MAX(ts_start) as last_seen FROM session_logs "
                    "WHERE LOWER(agent) LIKE '%claude%' OR LOWER(agent) LIKE '%gemini%' "
                    "GROUP BY LOWER(agent) ORDER BY last_seen DESC"
                ).fetchall():
                    agent_lower = row['agent'].lower()
                    if 'claude' in agent_lower and agent_last_seen.get('claude') is None:
                        agent_last_seen['claude'] = row['last_seen']
                    elif 'gemini' in agent_lower and agent_last_seen.get('gemini') is None:
                        agent_last_seen['gemini'] = row['last_seen']
                conn_h.close()
            except Exception:
                pass

            # shared_memory.db author 필드로 보완
            try:
                conn_sm = sqlite3.connect(str(DATA_DIR / 'shared_memory.db'), timeout=5, check_same_thread=False)
                conn_sm.row_factory = sqlite3.Row
                for row in conn_sm.execute(
                    "SELECT author, MAX(updated_at) as last_seen FROM memory "
                    "WHERE LOWER(author) LIKE '%claude%' OR LOWER(author) LIKE '%gemini%' "
                    "GROUP BY LOWER(author) ORDER BY last_seen DESC"
                ).fetchall():
                    author_lower = row['author'].lower()
                    last = row['last_seen']
                    if 'claude' in author_lower:
                        if agent_last_seen.get('claude') is None or (last and last > (agent_last_seen['claude'] or '')):
                            agent_last_seen['claude'] = last
                    elif 'gemini' in author_lower:
                        if agent_last_seen.get('gemini') is None or (last and last > (agent_last_seen['gemini'] or '')):
                            agent_last_seen['gemini'] = last
                conn_sm.close()
            except Exception:
                pass

            # in-memory AGENT_STATUS 로 보완 (가장 실시간 하트비트)
            with AGENT_STATUS_LOCK:
                for a_name, st in AGENT_STATUS.items():
                    a_key = ('claude' if 'claude' in a_name.lower()
                             else 'gemini' if 'gemini' in a_name.lower()
                             else None)
                    if a_key and st.get('last_seen'):
                        hb_dt = datetime.fromtimestamp(st['last_seen'])
                        hb_iso = hb_dt.isoformat()
                        if agent_last_seen.get(a_key) is None or hb_iso > agent_last_seen[a_key]:
                            agent_last_seen[a_key] = hb_iso

            # 터미널별 실시간 에이전트 현황 (PTY 세션 기반)
            terminal_agents: dict = {}
            pty_active_agents: set = set()
            for slot_num in range(1, 9):
                info = pty_sessions.get(str(slot_num))
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
            tasks_list: list = []
            if TASKS_FILE.exists():
                with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                    tasks_list = json.load(f)
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
                    warnings.append(f"{agent} {st['idle_sec'] // 60}분째 비활성")
            for agent, dist in task_dist.items():
                if agent == 'all':
                    continue
                active = dist['pending'] + dist['in_progress']
                if active >= 5:
                    warnings.append(f"{agent} 태스크 {active}개 (과부하)")

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
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        VIBE_SKILL_NAMES = ['master', 'brainstorm', 'debug', 'write-plan', 'execute-plan', 'tdd', 'code-review']
        _proj = _current_project_root()
        claude_commands_dir = _proj / '.claude' / 'commands'
        gemini_skills_dir   = _proj / '.gemini' / 'skills'
        result = {
            'claude': {
                skill: (claude_commands_dir / f'vibe-{skill}.md').exists()
                for skill in VIBE_SKILL_NAMES
            },
            'gemini': {
                skill: (gemini_skills_dir / skill / 'SKILL.md').exists()
                for skill in VIBE_SKILL_NAMES
            },
        }
        handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/skill-results ────────────────────────────────────────────────
    elif path == '/api/skill-results':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
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

    # ── /api/context-usage ───────────────────────────────────────────────
    elif path == '/api/context-usage':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            claude_proj_dir = Path.home() / '.claude' / 'projects' / PROJECT_ID
            sessions = []
            if claude_proj_dir.exists():
                for jsonl_file in claude_proj_dir.glob('*.jsonl'):
                    try:
                        info = _parse_session_tail(jsonl_file)
                        if info:
                            sessions.append(info)
                    except Exception:
                        continue
            sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
            handler.wfile.write(json.dumps(
                {'sessions': sessions[:8]}, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps(
                {'sessions': [], 'error': str(e)}
            ).encode('utf-8'))
        return True

    # ── /api/gemini-context-usage ─────────────────────────────────────────
    elif path == '/api/gemini-context-usage':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            gemini_chat_dir = Path.home() / '.gemini' / 'tmp' / PROJECT_ROOT.name / 'chats'
            sessions = []
            if gemini_chat_dir.exists():
                for json_file in gemini_chat_dir.glob('session-*.json'):
                    try:
                        info = _parse_gemini_session(json_file)
                        if info:
                            sessions.append(info)
                    except Exception:
                        continue
            sessions.sort(key=lambda s: s.get('last_ts', ''), reverse=True)
            handler.wfile.write(json.dumps(
                {'sessions': sessions[:8]}, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps(
                {'sessions': [], 'error': str(e)}
            ).encode('utf-8'))
        return True

    # ── /api/local-models ────────────────────────────────────────────────
    elif path == '/api/local-models':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        import urllib.request as _urllib
        result = {"hardware": {"ram_gb": 0, "gpus": []}, "models": [], "ollama_available": False, "error": None}
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # RAM 감지 (Windows wmic)
        try:
            mem = subprocess.run(
                ['wmic', 'OS', 'get', 'TotalVisibleMemorySize', '/value'],
                capture_output=True, text=True, encoding='utf-8', timeout=5,
                creationflags=_no_window
            )
            for line in mem.stdout.split('\n'):
                if 'TotalVisibleMemorySize=' in line:
                    kb = int(line.split('=')[1].strip())
                    result["hardware"]["ram_gb"] = round(kb / 1024 / 1024, 1)
        except Exception:
            pass
        # GPU 감지 (nvidia-smi)
        try:
            gpu = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, encoding='utf-8', timeout=5,
                creationflags=_no_window
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

    # ── /api/hive/approve-skill ──────────────────────────────────────────
    if path == '/api/hive/approve-skill':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            skill_name = data.get('skill_name')
            keyword    = data.get('keyword', skill_name)
            if not skill_name:
                handler.wfile.write(json.dumps({"status": "error", "message": "Skill name is required"}).encode('utf-8'))
                return True
            skill_dir  = PROJECT_ROOT / ".gemini" / "skills" / skill_name
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
    elif path == '/api/orchestrator/skill-chain/update':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            chain_file = DATA_DIR / 'skill_chain.json'
            chain = {}
            if chain_file.exists():
                with open(chain_file, 'r', encoding='utf-8') as f:
                    chain = json.load(f)
            # 요청 데이터로 병합 업데이트
            chain.update(data)
            chain['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            with open(chain_file, 'w', encoding='utf-8') as f:
                json.dump(chain, f, ensure_ascii=False, indent=2)
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/orchestrator/run ─────────────────────────────────────────────
    elif path == '/api/orchestrator/run':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            orch_script = str(SCRIPTS_DIR / 'orchestrator.py')
            result = subprocess.run(
                [sys.executable, orch_script],
                capture_output=True, text=True, timeout=15, encoding='utf-8',
                creationflags=0x08000000
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
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        import shutil as _shutil
        try:
            tool  = str(data.get('tool', 'claude'))
            _proj = _current_project_root()
            if tool == 'claude':
                skills_src = BASE_DIR / 'skills' / 'claude'
                if not skills_src.exists():
                    skills_src = _proj / 'skills' / 'claude'
                if not skills_src.exists():
                    raise Exception('내장 스킬 파일을 찾을 수 없습니다 (skills/claude/)')
                dest_dir = _proj / '.claude' / 'commands'
                dest_dir.mkdir(parents=True, exist_ok=True)
                installed = []
                for skill_file in skills_src.glob('vibe-*.md'):
                    _shutil.copy(skill_file, dest_dir / skill_file.name)
                    installed.append(skill_file.name)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Claude 스킬 설치 완료: {', '.join(installed)}",
                    'installed': installed
                }, ensure_ascii=False).encode('utf-8'))
            elif tool == 'gemini':
                skills_src = BASE_DIR / 'skills' / 'gemini'
                if not skills_src.exists():
                    skills_src = _proj / '.gemini' / 'skills'
                if not skills_src.exists():
                    raise Exception('내장 스킬 파일을 찾을 수 없습니다 (skills/gemini/ 또는 .gemini/skills/)')
                dest_dir = _proj / '.gemini' / 'skills'
                dest_dir.mkdir(parents=True, exist_ok=True)
                _shutil.copytree(str(skills_src), str(dest_dir), dirs_exist_ok=True)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Gemini 스킬 설치 완료 → {dest_dir}"
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
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        import shutil as _shutil
        try:
            tool  = str(data.get('tool', 'claude'))
            _proj = _current_project_root()
            if tool == 'claude':
                dest_dir = _proj / '.claude' / 'commands'
                removed = []
                if dest_dir.exists():
                    for skill_file in dest_dir.glob('vibe-*.md'):
                        skill_file.unlink(missing_ok=True)
                        removed.append(skill_file.name)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Claude 스킬 제거 완료: {', '.join(removed) if removed else '없음'}",
                    'removed': removed
                }, ensure_ascii=False).encode('utf-8'))
            elif tool == 'gemini':
                dest_dir = _proj / '.gemini' / 'skills'
                if dest_dir.exists():
                    _shutil.rmtree(dest_dir, ignore_errors=True)
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"Gemini 스킬 제거 완료 → {dest_dir}"
                }, ensure_ascii=False).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({'status': 'error', 'message': f'지원하지 않는 tool: {tool}'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
