# Phase 3: LLM 위키 자동생성 — 에이전트 브릿지 방식

> 코드 인텔리전스 Phase 3. code_nodes → 프롬프트 조립 → hive_tasks 등록 → 에이전트 위키 생성 → code_wiki 저장
> 승인일: 2026-04-15

---

## 백엔드

[x] Task 1: code_wiki 스키마 확장 — wiki_type + node_id 컬럼 추가
    파일: .ai_monitor/src/pg_store.py (L829~841)
    방법: code_wiki CREATE TABLE에 wiki_type TEXT DEFAULT 'file' + node_id INTEGER REFERENCES code_nodes(id) ON DELETE CASCADE 추가. UNIQUE 인덱스를 (project_id, file_path, wiki_type, COALESCE(node_id, -1))로 변경. ensure_schema() 내 마이그레이션 블록에 ALTER TABLE ADD COLUMN IF NOT EXISTS도 추가 (기존 DB 호환)
    검증: 서버 시작 → psql에서 \d code_wiki로 wiki_type, node_id 컬럼 확인

[x] Task 2: wiki_generator.py 신규 — 프롬프트 조립 + 태스크 등록 엔진
    파일: .ai_monitor/src/wiki_generator.py (신규)
    방법:
      - generate_file_wiki(project_id, file_path): code_nodes에서 해당 파일의 함수/클래스 목록 + raw_content 수집 → 한글 마크다운 위키 프롬프트 조립 → hive_tasks에 태스크 등록 (title: "위키생성: {file_path}", tags: ["wiki_generate"], description에 프롬프트 포함)
      - generate_module_wiki(project_id, dir_path): 하위 파일들의 기존 위키 요약 → 모듈 위키 생성 태스크
      - generate_node_wiki(project_id, node_id): 개별 함수/클래스 위키 생성 태스크
      - save_wiki(project_id, file_path, wiki_type, content, node_id=None): code_wiki에 UPSERT
      - get_wiki(project_id, file_path=None, wiki_type=None): 위키 조회
      - get_wiki_tree(project_id): 파일 목록 + 위키 존재 여부 트리
      - source_hash로 변경 감지 — 해시 동일하면 재생성 스킵
    검증: generate_file_wiki() 호출 → hive_tasks에 wiki_generate 태스크 생성 확인
    의존: Task 1 완료 후

[x] Task 3: codegraph_api.py에 위키 API 엔드포인트 4개 추가
    파일: .ai_monitor/api/codegraph_api.py (L91 앞, L150 앞)
    방법:
      - GET /api/codegraph/wiki?project_id=&file_path=&wiki_type= → get_wiki() 호출
      - GET /api/codegraph/wiki/tree?project_id= → get_wiki_tree() 호출
      - POST /api/codegraph/wiki/generate → {project_id, target_type(file/module/node), target_path, node_id?} → generate_*_wiki() 호출
      - PUT /api/codegraph/wiki → {project_id, file_path, wiki_type, content, node_id?} → save_wiki() 호출 (수동 편집/에이전트 결과 저장)
    검증: curl로 각 엔드포인트 호출 → JSON 응답 확인
    의존: Task 2 완료 후

---

## 프론트엔드

[x] Task 4: react-markdown 의존성 추가
    파일: .ai_monitor/vibe-view/package.json
    방법: npm install react-markdown remark-gfm
    검증: npm ls react-markdown

[x] Task 5: CodeWikiPanel.tsx 신규 — 파일트리 + 마크다운 뷰어/편집기
    파일: .ai_monitor/vibe-view/src/components/panels/CodeWikiPanel.tsx (신규)
    방법:
      - 상단: 프로젝트 선택 드롭다운 + "전체 생성" 버튼
      - 좌측 (w-1/3): 파일 트리 — /api/codegraph/wiki/tree에서 fetch. 폴더 접기/펼치기. 각 항목에 생성 상태 아이콘 (✅/⏳/➕)
      - 우측 (w-2/3): 뷰 모드=react-markdown 렌더링 / 편집 모드=textarea. 하단에 "위키 생성"/"재생성"/"저장" 버튼
      - 트리에서 파일 클릭 → GET /wiki로 조회 → 우측에 표시
      - "위키 생성" 클릭 → POST /wiki/generate 호출
      - "저장" 클릭 → PUT /wiki 호출
    검증: Playwright로 패널 렌더링 + 트리 클릭 → 위키 표시 확인
    의존: Task 3, Task 4 완료 후

[x] Task 6: App.tsx + ActivityBar.tsx에 codewiki 탭 등록
    파일: .ai_monitor/vibe-view/src/App.tsx (L525~527), .ai_monitor/vibe-view/src/components/ActivityBar.tsx (L192 뒤)
    방법: App.tsx에 CodeWikiPanel import + activeTab === 'codewiki' 분기 추가. ActivityBar에 BookOpen 아이콘 버튼 추가 (이미 import됨)
    검증: 탭 클릭 → CodeWikiPanel 전환 확인
    의존: Task 5 완료 후

---
**상태:** ✅ Phase 3 완료 (2026-04-15)
