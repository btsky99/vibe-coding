"""
FILE: tests/test_route_table.py
DESCRIPTION: server.py 라우트 완전성 가드 — do_GET/do_POST를 if/elif에서 디스패치 테이블로
             재구조화할 때 라우트가 조용히 누락(→404)되지 않도록 방어한다.
             HEAD 시점 골든 라우트 집합 ⊆ 현재 server.py 추출 집합을 강제한다.

  [WHY] 103개 유닛 테스트는 대부분 라우트를 커버하지 않음. 재구조화 중 라우트 한 개를
    빠뜨려도 유닛 테스트는 통과 → 조용히 기능 소실. 이 가드가 그 구멍을 막는다.
    (2026-07-05 projects 추출 near-miss로 확립한 규율.)

REVISION HISTORY:
- 2026-07-28 Codex: Guard the automatic first-run installer route.
- 2026-07-28 Codex: Guard the Setup Doctor status route against silent SPA fallback.
- 2026-07-05 Claude: 신규 — 디스패치 테이블 재구조화 Phase 1 Task 1(변경 전 게이트).
- 2026-07-06 Claude: Phase 2 R9.5 — `path in (...)` 튜플 파싱 추가(복합조건 라우트
  hive exact8·install-cli3·tasks/memory/files 감지, 기존 사각지대 해소). golden에 22종 편입.
"""
import re
from pathlib import Path

_SERVER = Path(__file__).resolve().parents[1] / ".ai_monitor" / "server.py"

# ── 골든 라우트 (2026-07-05 HEAD 캡처) — 재구조화 후에도 전부 처리되어야 한다 ──
GOLDEN_EXACT = {
    '/api/setup/auto-install',
    # do_GET
    '/api/agents', '/api/browse-folder', '/api/check-update-ready', '/api/config',
    '/api/config/telegram', '/api/copy-path', '/api/dirs', '/api/drives',
    '/api/events/agent', '/api/events/fs', '/api/events/thoughts', '/api/heal/metrics',
    '/api/heartbeat', '/api/help', '/api/image-file', '/api/install-skills',
    '/api/install-tool-status', '/api/memory/db-info',
    '/api/messages', '/api/projects', '/api/register-codex-to-ai', '/api/server-logs',
    '/api/shutdown', '/api/soft-update/check', '/api/tool-status',
    '/api/setup/status',
    '/api/trigger-update-check', '/api/vibe/notifications', '/api/vibe/sidebar',
    '/api/vibe/skills', '/stream',
    # do_POST
    '/api/agents/heartbeat', '/api/apply-update', '/api/config/update',
    '/api/dashboard/launch', '/api/git/diff', '/api/git/rollback', '/api/hive/log/pg',
    # [9차 정리 2026-07-16] /api/kanban/launch·/api/kanban/pg-activity 은퇴 — 보드 UI 소멸
    '/api/hive/thought/pg', '/api/install-playwright-cli',
    '/api/launch', '/api/locks', '/api/message', '/api/messages/clear',
    '/api/office/launch', '/api/office/restart', '/api/office/status',
    '/api/open-external', '/api/run-script', '/api/screenshot/analyze',
    '/api/select-folder', '/api/send-command', '/api/soft-update/apply',
    '/api/telegram/test', '/api/thoughts/add', '/api/vibe/log', '/api/vibe/log/clear',
    '/api/vibe/notify', '/api/vibe/progress', '/api/vibe/progress/clear',
    '/api/vibe/status', '/api/vibe/status/clear',
    # ── 복합조건(path in 튜플) 라우트 — R9.5 in튜플 파싱으로 감지, 기존 사각지대 해소 ──
    # do_GET: hive exact8 + memory in2 + tasks in4 + files in2 + install-cli in3
    '/api/superpowers/status', '/api/skill-results', '/api/skill-ab-test',
    '/api/skill/predict', '/api/context-usage', '/api/antigravity-context-usage',
    '/api/agent-quota', '/api/local-models',
    '/api/memory', '/api/project-info',
    '/api/tasks', '/api/tasks/kanban', '/api/task-logs', '/api/agents/status',
    '/api/files', '/api/read-file',
    '/api/install-gemini-cli', '/api/install-claude-code', '/api/install-codex-cli',
    # do_POST: tasks in4
    '/api/tasks/update', '/api/tasks/delete', '/api/tasks/claim',
}
GOLDEN_PREFIX = {
    # [8차 정리 2026-07-15] '/api/agents/' prefix 제거 — 유일 사용처였던
    # /api/agents/*/trigger(리스너 미가동 무기능)가 은퇴됨. exact 라우트
    # (/api/agents/status, /api/agents/heartbeat)는 유지.
    '/api/agent/', '/api/codegraph/', '/api/experience', '/api/git/',
    '/api/hive/', '/api/memory/', '/api/office/', '/api/orchestrator/', '/api/pty/',
    '/api/superpowers/', '/api/tasks/', '/api/tools/', '/api/zettel/',
}


