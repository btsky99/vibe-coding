# ─────────────────────────────────────────────────────────────────────────────
# 📄 파일명: infra/heartbeat_daemon.py
# 📝 설명: 자율 클로드 심장 박동 데몬 — 사람이 부르지 않아도 주기적으로 깨어나
#          hive_tasks(assigned_to='claude-auto')를 체크아웃·수행하고, 없으면
#          incident_ledger 재발 사고에서 개선 태스크를 자가 발굴한다.
#          샌드박스 = worktree 격리 + deny 권한 프로파일 이중벽.
# 🕒 변경 이력:
# [2026-07-17] Claude — 신규 (브레인스토밍 승인: project_heartbeat_daemon.md)
#   - [WHY] --dangerously-skip-permissions 대신 --settings deny 프로파일 주입 —
#     자율 실행이어도 push/merge/삭제류는 CLI 레벨에서 차단 (프롬프트 의존 금지).
#   - [WHY] 싱글턴은 socket bind 락 — PG advisory lock은 v3.7.142 무한 대기 사고
#     전례, 파일 락은 좀비 잔류 문제. 소켓은 프로세스 사망 시 OS가 즉시 해제.
#   - [제약] run_loop는 daemon=True 스레드에서 호출됨 (daemons.run_heartbeat 경유).
#     블로킹 루프 허용. 자식 claude 프로세스는 사이클 내에서 완결(타임아웃 킬)되므로
#     env.child_procs에 등록하지 않는다.
#   - [불변식] 실패 태스크는 status='blocked'로 릴리즈 — 'failed'는
#     find_tasks_for_agent 제외 목록에 없어 무한 재시도 루프가 된다.
#   - [불변식] 가드(킬스위치/일일 상한/쿼터/연속 실패)는 매 사이클 DB에서 재로드 —
#     텔레그램 /auto off가 다른 프로세스에서 상태를 바꾸기 때문.
# [2026-07-18] Claude — P0 품질 게이트 2종 (deny 프로파일만으론 못 막는 사각):
#   - [WHY] claude가 성공(is_error=false) 보고해도 산출물을 데몬이 독립 검증 —
#     첫 실전 테스트에서 자동생성 파일(HIVEMIND.md) 수정 + 무검증 커밋 사고.
#   - [WHY] 구문 검증은 subprocess `python -m py_compile`가 아니라 builtin compile() —
#     frozen EXE 모드에선 sys.executable이 앱 EXE라 `-m py_compile`이 안 뜬다.
#     인프로세스 compile()은 프로즌/개발 양쪽에서 동일 동작.
#   - [WHY] 게이트 차단은 되돌림(reset) 없이 blocked 릴리즈만 — 격리 브랜치라
#     머지 안 되면 무해하고, 다음 사이클 ensure_worktree의 reset+switch -C가 청소.
# [2026-07-18] Claude — P1 리포트/발굴 개선:
#   - [P1-③] 완료 리포트에 변경 파일 목록·개수·브랜치 구조화 (머지 판단 근거 제공).
#   - [P1-④] discover_task 3소스 디스패처화: 재발사고 → 미하드닝 사고 → 표준 헤더 누락.
#     [설계결정] TODO/FIXME(노이즈)·1500줄 분할(자율 리팩터 위험)은 의도 제외 — 신호
#     높은 소스만. discover_task 시그니처에 project_root 추가(헤더 스캔용 ls-files).
# [2026-07-20] Claude — 싱글턴 stale-takeover (사고 e9a48f66 후속):
#   - [WHY] 구버전/hung 인스턴스가 락 포트 9019를 영원히 물면 dev auto가 시작조차 못 함.
#     run_loop이 bind 실패 시 즉시 return(포기)하던 걸 재시도 루프로 — 주인이 놓는 즉시 인수.
#   - [WHY] _singleton_watchdog(별도 스레드): 메인 루프가 WATCHDOG_STALL_SEC(>태스크 최대치)
#     이상 정지하면 소켓만 close해 락 반납. os._exit(앱 통째 종료)는 과잉이라 배제.
# ─────────────────────────────────────────────────────────────────────────────
import json
import socket
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# ── 상수 (가드 기본값) ───────────────────────────────────────────────────────
STATE_KEY = 'heartbeat'
AGENT_ID = 'claude-auto'
NOTIFY_CHANNEL = 'hive_heartbeat'
POLL_INTERVAL_SEC = 600          # LISTEN 유실 대비 안전망 폴링
DISABLED_RECHECK_SEC = 30        # 꺼짐 상태에서 킬스위치 재확인 주기
TASK_TIMEOUT_SEC = 1800          # claude -p 행업 시 프로세스 트리 킬
DAILY_LIMIT = 5                  # 하루 최대 수행 태스크 수
QUOTA_LIMIT_PCT = 80.0           # 플랜 사용률 임계 — 초과 시 사이클 스킵
FAIL_LIMIT = 2                   # 연속 실패 시 자율 모드 자동 정지
DISCOVERED_CAP = 100             # 자가 발굴 중복 방지 시그니처 보관 상한
OUTBOX_CAP = 30                  # 텔레그램 미소비 보고 보관 상한
# [WHY] 9019 고정 — 서버 HTTP(9000-9007)·오피스(9010번대)와 겹치지 않는 대역.
# dev 서버와 설치본 EXE가 동시에 떠도 heartbeat는 딱 하나만 살아남게 하는 락.
SINGLETON_LOCK_PORT = 9019
SINGLETON_RETRY_SEC = 60         # bind 실패(다른 인스턴스 점유) 시 포기하지 않고 재시도하는 주기
WATCHDOG_CHECK_SEC = 60          # 자가반납 워치독 점검 주기
# [불변식] 반드시 TASK_TIMEOUT_SEC보다 커야 한다 — 정상 태스크 수행 중(run_claude_task,
#   최대 1800s)엔 last_progress가 갱신되지 않으므로, 이 값이 그보다 작으면 30분짜리
#   정상 작업을 hung으로 오판해 락을 반납→다른 인스턴스가 인수→이중 heartbeat 실행 사고.
# [WHY] keepalive(v3.7.270, pg_base)가 죽은 DB 소켓 hang을 ~60초 내 self-heal 하는 1차
#   방어라, 이 워치독은 keepalive가 못 잡는 다른 hang을 위한 백스톱 — 공격적 짧은 값 불필요.
WATCHDOG_STALL_SEC = TASK_TIMEOUT_SEC + 600   # =2400s(40분)

