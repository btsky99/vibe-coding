# 📋 Vibe Coding 리팩토링 + 기능 추가 계획
**작성일**: 2026-03-01
**버전**: v3.6.10 → v3.7.x
**상태**: 승인 대기

---

## 📊 현황 요약
| 파일 | 현재 상태 | 문제 |
|------|-----------|------|
| `server.py` | 3690줄, API 50+ 개 | 유지보수 어려움 |
| `App.tsx` | 3289줄, 9개 탭 | 단일 파일에 UI 집중 |
| `components/` | ThoughtTrace, VibeEditor만 | 컴포넌트 분리 미흡 |

---

## [ ] Task 1: 문서 업데이트
**소요**: ~15분 | **위험도**: 없음

```
파일: PROJECT_MAP.md, memory/current-work.md
방법:
  - PROJECT_MAP.md에 누락된 파일 추가
    (gemini_hook.py, hive_hook.py, skill_orchestrator.py,
     skill_analyzer.py, skill_manager.py, agent_protocol.py)
  - skills/claude/ 디렉토리 구조 반영
  - current-work.md 세션 기록 업데이트
검증: 파일 목록과 PROJECT_MAP.md 내용 일치 확인
```

---

## [ ] Task 2-A: App.tsx 사이드바 패널 컴포넌트 분리
**소요**: ~90분 | **위험도**: 중간 (worktree 필수)
**의존성**: Task 1 완료 후

```
파일:
  - vibe-view/src/components/panels/OrchestratorPanel.tsx (신규) — 1542~1671줄
  - vibe-view/src/components/panels/HivePanel.tsx (신규)         — 1672~1881줄
  - vibe-view/src/components/panels/MemoryPanel.tsx (신규)       — 1433~1541줄
  - vibe-view/src/components/panels/McpPanel.tsx (신규)          — 1992~2437줄
  - vibe-view/src/components/panels/MessagesPanel.tsx (신규)     — 1222~1312줄
  - vibe-view/src/components/panels/TasksPanel.tsx (신규)        — 1313~1432줄
  - vibe-view/src/components/panels/GitPanel.tsx (신규)          — 1882~1991줄
방법:
  - 각 탭의 JSX 블록을 별도 파일로 추출
  - 상태/핸들러는 App.tsx에 유지, props로 전달
  - 타입은 types.ts에서 import
검증: npm run build 성공 + 각 탭 정상 렌더링
```

## [ ] Task 2-B: App.tsx 정리
**의존성**: Task 2-A 완료 후

```
파일: vibe-view/src/App.tsx
방법:
  - 분리된 컴포넌트 import로 교체
  - 목표: 1500줄 이하로 감소
검증: 빌드 성공 + 기능 동일
```

---

## [ ] Task 3: 스킬 실행 결과 UI 패널 (신규 기능)
**소요**: ~60분 | **위험도**: 낮음
**의존성**: Task 2 완료 후

```
Task 3-A 백엔드 API 추가:
  파일: .ai_monitor/server.py
  방법:
    - GET /api/skill-results — skill_results.jsonl 읽어 반환 (최근 50개)
      응답: [{session_id, request, results:[{skill, status, summary}], completed_at}]
  검증: API 응답 확인

Task 3-B 프론트엔드 SkillResultsPanel:
  파일:
    - vibe-view/src/components/panels/SkillResultsPanel.tsx (신규)
    - vibe-view/src/types.ts (SkillResult 타입 추가)
  방법:
    - 좌측 사이드바 아이콘 탭 추가 (Zap 아이콘)
    - 세션별 카드: 요청, 실행한 스킬 체인, 완료시간
    - 스킬 상태 배지: done(녹색), skipped(회색), error(빨간색)
    - 30초 폴링
  검증: 탭 전환 시 skill_results.jsonl 데이터 표시
```

---

## [ ] Task 4: 에이전트 채팅 뷰 UI 개선
**소요**: ~60분 | **위험도**: 낮음
**의존성**: Task 2 완료 후

```
파일: vibe-view/src/components/panels/MessagesPanel.tsx
방법:
  - 현재 단순 리스트 → 채팅 버블 스타일 전환
    Claude: 파란 버블 (우측), Gemini: 초록 버블 (좌측), User: 회색 (중앙)
  - 세션 구분선 표시 (날짜/시간)
  - 에이전트별 아바타 아이콘
  - 자동 스크롤 (새 메시지 시 하단)
검증: 채팅 버블 뷰로 표시
```

---

## [ ] Task 5: server.py 모듈 분리 (리팩토링, 별도 진행)
**소요**: ~120분 | **위험도**: 높음 (worktree 필수)
**의존성**: Task 1~4 모두 완료 + 별도 커밋 후

```
Task 5-A 공통 설정 모듈:
  파일: .ai_monitor/server_config.py (신규)
  방법: 전역 변수(DATA_DIR, BASE_DIR 등) → server_config.py로 이동

Task 5-B API 핸들러 분리:
  파일:
    - .ai_monitor/api/memory_api.py — /api/memory, /api/project-info
    - .ai_monitor/api/mcp_api.py    — /api/mcp/*
    - .ai_monitor/api/hive_api.py   — /api/hive/*
    - .ai_monitor/api/file_api.py   — /api/files/*, /api/browse-folder
    - .ai_monitor/api/git_api.py    — /api/git/*
  방법: handle_xxx(handler, parsed_path, params) 함수 형태로 분리

Task 5-C PyInstaller spec 업데이트:
  파일: vibe-coding.spec
  방법: hiddenimports에 신규 모듈 추가
검증: 배포 EXE 실행 후 전체 API 정상 확인
```

---

## 📐 실행 순서
```
Task 1 (문서) → Task 2 (컴포넌트 분리) → Task 3 (스킬 결과 UI)
                                        → Task 4 (채팅 뷰 개선)
                                        → Task 5 (server 분리, 마지막)
```

## ⚠️ 주의사항
- Task 2, 5는 반드시 Git Worktree에서 진행
- Task 5는 배포 버전 검증 필수 (frozen 모드에서 import 경로 다름)
- 각 Task 완료 시 npm run build (프론트) 또는 python 문법 검사 실행
