"""
FILE: src/job_runner.py
DESCRIPTION: 노드 쪽 일감 실행기 — Phase 12 Task 51.
             중앙에서 온 일감을 집어(claim) 게이트를 통과시킨 뒤, 이 PC 슬롯 CLI 에
             지시를 꽂고 시작 시점의 커밋 해시를 남긴다.

[🔴 여기서 프로세스를 직접 띄우지 않는다 — 1단계 범위]
  '기동'은 두 가지로 갈린다: ① 이미 떠 있는 슬롯에 지시를 꽂기 ② 없으면 새로 띄우기.
  1단계는 ①만 한다. ②는 게이트가 검증된 뒤(2단계 이후) 얹는다 —
  검증되지 않은 게이트 위에서 프로세스를 띄우기 시작하면, 되돌릴 수 없는 실행이
  게이트 버그 하나에 통째로 열린다. 그래서 지금은 슬롯이 없으면 **거부**한다.
  거부도 기록으로 남으므로 '왜 안 돌았나'는 화면에서 보인다.

[🔴 실패해도 예외를 올리지 않는다]
  이 함수는 리스너 스레드에서 불린다. 여기서 터지면 그 PC 는 **알림 수신 자체**를
  잃는다(2026-08-11 리스너가 죽어 23시간 조용했던 것과 같은 계열의 사고).
  실패는 job 상태와 이벤트로 남기고 조용히 돌아온다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성 — Phase 12 Task 51.
"""
from __future__ import annotations

import subprocess

# 한 번의 신호에 처리할 최대 건수. [WHY 상한이 필요한가] 큐가 밀려 있을 때 한 스레드가
#   전부 붙들면 리스너가 그동안 NOTIFY 를 못 받는다 — 남은 것은 다음 신호/틱에 처리된다.
_MAX_PER_TICK = 3

# 재시도 상한(Task 60 에서 정교화). 여기서도 최소한의 방어선을 둔다 — 무한 왕복은
#   중앙 DB 와 상대 CLI 를 동시에 태운다.
_MAX_RETRY = 3


