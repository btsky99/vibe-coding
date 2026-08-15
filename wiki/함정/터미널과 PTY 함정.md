---
title: 터미널과 PTY 함정
type: 함정
sources:
  - .ai_monitor/infra/app_boot.py:193
  - .ai_monitor/vibe-view/src/components/TerminalSlot.tsx:377
  - incident_ledger  # 사고 9건
related: []
confidence: high
updated: 2026-08-15
---

# 터미널과 PTY 함정

## 한 줄

pywebview 6.x _add_edit_menu는 NSMenuItem엔 title을 안 주고

> 자동 합성 (코드 주석 2건 · 파일 2개 · 사고 장부 9건 · 추출 909e7e6).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 🔴 밟았던 것 (사고 장부)

### 터미널 우클릭 메뉴에 복사 버튼이 안 뜨고 붙여넣기만 표시, 복사 클릭 시 빈 문자열 복사

- **원인** — xterm SelectionService가 onUserInput마다 선택 자동 해제 — TUI 실행 중엔 우클릭/클릭 시점에 hasSelection()=false, getSelection() 재조회 시 빈 값
- **수정** — TerminalSlot.tsx: 드래그 시점 선택 텍스트를 lastSelectionRef에 캐시 + 메뉴 오픈 시점 selText 스냅샷으로 복사 (50ba69e)
- 출처: `incident_ledger` · 최초 2026-07-03

### 터미널 우클릭 메뉴에 복사 버튼 미표시 재발 — 드래그해도 선택 자체가 안 생김 (50ba69e 수정으로도 미해결)

- **원인** — TUI(claude CLI)가 마우스 리포팅 DECSET 1000/1006을 켜면 xterm이 드래그를 전부 TUI로 넘겨 로컬 선택 미생성 → 선택 캐시 영구 빈 값 → 조건부 렌더 미충족
- **수정** — 복사 버튼 상시 표시 + 선택 없으면 비활성(회색) + Shift+드래그 힌트 (조건부 렌더 제거) (`b784cbb`)
- 출처: `incident_ledger` · 최초 2026-07-04

### 터미널 드래그 우클릭 복사 후 외부 붙여넣기 불가 — 복사 버튼 상시표시(b784cbb) 후에도 재발

- **원인** — TUI 마우스 리포팅(DECSET 1000/1002) 중 xterm이 좌클릭 드래그를 TUI로 전달해 로컬 선택 자체가 미생성 — 이전 수정 2건은 버튼 가시성/캐시만 고친 증상 패치
- **수정** — capture 단계 mousedown을 shiftKey=true 합성 이벤트로 재디스패치해 xterm SelectionService 로컬 선택 강제 + 붙여넣기 무음 실패 제거 (`c8839fa`)
- 출처: `incident_ledger` · 최초 2026-07-04

### 쿼터 배지 미동작 — Claude available=false(http_429), Codex는 2개월 전 stale 값 고정

- **원인** — Codex: wham/usage 실응답 스키마(rate_limit.primary_window/reset_at)와 파서 기대(rate_limits.primary/resets_at) 불일치로 상시 파싱 실패→세션 폴백 고착. Claude: 일시 429에 배지 소멸+180s 재시도로 리밋 미해소
- **수정** — 실측 스키마 수용(구 스키마 폴백 유지)+window_seconds 전달, Claude는 마지막 성공값 stale 서빙+Retry-After/600s 쿨다운 (`1e82ac5`)
- 출처: `incident_ledger` · 최초 2026-07-04

### 설치본 업데이트 후 'Failed to load Python DLL python311.dll — 지정된 모듈을 찾을 수 없습니다' + 'Failed to remove temporary directo

- **원인** — updater.apply_update_from_temp의 os._exit(0)가 atexit 정리를 건너뜀 → 이전 인스턴스 node PTY 서버가 좀비로 남아 _MEI\pty-server 잠금 → 새 EXE onefile 부트로더가 잠긴 잔여 _MEI와 충돌해 python DLL 부분 추출(pty-server만, DLL 누락). 부트로더는 Python보다 먼저라 앱 내부 정리 불가
- **수정** — kill_runtime_mei_orphans() 신규(pty_process.py) — runtime _MEI 하위 node만 ExecutablePath 필터로 정밀 종료, only_orphans로 부모생존 판정해 타 인스턴스 보호. updater.py가 os._exit 직전 호출(핵심). cleanup_pyinstaller_temp도 rmtree 전 락 좀비 정리. 즉시복구: 좀비 node kill+runtime 청소 후 재기동시 DLL 정상추출 확인
- 출처: `incident_ledger` · 최초 2026-07-07

### 모듈 전역 HTTP_PORT/WS_PORT/_NODE_PTY_REST_URL을 함수 내부에서 global 없이 재대입 → 지역변수 shadowing, 모듈 스코프 소비자가 stale 값(9000/9

- **원인** — main()·중첩함수에서 global 선언 누락. noqa:F811로 경고만 억제하고 근본 원인 방치. 주석은 '__main__에서 재설정'이라 실제와 불일치
- **수정** — main()·_init_and_load_app에 global 선언 추가로 재대입을 실제 전역 갱신화. 정상부팅은 불변, 포트폴백/PTY세션 경로만 정상화
- 출처: `incident_ledger` · 최초 2026-07-07

