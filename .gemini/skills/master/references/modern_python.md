# 🐍 Modern Python Development Standards

1. **패키지 관리**: `uv` 또는 `poetry` 사용 권장. `requirements.txt` 최신화 유지.
2. **코드 품질**: `ruff`를 통한 린팅 및 포맷팅 자동화. 
3. **타입 힌팅**: 모든 함수에 `Type Hints` 명시 (Pydantic 적극 활용).
4. **테스트**: `pytest`를 기반으로 한 단위 테스트 필수 작성.
5. **비동기 처리**: `asyncio` 활용 시 이벤트 루프 블로킹 주의 (특히 GUI 연동 시).
