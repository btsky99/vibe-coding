<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 제텔카스텐 자동 캡처 파이프라인 (방식 C) 구현 계획
REVISION HISTORY:
- 2026-04-06 Claude: 제텔카스텐 자동 캡처 파이프라인 계획 수립 (DeskRPG-Lite 완료 후 교체)
- 2026-04-03 Claude: DeskRPG-Lite 오피스 모드 계획 수립 (전체 완료)
-->

# ��텔카스텐 자동 캡처 파이프라인

**상태:** 전체 완료 (Phase 1-5)
**목표:** 에이전트 작업 중 자동으로 지식 노트를 생성하고, Obsidian vault에 동기화
**원칙:** 기존 zettelkasten.py/zettel_api.py/zettel_sync.py 재사용. DB 스키마 변경 없음.

---

## Phase 1: 핵심 엔진 (zettelkasten.py 확장 + 캡처 스크립트)

[x] Task 1: zettelkasten.py에 find_similar + refine_note 함수 추가
    파일: .ai_monitor/src/zettelkasten.py
    방법: find_similar(content, tags, exclude_id, limit) — 태그 교집합 + ILIKE 키워드 매칭
          refine_note(note_id, new_title, new_content, new_type, new_tags) — fleeting→permanent 승격
    검증: python -c로 직접 호출하여 유사 노트 탐지 + 승격 동작 확���

[x] Task 2: scripts/zettel_capture.py 신규 생성 — 이벤트별 자동 캡처 엔진
    파일: scripts/zettel_capture.py (신���)
    방법: capture_commit(commit_msg, files, agent) — 커밋 유형별 노트 생성 (feat→fleeting, fix→permanent, refactor→literature)
          capture_fix(file_path, old_code, new_code, agent) — 버그 수정 지식 permanent 노트
          capture_decision(context, choice, reason, agent) — 설계 결정 permanent 노트
          capture_session(agent) — 세션 pg_logs 요약 fleeting 노트
          모든 캡처 후: find_similar로 유사 노트 탐지 → add_link 자동 연결
          모든 캡처 후: zettel_sync.export_to_vault 호출
          CLI: python scripts/zettel_capture.py --mode commit|fix|session --agent claude --data '{json}'
    검증: 각 모드 CLI 실행으로 zettel_notes에 노트 생성 + .zettel-vault/ 파일 생성 확인
    의존성: Task 1 완료 후

## Phase 2: 훅 연동 (claude_hook.py 수정)

[x] Task 3: claude_hook.py PostToolUse에 커밋 캡처 연동
    파일: scripts/claude_hook.py
    방법: PostToolUse > Bash > 'git commit' 감지 시 → zettel_capture.py --mode commit spawn (CREATE_NO_WINDOW)
          커밋 메시지에서 타입(feat/fix/refactor) 파싱하여 --data로 ���달
    검증: git commit 실행 후 zettel_notes에 노트 자동 생성 확인

[x] Task 4: claude_hook.py Stop에 세션 요약 캡처 연동
    파일: scripts/claude_hook.py
    방법: Stop 이벤트 핸들러 끝에 → zettel_capture.py --mode session spawn
          기존 log_task, log_thought 코드 유지 (추가만)
    검증: 세션 종료 시 세션 요약 fleeting 노트 자동 생성 확인
    의존성: Task 3과 동시 진행 가능

## Phase 3: vibe-zettel 스킬 (수동 노트 관리)

[x] Task 5: .claude/skills/vibe-zettel/skill.md 신규 생성
    파일: .claude/skills/vibe-zettel/skill.md (신규)
    방법: 서브커맨드 라우팅:
          capture "내용" — 즉석 fleeting 노트 생성
          refine [noteId] — fleeting 분석 → permanent 승격 (AI가 제목/내용/태그 정제)
          connect [noteId] — 유사 노트 탐지 → 링크 제안 및 생성
          search "키워드" — 노트 검색 + 결과 표시
          sync — Obsidian vault 즉시 동기화
          stats — 현황 요약 (노트 수, 유형별 분포, 허브 노트)
          스킬 메타: user-invocable: true, context: fork, agent: general-purpose
    검증: /vibe-zettel capture "테스트" → 노트 생성 확인, /vibe-zettel stats → 통계 출력 확인

## Phase 4: Obsidian 양방향 동기화 (Phase 2 준비)

[x] Task 6: zettel_sync.py에 import_from_vault 함수 추가
    파일: scripts/zettel_sync.py
    방법: import_from_vault(vault_dir) — Obsidian vault → PostgreSQL 역동기화
          YAML 프론트매터 파싱 → 기존 노트 upsert (zettel_id 기준)
          신규/수정 파일만 처리 (mtime vs DB updated_at 비교)
          삭제된 파일은 DB에서 archived=true 처리 (데이터 보존)
          CLI: python scripts/zettel_sync.py --import
          watch_and_sync에 양방향 옵션 추가: --bidirectional
    검증: .zettel-vault/에서 수동 편집 → --import 실행 → DB 반영 확인
    의존성: Task 2 완료 후 (export가 먼저 동작해야 역동기화 의미 있음)

## Phase 5: 통합 테스트 + 첫 번째 실제 노트 생성

[x] Task 7: 전체 파이프라인 통합 테스트 + 실제 작업 노트 생성
    방법: 1) 이번 작업(제텔카스텐 파이프라인 구현) 자체를 노트로 캡처
          2) git commit → 자동 노트 생성 확인
          3) Obsidian vault에서 노트 확인
          4) /vibe-zettel stats로 통계 확인
          5) /vibe-zettel refine으로 fleeting→permanent 승격 테���트
    검증: zettel_notes 테이블 0건 → N건, .zettel-vault/ 파일 생성, Obsidian에서 그래프 뷰 확인 가능
    의존성: Task 1-6 전체 완료 후

---
작성: 2026-04-06 Claude
