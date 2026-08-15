"""
FILE: api/wiki_api.py
DESCRIPTION: LLM 위키 상태 조회 + 초기화 API.
             GET  /api/wiki/status — 페이지 수·인덱스 수·허브 경로
             POST /api/wiki/reset  — 위키를 비우고 원료(코드 주석)에서 다시 만든다

REVISION HISTORY:
- 2026-08-15 Claude: 신설 — W10. "기존 거 다 지우고 다시 시작"을 설치본에서도 할 수
  있어야 한다는 사용자 요청. 개발 PC 전용 스크립트로 두면 설치본 사용자는 방법이 없다.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# wiki_build 는 scripts/ 에 있어 패키지 import 가 안 된다 — 경로로 로드한다.
# [제약] frozen(EXE) 에서는 프로젝트 체크아웃의 scripts/ 를 봐야 한다. tools_api 가
#   같은 문제를 _find_install_script 로 풀고 있으니 규칙이 바뀌면 양쪽을 같이 고칠 것.
_BUILD_SCRIPT = 'wiki_build.py'


def _json(handler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(body)


def _load_build(scripts_dir: Path):
    path = scripts_dir / _BUILD_SCRIPT
    if not path.exists():
        return None
    import importlib.util as ilu
    spec = ilu.spec_from_file_location('wiki_build', str(path))
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _counts(wiki_root: Path, project_id: str) -> dict:
    from src.pg_base import query_rows
    pages = sum(1 for p in wiki_root.rglob('*.md')
                if p.name not in ('INDEX.md', '_placeholder.md')) if wiki_root.is_dir() else 0
    rows = query_rows(
        "SELECT count(*) c FROM zettel_notes "
        "WHERE author='wiki_index' AND archived=false AND project_id=%s", (project_id,))
    indexed = int(rows[0]['c']) if rows else 0
    embedded = query_rows(
        "SELECT count(*) c FROM zettel_notes WHERE author='wiki_index' "
        "AND archived=false AND embedding IS NOT NULL AND project_id=%s", (project_id,))
    return {
        'pages': pages,
        'indexed': indexed,
        'embedded': int(embedded[0]['c']) if embedded else 0,
    }


def handle_get(handler, path: str, project_root: Path, project_id: str) -> bool:
    if path != '/api/wiki/status':
        return False
    try:
        from src import wiki_index
        wiki_root = project_root / 'wiki'
        hub = wiki_index.detect_gdrive_hub()
        payload = {
            'status': 'success',
            'wiki_path': str(wiki_root),
            'exists': wiki_root.is_dir(),
            'hub': str(hub / project_root.name) if hub else None,
            **_counts(wiki_root, project_id),
        }
        _json(handler, payload)
    except Exception as exc:
        _json(handler, {'status': 'error', 'message': str(exc)}, 500)
    return True


def handle_post(handler, path: str, data: dict | None,
                project_root: Path, project_id: str, scripts_dir: Path) -> bool:
    # 증분 갱신 — 데몬이 10분마다 하는 일을 사람이 지금 시키는 것.
    # [WHY reset 과 따로 두나] reset 은 페이지를 지우고 다시 만든다(손으로 덧붙인 내용이
    #   날아간다). 대부분의 경우 필요한 건 '방금 고친 주석을 지금 반영'뿐이다 —
    #   그걸 하려고 파괴적 버튼을 누르게 만들면 언젠가 사고가 난다.
    if path == '/api/wiki/sync':
        try:
            from src import wiki_index
            wiki_root = project_root / 'wiki'
            mod = _load_build(scripts_dir)
            build_stat = mod.build() if mod else {'pages': 0}
            sync_stat = wiki_index.sync(wiki_root, project_id)
            mirror = wiki_index.mirror_to_hub(wiki_root, project_root.name)
            _json(handler, {
                'status': 'success',
                'message': (f"{build_stat['pages']}장 · 새 항목 {sync_stat['created']} · "
                            f"변경 {sync_stat['updated']} · 정리 {sync_stat['archived']}"),
                'build': build_stat, 'sync': sync_stat, 'mirror': mirror,
                **_counts(wiki_root, project_id),
            })
        except Exception as exc:
            _json(handler, {'status': 'error', 'message': str(exc)}, 500)
        return True

    if path != '/api/wiki/reset':
        return False

    # [WHY 명시 확인을 요구하나] 위키 페이지를 통째로 지운다. 사람이 옵시디언에서 손으로
    #   덧붙인 문단도 함께 사라진다(원료에 없는 내용은 복원되지 않는다). 실수로 눌린
    #   요청 하나에 그게 날아가면 안 된다.
    if not (data or {}).get('confirm'):
        _json(handler, {
            'status': 'need_confirm',
            'message': '위키를 비우고 코드 주석에서 다시 만듭니다. confirm=true 로 다시 요청하세요.',
        }, 400)
        return True

    try:
        from src import wiki_index
        wiki_root = project_root / 'wiki'
        before = _counts(wiki_root, project_id)

        # 1) 생성물 디렉토리만 비운다.
        # [🔴 INDEX.md 와 .gitignore 는 남긴다] 둘은 사람이 손으로 쓴 파일이다.
        #   INDEX 는 안내문이 들어 있고 빌드가 목차 구간만 다시 채운다.
        removed_dirs = []
        for name in ('개념', '시스템', '함정', '결정'):
            d = wiki_root / name
            if d.is_dir():
                shutil.rmtree(d)
                d.mkdir(parents=True, exist_ok=True)
                removed_dirs.append(name)

        # 2) 인덱스 노트 삭제. 아카이브가 아니라 삭제다 — 재생성되면 같은 id 로
        #    되살아나므로 남겨둘 이유가 없고, 남기면 '초기화'라는 말이 거짓이 된다.
        from src import zettelkasten as zk
        from src.pg_base import query_rows
        for r in query_rows("SELECT id FROM zettel_notes WHERE author='wiki_index'"):
            zk.delete_note(r['id'])

        # 3) 원료에서 재생성
        mod = _load_build(scripts_dir)
        if mod is None:
            _json(handler, {'status': 'error',
                            'message': f'{_BUILD_SCRIPT} 를 찾지 못했습니다: {scripts_dir}'}, 500)
            return True
        build_stat = mod.build()

        # 4) 재인덱싱 (임베딩은 백필 데몬이 이어서 채운다)
        sync_stat = wiki_index.sync(wiki_root, project_id)

        _json(handler, {
            'status': 'success',
            'message': f"위키를 다시 만들었습니다 — {build_stat['pages']}장 / 인덱스 {sync_stat['created']}건",
            'before': before,
            'after': _counts(wiki_root, project_id),
            'cleared': removed_dirs,
            'build': build_stat,
            'sync': sync_stat,
        })
    except Exception as exc:
        _json(handler, {'status': 'error', 'message': str(exc)}, 500)
    return True
