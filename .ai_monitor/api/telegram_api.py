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

        # 기존 .env에서 현재 토큰값 로드 (마스킹 값 복원용)
        existing_tokens: dict = {}
        existing_lines: list = []
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("TELEGRAM_BOT_T") and "=" in stripped:
                    key = stripped.split("=", 1)[0].replace("TELEGRAM_BOT_", "")
                    val = stripped.split("=", 1)[1].strip()
                    existing_tokens[key] = val
                elif not stripped.startswith("TELEGRAM_"):
                    existing_lines.append(line)

        # 텔레그램 멀티봇 설정 추가
        existing_lines.append("")
        existing_lines.append("# Telegram Multi-Bot Bridge")
        for tid in range(1, 9):
            key = f"T{tid}"
            new_val = tokens.get(key, "").strip()
            # 마스킹된 값("123...")이면 기존 값 유지
            if new_val.endswith("..."):
                new_val = existing_tokens.get(key, "")
            existing_lines.append(f"TELEGRAM_BOT_{key}={new_val}")

        env_file.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")

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
