# 📄 scripts/skill_manager.py 상세 문서

버전: v1.0.0 - [Gemini] 생성

## 💡 개요
`skill_manager.py`는 Gemini CLI 및 Claude 에이전트가 사용하는 스킬(Skills)을 통합적으로 관리하기 위한 스크립트입니다. MCP(Model Context Protocol)의 개념을 차용하여, 로컬에 설치된 스킬들을 조회하고 외부 저장소에서 새로운 스킬을 검색 및 설치하는 기능을 제공합니다.

## 🛠️ 주요 기능
1. **로컬 스킬 목록 조회 (`list`)**: `.gemini/skills/` 디렉토리를 스캔하여 설치된 스킬의 이름, 경로, 설명을 JSON 형태로 출력합니다.
2. **원격 스킬 검색 (`search`)**: 공식 갤러리나 GitHub 등 외부 저장소에서 새로운 스킬을 검색합니다. (현재는 시뮬레이션 데이터를 제공하며, 에이전트의 검색 도구와 연동 가능합니다.)
3. **스킬 설치 (`install`)**: Git 저장소 URL을 통해 새로운 스킬을 `.gemini/skills/` 폴더에 자동으로 내려받습니다.

## 📖 사용 방법

### CLI 명령어 예시

- **설치된 스킬 목록 보기**
  ```bash
  python scripts/skill_manager.py list
  ```

- **스킬 검색하기**
  ```bash
  python scripts/skill_manager.py search --query "python"
  ```

- **새로운 스킬 설치하기**
  ```bash
  python scripts/skill_manager.py install --name "expert-bot" --url "https://github.com/user/expert-bot"
  ```

## 🏗️ 아키텍처 연동
- **Gemini CLI**: `master` 스킬이 사용자의 "스킬 검색" 요청을 받으면 이 스크립트를 호출하여 결과를 보여줍니다.
- **Vibe-View**: 프론트엔드 대시보드의 'Skill Store' UI에서 API 형태로 이 스크립트를 실행하여 사용자에게 시각적인 관리 환경을 제공합니다.

## ⚠️ 주의 사항
- 스킬 설치 시 `git` 명령어가 시스템에 설치되어 있어야 합니다.
- 외부 URL에서 스킬을 다운로드할 때는 신뢰할 수 있는 소스인지 반드시 확인해야 합니다.