def _git_head(work_dir: str) -> str:
    """작업 폴더의 현재 커밋. 저장소가 아니거나 실패하면 빈 문자열.

    [WHY 실측이 필요한가] '몇 개 고쳤냐'를 에이전트에게 물으면 그건 자기신고다.
      시작점을 남겨두면 나중에 `git_before..HEAD` 로 **저장소에서 직접** 읽을 수 있다.
      오늘(2026-08-12) na2js 가 '정상'이라 보고하며 23시간 아무것도 안 한 전례가
      자기신고를 믿으면 안 되는 이유다.
    [🔴 subprocess.run 을 직접 쓰지 말 것] 콘솔 숨김은 OS 기본이 아니라, 그냥 부르면
      검은 cmd 창이 번쩍인다. 이 함수는 일감마다 불리므로 그대로 두면 그 사고(d423a7d,
      5분 주기 작업의 창 깜빡임)를 재현한다. `infra.proc.run` 이 단일 소스다.
    """
    try:
        from infra.proc import run as proc_run
    except Exception:                                          # noqa: BLE001
        proc_run = subprocess.run          # infra 없는 경로(테스트 등) 폴백
    try:
        out = proc_run(['git', 'rev-parse', 'HEAD'], cwd=work_dir,
                       capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ''
    except Exception:                                          # noqa: BLE001
        return ''


def _fail(job: dict, why: str, detail: str = '') -> None:
    """일감을 거부 상태로 내리고 사유를 남긴다.

    [WHY rejected 로 내리나] running 에 두면 그 노드가 다음 일감을 못 집는 것처럼 보이고,
      queued 로 되돌리면 같은 이유로 즉시 다시 실패해 무한 루프가 된다.
      멈추되 **왜 멈췄는지가 보이는** 상태가 rejected 다.
    """
    from src import pg_jobs
    pg_jobs.add_event(job['id'], 'runner_fail', f'{why}: {detail}'.strip(': '))
    pg_jobs.decide_job(job['id'], approve=False, reason=why)


def _deliver(job: dict, pty_url: str) -> tuple[bool, str]:
    """일감 지시를 대상 슬롯 CLI 에 꽂는다. 오늘 고친 주입 배선을 그대로 쓴다.

    [WHY deliver_remote 를 재사용하나] 엔터 미제출·개행 두 동강·답장 경로 같은 함정을
      이미 다 통과한 경로다(v3.7.337). 새로 짜면 그 네 가지를 다시 밟는다.
    [제약] deliver_remote 는 '중앙 대화 메시지' 모양을 기대하므로 job 을 그 모양으로
      감싼다. from_node 는 발주자 — 답장 주소가 거기로 잡혀야 결과가 돌아온다.
    """
    from src import central_inject

    slot = int(job.get('target_slot') or 0)

    # [🔴 보고 방법을 **절대 경로**로 실어 보낸다]
    #   오늘 낮(2026-08-12) 같은 함정을 밟았다. 지시는 잘 꽂혔는데 답장 스크립트가
    #   상대 작업 폴더에 없어서 "답장 불가"로 끝났다 — 슬롯 CLI 는 어느 프로젝트에서든
    #   열릴 수 있으므로 cwd 를 가정하면 안 된다. 없으면 그 사실을 밝혀 적는다.
    reporter = _report_script()
    how = (f'python "{reporter}" {job["id"]} "한 줄 보고"' if reporter
           else '(보고 도구를 못 찾음 — 이 PC 설치가 깨졌을 수 있다)')

    msg = {
        'from_node': job.get('origin_node') or '',
        'from_agent': 'claude',                 # 슬롯 미상 — 노드 단위 주소로 답장된다
        'to_agent': f'claude:T{slot}' if slot else '',
        'content': f"[일감 #{job['id']}] {job.get('instruction') or ''} "
                   f"— 작업 폴더: {job.get('work_dir') or '(미지정)'}. "
                   f"끝나면 보고: {how}",
    }
    return central_inject.deliver_remote(msg, pty_url)


def _report_script() -> str:
    """이 PC 의 job_report.py 절대 경로. 못 찾으면 빈 문자열.

    [제약] 설치본은 소스가 `_appseed` 아래에, 개발본은 리포 루트에 있다.
      central_inject._reply_script 와 같은 사정이며, 같은 함정을 두 번 밟지 않으려고
      **실제로 존재하는 것만** 돌려준다 — 없는 경로를 안내하면 상대는 "파일이 없다"는
      오류만 보고 원인을 모른다.
    """
    import sys
    from pathlib import Path

    cands = []
    mei = getattr(sys, '_MEIPASS', '')
    if mei:
        cands.append(Path(mei) / '_appseed' / 'scripts' / 'job_report.py')
    if getattr(sys, 'frozen', False):
        cands.append(Path(sys.executable).parent / '_internal' / '_appseed'
                     / 'scripts' / 'job_report.py')
    cands.append(Path(__file__).resolve().parents[2] / 'scripts' / 'job_report.py')

    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return ''


def run_one(job: dict, config_file=None) -> bool:
    """집어온 일감 하나를 처리한다. 성공적으로 꽂았으면 True."""
    from api import pty_api
    from src import central_inject, pg_jobs

    # 게이트 — 작업 폴더가 허용 목록에 있는가.
    ok, why = central_inject.launch_allowed(job.get('work_dir') or '', config_file)
    if not ok:
        # [WHY 사유를 그대로 남기나] 'needs_approval' 은 사용자가 버튼 하나로 풀 수 있고
        #   'launch_disabled' 는 설정을 켜야 한다 — 화면이 무엇을 제안할지 갈린다.
        _fail(job, why, job.get('work_dir') or '(폴더 미지정)')
        return False

    if int(job.get('retry_count') or 0) > _MAX_RETRY:
        _fail(job, 'retry_exceeded', f"{job.get('retry_count')}회")
        return False

    head = _git_head(job['work_dir'])
    if head:
        pg_jobs.start_work(job['id'], head, config_file)
    else:
        # 저장소가 아니어도 일은 시킬 수 있다. 다만 diff 로 검증할 수 없으므로 남긴다 —
        # 나중에 "왜 이 일감은 검수가 비었지"를 설명해준다.
        pg_jobs.add_event(job['id'], 'no_git', job['work_dir'])

    sent, detail = _deliver(job, pty_api.get_pty_rest_url())
    if not sent:
        _fail(job, 'deliver_failed', detail)
        return False

    pg_jobs.add_event(job['id'], 'delivered', detail)
    return True


def run_pending(config_file=None) -> int:
    """이 노드 앞으로 온 일감을 처리한다. 처리 건수 반환.

    [불변식] 예외를 밖으로 내지 않는다 — 리스너가 이 함수를 부른다(파일 헤더 참조).
    """
    try:
        from src import pg_jobs
        from src.node_identity import get_node_id
        node = get_node_id(config_file)
    except Exception as exc:                                   # noqa: BLE001
        print(f'[jobs] 실행기 초기화 실패: {exc}')
        return 0

    done = 0
    for _ in range(_MAX_PER_TICK):
        try:
            job = pg_jobs.claim_job(node, config_file)
        except Exception as exc:                               # noqa: BLE001
            print(f'[jobs] 체크아웃 예외: {exc}')
            break
        if not job:
            break
        try:
            run_one(job, config_file)
        except Exception as exc:                               # noqa: BLE001
            # 여기까지 온 예외는 버그다. 그래도 리스너는 살려야 한다 — 대신 job 에
            # 흔적을 남겨 다음 세션이 원인을 찾을 수 있게 한다.
            try:
                _fail(job, 'runner_exception', str(exc)[:300])
            except Exception:                                  # noqa: BLE001
                pass
            print(f'[jobs] 실행 예외(job {job.get("id")}): {exc}')
        done += 1
    return done
