# 🔀 오피스/클래식 서버 프로세스 분리

## 🎯 목표
현재 server.py 하나가 클래식+오피스를 모두 서빙하는 구조를 분리.
오피스 전용 서버(office_server.py)를 별도 프로세스로 실행하여
안정성(크래시 격리), 독립 재시작, 리소스 격리를 확보한다.
DB(PostgreSQL)는 공유 유지 → 하이브 마인드 동기화 자연스러움.

## 🛠️ 태스크 리스트

### Phase 1: 공통 유틸 추출

- [x] **Task 1: server_utils.py 신규 — 포트 탐색 + JSON 응답 헬퍼 추출** ✅
    파일: `.ai_monitor/src/server_utils.py` (신규)
    방법:
    - `_find_free_port(start, max_tries)` — server.py L4938~4947에서 추출
    - `json_response(handler, data, status=200)` — CORS + Content-Type + JSON 직렬화 공통화
    - `cors_origin(headers, default_port)` — server.py `_cors_origin` 로직 추출
    검증: server.py에서 `from src.server_utils import find_free_port` 임포트하여 기존 동작 동일 확인

### Phase 2: 오피스 전용 서버

- [x] **Task 2: office_server.py 신규 — 오피스 전용 HTTP 서버** ✅
    파일: `.ai_monitor/office_server.py` (신규)
    방법:
    - BaseHTTPRequestHandler 기반 경량 서버
    - 9010~9027 범위에서 `find_free_port`로 자동 포트 탐색
    - `/api/office/*` → office_api.py 위임 (기존 핸들러 재사용)
    - `/api/pty/*` → PTY 프록시 또는 직접 처리 (오피스 터미널 전용)
    - `/api/experience/*`, `/api/agent/chat/*` 등 오피스에서 필요한 공유 API 포워딩
    - 정적 파일 서빙 (vibe-view/dist/)
    - 시작 시 stdout 첫 줄에 `PORT:<실제포트>` 출력 → 부모 프로세스가 읽음
    - `--classic-port <N>` 인자: 클래식 서버 포트 (공유 API 프록시용)
    검증: `python office_server.py` 단독 실행 → `/api/office/profiles` 200 OK

- [x] **Task 3: office_server에 PTY 연동 추가** ✅ (클래식 프록시 경유 — Task 2에서 이미 처리)
    파일: `.ai_monitor/office_server.py`
    방법:
    - 오피스 PTY 세션 관리 (`/api/pty/office/spawn`, `/api/pty/office/sessions`)
    - pty-server (Node.js) 인스턴스를 오피스 서버가 직접 관리하거나, 기존 PTY 서버에 프록시
    - 터미널 네임스페이스 `O` 접두사 유지
    검증: 오피스 창에서 터미널 세션 생성/입출력 동작

### Phase 3: server.py 수정 (클래식 전담)

- [x] **Task 4: server.py — 오피스 서버 서브프로세스 관리 추가** ✅
    파일: `.ai_monitor/server.py`
    방법:
    - `/api/office/launch` 핸들러 수정:
      1. `office_server.py`를 서브프로세스로 시작
      2. stdout에서 `PORT:<N>` 읽어 실제 포트 확인
      3. `dashboard_window.py`에 오피스 서버 포트 전달
    - `_child_procs`에 오피스 서버 프로세스 등록 → 종료 시 자동 정리
    - `/api/office/restart` 엔드포인트 추가: 오피스 서버만 kill + 재시작
    - `_find_free_port` → `from src.server_utils import find_free_port`로 교체
    검증: 오피스 실행 → 클래식 대시보드 영향 없음 확인

- [x] **Task 5: server.py — /api/office/* 라우팅 제거** ✅
    파일: `.ai_monitor/server.py`
    의존: Task 4 완료 후
    방법:
    - do_GET L2825, do_POST L3385, do_PUT L3350, do_DELETE L3363의 `/api/office/` 분기 제거
    - office_api import 제거 (server.py에서만 — office_server.py에서 사용)
    검증: 클래식 서버에서 `/api/office/profiles` → 404 확인 (오피스 서버에서만 서빙)

### Phase 4: 프론트엔드 + dashboard_window 수정

- [x] **Task 6: dashboard_window.py — 오피스 서버 포트 수신** ✅ (기존 sys.argv[1] 포트 인자로 이미 호환)
    파일: `.ai_monitor/dashboard_window.py`
    방법:
    - CLI 인자: `dashboard_window.py <classic_port> <tab> [office_port]`
    - office 탭일 때 `office_port`로 연결 (없으면 classic_port 폴백)
    - URL: `http://localhost:{office_port}/?page=office`
    검증: 오피스 창이 오피스 서버 포트에 연결되어 로드

- [x] **Task 7: 프론트엔드 — 오피스 API 라우팅 확인** ✅ (window.location 기반이라 변경 불필요)
    파일: `.ai_monitor/vibe-view/src/services/officeApi.ts`, `useOfficePty.ts`
    방법:
    - officeApi.ts는 이미 상대 URL 사용 (`/api/office/...`) → 변경 불필요 (오피스 서버에서 서빙되면 자동)
    - useOfficePty.ts도 PTY_BASE='' (상대 URL) → 변경 불필요
    - useVibeData.ts의 API_BASE는 `window.location` 기반 → 오피스 서버 포트로 자동 연결
    - 단, 클래식 전용 API (파일 탐색기, 칸반 등)가 오피스에서 필요한 경우 프록시 확인
    검증: Playwright로 오피스 창 열어서 프로필 CRUD, 채팅, 터미널 정상 동작

### Phase 5: 안정화

- [x] **Task 8: 오피스 서버 헬스체크 + 자동 재시작** ✅
    파일: `.ai_monitor/server.py`
    방법:
    - 기존 watchdog 패턴 재사용: 주기적으로 오피스 서버 프로세스 생존 확인
    - 크래시 감지 시 자동 재시작 (최대 3회)
    - `/api/office/status` 엔드포인트: 오피스 서버 상태(포트, PID, uptime) 반환
    검증: 오피스 서버 수동 kill → 자동 재시작 확인

## ⚠️ 예상 위험 및 대응
- **공유 API 접근**: 오피스에서 클래식 전용 API 필요 시 → office_server가 클래식 서버로 프록시
- **포트 충돌**: 양쪽 모두 자동 탐색이라 충돌 없음. 범위도 분리 (9000대 vs 9010대)
- **EXE 빌드**: office_server.py도 별도 EXE로 빌드 필요 → pyinstaller spec 수정

---
**작성일:** 2026-04-12
**상태:** ✅ 완료 (2026-04-12)
