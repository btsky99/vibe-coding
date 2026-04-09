<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 오피스 프로필 중앙화 리팩터링 — PostgreSQL SSOT 전환
REVISION HISTORY:
- 2026-04-09 Claude: 오피스 프로필 중앙화 계획 수립 (localStorage → PostgreSQL)
- 2026-04-08 Claude: Phase 1 코딩 부서 시스템 계획 (완료, 아카이브 예정)
-->

# 오피스 프로필 중앙화 리팩터링

**상태:** 진행 중
**목표:** 오피스 프로필을 PostgreSQL 중앙 저장소로 이동하고 모든 창이 동일 데이터를 공유하도록 전환
**원칙:** 편법 금지. 근본 원인 수정. 창 간 실시간 동기화.

## 배경 (Why)

현재 오피스 프로필은 브라우저 `localStorage`에 저장된다. 문제:

1. 메인 창(pywebview/WebView2)과 오피스 창(PySide6 QWebEngineView)은 **서로 다른 브라우저 엔진**이라 localStorage가 공유되지 않는다.
2. 오피스 창의 QWebEngineView는 `setPersistentStoragePath()` 설정이 없어 localStorage가 **아예 영구 저장되지 않는다**. 지휘자를 빼고 창을 닫았다 열면 되살아난다.
3. `OfficeWorld.tsx`의 `ZONE_LAYOUT`이 하드코딩된 4개 zone만 지원해서 동적 부서(`dept-coding`, `dept-exec`)가 전부 `desk` 영역으로 폴백 → 부서가 시각적으로 겹친다.
4. CEO 에이전트가 `user` zone(대표실)이 아닌 자기 부서 zone에 있어 대표실이 비어있다.
5. `OfficeApp.tsx:239`에 하드코딩된 "대표" 정적 UI가 있어 실제 CEO 에이전트와 중복된다.

---

## Phase 1: 백엔드 — 데이터 계층 + API

[x] Task 1: PostgreSQL 스키마 추가
    파일: .ai_monitor/src/pg_store.py
    방법:
    - 테이블 `office_profiles` 생성: id TEXT PK, name TEXT, data JSONB, is_default BOOLEAN, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
    - 테이블 `office_profile_state` 생성: singleton (id=1), active_profile_id TEXT
    - `init_office_schema()` 함수 — 최초 실행 시 DEFAULT_PROFILE 시드
    - CRUD 헬퍼: list/get/upsert/delete/set_active/get_active
    - LISTEN/NOTIFY 채널 'office_profiles_changed' 발행

[x] Task 2: 오피스 API 모듈 생성
    파일: .ai_monitor/api/office_api.py (신규)
    방법:
    - handle_office_api(handler, path, method) 디스패처 함수
    - GET /api/office/profiles — 전체 목록 + 활성 ID
    - GET /api/office/profiles/{id} — 단일 조회
    - POST /api/office/profiles — 생성 (body: {name, data})
    - PUT /api/office/profiles/{id} — 전체 대체 (body: {name, data})
    - DELETE /api/office/profiles/{id} — 삭제 (기본 프로필 삭제 금지)
    - PUT /api/office/profiles/active/{id} — 활성 프로필 변경
    - GET /api/office/profiles/stream — SSE (LISTEN 'office_profiles_changed')

[x] Task 3: server.py 라우팅 등록
    파일: .ai_monitor/server.py
    방법:
    - 상단 임포트: from api.office_api import handle_office_api
    - do_GET / do_POST / do_PUT / do_DELETE에서 path.startswith('/api/office/profiles') 분기 추가
    - 모듈 로드 시 init_office_schema() 호출

---

## Phase 2: 프론트엔드 — API 클라이언트 + 훅 재작성

[x] Task 4: API 클라이언트 생성
    파일: .ai_monitor/vibe-view/src/services/officeApi.ts (신규)
    방법:
    - listProfiles(), getProfile(id), createProfile(data), updateProfile(id, data), deleteProfile(id), setActiveProfile(id)
    - subscribeProfileChanges(onMessage): EventSource 구독
    - 에러 표준화 (에러 시 콘솔 경고 + 기본값 폴백)

