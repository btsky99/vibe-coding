<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 지식 노트(제텔카스텐) 파이프라인 재설계 실행 계획 — 세션요약 노이즈 제거 + 파일지식 1급화 +
             파일지도 스냅샷 + GDrive 크로스프로젝트 허브. 바이브 프로그램으로 돌리는 모든 프로젝트에
             적용되는 이식형 "나만의 지식 창고".

REVISION HISTORY:
- 2026-07-12 Claude: 신규. 브레인스토밍 승인(4대 설계) → 마이크로태스크 분해. 이전 onedir 전환 계획은 완료 → 교체.
-->

# 구현 계획 — 지식 노트 파이프라인 재설계 (나만의 지식 창고)

> **설계 승인**: 2026-07-12 (vibe-brainstorm). 메모리 `project_knowledge_vault_redesign.md` 참조.
> **목표**: GDrive를 서로 다른 프로젝트 지식 소통 허브로. 파일 구조/역할/변경이 진짜 지식으로 쌓이게.
> **북극성**: 기능 확장 아님 — 잡음(세션요약 65%) 제거 + 파일지식 축적 = 크로스프로젝트 재사용성.

## 핵심 통찰 (실측 근거)
- 영구지식 1264건 중 **65%(817)가 세션요약 노이즈**. 진범 = `pg_memory.py auto_promote_fleeting()`의
  허브형 조건(링크 degree≥3)에 세션요약이 auto_link로 걸려 permanent 승격. (memory_watcher.py:122 데몬 구동)
  cf. `run_zettel_refine`(daemons.py:400)은 이미 세션요약 배제 — auto_promote만 구멍.
- `export_to_vault`(zettel_sync.py:269 `_is_ephemeral`)은 **이미 세션요약을 vault/GDrive에서 제외** →
  #4의 남은 과제는 **커밋덤프(git-commit:*)까지 걸러 GDrive를 "파일카드·결정·교훈"으로 좁히는 것**.
- 파일카드(`capture_file_roles`, 261건)의 `_guess_file_role`은 경로 추측만 — 실제 헤더 DESCRIPTION 미사용.
- `capture_commit`이 이미 `capture_file_roles` 호출(146). 커밋폴링 데몬(daemons.py:510)이 capture_commit 호출.

## 이식성 제약 (전 프로젝트 공통 — 필수)
- 절대경로 하드코딩 금지. 경로는 `_rel_path`/env/프로젝트 루트 자동탐지 경유. (`feedback_vibe_essence`)
- 파일당 1500줄, 표준 헤더, 한글 LLM 관점 주석, project_id 가드 준수.

---

## 태스크

### [x] Task 1: auto_promote_fleeting에서 세션요약 승격 차단
- **파일**: `.ai_monitor/src/pg_memory.py`
- **방법**: `_auto_promote_where_clause()`에 배제절 추가 —
  `AND zn.source_ref IS DISTINCT FROM 'session-summary' AND zn.title NOT LIKE '세션 요약%' AND zn.title NOT LIKE 'Merge %'`.
  (run_zettel_refine의 배제 기준과 일치시켜 일관성 확보.) 주석에 진범/근거 1줄.
- **검증**: `preview_auto_promote()` 결과에 source_ref='session-summary' 0건 (DB 실측).

### [x] Task 2: 기존 세션요약 818건 아카이브 마이그레이션
- **파일**: `scripts/migrate_archive_session_summaries.py` (신규, 표준 헤더)
- **방법**: `UPDATE zettel_notes SET archived=true, updated_at=NOW() WHERE (source_ref='session-summary'
  OR title LIKE '세션 요약%') AND archived IS NOT TRUE`. `--dry` 옵션으로 대상 건수만 리포트.
  되돌림 안내(archived=false로 복구 가능) 출력. 현재 프로젝트 DB 대상(포터블 PC별).
- **검증**: 실행 후 `SELECT count(*) ... WHERE 세션요약 AND note_type='permanent' AND NOT archived` = 0.
- **의존**: Task 1 완료 후 (승격 재발 없는 상태에서 청소).

### [x] Task 3: 파일 헤더 DESCRIPTION 실제 파싱 (_read_file_description)
- **파일**: `scripts/zettel_capture.py`
- **방법**: `_read_file_description(rel)` 신설 — 파일 상단 ~40줄에서 `DESCRIPTION:` 추출(다음 대문자
  섹션 전까지, 첫 문장/80자 정규화). 헤더 없음/읽기 실패 → 기존 `_guess_file_role(rel)` 폴백.
  `capture_file_roles` 새 카드의 role_desc를 이 함수로 교체. 경로는 `_rel_path` 경유(이식성).
