"""
FILE: setup_doctor.py
DESCRIPTION: 하이브 마인드 초기 설정 자동 진단 + 수리 엔진.
             서버 시작 시 자동 실행되어 환경을 점검하고, 자동으로 고칠 수 있는 것은
             즉시 수리하고, 사용자 입력이 필요한 항목만 대시보드 배너로 안내한다.

             5가지 진단 항목:
             1. pg_locale   — PostgreSQL lc_messages=C 강제 (CP949 크래시 방지)
             2. pg_database — 프로젝트별 DB 존재 여부 확인
             3. hooks       — .claude/settings.json 훅 설정 확인/생성
             4. cli_agents  — claude/antigravity/codex CLI 설치 감지
             5. telegram    — .env 텔레그램 봇 토큰 유무

REVISION HISTORY:
- 2026-07-30 Claude: check_hooks가 그룹 형식(matcher+hooks)을 못 읽어 매 진단마다 flat 훅을
                     중복 추가하던 사고 수정 — /doctor "Expected array, received undefined" 원인.
- 2026-07-29 Codex: Detect official Antigravity command `agy`, separately from Gemini.
- 2026-07-29 Codex: Do not misreport a missing project .claude folder as a missing Claude CLI.
- 2026-07-28 Codex: Mark partial AI CLI installations as actionable and accept the Gemini compatibility command.
- 2026-03-27 Claude: 최초 작성. 접근법 C(자동 수리 + 필요할 때만 위자드) 구현.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── 경로 결정 ──────────────────────────────────────────────────────────
# frozen(EXE) 모드와 개발 모드 모두 지원
if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).resolve().parent
    _PG_DIR = _BASE_DIR / "pgsql"
    _PG_DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"
else:
    _BASE_DIR = Path(__file__).resolve().parent
    _PG_DIR = _BASE_DIR / "bin" / "pgsql"
    _PG_DATA_DIR = _PG_DIR / "data"

_PROJECT_ROOT = _BASE_DIR.parent if not getattr(sys, 'frozen', False) else _BASE_DIR


# ── 진단 결과 상수 ────────────────────────────────────────────────────
STATUS_OK = "ok"           # 정상
STATUS_FIXED = "fixed"     # 자동 수리 완료
STATUS_MISSING = "missing" # 사용자 조치 필요
STATUS_ERROR = "error"     # 수리 실패


def _make_result(status: str, message: str, auto_fixed: bool = False, action: str = "") -> dict:
    """진단 결과 딕셔너리 생성"""
    r = {"status": status, "message": message, "auto_fixed": auto_fixed}
    if action:
        r["action"] = action
    return r


# ═══════════════════════════════════════════════════════════════════════
#  1. PostgreSQL lc_messages 진단
# ═══════════════════════════════════════════════════════════════════════

def check_pg_locale() -> dict:
    """postgresql.conf의 lc_messages가 'C'인지 확인하고, 아니면 자동 수정한다.

    [배경] Windows 한글 환경에서 PostgreSQL이 CP949 에러 메시지를 반환하면
    psycopg2가 UTF-8 디코딩에 실패하여 UnicodeDecodeError 크래시 발생.
    lc_messages=C로 설정하면 영문 에러 메시지가 나와 문제가 해소됨.
    """
    pg_conf = _PG_DATA_DIR / "postgresql.conf"
    if not pg_conf.exists():
        return _make_result(STATUS_OK, "postgresql.conf 없음 (PG 미설치 또는 미초기화)")

    try:
        text = pg_conf.read_text(encoding='utf-8')
    except Exception as e:
        return _make_result(STATUS_ERROR, f"postgresql.conf 읽기 실패: {e}")

    # 현재 lc_messages 값 확인
    match = re.search(r"^lc_messages\s*=\s*'([^']*)'", text, re.MULTILINE)
    if match:
        current = match.group(1)
        if current == 'C':
            return _make_result(STATUS_OK, "lc_messages=C 정상")

        # 자동 수정: 기존 값을 'C'로 변경
        new_text = re.sub(
            r"^(lc_messages\s*=\s*)'[^']*'",
            r"\g<1>'C'\t\t\t# 영문 에러 메시지 강제 — psycopg2 UTF-8 디코딩 오류 방지 (setup_doctor 자동 적용)",
            text, count=1, flags=re.MULTILINE
        )
        try:
            pg_conf.write_text(new_text, encoding='utf-8')
            return _make_result(STATUS_FIXED, f"lc_messages={current} → C 자동 수정", auto_fixed=True)
        except Exception as e:
            return _make_result(STATUS_ERROR, f"postgresql.conf 쓰기 실패: {e}")
    else:
        return _make_result(STATUS_OK, "lc_messages 설정 없음 (기본값 사용 중)")


# ═══════════════════════════════════════════════════════════════════════
#  2. 프로젝트 DB 존재 여부
# ═══════════════════════════════════════════════════════════════════════

def check_pg_database() -> dict:
    """프로젝트별 PostgreSQL DB가 존재하는지 확인한다."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='127.0.0.1',
            port=int(os.environ.get('VIBE_PG_PORT', '5433')),
            user='postgres',
            dbname='postgres',
            options='-c lc_messages=C'
        )
        conn.autocommit = True
        cur = conn.cursor()

        # 프로젝트 DB 이름 결정 (pg_store._resolve_project_db 로직 재현)
        proj_raw = str(_PROJECT_ROOT).replace('\\', '/').replace(':', '').replace('/', '--')
        project_id = proj_raw.lstrip('-') or 'default'
        safe_id = project_id.lower().replace('-', '_').replace(' ', '_')
        safe_id = ''.join(c for c in safe_id if c.isalnum() or c == '_')
        db_name = f"vibe_{safe_id}"[:63]

        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db_name,))
        exists = cur.fetchone() is not None
        conn.close()

        if exists:
            return _make_result(STATUS_OK, f"프로젝트 DB '{db_name}' 존재")
        else:
            return _make_result(STATUS_MISSING, f"프로젝트 DB '{db_name}' 없음 — 서버 시작 시 자동 생성됨")
    except ImportError:
        return _make_result(STATUS_ERROR, "psycopg2 미설치")
    except Exception as e:
        return _make_result(STATUS_ERROR, f"PG 연결 실패: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  3. Claude Code 훅 설정
# ═══════════════════════════════════════════════════════════════════════

# 필수 훅 정의 — 각 이벤트에 필요한 명령어 목록
#
# [WHY 인자 없음] 훅은 이벤트 페이로드를 stdin JSON으로 받는다(hook_bridge.main()의
# `json.loads(sys.stdin.read())` → `data['prompt']`). 과거엔 `"$PROMPT"`를 argv로 넘겼지만
# Claude Code는 명령 문자열에 셸 변수 치환을 하지 않아 리터럴 `$PROMPT`가 전달됐고,
# 받는 쪽은 argv를 아예 읽지 않아 무의미했다. 인자를 늘리려면 stdin 스키마를 쓸 것.
_REQUIRED_HOOKS: dict[str, list[dict]] = {
    "UserPromptSubmit": [
        {"type": "command", "command": f"python \"{_PROJECT_ROOT / 'scripts' / 'hook_bridge.py'}\""}
    ],
    "Stop": [
        {"type": "command", "command": f"python \"{_PROJECT_ROOT / 'scripts' / 'claude_hook.py'}\" stop"}
    ],
}


def _as_group(cmd_def: dict) -> dict:
    """flat 훅 정의를 Claude Code 정식 그룹 형식으로 감싼다.

    [불변식] settings.json의 hooks.<event>는 반드시 {matcher, hooks:[...]} 그룹 배열이다.
    flat {type, command}를 직접 넣으면 CLI 스키마 검증에서 hooks 키 누락으로 거부된다.
    """
    return {"matcher": "", "hooks": [cmd_def]}


def _event_commands(entries: list) -> list[str]:
    """이벤트 배열에서 등록된 command 문자열을 전부 뽑는다 (그룹 안쪽까지).

    [과거사고] 2026-07-30: 옛 구현은 그룹 객체에 대고 바로 `.get("command")`를 읽어
    항상 ''를 얻었다 → 이미 등록된 hook_bridge/claude_hook을 못 보고 매 진단마다 flat
    항목을 append → hooks.UserPromptSubmit.1 / hooks.Stop.2에 hooks 키 없는 쓰레기 항목이
    쌓여 /doctor가 "Expected array, but received undefined"를 보고. 진단 API는 앱 부팅마다
    SetupBanner가 호출하므로 앱을 켤 때마다 재오염됐다.
    """
    out: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("hooks"), list):
            out.extend(h.get("command", "") for h in entry["hooks"] if isinstance(h, dict))
        elif "command" in entry:
            out.append(entry.get("command", ""))
    return out