[x] Task 5: useWorkspaceProfiles 훅 재작성
    파일: .ai_monitor/vibe-view/src/hooks/useWorkspaceProfiles.ts
    방법:
    - localStorage 관련 코드 전부 제거 (loadProfiles, saveProfiles, STORAGE_KEY_*)
    - 초기 로딩: useEffect + officeApi.listProfiles()
    - 상태: profiles, activeProfileId, loading, error
    - 모든 CRUD는 낙관적 업데이트 후 API 호출, 실패 시 롤백
    - SSE 구독으로 외부 변경 실시간 반영 (cleanup 필수)
    - AgentSlot/Department/WorkspaceProfile 타입 정의는 유지 (officeApi.ts에서도 재사용 위해 export)

[x] Task 6: 1회성 localStorage 마이그레이션
    파일: .ai_monitor/vibe-view/src/hooks/useWorkspaceProfiles.ts (또는 App.tsx 시작 훅)
    방법:
    - 앱 최초 로드 시 localStorage에서 'office_profiles_v2' 읽기
    - 있으면 각 프로필을 API로 POST/PUT
    - 성공 시 localStorage 키 삭제 + 콘솔 로그
    - 실패 시 localStorage 유지 (다음 실행에서 재시도)

---

## Phase 3: 오피스 레이아웃 버그 수정

[x] Task 7: 동적 zone 레이아웃
    파일: .ai_monitor/vibe-view/src/components/office/OfficeWorld.tsx
    방법:
    - `ZONE_LAYOUT`을 고정 객체 → `computeZoneLayout(deptIds: string[])` 함수로 변경
    - desk 영역(x:0.04, y:0.16, w:0.58, h:0.60)을 부서 개수에 따라 분할:
      - 1개: 전체
      - 2개: 좌우 50/50
      - 3개: 좌·우상·우하
      - 4개 이상: 2x2 그리드 + 스크롤
    - user/meeting/recovery zone은 그대로 유지
    - `getZoneRect(zone, layout)`이 동적 layout 인자를 받도록 시그니처 변경
    - 부서 이름 라벨을 zone 상단에 렌더링

[x] Task 8: CEO 대표실 배치 + 하드코딩 제거
    파일: .ai_monitor/vibe-view/src/hooks/useOfficeState.ts, .ai_monitor/vibe-view/src/components/office/OfficeApp.tsx
    방법:
    - useOfficeState.ts: presences 생성 루프에서 agent.role === 'ceo'면 zone = 'user'로 강제 (부서 zone 무시)
    - OfficeWorld.tsx의 `user` zone 크기 확대: w:0.20→0.22, h:0.08→0.14
    - OfficeApp.tsx:239-250 하드코딩된 "대표 (사용자)" <div> 블록 제거
    - 제거한 자리에 "조직" 헤더를 위로 올림

---

## Phase 4: 오피스 창 Qt 프로필 영구 저장

[x] Task 9: dashboard_window.py QWebEngineProfile 설정
    파일: .ai_monitor/dashboard_window.py
    방법:
    - QWebEngineProfile, QWebEnginePage 임포트 추가
    - 저장 경로: %APPDATA%/vibe-coding/{dev|exe}/{project}/qt_webengine/
    - QWebEngineProfile('vibe-office', self.webview)
    - setPersistentStoragePath, setCachePath, setPersistentCookiesPolicy(ForcePersistentCookies)
    - QWebEnginePage(profile) → self.webview.setPage(page)
    - 프로젝트명은 서버 API /api/project-info에서 가져오는 기존 로직 재사용

---

## Phase 5: 검증 + 커밋

[x] Task 10: 빌드 + 수동 테스트
    방법:
    - cd .ai_monitor/vibe-view && npm run build
    - 서버 재시작 후 메인 창에서 지휘자 삭제
    - 오피스 창 열어 즉시 반영되는지 확인
    - 오피스 창 닫고 다시 열기 → 삭제 유지 확인
    - 앱 전체 재시작 → 삭제 유지 확인
    - PostgreSQL 직접 쿼리: SELECT * FROM office_profiles;

[x] Task 11: 커밋
    방법:
    - Conventional Commits: feat(office): 프로필 PostgreSQL 중앙화 + 레이아웃 버그 수정
    - 본문에 5가지 근본 원인 명시
    - 영향 범위: 오피스 창 사용자 데이터 이전 (마이그레이션 자동)

---

## 결정 사항 (승인됨)

1. 마이그레이션 정책: **자동 마이그레이션** (기존 localStorage 데이터 보존)
2. 다중 사용자: **미지원** (단일 개발자용, user_id 컬럼 없음)
3. 실시간 동기화: **PostgreSQL LISTEN/NOTIFY + SSE**
4. 하드코딩 "대표" UI: **완전 제거** (실제 CEO 에이전트가 대표실에 렌더링됨)
