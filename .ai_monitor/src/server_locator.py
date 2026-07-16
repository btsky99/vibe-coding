# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/server_locator.py
# 📝 설명: 9000번대 바이브 서버 포트 공용 탐색기 — /api/project-info 슬러그 대조로
#          멀티 프로젝트 동시 가동 시 자기 프로젝트 서버만 채택한다.
# 🕒 변경 이력:
# [2026-07-16] Claude — 신설. recall_client 수정(ab0f1a3)의 대조 로직을 공용화 —
#   hook_bridge/hive_hook(stage)/agent_shell/terminal_agent에 남아있던
#   '첫 응답/9000 고정' 패턴 청산 (사고 장부 beccc5662a4961bf의 잔여분).
#   [불변식] 어떤 실패에서도 예외를 밖으로 던지지 않는다 — 호출자 전원이 훅/런처.
# ────────────────────────────────────────────────────────────────────────────
import json
import os
from pathlib import Path
import urllib.request as _req
from concurrent.futures import ThreadPoolExecutor

# [WHY] 'localhost'는 Windows에서 ::1→127.0.0.1 이중 시도로 닫힌 포트당 ~0.8초 소모
# (2026-07-16 실측 — 순차 대조 스캔 6.6초로 훅 상한 2초 초과). 127.0.0.1 고정 +
# 병렬 프로브로 전체 스캔 0.3~0.6초.
HOST = '127.0.0.1'


def probe_port(port: int) -> tuple[int, str] | None:
    """포트 생존 확인 + 그 서버의 활성 project_id 슬러그 반환. 불통이면 None."""
    try:
        _req.urlopen(f'http://{HOST}:{port}/api/hive/health', timeout=0.3)
    except Exception:
        return None
    try:
        with _req.urlopen(f'http://{HOST}:{port}/api/project-info', timeout=0.3) as r:
            info = json.loads(r.read().decode('utf-8'))
        return port, str(info.get('project_id') or '')
    except Exception:
        return port, ''  # 구버전 서버(project-info 없음) — 생존만 보고


def find_server_port(project_id: str = '', start: int = 9000,
                     count: int = 20) -> int | None:
    """응답하는 서버 포트 탐색. project_id 전달 시 그 프로젝트의 서버만 채택.

    [과거사고 2026-07-16] 멀티 프로젝트 동시 가동(9000=ons, 9010=vibe-coding)에서
    '첫 응답 포트' 채택이 타 프로젝트 서버(별도 PG DB)에 붙어 회상 오주입 + 계측
    오기록 + 파이프라인 stage 오표시. 서버별 DB가 다르므로 요청 파라미터로는
    해결 불가 — 포트 선택 단계에서 대조해야 한다.
    [하위호환] project_id=''이면 기존 '첫 응답' 동작 (슬러그 산출 실패 환경).
    매칭 실패 시 None — 호출자가 '자기 서버 없음'으로 처리 (타 서버 오염 금지).
    """
    env_port = os.getenv('VIBE_SERVER_PORT')
    if env_port:
        try:
            return int(env_port)  # 서버가 자식에게 주입한 값 — 자기 프로젝트 보장
        except ValueError:
            pass
    with ThreadPoolExecutor(max_workers=count) as ex:
        alive = [r for r in ex.map(probe_port, range(start, start + count)) if r]
    if project_id:
        for port, pid in alive:
            if pid == project_id:
                return port
        return None
    return alive[0][0] if alive else None


def slug_for_cwd(cwd: str = '') -> str:
    """호출 프로세스 cwd의 프로젝트 슬러그 — 산출 불가 환경이면 '' (하위호환).

    [제약] infra.project_context 임포트는 sys.path에 .ai_monitor가 있어야 함 —
    호출자(scripts/*)가 각자 보장. 실패 시 ''을 반환해 find_server_port가
    기존 첫 응답 동작으로 폴백한다.
    """
    try:
        from infra.project_context import slugify, find_project_root_marker
        p = Path(cwd or os.getcwd())
        return slugify(find_project_root_marker(p) or p)
    except Exception:
        return ''
