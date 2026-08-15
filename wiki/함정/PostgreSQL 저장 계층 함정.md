---
title: PostgreSQL 저장 계층 함정
type: 함정
sources:
  - .ai_monitor/src/pg_base.py:147
  - .ai_monitor/src/pg_base.py:231
  - .ai_monitor/src/pg_office.py:15
  - .ai_monitor/src/pg_office.py:303
  - .ai_monitor/src/pg_schema.py:386
  - incident_ledger  # 사고 5건
related: []
confidence: high
updated: 2026-08-15
---

# PostgreSQL 저장 계층 함정

## 한 줄

절전/네트워크 단절로 established 커넥션의 TCP 소켓이 죽으면

> 자동 합성 (코드 주석 5건 · 파일 3개 · 사고 장부 5건 · 추출 b28ef16).
> 🔴 **여기를 고치기 전에** 원본(주석 또는 사고 장부)을 먼저 고칠 것 — 다음 빌드에 덮어써진다.

## 🔴 밟았던 것 (사고 장부)

### 동적 포트 폴백(5433 점유→5434) 발동 시 psycopg2 풀/psql 폴백이 stale 5433으로 접속 실패 — pg_base.PG_PORT가 import 시점 1회 고정이라 미반영

- **원인** — pg_base.PG_PORT는 import-time env 평가. os.environ write-back은 자식 프로세스 fresh import만 반영, server 내부 pg_base엔 무효. DB는 set_project_db push 있으나 포트는 대응 push 부재(비대칭)
- **수정** — pg_base.set_pg_port(port) push 함수 신설(set_project_db와 대칭). ensure_postgres_running이 포트 확정 직후 호출, 포트 변경 시 단일+풀 커넥션 폐기. 세 소비처(_get_pg_conn/get_pool_conn/_run_psql) 단일 진실소스화
- 출처: `incident_ledger` · 최초 2026-07-07

### psql -c argv 한글 리터럴 → invalid byte sequence 0xb0, 쿼리 전체 실패

- **원인** — Windows subprocess가 -c 인자를 cp949로 인코딩해 psql에 전달, 서버는 UTF8이라 불일치. msvcrt ANSI 변환은 argv 경로에서 회피 불가
- **수정** — SQL을 UTF-8 임시파일에 쓰고 psql -f + PGCLIENTENCODING=UTF8로 실행 (auto_metrics.py _run_query)
- 출처: `incident_ledger` · 최초 2026-07-19

### zettel notify 'payload string too long' 폭주 (server.log 41MB)

- **원인** — notify_zettel_change 트리거가 title 원문을 pg_notify payload에 실어 8000바이트 초과 (한글 3948자≈11.8KB). AFTER 트리거 롤백으로 노트 쓰기 연쇄 실패. LISTEN 소비자도 없음
- **수정** — title을 left(coalesce(title,''),200)으로 상한 고정. pg_schema.py 수정 + 라이브 DB CREATE OR REPLACE 즉시 반영 (865eca7)
- 출처: `incident_ledger` · 최초 2026-07-19

### PG 터널 경로만 격리하려 했으나 pg_hba 규칙이 매치되지 않아 LEAK

- **원인** — pg_hba는 목적지가 아니라 소스 주소로 매칭한다. 리눅스 루프백에서 127.0.0.2:5433로 접속해도 커널이 소스를 127.0.0.1로 잡아 client_addr=127.0.0.1이 된다 -> host ... 127.0.0.2/32 규칙은 영원히 매치되지 않는다. 부수 함정: postgresql.conf를 고쳐도 include_dir conf.d가 더 뒤에서 읽혀 99-lowmem.conf가 listen_addresses를 덮어쓴다(PG는 마지막 값 채택)
- **수정** — 격리 시도 전부 롤백(백업본 복원+드롭인 제거, 서비스 3종 생존 확인). 작동하지 않는 보안 설정은 보호받고 있다는 착각을 유발하므로 남기지 않는다. 근본 해결은 trust 제거+전 클라이언트 비번화이나 서버의 vibe-bridge/vibe-status가 pg_base.py(비번 파라미터 없음)를 쓰므로 코드 선행 필요 - 별도 과제
- 출처: `incident_ledger` · 최초 2026-08-08

### PostgreSQL 루프백 접속이 아무 비밀번호로나 성공 (틀린 비밀번호로도 붙음)

- **원인** — pg_hba.conf 의 host all all 127.0.0.1/32 trust. 최소 권한 계정을 만들어도 무의미하고, 서버에서 코드를 실행하게 된 공격자가 postgres 슈퍼유저로 직행할 수 있다
- **수정** — 관제 계정만 scram-sha-256 을 강제하는 규칙을 trust 라인 **앞에** 삽입(pg_hba 는 첫 매칭이 이긴다). trust 자체를 지우면 어떤 서비스가 비밀번호 없는 연결에 의존하는지 모른 채 운영 중인 것을 멈추게 되므로, 근본 정리는 영향 조사 후 별건으로 분리
- 출처: `incident_ledger` · 최초 2026-08-09

## 코드에 박힌 지식

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
