# 구현 계획 — 전략 #2a: onefile → onedir 전환 (_MEI 버그 클래스 구조적 전멸)

<!--
FILE: ai_monitor_plan.md
DESCRIPTION: PyInstaller onefile→onedir 전환 + 업데이트 모델을 exe-swap→"setup EXE 사일런트 설치"로 전환.
             매 부팅 _MEI 추출을 없애 좀비 node/DLL로드실패/temp정리실패 버그 클래스를 뿌리째 제거.

REVISION HISTORY:
- 2026-07-09 Claude: 신규. 방향 승인(옵션 A, AskUserQuestion). 이전 계획(server.py 분할 Phase 2)은 완료 → 교체.
-->

> **설계 승인**: 2026-07-09 (전략 #2a, 옵션 A onedir). 메모리 `project_update_dll_load_fail.md` 참조.
> **북극성**: 기능 확장 아님 — 재발 핫스팟(update/pty/build fix 16건)의 공통 뿌리 제거 = 삽질 감소.
> **핵심 통찰**: 인스톨러가 이미 `CloseApplications=yes`로 "실행 중 앱 닫고 교체+재시작"을 처리 →
>   업데이트를 "setup /SILENT"로 바꾸면 _update.bat·_MEI 청소·좀비 처리가 통째로 은퇴한다.

## 🚨 매 단계 공통 안전 절차
1. **로컬 우선**: 릴리즈 파이프라인(build-release.yml)·인스톨러(.iss) 직접 수정은 **로컬 onedir 빌드+smoke 통과 후에만**.
2. **단계별 커밋 + 체크포인트**: 각 Phase 종료 시 `python scripts/checkpoint.py`. git bisect 가능하게.
3. **폴백 보존**: 구 exe-swap 경로를 즉시 삭제하지 말고, onedir 검증 완료(Phase E)까지 죽은 코드로 유지 후 은퇴.
4. **검증 3종**: `pytest tests --ignore=tests/office` + `python scripts/smoke_test.py` + 실제 업데이트 왕복.
5. **push = 릴리즈**: Phase C 이후 push는 실사용자에게 나감 — 각 push 전 사용자 확인.

---

## Phase A — onedir 빌드 성립 (로컬, 릴리즈 무영향)

```
[ ] Task A1: spec를 onefile→onedir로 전환
    파일: vibe-coding.spec
    방법: EXE(...)에 exclude_binaries=True 추가 + a.binaries/a.datas 제거,
          runtime_tmpdir 라인 삭제. 하단에 COLLECT(exe, a.binaries, a.datas, name=<앱폴더>) 추가.
    검증: pyinstaller vibe-coding.spec --noconfirm → dist/<앱폴더>/ 생성 + <앱>.exe 존재.

[ ] Task A2: onedir 실행 + 리소스 해석 검증
    파일: (없음 — 실행 검증)
    방법: dist/<앱폴더>/<앱>.exe 실행. sys._MEIPASS가 onedir 번들 루트를 가리키는지,
          api/infra/src/vibe-view/dist/pgsql 경로 해석이 정상인지 확인.
    검증: python scripts/smoke_test.py (onedir exe 대상) — /api/config·hive/health 200.
    의존: A1

[ ] Task A3: _MEIPASS 의존 코드 onedir 호환 점검
    파일: .ai_monitor/server.py, boot.py, updater.py, infra/lifecycle.py
    방법: sys._MEIPASS.parent(runtime_dir) 전제 코드 전수 확인. onedir엔 runtime _MEI 없음 →
          heal_broken_mei_at_startup/kill_runtime_mei_orphans는 자연 no-op(방어 확인만).
          boot.py _bundle_seed_root(_appseed)·_version 경로 onedir에서 유효한지 검증.
    검증: onedir 부팅 로그에 경로 에러 없음 + smoke 통과.
    의존: A2
```

## Phase B — 업데이트 모델 전환 (exe-swap → setup 사일런트)

```
[ ] Task B1: updater 에셋 선택을 setup exe 우선으로
    파일: .ai_monitor/updater.py (_find_asset_url)
    방법: 1순위를 vibe-coding-setup-*.exe로. update-*.exe(구 onefile)는 폴백/은퇴.
    검증: 단위 테스트 — setup 에셋이 있으면 그걸 고름.

[ ] Task B2: apply_update를 "setup /SILENT 실행 후 종료"로 전환
    파일: .ai_monitor/updater.py (apply_update_from_temp → apply_update_via_installer)
    방법: 다운로드한 setup을 `/SILENT /SUPPRESSMSGBOXES /NORESTART` 등으로 subprocess 실행 후
          현재 프로세스는 정상 종료(Inno CloseApplications가 앱 닫고 교체, [Run] postinstall이 재시작).
          _update.bat/build_update_bat/_MEI kill 경로는 死코드로 남기고 폴백 플래그로만 유지.
    검증: tests/test_updater_release_path.py 확장 — installer 실행 인자 계약(/SILENT 포함) 단위 테스트.
    의존: B1

[ ] Task B3: 진행바/상태 흐름 onedir 업데이트에 맞게 점검
    파일: .ai_monitor/updater.py, vibe-view (updateProgress)
    방법: setup 다운로드 percent는 그대로 유효. "적용 중" 이후 Inno가 프로세스를 닫으므로
          프론트 상태 전이(적용→재시작) 문구 확인.
    검증: 로컬에서 update_ready.json 상태 전이 수동 확인.
    의존: B2
```

## Phase C — 인스톨러 + CI onedir화 (릴리즈 파이프라인 수정)

```
[ ] Task C1: .iss [Files]를 onedir 폴더 전체로
    파일: vibe-coding-setup.iss
    방법: 단일 exe Source → `Source: ".ai_monitor\dist\<앱폴더>\*"; DestDir:"{app}";
          Flags: ignoreversion recursesubdirs createallsubdirs`. MyAppSrcExe 개념 교체.
          pgsql 등 기존 항목과 충돌/중복 정리.
    검증: 로컬 ISCC 빌드 → setup 실행 → {app}에 onedir 전체 설치 + 앱 정상 실행.
    의존: A3

[ ] Task C2: build-release.yml onedir 빌드로 전환
    파일: .github/workflows/build-release.yml
    방법: `pyinstaller --onefile` → onedir(spec 사용 권장: `pyinstaller vibe-coding.spec`).
          --runtime-tmpdir 제거. 업데이트 에셋 = setup exe(이미 빌드). 구 update-*.exe 에셋 제거.
          spec↔CI add-data 동기화 규칙 유지(메모리 feedback_spec_datas_check).
    검증: (Phase E에서 실제 CI 빌드로 검증) — 로컬에선 spec 빌드 성공까지.
    의존: C1

[ ] Task C3: smoke_test / 로컬빌드 스크립트 onedir 경로 대응
    파일: scripts/smoke_test.py, vibe-coding.spec 관련 헬퍼
    방법: dist/<파일>.exe → dist/<앱폴더>/<앱>.exe 경로로 갱신.
    검증: python scripts/smoke_test.py 통과.
    의존: C2
```

## Phase D — 기존 onefile 설치본 → onedir 호환 전환

```
[ ] Task D1: 전환 시나리오 설계 + 문서화
    파일: (메모리 project_update_dll_load_fail.md 갱신)
    방법: 현재 onefile 설치본이 v3.7.248 이후 updater로 setup을 받아 /SILENT 실행 →
          Inno가 {app}에 onedir 설치(단일 exe 자리를 폴더가 대체). AppId 동일 →
          Inno가 업그레이드로 인식. 구 단일 exe 잔재 정리(uninstall 로직/ignoreversion).
    검증: 구 onefile 설치 상태에서 신 setup 실행 → onedir로 깔끔히 전환 확인(수동 E2E).

[ ] Task D2: 소프트 업데이트 채널(boot.py) onedir 영향 검증
    파일: .ai_monitor/boot.py, soft_updater.py
    방법: _MEIPASS 위치 변화가 managed checkout/_appseed 폴백에 영향 없는지 재확인.
    검증: onedir에서 boot --boot-selftest 통과 + 소스 업데이트 왕복.
    의존: D1
```

## Phase E — E2E 검증 + 릴리즈

```
[ ] Task E1: 전체 회귀 + 실제 업데이트 왕복
    방법: pytest(112+) + smoke + "구버전 설치 → 신버전 업데이트 → 재부팅 무에러" 왕복.
          _MEI/DLL로드실패/temp정리실패가 실제로 안 뜨는지 확인.
    검증: 3종 그린 + 업데이트 왕복 무에러.

[ ] Task E2: 릴리즈 (사용자 확인 후 push)
    방법: /vibe-release. CI onedir 빌드 + setup 업로드. 첫 실사용자 전환 모니터.
    검증: CI 그린 + 릴리즈 에셋(setup) 정상 + 자동 업데이트 감지.
    의존: E1
```

---

## 리스크 & 마일스톤
- **최대 리스크**: Phase C/D — 실사용자 설치본의 update 경로 변경. 폴백(구 exe-swap) 유지로 완충.
- **되돌리기**: Phase A~B는 로컬 전용(무영향). Phase C부터 릴리즈 영향 → push 전 사용자 확인.
- **1차 목표(이번 세션 가능)**: Phase A(로컬 onedir 빌드 성립) — 릴리즈 무영향, 전환 타당성 실증.
