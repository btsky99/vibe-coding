# 📄 `megaphone.py` 파일 상세 문서

> **버전: v2.1.0 - [Gemini] 업무 위임(Delegation) 및 하이브 로깅 기능 추가**
> **메인 문서:** [README.md](README.md)

- **원본 파일 경로**: `scripts/megaphone.py`
- **파일 역할**: 하이브 마인드의 다중 터미널(에이전트) 간의 직접적인 **소통 및 명령어 전달(IPC)**을 담당하는 핵심 유틸리티 스크립트입니다.

## 🛠️ 주요 기능 (Key Features)

1. **에이전트 간 직접 통신 (Inter-Agent Communication)**
   - 1번 터미널에서 구동 중인 AI(기획자)가 2번 터미널에서 구동 중인 AI(개발자)에게 직접 작업 지시나 피드백을 보낼 때 사용됩니다.
   - 넥서스 뷰(대시보드) 서버(`server.py`)의 내부 API `/api/send-command`로 HTTP POST 요청을 보내어 통신을 매개합니다.

2. **업무 위임 프로토콜 (Delegation) [NEW]**
   - **`--delegate` 옵션**: 다른 에이전트에게 업무를 넘길 때 사용합니다. 수신 측 터미널에 발신자 정보와 위임 문구가 포함된 특수 포맷팅 메시지를 전송하여 업무 맥락을 파악하기 쉽게 돕습니다.

3. **하이브 자동 로깅 (Hive Logging) [NEW]**
   - 메시지 전송 성공 시 `scripts/hive_bridge.py`를 자동으로 호출하여 전체 대시보드 로그에 협업 사실을 공표합니다.

4. **자동 프롬프트 타이핑 및 실행**
   - 이 스크립트가 호출되면, 타겟 터미널(지정된 터미널 번호)의 PTY(명령 프롬프트)에 타자기로 직접 치는 것처럼 메시지가 입력되고 자동으로 엔터(`\r\n`)가 쳐져서 실행(또는 전송)됩니다.

## 📝 사용 방법 (Usage)

터미널이나 스크립트에서 다음과 같이 호출할 수 있습니다.

- **기본 메시지 전송** (터미널 2번으로 /clear 명령어 전송)
  ```bash
  python scripts/megaphone.py --target 2 --message "/clear"
  ```

- **업무 위임 예시** (Gemini-1이 터미널 3번의 에이전트에게 스타일 수정 요청)
  ```bash
  python scripts/megaphone.py --target 3 --agent "Gemini-1" --message "index.css 파일의 버튼 색상을 네온 블루로 변경해줘" --delegate
  ```

## ⚙️ 주요 옵션 설명 (CLI Options)

- `--target`: 메시지를 수신할 터미널 번호 (UI에 보이는 `Terminal 1`, `Terminal 2` 등의 숫자).
- `--message`: 해당 터미널 프롬프트에 자동으로 쳐질 명령어 텍스트, 프롬프트 대화 내용 등.
- `--agent`: 발신 에이전트 이름 (기본값: Gemini-1)
- `--delegate`: 위임 모드 활성화 (안내 문구 포함 포맷팅 적용)
