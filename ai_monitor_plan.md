# 하이브 마인드 기능 추가 계획
> 작성일: 2026-03-01 | 상태: 승인됨

## 목표
3가지 기능 순차 구현 (기능4 시각화는 이미 완성)

---

## [✅] Task 1: 서버 자동 재시작
**파일:** `scripts/hive_watchdog.py`
**방법:**
- `__init__`에 `self._restart_fail_count = 0` 추가
- `restart_server()` 메서드 신규 추가:
  - `DATA_DIR` 기준으로 server.py 경로 탐색
  - `subprocess.Popen([sys.executable, server_py_path])` 으로 재시작
  - 성공 시 카운트 리셋, 실패 시 증가
  - 3회 연속 실패 → `_add_log("🚨 서버 자동 재시작 3회 연속 실패")` 경고
- `run_check()`에서 `check_server()` 실패 시 `restart_server()` 호출
**검증:** watchdog 실행 중 server.py 강제 종료 → 60초 내 자동 재시작 확인

---

## [✅] Task 2: Gemini↔Claude 메시지 폴링
**파일:** `scripts/hive_hook.py`
**방법:**
- `read_messages(agent_name)` 함수 추가:
  - `data/messages.jsonl` 읽어서 `to == agent_name` AND `read_at == null` 필터
  - 해당 메시지 처리 후 `read_at` 타임스탬프 마킹 후 파일 재저장
- UserPromptSubmit 훅 실행 시 `read_messages("claude")` 호출 → 미읽음 메시지 출력
**검증:** `python scripts/send_message.py gemini claude info "테스트"` 후 훅 실행 시 출력 확인

---

## [✅] Task 3: 스킬 결과 영구 저장
**파일:** `scripts/skill_orchestrator.py`
**방법:**
- `cmd_done()` 끝에 결과 저장 로직 추가:
  - `data/skill_results.jsonl`에 JSON 한 줄 append
  - 저장 데이터: `session_id`, `request`, `results[]`, `completed_at`
**검증:** 오케스트레이터 실행 후 `cat .ai_monitor/data/skill_results.jsonl` 확인

---

## [✅ 완료] Task 4: 오케스트레이터 시각화
**파일:** `.ai_monitor/vibe-view/src/App.tsx`
**상태:** SkillChainWidget 완전 구현됨 (line 1554~1630) — 추가 작업 없음

---

## 실행 순서
Task 1 → Task 2 → Task 3
각 Task 완료 후 개별 커밋
