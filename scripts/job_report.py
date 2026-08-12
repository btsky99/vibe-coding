"""
FILE: scripts/job_report.py
DESCRIPTION: 슬롯 CLI 가 맡은 일감의 결과를 중앙에 되돌리는 수단 — Phase 12 Task 51.
             `python job_report.py <일감번호> "한 줄 보고"` 로 끝난다.

[🔴 왜 이 스크립트가 필요한가 — 없으면 왕복이 안 닫힌다]
  2026-08-12 낮에 같은 함정을 밟았다. 지시는 상대 CLI 에 잘 꽂혔는데 답장 수단이
  그 폴더에 없어서 "답장 불가"로 끝났다. 지시를 보내는 쪽이 **답하는 방법까지**
  실어 보내야 대화가 성립한다. 일감도 똑같다 — 보고 도구가 없으면 job 은 영원히
  running 에 남고, 화면에는 '작업 중'으로만 보인다.

[🔴 무엇을 고쳤는지는 사람에게 묻지 않는다]
  이 스크립트는 변경 요약을 **git 에서 직접** 읽는다(job_verify.collect_diff).
  인자로 받은 문장은 self_report — 참고용 라벨이고 판정 근거가 아니다.
  자기신고를 근거로 삼으면 오늘 na2js 처럼 '정상'이라 말하며 아무것도 안 한 상태를
  통과시킨다.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / '.ai_monitor'))


def main() -> int:
    args = [a for a in sys.argv[1:] if a.strip()]
    if not args:
        print('사용법: python job_report.py <일감번호> "한 줄 보고"')
        return 2

    try:
        job_id = int(args[0])
    except ValueError:
        print(f'[실패] 일감 번호가 숫자가 아니다: {args[0]}')
        return 2
    note = ' '.join(args[1:])

    from src import job_verify, pg_jobs

    job = pg_jobs.get_job(job_id)
    if not job:
        print(f'[실패] 일감 #{job_id} 을(를) 중앙에서 찾지 못함')
        return 1
    if job['status'] not in ('running', 'review'):
        # [WHY 막나] 이미 결정된 일감을 덮어쓰면 승인/반려 기록이 뒤집힌다.
        print(f'[실패] 일감 #{job_id} 은 지금 "{job["status"]}" 상태라 보고를 받지 않는다')
        return 1

    work_dir = job.get('work_dir') or str(_ROOT)
    diff = job_verify.collect_diff(work_dir, job.get('git_before') or '')
    ok = pg_jobs.report_job(job_id, git_after=diff.get('git_after', ''),
                            diff_stat=diff or None, self_report=note)
    if not ok:
        print(f'[실패] 일감 #{job_id} 보고 저장 실패')
        return 1

    if diff:
        print(f'[보고] #{job_id} — 파일 {diff["files"]}개 '
              f'+{diff["insertions"]}/-{diff["deletions"]}, 커밋 {len(diff["commits"])}개'
              + (' (커밋 안 된 변경 있음)' if diff.get('dirty') else ''))
    else:
        print(f'[보고] #{job_id} — git 저장소가 아니라 변경 요약 없음')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
