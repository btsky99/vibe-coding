"""
FILE: api/daemons_api.py
DESCRIPTION: 백그라운드 데몬 on/off API — infra/daemons.py의 DAEMON_TOGGLES 레지스트리를
             UI에 노출하고, config.json의 'daemons' 하위 dict를 부분 병합 저장한다.

REVISION HISTORY:
- 2026-08-01 Claude: 신규 — 상시 데몬 6종이 ~211MB/CPU를 점유하는데 UI 토글이 없어
  저사양 PC에서 손댈 방법이 config.json 직접 편집뿐이었음. 기존 /api/config/update는
  top-level 병합이라 daemons 하위 키를 부분 갱신하지 못한다(통째 덮어씀) → 전용 핸들러.
"""
from __future__ import annotations

import json
from pathlib import Path

from infra import daemons


def _respond(handler, payload: dict, code: int = 200) -> None:
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def handle_get(handler, config_file: Path) -> None:
    """GET /api/daemons — 레지스트리 + 현재 설정 + 실행 중 여부."""
    try:
        _respond(handler, {'status': 'success', 'daemons': daemons.daemon_status(config_file)})
    except Exception as e:
        _respond(handler, {'status': 'error', 'message': str(e)})


def handle_update(handler, config_file: Path) -> None:
    """POST /api/daemons — {"key": bool, ...} 부분 병합.

    [불변식] 레지스트리에 없는 키는 저장하지 않는다 — 오타 키가 config에 쌓이면
      start_all_daemons가 매 부팅 "알 수 없는 데몬 키" 경고를 뱉고, 사용자는 껐다고
      믿는 항목이 계속 뜨는 것을 보게 된다.
    [WHY True도 명시 저장] 키를 지우는 대신 true로 남긴다 — 사용자가 의도적으로 켠 것과
      한 번도 건드리지 않은 것을 config만 봐도 구분할 수 있다(기본값 변경 시 안전).
    """
    try:
        length = int(handler.headers.get('Content-Length') or 0)
        data = json.loads(handler.rfile.read(length).decode('utf-8')) if length else {}
        if not isinstance(data, dict):
            _respond(handler, {'status': 'error', 'message': '본문은 {키: bool} 객체여야 합니다'})
            return

        unknown = [k for k in data if k not in daemons.DAEMON_TOGGLES]
        if unknown:
            _respond(handler, {'status': 'error',
                               'message': f"알 수 없는 데몬 키: {', '.join(unknown)}"})
            return

        config = {}
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                config = {}
        toggles = config.get('daemons')
        if not isinstance(toggles, dict):
            toggles = {}
        toggles.update({k: bool(v) for k, v in data.items()})
        config['daemons'] = toggles
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')

        _respond(handler, {'status': 'success', 'daemons': toggles,
                           'note': '앱을 재시작해야 적용됩니다'})
    except Exception as e:
        _respond(handler, {'status': 'error', 'message': str(e)})
