"""
FILE: sitecustomize.py
DESCRIPTION: 프로젝트 Python 프로세스의 표준 입출력 인코딩을 UTF-8로 고정합니다.
             Windows PowerShell/cmd의 기본 코드페이지가 CP949 등으로 잡힌 상태에서도
             하이브 진단, 빌드 검증, 문서 생성 스크립트의 한글 출력이 깨지지 않도록
             Python이 자동 import하는 sitecustomize 훅을 사용합니다.

REVISION HISTORY:
- 2026-05-03 Codex: Windows 콘솔 한글 출력 깨짐 방지를 위해 stdout/stderr 및
                    Python UTF-8 환경변수 기본값을 설정.
"""

from __future__ import annotations

import os
import sys


def _force_utf8_streams() -> None:
    """Python 표준 출력/에러 스트림을 UTF-8로 재설정합니다."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # 일부 임베디드/GUI 실행 환경은 스트림 재설정을 허용하지 않습니다.
            # 그 경우 기존 스트림을 유지하되 프로세스 시작 자체는 막지 않습니다.
            pass


# 하위 Python 프로세스에도 UTF-8 기본값이 이어지도록 환경변수를 보강합니다.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_force_utf8_streams()
