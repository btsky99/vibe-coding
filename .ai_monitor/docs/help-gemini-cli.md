# Gemini CLI 사용 설명서

> Google의 오픈소스 AI 코딩 에이전트 CLI 도구 (Apache 2.0)

---

## 1. 설치

### 사전 요구사항
- **Node.js v18 이상** 및 npm

### npm 설치 (권장)
```bash
npm install -g @google/gemini-cli
```

### 기타 패키지 매니저
```bash
yarn global add @google/gemini-cli
pnpm install -g @google/gemini-cli
```

### 설치 없이 바로 실행
```bash
npx @google/gemini-cli
```

### 실행
```bash
gemini
```

---

## 2. 인증 방법

| 방법 | 설정 | 비용 |
|------|------|------|
| **Google 로그인** | `gemini` 실행 후 "Login with Google" 선택 | 무료 (일 1000건, 분 60건) |
| **API 키** | `GEMINI_API_KEY` 환경변수 또는 `~/.gemini/.env` | 종량제 |
| **Vertex AI** | `GOOGLE_APPLICATION_CREDENTIALS` 설정 | GCP 요금 |

### 무료 티어 한도
| 항목 | 한도 |
|------|------|
| 분당 요청 | 60건 |
| 일일 요청 | 1,000건 |
| 컨텍스트 윈도우 | 1,000,000 토큰 |
| 비용 | 무료 |

---

## 3. 사용 가능한 모델

| 모델 | 접근 |
|------|------|
| **Gemini 2.5 Flash** | 무료, 모든 사용자 |
| **Gemini 2.5 Pro** | 무료, 모든 사용자 |
| **Gemini 3 Pro** | AI Ultra 구독자 또는 유료 API 키 |
| **Gemini 3.1 Pro** | 최신, 프리뷰 채널 |

**자동 라우팅** (기본): 단순 질문은 Flash, 복잡한 질문은 Pro 자동 선택

```bash
# 특정 모델 지정
gemini --model gemini-2.5-pro
gemini -m gemini-3-pro-preview
```

---

## 4. 기본 사용법

### 실행 명령어

```bash
# 대화형 세션 시작
gemini

# 비대화형 (질문 후 종료)
gemini -p "이 코드베이스 설명해"

# 초기 질문과 함께 대화형 시작
gemini -i "프로젝트 구조 분석해"

# 파이프 입력
cat error.log | gemini

# 샌드박스 모드 (Docker 격리)
gemini --sandbox

# 자동 승인 모드 (모든 도구 자동 실행 - 주의!)
gemini --yolo

# CI/CD 자동화용
gemini --non-interactive --yolo --output-format json -p "테스트 실행 후 결과 보고"
```

---

## 5. CLI 플래그

| 플래그 | 짧은 형태 | 설명 |
|--------|-----------|------|
| `--model <이름>` | `-m` | 사용할 모델 지정 |
| `--prompt <텍스트>` | `-p` | 비대화형 모드 (답변 후 종료) |
| `--prompt-interactive <텍스트>` | `-i` | 초기 질문과 함께 대화형 시작 |
| `--sandbox` | `-s` | 샌드박스 실행 (Docker/Podman) |
| `--yolo` | `-y` | 모든 도구 호출 자동 승인 (주의!) |
| `--checkpointing` | | 파일 수정 전 스냅샷 저장 |
| `--debug` | `-d` | 디버그 출력 활성화 |
| `--output-format <형식>` | | 비대화형 출력 형식 (`json` 등) |
| `--non-interactive` | | 모든 프롬프트 차단 방지 (CI/CD용) |

---

## 6. 슬래시 명령어 (대화형 세션 내)

### 세션 관리
| 명령어 | 설명 |
|--------|------|
| `/help` (별칭 `/?`) | 명령어 도움말 표시 |
| `/quit` (별칭 `/exit`) | Gemini CLI 종료 |
| `/clear` | 터미널 화면 지우기 |
| `/about` | 버전 정보 표시 |

