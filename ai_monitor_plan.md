# 구현 계획 — 경량 소스 업데이트 채널 (A안 run-from-source 부트스트랩)

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 설치 EXE를 풀빌드 없이 git push + 버튼 클릭으로 순수 .py 변경 갱신하는 경량 업데이트 채널 구현 계획.
             2026-06-23 brainstorm 승인 (A안 run-from-source 부트스트랩).

REVISION HISTORY:
- 2026-06-23 Claude: 신규 계획 작성 (이전 'Antigravity CLI 마이그레이션'은 2026-06-11 전체 완료로 교체)
-->

> 설계 승인: 2026-06-23. 메모리: `project_soft_update_channel.md`
> 목표: 설치 EXE를 풀빌드 없이 `git push` + 버튼 클릭으로 순수 .py 변경 갱신.
> 제약: 의존성/C확장 변경은 `soft_manifest.min_exe` 게이트로 풀빌드 강제. dev 트리(D:\vibe-coding)와 관리 체크아웃 분리.

---

## 마일스톤 A — 부트스트랩 토대 (선행 필수)

### [ ] Task 1: soft_manifest.json 생성 (풀빌드 게이트 규약)
- 파일: `soft_manifest.json` (repo 루트, 신규)
- 방법: `{ "min_exe": "<현재 _version>", "channel": "main", "schema": 1 }`. boot.py/soft_updater가 읽을 최소 EXE 버전 게이트. JSON이라 표준 헤더 불가 → PROJECT_MAP에 역할 기재.
- 검증: `python -c "import json;json.load(open('soft_manifest.json'))"` 통과 + min_exe가 `_version.__version__`과 일치
- 의존성: 없음

### [ ] Task 2: boot.py 신규 — 체크아웃 보장 + seed 폴백
- 파일: `.ai_monitor/boot.py` (신규)
- 방법: 표준 헤더 + `resolve_src()` → `%LOCALAPPDATA%\VibeCoding\app`(없으면 `git clone https://github.com/btsky99/vibe-coding`). clone 실패 시 `_seed_from_bundle()` — `sys._MEIPASS`(또는 EXE 옆 datas)에서 SRC로 소스 복사(오프라인 최초 부팅 보장). git 미설치/clone 실패도 seed로 부팅 성립.
- 검증: dev에서 `python .ai_monitor/boot.py`로 SRC 생성/스킵 분기 로그 확인. SRC에 .ai_monitor/server.py 존재
- 의존성: Task 1 (manifest 경로 규약 공유)

### [ ] Task 3: boot.py — EXE버전 게이트 + sys.path 주입 + runpy 라우팅
- 파일: `.ai_monitor/boot.py` (Task 2 이어서)
- 방법:
  - `_check_min_exe()`: SRC/soft_manifest.json.min_exe > 현재 `_version` 이면 게이트 — 경고 후 **번들(frozen) 코드로 폴백 실행**(soft 미적용). 의존성 바뀐 소스를 옛 EXE가 안 받게.
  - `sys.path.insert(0, str(SRC)); sys.path.insert(0, str(SRC/'.ai_monitor'))`
  - **argv 라우팅(블로커 해결)**: 인자 없음 → `runpy.run_path(SRC/.ai_monitor/server.py, run_name='__main__')`. `boot.py <script.py> [args]`(데몬/도구 재실행) → `runpy.run_path(SRC/<script>, run_name='__main__')` (체크아웃 보장은 메인이 이미 함 → 스킵).
  - 부팅 예외 캐치 → 직전 SHA 있으면 `git reset --hard <prev>` 후 1회 재시도, 그래도 실패 시 seed 폴백.
- 검증: `python .ai_monitor/boot.py` → 앱 기동 / `python .ai_monitor/boot.py scripts/hive_bridge.py --help` → 데몬모드 분기
- 의존성: Task 2

---

## 마일스톤 B — 업데이트 채널 (감지/적용)

### [ ] Task 4: soft_updater.py 신규 — SHA 감지
- 파일: `.ai_monitor/soft_updater.py` (신규)
- 방법: 표준 헤더 + `check_soft_update(data_dir, src_dir)`: GitHub API `GET /repos/btsky99/vibe-coding/commits/main` → remote_sha. 로컬 `git -C SRC rev-parse HEAD` → local_sha. 다르면 `soft_update_ready.json {ready:true, remote_sha, local_sha, last_check}` 기록. 토큰 불필요(public)이나 updater.py 토큰 폴백 패턴 재사용. min_exe 게이트 위반 시 ready=false + reason.
- 검증: dev 호출 → SHA 일치 시 ready=false, 강제 mismatch 시 ready=true JSON 생성
- 의존성: Task 1

