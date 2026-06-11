#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/antigravity_adapter.py
DESCRIPTION: Antigravity CLI(agy) 호출 격리 레이어 — closed-source 인터페이스 변경 대비
             단일 격리점. 명령 빌드/경로 탐색/세션 감지/비대화형 실행을 전부 이 모듈로 통일.
             (2026-05-24 마이그레이션 승인안의 어댑터 패턴. 직접 agy 문자열 조립 금지)

REVISION HISTORY:
- 2026-06-11 Claude: 최초 작성 — Task 1 실측(agy 1.0.7) 기반
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# [실측 2026-06-11] agy는 구 Gemini CLI의 홈 디렉토리를 그대로 이어받는다.
# ~/.gemini/         — oauth_creds.json, settings.json(hooks), trusted_hooks.json
# ~/.gemini/antigravity-cli/ — agy 자체 데이터 (conversations/*.db, history.jsonl, cli.log)
# → '.gemini' 경로 문자열은 GEMINI_API_KEY와 동급의 외부 도구 인터페이스. rename 금지.
HOME_CONFIG_DIR = Path.home() / ".gemini"
DATA_ROOT = HOME_CONFIG_DIR / "antigravity-cli"


class AntigravityPrintCaptureError(RuntimeError):
    """agy -p가 파이프 환경에서 응답을 stdout에 쓰지 않는 알려진 결함의 명시적 신호.

    [실측 2026-06-11, agy 1.0.7] -p/--print는 stdout이 파이프/리다이렉트면
    exit 0 + 빈 출력으로 끝난다 (cli.log상 모델 생성은 성공 — TUI 콘솔 버퍼 전용 렌더).
    조용한 빈 문자열 반환은 호출부가 '응답 없음'으로 오인하므로 반드시 예외로 승격한다.
    agy 업데이트로 수정되면 run_print()가 자동으로 정상 동작한다 (출력 있으면 그대로 반환).
    """


def find_agy() -> str:
    """agy 실행 파일 전체 경로. 못 찾으면 'agy' 그대로 (쉘 PATH 위임)."""
    found = shutil.which("agy") or shutil.which("agy.exe")
    if found:
        return found
    # [실측] 표준 설치 위치 — LOCALAPPDATA/agy/bin/agy.exe
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    if cand.is_file():
        return str(cand)
    return "agy"


def conversations_dir() -> Path:
    """agy 대화 저장 디렉토리 — 외부 세션 감지(agent_api)가 mtime 스캔하는 대상.

    [주의] 구 Gemini CLI의 ~/.gemini/tmp/{project}/chats/ 는 agy에서 사용 안 함.
    """
    return DATA_ROOT / "conversations"


def cli_log_path() -> Path:
    return DATA_ROOT / "cli.log"


def detect_external_sessions(within_sec: int = 600) -> list[dict]:
    """최근 within_sec 이내 갱신된 agy 대화 파일 목록 — 외부 실행 감지용.

    [제약] agy 대화는 프로젝트별 디렉토리 분리가 없어 (UUID 평면 구조)
    구버전처럼 프로젝트 단위 매칭은 불가. 전역 활동 여부만 판단한다.
    """
    import time
    out: list[dict] = []
    conv = conversations_dir()
    if not conv.is_dir():
        return out
    now = time.time()
    try:
        for f in conv.iterdir():
            if f.suffix not in (".db", ".pb"):
                continue
            age = now - f.stat().st_mtime
            if age <= within_sec:
                out.append({"id": f.stem, "mtime_age_sec": int(age), "path": str(f)})
    except OSError:
        pass
    return sorted(out, key=lambda x: x["mtime_age_sec"])


def build_print_cmd(prompt: str, model: str | None = None, yolo: bool = False) -> list[str]:
    """비대화형(-p) 명령 리스트. subprocess 직접 전달용."""
    cmd = [find_agy()]
    if model:
        cmd.extend(["--model", model])
    if yolo:
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["-p", prompt])
    return cmd


def build_interactive_invocation(yolo: bool = False, prompt: str | None = None) -> str:
    """터미널(콘솔 보유) 컨텍스트용 호출 문자열 — server.py `start cmd /k` 경로에서 사용.

    [제약] 대화형 TUI는 실제 콘솔에서만 정상 렌더 — 이 문자열을 파이프로 실행 금지.
    """
    parts = ["agy"]
    if yolo:
        parts.append("--dangerously-skip-permissions")
    if prompt:
        # -i: 초기 프롬프트 실행 후 대화형 유지 (구 gemini -i 와 동일 의미)
        parts.extend(["-i", subprocess.list2cmdline([prompt])])
    return " ".join(parts)


def run_print(prompt: str, model: str | None = None, yolo: bool = False,
              timeout: int = 300, cwd: str | None = None) -> str:
    """비대화형 1회 실행 → 응답 텍스트. 빈 출력이면 AntigravityPrintCaptureError.

    [호환성] 호출부는 이 예외를 잡아 '비대화형 캡처 불가' 안내를 남겨야 한다.
    실콘솔 경로(pty-server O세션/터미널)는 정상이므로 대화형 경로로 우회 가능.
    """
    cmd = build_print_cmd(prompt, model=model, yolo=yolo)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, cwd=cwd, creationflags=creationflags,
    )
    text = (proc.stdout or "").strip()
    if text:
        return text
    raise AntigravityPrintCaptureError(
        f"agy -p 빈 출력 (exit={proc.returncode}). 알려진 파이프 캡처 결함 — "
        f"콘솔(PTY) 경유 실행 필요. stderr={(proc.stderr or '')[:200]!r}"
    )


if __name__ == "__main__":
    # 자가 진단: 경로 + 명령 빌드 + 외부 세션 감지 (네트워크 호출 없음)
    print("agy        :", find_agy())
    print("data_root  :", DATA_ROOT, "(exists:%s)" % DATA_ROOT.is_dir())
    print("print cmd  :", build_print_cmd("hi", model="m", yolo=True))
    print("interactive:", build_interactive_invocation(yolo=True, prompt="hi"))
    print("recent     :", detect_external_sessions(3600)[:3])
