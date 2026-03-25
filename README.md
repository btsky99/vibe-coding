# Vibe Coding

AI 멀티 에이전트 하이브 마인드 대시보드. Claude, Gemini, Codex 등 여러 AI 에이전트를 하나의 터미널 UI에서 동시 관리합니다.

## 설치

```bash
pip install git+https://github.com/btsky99/vibe-coding.git
```

> 캐시 문제 발생 시: `pip install --no-cache-dir git+https://github.com/btsky99/vibe-coding.git`

### 전제조건

- Python 3.11+
- Node.js 18+ (터미널 기능)
- PostgreSQL 15+ (데이터 저장)

## 실행

```bash
vibe-coding
```

## 바탕화면 바로가기

```bash
vibe-coding --create-shortcut
```

## 업데이트

실행 시 자동으로 최신 버전을 확인합니다. 수동 업데이트:

```bash
pip install --upgrade git+https://github.com/btsky99/vibe-coding.git
```

## 주요 기능

- **멀티 터미널**: 최대 6개 AI 에이전트 동시 실행 (Claude, Gemini, Codex)
- **채팅 모드**: 터미널 실행 중 채팅 UI로 전환 가능
- **하이브 마인드**: 에이전트 간 공유 메모리, 태스크 분배, 크로스 검증
- **지식 그래프**: PostgreSQL 기반 AI 사고 과정 시각화
- **자동 업데이트**: 실행 시 GitHub에서 최신 버전 자동 체크

## 개발 모드

```bash
git clone https://github.com/btsky99/vibe-coding.git
cd vibe-coding
pip install -e .
vibe-coding
```

## 라이선스

MIT
