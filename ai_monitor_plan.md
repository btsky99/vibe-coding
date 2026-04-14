# 코드 인텔리전스 시스템 — MindVault 영감 기반

> tree-sitter + PostgreSQL FTS + 코드 그래프 + LLM 위키 (접근법 C)
> 승인일: 2026-04-14

---

## Phase 1: 인덱싱 + 검색 + 그래프 저장 (백엔드)

[x] Task 1: PostgreSQL 스키마 추가 — code_projects/nodes/edges/wiki 4개 테이블
    파일: .ai_monitor/src/pg_store.py
    방법: ensure_schema() 내 schema_sql에 CREATE TABLE IF NOT EXISTS 블록 4개 추가. code_nodes에 TSVECTOR 컬럼 + GIN 인덱스, code_edges에 source/target 인덱스. content_tsv 자동 업데이트 트리거
    검증: ensure_schema() 호출 후 psql에서 \dt code_* 테이블 4개 확인

[x] Task 2: tree-sitter 의존성 추가
    파일: pyproject.toml
    방법: optional-dependencies에 [codegraph] = ["tree-sitter>=0.24", "tree-sitter-python", "tree-sitter-javascript", "tree-sitter-typescript", "tree-sitter-go", "tree-sitter-rust", "tree-sitter-java"] 추가
    검증: pip install -e ".[codegraph]" 성공

[x] Task 3: 코드 인덱서 엔진 — tree-sitter AST 파싱
    파일: .ai_monitor/src/code_indexer.py (신규)
    방법: tree-sitter로 파일별 AST 파싱 → 함수/클래스/import 노드 추출 → code_nodes/code_edges 저장. threading.Thread 백그라운드 실행. 언어별 파서 동적 로드 (확장자 매핑). tree-sitter 없으면 정규식 fallback. SSE로 진행률 스트리밍
    검증: 테스트 폴더 인덱싱 → code_nodes 레코드 존재 확인
    의존: Task 1, Task 2 완료 후

[x] Task 4: BM25 검색 엔진 — PostgreSQL FTS
    파일: .ai_monitor/src/code_search.py (신규)
    방법: plainto_tsquery + ts_rank_cd()로 BM25 랭킹. code_nodes.content_tsv GIN 인덱스 활용. 결과: file_path, name, node_type, snippet, score 포함
    검증: 인덱싱된 프로젝트에서 함수명 검색 → 관련 결과 반환
    의존: Task 1 완료 후

[x] Task 5: CodeGraph REST API
    파일: .ai_monitor/api/codegraph_api.py (신규)
    방법: handle_get/handle_post 패턴. POST /register(프로젝트등록), POST /index(인덱싱), GET /search(BM25), GET /graph(노드+엣지), GET /impact(영향분석 — 재귀적 엣지 탐색)
    검증: curl로 각 엔드포인트 호출 → JSON 응답 확인
    의존: Task 3, Task 4 완료 후

[x] Task 6: server.py에 라우팅 등록
    파일: .ai_monitor/server.py
    방법: import api.codegraph_api as codegraph_api + do_GET/do_POST에 /api/codegraph/ 분기 추가
    검증: 서버 시작 → /api/codegraph/search?q=test 호출 → 200
    의존: Task 5 완료 후

---

## Phase 2: 시각화 UI (프론트엔드)

[x] Task 7: react-force-graph-2d 의존성 추가
    파일: .ai_monitor/vibe-view/package.json
    방법: npm install react-force-graph-2d
    검증: npm ls react-force-graph-2d

[x] Task 8: CodeGraphPanel — 인터랙티브 그래프
    파일: .ai_monitor/vibe-view/src/components/panels/CodeGraphPanel.tsx (신규)
    방법: react-force-graph-2d로 노드+엣지 시각화. 노드 색상=타입별(function:파랑, class:초록, module:주황). 클릭→상세팝업. 줌/패닝. 프로젝트 선택 드롭다운. /api/codegraph/graph에서 데이터 fetch
    검증: Playwright로 그래프 렌더링 확인
    의존: Task 6, Task 7 완료 후

[x] Task 9: CodeSearchPanel — BM25 검색 UI
    파일: .ai_monitor/vibe-view/src/components/panels/CodeSearchPanel.tsx (신규)
    방법: 검색창(debounce 300ms) + 결과 리스트(파일경로/함수명/스니펫/점수). 결과 클릭→그래프 노드 하이라이트 연동
    검증: Playwright로 검색→결과 표시 확인
    의존: Task 6, Task 7 완료 후

[x] Task 10: App.tsx + ActivityBar에 패널 등록
    파일: .ai_monitor/vibe-view/src/App.tsx, .ai_monitor/vibe-view/src/components/ActivityBar.tsx
    방법: import 추가 + activeTab 조건식에 'codegraph'/'codesearch' 추가 + ActivityBar에 아이콘 탭 추가
    검증: 탭 클릭 → 패널 전환
    의존: Task 8, Task 9 완료 후

---

## Phase 3: LLM 위키 자동생성 (Phase 1,2 완료 후 별도 계획)

> wiki_generator.py + CodeWikiPanel.tsx — Karpathy LLM Wiki 패턴

---
**상태:** ✅ Phase 1+2 완료 (2026-04-14)
