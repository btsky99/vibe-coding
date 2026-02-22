# Claude Code 사용 설명서

> Anthropic의 공식 AI 코딩 에이전트 CLI 도구

---

## 1. 설치

### 권장 설치 (자동 업데이트 지원)

**Windows PowerShell:**
```powershell
irm https://claude.ai/install.ps1 | iex
```

**Windows CMD:**
```batch
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```

**macOS / Linux / WSL:**
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### 기타 설치 방법
```bash
# Homebrew (자동 업데이트 없음)
brew install --cask claude-code

# WinGet (자동 업데이트 없음)
winget install Anthropic.ClaudeCode
```

### 인증 방법
| 방법 | 설명 |
|------|------|
| **Claude Pro/Max/Teams** | 구독 계정으로 로그인 (권장) |
| **API 키** | Console에서 선불 크레딧 충전 후 사용 |
| **클라우드** | AWS Bedrock, Google Vertex AI, MS Foundry |

---

## 2. 기본 사용법

### 실행 명령어

| 명령어 | 설명 |
|--------|------|
| `claude` | 대화형 세션 시작 |
| `claude "질문"` | 초기 질문과 함께 시작 |
| `claude -p "질문"` | 질문에 답하고 바로 종료 (비대화형) |
| `claude -c` | 가장 최근 대화 이어하기 |
| `claude -r "세션명"` | 특정 세션 재개 |
| `claude update` | 최신 버전으로 업데이트 |
| `claude doctor` | 설치 상태 점검 |
| `claude commit` | Git 커밋 생성 |

### 파이프 활용
```bash
# 파일 내용을 분석
cat error.log | claude -p "이 에러 원인 분석해"

# 명령 결과 분석
git diff | claude -p "이 변경 사항 리뷰해"

# 결과를 파일로 저장
claude -p "README 작성해" > README.md
```

---

## 3. 주요 CLI 플래그

| 플래그 | 짧은 형태 | 설명 |
|--------|-----------|------|
| `--print` | `-p` | 비대화형 모드 (답변 후 종료) |
| `--continue` | `-c` | 최근 대화 이어하기 |
| `--resume` | `-r` | 특정 세션 재개 |
| `--model` | | 모델 선택 (`sonnet`, `opus`) |
| `--worktree` | `-w` | 격리된 Git 워크트리에서 작업 |
| `--permission-mode` | | 권한 모드 설정 |
| `--max-turns` | | 최대 에이전트 턴 수 제한 |
| `--max-budget-usd` | | 최대 API 비용 제한 |
| `--verbose` | | 상세 로그 출력 |
| `--debug` | | 디버그 모드 |
| `--allowedTools` | | 자동 허용할 도구 목록 |
| `--disallowedTools` | | 사용 금지할 도구 목록 |
| `--system-prompt` | | 시스템 프롬프트 교체 |
| `--json-schema` | | JSON 스키마에 맞는 출력 |
| `--output-format` | | 출력 형식 (`text`, `json`, `stream-json`) |
| `--mcp-config` | | MCP 서버 설정 파일 |
| `--remote` | | claude.ai 웹 세션 생성 |
| `--dangerously-skip-permissions` | | 모든 권한 확인 건너뛰기 (주의!) |

---

## 4. 슬래시 명령어 (대화형 세션 내)

### 세션 관리
| 명령어 | 설명 |
|--------|------|
| `/clear` | 대화 기록 초기화 |
| `/compact [지침]` | 대화 압축 (컨텍스트 절약) |
| `/exit` | 세션 종료 |
| `/resume [세션]` | 이전 세션 재개 |
| `/rename <이름>` | 현재 세션 이름 변경 |
| `/rewind` | 대화/코드 되돌리기 |
| `/export [파일명]` | 대화 내용 내보내기 |
| `/copy` | 마지막 응답 클립보드 복사 |

### 정보 확인
| 명령어 | 설명 |
|--------|------|
| `/help` | 도움말 표시 |
| `/status` | 버전, 모델, 계정, 연결 상태 확인 |
| `/cost` | 토큰 사용량 통계 |
| `/stats` | 일별 사용량, 세션 기록 |
| `/usage` | 플랜 사용 한도 및 속도 제한 |
| `/context` | 컨텍스트 사용량 시각화 |
| `/todos` | 현재 TODO 항목 목록 |
| `/tasks` | 백그라운드 작업 관리 |

