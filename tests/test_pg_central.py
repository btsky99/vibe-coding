"""
FILE: tests/test_pg_central.py
DESCRIPTION: 중앙 PG 커넥션 모듈 회귀 테스트 — 미설정/오설정에서 예외 없이 None인지,
             실패 쿨다운이 반복 접속을 막는지 검증한다.

REVISION HISTORY:
- 2026-08-08 Claude: 신규 (아픽스 중앙 대화 PG Task 4).
"""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from src import pg_central as pc


def _write(cfg_path: Path, payload: dict) -> Path:
    cfg_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return cfg_path


@pytest.fixture
def cfg(tmp_path):
    pc.reset_state()
    yield tmp_path / "config.json"
    pc.reset_state()


def test_missing_config_file_is_disabled(cfg):
    assert pc.get_central_config(cfg) is None
    assert pc.is_central_enabled(cfg) is False
    assert pc.get_central_conn(cfg) is None


def test_config_without_central_db_is_disabled(cfg):
    _write(cfg, {"last_path": "D:/vibe-coding"})
    assert pc.get_central_config(cfg) is None
    assert pc.get_central_conn(cfg) is None


@pytest.mark.parametrize("central", [
    {"host": "127.0.0.1", "port": 5433, "user": "hive", "password": "pw"},   # dbname 누락
    {"host": "", "port": 5433, "user": "hive", "password": "pw", "dbname": "k"},
    {"host": "127.0.0.1", "port": "포트아님", "user": "hive", "password": "pw", "dbname": "k"},
    "이건 dict가 아니다",
])
def test_incomplete_config_is_treated_as_unset(cfg, central):
    """[불변식] 하나라도 비면 '미설정'. 반쯤 채운 설정으로 연결을 시도하면
    사용자는 '왜 안 되는지' 대신 알 수 없는 psycopg2 에러를 본다."""
    _write(cfg, {"central_db": central})
    assert pc.get_central_config(cfg) is None
    assert pc.get_central_conn(cfg) is None


def test_unreachable_server_returns_none_without_raising(cfg):
    """서버가 죽어 있어도 예외가 새면 안 된다 — 이게 '서버 없어도 앱은 멀쩡하다'의 근거다."""
    _write(cfg, {"central_db": {
        "host": "127.0.0.1", "port": 1,      # 아무도 듣지 않는 포트
        "user": "hive", "password": "pw", "dbname": "hive_knowledge",
    }})
    assert pc.is_central_enabled(cfg) is True      # 설정은 있다
    assert pc.get_central_conn(cfg) is None        # 하지만 연결은 없다


def test_failure_cooldown_skips_repeated_connect(cfg, monkeypatch):
    """[회귀] 쿨다운이 없으면 API 호출마다 connect_timeout(5초)을 물어 UI가 멈춘다."""
    _write(cfg, {"central_db": {
        "host": "127.0.0.1", "port": 1,
        "user": "hive", "password": "pw", "dbname": "hive_knowledge",
    }})
    assert pc.get_central_conn(cfg) is None

    calls = {"n": 0}
    import psycopg2

    def _boom(*a, **kw):
        calls["n"] += 1
        raise psycopg2.OperationalError("연결되면 안 된다")

    monkeypatch.setattr(psycopg2, "connect", _boom)
    assert pc.get_central_conn(cfg) is None
    assert calls["n"] == 0, "쿨다운 중인데 재접속을 시도했다"


def test_port_is_normalized_to_int(cfg):
    _write(cfg, {"central_db": {
        "host": "127.0.0.1", "port": "5433",
        "user": "hive", "password": "pw", "dbname": "hive_knowledge",
    }})
    assert pc.get_central_config(cfg)["port"] == 5433


def test_str_path_is_accepted(cfg):
    """[🔴 회귀] str 경로가 '설정 없음'으로 둔갑하지 않는다.

    _read_config가 모든 예외를 {}로 삼키므로, str을 넘겼을 때 나던
    AttributeError가 그대로 미설정으로 보였다. 노드 온보딩 진단이 이 함정에
    걸려 "config를 썼는데 앱이 못 읽는다"로 오진했다(Task 32).
    """
    payload = {"central_db": {
        "host": "127.0.0.1", "port": 5433,
        "user": "hive", "password": "pw", "dbname": "hive_knowledge",
    }}
    _write(cfg, payload)

    assert pc.get_central_config(str(cfg)) is not None
    assert pc.get_central_config(cfg) is not None
    # 진짜 없는 파일은 여전히 None이어야 한다 — 관대해진 것이 아니라 타입만 정규화했다.
    assert pc.get_central_config(str(cfg.parent / "nope.json")) is None


def test_schema_ddl_is_not_run_without_connection(cfg):
    """[🔴 핵심] 연결이 성립하기 전에는 DDL이 절대 실행되지 않는다."""
    _write(cfg, {"central_db": {
        "host": "127.0.0.1", "port": 1,
        "user": "hive", "password": "pw", "dbname": "hive_knowledge",
    }})
    pc.get_central_conn(cfg)
    assert pc._schema_ready is False
