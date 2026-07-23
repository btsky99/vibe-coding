"""
FILE: api/telegram_api.py
DESCRIPTION: Telegram 멀티봇 설정 API. .env에서 봇 토큰을 읽고 저장하며,
             텔레그램 브릿지 프로세스(_child_procs 내) 가동 여부를 체크하여
             봇별 online/offline 상태를 노출한다. /api/telegram/test는
             첫 번째 유효 토큰으로 getMe 호출하여 봇 이름을 확인한다.

REVISION HISTORY:
- 2026-04-20 Claude: server.py SSEHandler L1987~2131 분리 (Task 5.1)
                     클래스 메서드 → handler 인자를 받는 모듈 함수로 변환
"""
from __future__ import annotations

import json
from pathlib import Path


def telegram_config_get(handler, project_root: Path, child_procs: list) -> None:
    """GET /api/config/telegram — .env에서 멀티봇 텔레그램 설정 읽기.

    [반환 형식]
    {
      "tokens": {"T1": "123...", "T2": "456..."},  // 마스킹된 봇 토큰
      "bot_statuses": {"T1": "online", "T2": "offline"}  // 브릿지 실행 시
    }
    """
    env_file = project_root / ".env"
    config: dict = {"tokens": {}, "bot_statuses": {}}
    try:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_T") and "=" in line:
                    # TELEGRAM_BOT_T1=token → tokens["T1"] = "token..."(마스킹)
                    key = line.split("=", 1)[0].replace("TELEGRAM_BOT_", "")
                    val = line.split("=", 1)[1].strip()
                    if val:
                        config["tokens"][key] = val[:8] + "..." if len(val) > 8 else val
        # 브릿지 프로세스 실행 여부 확인
        bridge_running = False
        for proc in child_procs:
            try:
                if proc.poll() is None and hasattr(proc, 'args'):
                    args_str = str(getattr(proc, 'args', ''))
                    if 'telegram_bridge' in args_str:
                        bridge_running = True
                        break
            except Exception:
                pass
        # 브릿지 실행 중이면 토큰이 있는 봇은 online 표시
        if bridge_running:
            for key in config["tokens"]:
                config["bot_statuses"][key] = "online"
    except Exception:
        pass
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(config, ensure_ascii=False).encode('utf-8'))


_TG_SECTION_MARKER = "# Telegram Multi-Bot Bridge"


def rewrite_env_telegram_tokens(env_text: str, tokens: dict) -> str:
    """`.env` 본문에서 TELEGRAM_BOT_T1~T8 블록만 교체한 새 본문을 돌려준다.

    [WHY 순수 함수인가] 원래 이 로직이 handler 안에 인라인돼 있어 테스트가 불가능했고,
    그래서 아래 두 사고가 실제 저장 시점까지 발견되지 않았다. 문자열→문자열 함수로
    떼어내 단위 테스트로 회귀를 고정한다.

    [불변식 1] TELEGRAM_BOT_T* 이외의 라인은 무엇도 잃지 않는다.
      과거사고: 제거 조건이 `startswith("TELEGRAM_")`이라 TELEGRAM_GROUP_CHAT_ID까지
      지워졌고, 그룹 ID가 비면 send_to_group이 가드에 걸려 **조용히** 전부 무동작했다.
    [불변식 2] 멱등 — 같은 입력으로 두 번 돌리면 결과가 같다.
      마커 주석/말미 공백을 걷어내지 않으면 저장할 때마다 헤더가 누적된다.
    [불변식 3] 마스킹 토큰("123...")은 저장하지 않고 기존 값을 유지한다
      (UI가 마스킹된 값을 그대로 되돌려보내므로, 이게 없으면 토큰이 파괴된다).
    """
    existing_tokens: dict = {}
    kept: list = []
    for line in env_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("TELEGRAM_BOT_T") and "=" in stripped:
            key = stripped.split("=", 1)[0].replace("TELEGRAM_BOT_", "")
            existing_tokens[key] = stripped.split("=", 1)[1].strip()
            continue
        if stripped == _TG_SECTION_MARKER:
            continue  # [불변식 2] 아래에서 다시 붙이므로 여기선 제거
        kept.append(line)

    while kept and not kept[-1].strip():  # [불변식 2] 말미 공백 정리
        kept.pop()

    kept.append("")
    kept.append(_TG_SECTION_MARKER)
    for tid in range(1, 9):
        key = f"T{tid}"
        new_val = (tokens.get(key) or "").strip()
        if new_val.endswith("..."):  # [불변식 3]
            new_val = existing_tokens.get(key, "")
        kept.append(f"TELEGRAM_BOT_{key}={new_val}")
    return "\n".join(kept) + "\n"


def telegram_config_post(handler, project_root: Path) -> None:
    """POST /api/config/telegram — .env에 멀티봇 텔레그램 설정 저장.

    [요청 형식]
    {
      "tokens": {"T1": "full_token_1", "T2": "full_token_2"}
    }

    [동작]
    .env에서 TELEGRAM_ 접두사 라인을 모두 제거 후 새로운 멀티봇 형식으로 재작성.
    마스킹된 토큰("123...") 값은 무시하고 기존 값 유지.
    """
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = json.loads(handler.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
        tokens = body.get("tokens", {})

        env_file = project_root / ".env"
        env_text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        env_file.write_text(rewrite_env_telegram_tokens(env_text, tokens), encoding="utf-8")

        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "saved"}).encode('utf-8'))
    except Exception as e:
        handler.send_response(500)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))


def telegram_test(handler, project_root: Path) -> None:
    """POST /api/telegram/test — 멀티봇 텔레그램 테스트 메시지 전송.

    [동작]
    .env에서 첫 번째 유효한 봇 토큰을 찾아 getMe API로 봇 이름 확인.
    """
    try:
        env_file = project_root / ".env"
        # 첫 번째 유효한 봇 토큰 찾기
        first_token = ""
        first_tid = ""
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("TELEGRAM_BOT_T") and "=" in stripped:
                    key = stripped.split("=", 1)[0].replace("TELEGRAM_BOT_", "")
                    val = stripped.split("=", 1)[1].strip()
                    if val and not first_token:
                        first_token = val
                        first_tid = key

        if not first_token:
            raise ValueError("봇 토큰이 하나도 설정되지 않았습니다")

        import urllib.request
        # getMe로 봇 이름 확인
        url = f"https://api.telegram.org/bot{first_token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as resp:
            me = json.loads(resp.read().decode("utf-8"))

        bot_name = me.get("result", {}).get("first_name", first_tid)
        results = {"bot_name": bot_name, "tid": first_tid}

        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "sent", **results}).encode('utf-8'))
    except Exception as e:
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({"status": "failed", "error": str(e)}).encode('utf-8'))
