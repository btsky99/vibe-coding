# 📋 Skill Orchestrator 명령 레퍼런스

이 파일은 `scripts/skill_orchestrator.py` 사용법 가이드입니다.
vibe-orchestrate 스킬이 대시보드 연동 시 참조합니다.

---

## 기본 명령

### 1. 체인 계획 등록
```bash
python scripts/skill_orchestrator.py plan "<요청 내용>" "<skill1>" "<skill2>" ...
```
- 터미널 번호는 환경변수 `TERMINAL_ID`에서 자동 읽음 (기본값: T1)
- 에이전트는 환경변수 `AGENT_NAME`에서 자동 읽음 (기본값: claude)

### 2. 단계 상태 업데이트
```bash
# 실행 시작
python scripts/skill_orchestrator.py update <step번호> running

# 완료 (summary 필수)
python scripts/skill_orchestrator.py update <step번호> done "<결과 요약>"

# 실패
python scripts/skill_orchestrator.py update <step번호> failed "<실패 이유>"

# 건너뜀
python scripts/skill_orchestrator.py update <step번호> skipped "<이유>"
```

**step번호**: 0부터 시작 (plan에서 지정한 스킬 순서)

### 3. 전체 완료
```bash
python scripts/skill_orchestrator.py done
```

### 4. 현재 상태 조회
```bash
python scripts/skill_orchestrator.py status
```

---

## 대시보드 연동

- 상태 변경 즉시 `/api/orchestrator/skill-chain` API 반영
- 프론트엔드 OrchestratorPanel이 3초마다 폴링
- `running` → 노란색 배지, `done` → 녹색, `failed` → 빨간색

---

## 예시: 버그 수정 체인

```bash
python scripts/skill_orchestrator.py plan "로그인 버그 고쳐줘" "vibe-debug" "vibe-code-review"

python scripts/skill_orchestrator.py update 0 running
# ... vibe-debug 실행 ...
python scripts/skill_orchestrator.py update 0 done "[오류 발견] auth.py:45 KeyError — session_id 누락 수정"

python scripts/skill_orchestrator.py update 1 running
# ... vibe-code-review 실행 ...
python scripts/skill_orchestrator.py update 1 done "[리뷰 완료] Critical 0건, Warning 2건 정리"

python scripts/skill_orchestrator.py done
```