### 대화 관리
| 명령어 | 설명 |
|--------|------|
| `/chat save <태그>` | 대화 상태 태그로 저장 |
| `/chat resume <태그>` | 저장된 대화 재개 |
| `/chat list` | 저장된 대화 태그 목록 |
| `/chat delete <태그>` | 저장된 체크포인트 삭제 |
| `/chat share file.md` | 대화를 Markdown/JSON으로 내보내기 |

### 컨텍스트 & 메모리
| 명령어 | 설명 |
|--------|------|
| `/memory show` | 현재 GEMINI.md 컨텍스트 표시 |
| `/memory add <텍스트>` | AI 메모리에 텍스트 추가 |
| `/memory refresh` | 모든 GEMINI.md 파일 다시 로드 |
| `/memory list` | 사용 중인 GEMINI.md 파일 경로 표시 |
| `/compress` | 대화 컨텍스트 요약 (토큰 절약) |
| `/init` | 코드베이스 분석 후 GEMINI.md 자동 생성 |

### 도구 & 확장
| 명령어 | 설명 |
|--------|------|
| `/tools` | 사용 가능한 도구 목록 |
| `/tools desc` | 도구 목록 + 설명 |
| `/mcp` | MCP 서버 목록 및 연결 상태 |
| `/mcp desc` | MCP 서버 + 도구 설명 |
| `/mcp schema` | 전체 JSON 파라미터 스키마 |
| `/extensions` | 활성 확장 목록 |

### 설정 & 구성
| 명령어 | 설명 |
|--------|------|
| `/settings` | settings.json 편집기 열기 |
| `/theme` | 시각적 테마 변경 |
| `/vim` | Vim 모드 토글 |
| `/auth` | 인증 방법 변경 |
| `/editor` | 텍스트 에디터 선택 |

### 작업 공간 & 파일
| 명령어 | 설명 |
|--------|------|
| `/directory add <경로>` | 작업 공간에 디렉토리 추가 |
| `/directory show` | 모든 작업 공간 디렉토리 표시 |
| `/copy` | 마지막 응답 클립보드 복사 |
| `/stats` | 토큰 사용량 및 세션 시간 |

### 복원 (`--checkpointing` 필요)
| 명령어 | 설명 |
|--------|------|
| `/restore` | 사용 가능한 체크포인트 목록 |
| `/restore <id>` | 특정 체크포인트로 파일 복원 |

### IDE 통합
| 명령어 | 설명 |
|--------|------|
| `/ide install` | IDE 통합 설정 |
| `/ide enable` | IDE 연결 (VS Code) |

---

## 7. 특수 입력 문법

### @ (컨텍스트 참조)
프롬프트에서 파일/디렉토리를 직접 참조:
```
@./src/main.js 이 파일 설명해
@./screenshot.png 이 UI 설명해
@./src/ 이 디렉토리 모든 코드 요약해
```

**지원 형식**: 텍스트 파일, 이미지(PNG, JPG), PDF, 오디오, 비디오
`.gitignore`와 `.geminiignore` 규칙을 따릅니다.

### ! (쉘 모드)
```
!git status          # 단일 쉘 명령 실행
!                    # 지속 쉘 모드 토글
```

---

## 8. 키보드 단축키

| 단축키 | 기능 |
|--------|------|
| `Ctrl+L` | 화면 지우기 |
| `Ctrl+V` | 클립보드에서 텍스트/이미지 붙여넣기 |
| `Ctrl+Y` | YOLO 모드 토글 |
| `Ctrl+X` | 외부 에디터에서 프롬프트 열기 |
| `Ctrl+Z` | 실행 취소 |
| `Ctrl+Shift+Z` | 다시 실행 |

---

## 9. 내장 도구

