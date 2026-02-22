# 📄 `megaphone.py` 파일 상세 문서

- **원본 파일 경로**: `scripts/megaphone.py`
- **파일 역할**: 하이브 마인드의 다중 터미널(에이전트) 간의 직접적인 **소통 및 명령어 전달(IPC)**을 담당하는 핵심 유틸리티 스크립트입니다.

## 🛠️ 주요 기능 (Key Features)

1. **에이전트 간 직접 통신 (Inter-Agent Communication)**
   - 1번 터미널에서 구동 중인 AI(기획자)가 2번 터미널에서 구동 중인 AI(개발자)에게 직접 작업 지시나 피드백을 보낼 때 사용됩니다.
   - 넥서스 뷰(대시보드) 서버(`server.py`)의 내부 API `/api/send-command`로 HTTP POST 요청을 보내어 통신을 매개합니다.

2. **자동 프롬프트 타이핑 및 실행**
   - 이 스크립트가 호출되면, 타겟 터미널(지정된 터미널 번호)의 PTY(명령 프롬프트)에 타자기로 직접 치는 것처럼 메시지가 입력되고 자동으로 엔터(`
`)가 쳐져서 실행(또는 전송)됩니다.

3. **CLI 옵션 지원 (Argument Parser)**
   - `--target`: 메시지를 전송받을 터미널 슬롯의 번호 (UI에 보이는 `Terminal 1`, `Terminal 2` 등의 숫자).
   - `--message`: 해당 터미널 프롬프트에 자동으로 쳐질 명령어 텍스트, 프롬프트 대화 내용 등.

## 📝 사용 예시 (Usage)

- 터미널 1의 제미나이가 터미널 2의 클로드에게 지시를 내리는 경우:
  ```bash
  python scripts/megaphone.py --target 2 --message "클로드, App.tsx에 버튼 하나 추가해줘."
  ```

- 특정 터미널(예: 3번)에서 빌드 스크립트를 강제로 실행시키는 경우:
  ```bash
  python scripts/megaphone.py --target 3 --message "npm run build"
  ```