### 설정 및 구성
| 명령어 | 설명 |
|--------|------|
| `/config` | 설정 인터페이스 열기 |
| `/model` | AI 모델 선택/변경 |
| `/permissions` | 권한 설정 확인/변경 |
| `/memory` | CLAUDE.md 메모리 파일 편집 |
| `/init` | 프로젝트 CLAUDE.md 초기화 |
| `/theme` | 색상 테마 변경 |
| `/vim` | Vim 편집 모드 활성화 |
| `/terminal-setup` | 터미널 키바인딩 설정 |
| `/statusline` | 상태 표시줄 설정 |
| `/login` | 로그인/계정 전환 |

### 도구 관리
| 명령어 | 설명 |
|--------|------|
| `/mcp` | MCP 서버 연결 관리 |
| `/hooks` | 훅(Hook) 관리자 |
| `/doctor` | 설치 상태 점검 |
| `/debug [설명]` | 디버그 로그로 문제 해결 |
| `/plan` | 계획 모드 진입 |
| `/desktop` | 데스크톱 앱으로 전환 |

### 입력 단축 접두사
| 접두사 | 동작 |
|--------|------|
| `/` | 슬래시 명령어 또는 스킬 호출 |
| `!` | 쉘 명령어 직접 실행 |
| `@` | 파일 경로 자동완성 / MCP 리소스 참조 |

---

## 5. 키보드 단축키

### 일반 조작
| 단축키 | 설명 |
|--------|------|
| `Ctrl+C` | 현재 입력/생성 취소 |
| `Ctrl+D` | 세션 종료 |
| `Ctrl+G` | 기본 텍스트 에디터에서 열기 |
| `Ctrl+L` | 터미널 화면 지우기 |
| `Ctrl+O` | 상세 출력 토글 |
| `Ctrl+R` | 명령어 기록 역방향 검색 |
| `Ctrl+V` | 클립보드에서 이미지 붙여넣기 |
| `Ctrl+B` | 백그라운드 작업 전환 |
| `Ctrl+T` | 작업 목록 표시 토글 |
| `Ctrl+F` | 백그라운드 에이전트 전체 종료 (2번 눌러 확인) |
| `Esc Esc` | 되돌리기 또는 요약 |
| `Shift+Tab` / `Alt+M` | 권한 모드 전환 |
| `Alt+P` | 모델 전환 (프롬프트 유지) |
| `Alt+T` | 확장 사고(Extended Thinking) 토글 |

### 텍스트 편집
| 단축키 | 설명 |
|--------|------|
| `Ctrl+K` | 줄 끝까지 삭제 |
| `Ctrl+U` | 전체 줄 삭제 |
| `Ctrl+Y` | 삭제한 텍스트 붙여넣기 |
| `Alt+B` | 커서를 한 단어 뒤로 |
| `Alt+F` | 커서를 한 단어 앞으로 |

