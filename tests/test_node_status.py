"""
FILE: tests/test_node_status.py
DESCRIPTION: 노드 상태 판정(생존/접속 분리) + 원격 명령 조립 규약의 회귀 테스트.

             [WHY 원격 명령 '문자열'을 테스트하는가] 이 모듈의 사고는 전부 셸 인용
             계층에서 났고, 증상은 언제나 '조용히 빈 결과'였다(ss·psql은 정상 동작).
             값이 아니라 명령 조립 규칙 자체를 못으로 박아야 재발이 잡힌다.

REVISION HISTORY:
- 2026-08-09 Claude: 최초 작성 — 마커 '#' 주석 사고, 종료코드 오판 사고, SQL 따옴표 사고.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / '.ai_monitor'))

from infra import node_status as ns  # noqa: E402


def _probe(**kw) -> dict:
    base = {'available': True, 'error': '', 'tunnel_ports': set(),
            'heartbeats': {}, 'heartbeats_by_port': {},
            'heartbeat_available': True, 'alias': 'apix'}
    base.update(kw)
    return base


def _host(**kw) -> dict:
    base = {'alias': 'cipher', 'aliases': ['cipher'], 'hostName': 'localhost',
            'user': 'com', 'port': 22001, 'proxyJump': 'vibe-vps'}
    base.update(kw)
    return base


# ── 원격 명령 조립 규약 (사고 3건 고정) ──────────────────────────────────────

def test_markers_do_not_start_with_hash():
    """[🔴 사고] '#'로 시작하는 마커는 원격 셸이 주석으로 먹어 출력이 통째로 빈다."""
    for mark in (ns._MARK_TUNNEL, ns._MARK_HB):
        assert not mark.lstrip().startswith('#'), f'{mark} — 원격 셸이 주석 처리한다'
        assert f"echo '{mark}'" in ns._REMOTE_CMD, f'{mark} 가 따옴표 없이 들어갔다'


def test_remote_cmd_ends_with_true():
    """[🔴 사고] 마지막 psql 실패의 종료코드가 ssh 반환값이 되어 '접속 실패'로 오판했다."""
    assert ns._REMOTE_CMD.rstrip().endswith('true'), '원격 명령이 0으로 끝나지 않는다'


def test_sql_is_passed_as_base64_not_inline():
    """[🔴 사고] SQL 안의 작은따옴표가 su -c '...' 를 끊었다 → base64 로만 넘긴다."""
    assert "payload->>'" not in ns._REMOTE_CMD, 'SQL 따옴표가 명령줄에 그대로 들어갔다'
    assert ns._HB_SQL_B64 in ns._REMOTE_CMD
    assert base64.b64decode(ns._HB_SQL_B64).decode('utf-8') == ns._HB_SQL


def test_no_password_in_remote_cmd():
    """[보안] 관제 DB 접속은 peer 인증 — 비밀번호/DSN 이 명령줄에 등장하면 안 된다."""
    low = ns._REMOTE_CMD.lower()
    for banned in ('password', 'pgpassword', 'postgresql://', 'apix.env'):
        assert banned not in low, f'원격 명령에 {banned} 유입'


# ── 생존/접속 분리 ───────────────────────────────────────────────────────────

def test_alive_and_reachable_are_independent():
    """[🔴 불변식] 둘을 합치지 않는다 — 조치가 정반대라 구분이 되어야 한다."""
    # 살아있는데 터널만 끊김 → 터널 재기동이 답
    p = _probe(tunnel_ports=set(), heartbeats_by_port={22001: 30})
    assert ns.is_alive(p, _host()) is True
    assert ns.is_reachable(p, _host()) is False

    # 터널만 살고 앱이 죽음 → 앱 재시작이 답
    p = _probe(tunnel_ports={22001}, heartbeats_by_port={22001: 99999})
    assert ns.is_alive(p, _host()) is False
    assert ns.is_reachable(p, _host()) is True


def test_unknown_is_none_not_false():
    """판정 불가는 None이다. False로 만들면 멀쩡한 노드가 '죽음'으로 표시된다."""
    # 서버에 못 물어봄
    p = _probe(available=False, heartbeat_available=False)
    assert ns.is_alive(p, _host()) is None
    assert ns.is_reachable(p, _host()) is None

    # ProxyJump 없는 항목(서버 자신 등)은 역터널 개념이 없다
    p = _probe(tunnel_ports={22001})
    assert ns.is_reachable(p, _host(port=0, proxyJump='')) is None

    # 관제 DB만 못 읽음 → 생존은 모르지만 터널은 유효
    p = _probe(tunnel_ports={22001}, heartbeat_available=False)
    assert ns.is_alive(p, _host()) is None
    assert ns.is_reachable(p, _host()) is True


def test_stale_threshold():
    assert ns.is_alive(_probe(heartbeats_by_port={22001: ns.STALE_AFTER_SEC}), _host()) is True
    assert ns.is_alive(_probe(heartbeats_by_port={22001: ns.STALE_AFTER_SEC + 1}), _host()) is False


# ── 매칭 우선순위 ────────────────────────────────────────────────────────────

def test_tunnel_port_wins_over_name():
    """[불변식] 포트가 있으면 이름을 보지 않는다 — 이름은 중복될 수 있어 오탐을 만든다."""
    p = _probe(heartbeats_by_port={22001: 10}, heartbeats={'cipher': 99999})
    assert ns.heartbeat_age(p, _host()) == 10


def test_name_fallback_when_no_port_match():
    """포트를 못 실은 옛 노드는 이름 계열로라도 붙는다(node_id 접두사 제거 포함)."""
    p = _probe(heartbeats={'cipher': 42})
    assert ns.heartbeat_age(p, _host()) == 42

    p = _probe(heartbeats={'yjscom': 7})
    assert ns.heartbeat_age(p, _host(alias='yjscom', aliases=['yjscom'], port=0,
                                     proxyJump='')) == 7


def test_no_match_is_none():
    p = _probe(heartbeats={'someone-else': 5})
    assert ns.heartbeat_age(p, _host()) is None