- **검증**: 헤더 있는 파일(server.py 등) → 실제 DESCRIPTION 반환, 헤더 없는 파일 → 폴백. pytest.

### [x] Task 4: 변경 요약(무엇을/왜) 누적 (_extract_commit_why)
- **파일**: `scripts/zettel_capture.py`
- **방법**: `_extract_commit_why(commit_msg)` 신설 — 커밋 본문 '## 변경 이유' 또는 '## 변경 내용'
  첫 유효 줄 추출. `capture_file_roles`의 change_line을 `[날짜] {제목} — {why}`로 (why 없으면 제목만).
- **검증**: 3섹션 커밋 → change_line에 why 포함, 제목만 커밋 → 제목만. pytest.
- **의존**: Task 3 완료 후 (같은 함수 편집 영역).

### [x] Task 5: 파일 구조 스냅샷 capture_project_map
- **파일**: `scripts/zettel_capture.py` (500줄 → +~100, 1500 여유. 초과 시 `scripts/zettel_file_knowledge.py` 분리)
- **방법**: `capture_project_map(root=None, agent='system')` — 프로젝트 루트(미지정 시 자동탐지) 트리
  순회: 코드 확장자 화이트리스트(.py/.ts/.tsx/.js/.md 등) + `_is_noise_file` 제외 + 디렉토리별 그룹핑 +
  파일당 `_read_file_description` 한 줄. 단일 노트 upsert(source_ref='project-map',
  title='🗂️ 프로젝트 파일 지도', note_type='permanent') + auto_link. 비대 방지: 상위 N디렉토리 제한.
- **검증**: 실행 후 source_ref='project-map' 정확히 1건, content에 트리+설명. 재실행 시 update(중복無). DB 실측.

### [x] Task 6: 커밋 폴링 데몬에 project-map 편승
- **파일**: `.ai_monitor/infra/daemons.py` (커밋 감지 → capture_commit 호출부 ~510)
- **방법**: capture_commit 직후 `capture_project_map()` 호출(try/except, 실패 무시). 변경 파일 있을 때만.
- **검증**: 새 커밋 후 project-map 노트 updated_at 갱신. Task 5 완료 후.

### [x] Task 7: GDrive 크로스공유 화이트리스트
- **파일**: `scripts/zettel_sync.py`(`mirror_vault`), `.ai_monitor/infra/daemons.py`(`_sync_with_gdrive`)
- **방법**: GDrive mirror 대상을 크로스프로젝트 가치 노트로 한정 — `mirror_vault(source, target,
  note_whitelist=None)`에 선택적 predicate 추가. 로컬 vault md의 frontmatter `source_ref`를 읽어
  `file-role:*`/`project-map`/`decision`/교훈태그면 복사, `git-commit:*`는 skip. **비파괴 유지**(타 프로젝트
  target-only 파일 보존). `_sync_with_gdrive`에서 이 필터 전달. 로컬 vault 자체는 불변.
- **검증**: mirror 후 GDrive에 git-commit:* 파일 없음 + file-role/project-map 존재, 로컬 vault 변화 없음. Task 5 후.

### [x] Task 8: 회귀 테스트 + 최종 실측
- **파일**: `tests/test_knowledge_pipeline.py` (신규)
- **방법**: Task1(승격 배제 WHERE), Task3(헤더 파싱+폴백), Task4(why 추출), Task5(project-map upsert) 단위 테스트.
- **검증**: `pytest tests/test_knowledge_pipeline.py` 통과 + 전체 스모크(기존 테스트 회귀 없음). 전 Task 완료 후.

---

## 의존성 요약
- Task 2 ← Task 1 / Task 4 ← Task 3 / Task 6 ← Task 5 / Task 7 ← Task 5 / Task 8 ← 전체
- Task 1·3·5는 독립 병렬 가능.

## 완료 정의
- 세션요약이 더 이상 permanent 승격 안 됨(신규) + 기존 818건 아카이브됨.
- 파일카드가 실제 헤더 DESCRIPTION + 변경 이유를 담음.
- `🗂️ 프로젝트 파일 지도` 노트가 커밋마다 자동 갱신.
- GDrive에 파일카드·지도·결정·교훈만 흐르고 커밋덤프·세션요약 제외.
- 배포는 `/vibe-release`로 별도 진행(코드 완료 후).