### UI 폴더 전환 후 일부 API가 옛 프로젝트 데이터 반환/저장 — memory/project-info 옛 이름, 새 태스크가 옛 슬러그로 저장돼 목록 누락, hive 세션/PTY/채팅/스킬 경로 

- **원인** — 요청 런타임 wrapper/핸들러가 부팅 시점 고정값 PROJECT_ID/PROJECT_ROOT를 _current_project_id()/_current_project_root() 대신 사용. 동적함수로의 부분이관이 미완(hive_api)이라 static과 dynamic 혼용
- **수정** — 요청 처리 경로는 _current_project_* 동적값으로 통일(memory/tasks write/hive 5곳/fallback default). 부팅 1회 초기화(_init_project_db 등)는 static 유지. hive_api에 _current_project_id ref 전달, 방어 fallback 패턴 적용
- 출처: `incident_ledger` · 최초 2026-07-07

### 터미널 드래그 선택 하이라이트가 사라진 채 굳음(5회 재발)

- **원인** — 복원 재진입 가드를 restoringSelRef 불리언 플래그로 구분 → term.select()가 onSelectionChange 미발화/rAF 병합 시 플래그 stuck → 다음 진짜 clear를 '내 재적용 이벤트'로 오인해 삼켜 복원 실패. 저장 좌표가 alt버퍼 전환/스크롤백 트림으로 무효화돼도 미검증
- **수정** — restoringSelRef 완전 제거 → 무상태 내용비교(sel===lastSelectionRef) 재진입 가드 + 복원 전 버퍼 바운드 검증(row<buffer.active.length, col<cols)으로 자가복구. TerminalSlot.tsx, v3.7.252
- 출처: `incident_ledger` · 최초 2026-07-12

### 개발+설치버전 동시 실행 시 하나 닫으면 나머지 터미널 콘솔 전멸 + 나중 켠 auto 미동작

- **원인** — resolve_server_ports TOCTOU(test-bind→close→real-bind)로 dev+frozen이 동일 http/ws 선택 → 나중 인스턴스가 먼저 인스턴스 PTY(9001)에 얹힘. auto는 9019 전역 싱글턴이라 나중 켠 쪽 대기인데 UI 침묵
- **수정** — 환경별 포트 베이스 분리(frozen=9000/dev=9004) + is_active_holder() + active_here 필드 + AUTO 대기 칩
- 출처: `incident_ledger` · 최초 2026-07-22

## 코드에 박힌 지식

## `.ai_monitor/infra/app_boot.py`

### _install_mac_edit_menu `[과거사고]`

[과거사고 2026-07-22] pywebview 6.x _add_edit_menu는 NSMenuItem엔 title을 안 주고
서브메뉴에만 'Edit'을 준다 — 아이템 title만 검사하면 탐색이 항상 실패해 중복 '편집'
메뉴를 만들고, 정작 keyEquivalent(⌘C/⌘V)를 소비하는 진짜 Edit 메뉴는 autoenables
그대로 남아 회색 항목이 키를 삼켰다(전 플랫폼 무반응). 서브메뉴 title도 함께 검사.

출처: `.ai_monitor/infra/app_boot.py:193`

## `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx`

### connectPath `[WHY]` `[과거사고]` `[제약]`

[WHY] TUI(claude 등)가 마우스 리포팅(DECSET 1000/1002)을 켜면 xterm이 좌클릭 드래그를
TUI로 전달해 로컬 선택이 아예 안 생긴다 → "드래그→우클릭 복사"가 통째로 죽음(2026-07-04 사고).
xterm 내부 SelectionService는 shiftKey 이벤트만 마우스 리포팅 중에도 로컬 선택으로 처리하므로,
capture 단계에서 일반 좌클릭 mousedown을 shiftKey=true 합성 이벤트로 재디스패치해 선택을 강제한다.
[제약] 이로 인해 마우스 리포팅 중 좌클릭은 TUI에 전달되지 않는다 — claude CLI는 좌클릭을
쓰지 않고(스크롤 휠은 별도 경로라 영향 없음) 사용자 워크플로우(드래그 복사)가 우선.
합성 이벤트는 shiftKey=true라 첫 가드에서 통과 → 재귀 없음. 일반 셸(리포팅 OFF)은 미개입.
[과거사고] v3.7.243은 mousedown만 shift로 합성 → 선택 앵커(시작점)만 생기고
드래그 이동분(mousemove)이 shift 없이 TUI로 새어나가 리포팅 응답이 선택을 즉시 초기화.
증상(2026-07-05 리포트): "복사는 되는데 드래그하면 하이라이트가 바로 사라짐".
해결: 드래그 세션 전체(mousedown→mousemove→mouseup)를 shift 이벤트로 재디스패치해
xterm 로컬 선택 확장을 유지하고 원본 이벤트는 stopImmediatePropagation으로 리포팅 경로 차단.

출처: `.ai_monitor/vibe-view/src/components/TerminalSlot.tsx:377`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 과거사고, 제약 -->
