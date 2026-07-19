# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: api/experience_api.py
# 📝 설명: 에이전트 경험 수집 & 성장 시스템 REST API.
#          작업 완료 시 경험 기록, 레벨/스킬 통계 조회를 제공한다.
#
#          [엔드포인트 목록]
#          POST  /api/experience          → 경험 기록 (agent_experience INSERT + stats 갱신)
#          GET   /api/experience/stats    → 에이전트별 레벨/XP/스킬맵 조회
#          GET   /api/experience/history  → 최근 경험 목록 조회
#
# REVISION HISTORY:
# [2026-04-10] Claude: 최초 구현 — 진화하는 LLM Phase 1
# ------------------------------------------------------------------------
"""



# [중복통합 2026-07-18] _json_response/_read_body는 api/_common.py로 통합 — 패스스루 재노출.
from api._common import json_response as _json_response, read_body as _read_body


def handle_get(handler, path: str, params: dict | None = None) -> None:
    """GET 요청 처리."""
    from src.pg_store import get_agent_stats, get_experience_history

    params = params or {}

    if path == '/api/experience/stats':
        agent = (params.get('agent', ['']) or [''])[0] or None
        stats = get_agent_stats(agent)
        _json_response(handler, {'stats': stats})
        return

    if path == '/api/experience/seed':
        result = seed_from_git_log()
        _json_response(handler, result)
        return

    if path == '/api/experience/recall':
        from src.pg_store import recall_similar_experience
        query = (params.get('query', ['']) or [''])[0]
        if not query:
            _json_response(handler, {'error': 'query 파라미터 필수'}, 400)
            return
        domain = (params.get('domain', ['']) or [''])[0] or ''
        task_type = (params.get('task_type', ['']) or [''])[0] or ''
        agent = (params.get('agent', ['']) or [''])[0] or ''
        limit = int((params.get('limit', ['5']) or ['5'])[0])
        results = recall_similar_experience(query, domain=domain, task_type=task_type,
                                            agent_id=agent, limit=limit)
        _json_response(handler, {'recall': results, 'query': query})
        return

    if path == '/api/experience/history':
        agent = (params.get('agent', ['']) or [''])[0] or None
        limit = int((params.get('limit', ['20']) or ['20'])[0])
        history = get_experience_history(agent, limit=limit)
        _json_response(handler, {'history': history})
        return

    _json_response(handler, {'error': 'not_found', 'path': path}, 404)


def handle_post(handler, path: str) -> None:
    """POST 요청 처리."""
    from src.pg_store import record_experience

    if path != '/api/experience':
        _json_response(handler, {'error': 'not_found', 'path': path}, 404)
        return

    data = _read_body(handler)
    agent_id = data.get('agent_id', '').strip()
    if not agent_id:
        _json_response(handler, {'error': 'agent_id 필수'}, 400)
        return

    ok = record_experience(
        agent_id=agent_id,
        task_type=data.get('task_type', 'feat'),
        domain=data.get('domain', 'general'),
        outcome=data.get('outcome', 'success'),
        duration_sec=int(data.get('duration_sec', 0)),
        file_patterns=data.get('file_patterns'),
        session_id=data.get('session_id', ''),
        description=data.get('description', ''),
    )

    if ok:
        from src.pg_store import get_agent_stats
        stats = get_agent_stats(agent_id)
        _json_response(handler, {
            'status': 'success',
            'xp_recorded': True,
            'stats': stats[0] if stats else {},
        })
    else:
        _json_response(handler, {'error': '경험 기록 실패'}, 500)


# ── 초기 데이터 마이닝 — git log에서 경험 시드 생성 ──────────────────────────

def _detect_agent(commit_body: str) -> str:
    """Co-Authored-By 헤더에서 에이전트 이름 추출."""
    body_lower = commit_body.lower()
    if 'claude' in body_lower:
        return 'claude'
    if 'antigravity' in body_lower:
        return 'antigravity'
    if 'codex' in body_lower or 'gpt' in body_lower:
        return 'codex'
    return 'claude'  # 기본값


def _detect_task_type(subject: str) -> str:
    """커밋 제목에서 Conventional Commits 타입 추출."""
    import re
    m = re.match(r'^(feat|fix|refactor|docs|build|chore|test)', subject.lower())
    return m.group(1) if m else 'chore'


def _detect_domain(files: list[str]) -> str:
    """변경 파일 확장자에서 도메인 추론."""
    ext_map = {
        '.tsx': 'frontend', '.ts': 'frontend', '.jsx': 'frontend',
        '.css': 'frontend', '.html': 'frontend',
        '.py': 'backend', '.sql': 'db',
        '.json': 'config', '.yaml': 'config', '.yml': 'config',
        '.md': 'docs', '.spec': 'build', '.sh': 'infra',
    }
    domain_counts: dict[str, int] = {}
    for f in files:
        for ext, domain in ext_map.items():
            if f.endswith(ext):
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
                break
    if not domain_counts:
        return 'general'
    return max(domain_counts, key=domain_counts.get)


def seed_from_git_log(repo_dir: str = '.', since: str = '2026-01-01',
                      dry_run: bool = False) -> dict:
    """git log를 파싱하여 agent_experience에 초기 데이터를 시드한다.

    Returns: {'seeded': int, 'skipped': int, 'errors': int}
    """
    import re
    from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼
    from src.pg_store import record_experience, query_rows

    # 이미 시드 완료 여부 확인
    existing = query_rows("SELECT COUNT(*) AS cnt FROM agent_experience;")
    if existing and int(existing[0].get('cnt', 0)) > 10:
        return {'seeded': 0, 'skipped': 0, 'errors': 0, 'message': '이미 시드 데이터 존재'}

    # git log 파싱: hash, subject, body, files
    sep = '|||COMMIT_SEP|||'
    cmd = [
        'git', 'log', f'--since={since}', '--no-merges',
        f'--format={sep}%H||%s||%b', '--stat',
    ]
    # [WHY] POST /api/experience 시드 시 git 자식이 콘솔 없이 돌게 — proc.run이 숨김 주입.
    result = proc.run(cmd, capture_output=True, text=True, cwd=repo_dir,
                      encoding='utf-8', errors='replace')
    if result.returncode != 0:
        return {'seeded': 0, 'skipped': 0, 'errors': 1, 'message': result.stderr}

    commits = result.stdout.split(sep)
    stats = {'seeded': 0, 'skipped': 0, 'errors': 0}

    for block in commits:
        block = block.strip()
        if not block or '||' not in block:
            continue

        # 첫 줄: hash||subject||body, 나머지: stat 파일 목록
        lines = block.split('\n')
        header = lines[0]
        parts = header.split('||', 2)
        if len(parts) < 2:
            continue

        commit_hash = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ''

        # github-actions 봇 커밋 스킵
        if '[skip ci]' in subject or 'auto-bump' in subject:
            stats['skipped'] += 1
            continue

        # 변경 파일 추출 (stat 출력에서)
        files = []
        for line in lines[1:]:
            line = line.strip()
            if '|' in line and not line.startswith('|||'):
                fname = line.split('|')[0].strip()
                if fname:
                    files.append(fname)

        agent = _detect_agent(body)
        task_type = _detect_task_type(subject)
        domain = _detect_domain(files)

        if dry_run:
            stats['seeded'] += 1
            continue

        ok = record_experience(
            agent_id=agent,
            task_type=task_type,
            domain=domain,
            outcome='success',
            file_patterns=files[:10],  # 최대 10개
            session_id=f'git_{commit_hash[:8]}',
            description=subject,
        )
        if ok:
            stats['seeded'] += 1
        else:
            stats['errors'] += 1

    return stats
