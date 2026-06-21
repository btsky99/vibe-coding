# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: scripts/vibe_cli.py
# 📝 설명: cmux 호환 vibe CLI — 에이전트 알림/진행률/상태/로그를 제어하는 커맨드라인 도구.
#          cmux CLI(notify, set-progress, set-status, log 등)를 미러링하되,
#          백엔드는 server.py REST API + PostgreSQL을 사용합니다.
#
#          [사용법]
#          python scripts/vibe_cli.py notify --title "빌드 완료" --body "테스트 통과"
#          python scripts/vibe_cli.py set-progress 0.75 --label "Building..."
#          python scripts/vibe_cli.py codex status
#
# REVISION HISTORY:
# [2026-03-22] Gemini: Codex 명령어 통합 (status, start, msg, guide)
# [2026-03-18] Claude: 최초 구현 — cmux CLI 미러링
# ------------------------------------------------------------------------
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ── 경로 및 설정 ──────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_CONFIG_FILE = _PROJECT_ROOT / ".ai_monitor" / "config.json"
_PG_BIN = _PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
_PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')


def _get_server_url() -> str:
    """server.py의 HTTP 포트를 config.json에서 읽어 URL을 반환합니다."""
    port = 9000
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                port = int(cfg.get('http_port', cfg.get('port', 9000)))
        except Exception:
            pass
    return f"http://localhost:{port}"


def _api_call(path: str, data: dict = None, method: str = 'POST') -> dict:
    """server.py API를 호출합니다. 실패 시 빈 dict 반환."""
    url = f"{_get_server_url()}{path}"
    try:
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header('Content-Type', 'application/json')
        else:
            req = urllib.request.Request(url, method=method)

        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        return {'_error': str(e)}


