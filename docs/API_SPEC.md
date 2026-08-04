"""
FILE: docs/API_SPEC.md
DESCRIPTION: Vibe-Coding (AI Monitor) REST API 상세 명세서
REVISION HISTORY:
- 2026-08-03 Codex: Discord 터미널별 토큰 설정 GET/POST API 추가
- 2026-08-03 Codex: Discord API를 공용 토큰·Node ID·터미널별 채널 binding 계약으로 교정
- 2026-08-03 Codex: 사용량 권고를 포함하는 `/api/agent-quota` 계약 추가
- 2026-03-19 Gemini: 최초 작성. v5.0 기준 모든 엔드포인트 정리.
"""

# 📋 Vibe-Coding REST API Specification (v5.0)

이 문서는 Vibe-Coding 프로젝트의 중앙 서버(`server.py`)가 제공하는 모든 REST API 엔드포인트에 대한 상세 명세입니다.

---

## 1. Hive API (하이브 마인드 관리)
에이전트의 활동 로그, 사고 과정, 메시징 및 태스크 관리를 담당합니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/hive/log/pg` | PostgreSQL에 활동 로그 기록 |
| **POST** | `/api/hive/thought/pg` | PostgreSQL에 사고 과정(Thought) 기록 |
| **POST** | `/api/message` | 에이전트 간 ITCP 메시지 전송 |
| **GET** | `/api/tasks` | 전체 태스크 목록 조회 |
| **POST** | `/api/tasks` | 신규 태스크 생성 |
| **GET** | `/api/orchestrator/summary` | 하이브 상태 요약 브리핑 조회 |

---

## 2. Vibe API (실시간 모니터링 및 알림)
Mission Control UI와 cmux 호환 CLI 시스템을 위한 실시간 피드백 API입니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/vibe/notify` | 시스템 트레이 및 대시보드 알림 생성 |
| **POST** | `/api/vibe/progress` | 에이전트 진행률(0-100) 업데이트 |
| **POST** | `/api/vibe/status` | 에이전트 현재 상태(텍스트/아이콘) 업데이트 |
| **POST** | `/api/vibe/log` | 에이전트 전용 로그 기록 |
| **GET** | `/api/vibe/sidebar` | 대시보드 사이드바 전체 상태 조회 |

---

## 3. MUX API (터미널 멀티플렉서 제어)
에이전트 터미널에 텍스트를 직접 주입하거나 제어하는 cmux 스타일 API입니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/mux/send-text` | 특정 터미널 슬롯에 텍스트 주입 및 실행 |
| **POST** | `/api/mux/send-key` | 특정 터미널 슬롯에 특수 키(Enter, Ctrl+C 등) 전송 |
| **GET** | `/api/mux/terminals` | 현재 활성화된 터미널 슬롯 목록 조회 |

---

## 4. Dispatcher API (자율 태스크 분배)
멀티 에이전트 간의 작업을 자동으로 조율하고 검증을 요청합니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/dispatcher/dispatch` | 입력된 페이로드를 바탕으로 최적 에이전트 배정 |
| **POST** | `/api/dispatcher/verify` | 다른 에이전트에게 결과물 크로스 검증 요청 |
| **GET** | `/api/dispatcher/history` | 과거 디스패치 이력 조회 |

---

## 5. System & Utility API
시스템 설정, 파일 관리 및 기타 편의 기능을 제공합니다.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/api/files` | 특정 경로의 파일/폴더 목록 조회 |
| **POST** | `/api/save-file` | 파일 내용 저장 |
| **GET** | `/api/config` | 시스템 전역 설정 조회 |
| **POST** | `/api/config/update` | 시스템 전역 설정 업데이트 |
| **GET** | `/api/config/discord` | Discord 공용 토큰 설정 여부와 Node/ACL/터미널 채널 binding 조회(토큰 원문 비노출) |
| **POST** | `/api/config/discord` | Discord 공용 토큰·Node ID·서버/사용자 ACL·T1~T9 채널 binding 저장 |
| **POST** | `/api/launch` | 특정 에이전트(Claude/Gemini/Codex) 터미널 실행 |
| **POST** | `/api/shutdown` | 서버 및 관련 프로세스 안전 종료 |

---

## 6. Quota Policy API

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/api/agent-quota` | Claude/Codex 쿼터 snapshot과 provider별 작업 크기 권고 반환 |

각 provider의 `advice`는 `level`, `recommended_task_size`, `action`, `reason`,
`blocks_new_work`, `requires_approval`을 제공한다. 초기 guard mode는 `warn`이며 쿼터를
조회하지 못하면 `level=unavailable`, `blocks_new_work=false`로 fail-open한다.

---

## 7. Connector Runtime API

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/agent/chat/bus` | 외부 connector 발화를 기록하고 백그라운드 소비자에 전달 |
| **GET** | `/api/agent/chat/feed` | 터미널별 메시지와 `reply_to_seq` 상관 응답을 seq 기준 조회 |
| **POST** | `/api/pty/write` | 실행 중인 PTY 세션에 검증된 텍스트 입력 |
| **GET** | `/api/pty/output` | PTY 출력 버퍼를 seq 기준으로 조회 |

외부 connector는 반드시 ACL과 이벤트 중복 방지를 먼저 통과한 뒤 chat bus만 호출한다.
PTY API는 서버 내부 버스 소비자의 transport adapter 및 로컬 UI가 사용하며, connector가
직접 호출하지 않는다.

---
**기본 포트**: 9000 (설정에 따라 가변)
**데이터 인코딩**: `application/json;charset=utf-8`
