<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 자율 클로드 heartbeat 데몬 구현 계획 — OpenClaw식 자율 루프.
             worktree 샌드박스 + deny 권한 프로파일 + 자가 발굴 + 텔레그램 제어.

REVISION HISTORY:
- 2026-07-17 Claude: 신규. 이전 계획(telegram_bridge 분할)은 76bf532까지 완료 → 교체.
  브레인스토밍 승인 완료 (memory: project_heartbeat_daemon.md).
-->

# 구현 계획 — 자율 클로드 heartbeat 데몬

> **근거**: 2026-07-17 브레인스토밍 승인. 사람이 부르지 않아도 스스로 깨어나
> hive_tasks 소비 + 자가 발굴하는 자율 루프. 샌드박스(worktree + deny 프로파일) 필수.

## 핵심 사실 (정찰 실측)
- `pg_tasks.py`에 `save_state`/`load_state`(hive_state KV), `atomic_checkout`,
  `release_checkout`, `save_task`, `add_task_comment` 전부 존재 — DB 신규 함수 불필요.
- 쿼터는 로컬 HTTP `/api/context-usage`(hive_api)가 사용률(%) 반환 — 재사용.
- `.ai_monitor/config/`는 미존재 디렉토리 — 신규 생성 시 spec datas 사고(v3.7.215~218)
  조건. → 설정 JSON은 파일로 두지 않고 **데몬 모듈 내 상수 → 런타임에 data_dir 생성**.
- `infra/daemons.py`는 `DaemonEnv` + `start_all_daemons` 패턴. daemon=True 스레드,
  subprocess 자식은 `env.child_procs` append 불변식.
- 텔레그램 명령은 `telegram_agent_bot.py`의 `CommandHandler` 패턴 (별도 프로세스 —
  데몬↔봇 상태 공유는 hive_state 경유).

---

## 태스크

### [x] Task 1: heartbeat_daemon.py 골격 + 가드 계층 생성
- **파일**: `.ai_monitor/infra/heartbeat_daemon.py` (신규)
- **방법**: 표준 헤더 + `SANDBOX_SETTINGS` 상수(deny: `git push/merge`, `rm -rf`,
  릴리즈/버전 스크립트, worktree 밖 쓰기) + hive_state(`state_key='heartbeat'`) 기반
  상태 모델(enabled·일일 카운터·연속 실패·발굴 해시 목록) + PG advisory lock 싱글턴 +
  `/api/context-usage` 쿼터 조회 + 가드 판정 함수(킬스위치/일일 5건/쿼터 80%/연속 실패 2회)
- **검증**: `python -c "from infra.heartbeat_daemon import ..."` + 가드 판정 경계값 확인

### [x] Task 2: worktree 샌드박스 + claude -p 실행기 (Task 1 완료 후)
- **파일**: `.ai_monitor/infra/heartbeat_daemon.py` (계속)
- **방법**: worktree 보장(`git worktree add D:\vibe-coding-auto`, 사이클 시작 시
  `reset --hard`+`clean -fd`, 태스크별 `auto/task-<id>` 브랜치를 main에서 생성) +
  SANDBOX_SETTINGS를 data_dir에 materialize + `claude -p --settings <경로>` subprocess
  실행(cwd=worktree, 타임아웃 30분 후 킬, stdout 결과 파싱)
- **검증**: worktree 준비 함수 단독 dry-run (실제 claude 호출 없이 브랜치/리셋 확인)

### [x] Task 3: 메인 루프 + 자가 발굴 + 보고 (Task 2 완료 후)
- **파일**: `.ai_monitor/infra/heartbeat_daemon.py` (계속)
- **방법**: PG `LISTEN hive_heartbeat` + 10분 폴링 하이브리드 루프 → 가드 통과 시
  pending 태스크 `atomic_checkout('claude-auto', id)` → 실행 → `release_checkout` +
  `add_task_comment` + pg_logs 기록. pending 없으면 자가 발굴: 사고 장부/교훈에서
  개선 후보 1건 → 근거 해시 중복 스킵 → `save_task(source='self')` 후 동일 경로 실행.
  결과 보고는 hive_state 아웃박스에 적재(텔레그램 프로세스가 소비 — Task 5와 계약)
- **검증**: 태스크 1건 수동 등록 → 1사이클 실행 → 체크아웃/커밋/보고 적재 확인

### [x] Task 4: daemons.py에 run_heartbeat 등록 (Task 3 완료 후)
- **파일**: `.ai_monitor/infra/daemons.py`
- **방법**: `run_heartbeat(env)` 추가 — hive_state `heartbeat.enabled` False면 즉시
  return(기본 꺼짐), True면 heartbeat_daemon 루프 진입. `start_all_daemons`에 `_t` 등록
- **검증**: 서버 부팅 → enabled=False에서 데몬 무동작 확인, 1500줄 제한 확인

### [x] Task 5: 텔레그램 /auto on|off|status 명령 (Task 1 완료 후 병행 가능)
- **파일**: `scripts/telegram_agent_bot.py`
- **방법**: `CommandHandler("auto", ...)` 추가 — hive_state `heartbeat.enabled` 토글 +
  status는 일일 카운터/연속 실패/최근 보고 출력. Task 3의 아웃박스를 그룹 발신으로 소비
- **검증**: 봇 재시작 → /auto status 응답 확인, 1500줄 제한 확인

### [x] Task 6: 통합 검증 + 문서 + 커밋 (Task 4·5 완료 후)
- **파일**: `PROJECT_MAP.md`, 커밋
- **방법**: 스모크(enabled off→on→1사이클→off), `wc -l` 전 파일 확인,
  PROJECT_MAP.md에 heartbeat_daemon.py 등재, Conventional Commit(3단 본문)
- **검증**: 규칙 8 리포트 3줄 출력 + checkpoint.py 기록

## 의존성
Task 1 → Task 2 → Task 3 → Task 4 → Task 6
Task 1 → Task 5 → Task 6 (Task 2·3과 병행 가능)
