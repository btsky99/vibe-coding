# 📜 하이브 에볼루션 (Hive Evolution) v4.0 구현 계획 (완료)
... (기존 내용 유지) ...

# 🚀 하이브 에볼루션 (Hive Evolution) v5.0: 통합 지능체계 고도화 계획

이 계획은 AI 에이전트의 장기 기억력을 강화하고, 사고 과정을 투명하게 공개하며, 에이전트 간의 협업 프로토콜을 공식화하는 것을 목표로 합니다.

## 🧠 단계 1: Vector DB 기반 지능형 장기 기억 (Vector Memory)

### [ ] Task 1: 환경 구축 및 `chromadb` 연동
- **파일**: `scripts/vector_memory.py` (신규)
- **방법**: 
    - `chromadb` 라이브러리 설치 및 초기화 코드 작성.
    - Gemini Embedding API 연동을 위한 전용 클래스 구현.
- **검증**: `python scripts/vector_memory.py --test` 실행 시 임베딩 생성 및 저장 확인.

### [ ] Task 2: `memory.py` 및 `server.py` 벡터 검색 통합
- **파일**: `scripts/memory.py`, `.ai_monitor/server.py`
- **방법**:
    - `memory.py set` 호출 시 자동으로 `vector_memory.py`를 통해 벡터 DB에도 저장.
    - `/api/memory/search` 엔드포인트에 시맨틱 검색 기능 추가.
- **검증**: 키워드가 달라도 의미가 유사한 메모리가 검색되는지 확인.

---

## 🎨 단계 2: 사고 과정 시각화 (Thought Trace Visualizer)

### [ ] Task 3: 사고 로그 추적 (Trace Capture)
- **파일**: `.ai_monitor/server.py`
- **방법**:
    - AI의 도구 호출(특히 `sequentialthinking`) 로그를 실시간으로 캐싱하는 싱글톤 객체 구현.
    - `/api/events/thoughts` SSE(Server-Sent Events) 엔드포인트 추가.
- **검증**: 도구 호출 시 브라우저에서 SSE 이벤트를 수신하는지 확인.

### [ ] Task 4: 프론트엔드 사고 타임라인 UI 구현
- **파일**: `vibe-view/src/App.tsx`, `vibe-view/src/components/ThoughtTrace.tsx` (신규)
- **방법**:
    - 메인 대시보드 좌측/우측에 'Thought Trace' 패널 추가.
    - 수신된 SSE 데이터를 기반으로 노드 그래프 또는 타임라인 시각화.
- **검증**: AI가 작업하는 동안 UI에 실시간으로 사고 과정이 업데이트되는지 확인.

---

## 🤝 단계 3: 에이전트 협업 프로토콜 (Agent RFC)

### [ ] Task 5: RFC(Request for Comments) 시스템 구축
- **파일**: `scripts/agent_protocol.py` (신규), `scripts/memory.py`
- **방법**:
    - `RFC` 상태 관리 (PENDING, ACCEPTED, COMPLETED) 로직 구현.
    - 에이전트가 `memory.py set` 시 `--type rfc` 옵션을 줄 수 있도록 확장.
- **검증**: Gemini가 발행한 RFC를 Claude가 수락하고 상태를 업데이트하는 워크플로우 확인.

---

## 🔄 최종 통합 및 자가 진단
- `PROJECT_MAP.md` 업데이트 및 모든 신규 파일에 표준 헤더 적용.
- `CHANGELOG.md` v5.0 업데이트.

---
**작성일**: 2026-02-26
**에이전트**: Gemini-1 (Master)

---

# 🔍 ThoughtTrace 벡터 메모리 검색 UI 추가 계획

**목표**: 오른쪽 패널(ThoughtTrace)에 탭 구조 추가 — [🧠 사고] / [🔍 메모리] 전환
**승인일**: 2026-02-26
**담당**: Claude
**상태**: 실행 대기 중

## Task 1: server.py에 벡터 검색 API 엔드포인트 추가

```
[ ] Task 1: /api/vector/search (POST) 및 /api/vector/list (GET) 엔드포인트 구현
    파일: .ai_monitor/server.py
    방법:
      - 파일 상단 sys.path에 scripts/ 디렉터리 추가 (이미 있으면 생략)
      - do_GET: /api/vector/list → VectorMemory().collection.get() 전체 항목 반환
        응답: { "items": [{ "id", "content", "metadata" }] }
      - do_POST: /api/vector/search → body { "query": str, "n": int=5 } 받아
        VectorMemory().search(query, n) 호출 후 결과 반환
        응답: { "results": [{ "id", "content", "metadata", "distance" }] }
      - 예외 처리: chromadb 미설치 시 503 + 안내 메시지 반환
    검증: 서버 재시작 후 POST /api/vector/search {"query":"테스트"} 응답 200 확인
```

## Task 2: ThoughtTrace.tsx — 탭 UI + 벡터 검색 패널 구현

```
[ ] Task 2: ThoughtTrace 컴포넌트에 탭 전환 + 벡터 검색 UI 추가
    파일: .ai_monitor/vibe-view/src/components/ThoughtTrace.tsx
    의존성: Task 1 완료 후 시작
    방법:
      - import 추가: Search, Database, Loader2 (lucide-react)
      - state 추가:
          activeTab: 'thoughts' | 'vector'
          vectorQuery: string
          vectorResults: VectorResult[]
          isSearching: boolean
      - 헤더 영역에 탭 버튼 삽입 (isOpen일 때만 표시):
          [🧠 사고] [🔍 메모리]
          활성 탭: border-b-2 border-primary 강조
      - 기존 thoughts 렌더링을 activeTab === 'thoughts' 조건으로 감싸기
      - vector 탭 UI:
          1) 검색 입력창 + Enter/버튼으로 POST /api/vector/search 호출
          2) 로딩 중: Loader2 스피너
          3) 결과 없음: Database 아이콘 + "저장된 기억 없음" 안내
          4) 결과 카드:
             - content 앞 100자 미리보기
             - 유사도 배지: ((1 - distance) * 100).toFixed(0) + '%'
             - 유사도 70%↑: 초록, 50~70: 노랑, 50↓: 회색
             - 클릭 시 전체 내용 expand
             - 메타데이터 태그 (type, agent 등)
      - 서버 포트: App.tsx에서 사용하는 방식 동일하게 window.SERVER_PORT 또는 8765 기본값 사용
    검증: 탭 클릭 → 검색창 표시 → 쿼리 입력 → 결과 카드 렌더링 확인
```

## Task 3: 프론트엔드 빌드 및 배포

```
[ ] Task 3: npm run build 실행 후 dist/ 반영 확인
    파일: .ai_monitor/vibe-view/
    의존성: Task 2 완료 후 시작
    방법:
      - cd .ai_monitor/vibe-view && npm run build
      - 빌드 성공 여부 확인
    검증: .ai_monitor/dist/index.html 수정 시각이 현재 시각 기준 최신인지 확인
```

## 완료 기준
- [ ] 오른쪽 패널에서 [🧠 사고] / [🔍 메모리] 탭 전환 가능
- [ ] 검색창 쿼리 입력 → 결과 카드 표시 (유사도 % 포함)
- [ ] 빈 상태 UI 처리 완료
- [ ] 빌드 성공, dist/ 최신화

---
**작성일**: 2026-02-26
**담당 에이전트**: Claude