### 파일 시스템 도구
| 도구 | 기능 |
|------|------|
| `read_file(path)` | 단일 파일 읽기 |
| `read_many_files(paths)` | 여러 파일 한번에 읽기 |
| `write_file(file_path, content)` | 파일 쓰기/생성 |
| `replace(file_path, old, new)` | 파일 내 문자열 교체 |
| `list_directory(path)` | 디렉토리 목록 |
| `glob(pattern)` | 글로브 패턴으로 파일 찾기 |
| `grep_search(pattern)` | 정규식으로 파일 내용 검색 |

### 쉘 도구
| 도구 | 기능 |
|------|------|
| `run_shell_command(command)` | 쉘 명령 실행 |

### 웹 도구
| 도구 | 기능 |
|------|------|
| `google_web_search(query)` | Google 검색 |
| `web_fetch(url, prompt)` | 웹 콘텐츠 가져와서 분석 |

### 메모리 도구
| 도구 | 기능 |
|------|------|
| `save_memory(fact)` | 사실을 메모리에 저장 |

### 도구 실행 승인
- **읽기 전용 도구**: 확인 없이 바로 실행
- **파일 수정 / 쉘 명령**: 실행 전 사용자 확인 필요
- **YOLO 모드** (`--yolo` / `Ctrl+Y`): 모든 확인 건너뛰기

---

## 10. 설정 & 구성

### 설정 파일 위치 (우선순위 높음 → 낮음)
1. **시스템**: `/etc/gemini-cli/settings.json`
2. **사용자**: `~/.gemini/settings.json`
3. **프로젝트**: `<프로젝트>/.gemini/settings.json`

### 주요 settings.json 옵션
```json
{
  "theme": "default",
  "model": { "name": "gemini-2.5-pro" },
  "modelThinking": "off",
  "autoAccept": true,
  "sandbox": true,
  "vimMode": false,
  "checkpointing": true,
  "excludeTools": [],
  "chatCompression": {
    "contextPercentageThreshold": 0.7
  },
  "mcpServers": {}
}
```

### GEMINI.md (프로젝트 컨텍스트 파일)
- **글로벌**: `~/.gemini/GEMINI.md` - 모든 프로젝트에 적용
- **프로젝트**: `<프로젝트>/.gemini/GEMINI.md` 또는 `<프로젝트>/GEMINI.md`
- **하위 디렉토리**: 프로젝트 루트까지 계층적 탐색
- `@file.md` 구문으로 다른 마크다운 파일 import 가능
- `/init`으로 자동 생성

### .geminiignore
`.gitignore`와 유사하게 Gemini CLI가 읽지 않을 파일/디렉토리 지정

### .env 파일
- `~/.gemini/.env` - 글로벌 환경 변수
- `./.gemini/.env` - 프로젝트별 환경 변수

---

## 11. 커스텀 슬래시 명령

커스텀 명령은 **TOML 파일**로 정의합니다.

### 파일 위치
- **글로벌**: `~/.gemini/commands/`
- **프로젝트**: `<프로젝트>/.gemini/commands/`

### 이름 규칙
- `test.toml` → `/test`
- `git/commit.toml` → `/git:commit`

### TOML 형식 예시
```toml
# ~/.gemini/commands/review.toml
prompt = """
다음 코드를 리뷰해주세요:
- 보안 취약점
- 성능 문제
- 베스트 프랙티스 위반
{{args}}
"""
```

사용법: `/review @./src/main.ts`

`{{args}}` 자리표시자가 명령어 뒤의 모든 입력을 캡처합니다.

---

## 12. 확장(Extensions) 시스템

확장은 프롬프트, MCP 서버, 커스텀 명령을 하나로 패키징합니다.

### 위치
- `<작업공간>/.gemini/extensions/`
- `~/.gemini/extensions/`

