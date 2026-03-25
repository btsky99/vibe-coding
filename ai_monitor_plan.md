<!--
FILE: ai_monitor_plan.md
DESCRIPTION: pip install 배포 전환 — PyInstaller/Inno Setup → pip install git+ 방식
REVISION HISTORY:
- 2026-03-25 Claude: pip install 배포 전환 계획 수립
- 2026-03-24 Claude: 배포 범용화 계획 수립 (완료)
-->

# pip install 배포 전환

## 목표
`pip install git+https://github.com/btsky99/vibe-coding.git` 한 줄로 설치/업데이트.
실행 시 자동 업데이트 체크 (Claude Code 방식). 기존 EXE 빌드는 유지.

---

## 태스크 목록

### Phase 1: 패키지 구조

[x] Task 1: pyproject.toml 생성 — pip 패키지 정의
    파일: `pyproject.toml` (신규)
    방법: - [project] name="vibe-coding", dynamic=["version"]
          - [project.scripts] vibe-coding = "ai_monitor.server:main"
          - dependencies: requirements.txt에서 pyinstaller/PySide6 제외한 핵심 의존성
          - [tool.setuptools.package-data]: vibe-view/dist/**, pty-server/*.js, bin/*.ico
          - [tool.setuptools.dynamic] version = {attr = "ai_monitor._version.__version__"}
    검증: pyproject.toml 문법 유효

[x] Task 2: __init__.py + __main__.py 생성 — 패키지 초기화
    파일: `.ai_monitor/__init__.py` (신규), `.ai_monitor/__main__.py` (신규)
    방법: - __init__.py: `from ._version import __version__`
          - __main__.py: `from .server import main; main()`
    검증: 파일 존재 확인

[x] Task 3: server.py main() 함수 추출 — entry point 대응
    파일: `.ai_monitor/server.py`
    방법: - `if __name__ == '__main__':` 블록(line 4398~끝)을 `def main():` 함수로 감싸기
          - `if __name__ == '__main__': main()` 유지
          - 모듈 내 상대 임포트는 건드리지 않음 (기존 dev 모드 경로 그대로 동작)
    의존: Task 2 완료 후
    검증: `python .ai_monitor/server.py` 기존 방식 정상 동작

### Phase 2: 에셋 포함

[x] Task 4: .gitignore 수정 + vibe-view/dist 커밋
    파일: `.gitignore`
    방법: - `.ai_monitor/vibe-view/dist/` 라인을 `# .ai_monitor/vibe-view/dist/` 로 주석 처리
          - `dist/` 라인은 유지 (다른 프로젝트의 dist 제외)
          - `git add -f .ai_monitor/vibe-view/dist/`
    검증: `git status`에서 dist 파일 추적됨

### Phase 3: 자동 업데이트

[x] Task 5: updater.py — pip upgrade 모드 추가
    파일: `.ai_monitor/updater.py`
    방법: - `check_and_update_pip(data_dir)` 함수 신규 추가
          - GitHub API로 최신 태그 확인 (기존 _fetch_latest_release 재활용)
          - 새 버전: `subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "git+https://...@vX.Y.Z"])`
          - 결과를 update_ready.json에 기록: {"version": "3.7.121", "ready": True, "pip_mode": True}
          - EXE 모드(frozen) 기존 로직은 그대로 유지
    검증: pip 모드에서 업데이트 체크 로그 출력

[x] Task 6: server.py — pip 모드에서도 자동 업데이트 활성화
    파일: `.ai_monitor/server.py`
    방법: - main() 내 업데이트 루프: frozen 조건 제거, pip 모드면 check_and_update_pip 호출
          - 업데이트 완료 시 대시보드에 "재시작하면 적용" 알림
    의존: Task 5 완료 후
    검증: 개발 모드에서 업데이트 체크 로그 확인

### Phase 4: 바로가기 + 테스트

[x] Task 7: create_shortcut.py — pip entry point 대응
    파일: `.ai_monitor/create_shortcut.py`
    방법: - pip entry point 경로 탐색: `shutil.which('vibe-coding')`
          - 못 찾으면 fallback: `pythonw -m ai_monitor`
          - `--create-shortcut` CLI 인자 처리를 server.py main()에 추가
    의존: Task 3 완료 후
    검증: 바탕화면 바로가기 생성

[x] Task 8: 로컬 테스트 — pip install -e . 검증
    방법: - `pip install -e .` 실행
          - `vibe-coding` 명령 실행 → 서버 기동 확인
          - 기존 `python .ai_monitor/server.py` 방식도 정상 동작 확인
    의존: Task 1~7 전부 완료 후
    검증: 양쪽 모두 정상 동작