def _script_names(command: str) -> set[str]:
    """command 문자열에서 실행되는 .py 스크립트 파일명만 뽑는다.

    [WHY] 오염분과 정상 항목은 인자/인용 부호가 달라(`...hook_bridge.py` vs
    `"...hook_bridge.py" "$PROMPT"`) 문자열 동등 비교로는 중복을 못 잡는다.
    같은 스크립트가 두 번 등록되면 훅이 두 번 실행돼 pg_logs `[지시]`가 2줄씩 찍혔다.
    """
    return {m.lower() for m in re.findall(r"([\w.-]+\.py)", command)}


def _normalize_event(entries: list) -> tuple[list, bool]:
    """flat 잔재 정리 + 같은 스크립트 중복 등록 제거. (정규화 결과, 변경여부)

    [WHY] 과거 오염분을 사용자가 손으로 지우게 두면 앱 재시작마다 되살아난다 —
    자동 수리 엔진이므로 형식 정규화까지 여기서 끝낸다.
    [불변식] 정상 그룹은 원본 그대로 보존한다. 버리는 쪽은 항상 flat 잔재 — 사용자가
    직접 손본 그룹 항목을 자동 수리가 삭제하는 일은 없어야 한다.
    """
    groups = [e for e in entries if isinstance(e, dict) and isinstance(e.get("hooks"), list)]
    registered: set[str] = set()
    for g in groups:
        for h in g["hooks"]:
            if isinstance(h, dict):
                registered |= _script_names(h.get("command", ""))

    out: list = []
    changed = False
    for entry in entries:
        if not isinstance(entry, dict):
            changed = True
            continue
        if isinstance(entry.get("hooks"), list):
            out.append(entry)
            continue
        # flat 잔재 — 같은 스크립트가 이미 그룹으로 있으면 버리고, 없으면 그룹으로 승격
        cmd = entry.get("command", "")
        changed = True
        if cmd and not (_script_names(cmd) & registered):
            registered |= _script_names(cmd)
            out.append({
                "matcher": entry.get("matcher", ""),
                "hooks": [{"type": entry.get("type", "command"), "command": cmd}],
            })
    return out, changed


