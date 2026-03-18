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
#          python scripts/vibe_cli.py clear-progress
#          python scripts/vibe_cli.py set-status build "running" --color "#2ecc71"
#          python scripts/vibe_cli.py clear-status build
#          python scripts/vibe_cli.py log "Task complete" --level success
#          python scripts/vibe_cli.py clear-log
#          python scripts/vibe_cli.py sidebar-state
#
#          [통신 경로]
#          1차: HTTP POST → server.py /api/vibe/* (로컬 9000번 포트)
#          폴백: psql.exe 직접 INSERT (server.py 미기동 시)
#
# REVISION HISTORY:
# [2026-03-18] Claude: 최초 구현 — cmux CLI 미러링
#   - argparse 기반 8개 서브커맨드
#   - server.py API 호출 + psql 폴백 이중 경로
#   - 포트 자동 탐색 (config.json → 9000 기본값)
# ------------------------------------------------------------------------
"""

import argparse
import json
import os
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
    """server.py의 HTTP 포트를 config.json에서 읽어 URL을 반환합니다.
    config.json이 없거나 포트 정보가 없으면 기본값 9000 사용.
    """
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
    """server.py API를 호출합니다. 실패 시 빈 dict 반환.

    [설계 의도] hive_bridge.py의 _call_api 패턴을 재사용.
    urllib.request로 외부 의존성 없이 HTTP 호출.
    """
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
    """server.py 미기동 시 psql.exe로 직접 SQL 실행합니다.

    [설계 의도] hive_bridge.py의 psql 폴백 패턴을 재사용.
    server.py가 꺼져 있어도 CLI가 동작하도록 보장합니다.
    """
    if not _PG_BIN.exists():
        print(f"[vibe] psql 미발견: {_PG_BIN}", file=sys.stderr)
        return False
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # PGCLIENTENCODING=UTF8: Windows CP949 환경에서 한글 인코딩 충돌 방지
        env = os.environ.copy()
        env['PGCLIENTENCODING'] = 'UTF8'
        result = subprocess.run(
            [str(_PG_BIN), '-h', 'localhost', '-p', _PG_PORT,
             '-U', 'postgres', '-d', 'postgres', '-c', sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window, timeout=10, env=env
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[vibe] psql 오류: {e}", file=sys.stderr)
        return False


def _detect_agent() -> str:
    """현재 환경에서 에이전트 이름을 자동 감지합니다."""
    terminal_id = os.environ.get('TERMINAL_ID', '')
    if 'claude' in terminal_id.lower():
        return 'claude'
    if 'gemini' in terminal_id.lower():
        return 'gemini'
    if 'codex' in terminal_id.lower():
        return 'codex'
    return 'unknown'


# ═══════════════════════════════════════════════════════════════════════════
# 서브커맨드 구현
# ═══════════════════════════════════════════════════════════════════════════

def cmd_notify(args):
    """알림 전송 — cmux notify 미러"""
    agent = args.agent or _detect_agent()
    data = {
        'agent': agent,
        'title': args.title,
        'body': args.body,
        'subtitle': getattr(args, 'subtitle', None),
        'source': 'cli',
    }
    result = _api_call('/api/vibe/notify', data)
    if '_error' in result:
        # 폴백: psql 직접 INSERT
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
    """진행률 설정 — cmux set-progress 미러"""
    agent = args.agent or _detect_agent()
    data = {
        'agent': agent,
        'value': args.value,
        'label': args.label or '',
    }
    result = _api_call('/api/vibe/progress', data)
    if '_error' in result:
        progress_json = json.dumps({'value': args.value, 'label': args.label or ''})
        sql = f"INSERT INTO vibe_agent_state (agent, key, value) VALUES ('{agent}', '_progress', '{progress_json}') ON CONFLICT (agent, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();"
        _psql_fallback(sql)
    print(f"[vibe] 진행률 설정: {agent} → {args.value}")
    return 0


def cmd_clear_progress(args):
    """진행률 제거 — cmux clear-progress 미러"""
    agent = args.agent or _detect_agent()
    result = _api_call('/api/vibe/progress/clear', {'agent': agent})
    if '_error' in result:
        _psql_fallback(f"DELETE FROM vibe_agent_state WHERE agent = '{agent}' AND key = '_progress';")
    print(f"[vibe] 진행률 제거: {agent}")
    return 0


def cmd_set_status(args):
    """사이드바 상태 설정 — cmux set-status 미러"""
    agent = args.agent or _detect_agent()
    data = {
        'agent': agent,
        'key': args.key,
        'value': args.value,
        'icon': args.icon,
        'color': args.color,
    }
    result = _api_call('/api/vibe/status', data)
    if '_error' in result:
        sql = f"INSERT INTO vibe_agent_state (agent, key, value, icon, color) VALUES ('{agent}', '{args.key}', '{args.value}', NULL, NULL) ON CONFLICT (agent, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();"
        _psql_fallback(sql)
    print(f"[vibe] 상태 설정: {agent}.{args.key} = {args.value}")
    return 0


def cmd_clear_status(args):
    """사이드바 상태 제거 — cmux clear-status 미러"""
    agent = args.agent or _detect_agent()
    data = {'agent': agent, 'key': args.key}
    result = _api_call('/api/vibe/status/clear', data)
    if '_error' in result:
        _psql_fallback(f"DELETE FROM vibe_agent_state WHERE agent = '{agent}' AND key = '{args.key}';")
    print(f"[vibe] 상태 제거: {agent}.{args.key}")
    return 0


def cmd_log(args):
    """로그 추가 — cmux log 미러"""
    agent = args.agent or _detect_agent()
    data = {
        'agent': agent,
        'message': args.message,
        'level': args.level,
        'source': args.source,
    }
    result = _api_call('/api/vibe/log', data)
    if '_error' in result:
        sql = f"INSERT INTO vibe_agent_logs (agent, message, level, source) VALUES ('{agent}', '{args.message}', '{args.level}', NULL);"
        _psql_fallback(sql)
    print(f"[vibe] 로그 추가 [{args.level}]: {args.message}")
    return 0


def cmd_clear_log(args):
    """로그 전체 삭제 — cmux clear-log 미러"""
    agent = args.agent or _detect_agent()
    result = _api_call('/api/vibe/log/clear', {'agent': agent})
    if '_error' in result:
        _psql_fallback(f"DELETE FROM vibe_agent_logs WHERE agent = '{agent}';")
    print(f"[vibe] 로그 삭제: {agent}")
    return 0


def cmd_sidebar_state(args):
    """전체 사이드바 상태 조회 — cmux sidebar-state 미러"""
    result = _api_call('/api/vibe/sidebar', method='GET')
    if '_error' in result:
        print(f"[vibe] 조회 실패: {result['_error']}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# argparse 메인
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        prog='vibe',
        description='cmux 호환 vibe CLI — 에이전트 알림/진행률/상태/로그 제어'
    )
    parser.add_argument('--agent', '-a', help='에이전트 이름 (기본: 자동 감지)')
    subparsers = parser.add_subparsers(dest='command', help='사용 가능한 명령어')

    # notify
    p_notify = subparsers.add_parser('notify', help='알림 전송')
    p_notify.add_argument('--title', '-t', required=True, help='알림 제목')
    p_notify.add_argument('--body', '-b', required=True, help='알림 본문')
    p_notify.add_argument('--subtitle', '-s', help='부제목')

    # set-progress
    p_progress = subparsers.add_parser('set-progress', help='진행률 설정 (0.0~1.0)')
    p_progress.add_argument('value', type=float, help='진행률 값 (0.0~1.0)')
    p_progress.add_argument('--label', '-l', help='진행률 레이블')

    # clear-progress
    subparsers.add_parser('clear-progress', help='진행률 제거')

    # set-status
    p_status = subparsers.add_parser('set-status', help='사이드바 상태 설정')
    p_status.add_argument('key', help='상태 키 (예: build, deploy)')
    p_status.add_argument('value', help='상태 값 (예: running, done)')
    p_status.add_argument('--icon', '-i', help='아이콘 이름')
    p_status.add_argument('--color', '-c', help='색상 (예: #2ecc71)')

    # clear-status
    p_clear_status = subparsers.add_parser('clear-status', help='사이드바 상태 제거')
    p_clear_status.add_argument('key', help='제거할 상태 키')

    # log
    p_log = subparsers.add_parser('log', help='로그 추가')
    p_log.add_argument('message', help='로그 메시지')
    p_log.add_argument('--level', '-l', default='info',
                       choices=['info', 'progress', 'success', 'warning', 'error'],
                       help='로그 레벨 (기본: info)')
    p_log.add_argument('--source', '-s', help='소스 이름')

    # clear-log
    subparsers.add_parser('clear-log', help='로그 전체 삭제')

    # sidebar-state
    subparsers.add_parser('sidebar-state', help='전체 사이드바 상태 조회')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # 커맨드 디스패치
    commands = {
        'notify': cmd_notify,
        'set-progress': cmd_set_progress,
        'clear-progress': cmd_clear_progress,
        'set-status': cmd_set_status,
        'clear-status': cmd_clear_status,
        'log': cmd_log,
        'clear-log': cmd_clear_log,
        'sidebar-state': cmd_sidebar_state,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
