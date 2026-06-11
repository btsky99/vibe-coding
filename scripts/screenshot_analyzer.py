# -*- coding: utf-8 -*-
"""
FILE: scripts/screenshot_analyzer.py
DESCRIPTION: 멀티모달 버그 감지 — 스크린샷을 Antigravity Vision API로 분석하여
             에러 다이얼로그, UI 깨짐, 예외 메시지를 자동 감지합니다.

             [동작 원리]
             1. /api/screenshot/analyze로 base64 인코딩된 이미지 수신
             2. Gemini Vision API (gemini-2.0-flash)로 이미지 분석
             3. 에러/버그 감지 시 자동으로 태스크 생성
             4. GOOGLE_API_KEY 환경변수 필요

REVISION HISTORY:
- 2026-03-15 Claude: 최초 구현 — Gemini Vision 기반 스크린샷 분석
"""

import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, save_task

DATA_DIR = MONITOR_DIR / 'data'

# Antigravity Vision 분석 프롬프트
_ANALYSIS_PROMPT = (
    "이 스크린샷을 분석하세요. 다음을 확인하세요:\n"
    "1. 에러 다이얼로그 (Error, Exception, 오류, 실패 등)\n"
    "2. UI 깨짐 (레이아웃 틀어짐, 텍스트 겹침, 빈 화면)\n"
    "3. 스택 트레이스 또는 예외 메시지\n"
    "4. 비정상 상태 (로딩 무한, 빈 데이터 표시)\n\n"
    "문제가 발견되면 JSON으로 응답하세요:\n"
    '{"found": true, "issues": [{"type": "error|ui_bug|crash", "description": "설명", "severity": "critical|high|medium|low"}]}\n\n'
    '문제가 없으면: {"found": false, "issues": []}'
)


def analyze_screenshot(image_base64: str, api_key: str = None) -> dict:
    """Base64 인코딩된 스크린샷을 Antigravity Vision으로 분석합니다.

    Args:
        image_base64: PNG/JPEG 이미지의 base64 문자열
        api_key: Google API 키 (없으면 환경변수에서 조회)

    Returns:
        {"found": bool, "issues": [...], "raw_response": "..."}
    """
    key = api_key or os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not key:
        return {"found": False, "issues": [], "error": "GOOGLE_API_KEY 환경변수가 설정되지 않았습니다."}

    # MIME 타입 추정 (base64 헤더로 판단)
    mime_type = "image/png"
    if image_base64.startswith("/9j/"):
        mime_type = "image/jpeg"

    req_body = json.dumps({
        "contents": [{
            "parts": [
                {"text": _ANALYSIS_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": image_base64}}
            ]
        }],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0.1}
    }).encode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
    req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"found": False, "issues": [], "error": f"API 호출 실패: {e}"}

    # 응답 파싱
    text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not text.strip():
        return {"found": False, "issues": [], "raw_response": "빈 응답"}

    # JSON 응답 추출 (마크다운 코드블록 안에 있을 수 있음)
    clean = text.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(clean)
        parsed["raw_response"] = text
        return parsed
    except json.JSONDecodeError:
        return {"found": False, "issues": [], "raw_response": text}


def analyze_and_create_tasks(image_base64: str, project_id: str = '') -> dict:
    """스크린샷 분석 후 발견된 버그를 자동으로 태스크로 생성합니다.

    Returns:
        {"analysis": {...}, "tasks_created": N}
    """
    analysis = analyze_screenshot(image_base64)
    tasks_created = 0

    if analysis.get("found") and analysis.get("issues"):
        ensure_schema(DATA_DIR)
        for issue in analysis["issues"]:
            severity = issue.get("severity", "medium")
            description = issue.get("description", "스크린샷에서 감지된 버그")
            issue_type = issue.get("type", "bug")

            priority_map = {"critical": "urgent", "high": "high", "medium": "medium", "low": "low"}
            task = {
                "id": str(int(time.time() * 1000) + tasks_created),
                "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S'),
                "updated_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
                "title": f"[{issue_type}] {description[:80]}",
                "description": f"멀티모달 감지(스크린샷 분석)로 자동 생성됨.\n\n{description}",
                "status": "pending",
                "assigned_to": "all",
                "priority": priority_map.get(severity, "medium"),
                "created_by": "screenshot_analyzer",
                "kanban_status": "todo",
                "tags": ["auto-detected", "screenshot", issue_type],
            }
            save_task(task, project_id=project_id)
            tasks_created += 1

    return {"analysis": analysis, "tasks_created": tasks_created}


if __name__ == "__main__":
    # 테스트: 파일 경로를 인자로 전달
    if len(sys.argv) > 1:
        img_path = Path(sys.argv[1])
        if img_path.exists():
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            result = analyze_screenshot(b64)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"파일 없음: {img_path}")
    else:
        print("사용법: python screenshot_analyzer.py <image_path>")
