<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 하이브 마인드 고도화 및 신규 기능 구현 로드맵
REVISION HISTORY:
- 2026-03-13 Claude: Skills 2.0 전체 마이그레이션 + vibe-security 신규 추가 계획으로 교체
- 2026-03-13 Claude: [오케스트레이터] 전체 태스크 완료 상태 확인 및 계획 동기화
-->

# 📋 Skills 2.0 전체 마이그레이션 + vibe-security 신규 추가

**작성일:** 2026-03-13
**목표:** .claude/commands/*.md → .claude/skills/<name>/SKILL.md 전환 (10개) + 오케스트레이터 레지스트리 갱신

---

## 태스크 목록

[x] Task 1: vibe-debug 마이그레이션
    파일: .claude/skills/vibe-debug/SKILL.md
    방법: .claude/commands/vibe-debug.md 내용 복사 + 프론트매터 allowed-tools 완전판(Read,Bash,Grep,Glob,Edit) 추가
    검증: .claude/skills/vibe-debug/SKILL.md 존재 확인

[x] Task 2: vibe-tdd 마이그레이션
    파일: .claude/skills/vibe-tdd/SKILL.md
    방법: .claude/commands/vibe-tdd.md 복사 + 프론트매터 갱신(allowed-tools: Read,Write,Bash,Edit)
    검증: .claude/skills/vibe-tdd/SKILL.md 존재 확인

[x] Task 3: vibe-brainstorm 마이그레이션
    파일: .claude/skills/vibe-brainstorm/SKILL.md
    방법: .claude/commands/vibe-brainstorm.md 복사 + 프론트매터 갱신(allowed-tools: Read,Write,Bash,Glob)
    검증: .claude/skills/vibe-brainstorm/SKILL.md 존재 확인

[x] Task 4: vibe-write-plan 마이그레이션
    파일: .claude/skills/vibe-write-plan/SKILL.md
    방법: .claude/commands/vibe-write-plan.md 복사 + 프론트매터 갱신(allowed-tools: Read,Write)
    검증: .claude/skills/vibe-write-plan/SKILL.md 존재 확인

[x] Task 5: vibe-execute-plan 마이그레이션
    파일: .claude/skills/vibe-execute-plan/SKILL.md
    방법: .claude/commands/vibe-execute-plan.md 복사 + 프론트매터 갱신(allowed-tools: Read,Write,Bash,Edit,Glob,Grep)
    검증: .claude/skills/vibe-execute-plan/SKILL.md 존재 확인

[x] Task 6: vibe-code-review 마이그레이션
    파일: .claude/skills/vibe-code-review/SKILL.md
    방법: .claude/commands/vibe-code-review.md 복사 + 프론트매터 갱신(allowed-tools: Read,Bash,Grep,Glob)
    검증: .claude/skills/vibe-code-review/SKILL.md 존재 확인

[x] Task 7: vibe-release 마이그레이션
    파일: .claude/skills/vibe-release/SKILL.md
    방법: .claude/commands/vibe-release.md 복사 + 프론트매터 갱신(allowed-tools: Bash,Read,Edit)
    검증: .claude/skills/vibe-release/SKILL.md 존재 확인

[x] Task 8: vibe-heal 마이그레이션 (context: fork 적용)
    파일: .claude/skills/vibe-heal/SKILL.md, .claude/skills/vibe-heal/known-patterns.md
    방법: .claude/commands/vibe-heal.md 복사 + context: fork + agent: general-purpose 추가
          known-patterns.md에 현재까지 알려진 반복 패턴 목록 작성
    검증: 프론트매터에 context: fork 포함 확인

[x] Task 9: vibe-orchestrate 마이그레이션
    파일: .claude/skills/vibe-orchestrate/SKILL.md, .claude/skills/vibe-orchestrate/skill-chain-guide.md
    방법: .claude/commands/vibe-orchestrate.md 복사 + 프론트매터 갱신
          skill-chain-guide.md에 plan/update/done 명령 레퍼런스 작성
    검증: .claude/skills/vibe-orchestrate/SKILL.md 존재 확인

[x] Task 10: vibe-security 신규 스킬 생성 (OWASP 보안 점검)
    파일: .claude/skills/vibe-security/SKILL.md, .claude/skills/vibe-security/owasp-checklist.md
    방법: OWASP Top 10 기반 4단계 보안 점검 스킬 신규 작성
          Use when: "보안 점검", "취약점", "OWASP", 배포 전 보안 검토 요청 시
    검증: /vibe-security 호출 가능 확인

[x] Task 11: skill_orchestrator.py 레지스트리에 vibe-security 추가
    파일: scripts/skill_orchestrator.py
    방법: SKILL_REGISTRY에 {"num": 9, "name": "vibe-security", "short": "security"} 추가
    의존성: Task 10 완료 후
    검증: python scripts/skill_orchestrator.py status 출력에 vibe-security 포함 확인

[x] Task 12: .claude/commands/ 폴더 삭제
    파일: .claude/commands/ (폴더 전체 삭제)
    방법: Task 1~9 모두 완료 확인 후 .claude/commands/ 폴더 삭제
    의존성: Task 1~9 완료 후
    검증: .claude/commands/ 없음, .claude/skills/ 10개 폴더 존재

---

## 의존성
- Task 1~10: 병렬 실행 가능
- Task 11: Task 10 완료 후
- Task 12: Task 1~9 완료 후
