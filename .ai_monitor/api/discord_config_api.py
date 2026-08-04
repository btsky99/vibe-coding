"""
FILE: api/discord_config_api.py
DESCRIPTION: Discord 공용 봇 토큰과 PC·터미널별 채널 binding을 안전하게 저장하는 API.

REVISION HISTORY:
- 2026-08-03 Codex: T1~T9 다중 토큰 저장 API와 Windows DPAPI 보호 추가.
- 2026-08-03 Codex: 봇 1개와 Node ID, ACL, T1~T9 채널 binding을 저장하는 v2 스키마로 교체.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path


_TERMINAL = re.compile(r"T[1-9]")
_SNOWFLAKE = re.compile(r"\d{15,22}")
_NODE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(raw: bytes) -> str:
    """Windows에서는 현재 사용자 DPAPI로 암호화한다. 비 Windows 개발 환경은 권한 파일 폴백."""
    if os.name != "nt":
        return "plain:" + base64.b64encode(raw).decode("ascii")
    source_buffer = ctypes.create_string_buffer(raw)
    source = _Blob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "VibeCoding Discord", None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _unprotect(value: str) -> bytes:
    prefix, encoded = value.split(":", 1)
    encrypted = base64.b64decode(encoded)
    if prefix == "plain" and os.name != "nt":
        return encrypted
    if prefix != "dpapi" or os.name != "nt":
        raise ValueError("unsupported_discord_secret_format")
    source_buffer = ctypes.create_string_buffer(encrypted)
    source = _Blob(len(encrypted), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    target = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _empty_config() -> dict:
    return {"version": 2, "token": "", "node_id": "", "guild_ids": [],
            "user_ids": [], "channels": {}}


def load_config(secret_file: Path) -> dict:
    """v1의 터미널별 토큰은 의도적으로 승계하지 않는다.

    노출된 구 토큰이 자동 실행되지 않고 사용자가 공용 토큰을 다시 입력하게 하는
    것이 이 스키마 전환의 보안 불변식이다.
    """
    if not secret_file.exists():
        return _empty_config()
    payload = json.loads(_unprotect(secret_file.read_text(encoding="utf-8")).decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 2:
        return _empty_config()
    channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}
    return {
        "version": 2,
        "token": str(payload.get("token") or "").strip(),
        "node_id": str(payload.get("node_id") or "").strip().lower(),
        "guild_ids": [str(value) for value in payload.get("guild_ids", []) if _SNOWFLAKE.fullmatch(str(value))],
        "user_ids": [str(value) for value in payload.get("user_ids", []) if _SNOWFLAKE.fullmatch(str(value))],
        "channels": {str(key): str(value) for key, value in channels.items()
                     if _TERMINAL.fullmatch(str(key)) and _SNOWFLAKE.fullmatch(str(value))},
    }


def save_config(secret_file: Path, config: dict) -> None:
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    secret_file.write_text(_protect(raw), encoding="utf-8")
    if os.name != "nt":
        secret_file.chmod(0o600)


def _send(handler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json;charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", handler._cors_origin())
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_get(handler, secret_file: Path) -> None:
    """토큰 원문은 절대 응답하지 않고 비민감 binding과 설정 여부만 공개한다."""
    try:
        config = load_config(secret_file)
        _send(handler, {"token_configured": bool(config["token"]),
                        "node_id": config["node_id"], "guild_ids": config["guild_ids"],
                        "user_ids": config["user_ids"], "channels": config["channels"]})
    except Exception:
        _send(handler, {"token_configured": False, "node_id": "", "guild_ids": [],
                        "user_ids": [], "channels": {}, "error": "discord_config_unavailable"}, 500)


def handle_post(handler, secret_file: Path) -> None:
    """빈 token은 기존 secret을 유지하고 clear_token만 명시적 삭제로 처리한다."""
    try:
        length = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(body, dict):
            raise ValueError("invalid_payload")
        config = load_config(secret_file)
        token = str(body.get("token") or "").strip()
        if token:
            config["token"] = token
        elif body.get("clear_token") is True:
            config["token"] = ""
        node_id = str(body.get("node_id") or "").strip().lower()
        if not _NODE_ID.fullmatch(node_id):
            raise ValueError("invalid_node_id")
        config["node_id"] = node_id
        for field in ("guild_ids", "user_ids"):
            values = body.get(field)
            if not isinstance(values, list) or not values:
                raise ValueError(f"{field}_required")
            normalized = [str(value).strip() for value in values]
            if any(not _SNOWFLAKE.fullmatch(value) for value in normalized):
                raise ValueError(f"invalid_{field}")
            config[field] = list(dict.fromkeys(normalized))
        channels = body.get("channels")
        if not isinstance(channels, dict) or not channels:
            raise ValueError("channels_required")
        normalized_channels = {}
        for terminal, channel in channels.items():
            terminal = str(terminal).upper()
            channel = str(channel).strip()
            if not _TERMINAL.fullmatch(terminal) or not _SNOWFLAKE.fullmatch(channel):
                raise ValueError("invalid_channel_binding")
            normalized_channels[terminal] = channel
        if len(set(normalized_channels.values())) != len(normalized_channels):
            raise ValueError("duplicate_channel_binding")
        config["channels"] = normalized_channels
        save_config(secret_file, config)
        _send(handler, {"status": "saved", "token_configured": bool(config["token"]),
                        "node_id": config["node_id"], "guild_ids": config["guild_ids"],
                        "user_ids": config["user_ids"], "channels": config["channels"]})
    except ValueError as error:
        _send(handler, {"status": "error", "error": str(error)}, 400)
    except Exception:
        _send(handler, {"status": "error", "error": "discord_config_save_failed"}, 500)
