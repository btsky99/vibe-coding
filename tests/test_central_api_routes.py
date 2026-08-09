"""
FILE: tests/test_central_api_routes.py
DESCRIPTION: 중앙 대화 HTTP 라우트 배선 회귀 테스트 — 구현만 되고 안 붙는 사고 방지 + 원격 실행 금지선 고정.

             [WHY 배선을 테스트하는가] Task 26에서 send/ack를 구현하고 GET 3종만
             등록해, 발신 경로가 통째로 죽은 채 '구현 완료'로 보였다. 함수 존재만
             확인하는 테스트로는 안 잡힌다 — 라우트 표에 있는지를 직접 본다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — POST 미배선 사고 + 원격 실행 라우트 유입 방지.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from api import central_api  # noqa: E402

SERVER_PY = (BASE / '.ai_monitor' / 'server.py').read_text(encoding='utf-8')

GET_PATHS = ['/api/central/status', '/api/central/messages', '/api/central/poll']
POST_PATHS = ['/api/central/send', '/api/central/ack']


@pytest.mark.parametrize('path', GET_PATHS + POST_PATHS)
def test_route_is_registered_in_server(path):
    """[불변식] 5종 전부 server.py 라우트 표에 등록돼 있어야 한다."""
    assert f"'{path}'" in SERVER_PY, f'{path} 가 server.py 라우트 표에 없음 — 구현해도 호출 불가'


def test_post_routes_are_in_post_table_not_get():
    """send/ack는 본문을 읽으므로 GET 표에 들어가면 항상 빈 본문으로 동작한다."""
    get_table = SERVER_PY.split('GET_ROUTES = {', 1)[1].split('}', 1)[0]
    post_table = SERVER_PY.split('POST_ROUTES = {', 1)[1]
    for path in POST_PATHS:
        assert f"'{path}'" not in get_table, f'{path} 가 GET 표에 잘못 등록됨'
        assert f"'{path}'" in post_table, f'{path} 가 POST 표에 없음'


@pytest.mark.parametrize('name', ['status', 'messages', 'poll', 'send', 'ack'])
def test_handler_exists(name):
    assert callable(getattr(central_api, name, None)), f'central_api.{name} 없음'


def test_no_remote_execution_route():
    """[🔴 설계 고정] 중앙 DB는 여러 PC의 공용 접점 — 실행 라우트 하나가 전 노드 RCE가 된다.

    실행이 필요하면 LAN 브리지의 3중 게이트를 쓴다. 이 금지선은 코드로 지킨다.
    """
    banned = ('exec', 'run', 'command', 'shell', 'spawn', 'eval')
    央 = [ln for ln in SERVER_PY.splitlines() if '/api/central/' in ln]
    for line in 央:
        route = line.split('/api/central/', 1)[1].split("'", 1)[0].lower()
        assert not any(b in route for b in banned), f'중앙에 실행성 라우트 유입: {line.strip()}'

    for attr in dir(central_api):
        if attr.startswith('_'):
            continue
        assert not any(b == attr.lower() for b in banned), f'central_api에 실행성 핸들러: {attr}'
