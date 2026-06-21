---
name: vibe-zettel
description: >
  제텔카스텐 지식 관리 스킬. 노트 캡처, 정제(fleeting→permanent 승격), 유사 노트 연결, 검색, Obsidian 동기화.
  Use when: "노트 만들어", "지식 저장", "제텔카스텐", "옵시디언", "zettel", "노트 검색", "정리해줘" 요청 시.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
context: fork
agent: general-purpose
---

<!--
FILE: .claude/skills/vibe-zettel/skill.md
DESCRIPTION: Hive Zettelkasten 지식 관리 스킬.
             에이전트가 작업 중 발생하는 지식을 노트로 캡처하고,
             정제(fleeting→permanent 승격), 유사 노트 연결, 검색, Obsidian vault 동기화를 수행한다.

REVISION HISTORY:
- 2026-04-06 Claude: 초기 구현 — capture/refine/connect/search/sync/stats 서브커맨드
-->

당신은 **Hive Zettelkasten 지식 관리 스킬**을 실행합니다.

# 서브커맨드 라우팅

ARGUMENTS에서 서브커맨드를 파싱하여 해당 작업을 수행합니다.
인자가 없으면 `stats`를 기본 실행합니다.

## 1. `capture "내용"` — 즉석 노트 캡처

현재 맥락에서 즉시 fleeting 노트를 생성합니다.

```bash
python scripts/zettel_capture.py --mode decision --agent claude --data '{"context":"현재 작업 맥락","choice":"ARGUMENTS에서 파싱한 내용","reason":"에이전트 판단"}'
```

생성 후 결과를 사용자에게 보고:
- 노트 ID, 제목, 유형
- 자동 연결된 유사 노�� 목록

## 2. `refine [noteId]` — fleeting → permanent 승격

> **🚨 저장소 역할 분리 (절대 규칙) — LLM이 올바로 저장하는 기준**
> - **PG(PostgreSQL) = LLM의 작업기억 + 진실의 원천.** 세션 요약·로그·휘발성 기록은 전부 여기. fleeting으로 남긴다.
> - **옵시디언(로컬+GDrive) = 사람이 읽는 "정제된 영구지식"만의 거울.** 진짜 지식만 올라간다.
> - **세션 요약(`source_ref='session-summary'`)·머지 커밋 노트는 절대 permanent로 승격 금지 + 옵시디언 동기화 제외.** (PG에만 보존)
> - 자동 승격 데몬(`run_zettel_refine`)도 이 노트들을 제외한다(daemons.py 가드). 수동 refine도 동일하게 금지.
> - [과거사고 2026-06-21] refine가 fleeting 전부를 24h 후 무차별 승격 → 세션요약 411개가 영구지식·그래프 점령. PG 보존한 채 옵시디언서만 정리.

지정한 노트를 분석하여 permanent로 승격합니다. **단, 위 역할 분리 규칙을 지킨다 — 실제 지식 가치가 있는 노트만 승격.**

1. 현재 노트 내용 조회:
   ```bash
   python -c "import sys; sys.path.insert(0,'.ai_monitor'); from src.zettelkasten import get_note; import json; print(json.dumps(get_note('NOTE_ID'), default=str, ensure_ascii=False))"
   ```

2. AI로 내용을 정제:
   - 제목을 명확하고 검색 가능하게 개선
   - 본문을 구조화 (## 섹션, 핵심 포인트)
   - 태그를 의미 있게 보강
   - note_type을 'permanent'로 변경

3. 업데이트 실행:
   ```bash
   python -c "import sys; sys.path.insert(0,'.ai_monitor'); from src.zettelkasten import refine_note; refine_note('NOTE_ID', new_title='정제된 제목', new_content='정제된 내용', new_type='permanent', new_tags=['태그1','태그2'])"
   ```

4. 유사 노트 재연결:
   ```bash
   python -c "import sys; sys.path.insert(0,'.ai_monitor'); from src.zettelkasten import auto_link; auto_link('NOTE_ID', content='정제된 내용', tags=['태그들'])"
   ```

5. Obsidian vault 동기화:
   ```bash
   python scripts/zettel_sync.py
   ```

## 3. `connect [noteId]` — 유사 노트 탐지 + 링크

지정한 노트와 유사한 기존 노트를 찾아 링크를 제안합니다.

```bash
python -c "
import sys, json; sys.path.insert(0,'.ai_monitor')
from src.zettelkasten import get_note, find_similar, add_link
note = get_note('NOTE_ID')
if note:
    similar = find_similar(note.get('content',''), note.get('tags',[]), exclude_id='NOTE_ID')
    print(json.dumps(similar, default=str, ensure_ascii=False, indent=2))
"
```

결과를 사용자에게 보여주고, 연결할 노트를 선택하게 합니다.

## 4. `search "키워드"` — 노트 검색

```bash
python -c "
import sys, json; sys.path.insert(0,'.ai_monitor')
from src.zettelkasten import list_notes
results = list_notes(q='KEYWORD', limit=10)
for n in results:
    print(f'[{n[\"id\"]}] {n[\"title\"]} ({n[\"note_type\"]}) tags={n.get(\"tags\",[])}')
print(f'--- 총 {len(results)}건 ---')
"
```

## 5. `sync` — Obsidian vault 즉시 동기화 (노트 + 프로젝트 문서)

로컬 vault + Google Drive vault 동시 동기화. 프로젝트 문서(CLAUDE.md, RULES.md, 스킬, 규칙, docs/ 등)도 자동 포함.

```bash
python scripts/zettel_sync.py
python scripts/zettel_sync.py --vault "I:/내 드라이브/obsidian/hive-zettel"
```

vault 구조:
- `작업기록/`(fleeting), `참고문헌/`(literature), `영구지식/`(permanent), `_보관/`(archived) — 지식 노트 (자동 캡처)
- `_project/{프로젝트명}/` — 프로젝트별 문서 (멀티 프로젝트 충돌 방지)
  - 루트 문서: 클로드/제미나이/코덱스 설정, 프로젝트 규칙, 구조 지도 등
  - `docs/` — API 명세서, 하네스 계약, 개발 가이드 등
  - `rules/` — 아키텍처 규칙, 커밋 규칙, 동기화 프로토콜
  - `skills/` — 모든 스킬 정의 문서
- `INDEX.md` — 전체 목차 (한글 제목, 위키링크)

## 7. `stats` — 현황 요약 (기본)

```bash
python -c "
import sys, json; sys.path.insert(0,'.ai_monitor')
from src.zettelkasten import get_stats, list_notes
stats = get_stats()
print(json.dumps(stats, default=str, ensure_ascii=False, indent=2))
recent = list_notes(limit=5)
print('--- 최근 노트 ---')
for n in recent:
    print(f'[{n[\"id\"]}] {n[\"title\"]} ({n[\"note_type\"]})')
"
```

# 출력 형식

모든 서브커맨드 실행 후 결과를 한글로 보고합니다:
- 수행한 작업
- 영향받은 노��� ID + 제목
- Obsidian vault 동기화 여부
