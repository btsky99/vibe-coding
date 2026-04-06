---
name: 반복 발견 안티패턴
description: 여러 리뷰에서 반복적으로 발견된 안티패턴 목록 — 향후 리뷰 시 우선 점검 대상
type: project
---

## 오프라인 에이전트 감지 로직 중복 (2026-04-05 최초 발견)
- AgentMonitorPanel과 TaskBoardPanel 양쪽에 `(Date.now() - new Date(last_beat).getTime()) / 1000 > 300` 로직이 독립적으로 존재.
- TaskBoardPanel은 렌더 내 JSX 표현식에서 `.some()` + `.filter()` 두 번 호출 (동일 연산 반복).
- 권장: 공유 훅 `useOfflineAgents(agents)` 또는 유틸 함수로 추출.

## 렌더 중 고비용 연산 (2026-04-05 최초 발견)
- TaskBoardPanel `OrgAgentCard` 컴포넌트 내 `color` 계산을 즉시실행함수(IIFE)로 인라인 처리.
- useMemo/상수 맵 대신 렌더마다 Date 객체 생성 + 산술 연산 수행.

## key={index} 사용 (2026-04-05 최초 발견)
- AgentMonitorPanel RECENT ACTIVITY 섹션: `key={\`log-\${i}\`}` — 인덱스 기반 키.
- 로그 목록이 갱신되면 불필요한 DOM 재생성 발생 가능.

## useMemo 훅 규칙 위반 (2026-04-05 최초 발견)
- AgentMonitorPanel: `offlineAgents` useMemo가 얼리 리턴(loading/empty 분기) 이후에 선언됨.
- React Hooks 규칙 위반 — 조건부 실행 경로에 따라 훅 호출 순서가 달라질 수 있음.

## N+1 쿼리 — 루프 내 개별 SELECT (2026-04-06 최초 발견, 백엔드)
- `import_from_vault`: vault 파일 루프 내에서 파일마다 `_get_note_raw(id)` 1회 SELECT.
- `export_to_vault`: 노트 루프 내에서 `_format_links_section(id)` → get_links + get_backlinks = 2 SELECT.
- `get_stats` 허브 계산: 노트마다 zettel_links 서브쿼리.
- 공통 패턴: 루프 전에 관련 테이블을 한 번에 로드 후 dict로 O(1) 조회.

## bash 명령 전체를 이벤트 데이터로 전달 (2026-04-06 최초 발견)
- `claude_hook.py`: `git commit` 감지 시 bash 명령 문자열 전체를 `message` 필드로 전달.
- `zettel_capture.py`의 Conventional Commit 정규식이 `git commit -m "..."` 형태를 받아 파싱 실패.
- 수정 방향: hook에서 커밋 메시지 부분만 추출 후 전달.

## 함수 내부 표준 라이브러리 임포트 (2026-04-06 최초 발견)
- `_extract_keywords`에서 `from collections import Counter` 함수 내부에 위치.
- `_spawn_zettel_capture`에서 `import json as _json` — 최상단 `import json`과 중복.
- 표준 라이브러리는 항상 모듈 최상단에 임포트.
