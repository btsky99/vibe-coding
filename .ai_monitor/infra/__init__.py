"""
FILE: infra/__init__.py
DESCRIPTION: 인프라/라이프사이클 모듈 패키지 초기화 파일.
             server.py에서 분리된 런타임 보조 모듈(라이프사이클, 파일감시,
             메모리 워처, 도구설치, 런타임 유틸 등)을 묶습니다.
             도메인 라우트는 api/ 패키지, 데이터 계층은 src/ 패키지를 사용합니다.

REVISION HISTORY:
- 2026-04-20 Claude: server.py 분할 — infra/ 패키지 신설 (Task 0)
"""
