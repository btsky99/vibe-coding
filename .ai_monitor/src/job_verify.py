"""
FILE: src/job_verify.py
DESCRIPTION: 일감 검수 — Phase 12 Task 54(git 실측 수집).
             "무엇이 바뀌었나"를 **저장소에서 직접** 읽는다. 에이전트에게 묻지 않는다.

[🔴 왜 자기신고를 안 쓰는가]
  2026-08-12 실측: na2js 는 `listener: running`(정상)이라고 보고하면서 23시간 동안
  아무것도 배달하지 않았다. 상태를 스스로 적는 주체는 자기가 고장난 것을 모른다.
  git 은 다르다 — 커밋과 diff 는 파일 시스템이 증명하며 꾸밀 수 없다.
  그래서 카드의 뼈대는 여기서 나오는 값이고, 에이전트의 self_report 는 라벨일 뿐이다.

[제약] 이 모듈은 **판정만** 한다. 고치지 않는다. 검수가 코드를 손대기 시작하면
  "검수를 통과한 코드"와 "검수가 만든 코드"가 섞여 무엇을 승인하는지 알 수 없게 된다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성 — collect_diff. Task 53 의 완료 조건(결과가 job 에 남는가)이
                     이 함수에 걸려 있어 계획보다 앞당겨 구현.
"""
from __future__ import annotations

import subprocess


def _git(args: list[str], cwd: str, timeout: int = 20) -> tuple[bool, str]:
    """git 한 번 실행. (성공, 표준출력).

    [🔴 subprocess.run 을 직접 쓰지 말 것] 콘솔 숨김은 OS 기본이 아니다 — 그냥 부르면
      검은 cmd 창이 번쩍인다(d423a7d 사고). infra.proc 이 단일 소스다.
    """
    try:
        from infra.proc import run as proc_run
    except Exception:                                          # noqa: BLE001
        proc_run = subprocess.run
    try:
        out = proc_run(['git', *args], cwd=cwd, capture_output=True,
                       text=True, timeout=timeout)
        return out.returncode == 0, (out.stdout or '')
    except Exception:                                          # noqa: BLE001
        return False, ''


def head(work_dir: str) -> str:
    """현재 커밋. 저장소가 아니면 빈 문자열."""
    ok, out = _git(['rev-parse', 'HEAD'], work_dir)
    return out.strip() if ok else ''


def collect_diff(work_dir: str, git_before: str) -> dict:
    """`git_before..HEAD` 의 실측 변경 요약.

    반환: {git_after, files, insertions, deletions, commits[], dirty}
    실패하면 빈 dict — **추정값을 만들어 넣지 않는다.** 모르는 것을 그럴듯한 숫자로
    채우면 카드가 거짓말을 하고, 그건 카드가 없는 것보다 나쁘다.

    [WHY dirty 를 같이 보나] 커밋하지 않은 변경이 남아 있으면 diff 가 실제 작업량을
      과소 표시한다. 그 사실을 숨기면 "파일 0개 수정"으로 보이면서 실은 잔뜩 고친
      상태가 되어, 승인 판단이 어긋난다.
    """
    after = head(work_dir)
    if not after:
        return {}

    result: dict = {'git_after': after, 'files': 0, 'insertions': 0,
                    'deletions': 0, 'commits': [], 'dirty': False}

    ok, status = _git(['status', '--porcelain'], work_dir)
    result['dirty'] = bool(ok and status.strip())

    if not git_before or git_before == after:
        # 커밋이 없는 경우도 정상이다(문서만 고쳤거나 아직 커밋 전). 그 사실만 남긴다.
        return result

    rng = f'{git_before}..{after}'
    ok, numstat = _git(['diff', '--numstat', rng], work_dir)
    if ok:
        files = 0
        for line in numstat.splitlines():
            parts = line.split('\t')
            if len(parts) != 3:
                continue
            files += 1
            # 바이너리 파일은 '-'로 나온다 — int() 하면 터지므로 건너뛴다.
            if parts[0].isdigit():
                result['insertions'] += int(parts[0])
            if parts[1].isdigit():
                result['deletions'] += int(parts[1])
        result['files'] = files

    ok, log = _git(['log', '--oneline', '--no-decorate', rng], work_dir)
    if ok:
        result['commits'] = [ln.strip() for ln in log.splitlines() if ln.strip()][:20]
    return result
