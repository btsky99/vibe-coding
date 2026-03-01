"""
FILE: api/__init__.py
DESCRIPTION: API 모듈 패키지 초기화 파일.
             server.py에서 분리된 각 도메인별 API 핸들러 모듈을 묶습니다.
             각 모듈은 handle_get(handler, path, params, ...) 또는
             handle_post(handler, path, data, ...) 형태의 함수를 공개합니다.

REVISION HISTORY:
- 2026-03-01 Claude: server.py 리팩토링 — API 핸들러 모듈 분리 패키지 생성
"""
