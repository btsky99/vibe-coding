---
name: pg_store 코딩 컨벤션
description: pg_store.py의 SQL 실행 패턴과 커넥션 관리 방식
type: project
---

- SQL 파라미터는 `_sql_text()` 수동 이스케이프 (psycopg2 파라미터 바인딩 미사용)
- `_pg_conn`은 싱글 글로벌 커넥션, `autocommit=True`
- `execute()` 래퍼가 모든 DML/DDL에 사용됨
- JSON 값은 `_sql_json()` 또는 `_sql_text()` + `::jsonb` 캐스팅으로 처리
- `_pg_conn_lock`은 커넥션 획득 시에만 사용, 쿼리 실행 중에는 락 해제

**Why:** psycopg2 파라미터 바인딩 대신 수동 이스케이프를 사용하는 이유는 psql subprocess 폴백 경로와 동일한 SQL 문자열을 재사용하기 위함.
