# 🎯 AI 오케스트레이터 완전 구현 계획
> 작성일: 2026-03-01 | 작성자: Claude
> 목표: A안(vibe-orchestrate 스킬 + hook 자동 트리거) + B안(skill_orchestrator.py 상태 추적 + 대시보드) 통합

---

## 전체 아키텍처

```
[사용자 입력]
    ↓
[hive_hook.py] — 복잡한 요청 감지 → /vibe-orchestrate 컨텍스트 주입
    ↓
[vibe-orchestrate.md] — 요청 분석 → 스킬 체인 계획 수립
    ↓  (plan 저장 → skill_chain.json)
[skill_orchestrator.py] ← server.py /api/orchestrator/skill-chain
    ↓
[Claude: Skill 도구로 vibe-debug → vibe-tdd → vibe-release 자동 체인 실행]
    ↓
[대시보드: 실행 흐름 실시간 시각화]
```

---

## Task 목록

### Task 1: vibe-orchestrate.md 스킬 신설 (A안 핵심)
```
[ ] Task 1: skills/claude/vibe-orchestrate.md 생성
    파일: skills/claude/vibe-orchestrate.md
    방법:
      - 요청 분석 → 카테고리 판별 (버그/기능/빌드/리팩/문서/단순질문)
      - 스킬 체인 매핑:
          버그/오류  → [vibe-debug] → [vibe-tdd] → (옵션)[vibe-release]
          새 기능    → [vibe-brainstorm] → [vibe-write-plan] → [vibe-execute-plan]
          코드 품질  → [vibe-code-review] → [vibe-execute-plan]
          빌드/배포  → [vibe-release]
          단순 질문  → 직접 답변 (스킬 체인 없음)
      - 체인 시작 전 skill_chain.json에 계획 저장 (B안 연동)
      - Skill 도구로 각 스킬 순서대로 자동 실행
      - 각 스킬 완료 후 결과 평가 → 다음 스킬 필요 여부 재판단
    검증: "로그인 버그 고쳐줘" → 자동으로 vibe-debug → vibe-tdd 체인 실행
```

### Task 2: hive_hook.py 오케스트레이터 자동 트리거
```
[ ] Task 2: scripts/hive_hook.py — 복잡한 요청 감지 시 orchestrate 모드 활성화
    파일: scripts/hive_hook.py
    방법:
      - _INTENT_MAP 맨 앞에 "orchestrate" 의도 추가 (최고 우선순위)
      - 복잡도 감지 로직:
          키워드 2개 이상 동시 매칭 → orchestrate 강제
          "자동", "전부", "다", "전체" 키워드 포함 → orchestrate 강제
      - Context 주입: "즉시 /vibe-orchestrate 스킬을 실행하세요"
      - 단순 요청(commit/push 단독)은 기존 단일 스킬 유지
    검증: "버그 고치고 테스트도 해줘" → hook stdout에 orchestrate 지시 확인
```

### Task 3: skill_orchestrator.py 신규 생성 (B안 핵심)
```
[ ] Task 3: scripts/skill_orchestrator.py 생성
    파일: scripts/skill_orchestrator.py
    방법:
      - DATA_DIR/.ai_monitor/data/skill_chain.json 읽기/쓰기
      - 데이터 구조:
          {
            "session_id": "타임스탬프",
            "request": "사용자 원본 요청",
            "plan": ["vibe-debug", "vibe-tdd", "vibe-release"],
            "current_step": 1,
            "results": [
              {"skill": "vibe-debug", "status": "done", "summary": "버그: null체크 누락"}
            ],
            "status": "running|done|failed",
            "started_at": "ISO시각",
            "updated_at": "ISO시각"
          }
      - CLI 인터페이스:
          python skill_orchestrator.py plan <요청문> → 새 체인 계획 생성
          python skill_orchestrator.py update <step> <status> [summary] → 단계 갱신
          python skill_orchestrator.py status → 현재 상태 JSON 출력
          python skill_orchestrator.py done → 전체 완료 처리
    검증: python skill_orchestrator.py status → JSON 정상 출력
```

### Task 4: server.py 스킬 체인 API 엔드포인트 추가
```
[ ] Task 4: server.py에 /api/orchestrator/skill-chain 추가
    파일: .ai_monitor/server.py
    방법:
      - GET /api/orchestrator/skill-chain → skill_chain.json 내용 반환
        없으면 {"status": "idle"} 반환
      - POST /api/orchestrator/skill-chain/update → 단계 상태 갱신
        body: {"step": 0, "status": "done", "summary": "버그 원인 파악 완료"}
      - 기존 GET /api/orchestrator/status 응답에 "skill_chain" 키 추가 (하위 호환)
    검증: curl http://localhost:8765/api/orchestrator/skill-chain → JSON 반환
```

### Task 5: App.tsx 스킬 체인 실행 흐름 시각화
```
[ ] Task 5: App.tsx 하이브 마인드 패널에 스킬 체인 위젯 추가
    파일: .ai_monitor/vibe-view/src/App.tsx
    방법:
      - skillChain 상태 추가 (3초 폴링, /api/orchestrator/skill-chain)
      - 위치: 하이브 마인드 탭 orchestrator 섹션 상단
      - 시각화:
          실행 중: [vibe-debug ✅] → [vibe-tdd 🔄] → [vibe-release ⏳]
          완료:    모든 스킬 ✅, "체인 완료 N분 전" 표시
          대기:    "오케스트레이터 대기 중..." 흐리게 표시
      - 각 스킬 카드: 이름 + 상태 아이콘 + 완료 요약 툴팁
    검증: 개발 서버에서 스킬 체인 위젯 렌더링 확인
```

### Task 6: 완성본 빌드 + 배포
```
[ ] Task 6: 전체 빌드 후 릴리즈
    파일: dist/, GitHub Release
    방법:
      1. skills/claude/vibe-orchestrate.md → .claude/commands/ 복사
      2. npm run build
      3. pyinstaller vibe-coding.spec --noconfirm
      4. ISCC.exe vibe-coding-setup.iss
      5. git add + commit + push
      6. gh release create v3.6.6 (버전 업)
    검증: GitHub v3.6.6 릴리즈에 EXE 2종 업로드 확인
```

---

## 의존성 순서

```
Task 1 (스킬)    ─┐
Task 3 (상태추적) ─┤→ Task 2 (hook) → Task 4 (API) → Task 5 (UI) → Task 6 (배포)
```

## 실행 순서
**1 → 3 → 4 → 2 → 5 → 6**
(스킬 먼저, 상태 추적 스크립트, API, hook 업데이트, UI, 배포)

---

## 현재 진행 상황
- [ ] Task 1: vibe-orchestrate.md 신설
- [ ] Task 2: hive_hook.py 업데이트
- [ ] Task 3: skill_orchestrator.py 생성
- [ ] Task 4: server.py API 추가
- [ ] Task 5: App.tsx UI 위젯
- [ ] Task 6: 빌드 + 배포