def check_hooks() -> dict:
    """Claude Code 훅 설정(.claude/settings.json)을 확인하고, 누락된 훅만 추가한다.

    [핵심 원칙] 기존 설정을 절대 덮어쓰지 않는다. 누락된 이벤트 훅만 추가.
    """
    # .claude/settings.json 경로 (프로젝트 루트)
    settings_path = _PROJECT_ROOT / ".claude" / "settings.json"

    # Project configuration is independent from the globally installed CLI.
    # Create the folder and repair hooks below; check_cli_agents() is the sole
    # authority for deciding whether Claude itself is installed.
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # 기존 설정 로드
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding='utf-8'))
        except Exception:
            existing = {}

    hooks = existing.get("hooks", {})
    added = []

    normalized = False
    for event, commands in _REQUIRED_HOOKS.items():
        if event not in hooks or not isinstance(hooks.get(event), list):
            hooks[event] = [_as_group(c) for c in commands]
            added.append(event)
            continue

        # 기존 항목의 형식 정규화 먼저 — 과거 오염분(flat/중복)을 여기서 청산
        hooks[event], ev_changed = _normalize_event(hooks[event])
        normalized = normalized or ev_changed

        # 이벤트는 있지만 필수 명령어가 빠진 경우 추가
        existing_cmds = _event_commands(hooks[event])
        for cmd_def in commands:
            # hook_bridge.py 또는 claude_hook.py가 포함된 명령어가 있는지 확인
            key_script = "hook_bridge.py" if "hook_bridge" in cmd_def["command"] else "claude_hook.py"
            if not any(key_script in c for c in existing_cmds):
                hooks[event].append(_as_group(cmd_def))
                added.append(f"{event}(+{key_script})")

    if not added and normalized:
        existing["hooks"] = hooks
        try:
            settings_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            return _make_result(STATUS_FIXED, "훅 형식 정규화 (flat/중복 항목 정리)", auto_fixed=True)
        except Exception as e:
            return _make_result(STATUS_ERROR, f"settings.json 쓰기 실패: {e}")

    if not added:
        hook_count = sum(len(v) for v in hooks.values())
        return _make_result(STATUS_OK, f"훅 {hook_count}개 정상")

    # 수정된 설정 저장 (기존 설정 보존)
    existing["hooks"] = hooks
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        return _make_result(STATUS_FIXED, f"훅 자동 추가: {', '.join(added)}", auto_fixed=True)
    except Exception as e:
        return _make_result(STATUS_ERROR, f"settings.json 쓰기 실패: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  4. CLI 에이전트 설치 감지
# ═══════════════════════════════════════════════════════════════════════

def check_cli_agents() -> dict:
    """claude, antigravity, codex CLI가 시스템에 설치되어 있는지 확인한다."""
    agents = {
        "claude": ["claude", "--version"],
        "antigravity": ["agy", "--version"],
        "codex": ["codex", "--version"],
    }

    found = []
    missing = []

    for name, cmd in agents.items():
        candidates = [cmd[0]]
        # shutil.which로 PATH에서 찾기
        if any(shutil.which(candidate) for candidate in candidates):
            found.append(name)
        else:
            # Windows: .cmd 확장자로도 확인
            if os.name == 'nt' and any(shutil.which(f"{candidate}.cmd") for candidate in candidates):
                found.append(name)
            else:
                missing.append(name)

    if not missing:
        return _make_result(STATUS_OK, f"CLI 감지: {', '.join(found)}")
    if found:
        message = f"CLI 감지: {', '.join(found)} (미설치: {', '.join(missing)})"
    else:
        message = f"CLI 미감지 — {', '.join(missing)} 설치 필요"
    return _make_result(STATUS_MISSING, message, action="install_cli")


# ═══════════════════════════════════════════════════════════════════════
#  5. 텔레그램 봇 토큰
# ═══════════════════════════════════════════════════════════════════════

def check_telegram() -> dict:
    """프로젝트 루트의 .env에 텔레그램 봇 토큰이 설정되어 있는지 확인한다."""
    env_path = _PROJECT_ROOT / ".env"

    if not env_path.exists():
        return _make_result(STATUS_MISSING, "텔레그램 봇 미설정 (.env 파일 없음)",
                            action="open_telegram_panel")

    try:
        text = env_path.read_text(encoding='utf-8')
    except Exception:
        return _make_result(STATUS_ERROR, ".env 읽기 실패")

    # TELEGRAM_BOT_T{n}= 패턴에서 실제 토큰(숫자:문자열)이 있는지 확인
    token_pattern = re.compile(r'^TELEGRAM_BOT_T\d+=(\d+:[A-Za-z0-9_-]+)', re.MULTILINE)
    tokens = token_pattern.findall(text)

    if tokens:
        return _make_result(STATUS_OK, f"텔레그램 봇 {len(tokens)}개 설정됨")
    else:
        return _make_result(STATUS_MISSING, "텔레그램 봇 토큰 미설정",
                            action="open_telegram_panel")


# ═══════════════════════════════════════════════════════════════════════
#  6. Sub-agent 설정 확인
# ═══════════════════════════════════════════════════════════════════════

def check_subagents() -> dict:
    """Claude Code Sub-agent 정의 파일(.claude/agents/*.md)과
    Agent Teams 활성화 설정을 확인한다."""
    agents_dir = _PROJECT_ROOT / ".claude" / "agents"
    settings_path = _PROJECT_ROOT / ".claude" / "settings.json"

    agent_files = list(agents_dir.glob("*.md")) if agents_dir.exists() else []

    teams_enabled = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding='utf-8'))
            env = settings.get("env", {})
            teams_enabled = env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1"
        except Exception:
            pass

    agent_names = [f.stem for f in agent_files]
    parts = []
    if agent_names:
        parts.append(f"Sub-agent {len(agent_names)}개 ({', '.join(agent_names)})")
    else:
        parts.append("Sub-agent 없음")
    parts.append("Agent Teams " + ("활성" if teams_enabled else "비활성"))

    if agent_files and teams_enabled:
        return _make_result(STATUS_OK, " / ".join(parts))
    elif agent_files:
        return _make_result(STATUS_OK, " / ".join(parts))
    else:
        return _make_result(STATUS_MISSING, " / ".join(parts),
                            action="create_subagents")