def _psql_fallback(sql: str) -> bool:
    """server.py 미기동 시 psql.exe로 직접 SQL 실행합니다."""
    if not _PG_BIN.exists():
        return False
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        env = os.environ.copy()
        env['PGCLIENTENCODING'] = 'UTF8'
        result = subprocess.run(
            [str(_PG_BIN), '-h', 'localhost', '-p', _PG_PORT,
             '-U', 'postgres', '-d', 'postgres', '-c', sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window, timeout=10, env=env
        )
        return result.returncode == 0
    except Exception:
        return False


def _detect_agent() -> str:
    """현재 환경에서 에이전트 이름을 자동 감지합니다."""
    terminal_id = os.environ.get('TERMINAL_ID', '')
    for name in ['claude', 'antigravity', 'codex']:
        if name in terminal_id.lower():
            return name
    return 'unknown'


# ═══════════════════════════════════════════════════════════════════════════
# 서브커맨드 구현
# ═══════════════════════════════════════════════════════════════════════════

def cmd_notify(args):
    agent = args.agent or _detect_agent()
    data = {'agent': agent, 'title': args.title, 'body': args.body, 'subtitle': getattr(args, 'subtitle', None), 'source': 'cli'}
    result = _api_call('/api/vibe/notify', data)
    if '_error' in result:
        subtitle_val = f"'{args.subtitle}'" if args.subtitle else 'NULL'
        sql = f"INSERT INTO vibe_notifications (agent, title, subtitle, body, source) VALUES ('{agent}', '{args.title}', {subtitle_val}, '{args.body}', 'cli');"
        if _psql_fallback(sql):
            print(f"[vibe] 알림 전송 (psql 폴백): {args.title}")
        else:
            print(f"[vibe] 알림 전송 실패: {result['_error']}", file=sys.stderr)
            return 1
    else:
        print(f"[vibe] 알림 전송: {args.title}")
    return 0


def cmd_set_progress(args):
    agent = args.agent or _detect_agent()
    data = {'agent': agent, 'value': args.value, 'label': args.label or ''}
    result = _api_call('/api/vibe/progress', data)
    if '_error' in result:
        val_json = json.dumps({'value': args.value, 'label': args.label or ''})
        sql = f"INSERT INTO vibe_agent_state (agent, key, value) VALUES ('{agent}', '_progress', '{val_json}') ON CONFLICT (agent, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();"
        _psql_fallback(sql)
    print(f"[vibe] 진행률 설정: {agent} → {args.value}")
    return 0


def cmd_clear_progress(args):
    agent = args.agent or _detect_agent()
    _api_call('/api/vibe/progress/clear', {'agent': agent})
    _psql_fallback(f"DELETE FROM vibe_agent_state WHERE agent = '{agent}' AND key = '_progress';")
    print(f"[vibe] 진행률 제거: {agent}")
    return 0


def cmd_set_status(args):
    agent = args.agent or _detect_agent()
    data = {'agent': agent, 'key': args.key, 'value': args.value, 'icon': args.icon, 'color': args.color}
    result = _api_call('/api/vibe/status', data)
    if '_error' in result:
        sql = f"INSERT INTO vibe_agent_state (agent, key, value, icon, color) VALUES ('{agent}', '{args.key}', '{args.value}', NULL, NULL) ON CONFLICT (agent, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();"
        _psql_fallback(sql)
    print(f"[vibe] 상태 설정: {agent}.{args.key} = {args.value}")
    return 0


def cmd_clear_status(args):
    agent = args.agent or _detect_agent()
    _api_call('/api/vibe/status/clear', {'agent': agent, 'key': args.key})
    _psql_fallback(f"DELETE FROM vibe_agent_state WHERE agent = '{agent}' AND key = '{args.key}';")
    print(f"[vibe] 상태 제거: {agent}.{args.key}")
    return 0


def cmd_log(args):
    agent = args.agent or _detect_agent()
    data = {'agent': agent, 'message': args.message, 'level': args.level, 'source': args.source}
    result = _api_call('/api/vibe/log', data)
    if '_error' in result:
        sql = f"INSERT INTO vibe_agent_logs (agent, message, level, source) VALUES ('{agent}', '{args.message}', '{args.level}', NULL);"
        _psql_fallback(sql)
    print(f"[vibe] 로그 추가 [{args.level}]: {args.message}")
    return 0


def cmd_clear_log(args):
    agent = args.agent or _detect_agent()
    _api_call('/api/vibe/log/clear', {'agent': agent})
    _psql_fallback(f"DELETE FROM vibe_agent_logs WHERE agent = '{agent}';")
    print(f"[vibe] 로그 삭제: {agent}")
    return 0


def cmd_sidebar_state(args):
    result = _api_call('/api/vibe/sidebar', method='GET')
    if '_error' in result:
        print(f"[vibe] 조회 실패: {result['_error']}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ── 코덱스(Codex) 전용 명령어 ──────────────────────────────────────────────

def _check_codex_install():
    status = {"node": False, "codex": False, "path": "", "version": ""}
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        status["node"] = True
    except Exception: pass

    codex_path = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_path:
        local_cmd = _PROJECT_ROOT / "node_modules" / ".bin" / ("codex.cmd" if os.name == "nt" else "codex")
        if local_cmd.exists():
            codex_path = str(local_cmd)

    if codex_path:
        status["codex"] = True
        status["path"] = codex_path
        try:
            result = subprocess.run(
                [codex_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if result.returncode == 0:
                status["version"] = (result.stdout or result.stderr).strip()
        except Exception:
            pass
    return status


def cmd_codex(args):
    action = args.codex_action

    if action == 'status':
        print("\n🔍 [Codex] 시스템 상태 점검")
        st = _check_codex_install()
        codex_path = st.get('path', '')
        codex_version = st.get('version', '')
        print(f"  - Node.js: {'✅ 설치됨' if st['node'] else '❌ 미설치'}")
        print(f"  - Codex CLI: {'✅ 확인됨' if st['codex'] else '🟡 미확인 (scripts/install_codex.py 실행 권장)'}")
        
        if codex_path:
            print(f"  - Codex Path: {codex_path}")
        if codex_version:
            print(f"  - Codex Version: {codex_version}")

        sidebar = _api_call('/api/vibe/sidebar', method='GET')
        active = [agent for agent in sidebar.keys() if agent.startswith('T') or 'codex' in agent.lower()] if not '_error' in sidebar else []
        print(f"  - 활성 터미널: {', '.join(active) if active else '없음'}\n")

    elif action == 'guide':
        guide_path = _PROJECT_ROOT / "CODEX_GUIDE.md"
        if guide_path.exists():
            with open(guide_path, 'r', encoding='utf-8') as f:
                print("\n" + f.read())
        else:
            print("[vibe] CODEX_GUIDE.md 미발견.")

    elif action == 'start':
        tid = args.id or "T1"
        print(f"🚀 [Codex] 에이전트 시작 중... (ID: {tid})")
        script = _PROJECT_ROOT / "scripts" / "agent_shell.py"
        if not script.exists():
            print(f"[vibe] 에러: 스크립트 미발견: {script}")
            return 1
            
        env = os.environ.copy()
        env['TERMINAL_ID'] = tid
        env['VIBE_CLI_TYPE'] = 'codex'
        try:
            subprocess.Popen(
                f'start "{tid} - Codex Agent" python {script} --cli codex --terminal {tid}',
                shell=True,
                env=env,
            )
            print(f"✅ 새 터미널 창에서 {tid} 실행됨.")
        except Exception as e:
            print(f"❌ 실행 실패: {e}")
            return 1

    elif action == 'msg':
        itcp = _PROJECT_ROOT / "scripts" / "itcp.py"
        try:
            subprocess.run([sys.executable, str(itcp), "send", "codex", args.to, args.text], check=True)
            print("✅ ITCP 전송 완료.")
        except Exception as e:
            print(f"❌ 전송 실패: {e}")
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog='vibe', 
        description='🐝 Vibe Coding Hive Mind CLI - 에이전트 상태 및 코덱스(Codex) 제어 도구',
        epilog='자세한 코덱스 사용법은 "vibe codex guide" 명령어를 실행하거나 CODEX_GUIDE.md를 참조하세요.'
    )
    parser.add_argument('--agent', '-a', help='에이전트 이름')
    subparsers = parser.add_subparsers(dest='command', help='명령어')

    # [정리] vibe sync(Junction 방식)는 제거됨 — 옵시디언 2벌 저장 설계(각 PC 로컬 +
    # 구글드라이브 비파괴 미러)와 정면 충돌. 실제 동기화는 daemons.py run_zettel_sync가
    # 전담한다: PG↔로컬 vault 양방향(60초) + 로컬→GDrive mirror_vault(120초).

    # notify, set-progress, clear-progress, set-status, clear-status, log, clear-log, sidebar-state
    p_notify = subparsers.add_parser('notify', help='알림 전송')
    p_notify.add_argument('--title', '-t', required=True)
    p_notify.add_argument('--body', '-b', required=True)
    p_notify.add_argument('--subtitle', '-s')

    p_prog = subparsers.add_parser('set-progress', help='진행률 설정')
    p_prog.add_argument('value', type=float)
    p_prog.add_argument('--label', '-l')

    subparsers.add_parser('clear-progress', help='진행률 제거')

    p_stat = subparsers.add_parser('set-status', help='상태 설정')
    p_stat.add_argument('key')
    p_stat.add_argument('value')
    p_stat.add_argument('--icon', '-i')
    p_stat.add_argument('--color', '-c')

    p_cstat = subparsers.add_parser('clear-status', help='상태 제거')
    p_cstat.add_argument('key')

    p_log = subparsers.add_parser('log', help='로그 추가')
    p_log.add_argument('message')
    p_log.add_argument('--level', '-l', default='info', choices=['info', 'progress', 'success', 'warning', 'error'])
    p_log.add_argument('--source', '-s')

    subparsers.add_parser('clear-log', help='로그 제거')
    subparsers.add_parser('sidebar-state', help='상태 조회')

    # codex
    p_cdx = subparsers.add_parser('codex', help='코덱스 관리')
    cdx_s = p_cdx.add_subparsers(dest='codex_action')
    cdx_s.add_parser('status')
    cdx_s.add_parser('guide')
    p_start = cdx_s.add_parser('start'); p_start.add_argument('--id')
    p_msg = cdx_s.add_parser('msg'); p_msg.add_argument('--to', required=True); p_msg.add_argument('--text', required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {
        'notify': cmd_notify, 'set-progress': cmd_set_progress, 'clear-progress': cmd_clear_progress,
        'set-status': cmd_set_status, 'clear-status': cmd_clear_status, 'log': cmd_log,
        'clear-log': cmd_clear_log, 'sidebar-state': cmd_sidebar_state, 'codex': cmd_codex,
    }

    handler = cmds.get(args.command)
    return handler(args) if handler else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