### 구조
각 확장은 `gemini-extension.json`을 포함하는 디렉토리:
```json
{
  "name": "my-extension",
  "description": "내 커스텀 확장",
  "mcpServers": { },
  "tools": { },
  "context": ["context.md"],
  "settings": [
    {
      "name": "API Token",
      "envVar": "MY_API_TOKEN",
      "sensitive": true
    }
  ]
}
```

---

## 13. MCP 서버 연동

### settings.json에서 설정
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "$GITHUB_TOKEN" },
      "timeout": 15000
    },
    "remote-server": {
      "url": "https://example.com/sse"
    }
  }
}
```

### 전송 방식
| 키 | 전송 방식 |
|----|-----------|
| `command` + `args` | 로컬 프로세스 (Stdio) |
| `url` | Server-Sent Events (SSE) |
| `httpUrl` | HTTP 스트리밍 |

### 주요 기능
- OAuth 2.0 인증 지원
- 도구 화이트리스트/블랙리스트 (`includeTools` / `excludeTools`)
- MCP 프롬프트가 슬래시 명령으로 자동 등록

---

## 14. 멀티모달 기능

`@` 구문으로 다양한 형식의 파일을 AI에 전달:

```bash
# 이미지 분석
@./screenshot.png 이 UI의 문제점을 찾아줘

# PDF 분석
@./document.pdf 이 문서를 요약해

# 디렉토리 전체 분석
@./src/ 이 코드 구조를 설명해
```

- `Ctrl+V`로 클립보드의 이미지를 바로 붙여넣기 가능
- 이미지, PDF, 오디오, 비디오 파일 지원

---

## 15. 실전 활용 팁

### 자주 쓰는 워크플로우

```bash
# 코드베이스 이해
gemini -i "이 프로젝트 구조와 아키텍처 설명해"

# 버그 수정
gemini -i "이 에러를 추적하고 수정해: [에러 메시지]"

# 코드 리뷰
gemini -p "git diff를 보고 코드 리뷰해" < <(git diff)

# 테스트 작성
gemini -i "@./src/utils.ts 이 파일에 대한 단위 테스트 작성해"

# 문서화
gemini -p "@./src/ 이 프로젝트의 README를 작성해" > README.md
```

### 효율적 사용을 위한 팁
1. **`/init` 먼저 실행**: 프로젝트 시작 시 GEMINI.md 자동 생성
2. **`@` 적극 활용**: 파일/디렉토리를 직접 참조하여 정확한 컨텍스트 제공
3. **`/compress` 활용**: 대화가 길어지면 토큰 절약을 위해 압축
4. **`/stats`로 모니터링**: 토큰 사용량 확인
5. **`--checkpointing` 사용**: 파일 수정 전 자동 백업 생성
6. **`/chat save`**: 실험 전 대화 상태 저장, 실패 시 `/chat resume`으로 복구
7. **커스텀 명령 공유**: `.gemini/commands/`를 Git에 커밋하여 팀 전체 사용
8. **`excludeTools` 설정**: 위험한 도구 제한 (`"excludeTools": ["run_shell_command(rm)"]`)
9. **구체적인 프롬프트**: "개선해"보다 "에러 핸들링 추가해"가 효과적
10. **복잡한 작업은 단계별로**: 한 번에 하나씩 요청

### Gemini CLI vs Claude Code 비교

| 항목 | Gemini CLI | Claude Code |
|------|-----------|-------------|
| **개발사** | Google | Anthropic |
| **라이선스** | Apache 2.0 (오픈소스) | 상용 |
| **무료 사용** | O (일 1000건) | X (구독 필요) |
| **설치** | `npm install -g` | 전용 설치 스크립트 |
| **컨텍스트** | 1M 토큰 | 200K 토큰 |
| **커스텀 명령** | TOML 파일 | SKILL.md 파일 |
| **프로젝트 설정** | GEMINI.md | CLAUDE.md |
| **샌드박스** | Docker/Podman | 내장 |
| **자동 승인** | --yolo | --dangerously-skip-permissions |
| **대화 저장** | /chat save | /resume |
