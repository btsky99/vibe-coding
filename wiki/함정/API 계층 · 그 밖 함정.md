---
title: API 계층 · 그 밖 함정
type: 함정
sources:
  - .ai_monitor/api/_common.py:36
  - .ai_monitor/api/config_api.py:25
  - .ai_monitor/api/config_api.py:57
  - .ai_monitor/api/files_api.py:50
related: []
confidence: high
updated: 2026-08-15
---

# API 계층 · 그 밖 함정

## 한 줄

클라이언트(WebView UI)가 응답을 기다리다 fetch를 취소하면

> 자동 합성 (코드 주석 4건 · 파일 3개 · 추출 b28ef16).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 코드에 박힌 지식

## `.ai_monitor/api/_common.py`

### json_response `[WHY]` `[과거사고]`

[과거사고 2026-08-01] 클라이언트(WebView UI)가 응답을 기다리다 fetch를 취소하면
여기 write가 ConnectionAbortedError(WinError 10053)로 터진다. 이건 정상 상황인데,
예외가 핸들러 밖으로 나가면 BaseHTTPRequestHandler가 스택 전체를 stderr에 찍는다.
UI 렌더러가 메모리 압박으로 느려질수록 취소가 늘어 → 48시간에 traceback 7,200건,
server.log 61MB → 로그 쓰기 I/O가 서버를 더 느리게 만드는 악순환이 됐다.
[WHY 흡수] 상대가 이미 끊은 소켓이라 재시도/에러응답 모두 불가능. 호출자가 할 수 있는
일이 없으므로 조용히 종료한다. ConnectionError 계열만 좁게 잡아 진짜 버그(직렬화
실패 등)는 그대로 올라가게 둔다.

출처: `.ai_monitor/api/_common.py:36`

## `.ai_monitor/api/config_api.py`

### handle_get `[과거사고]`

GET /api/config — config.json 로드 + 활성 프로젝트 컨텍스트 주입.
[과거사고 방지] project_unresolved=True면 UI가 '프로젝트 폴더 선택'을 유도(설치본 빈 패널 사고).
이 두 값은 런타임에 갱신되는 전역이라 wrapper가 호출 시점 값을 주입해야 한다(디폴트 바인딩 금지).
[맥포팅 2026-07-22] 프론트 FileExplorer는 last_path로 currentPath를 초기화한다. 저장된
last_path가 이 OS에서 무효(맥의 'D:/..' 등)면 파일탐색기가 빈 목록·잘못된 경로를 표시하므로,
해석된 current_root로 정규화해 내려준다 — 백엔드 project_root(project-info)와 단일 진실로 일치.

출처: `.ai_monitor/api/config_api.py:25`

### handle_update `[과거사고]`

POST /api/config/update — {키:값} 부분 병합 저장.
[과거사고 방지] last_path 변경 시 projects.json MRU도 동기화 — 배포 버전에서 프로젝트
전환 후 재시작해도 올바른 PROJECT_ROOT 사용(설치본 빈 패널 사고 계열).

출처: `.ai_monitor/api/config_api.py:57`

## `.ai_monitor/api/files_api.py`

### handle_get `[과거사고]`

숨김 항목 필터링 (주요 설정 파일 제외)
[과거사고] 정확히 '.env'만 허용해 Next.js 표준인 '.env.local'/'.env.production'/
'.env.example'이 탐색기에서 통째로 사라짐 (OnS 프로젝트 사고). 특정 프로젝트에
종속되지 않게 '.env'로 시작하는 모든 파일을 노출한다 — 바이브 코딩 이식성 원칙.

출처: `.ai_monitor/api/files_api.py:50`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: WHY, 과거사고 -->