def _extract(source: str):
    """server.py 소스에서 라우트 리터럴 추출 — elif(path==)·dict키·startswith·prefix튜플 모두.
    [WHY] 라우트가 elif에 있든 테이블 dict키/prefix리스트에 있든 동일하게 잡아야 재구조화 도중
      위치가 바뀌어도 완전성을 검증할 수 있다.
    """
    exact = set(re.findall(r"path == '(/[^']+)'", source))
    # 테이블 dict 키: 줄 시작 공백 + '/...': (라우트형만)
    exact |= {m for m in re.findall(r"^\s*'(/[^']+)'\s*:", source, re.M)
              if m.startswith('/api/') or m == '/stream'}
    prefix = set(re.findall(r"startswith\('(/[^']+)'\)", source))
    # prefix 튜플: ('/...', 형태
    prefix |= {m for m in re.findall(r"^\s*\(\s*'(/[^']+)'\s*,", source, re.M)
               if m.startswith('/api/')}
    # path in ('/a', '/b', ...) 튜플 — 복합조건 라우트(R9.5). 멀티라인 튜플 지원.
    # [WHY] hive exact8·install-cli3·tasks/memory/files의 in 튜플은 path==/dict키/startswith
    #   어디에도 안 걸려 기존 가드 사각지대였다(Critic 지적). in(...) 안 리터럴을 exact로 편입.
    #   [제약] 튜플 안엔 ')' 문자가 없다는 전제(라우트 문자열엔 괄호 없음) — [^)]+로 멀티라인 캡처.
    for _tup in re.findall(r"path in \(([^)]+)\)", source):
        exact |= set(re.findall(r"'(/[^']+)'", _tup))
    return exact, prefix


def test_no_route_lost():
    """골든 라우트가 전부 현재 server.py에 처리 리터럴로 존재해야 한다(누락=404 회귀)."""
    exact, prefix = _extract(_SERVER.read_text(encoding='utf-8'))
    missing_exact = GOLDEN_EXACT - exact
    missing_prefix = GOLDEN_PREFIX - prefix
    assert not missing_exact, f"exact 라우트 누락(404 위험): {sorted(missing_exact)}"
    assert not missing_prefix, f"prefix 라우트 누락(404 위험): {sorted(missing_prefix)}"


def test_prefix_non_shadowing():
    """어떤 골든 prefix도 다른 golden prefix의 시작부분이면 안 됨(리스트 순서 조회 시 가림 방지).
    [불변식] 정확 경로는 exact 테이블이 먼저 처리 → prefix끼리만 비중첩이면 안전.
    """
    pfx = sorted(GOLDEN_PREFIX)
    for a in pfx:
        for b in pfx:
            if a != b:
                assert not b.startswith(a), f"prefix 가림: '{a}'가 '{b}'를 선점 (순서 의존)"
