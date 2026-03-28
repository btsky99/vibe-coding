# LLM Group Chat CLI - 설계 문서

## 프로젝트 개요
서로 다른 터미널에서 실행 중인 LLM(Claude Code, Gemini CLI, Codex CLI 등)이
CLI 기반으로 실시간 그룹 채팅하는 도구.

## 배경 & 트렌드
- MCP는 에이전트↔도구(수직) 연결용. 에이전트↔에이전트(수평) 통신에는 부적합
- Google A2A 프로토콜이 에이전트 간 통신용으로 나왔지만, 복잡함
- Playwright도 MCP → CLI로 전환 (토큰 4배 절약)
- 2026년 CLI가 대세: Claude Code, Gemini CLI, Codex CLI, Aider 등 120+개 도구

## 핵심 컨셉
```
터미널1: Claude Code  ──┐
터미널2: Gemini CLI    ──┼──→  WebSocket 서버  ←──→  실시간 그룹챗
터미널3: Codex CLI     ──┘
```

## 기술 스택
- **언어**: Python 3.10+
- **통신**: WebSocket (asyncio + websockets 라이브러리)
- **CLI**: Click
- **의존성**: websockets, click (최소 2개)

## 사용법
```bash
# 서버 시작
python -m llm_group_chat serve --port 8765

# 참여
python -m llm_group_chat join --name "claude" --port 8765

# 원샷 메시지
python -m llm_group_chat send --name "claude" --msg "분석 결과입니다"

# 파이프 모드 (LLM 연동)
python -m llm_group_chat pipe --name "claude"

# 로그 보기
python -m llm_group_chat log --tail 50
```

## 구현 순서
1. [x] protocol.py (메시지 포맷 정의 + 직렬화)
2. [x] server.py (WebSocket 서버 - 연결 관리 + 브로드캐스트)
3. [x] client.py (WebSocket 클라이언트 - 송수신 + 파이프 모드)
4. [x] cli.py (Click CLI - serve/join/send/log/pipe)
5. [x] __main__.py (python -m 지원)
6. [x] 통합 테스트 (2개 클라이언트 연결 + 메시지 교환)
7. [x] LLM 자동 연동 모드 (--auto-reply)

## 향후 확장 (v2)
- 멀티 룸 지원
- 메시지 암호화
- 파일 공유
- 웹 UI 대시보드
