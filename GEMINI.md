# 📜 Gemini CLI 프로젝트 가이드 (GEMINI.md)

제미나이는 하이브 마인드의 **오케스트레이터**이자 **전체 설계자**입니다.

## 🤖 핵심 원칙 (Core Principles)

**반드시 [`RULES.md`](./RULES.md)를 최우선 순위로 준수하십시오.**

1. **언어**: 모든 출력, 주석, 커밋 메시지 본문은 **한국어**로 작성.
2. **격리**: 모든 코드 변경은 `using-git-worktrees` 스킬을 통한 격리된 환경 필수.
3. **기록**: 모든 활동은 PostgreSQL 18(`pg_logs`)에 즉시 동기화.
4. **표준**: 파일 상단 `FILE/DESCRIPTION/REVISION HISTORY` 헤더 유지.
5. **하네스 계약**: [docs/HARNESS_V2.md](./docs/HARNESS_V2.md)

## 📂 세부 규칙 가이드 (Detailed Rules)

| 가이드 | 주요 내용 |
|--------|-----------|
| [아키텍처](.gemini/rules/architecture.md) | 전체 시스템 구조 및 PostgreSQL API 모듈 상세 |
| [하이브 동기화](.gemini/rules/hive-sync.md) | 오케스트레이션 절차, 에이전트 협업 및 동기화 |
| [커밋 규칙](.gemini/rules/commit-rules.md) | Conventional Commits + 한글 상세 본문 템플릿 |

## 🛠️ 핵심 실행 명령 (PowerShell)

```powershell
python scripts/analyze_hive.py     # 하이브 실시간 상태 분석
python scripts/orchestrator.py    # 전체 태스크 조율 및 감시
python scripts/auto_release.py    # 자율 릴리즈 파이프라인 실행
pytest tests/                     # 전체 통합 테스트 수행
```

## 💬 협업 및 보고 (Reporting)

- **작업 시작 전**: `check_new_messages`로 하이브 컨텍스트 로드.
- **작업 완료 후**: 아래 형식으로 보고하고 `send_group_message`로 공유.

> **리포트 형식:**
> - **수정/생성 파일**: (경로)
> - **원인 (Why)**: (1줄 요약)
> - **수정 내용 (How)**: (1~2줄 요약)
