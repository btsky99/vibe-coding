"""
FILE: api/mcp_api.py
DESCRIPTION: /api/mcp/* endpoints for catalog, Smithery lookup, and MCP install state.

REVISION HISTORY:
- 2026-03-01 Claude: split MCP routes out of server.py
- 2026-03-08 Claude: add Codex CLI catalog entry and custom command/args support
- 2026-03-08 Codex: switch Codex MCP management to config.toml / `codex mcp`
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode


_AI_MONITOR_DIR = Path(__file__).resolve().parent.parent


def _codex_installed_entries(config_path: Path) -> list[str]:
    """Read Codex MCP server names from ~/.codex/config.toml."""
    if not config_path.exists():
        return []
    data = tomllib.loads(config_path.read_text(encoding='utf-8'))
    servers = data.get('mcp_servers', {})
    return list(servers.keys()) if isinstance(servers, dict) else []


def _default_npx_command() -> str:
    """Return a Windows-safe npx command path for MCP stdio servers."""
    if os.name == 'nt':
        return shutil.which('npx.cmd') or shutil.which('npx') or 'npx.cmd'
    return shutil.which('npx') or 'npx'


def _powershell_quote(arg: str) -> str:
    """Quote a single PowerShell argument safely."""
    return "'" + arg.replace("'", "''") + "'"


def _run_codex_mcp(args: list[str]) -> tuple[bool, str]:
    """Run `codex mcp ...` and return (success, output_message)."""
    codex_bin = shutil.which('codex.cmd' if os.name == 'nt' else 'codex') or shutil.which('codex')
    if not codex_bin:
        return False, 'Codex CLI가 설치되어 있지 않습니다. 먼저 Codex CLI를 설치하세요.'

    try:
        if os.name == 'nt':
            ps_cmd = ' '.join([
                'codex',
                _powershell_quote('mcp'),
                *(_powershell_quote(arg) for arg in args),
            ])
            proc = subprocess.run(
                ['powershell.exe', '-NoProfile', '-Command', ps_cmd],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=20,
                check=False,
            )
        else:
            proc = subprocess.run(
                [codex_bin, 'mcp', *args],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=20,
                check=False,
            )
    except Exception as e:
        return False, str(e)

    output = (proc.stdout or proc.stderr or '').strip()
    if proc.returncode != 0:
        return False, output or f'codex mcp 명령 실패 (exit={proc.returncode})'
    return True, output or '완료'


def _catalog() -> list[dict]:
    """Return the built-in MCP catalog displayed in the panel."""
    return [
        {
            'name': 'context7',
            'package': '@upstash/context7-mcp',
            'description': '최신 라이브러리 공식 문서를 실시간으로 조회합니다.',
            'category': '문서',
            'args': [],
        },
        {
            'name': 'github',
            'package': '@modelcontextprotocol/server-github',
            'description': 'GitHub API 연동으로 이슈, PR, 저장소를 조회합니다.',
            'category': '개발',
            'requiresEnv': ['GITHUB_PERSONAL_ACCESS_TOKEN'],
            'args': [],
        },
        {
            'name': 'playwright',
            'package': '@playwright/mcp',
            'description': '브라우저 자동화, 스크린샷, 입력, 클릭을 수행합니다.',
            'category': '브라우저',
            'args': [],
        },
        {
            'name': 'codex-cli',
            'package': '__local__',
            'command': str(_AI_MONITOR_DIR / 'venv' / 'Scripts' / 'python.exe'),
            'args': [str(_AI_MONITOR_DIR / 'bin' / 'mcp_server.py')],
            'description': 'Vibe Coding 로컬 AI 오케스트레이터 MCP 서버 (Codex CLI).',
            'category': 'AI',
        },
    ]


def handle_get(handler, path: str, params: dict, _smithery_api_key, _mcp_config_path, **_unused) -> bool:
    """Handle GET requests for MCP APIs."""
    if path == '/api/mcp/catalog':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        handler.wfile.write(json.dumps(_catalog(), ensure_ascii=False).encode('utf-8'))
        return True

    if path == '/api/mcp/apikey':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        key = _smithery_api_key()
        masked = (key[:6] + '...' + key[-4:]) if len(key) > 12 else ('*' * len(key) if key else '')
        handler.wfile.write(
            json.dumps({'has_key': bool(key), 'masked': masked}, ensure_ascii=False).encode('utf-8')
        )
        return True

    if path == '/api/mcp/search':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        q = params.get('q', [''])[0].strip()
        page = int(params.get('page', ['1'])[0])
        page_size = int(params.get('pageSize', ['20'])[0])
        api_key = _smithery_api_key()

        if not api_key:
            handler.wfile.write(json.dumps({
                'error': 'NO_KEY',
                'message': 'Smithery API 키가 설정되지 않았습니다.',
            }, ensure_ascii=False).encode('utf-8'))
            return True

        if not q:
            handler.wfile.write(json.dumps({
                'servers': [],
                'pagination': {'currentPage': 1, 'totalPages': 0, 'totalCount': 0},
            }, ensure_ascii=False).encode('utf-8'))
            return True

        try:
            query = urlencode({'q': q, 'page': page, 'pageSize': page_size})
            req = urllib.request.Request(
                f'https://registry.smithery.ai/servers?{query}',
                headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except urllib.error.HTTPError as e:
            msg = 'API 키가 유효하지 않습니다.' if e.code == 401 else f'Smithery API 오류 ({e.code})'
            handler.wfile.write(json.dumps({
                'error': f'HTTP_{e.code}',
                'message': msg,
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({
                'error': 'NETWORK',
                'message': str(e),
            }, ensure_ascii=False).encode('utf-8'))
        return True

    if path == '/api/mcp/installed':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        tool = params.get('tool', ['claude'])[0]
        scope = params.get('scope', ['global'])[0]
        config_path = _mcp_config_path(tool, scope)

        try:
            if tool == 'codex':
                installed = _codex_installed_entries(config_path)
            elif config_path.exists():
                data = json.loads(config_path.read_text(encoding='utf-8'))
                installed = list(data.get('mcpServers', {}).keys())
            else:
                installed = []
            handler.wfile.write(json.dumps({'installed': installed}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({
                'installed': [],
                'error': str(e),
            }, ensure_ascii=False).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict, _smithery_api_key_setter, _mcp_config_path, **_unused) -> bool:
    """Handle POST requests for MCP APIs."""
    if path == '/api/mcp/apikey':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            api_key = str(data.get('api_key') or data.get('apikey') or '').strip()
            _smithery_api_key_setter.write_text(
                json.dumps({'api_key': api_key}, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({
                'status': 'error',
                'message': str(e),
            }, ensure_ascii=False).encode('utf-8'))
        return True

    if path == '/api/mcp/install':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            tool = str(data.get('tool', 'claude'))
            scope = str(data.get('scope', 'global'))
            name = str(data.get('name', ''))
            package = str(data.get('package', ''))
            req_env = [str(v) for v in data.get('requiresEnv', [])]

            if not name or not package:
                handler.wfile.write(json.dumps({
                    'status': 'error',
                    'message': 'name/package required',
                }, ensure_ascii=False).encode('utf-8'))
                return True

            if tool == 'codex':
                if scope != 'global':
                    handler.wfile.write(json.dumps({
                        'status': 'error',
                        'message': '현재 Codex CLI MCP 설치는 전역(Global) 범위만 지원합니다.',
                    }, ensure_ascii=False).encode('utf-8'))
                    return True

                custom_command = str(data.get('command', '')).strip()
                custom_args = [str(arg) for arg in data.get('args', [])]
                cmd = ['add', name]
                for env_key in req_env:
                    cmd.extend(['--env', f'{env_key}=<YOUR_{env_key}>'])
                cmd.append('--')
                if custom_command:
                    cmd.extend([custom_command, *custom_args])
                else:
                    cmd.extend([_default_npx_command(), '-y', package])

                ok, msg = _run_codex_mcp(cmd)
                handler.wfile.write(json.dumps({
                    'status': 'success' if ok else 'error',
                    'message': msg,
                }, ensure_ascii=False).encode('utf-8'))
                return True

            config_path = _mcp_config_path(tool, scope)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
            if 'mcpServers' not in config:
                config['mcpServers'] = {}

            custom_command = str(data.get('command', '')).strip()
            custom_args = [str(arg) for arg in data.get('args', [])]
            if custom_command:
                entry: dict = {'command': custom_command, 'args': custom_args}
            else:
                entry = {'command': _default_npx_command(), 'args': ['-y', package]}
            if req_env:
                entry['env'] = {k: f'<YOUR_{k}>' for k in req_env}
            config['mcpServers'][name] = entry

            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            msg = f"MCP '{name}' 설치 완료 -> {config_path}"
            if req_env:
                msg += f" | 환경변수 필요: {', '.join(req_env)} | 설치 후 실제 키 값으로 바꾸세요."
            handler.wfile.write(json.dumps({
                'status': 'success',
                'message': msg,
            }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({
                'status': 'error',
                'message': str(e),
            }, ensure_ascii=False).encode('utf-8'))
        return True

    if path == '/api/mcp/uninstall':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            tool = str(data.get('tool', 'claude'))
            scope = str(data.get('scope', 'global'))
            name = str(data.get('name', ''))

            if not name:
                handler.wfile.write(json.dumps({
                    'status': 'error',
                    'message': 'name required',
                }, ensure_ascii=False).encode('utf-8'))
                return True

            if tool == 'codex':
                if scope != 'global':
                    handler.wfile.write(json.dumps({
                        'status': 'error',
                        'message': '현재 Codex CLI MCP 삭제는 전역(Global) 범위만 지원합니다.',
                    }, ensure_ascii=False).encode('utf-8'))
                    return True

                ok, msg = _run_codex_mcp(['remove', name])
                handler.wfile.write(json.dumps({
                    'status': 'success' if ok else 'error',
                    'message': msg,
                }, ensure_ascii=False).encode('utf-8'))
                return True

            config_path = _mcp_config_path(tool, scope)
            if not config_path.exists():
                handler.wfile.write(json.dumps({
                    'status': 'error',
                    'message': '설정 파일이 없습니다.',
                }, ensure_ascii=False).encode('utf-8'))
                return True

            config = json.loads(config_path.read_text(encoding='utf-8'))
            servers = config.get('mcpServers', {})
            if name in servers:
                del servers[name]
                config['mcpServers'] = servers
                config_path.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                handler.wfile.write(json.dumps({
                    'status': 'success',
                    'message': f"MCP '{name}' 제거 완료",
                }, ensure_ascii=False).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({
                    'status': 'error',
                    'message': f"'{name}' 항목이 없습니다.",
                }, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({
                'status': 'error',
                'message': str(e),
            }, ensure_ascii=False).encode('utf-8'))
        return True

    return False