### [ ] Task 5: soft_updater.py — 적용(apply) + 재시작
- 파일: `.ai_monitor/soft_updater.py` (Task 4 이어서)
- 방법: `apply_soft_update(src_dir)`: `git -C SRC fetch origin main` → 현재 SHA 백업(rollback 파일) → `git -C SRC reset --hard origin/main`. 성공 후 updater.py의 `_update.bat` 패턴 유사 `_restart.bat`로 PID 종료 대기 후 EXE 재실행. 설치본 dirty 트리는 `reset --hard`로 흡수.
- 검증: dev 복제 SRC에서 과거 커밋 → apply → HEAD가 origin/main 전진 + rollback 파일 생성
- 의존성: Task 4

### [ ] Task 6: server.py — soft-update 엔드포인트 2개 + 폴링 스레드
- 파일: `.ai_monitor/server.py`
- 방법: 기존 `/api/check-update-ready`(1980), `/api/apply-update`(2792) 패턴 복제 —
  - `GET /api/soft-update/check` → `soft_updater.check_soft_update` 백그라운드 트리거 + `soft_update_ready.json` 반환
  - `POST /api/soft-update/apply` → `soft_updater.apply_soft_update`
  - 데몬 등록 블록(4047 부근)에 시동 1회 + 주기 폴링 스레드 추가(기존 updater 옆).
- 검증: 기동 후 `curl /api/soft-update/check` 200 + JSON. **server.py 줄 수 재확인**(현재 4658줄, +40 이내 유지; 초과 시 soft 핸들러를 api/ 모듈로 분리)
- 의존성: Task 4, Task 5

---

## 마일스톤 C — UI + 빌드 전환

### [ ] Task 7: UI — "소스 업데이트(빠름)" 버튼
- 파일: `.ai_monitor/vibe-view/src/App.tsx`(배너 391~410), `components/TopMenuBar.tsx`(버튼 503)
- 방법: 기존 EXE 업데이트 배너/버튼 옆에 soft 채널 상태 추가. `/api/soft-update/check` 폴링 → ready면 "소스 업데이트(빠름)" 버튼 → `/api/soft-update/apply`. 풀빌드(파랑)와 시각 구분(빠름=초록).
- 검증: `npm run build` 통과 + Playwright로 버튼 렌더/클릭 흐름 확인(스크린샷 금지)
- 의존성: Task 6

### [ ] Task 8: vibe-coding.spec — entry 전환 + 의존성 hiddenimports 보강
- 파일: `vibe-coding.spec`
- 방법: `Analysis([...server.py])` → `Analysis([...boot.py])`. 앱 모듈이 PYZ에서 빠지므로 의존성을 `collect_all('pywebview')` + `collect_submodules('psycopg2'/'websockets'/'winpty'/'fastembed'/'onnxruntime'/'tokenizers')`로 hiddenimports 보강. **datas는 seed용 유지**(현행). `soft_manifest.json` datas 추가. [과거사고 spec↔CI 동기] build-release.yml `--add-data`도 동시 갱신.
- 검증: 로컬 `pyinstaller vibe-coding.spec --noconfirm` 성공 → 빈 폴더 실행 → SRC clone/seed 후 정상 기동(데몬 포함). app 모듈이 PYZ에 없음 확인
- 의존성: Task 3

### [ ] Task 9: build-release.yml CI 동기화 + 문서
- 파일: `.github/workflows/build-release.yml`, `PROJECT_MAP.md`
- 방법: CI `--add-data`/entry를 spec과 일치. PROJECT_MAP에 boot.py/soft_updater.py/soft_manifest.json 역할 + 줄 수 기재.
- 검증: CI 빌드 그린 + 생성 EXE 설치본에서 soft 업데이트 1회 왕복(푸시→버튼→갱신) E2E
- 의존성: Task 8

---

## 실행 순서 요약
1 → 2 → 3 → (4 → 5 → 6) → 7 → 8 → 9
- 마일스톤 A(1~3) 먼저: 부트스트랩이 모든 것의 토대.
- B(4~6)와 C-UI(7)는 A 위에서.
- spec/CI(8~9)는 boot.py 안정화 후 마지막 — 빌드 깨짐 위험 최소화.

## 리스크 체크포인트
- **데몬 재귀**: Task 3 argv 라우팅 누락 시 watchdog/orchestrator 전멸 → Task 3 검증에 데몬모드 분기 필수.
- **오프라인 최초 부팅**: Task 2 seed 폴백 없으면 네트워크 없는 PC 부팅 불가 → 필수.
- **min_exe 게이트**: Task 3/4 게이트 누락 시 의존성 바뀐 소스를 옛 EXE가 받아 크래시 → 양쪽 모두 검사.
