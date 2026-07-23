# -*- coding: utf-8 -*-
"""
FILE: tests/test_telegram_hub.py
DESCRIPTION: 텔레그램 그룹방 허브화(ai_monitor_plan.md Task 1~4) 회귀 테스트.
             .env 저장 시 그룹ID 소실 / 4000자 초과 유실 / 민감 파일 전송이라는
             세 사고를 코드가 아니라 테스트로 고정한다.

             [WHY 이 파일이 필요한가] 세 결함 모두 **조용히** 실패했다 —
             예외도 로그도 없이 그룹 전송이 무동작하거나 내용이 사라졌다.
             조용한 실패는 수동 확인으로 재발을 못 잡으므로 회귀는 테스트로만 고정된다.

             [제약] 텔레그램 네트워크는 타지 않는다. app.bot을 가짜 객체로 갈아끼워
             전송 경로만 검증한다(토큰·인터넷 불필요 → CI에서도 그대로 돈다).
             Task 5(그룹 미러링 가독성)는 async 폴링 루프 내부 인라인 로직이라
             단위 테스트 대상이 아니다 — 순수 함수인 source_label만 여기서 고정한다.

REVISION HISTORY:
- 2026-07-24 Claude: 신규. 계획(Task 1~4)의 '검증' 항목이 미구현이던 것을 채움.
"""

import asyncio
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from api.telegram_api import rewrite_env_telegram_tokens  # noqa: E402
import telegram_helpers as th  # noqa: E402
from telegram_helpers import _split_message, is_sendable_path  # noqa: E402

telegram_agent_bot = pytest.importorskip(
    "telegram_agent_bot",
    reason="python-telegram-bot 미설치 환경에서는 전송 경로 테스트를 건너뛴다",
)


# ══════════════════════════════════════════════════════════════
# Task 1 — .env 저장 시 TELEGRAM_GROUP_CHAT_ID 보존
# ══════════════════════════════════════════════════════════════

_ENV_SAMPLE = (
    "DATABASE_URL=postgresql://localhost:5433/hive\n"
    "SOME_OTHER=1\n"
    "\n"
    "# Telegram Multi-Bot Bridge\n"
    "TELEGRAM_BOT_T1=111:aaa\n"
    "TELEGRAM_BOT_T2=222:bbb\n"
    "TELEGRAM_PC_LABEL=데스크탑\n"
    "TELEGRAM_GROUP_CHAT_ID=-1001234567890\n"
)


