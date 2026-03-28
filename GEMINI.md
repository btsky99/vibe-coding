# 📜 프로젝트 하이브 마인드 지침 (Project Constitution)

이 프로젝트는 **Gemini-1/2**와 **Claude-1/2**가 협업하는 **하이브 마인드(Hive Mind)** 체제로 운영됩니다. 모든 AI 에이전트는 이 파일의 지침을 최우선으로 준수해야 합니다.

## 🤖 기본 행동 원칙
프로젝트에 참여하는 모든 에이전트의 핵심 행동, 보고 양식 및 문서화 의무는 루트 폴더의 **`RULES.md`** 파일에 명시되어 있습니다.
**반드시 작업 시작 전 `RULES.md` 파일을 읽고, 그 안의 모든 규칙을 최우선으로 준수해야 합니다.**
- **격리된 작업 환경 강제 (Git Worktrees):** 새로운 기능 구현, 버그 수정 등 코드를 변경하는 작업은 반드시 메인 브랜치가 아닌, `using-git-worktrees` 스킬을 활성화하여 `.worktrees/` 디렉토리 하위에 생성된 독립된 워크트리에서 수행해야 합니다.

## 📡 에이전트 역할
- **Gemini**: 전체 설계, 워크플로우 조율, 데이터 및 ML 분석 담당.
- **Claude**: 정밀 프론트엔드(React/Tailwind) 구현 및 세부 로직 최적화 담당.

## 📂 핵심 참조 파일
- **작업 계획**: `ai_monitor_plan.md`
- **전문 지식**: `.gemini/skills/orchestrate/` 폴더 내 가이드 참고

## 💬 그룹 채팅 (MCP groupchat)
이 프로젝트에는 `groupchat` MCP 서버가 등록되어 있습니다.
다른 터미널의 에이전트(Claude, Codex)와 실시간 소통이 가능합니다.

**사용 방법:**
- `send_group_message` 도구로 메시지 전송
- `check_new_messages` 도구로 새 메시지 확인
- `read_group_messages` 도구로 최근 대화 조회

**자동 참여 규칙:**
- 작업 시작 시 `check_new_messages`로 그룹챗을 확인하세요
- 다른 에이전트의 질문이나 요청이 있으면 응답하세요
- 작업 완료 시 결과를 `send_group_message`로 공유하세요