# [P0 게이트] 오토가 건드리면 안 되는 자동생성/산출물 경로 조각 (커밋 파일 경로를
# lower-case로 substring 매칭). deny 프로파일(Bash 접두)로는 Edit/Write 도구를 못 막아
# 여기서 커밋 후 결정적으로 검사한다. 손으로 관리하는 문서(PROJECT_MAP 등)는 제외 —
# 과잉 차단 시 정당한 문서 태스크까지 blocked 되므로 '명백한 생성물'만 등재.
FORBIDDEN_PATH_MARKERS = (
    'dist/',              # 번들 산출물 (vibe-view/dist 등)
    'hivemind.md',        # generate_hivemind_doc.py 자동생성 — 수정해도 재생성 시 덮어써짐
    '.min.js', '.min.css',
    'package-lock.json', 'uv.lock', 'poetry.lock',
    '_version.py',        # 배포 파이프라인(vibe-release) 전용 — 자율 버전 증가 금지
)

# ── 샌드박스 권한 프로파일 ───────────────────────────────────────────────────
# [WHY] 파일로 배포하지 않고 상수→런타임 materialize — .ai_monitor/config/ 신규
# 디렉토리를 만들면 spec datas + CI --add-data 양쪽 갱신이 필요(v3.7.215~218 사고).
# data_dir은 이미 런타임 쓰기 경로라 frozen 모드에서도 안전.
# [제약] deny 규칙은 Bash 접두 매칭 — 워크트리 밖 파일 파손은 defaultMode가
# cwd 밖 편집을 자동 승인하지 않는 성질 + 워크트리 격리로 막는다.
SANDBOX_SETTINGS = {
    "permissions": {
        "defaultMode": "acceptEdits",
        "deny": [
            "Bash(git push:*)",
            "Bash(git push)",
            "Bash(gh pr merge:*)",
            "Bash(git merge:*)",
            "Bash(git rebase:*)",
            "Bash(git tag:*)",
            "Bash(git reset --hard:*)",
            "Bash(git worktree:*)",
            "Bash(rm -rf:*)",
            "Bash(rmdir:*)",
            "Bash(Remove-Item:*)",
            "Bash(del:*)",
            "Bash(pyinstaller:*)",
        ],
    },
}

# 자율 태스크 수행 프롬프트 골격 — {title}/{description} 치환.
# [WHY] push·버전·머지 금지는 deny 프로파일이 강제하지만, 지시문에도 명시해
# 모델이 차단당하며 헤매는 낭비 턴을 줄인다 (이중벽의 안내판 역할).
TASK_PROMPT = """[자율 모드] 아래 태스크를 이 워크트리 안에서만 수행하라.

## 태스크
제목: {title}
내용:
{description}

## 제약 (위반 시 도구가 차단됨)
- 이 워크트리(cwd) 밖의 파일을 수정하지 마라.
- git push / merge / rebase / tag / 버전 증가 / 릴리즈 금지 — 커밋까지만.
- 완료 시 Conventional Commits 형식(한글 3단 본문)으로 커밋하라.
- 마지막 출력은 3줄 요약: 수정 파일 / 원인(Why) / 수정 내용(How).
"""


# ── 상태 모델 (hive_state KV 재사용) ─────────────────────────────────────────

def _default_state() -> dict:
    return {
        'enabled': False,
        'daily_date': '',
        'daily_count': 0,
        'consecutive_fails': 0,
        'discovered': [],        # 자가 발굴한 incident 시그니처 (중복 재제안 방지)
        'outbox': [],            # 텔레그램 봇이 소비하는 보고 큐 [{ts, text}]
        'last_cycle_at': '',
        'last_result': '',
    }


