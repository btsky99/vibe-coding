<!--
FILE: ai_monitor_plan.md
DESCRIPTION: 원스톱 설치 + 언인스톨 기능 구현 계획
REVISION HISTORY:
- 2026-03-26 Claude: 원스톱 설치(바탕화면 아이콘 자동) + 언인스톨 명령어 계획 수립
- 2026-03-25 Claude: pip install 배포 전환 계획 수립 (완료)
-->

# 🎯 원스톱 설치 + 언인스톨 기능 구현

**상태:** 승인 대기
**목표:** `pip install` 한 줄 + 첫 실행 시 바탕화면 아이콘 자동 생성. `--uninstall`로 깔끔 제거.

---

## 태스크 목록

[ ] Task 1: pyproject.toml에 pywin32 의존성 추가
    파일: pyproject.toml
    방법: dependencies에 `pywin32>=310; sys_platform == "win32"` 추가
    검증: pip install 시 pywin32 자동 설치

[ ] Task 2: create_shortcut.py에 remove_shortcut() 함수 추가
    파일: .ai_monitor/create_shortcut.py
    방법: 바탕화면 "바이브코딩.lnk" 삭제 함수
    검증: 함수 호출 시 바로가기 삭제

[ ] Task 3: server.py main()에 --install / --uninstall 명령어 추가
    파일: .ai_monitor/server.py
    방법:
      - `--install`: create_shortcut() + 완료 메시지
      - `--uninstall`: remove_shortcut() + pip uninstall 안내
      - 기존 `--create-shortcut` 호환 유지
    검증: 각 명령어 동작 확인
    의존성: Task 2 완료 후

[ ] Task 4: 첫 실행 시 바탕화면 바로가기 자동 생성
    파일: .ai_monitor/server.py
    방법: 서버 시작 시 "바이브코딩.lnk" 없으면 자동 create_shortcut()
    검증: 첫 실행 시 아이콘 자동 생성
    의존성: Task 1 완료 후

[ ] Task 5: README.md 원스톱 설치/언인스톨 문서화
    파일: README.md
    방법: 설치 원스톱 명령어 + 언인스톨 섹션 추가
    검증: README 확인
    의존성: 전체 완료 후
