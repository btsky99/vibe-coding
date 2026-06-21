# Vibe Coding

AI 멀티 에이전트 하이브 마인드 대시보드. 여러 AI 에이전트를 하나의 터미널 UI에서 동시 관리합니다.

> **에이전트 지원 현황**: Claude (완전 통합) / Antigravity(agy, 구 Gemini — CLI 자동 실행 통합) / Codex (실험적)

## 설치

[GitHub Releases](https://github.com/btsky99/vibe-coding/releases)에서 최신 설치파일을 다운로드하세요:

- **`vibe-coding-setup-X.Y.Z.exe`** — 올인원 설치버전 (권장)
- **`vibe-coding-update-X.Y.Z.exe`** — GUI 모드 (수동 업데이트)

### 전제조건

- Windows 10/11
- Node.js 18+ (터미널 기능)
- PostgreSQL 15+ (데이터 저장, 설치버전에 포함)

## 실행

설치 후 바탕화면의 **바이브 코딩** 바로가기를 클릭하세요.

## 업데이트

실행 시 자동으로 최신 버전을 확인합니다. 새 버전이 있으면 자동 다운로드 + 교체됩니다.

## 주요 기능

- **멀티 터미널**: 최대 6개 AI 에이전트 동시 실행 (Claude 완전 지원, Gemini/Codex 실험적)
- **채팅 모드**: 터미널 실행 중 채팅 UI로 전환 가능
- **하이브 마인드**: 에이전트 간 공유 메모리, 태스크 분배, 크로스 검증
- **지식 그래프**: PostgreSQL 기반 AI 사고 과정 시각화
- **자동 업데이트**: 실행 시 GitHub에서 최신 EXE 자동 체크

## 개발 모드

```bash
git clone https://github.com/btsky99/vibe-coding.git
cd vibe-coding
pip install -e .
vibe-coding
```

## Playwright CLI

권장 방식: 앱에서 프로젝트 폴더를 먼저 선택한 뒤 `AI 도구 -> Playwright 설치 (현재 프로젝트)`를 사용하세요.
수동 설치가 필요할 때만 아래 스크립트를 직접 실행하면 됩니다.

```bash
python scripts/install_playwright_cli.py
python -m playwright --version
```

브라우저 다운로드만 나중에 하고 싶으면:

```bash
python scripts/install_playwright_cli.py --skip-browser-install
python -m playwright install chromium
```

다른 PC에서도 이 프로젝트만 있으면 같은 방식으로 설치할 수 있습니다.

```bash
git clone https://github.com/btsky99/vibe-coding.git
cd vibe-coding
python scripts/install_playwright_cli.py
```

프로젝트 전체를 설치할 필요는 없고, Python과 인터넷 연결만 있으면 됩니다. 브라우저 바이너리는 PC마다 다시 설치해야 하므로, 복사본을 옮기기보다 이 스크립트를 다시 실행하는 방식이 안전합니다.

## 라이선스

MIT
