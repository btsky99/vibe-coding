---
name: 반복 안티패턴 기록
description: 이 프로젝트에서 발견된 반복 안티패턴 목록 (미래 리뷰에서 우선 점검)
type: project
---

## 1. JSON 문자열 f-string 직접 SQL 삽입
- `insert_pg_log`에서 `meta_json`을 `_sql_text()` 거치지 않고 `'{meta_json}'::jsonb`로 직접 삽입
- `metadata` dict 값에 작은따옴표 포함 시 SQL 파싱 오류 또는 인젝션 위험
- 수정 방향: `_sql_json(metadata or {})` 사용

## 2. 무한루프 최외곽 except에서 sleep(60) 중복
- `_agent_sync_daemon`의 외부 except가 내부 sleep(60) 이후 또 sleep(60) 호출
- 예외 발생 시 최대 120초 지연 발생

## 3. 하트비트마다 pg_logs INSERT
- POST /api/agents/heartbeat가 호출될 때마다 `record_heartbeat` + `insert_pg_log` 2회 DB 쓰기
- 에이전트가 많고 heartbeat 주기가 짧으면 pg_logs 테이블이 무제한 증가 (보존 정책 없음)

## 4. handle_stop의 하드코딩된 agent_id
- `record_heartbeat('cli_agent', ...)` — 실제 중지된 에이전트 이름(`chosen_cli`) 아닌 고정 문자열 사용