### 여러 줄 입력
| 방법 | 단축키 |
|------|--------|
| 빠른 줄바꿈 | `\` + `Enter` |
| macOS | `Option+Enter` |
| 범용 | `Ctrl+J` |
| 일부 터미널 | `Shift+Enter` |

---

## 6. 권한 모드

| 모드 | 설명 |
|------|------|
| **default** | 기본값. 첫 사용 시 권한 확인 |
| **acceptEdits** | 파일 편집 자동 승인 |
| **plan** | 읽기 전용 - 분석만 가능, 수정 불가 |
| **dontAsk** | 사전 승인된 것만 허용, 나머지 자동 거부 |
| **bypassPermissions** | 모든 권한 확인 건너뛰기 (격리 환경 전용) |

### 권한 규칙 문법
```
Bash(npm run *)        → npm run으로 시작하는 명령어 허용
Read(./.env)           → .env 파일 읽기 허용
WebFetch(domain:example.com)  → 특정 도메인 접근 허용
```

**평가 순서**: Deny(거부) > Ask(확인) > Allow(허용)

---

## 7. 메모리 시스템 (CLAUDE.md)

Claude Code는 계층적 메모리 시스템을 사용합니다.

### 메모리 파일 우선순위 (높음 → 낮음)

| 유형 | 위치 | 공유 범위 |
|------|------|-----------|
| **관리 정책** | `C:\Program Files\ClaudeCode\CLAUDE.md` | 조직 전체 |
| **프로젝트** | `./CLAUDE.md` 또는 `./.claude/CLAUDE.md` | 팀 (Git 공유) |
| **프로젝트 규칙** | `./.claude/rules/*.md` | 팀 (Git 공유) |
| **사용자** | `~/.claude/CLAUDE.md` | 개인 전체 |
| **프로젝트 로컬** | `./CLAUDE.local.md` | 개인 현재 프로젝트 |
| **자동 메모리** | `~/.claude/projects/<프로젝트>/memory/` | 개인 프로젝트별 |

### 주요 기능
- **자동 메모리**: 패턴, 디버깅 인사이트, 설정 등을 자동 저장
- **import 구문**: `@path/to/import`로 다른 파일 포함 가능
- **경로별 규칙**: `.claude/rules/` 내 파일에 `paths` 프론트매터로 특정 파일에만 적용
- **`/init`**: 프로젝트용 CLAUDE.md 자동 생성
- **`/memory`**: 메모리 파일을 에디터에서 편집

---

## 8. 설정 파일

### 설정 파일 위치 (우선순위 순)

| 범위 | 위치 | 공유 |
|------|------|------|
| CLI 인자 | 명령줄 | 세션만 |
| 로컬 | `.claude/settings.local.json` | 개인 (gitignore) |
| 프로젝트 | `.claude/settings.json` | 팀 (커밋) |
| 사용자 | `~/.claude/settings.json` | 개인 |

### 주요 설정 항목
```json
{
  "model": "claude-sonnet-4-6",
  "permissions": {
    "allow": ["Bash(npm run *)"],
    "deny": ["Bash(rm -rf *)"]
  },
  "hooks": { },
  "env": { "NODE_ENV": "development" },
  "language": "ko",
  "outputStyle": "concise"
}
```

### 주요 환경 변수
| 변수 | 용도 |
|------|------|
| `ANTHROPIC_API_KEY` | API 키 |
| `ANTHROPIC_MODEL` | 사용할 모델 |
| `CLAUDE_CODE_EFFORT_LEVEL` | `low`, `medium`, `high` |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 최대 출력 토큰 (기본 32000) |
| `MAX_THINKING_TOKENS` | 확장 사고 토큰 예산 |
| `BASH_DEFAULT_TIMEOUT_MS` | Bash 기본 타임아웃 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 프록시 서버 |

---

## 9. MCP 서버 (외부 도구 연결)

### 서버 추가
```bash
# HTTP 서버 (원격 권장)
claude mcp add --transport http <이름> <URL>

# 로컬 stdio 서버
claude mcp add --transport stdio <이름> -- <명령> [인자...]

# 환경 변수 포함
claude mcp add --transport stdio --env API_KEY=값 myserver -- npx -y @some/package

# Windows에서 npx 사용 시
claude mcp add --transport stdio my-server -- cmd /c npx -y @some/package

# Claude Desktop 설정 가져오기
claude mcp add-from-claude-desktop
```

### 서버 관리
```bash
claude mcp list          # 목록 확인
claude mcp get <이름>     # 상세 정보
claude mcp remove <이름>  # 삭제
```

---

## 10. 훅(Hooks) 시스템

훅은 특정 이벤트 시점에 자동 실행되는 사용자 정의 명령입니다.

### 주요 이벤트
| 이벤트 | 시점 | 차단 가능 |
|--------|------|-----------|
| `PreToolUse` | 도구 실행 전 | O |
| `PostToolUse` | 도구 실행 후 | X |
| `UserPromptSubmit` | 사용자 입력 제출 시 | O |
| `Stop` | Claude 응답 완료 시 | O |
| `SessionStart` | 세션 시작 시 | X |
| `SessionEnd` | 세션 종료 시 | X |

### 핸들러 유형
- **command**: 쉘 명령 실행
- **prompt**: 단일 LLM 평가
- **agent**: 도구 접근 가능한 멀티턴 서브에이전트

### 설정 예시
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "command": ".claude/hooks/check-cmd.sh",
          "timeout": 600
        }]
      }
    ]
  }
}
```

---

## 11. 스킬 (커스텀 슬래시 명령)

스킬은 재사용 가능한 AI 워크플로우입니다.

### 스킬 파일 위치
- 개인: `~/.claude/skills/<이름>/SKILL.md`
- 프로젝트: `.claude/skills/<이름>/SKILL.md`

### SKILL.md 예시
```markdown
---
name: 코드리뷰
description: PR 코드 리뷰 수행
allowed-tools:
  - Read
  - Grep
  - Glob
---

현재 변경된 파일들을 분석하고 다음 기준으로 코드 리뷰를 수행하세요:
1. 보안 취약점
2. 성능 문제
3. 코드 스타일

$ARGUMENTS
```

사용법: `/코드리뷰 src/main.ts` 입력

### 프론트매터 필드
| 필드 | 설명 |
|------|------|
| `name` | 표시 이름 (슬래시 명령 이름) |
| `description` | 용도 설명 |
| `allowed-tools` | 권한 없이 사용할 도구 |
| `model` | 사용할 모델 |
| `context: fork` | 서브에이전트에서 실행 |
| `user-invocable: false` | Claude 전용 (사용자 호출 불가) |

---

## 12. 내장 도구

| 도구 | 설명 |
|------|------|
| `Bash` | 쉘 명령 실행 |
| `Read` | 파일 읽기 |
| `Edit` | 파일 내 문자열 교체 |
| `Write` | 파일 생성/덮어쓰기 |
| `Glob` | 패턴으로 파일 찾기 |
| `Grep` | 정규식으로 파일 내용 검색 |
| `WebFetch` | 웹 콘텐츠 가져오기 |
| `WebSearch` | 웹 검색 |
| `Task` | 서브에이전트 실행 |
| `NotebookEdit` | Jupyter 노트북 편집 |
| `AskUserQuestion` | 사용자에게 질문 |
| `EnterWorktree` | 격리된 Git 워크트리 생성 |

---

## 13. IDE 통합

| IDE | 설치 방법 |
|-----|-----------|
| **VS Code** | 확장 프로그램에서 "Claude Code" 검색 |
| **JetBrains** | 플러그인 마켓에서 "Claude Code" 검색 |
| **Cursor** | VS Code와 동일한 방법 |
| **데스크톱 앱** | macOS / Windows 지원, `/desktop`으로 전환 |
| **웹** | claude.ai/code, `--remote`로 웹 세션 생성 |

---

## 14. 실전 활용 팁

### 자주 쓰는 워크플로우

```bash
# 코드베이스 이해하기
claude "이 프로젝트 구조 설명해"

# 버그 수정
claude "이 에러 메시지 원인 찾고 수정해: [에러 내용]"

# 테스트 작성
claude "src/utils.ts에 대한 단위 테스트 작성해"

# PR 생성
claude "변경 사항 커밋하고 PR 만들어"

# 코드 리팩토링
claude "이 함수를 더 효율적으로 개선해"

# 문서 생성
claude -p "이 모듈의 API 문서 작성해" > docs/api.md
```

### 효율적 사용을 위한 팁
1. **구체적으로 요청**: "개선해줘" 대신 "에러 처리 추가해줘"
2. **복잡한 작업은 단계별로**: 한 번에 하나씩 요청
3. **`@`로 파일 참조**: `@src/main.ts` 형식으로 직접 파일 지정
4. **`/compact` 활용**: 대화가 길어지면 컨텍스트 압축
5. **`Esc Esc`**: 실수한 변경 사항 되돌리기
6. **Plan 모드**: 큰 작업 전 `--permission-mode plan`으로 먼저 분석
7. **워크트리**: `claude -w feature` 로 격리된 브랜치에서 작업
