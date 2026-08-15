---
title: PostgreSQL 저장 계층 함정
type: 함정
sources:
  - .ai_monitor/src/pg_base.py:147
  - .ai_monitor/src/pg_base.py:231
  - .ai_monitor/src/pg_office.py:15
  - .ai_monitor/src/pg_office.py:303
  - .ai_monitor/src/pg_schema.py:386
related: []
confidence: high
updated: 2026-08-15
---

# PostgreSQL 저장 계층 함정

## 한 줄

절전/네트워크 단절로 established 커넥션의 TCP 소켓이 죽으면

> 코드 주석에서 자동 합성 (원료 5건 · 파일 3개 · 추출 7cbf195).
> 🔴 **여기를 고치기 전에** 원본 주석을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## `.ai_monitor/src/pg_base.py`

### 모듈 상단 `[과거사고]` `[불변식]`

[과거사고 2026-07-20] 절전/네트워크 단절로 established 커넥션의 TCP 소켓이 죽으면
라이브니스 체크 SELECT 1이 recv()에서 무한 블록(hang)된다 — connect_timeout은 최초
연결에만 적용돼 이미 맺어진 소켓엔 무효. 이 hang이 heartbeat 데몬 run_loop을 16시간
동결(loop_beat_at 00:15 고정)시키고 9019 싱글턴 락을 물고 안 놔 dev/설치본 전 인스턴스
auto를 마비시켰다. TCP keepalive를 켜면 OS 스택이 죽은 피어를 ~30-60s 내 감지해 recv()가
에러를 반환 → 아래 except가 커넥션 폐기·재연결을 유도(무한 hang → 유한 실패 전환).
[불변식] psycopg2.connect 두 경로(_get_pg_conn·get_pool_conn)에 동일 적용해야 함 —
한쪽만 고치면 다른 경로가 여전히 죽은 소켓에서 hang(단일 소스로 강제).

출처: `.ai_monitor/src/pg_base.py:147`

### get_pool_conn `[과거사고]`

[과거사고 2026-07-20] _get_pg_conn과 동일한 죽은-소켓 hang 취약점 — keepalive 필수.

출처: `.ai_monitor/src/pg_base.py:231`

## `.ai_monitor/src/pg_office.py`

### _session_pid_and `[과거사고]`

active_session_context WHERE절용 project_id 경계 조각.
[과거사고 2026-07-15] 훅이 여러 프로젝트에 공유 등록되는데 이 테이블의
매칭이 terminal_id로만 이뤄져 T0끼리 프로젝트를 넘나들며 덮어쓰기/브리핑 오염 발생.
project_id가 주어지면 반드시 경계로 강제한다. 빈 값이면 레거시 호환(무필터).

출처: `.ai_monitor/src/pg_office.py:15`

### get_interrupted_sessions `[과거사고]`

미완료(active) 상태인 세션 목록을 반환한다.
새 세션 시작 시 UserPromptSubmit에서 호출.
terminal_id/project_id 필터는 선택적 — 빈 문자열이면 무필터(레거시 호환).
[과거사고 2026-07-15] project_id 무필터로 다른 프로젝트의 중단 세션이
이 프로젝트 복구 브리핑에 섞여 나옴 — 훅 경유 호출은 반드시 project_id 전달.

출처: `.ai_monitor/src/pg_office.py:303`

## `.ai_monitor/src/pg_schema.py`

### ensure_schema `[과거사고]` `[불변식]`

)
execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_source ON zettel_links (source_id);")
execute_raw("CREATE INDEX IF NOT EXISTS idx_zettel_links_target ON zettel_links (target_id);")
NOTIFY 트리거 — 노트 변경 시 실시간 알림
[과거사고] 2026-07-19: title을 통째로 payload에 실어 pg_notify 8000바이트 한도를
초과 → 트리거가 AFTER INSERT/UPDATE 트랜잭션을 롤백시켜 zettel 노트 쓰기가
연쇄 실패하고 server.log가 'payload string too long'으로 폭주(41MB). 세션 요약처럼
본문이 title에 들어간 노트가 방아쇠. 게다가 'zettel_change' 채널을 LISTEN하는
소비자가 코드에 없어 title 전달은 순수 손해였음.
[불변식] payload는 bounded여야 함 — title은 left(...,200)으로 상한 고정.
소비자가 생겨도 '변경 감지 → id로 재조회'만 하면 되므로 title 원문은 불필요.
execute_raw("""

출처: `.ai_monitor/src/pg_schema.py:386`

## 확인법

```bash
python scripts/wiki_lint.py        # 이 페이지의 출처가 아직 살아 있는지
python scripts/wiki_build.py       # 원본 주석 변경분 재합성
```

<!-- tags: 과거사고, 불변식 -->
