"""
FILE: api/launch_api.py
DESCRIPTION: CLI 에이전트(claude/antigravity/codex) 실행 API — 새 cmd 창에서 에이전트를 띄운다.
             경로/모델/역할 파라미터를 검증(커맨드 인젝션 방지)하고 역할별 초기 프롬프트를 주입한다.
             server.py do_POST '/api/launch'에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py do_POST '/api/launch' 88줄 분리(long-tail 라운드). 로직 원본 동일
  (verbatim — 보안 검증 보존). _codex_main_model은 server.py 함수라 파라미터 주입.
"""
from __future__ import annotations

import re
import json
import subprocess
from pathlib import Path


def handle_launch(handler, codex_main_model) -> None:
    """POST /api/launch — {agent, path, yolo, model, role, slot} → 새 cmd 창에서 CLI 실행.
    [보안] target_dir는 실존 디렉터리만 허용 + 셸 메타문자([&|;`$<>!]) 차단(커맨드 인젝션 방지).
      model/role은 화이트리스트 정규식 통과분만 사용. agy 옵션은 antigravity_adapter로 격리.
    """
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))

        agent = data.get('agent')
        target_dir = data.get('path', 'C:\\')
        is_yolo = data.get('yolo', False)
        # 오피스 모드 확장 파라미터: 모델, 역할, 슬롯
        req_model = data.get('model', '')
        req_role = data.get('role', '')
        req_slot = data.get('slot', 0)

        # 경로 검증 — 커맨드 인젝션 방지: 실제 존재하는 디렉터리만 허용
        _resolved_dir = Path(target_dir).resolve()
        if not _resolved_dir.is_dir():
            raise ValueError(f"Invalid directory: {target_dir}")
        _safe_dir = str(_resolved_dir)
        # 셸 메타 문자 차단 (& | ; ` $ 등)
        if re.search(r'[&|;`$<>!]', _safe_dir):
            raise ValueError(f"Directory path contains invalid characters: {_safe_dir}")

        # 모델/역할 파라미터 안전 문자 검증
        if req_model and not re.match(r'^[a-zA-Z0-9\-_.]+$', req_model):
            req_model = ''
        if req_role and not re.match(r'^[a-zA-Z0-9_]+$', req_role):
            req_role = ''

        # 역할별 초기 프롬프트 매핑 — Claude/Antigravity에 --prompt로 역할 지시 전달
        _role_prompts = {
            'developer': '코드 구현과 기능 개발에 집중해줘. 버그 수정, 리팩토링, 새 기능 추가가 주 업무야.',
            'reviewer': '코드 리뷰어로 활동해줘. /vibe-code-review 스킬을 활용하여 품질, 성능, 보안을 검토해.',
            'tester': '테스터로 활동해줘. /vibe-tdd 스킬로 테스트를 작성하고, 회귀 버그를 방지해.',
            'architect': '설계자로 활동해줘. /vibe-brainstorm 으로 아키텍처를 설계하고, 기술 결정을 문서화해.',
        }
        _role_prompt = _role_prompts.get(req_role, '')
        _slot_label = f"T{req_slot}" if req_slot else ""

        if agent == 'claude':
            yolo_flag = " --dangerously-skip-permissions" if is_yolo else ""
            prompt_flag = f' -p "{_role_prompt}"' if _role_prompt else ""
            model_flag = f' --model {req_model}' if req_model else ""
            title = f"[Claude Code] {_slot_label}" if _slot_label else "[Claude Code]"
            cmd = f'start "Claude Code" cmd.exe /k "cd /d "{_safe_dir}" && title {title} && echo Launching Claude Code... && claude{yolo_flag}{model_flag}{prompt_flag}"'
        elif agent in ('gemini', 'antigravity', 'agy'):
            # [2026-05-26] Gemini CLI → Antigravity CLI(`agy`) 전환. 'gemini'는 레거시 alias.
            # [2026-06-11] 옵션 매핑을 antigravity_adapter로 격리 — closed-source CLI
            # 인터페이스 변경 시 어댑터 한 곳만 수정 (직접 agy 문자열 조립 금지)
            from antigravity_adapter import build_interactive_invocation
            title = f"[Antigravity] {_slot_label}" if _slot_label else "[Antigravity]"
            agy_invocation = build_interactive_invocation(yolo=is_yolo, prompt=_role_prompt or None)
            cmd = f'start "{title}" cmd.exe /k "cd /d "{_safe_dir}" && title {title} && echo Launching Antigravity CLI... && {agy_invocation}"'
        elif agent == 'codex':
            yolo_flag = " --dangerously-bypass-approvals-and-sandbox" if is_yolo else ""
            # 요청된 모델 우선, 없으면 config에서 읽기
            model_name = req_model if req_model else codex_main_model()
            if model_name and not re.match(r'^[a-zA-Z0-9\-_/:.]+$', model_name):
                model_name = None
            model_flag = f' --model {model_name}' if model_name else ""
            title = f"[Codex CLI] {_slot_label}" if _slot_label else "[Codex CLI]"
            prompt_arg = f' "{_role_prompt}"' if _role_prompt else ""
            cmd = f'start "{title}" cmd.exe /k "cd /d "{_safe_dir}" && title {title} && echo Launching Codex CLI... && codex{yolo_flag}{model_flag}{prompt_arg}"'
        else:
            cmd = f'start "Terminal" cmd.exe /k "cd /d "{_safe_dir}""'

        subprocess.Popen(cmd, shell=True)

        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({
            "status": "launched", "agent": agent,
            "model": req_model, "role": req_role, "slot": req_slot
        }).encode('utf-8'))
    except Exception as e:
        handler.send_response(500)
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
