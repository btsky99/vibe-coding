<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 라이브 프로젝트 전환(무재시작) 구현 계획 — 폴더 선택 즉시 DB/컨텍스트/패널 전환.

REVISION HISTORY:
- 2026-07-19 Claude: ✅ 전체 완료 — 구현 a54ba4a + 배포 v3.7.268(8171d93, CI 성공). 체크박스 갱신.
- 2026-07-19 Claude: 신규. LAN 자동공유(v3.7.267) 완료 → 교체. 브레인스토밍 승인(라이브 전환).
-->

# 라이브 프로젝트 전환 (무재시작) — 구현 계획

승인: 2026-07-19. 폴더 선택 → 재시작 없이 프로젝트 전환(DB 커넥션+컨텍스트+배너+패널).
근본원인: PROJECT_CONTEXT_UNRESOLVED/DB커넥션/PROJECT_ROOT가 부팅 시 1회 고정, 런타임 재초기화 없음.

핵심 발견: `DaemonEnv.current_project_id/root`는 이미 라이브 콜러블(late-binding) → 데몬 대부분 자동 추종.
예외는 zettel_sync(루프 진입 전 1회 캡처)뿐 → 재시작(위험) 대신 매 사이클 재해석으로 해결.

---

## Phase 1 — 백엔드 라이브 전환 관문

[x] Task 1: server.py `_switch_project(path)` 구현
    방법: ① dir 검증 ② last_path 저장 + projects.json MRU ③ _pg_conn_lock 안에서
          _init_project_db(새슬러그)(DB 생성+set_project_db+커넥션리셋) + ensure_schema
          ④ PROJECT_ROOT 전역 갱신 + PROJECT_CONTEXT_UNRESOLVED=False
          ⑤ fs_watcher 옵저버 새 루트로 재지정(best-effort try/except)
          ⑥ 실패 시 이전 프로젝트로 롤백 + {ok:false,error}. 성공 {ok,project_id}.
    검증: 존재 dir→전환+ok, 없는 경로→에러+상태불변.
    의존성: 없음

[x] Task 2: POST /api/switch-project 라우트 등록
    파일: server.py POST 라우트 테이블
    방법: {path} 받아 _switch_project 호출, JSON 반환.
    검증: curl로 전환 호출 200.
    의존성: Task 1

## Phase 2 — 데몬 라이브 추종 (재시작 없이)

[x] Task 3: zettel_sync 매 사이클 project/vault 재해석
    파일: infra/daemons.py run_zettel_sync
    방법: _proj_id/_vault/_old_vault 해석을 루프 밖→루프 안으로 이동(또는 콜러블 재호출).
          전환 후 다음 60초 사이클부터 새 프로젝트 vault로 동기화.
    검증: 전환 후 로그의 project_id 변경 확인(구문검증으로 대체 가능).
    의존성: 없음(Task 1과 병렬)

## Phase 3 — 프론트 배선

[x] Task 4: App.tsx openFolder → switch-project 호출
    파일: vibe-view/src/App.tsx
    방법: select-folder 성공(+prompt 폴백) 후 POST /api/switch-project 호출 →
          ok면 setCurrentPath + config/패널 리페치(projectUnresolved effect가 이미 재조회).
          FileExplorer의 select-folder 경로(line 183)도 동일 적용 검토.
    검증: 빌드(tsc) 통과.
    의존성: Task 2

## Phase 4 — 검증 + 배포

[x] Task 5: 로컬 검증
    방법: dev 서버에서 switch-project 정상/롤백/없는경로 케이스 + py_compile/ruff/tsc.
    검증: 케이스 통과.
    의존성: Task 1~4

[x] Task 6: /vibe-release 배포
    방법: Step0~0.5 + 버전증가 + 커밋 + 푸시 + CI.
    검증: CI 성공 + Release.
    의존성: Task 5

---
## 의존성: Task 1→2, Task 3 병렬 → Task 4 → Task 5 → Task 6
## 리스크 관리: 데몬 재시작 회피(라이브 콜러블+zettel 재해석), fs_watcher 재지정은 best-effort, 전환 실패 시 롤백.