# ═══════════════════════════════════════════════════════════════════════
#  통합 진단 실행
# ═══════════════════════════════════════════════════════════════════════

def run_all() -> dict[str, Any]:
    """모든 진단 항목을 실행하고 결과를 반환한다.

    Returns:
        {
            "ready": bool,     # 모든 항목이 ok 또는 fixed면 True
            "checks": {
                "pg_locale": { "status": ..., "message": ..., ... },
                "pg_database": ...,
                "hooks": ...,
                "cli_agents": ...,
                "telegram": ...,
            },
            "auto_fixed": [...],  # 자동 수리된 항목 이름 목록
            "needs_action": [...],  # 사용자 조치 필요 항목
        }
    """
    checks = {
        "pg_locale": check_pg_locale(),
        "pg_database": check_pg_database(),
        "hooks": check_hooks(),
        "cli_agents": check_cli_agents(),
        "telegram": check_telegram(),
        "subagents": check_subagents(),
    }

    auto_fixed = [k for k, v in checks.items() if v.get("auto_fixed")]
    needs_action = [k for k, v in checks.items() if v["status"] == STATUS_MISSING]
    ready = all(v["status"] in (STATUS_OK, STATUS_FIXED) for v in checks.values())

    return {
        "ready": ready,
        "checks": checks,
        "auto_fixed": auto_fixed,
        "needs_action": needs_action,
    }


# ── CLI 직접 실행 지원 ────────────────────────────────────────────────
if __name__ == "__main__":
    result = run_all()

    print("=" * 60)
    print("🏥 하이브 마인드 Setup Doctor")
    print("=" * 60)

    for name, check in result["checks"].items():
        icon = {"ok": "✅", "fixed": "🔧", "missing": "⚠️", "error": "❌"}.get(check["status"], "?")
        print(f"  {icon} {name:15s}  {check['message']}")

    print()
    if result["auto_fixed"]:
        print(f"  🔧 자동 수리: {', '.join(result['auto_fixed'])}")
    if result["needs_action"]:
        print(f"  ⚠️  조치 필요: {', '.join(result['needs_action'])}")
    if result["ready"]:
        print("  ✅ 시스템 준비 완료!")
    print()