def load_hb_state() -> dict:
    from src.pg_store import load_state
    raw = load_state(STATE_KEY, default=None)
    state = _default_state()
    if isinstance(raw, dict):
        state.update(raw)
    return state


def save_hb_state(state: dict) -> None:
    from src.pg_store import save_state
    save_state(STATE_KEY, state)


def _report(state: dict, text: str) -> None:
    """보고 1건을 아웃박스에 적재 — 소비자는 텔레그램 봇(별도 프로세스, hive_state 폴링)."""
    state['outbox'] = (state.get('outbox') or [])[-(OUTBOX_CAP - 1):]
    state['outbox'].append({'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'text': text[:1500]})
    print(f"[heartbeat] {text}")


# ── 가드 계층 ────────────────────────────────────────────────────────────────

def _quota_pct() -> float:
    """플랜 사용률(%) 최대값. 조회 불가 시 -1 — 불가를 초과로 오판해 영구 정지되는 것 방지."""
    try:
        from src.claude_quota import get_claude_quota
        q = get_claude_quota()
        if not q.get('available'):
            return -1.0
        pcts = []
        for key in ('five_hour', 'seven_day'):
            win = q.get(key) or {}
            if isinstance(win.get('utilization'), (int, float)):
                pcts.append(float(win['utilization']))
        return max(pcts) if pcts else -1.0
    except Exception:
        return -1.0


def guard_check(state: dict) -> tuple[bool, str]:
    """사이클 진입 가드. (통과 여부, 사유). 일일 카운터는 날짜 바뀌면 여기서 리셋."""
    if not state.get('enabled'):
        return False, 'disabled'
    today = date.today().isoformat()
    if state.get('daily_date') != today:
        state['daily_date'] = today
        state['daily_count'] = 0
    if int(state.get('daily_count', 0)) >= DAILY_LIMIT:
        return False, f'daily_limit({DAILY_LIMIT})'
    if int(state.get('consecutive_fails', 0)) >= FAIL_LIMIT:
        # [불변식] 연속 실패 정지는 enabled 자체를 내림 — /auto on으로만 재개 (자동 재개 금지)
        state['enabled'] = False
        return False, f'fail_limit({FAIL_LIMIT})'
    pct = _quota_pct()
    if pct >= QUOTA_LIMIT_PCT:
        return False, f'quota({pct:.0f}%)'
    return True, ''


# [①-active_here] 이 프로세스가 싱글턴 락(9019)을 실제로 쥐고 있는지 공개하는 창.
# run_loop의 지역 holder를 모듈 스코프에 참조로 걸어, /api/heartbeat/status가 '이 인스턴스가
# auto 실행 주체인지'를 판별할 수 있게 한다. loop_beat_at은 DB 공유값이라 락을 못 쥔
# 인스턴스에서도 (주인이 갱신해) 신선해 보이므로 그것만으론 '나만 대기 중'을 구분 못 함 —
# 프로세스-로컬 소켓 소유 여부가 유일한 확실한 신호다.
_run_holder: dict | None = None


def is_active_holder() -> bool:
    """이 프로세스가 싱글턴 락을 쥔 auto 실행 주체이면 True.

    [하위호환] 데몬 run_loop이 아직 안 돌았으면(_run_holder=None) True로 본다 —
    단일 인스턴스 환경에선 '내가 곧 주체'가 기본값이라 대기 배지를 잘못 띄우지 않는다.
    """
    if _run_holder is None:
        return True
    return _run_holder.get('sock') is not None


def _acquire_singleton() -> socket.socket | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', SINGLETON_LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        return None


# ── 워크트리 샌드박스 ────────────────────────────────────────────────────────

def _git(worktree_or_root: Path, *args: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        r = proc.run(
            ['git', '-C', str(worktree_or_root), *args],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout,
        )
        return r.returncode == 0, (r.stdout or r.stderr or '').strip()
    except Exception as e:
        return False, str(e)


def worktree_path(project_root: Path) -> Path:
    return project_root.parent / (project_root.name + '-auto')


def ensure_worktree(project_root: Path, task_id: str) -> Path | None:
    """영구 워크트리 보장 + 태스크 전용 브랜치 준비. 실패 시 None.

    [WHY] switch -C(강제 재생성) — 같은 태스크 재실행 시 이전 부분 작업을 버리고
    main에서 새로 시작. 실패 태스크는 blocked로 재시도 안 되므로 유실 위험 없음.
    [불변식] reset --hard + clean -fd는 데몬만 수행 (에이전트에겐 deny) —
    이전 사이클의 더티 잔류물이 다음 태스크 커밋에 섞이는 오염 방지.
    """
    wt = worktree_path(project_root)
    if not wt.exists():
        ok, out = _git(project_root, 'worktree', 'add', str(wt), '-b', 'auto/base', 'main')
        if not ok and 'already exists' not in out:
            # auto/base 브랜치만 남은 반쪽 상태 재시도 (worktree remove 후 재생성은 위험 — 수동 개입 유도)
            ok2, out2 = _git(project_root, 'worktree', 'add', str(wt), 'auto/base')
            if not ok2:
                print(f"[heartbeat] worktree 생성 실패: {out} / {out2}")
                return None
    _git(wt, 'reset', '--hard')
    _git(wt, 'clean', '-fd')
    ok, out = _git(wt, 'switch', '-C', f'auto/task-{task_id}', 'main')
    if not ok:
        print(f"[heartbeat] 브랜치 준비 실패: {out}")
        return None
    return wt


def materialize_settings(data_dir: Path) -> Path:
    # [과거사고] 상대 data_dir을 그대로 쓰면 subprocess cwd(워크트리) 기준으로
    # 해석돼 settings 미발견 → claude 즉시 exit 1 (2026-07-17 스모크에서 실측)
    path = (data_dir / 'heartbeat_settings.json').resolve()
    path.write_text(json.dumps(SANDBOX_SETTINGS, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


# ── claude -p 실행기 ─────────────────────────────────────────────────────────

def run_claude_task(worktree: Path, task: dict, settings_path: Path,
                    timeout: int = TASK_TIMEOUT_SEC) -> tuple[bool, str]:
    """워크트리 안에서 claude를 1회 실행. (성공 여부, 결과 요약).

    [제약] shell=True 필수 — Windows에서 claude.CMD는 cmd.exe 경유해야 함
    (agent_api._build_chat_cmd와 동일 제약). 타임아웃 시 taskkill /T로 트리 전체 킬 —
    shell=True는 cmd.exe가 부모라 proc.kill()만으로는 claude 자식이 고아로 남는다.
    """
    prompt = TASK_PROMPT.format(
        title=str(task.get('title', ''))[:200],
        description=str(task.get('description', ''))[:4000],
    )
    # [과거사고] 프롬프트를 -p 인자로 주면 shell=True 경유 cmd.exe가 멀티라인 인자를
    # 첫 줄에서 절단(2026-07-17 스모크 실측: 태스크 본문 증발) → 반드시 stdin 파이프로.
    cmd = ['claude', '--output-format', 'json', '--settings', str(settings_path), '-p']
    try:
        # [WHY] shell=True면 cmd.exe가 부모 — proc.popen이 CREATE_NO_WINDOW를 주입해
        # 대기 태스크 처리마다 백그라운드 cmd 창이 번쩍이는 걸 막는다(데몬은 무음 전제).
        # 지역변수명은 child로 — 모듈 proc(래퍼)와 충돌 방지.
        child = proc.popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(worktree), shell=True, text=True, encoding='utf-8', errors='replace',
        )
        try:
            out, _ = child.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.run(['taskkill', '/F', '/T', '/PID', str(child.pid)],
                     capture_output=True)
            return False, f'타임아웃({timeout}s) — 프로세스 킬'
    except Exception as e:
        return False, f'실행 실패: {e}'
    try:
        payload = json.loads((out or '').strip() or '{}')
        result_text = str(payload.get('result', ''))[:2000]
        is_error = bool(payload.get('is_error')) or child.returncode != 0
        return (not is_error), (result_text or f'exit={child.returncode}')
    except json.JSONDecodeError:
        # --output-format json인데 JSON이 아니면 비정상 종료로 간주
        return False, f'출력 파싱 실패 (exit={child.returncode}): {(out or "")[:300]}'


def _commit_delta(worktree: Path) -> str:
    ok, out = _git(worktree, 'log', '--oneline', 'main..HEAD')
    if not ok or not out:
        return '커밋 없음'
    lines = out.splitlines()
    return f'{len(lines)}개 커밋: ' + '; '.join(lines[:3])


# ── P0 품질 게이트 (커밋 산출물 독립 검증) ───────────────────────────────────

def _changed_files(worktree: Path) -> list[str]:
    """main 대비 이 브랜치가 바꾼 파일 경로 목록 (커밋된 것 기준)."""
    ok, out = _git(worktree, 'diff', '--name-only', 'main..HEAD')
    return out.splitlines() if ok and out else []


def _forbidden_changes(changed: list[str]) -> list[str]:
    """변경 파일 중 자동생성/금지 경로에 걸리는 것 반환 (blocked 사유용)."""
    bad = []
    for p in changed:
        pl = p.replace('\\', '/').lower()
        if any(marker in pl for marker in FORBIDDEN_PATH_MARKERS):
            bad.append(p)
    return bad


def _syntax_gate(worktree: Path, changed: list[str]) -> tuple[bool, str]:
    """변경된 .py 파일을 builtin compile()로 파싱 검증. (통과, 실패 사유).

    [WHY] subprocess가 아닌 인프로세스 compile — frozen EXE에선 `python -m py_compile`이
    sys.executable=앱 EXE라 동작 안 함. compile()은 import 부작용도 없어 안전(파싱만).
    """
    for p in changed:
        if not p.endswith('.py'):
            continue
        fp = worktree / p
        if not fp.exists():   # 삭제/이동된 파일은 검증 대상 아님
            continue
        try:
            compile(fp.read_text(encoding='utf-8', errors='replace'), str(fp), 'exec')
        except SyntaxError as e:
            return False, f'{p}:{e.lineno} {e.msg}'
    return True, ''


def _quality_gate(worktree: Path) -> str:
    """커밋 후 산출물 검증. 통과면 '' , 실패면 blocked 사유 문자열.

    [불변식] 순서 고정 — 금지경로 먼저(값싼 검사), 통과 시 구문 검증. 둘 중 하나라도
    걸리면 즉시 사유 반환. 되돌림은 호출부가 하지 않음 (헤더 [2026-07-18] 참조).
    """
    changed = _changed_files(worktree)
    if not changed:
        return '커밋 산출물 없음 — 변경 파일 0'   # claude가 아무것도 안 함 = 실패로 간주
    bad = _forbidden_changes(changed)
    if bad:
        return f'자동생성/금지 경로 수정: {", ".join(bad[:5])}'
    ok, reason = _syntax_gate(worktree, changed)
    if not ok:
        return f'구문 오류: {reason}'
    return ''


# ── 자가 발굴 (source='self') ────────────────────────────────────────────────

def _record_discovered(state: dict, sig: str) -> None:
    """발굴 시그니처를 단일 풀에 영구 보관 — 사용자가 태스크를 지워도 무한 재제안 방지.

    [불변식] 모든 소스(재발/미하드닝/헤더)가 이 한 풀을 공유 — 소스별로 나누면
    같은 파일/사고가 소스 경계를 넘나들며 중복 제안될 수 있다.
    """
    state['discovered'] = ((state.get('discovered') or []) + [sig])[-DISCOVERED_CAP:]


def _discover_incident(project_id: str, state: dict, recurrence_min: int,
                       unhardened: bool) -> dict | None:
    """incident_ledger에서 하드닝 태스크 1건 발굴.

    unhardened=True: 아직 fix_description이 없는 미하드닝 사고 (재발 안 했어도).
    [WHY] root_cause NOT NULL 필터 — 분석조차 안 된 일회성 에러까지 태스크화하면
    노이즈 폭주. '원인은 규명됐는데 재발방지책만 없는' 건으로 한정해 신호 유지.
    """
    from src.pg_base import _sql_text, query_rows
    from src.pg_store import save_task
    seen = set(state.get('discovered') or [])
    proj_filter = f"AND project_id = {_sql_text(project_id)}" if project_id else ''
    unhardened_filter = (
        "AND (fix_description IS NULL OR fix_description = '') "
        "AND root_cause IS NOT NULL AND root_cause <> ''"
    ) if unhardened else ''
    rows = query_rows(f"""
        SELECT error_signature, LEFT(error_text, 300) AS error_text,
               root_cause, fix_description, recurrence_count
        FROM incident_ledger
        WHERE recurrence_count >= {int(recurrence_min)} {unhardened_filter} {proj_filter}
        ORDER BY last_seen_at DESC LIMIT 10;
    """)
    kind = '미하드닝 사고' if unhardened else '재발 사고'
    for row in rows:
        sig = str(row.get('error_signature', ''))
        if not sig or sig in seen:
            continue
        _record_discovered(state, sig)
        occurred = ('아직 재발방지책이 없는' if unhardened
                    else f"재발 {row.get('recurrence_count')}회")
        task = {
            'id': f'auto-{sig[:16]}-{int(time.time())}',
            'title': f"[자가발굴] {kind} 하드닝: {str(row.get('root_cause', ''))[:60]}",
            'description': (
                f"{occurred} 사고의 재발 방지 가드/테스트를 추가하라.\n\n"
                f"에러: {row.get('error_text', '')}\n"
                f"근본 원인: {row.get('root_cause', '')}\n"
                f"기존 수정법: {row.get('fix_description', '') or '(없음 — 미하드닝)'}\n\n"
                f"할 일: 같은 실수를 커밋 전에 잡아낼 회귀 테스트 또는 코드 가드를 추가하고, "
                f"불변식 주석([과거사고])을 해당 지점에 남겨라."
            ),
            'assigned_to': AGENT_ID, 'priority': 'medium',
            'created_by': AGENT_ID, 'source': 'self', 'project_id': project_id,
        }
        return save_task(task, project_id=project_id, source='self')
    return None


# 표준 헤더(규칙 #5) 존재 판정 마커 — 표준형(FILE:/DESCRIPTION:)과 박스형(📄 파일명) 모두.
_HEADER_MARKERS = ('FILE:', 'DESCRIPTION:', '파일명')
# 헤더 발굴 제외 — 자동생성/서드파티/관례상 헤더 불필요 파일.
_HEADER_SKIP = ('dist/', 'migrations/', 'node_modules/', '/test', 'test_',
                '__init__.py', 'setup.py', 'conftest.py')


def _discover_missing_header(project_root: Path, project_id: str, state: dict) -> dict | None:
    """표준 파일 헤더가 없는 추적 .py 1건 발굴 (규칙 #5 자동 이행).

    [제약] 추적 파일(git ls-files)만 대상 — dist/ 등 비추적 산출물은 애초 제외.
    첫 파일 600자만 읽어 마커 검사 → 없으면 태스크화하고 즉시 반환(early-exit).
    """
    from src.pg_store import save_task
    seen = set(state.get('discovered') or [])
    ok, out = _git(project_root, 'ls-files', '*.py')
    if not ok or not out:
        return None
    for rel in out.splitlines():
        rl = rel.replace('\\', '/').lower()
        if any(s in rl for s in _HEADER_SKIP):
            continue
        # [불변식] 게이트 금지경로(_version.py 등)는 발굴 제외 — 태스크화해도 claude
        # 수정 후 _quality_gate가 blocked 처리해 헛사이클+연속실패만 유발한다.
        if _forbidden_changes([rel]):
            continue
        sig = f'header:{rel}'
        if sig in seen:
            continue
        try:
            head = (project_root / rel).read_text(encoding='utf-8', errors='replace')[:600]
        except Exception:
            continue
        if any(m in head for m in _HEADER_MARKERS):
            continue   # 헤더 있음
        _record_discovered(state, sig)
        task = {
            'id': f'auto-hdr-{abs(hash(rel)) % 10_000_000}-{int(time.time())}',
            'title': f"[자가발굴] 표준 헤더 추가: {rel}",
            'description': (
                f"{rel} 파일 상단에 규칙 #5 표준 헤더(FILE/DESCRIPTION/REVISION HISTORY)를 추가하라.\n"
                f"DESCRIPTION은 이 파일의 역할을 LLM이 1초 안에 판단하게 1~2줄로. "
                f"코드 로직은 절대 변경 금지 — 헤더 주석만 추가하고 커밋하라."
            ),
            'assigned_to': AGENT_ID, 'priority': 'low',
            'created_by': AGENT_ID, 'source': 'self', 'project_id': project_id,
        }
        return save_task(task, project_id=project_id, source='self')
    return None


def discover_task(project_root: Path, project_id: str, state: dict) -> dict | None:
    """자가 발굴 디스패처 — 소스 우선순위대로 첫 성공 1건 반환.

    우선순위: ①재발 사고(오탐 최소) → ②미하드닝 사고 → ③표준 헤더 누락.
    [설계결정 2026-07-18] TODO/FIXME 스캔(노이즈)·1500줄 분할(자율 리팩터 위험)은
    의도적으로 제외 — 자율 데몬이 밤새 잡일/사고를 양산하지 않게 신호 높은 소스만.
    """
    return (
        _discover_incident(project_id, state, recurrence_min=2, unhardened=False)
        or _discover_incident(project_id, state, recurrence_min=1, unhardened=True)
        or _discover_missing_header(project_root, project_id, state)
    )


# ── 사이클 + 메인 루프 ───────────────────────────────────────────────────────

def _cycle(project_root: Path, data_dir: Path, project_id: str) -> None:
    """1사이클: 가드 → 체크아웃(없으면 발굴) → 샌드박스 실행 → 릴리즈 + 보고."""
    from src.pg_experience import insert_pg_log
    from src.pg_store import add_task_comment, atomic_checkout, find_tasks_for_agent, release_checkout

    state = load_hb_state()
    ok, reason = guard_check(state)
    if not ok:
        if reason.startswith('fail_limit'):
            _report(state, f'⛔ 연속 실패 {FAIL_LIMIT}회 — 자율 모드 자동 정지. /auto on으로 재개')
        save_hb_state(state)   # 날짜 리셋/자동 정지 반영
        return

    pending = find_tasks_for_agent(AGENT_ID, project_id)
    task = pending[0] if pending else discover_task(project_root, project_id, state)
    if not task:
        state['last_cycle_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        state['last_result'] = 'idle'
        save_hb_state(state)
        return

    task_id = str(task.get('id', ''))
    checked = atomic_checkout(AGENT_ID, task_id)
    if not checked:
        save_hb_state(state)
        return

    wt = ensure_worktree(project_root, task_id)
    if not wt:
        release_checkout(task_id, 'blocked', 'worktree 준비 실패')
        state['consecutive_fails'] = int(state.get('consecutive_fails', 0)) + 1
        _report(state, f'❌ [{task_id}] worktree 준비 실패')
        save_hb_state(state)
        return

    settings_path = materialize_settings(data_dir)
    _report(state, f"🤖 자율 작업 시작: {task.get('title', '')[:80]}")
    save_hb_state(state)

    success, summary = run_claude_task(wt, checked, settings_path)
    delta = _commit_delta(wt)

    # [P0] claude가 성공 보고해도 커밋 산출물을 데몬이 독립 검증 — 자동생성 파일
    # 수정/구문 오류를 done으로 통과시키지 않는다. 게이트 실패는 실행 실패와 동급 처리.
    if success:
        gate_reason = _quality_gate(wt)
        if gate_reason:
            success = False
            summary = f'[게이트 차단] {gate_reason}\n(claude 보고 요약: {summary[:300]})'

    # [P1-③] 완료 리포트 구조화 — 텔레그램/아웃박스 소비자가 머지 판단에 필요한
    # '무엇이 바뀌었나'를 한눈에. changed는 게이트가 이미 커밋을 검증한 후라 신뢰 가능.
    changed = _changed_files(wt)
    files_line = (
        f"📝 변경 {len(changed)}개: {', '.join(changed[:8])}"
        + (f" 외 {len(changed) - 8}개" if len(changed) > 8 else '')
    ) if changed else '📝 변경 파일 없음'
    title60 = task.get('title', '')[:60]

    state = load_hb_state()   # 실행 중 /auto off 등 외부 변경 반영 후 갱신
    if success:
        state['daily_count'] = int(state.get('daily_count', 0)) + 1
        state['consecutive_fails'] = 0
        release_checkout(task_id, 'done', summary[:2000])
        _report(state, (
            f"✅ [{title60}] 완료\n"
            f"📦 {delta}\n{files_line}\n"
            f"🌿 브랜치 auto/task-{task_id} (머지는 사람 판단)\n"
            f"{summary[:300]}"
        ))
    else:
        state['consecutive_fails'] = int(state.get('consecutive_fails', 0)) + 1
        # [불변식] 'failed' 금지 — find_tasks_for_agent가 다시 집어 무한 재시도됨
        release_checkout(task_id, 'blocked', summary[:2000])
        _report(state, (
            f"❌ [{title60}] 실패/차단\n{files_line}\n"
            f"사유: {summary[:350]}"
        ))
    state['last_cycle_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    state['last_result'] = 'done' if success else 'fail'
    save_hb_state(state)

    add_task_comment(task_id, AGENT_ID, summary[:1000], project_id)
    insert_pg_log(agent=AGENT_ID, task=f"heartbeat: {task.get('title', '')[:100]}",
                  status='success' if success else 'error', project_id=project_id,
                  metadata={'task_id': task_id, 'commits': delta})


def _wait_for_wake(listen_state: dict, timeout_sec: float) -> None:
    """NOTIFY 수신 또는 timeout까지 대기 (하이브리드). LISTEN 실패 시 sleep 폴백.

    [제약] pg_base 공유 커넥션을 쓰지 않고 전용 커넥션 — LISTEN은 세션 소속이라
    공유 커넥션의 재연결/트랜잭션에 구독이 소리 없이 증발한다.
    """
    conn = listen_state.get('conn')
    # [방어] 죽은 커넥션(절전/네트워크 단절 후)이면 재생성 유도 — stale conn으로 select가
    # 영원히 안 깨는 hang(15시간 사고)을 차단한다.
    if conn is not None and getattr(conn, 'closed', 0):
        conn = None
        listen_state['conn'] = None
    if conn is None:
        try:
            import psycopg2
            from src import pg_base
            # [불변식] pg_base와 동일한 keepalive 적용 — LISTEN 전용 커넥션도 절전발 죽은
            #   소켓에서 poll()이 hang 나지 않게(closed 플래그가 반영 안 되는 half-open 대비).
            conn = psycopg2.connect(
                host='127.0.0.1', port=int(pg_base.PG_PORT), user=pg_base.PG_USER,
                dbname=pg_base.PG_DB, **pg_base._CONN_RESILIENCE_KW,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'LISTEN {NOTIFY_CHANNEL};')
            listen_state['conn'] = conn
        except Exception:
            listen_state['conn'] = None
            time.sleep(min(timeout_sec, 60))
            return
    try:
        import select
        # [방어] timeout을 60초로 캡 — 죽은 conn이 select를 안 깨워도 최대 60초 내 run_loop로
        # 복귀해 loop_beat 갱신 + conn 재평가한다. POLL_INTERVAL(600)은 상한일 뿐, 태스크 할당
        # 즉시성은 NOTIFY가 담당하므로 짧은 캡이 즉시성을 해치지 않는다.
        select.select([conn], [], [], min(timeout_sec, 60.0))
        conn.poll()
        conn.notifies.clear()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        listen_state['conn'] = None


def _singleton_watchdog(holder: dict) -> None:
    """홀더의 메인 루프 진행(last_progress)을 감시 — WATCHDOG_STALL_SEC 이상 정지하면
    싱글턴 소켓만 close해 락을 반납한다 (다른 정상 인스턴스가 인수하도록).

    [WHY] os._exit로 프로세스를 죽이지 않는다 — heartbeat는 앱의 여러 데몬 스레드 중
      하나일 뿐이라, 그거 하나 hung 때문에 멀쩡한 HTTP 서버(9000)/UI까지 나가면 과잉.
      소켓만 놓으면 하드 상호배제(살아있는 소켓 1개)는 유지되고 앱 본체는 산다.
    [과거사고 e9a48f66 2026-07-20] 구버전 설치본(v3.7.269)이 절전발 죽은 PG 소켓 hang으로
      싱글턴 락을 23시간 물고 죽어, dev auto가 시작조차 못 했다 — 이 워치독이 그 hang을
      스스로 반납해 재발을 막는다(단 keepalive가 1차 방어, 이건 백스톱).
    [제약] 별도 daemon 스레드 — 메인 루프가 C레벨(recv 등)에 블록돼도 이 스레드는 돈다.
    [불변식] last_progress는 time.monotonic() 기준 (벽시계/절전 보정 무관). 소켓 close(반납)는
      이 워치독만, bind(재획득)는 메인 루프만 — 상호배제 담당은 언제나 소켓 1개.
      holder 딕트 접근은 GIL 하 원자적 get/set만 사용하므로 별도 락 불필요.
    """
    while not holder.get('stop'):
        time.sleep(WATCHDOG_CHECK_SEC)
        if holder.get('sock') is None:
            continue   # 이미 반납/미보유 — 메인 루프가 재획득할 때까지 대기
        age = time.monotonic() - holder.get('last_progress', time.monotonic())
        if age > WATCHDOG_STALL_SEC:
            sock = holder.get('sock')
            holder['sock'] = None   # 먼저 무효화 (재획득 경로가 소켓 없음을 즉시 관측)
            try:
                sock.close()
            except Exception:
                pass
            print(f"[heartbeat] 자기 루프 {int(age)}s 정지 감지 — 싱글턴 락 반납 "
                  f"(다른 인스턴스 인수 허용). hung 스레드는 leaked 가능 — 앱 재시작 권장")


def run_loop(get_project_root, data_dir: Path, get_project_id) -> None:
    """데몬 진입점 — daemons.run_heartbeat가 daemon 스레드에서 호출.

    get_project_root/get_project_id: callable — 프로젝트 전환(set_project_db)
    반영을 위해 매 사이클 재평가 (DaemonEnv late-binding 계약과 동형).

    [2026-07-20] 락 재시도 + 자가반납 워치독 — 구버전/hung 인스턴스가 싱글턴 포트를
      영원히 물어 dev auto가 시작조차 못 하던 문제(사고 e9a48f66) 방지.
    """
    holder: dict = {'sock': None, 'last_progress': time.monotonic(), 'stop': False}
    global _run_holder
    _run_holder = holder   # [①] is_active_holder가 이 프로세스의 락 보유를 관측하는 통로
    # [변경] bind 실패 시 return(즉시 포기) 금지 → 재시도. 현재 주인이 락을 놓는 순간
    #   (앱 종료/워치독 반납/270 업데이트 재시작) 대기 인스턴스가 SINGLETON_RETRY_SEC 내 인수.
    _warned = False
    while holder['sock'] is None:
        holder['sock'] = _acquire_singleton()
        if holder['sock'] is None:
            if not _warned:
                print(f"[heartbeat] 다른 인스턴스가 락(port {SINGLETON_LOCK_PORT}) 점유 중 — "
                      f"{SINGLETON_RETRY_SEC}s 간격 재시도(주인이 놓는 즉시 인수)")
                _warned = True
            time.sleep(SINGLETON_RETRY_SEC)
    print("[heartbeat] 자율 루프 시작 (기본 꺼짐 — /auto on으로 활성화)")
    threading.Thread(target=_singleton_watchdog, args=(holder,), daemon=True).start()
    listen_state: dict = {'conn': None}
    while True:
        try:
            # [변경] 워치독이 락을 반납했으면(hung 판정) 재획득 후에만 진행 — 소켓 없는 채
            #   heartbeat를 돌리면 다른 인스턴스와 이중 실행 위험. 재획득은 메인 스레드 전담.
            if holder['sock'] is None:
                holder['sock'] = _acquire_singleton()
                if holder['sock'] is None:
                    time.sleep(SINGLETON_RETRY_SEC)
                    continue
            # [계측] monotonic 진행 마커 — 워치독의 hung 판정 기준(벽시계 loop_beat_at과 별개).
            holder['last_progress'] = time.monotonic()
            state = load_hb_state()
            # [계측] liveness 하트비트 — enabled/게이트와 무관하게 '스레드가 돈다'를 기록한다.
            # [과거사고] last_cycle_at은 쿼터/enabled 게이트에 막히면 안 갱신돼 '멈춤(hang)'과
            #   '정상 대기'를 구분 못 함 → 데몬 스레드가 _wait_for_wake의 죽은 LISTEN conn에
            #   15시간 갇혔는데 아무도 몰랐다(계측 부재). loop_beat_at은 매 iteration 갱신되므로
            #   이게 멈추면 진짜 hang → stale 워치독(heartbeat status API)이 감지한다.
            state['loop_beat_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            save_hb_state(state)
            if not state.get('enabled'):
                time.sleep(DISABLED_RECHECK_SEC)
                continue
            _cycle(Path(get_project_root()), data_dir, str(get_project_id() or ''))
            _wait_for_wake(listen_state, POLL_INTERVAL_SEC)
        except Exception as e:
            # [WHY] 루프는 어떤 예외에도 죽지 않는다 — 데몬 스레드 재시작 수단이 없음
            print(f"[heartbeat] 사이클 예외 (루프 계속): {e}")
            time.sleep(60)
