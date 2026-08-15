"""
FILE: migrate_vault_pretty_names.py
DESCRIPTION: 볼트 노트 파일명을 옛 규칙(`{note_id} {제목}`)에서 새 규칙(제목만)으로 1회 개명한다.
  로컬 볼트는 export가 스스로 정리하지만 GDrive 미러는 비파괴라 옛 이름이 유령으로 남는다 —
  이 스크립트가 그 유령을 없앤다.

REVISION HISTORY:
- 2026-08-15 Claude: 파일명에서 note_id 접두 제거(정렬이 해시순이라 무작위였음) — 1회 마이그레이션
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / '.ai_monitor'))

# [WHY import 방식] zettel_sync 는 패키지가 아니라 스크립트다. 새 이름 규칙(_safe_filename /
#   build_name_registry)을 여기서 다시 구현하면 두 벌이 갈라져 언젠가 어긋난다 —
#   반드시 정본 모듈을 그대로 불러 쓴다.
_spec = importlib.util.spec_from_file_location('zettel_sync', str(_SCRIPT_DIR / 'zettel_sync.py'))
_zs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_zs)

import re  # noqa: E402  (zettel_sync 로드 후에 둬야 import 순서 경고가 안 뜬다)


def _old_filename(note_id: str, title: str) -> str:
    """v3.7 까지 쓰던 파일명 규칙을 그대로 재현한다 — 지울 대상을 정확히 짚기 위한 것.

    [불변식] 이 함수는 **과거를 복원**한다. 절대 '개선'하지 말 것 — 규칙이 어긋나는 순간
      옛 파일을 못 찾아 유령이 남거나, 엉뚱한 파일을 지운다.
    """
    safe_id = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', note_id).replace('..', '')
    if not safe_id:
        safe_id = 'unnamed'
    if title:
        safe_title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', title)
        safe_title = safe_title.replace('..', '').strip()[:60]
        return f'{safe_id} {safe_title}' if safe_title else safe_id
    return safe_id


def _note_folder(vault: Path, note: dict) -> Path:
    if note.get('archived'):
        return vault / '_보관'
    return vault / _zs._NOTE_TYPE_FOLDER.get(note.get('note_type', 'fleeting'), '작업기록')


def _candidate_vaults(explicit: str | None) -> list[Path]:
    """개명 대상 볼트 목록. 로컬 볼트 + GDrive 허브를 자동 탐지한다."""
    if explicit:
        return [Path(explicit)]

    found: list[Path] = []
    appdata = os.environ.get('APPDATA')
    if appdata:
        local = Path(appdata) / 'VibeCoding' / 'vault'
        if local.is_dir():
            found.append(local)

    # GDrive 는 PC마다 드라이브 레터와 언어가 달라 고정 경로를 쓸 수 없다(daemons.py 와 같은 이유).
    import string
    for letter in string.ascii_uppercase:
        for drive_name in ('내 드라이브', 'My Drive'):
            cand = Path(f'{letter}:/') / drive_name / 'obsidian' / 'hive-zettel'
            if cand.is_dir():
                found.append(cand)
    return found


def migrate(vault: Path, notes: list[dict], apply: bool) -> dict:
    """옛 이름 → 새 이름. delete 가 아니라 rename 이다.

    [WHY rename] GDrive 는 삭제+재업로드보다 개명이 압도적으로 싸고, 개명하면 본문이 남아
      다음 미러가 내용만 갱신한다. 삭제로 처리하면 2000여 파일이 통째로 재업로드된다.
    [제약] 옵시디언이 볼트를 열어둔 채면 Windows 파일 잠금으로 개명이 실패할 수 있다 —
      실패는 건너뛰고 집계만 한다(다음 실행에서 재시도되므로 중단시킬 이유가 없다).
    """
    stat = {'renamed': 0, 'already': 0, 'missing': 0, 'collision': 0, 'failed': 0}
    for note in notes:
        nid = str(note.get('id', ''))
        if not nid:
            continue
        folder = _note_folder(vault, note)
        old = folder / f"{_old_filename(nid, note.get('title', '') or '')}.md"
        new = folder / f"{_zs._safe_filename(nid, note.get('title', '') or '')}.md"

        if old == new:
            stat['already'] += 1
            continue
        if not old.exists():
            stat['missing'] += 1
            continue
        if new.exists():
            # 새 이름이 이미 있다 = 이전 실행이 여기까지 왔다는 뜻. 옛 파일은 잔재이므로 제거.
            stat['collision'] += 1
            if apply:
                try:
                    old.unlink()
                except OSError:
                    stat['failed'] += 1
            continue

        stat['renamed'] += 1
        if apply:
            try:
                old.rename(new)
            except OSError as exc:
                stat['renamed'] -= 1
                stat['failed'] += 1
                print(f'  개명 실패(건너뜀): {old.name} — {exc}')
    return stat


def main() -> int:
    parser = argparse.ArgumentParser(
        description='볼트 노트 파일명에서 note_id 접두를 제거한다 (1회 마이그레이션)')
    parser.add_argument('--project', default='D--vibe-coding', help="프로젝트 ID (기본: D--vibe-coding)")
    parser.add_argument('--vault', default=None, help='특정 볼트만 처리 (기본: 로컬+GDrive 자동 탐지)')
    parser.add_argument('--apply', action='store_true', help='실제로 개명 (기본은 미리보기)')
    args = parser.parse_args()

    from src.pg_store import query_rows
    notes = query_rows(
        'SELECT id, title, note_type, archived FROM zettel_notes WHERE project_id = %s',
        (args.project,),
    )
    if not notes:
        print(f'[migrate] 프로젝트 {args.project} 노트가 없다 — 중단')
        return 1

    _zs.build_name_registry(notes)
    print(f'[migrate] 노트 {len(notes)}건 / 모드: {"실행" if args.apply else "미리보기"}\n')

    vaults = _candidate_vaults(args.vault)
    if not vaults:
        print('[migrate] 볼트를 찾지 못했다')
        return 1

    for vault in vaults:
        stat = migrate(vault, notes, args.apply)
        print(f'  {vault}')
        print(f'    개명 {stat["renamed"]} · 이미 새이름 {stat["already"]} · '
              f'볼트에 없음 {stat["missing"]} · 잔재정리 {stat["collision"]} · 실패 {stat["failed"]}')

    if not args.apply:
        print('\n실제로 바꾸려면 --apply 를 붙여 다시 실행.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
