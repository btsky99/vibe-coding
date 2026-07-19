---
name: vibe-share
description: >
  LAN 자동 공유 — 작업한 파일과 세션 요약을 같은 네트워크의 페어링된 내 다른 PC로 전송.
  Use when: "이거 보내줘", "옆 PC로 공유", "다른 컴퓨터로 전달", 클로드가 픽스/빌드 산출물을
  공유할 가치가 있다고 자율 판단했을 때. 수동 발송(LanPanel) 대신 API로 자동 전송.
allowed-tools: Bash, Read
user-invocable: true
---

<!--
FILE: .claude/skills/vibe-share/SKILL.md
DESCRIPTION: LAN 자동 공유 스킬 — 클로드가 파일+세션요약을 페어PC로 자동 전송.
             서버측 관문 /api/lan/auto-share(민감필터·dedup·레이트리밋·토글 강제)를 호출한다.

REVISION HISTORY:
- 2026-07-19 Claude: 신규 — LAN 자동 공유 A안 Task 5. 설계 memory: project_lan_auto_share.md.
-->

# vibe-share (LAN 자동 공유)

작업 산출물(파일)과 이번 세션 작업 요약을 **같은 LAN의 페어링된 내 다른 PC**로 자동 전송한다.
수동 LanPanel 대신 서버 API를 호출해 클로드가 직접 보낸다.

## 🚦 절대 원칙 — 마스터 토글 OFF면 발송 금지

발송 전 항상 서버가 토글을 강제하지만, 스킬 레벨에서도 지킨다:
- 응답이 `{ok:false, reason:'disabled'}`면 **절대 재시도하지 말고**, 사용자에게
  "자동 공유가 꺼져 있어. LAN 탭에서 켤까?"라고 **제안만** 한다.
- 사용자가 "보내지 마"라고 하면 그 세션에서 다시 시도하지 않는다.

## 언제 자동 공유하나 (자율 판단 기준)

아래에 해당하고 **페어 PC가 온라인**일 때 공유 가치가 있다고 본다:
- 버그 픽스/기능 구현을 **완료**해 결과 파일이 확정됐을 때
- 빌드/릴리즈 산출물(dist EXE 등)이나 다른 PC에서 이어받을 파일이 생겼을 때
- 사용자가 명시적으로 "보내줘/공유" 요청했을 때 (이때는 토글 OFF여도 켤지 물어봄)

공유하지 않음: 미완성 중간물, 민감 파일(.env·키·토큰 — 서버가 어차피 필터), 사소한 변경.

## 실행 절차

### 1. 대상 파일 + 요약 준비
- files: 방금 확정된 절대경로 목록 (예: 수정한 소스, 빌드 산출물)
- summary: 이번 세션 **작업 요약**(원문 전체 아님, 8KB 이내). 무엇을 왜 어떻게 바꿨는지 3~5줄.
  경로·키 등 민감정보는 요약에서 뺀다.

### 2. auto-share 호출
서버 포트는 9000부터 살아있는 것을 쓴다(대개 9000).
```bash
curl -s -X POST http://127.0.0.1:9000/api/lan/auto-share \
  -H "Content-Type: application/json" \
  -d '{"files":["D:/vibe-coding/.ai_monitor/api/lan_api.py"],
       "summary":"lan_api에 auto-share 엔드포인트 추가 — 민감필터+dedup+레이트리밋."}'
```
peer_id는 생략(온라인 페어 1대면 자동 선택). 여러 대면 아래 ambiguous 처리.

### 3. 응답별 처리
- `{ok:true, peer, sent_files, skipped, summary_sent}` →
  화면에 명시: `📤 [자동공유] <sent_files 개수>건 + 요약 → <peer> 전송함` (skipped 있으면 사유 요약).
- `{ok:false, reason:'disabled'}` → 발송 안 함, 켤지 제안만.
- `{ok:false, reason:'bridge_off'}` → 브리지 꺼짐. 조용히 넘어가거나 켤지 제안.
- `{ok:false, reason:'no_peer'|'peer_offline'}` → 페어 오프라인. 발송 보류(에러 아님).
- `{ok:false, reason:'ambiguous', peers:[...]}` → 어느 PC로 보낼지 사용자에게 확인하거나
  가장 관련 있는 peer_id를 골라 `peer_id` 지정 후 2번 재호출.
- `{ok:false, reason:'rate_limited'}` → 분당 상한 초과. 잠시 후로 미룸.

## 🔒 안전장치 (서버가 강제 — 스킬은 신뢰)
- 민감파일(.env/secret/token/*.pem/*.key 등)은 서버가 skipped 처리 — 스킬이 우회 못함.
- 같은 파일/요약(내용 해시)은 재발송 안 됨(dedup). 파일이 바뀌면 재발송 허용.
- 분당 발송 상한(레이트리밋)으로 스팸/무한루프 차단.

## 판단이 서지 않으면
확신이 없으면 자동 발송하지 말고 **"이 파일들 옆 PC로 보낼까?"**라고 먼저 물어본다.
자율 판단의 목적은 편의지 강제가 아니다 — 오발송보다 한 번 묻는 게 낫다.
