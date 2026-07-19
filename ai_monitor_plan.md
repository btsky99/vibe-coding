<!--
FILE: ai_monitor_plan.md
DESCRIPTION: LAN 자동 공유(A안) 구현 계획 — 클로드 자율 판단으로 파일+세션요약을 페어PC 자동 전송.

REVISION HISTORY:
- 2026-07-19 Claude: 신규. LAN 브리지 Phase 2(채팅, 2df6826·53867eb) 완료 → 교체.
  브레인스토밍 승인 (memory: project_lan_auto_share.md, A안 자율판단+마스터토글 OFF).
-->

# LAN 자동 공유 (A안) — 구현 계획

브레인스토밍 승인: 2026-07-19 (A안, 클로드 자율 판단 발송). 설계 메모리: `project_lan_auto_share.md`.
원칙: 클로드가 공유가치 판단 시 페어링된 온라인 PC로 **파일+세션요약** 자동 전송. 🔴 마스터 토글 기본 OFF + 전송 후 명시 리포트 + 민감파일 필터.

기존 자산 재사용: `POST /api/lan/send`(파일), `POST /api/lan/chat-send`(채팅), `GET /api/lan/status`(피어), `_proxy`/`_self_id` 헬퍼.

---

## Phase 1 — 서버측 auto-share 엔드포인트 (안전장치 강제)

[ ] Task 1: config에 마스터 토글 기본 OFF 추가
    파일: .ai_monitor/data/config.json + config 기본값 로직
    방법: `lan_auto_share_enabled: false` 키 추가. 기본값 로더에도 false 명시(누락 시 OFF).
    검증: 키 없음/false일 때 auto-share가 no-op 되는지 Task 3에서 확인.
    의존성: 없음

[ ] Task 2: 민감파일 필터 + dedup 유틸 추가
    파일: .ai_monitor/api/lan_api.py (모듈 상단 헬퍼)
    방법: `_is_sensitive(path)` — .env/credentials/*secret*/*.pem/*token* 차단 목록.
          `_dedup_seen`(data_dir/lan_share_seen.json) — 파일해시+요약해시 기록, 재발송 차단.
          레이트리밋 — 분당 상한(타임스탬프 deque, 메모리).
    검증: .env 경로 필터됨, 같은 파일 2회 요청 시 2번째 skip.
    의존성: 없음

[ ] Task 3: /api/lan/auto-share 엔드포인트 구현
    파일: .ai_monitor/api/lan_api.py (handle_post 분기 추가)
    방법: 입력 {files:[path...], summary:str, peer_id?:str}.
          ① 토글 OFF → {ok:false, reason:'disabled'} no-op. ② status로 온라인 페어 조회 →
          미지정+1대면 자동, 여러 대면 {ok:false, reason:'ambiguous', peers:[...]}. ③ 파일 각각
          _is_sensitive/dedup/캡 통과분만 /send. ④ summary 8KB 절단+dedup 후 /chat-send.
          ⑤ 리포트 {ok, peer, sent_files, skipped, summary_sent} 반환.
    검증: 브리지 OFF→no-op, 토글 OFF→disabled, 페어 오프라인→graceful, 정상→전송+리포트.
    의존성: Task 1, Task 2 완료 후

[ ] Task 4: 이식성/줄수 확인
    파일: .ai_monitor/api/lan_api.py
    방법: project_id 비의존 확인, wc -l ≤ 1500, py_compile+ruff(E9,F821,F823).
    검증: 구문/린트 통과, 줄수 여유.
    의존성: Task 3 완료 후

## Phase 2 — 클로드 판단 스킬 (자율 트리거)

[ ] Task 5: /vibe-share 스킬 작성
    파일: .claude/skills/vibe-share/SKILL.md
    방법: 공유가치 판단 기준(픽스완료/빌드산출물/요약요청)과 절차 명세:
          토글 확인 → /api/lan/auto-share 호출 → ambiguous면 대상 명시 후 재호출 →
          전송 후 `📤 [자동공유] X 외 N건 + 요약 → <peer> 전송함` 출력.
          토글 OFF면 발송 대신 "공유할까?" 제안만. 표준 헤더+한글.
    검증: 스킬 목록 노출, 절차가 auto-share 계약과 일치.
    의존성: Task 3 완료 후

[ ] Task 6: 판단 기준 문서 연결 (선택)
    파일: project_lan_auto_share.md 갱신(구현완료) + 필요시 CLAUDE.md 1줄 포인터
    방법: 자동공유 판단 기준 요약. 스킬 설명으로 충분하면 생략(과설계 금지).
    검증: 다음 세션 클로드가 기준 파악 가능.
    의존성: Task 5 완료 후

## Phase 3 — 검증 + 배포

[ ] Task 7: E2E 로컬 검증
    방법: 브리지 ON+페어링 2인스턴스에서 auto-share → 파일+요약 왕복 확인.
          토글 OFF/브리지 OFF/민감파일/dedup 4개 방어 케이스 확인.
    검증: 정상 전송 + 4개 방어 케이스 통과.
    의존성: Task 5 완료 후

[ ] Task 8: /vibe-release 배포
    방법: Step 0~0.5(로컬 EXE+smoke) → 버전증가 → 커밋 → 푸시 → CI 확인.
          🔴 새 파일 vibe-share/SKILL.md는 install_skills 복사 대상 — 경로 확인.
    검증: CI 빌드 성공 + Release 게시.
    의존성: Task 7 완료 후

---

## 의존성 요약
- Task 1, 2 병렬 → Task 3 → Task 4
- Task 3 후 Task 5 → Task 6/7 → Task 8