def _env_map(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_그룹ID가_토큰만_저장할_때_살아남는다():
    """[과거사고] 제거 조건이 startswith("TELEGRAM_")이라 대시보드에서 저장하는
    순간 GROUP_CHAT_ID가 소멸 → send_to_group이 가드에 걸려 전부 무동작했다."""
    out = rewrite_env_telegram_tokens(_ENV_SAMPLE, {"T1": "999:zzz"})
    m = _env_map(out)
    assert m["TELEGRAM_GROUP_CHAT_ID"] == "-1001234567890"
    assert m["TELEGRAM_PC_LABEL"] == "데스크탑"
    assert m["TELEGRAM_BOT_T1"] == "999:zzz"


def test_텔레그램과_무관한_라인은_보존된다():
    m = _env_map(rewrite_env_telegram_tokens(_ENV_SAMPLE, {}))
    assert m["DATABASE_URL"] == "postgresql://localhost:5433/hive"
    assert m["SOME_OTHER"] == "1"


def test_마스킹된_토큰은_기존값을_덮어쓰지_않는다():
    """UI는 마스킹 값("111:aaa..." 형태)을 그대로 되돌려보낸다 — 그대로 쓰면 토큰 파괴."""
    m = _env_map(rewrite_env_telegram_tokens(_ENV_SAMPLE, {"T1": "111:aaa...", "T2": ""}))
    assert m["TELEGRAM_BOT_T1"] == "111:aaa"
    assert m["TELEGRAM_BOT_T2"] == ""


def test_저장은_멱등이다():
    """[불변식 2] 마커 주석·말미 공백을 걷어내지 않으면 저장할 때마다 헤더가 누적된다."""
    once = rewrite_env_telegram_tokens(_ENV_SAMPLE, {"T1": "111:aaa"})
    twice = rewrite_env_telegram_tokens(once, {"T1": "111:aaa"})
    assert once == twice
    assert once.count("# Telegram Multi-Bot Bridge") == 1


def test_빈문자열은_의도적_비움이라_적용된다():
    """None(=이번 요청이 안 건드림)과 ""(=비움)의 구분이 무너지면 사고가 재발한다."""
    kept = _env_map(rewrite_env_telegram_tokens(_ENV_SAMPLE, {}, group_chat_id=None))
    cleared = _env_map(rewrite_env_telegram_tokens(_ENV_SAMPLE, {}, group_chat_id=""))
    assert kept["TELEGRAM_GROUP_CHAT_ID"] == "-1001234567890"
    assert cleared["TELEGRAM_GROUP_CHAT_ID"] == ""


# ══════════════════════════════════════════════════════════════
# Task 2 — _split_message (유실 0)
# ══════════════════════════════════════════════════════════════

def test_짧은_텍스트는_한_조각():
    assert _split_message("짧다", limit=100) == ["짧다"]


def test_경계값은_분할되지_않는다():
    text = "a" * 100
    assert _split_message(text, limit=100) == [text]
    assert len(_split_message("a" * 101, limit=100)) == 2


def test_여러_줄_분할은_원문을_완전복원한다():
    """[불변식] 유실 0 — 줄 경계 분할이면 다시 이어붙여 원문과 정확히 같아야 한다."""
    text = "\n".join(f"라인{i:03d} " + "가" * 40 for i in range(60))
    parts = _split_message(text, limit=300)
    assert len(parts) > 1
    assert "\n".join(parts) == text


def test_줄바꿈_없는_초장문도_유실되지_않는다():
    text = "x" * 2500
    parts = _split_message(text, limit=400)
    assert len(parts) == 7
    assert "".join(parts) == text


def test_코드펜스가_조각마다_짝을_이룬다():
    """펜스가 열린 채 끝나면 텔레그램 Markdown 파싱이 깨져 통째로 plain 폴백된다."""
    body = "\n".join(f"print({i})" for i in range(120))
    text = f"결과입니다\n```\n{body}\n```\n끝"
    parts = _split_message(text, limit=300)
    assert len(parts) > 1
    for p in parts:
        assert p.count("```") % 2 == 0, f"펜스 불균형: {p[:60]!r}"
    # 펜스 보정으로 ``` 가 추가될 뿐, 원문 라인은 하나도 사라지지 않는다
    joined = "\n".join(parts)
    for line in text.splitlines():
        assert line in joined


def test_max_parts는_잘라내지_않는다():
    """max_parts는 호출부의 '파일로 전환' 판단 기준일 뿐 — 여기서 버리면 유실 재발."""
    text = "\n".join("y" * 80 for _ in range(200))
    parts = _split_message(text, limit=300, max_parts=2)
    assert len(parts) > 2
    assert "\n".join(parts) == text


# ══════════════════════════════════════════════════════════════
# Task 3 — is_sendable_path 보안 가드
# ══════════════════════════════════════════════════════════════

def test_프로젝트_내_일반파일은_허용():
    ok, why = is_sendable_path(_PROJECT_ROOT / "README.md", _PROJECT_ROOT)
    assert ok, why


@pytest.mark.parametrize("name", [
    ".env", ".env.local", "id_rsa", "server.key", "cert.pem",
    "credentials.json", "my_token.txt", "telegram_bridge.log", "dump.sql",
])
def test_민감_파일명은_거부(tmp_path, name):
    """[🔴 최우선] .env에는 봇 토큰 자체가 들어있다 — 유출되면 봇이 통째로 탈취된다."""
    f = tmp_path / name
    f.write_text("secret", encoding="utf-8")
    ok, why = is_sendable_path(f, tmp_path)
    assert not ok
    assert "민감" in why


def test_상위경로_탈출은_거부(tmp_path):
    """문자열 검사만으로는 `..`/심볼릭 탈출을 못 막는다 — resolve 후 판정이 불변식."""
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    ok, why = is_sendable_path(root / ".." / "outside.txt", root)
    assert not ok
    assert "프로젝트 폴더 밖" in why


def test_민감_디렉토리_포함은_거부(tmp_path):
    d = tmp_path / ".ssh"
    d.mkdir()
    f = d / "notes.txt"
    f.write_text("x", encoding="utf-8")
    ok, why = is_sendable_path(f, tmp_path)
    assert not ok
    assert "민감 디렉토리" in why


def test_초대용량은_거부(tmp_path, monkeypatch):
    monkeypatch.setattr(th, "MAX_DOC_BYTES", 10)
    f = tmp_path / "big.txt"
    f.write_text("x" * 100, encoding="utf-8")
    ok, why = is_sendable_path(f, tmp_path)
    assert not ok
    assert "너무 큼" in why


def test_빈파일과_없는파일은_거부(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.touch()
    assert is_sendable_path(empty, tmp_path)[0] is False
    assert is_sendable_path(tmp_path / "nope.txt", tmp_path)[0] is False


def test_디렉토리는_거부(tmp_path):
    assert is_sendable_path(tmp_path, tmp_path)[0] is False


# ══════════════════════════════════════════════════════════════
# Task 4 — _safe_send 3경로 (내용이 조용히 사라지지 않는다)
# ══════════════════════════════════════════════════════════════

class _FakeBot:
    """텔레그램 Bot 대역. 네트워크 없이 전송 시도를 기록한다."""

    def __init__(self):
        self.messages: list = []      # (chat_id, text, parse_mode)
        self.documents: list = []     # (chat_id, filename, 내용, caption)
        self.fail_markdown = False    # Markdown 파싱 실패 재현
        self.fail_document = False    # 문서 업로드 실패 재현

    async def send_message(self, chat_id, text, parse_mode=None):
        if parse_mode is not None and self.fail_markdown:
            raise RuntimeError("Can't parse entities")
        self.messages.append((chat_id, text, parse_mode))

    async def send_document(self, chat_id, document, filename=None,
                            caption=None, parse_mode=None):
        if self.fail_document:
            raise RuntimeError("upload failed")
        self.documents.append(
            (chat_id, filename, document.read().decode("utf-8"), caption)
        )


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


@pytest.fixture
def bot(monkeypatch):
    """AgentBot을 __init__ 없이 만든다 — 실제 __init__은 봇 토큰으로 Application을
    빌드하므로 단위 테스트에서 쓸 수 없다. 전송 경로에 필요한 속성만 채운다."""
    b = telegram_agent_bot.AgentBot.__new__(telegram_agent_bot.AgentBot)
    b.label = "T1(claude)"
    b.emoji = "\U0001f916"
    b.app = _FakeApp()
    # 조각 간 0.3초 슬립은 레이트 회피용 — 테스트에선 실시간을 기다릴 이유가 없다
    monkeypatch.setattr(telegram_agent_bot.asyncio, "sleep", _noop_sleep)
    return b


async def _noop_sleep(_seconds):
    return None


def test_경로1_짧은_메시지는_1건(bot):
    asyncio.run(bot._safe_send(1, "안녕"))
    assert len(bot.app.bot.messages) == 1
    assert bot.app.bot.messages[0][1] == "안녕"
    assert bot.app.bot.documents == []


def test_경로2_분할_전송은_내용을_보존한다(bot):
    text = "\n".join(f"줄{i:04d} " + "나" * 60 for i in range(100))  # ≈7천자 → 2~4조각
    asyncio.run(bot._safe_send(1, text))
    sent = [m[1] for m in bot.app.bot.messages]
    assert 1 < len(sent) <= telegram_agent_bot._MSG_MAX_PARTS
    assert "\n".join(sent) == text
    assert bot.app.bot.documents == []


def test_경로3_초장문은_파일로_전문이_간다(bot):
    """조각 > MAX_PARTS면 알림 폭탄 대신 .txt 첨부 — 단, 전문이 그대로 들어가야 한다."""
    text = "\n".join(f"줄{i:05d} " + "다" * 60 for i in range(600))
    asyncio.run(bot._safe_send(1, text))
    assert len(bot.app.bot.documents) == 1
    _, filename, content, caption = bot.app.bot.documents[0]
    assert filename.endswith(".txt")
    assert content == text          # [불변식] 유실 0
    assert caption                  # 미리보기 캡션 동반


def test_파일전송이_실패해도_분할로_폴백된다(bot):
    """파일 경로가 막혔다고 내용이 사라지면 안 된다 — 사고의 본질은 '조용한 소실'."""
    bot.app.bot.fail_document = True
    text = "\n".join(f"줄{i:05d} " + "라" * 60 for i in range(600))
    asyncio.run(bot._safe_send(1, text))
    assert bot.app.bot.documents == []
    sent = [m[1] for m in bot.app.bot.messages]
    assert "\n".join(sent) == text


def test_마크다운_실패시_plain으로_폴백(bot):
    bot.app.bot.fail_markdown = True
    asyncio.run(bot._safe_send(1, "*깨진 마크다운"))
    assert len(bot.app.bot.messages) == 1
    assert bot.app.bot.messages[0][2] is None   # parse_mode 없이 재시도됨


def test_분할_후에도_마크다운_폴백이_동작한다(bot):
    bot.app.bot.fail_markdown = True
    text = "\n".join(f"줄{i:04d} " + "마" * 60 for i in range(100))
    asyncio.run(bot._safe_send(1, text))
    sent = [m[1] for m in bot.app.bot.messages]
    assert len(sent) > 1
    assert all(m[2] is None for m in bot.app.bot.messages)
    assert "\n".join(sent) == text


def test_문서전송은_가드에_막히면_사유를_회신한다(bot, tmp_path):
    """거부는 조용히 하지 않는다 — 사용자가 왜 안 왔는지 알 수 있어야 한다."""
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    ok = asyncio.run(bot._safe_send_document(1, outside))
    assert ok is False
    assert bot.app.bot.documents == []
    assert "⛔" in bot.app.bot.messages[0][1]


def test_문서전송은_허용된_파일을_보낸다(bot):
    ok = asyncio.run(bot._safe_send_document(1, _PROJECT_ROOT / "README.md"))
    assert ok is True
    assert bot.app.bot.documents[0][1] == "README.md"


# ══════════════════════════════════════════════════════════════
# Task 5 — 미러링 표시명은 봇이 아니라 메시지에서 나온다
# ══════════════════════════════════════════════════════════════

def test_표시명은_메시지의_터미널에서_나온다():
    """[과거사고] 헤더가 sender_bot.label을 써서, 봇 수 < 터미널 수일 때 폴백 봇이
    선택되면 터미널6 메시지가 T1로 찍혔다. 출처는 메시지에서 뽑아야 정확하다."""
    assert "6" in telegram_agent_bot.source_label("T6", "claude")
    assert telegram_agent_bot.source_label("T6", "claude") != \
        telegram_agent_bot.source_label("T1", "claude")
