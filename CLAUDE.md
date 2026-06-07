<!--
FILE: CLAUDE.md
DESCRIPTION: 프로젝트 루트의 자동 로드 규칙 파일. 모든 Claude/AI 세션 시작 시 자동 주입됨.
             세부 규칙은 .claude/rules/ 하위 + RULES.md에 위임하되, **위반 시 즉시 거부**해야 하는
             절대 규칙은 이 파일에 직접 박는다. (LLM이 RULES.md 별도 조회를 누락하는 사고 반복.)

REVISION HISTORY:
- 2026-05-26 Claude: 규칙이 안 지켜진다는 사용자 피드백 반영. 절대 규칙 본문 직접 명시 +
                    파일 1500줄 제한 + LLM 관점 주석 규칙 신규 추가.
- 2026-02-25 (기존): 7개 핵심 규칙을 bullet로 요약 + RULES.md 참조.
-->

# CLAUDE.md — 이 프로젝트의 절대 규칙 (LLM 자동 로드)

AI 멀티 에이전트 하이브 마인드 대시보드. PostgreSQL 18 기반, Windows PyWebView 데스크톱 앱.

---

## 🚨 절대 규칙 — 위반 시 즉시 중단

아래 8개는 **세부 규칙 파일을 읽지 않아도** 항상 적용된다. 위반이 감지되면 진행 전에 반드시 수정한다.

### 1. 한글 필수
대화 출력, 코드 주석, 커밋 메시지 본문, 문서 — **전부 한글**. 영어 식별자/외부 인용은 허용.

### 2. 파일당 1500줄 제한 (주석 포함)
- **모든 코드 파일은 주석 포함 1500줄 이하**. `wc -l <file>` ≤ 1500.
- **초과 시 즉시 분할** — 도메인 책임 단위로 파일을 쪼갠다. "다음에 분리" 금지.
- 새 파일을 만들거나 큰 수정을 한 직후 줄 수를 확인한다.
- 예외 없음. 자동 생성 파일(`vibe-view/dist/*`)은 .gitignore 대상이라 제외.
- 위반 사례: `server.py`(5103줄) — 분할 진행 중. 신규 위반 누적 금지.

### 3. LLM 관점 주석 (사람용 주석 금지)
주석의 독자는 사람이 아니라 **다음 세션의 LLM**이다.

**❌ 금지 — 코드만 보면 알 수 있는 것:**
```python
# X를 Y로 변환
result = transform(x)  # 변환 호출
```

**✅ 필수 — 코드만 봐서는 알 수 없는 것만:**
- **WHY**: 왜 이 방식을 택했는지 (대안과 비교한 이유)
- **제약 조건**: "GIL 보호 없이 호출됨", "Windows EXE 모드에서만 유효", "fsync 없이는 부분 쓰기"
- **불변식**: "lock_a → lock_b 순서 고정 (역순 시 데드락)", "이 큐는 단일 producer 전제"
- **과거 사고**: "v3.7.215~218 `infra/` 누락 사고 — spec datas와 CI --add-data 양쪽 갱신 필수"
- **호환성 함정**: "PyInstaller 정적 분석이 `__import__()`를 못 잡음 → hiddenimports 필수"
- **외부 의존 가정**: "이 API는 PG NOTIFY 채널 `hive_*`만 듣는다고 가정"

**길이 기준**: 의미 있는 1줄 ≥ 형식상 5줄. 표준 헤더(`FILE/DESCRIPTION/REVISION HISTORY`)는 필수 유지.

### 4. PostgreSQL-first 로깅
모든 활동 로그는 `pg_logs` 테이블. `.jsonl`/SQLite 신규 사용 금지(레거시 폴백만).

### 5. 표준 파일 헤더 의무
모든 코드/문서 파일 상단:
```python
"""
FILE: 파일명
DESCRIPTION: 역할 + 핵심 책임 (LLM이 이 파일을 읽을지 1초 안에 판단할 수 있게)

REVISION HISTORY:
- YYYY-MM-DD Author: 수정 사유 (Why) — 1줄
"""
```

### 6. Conventional Commits + 한글 본문
제목만 작성 금지. `## 변경 이유 / ## 변경 내용 / ## 영향 범위` 3단 본문 한글 작성.
상세: `.claude/rules/commit-rules.md`.

### 7. 문서는 PROJECT_MAP.md에 중앙 관리
`docs/` 아래 코드와 1:1 매칭되는 설명 문서 신규 생성 금지. `PROJECT_MAP.md` 갱신으로 대체.

### 8. 작업 완료 자동 리포트
모든 단위 작업 종료 시 다음 3줄 출력:
- **수정/생성된 파일:** (콤마 나열)
- **원인 (Why):** (1줄)
- **수정 내용 (How):** (1~2줄)

---

## 🗂️ 세부 규칙 (자동 로드되는 보조 파일)

- [`.claude/rules/architecture.md`](.claude/rules/architecture.md) — 아키텍처 + 데이터 흐름
- [`.claude/rules/commit-rules.md`](.claude/rules/commit-rules.md) — 커밋 메시지 상세
- [`.claude/rules/hive-sync.md`](.claude/rules/hive-sync.md) — 하이브 동기화 프로토콜
- [`.claude/rules/file-limits.md`](.claude/rules/file-limits.md) — 1500줄 제한 + LLM 주석 가이드
- [`.claude/agents/README.md`](./.claude/agents/README.md) — Subagent 위임 라우팅 정책 (vibe-code-review/security/debug)
- [`RULES.md`](./RULES.md) — 신규 멤버용 종합 안내 (위 규칙들의 풀 버전)
- [`docs/HARNESS_V2.md`](./docs/HARNESS_V2.md) — 하네스 계약

세부 규칙과 본 파일이 충돌하면 **본 파일이 우선**한다.

---

## ⚙️ 빌드 및 실행

```bash
pip install -e .                            # 개발 설치
python .ai_monitor/server.py                # 서버 직접 실행
pyinstaller vibe-coding.spec --noconfirm    # EXE 빌드 (로컬)
pytest tests/                               # 테스트
```

배포는 `/vibe-release` 스킬 사용. 수동으로 `_version.py` 편집 금지.
