# CLAUDE.md

AI 멀티 에이전트 하이브 마인드 대시보드. PostgreSQL 18 기반, Windows PyWebView.

## 핵심 규칙

**반드시 [`RULES.md`](./RULES.md)를 먼저 읽고 모든 규칙을 절대적으로 준수할 것.**

- **한글 필수**: 주석, 커밋 본문, 대화 출력 모두 한글
- **표준 헤더**: 모든 파일 상단에 FILE/DESCRIPTION/REVISION HISTORY 포함
- **PostgreSQL-first**: 로깅은 `pg_logs` 테이블 (`.jsonl`/SQLite 금지)
- **Git worktree**: 새 기능은 격리된 worktree에서 작업
- **커밋**: Conventional Commits + 한글 본문 (상세: `.claude/rules/commit-rules.md`)
- **문서 금지**: `docs/` 내 1:1 설명 문서 대신 `PROJECT_MAP.md` 중앙 관리
- **하네스 계약**: [docs/HARNESS_V2.md](./docs/HARNESS_V2.md)

## 빌드 및 실행

```bash
pip install -e .           # 개발 설치
python .ai_monitor/server.py  # 서버 직접 실행
pyinstaller vibe-coding.spec --noconfirm  # EXE 빌드
pytest tests/              # 테스트
```

## 작업 완료 리포트 (필수)

- **수정/생성된 파일:** (경로 나열)
- **원인 (Why):** (1줄 요약)
- **수정 내용 (How):** (1~2줄 요약)
