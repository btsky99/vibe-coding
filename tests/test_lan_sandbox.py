"""
FILE: tests/test_lan_sandbox.py
DESCRIPTION: LAN 원격실행 폴더 격리 회귀 테스트 — 화이트리스트 검증(우회 차단) + 모드별
             작업공간 준비 + deny 프로파일. 원격실행은 간접 RCE라 여기가 최후 방어선이다.

REVISION HISTORY:
- 2026-07-30 Claude: 신규 — Phase A. yolo+프로젝트루트 무제한 실행 구멍을 막은 격리 계층 검증.
"""

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from src.lan_sandbox import (SANDBOX_SETTINGS, SandboxError, allowed_dirs,
                             materialize_settings, prepare_workspace, resolve_target)


# ── 화이트리스트 검증 ────────────────────────────────────────────────────────

def test_no_allowed_dirs_rejects_everything(tmp_path):
    """폴더를 등록하지 않은 PC는 모든 요청을 거부한다(기본이 '닫힘')."""
    with pytest.raises(SandboxError, match='허용된 작업 폴더가 없'):
        resolve_target({}, str(tmp_path))


def test_empty_target_is_rejected(tmp_path):
    """폴더 미지정 요청은 거부 — '지정 안 하면 프로젝트 루트'였던 과거 동작 재발 방지."""
    cfg = {'lan_exec_allowed_dirs': [{'path': str(tmp_path)}]}
    with pytest.raises(SandboxError):
        resolve_target(cfg, '')


def test_unlisted_dir_is_rejected(tmp_path):
    allowed = tmp_path / 'ok'
    other = tmp_path / 'secret'
    allowed.mkdir()
    other.mkdir()
    cfg = {'lan_exec_allowed_dirs': [{'path': str(allowed)}]}
    with pytest.raises(SandboxError, match='허용되지 않은 폴더'):
        resolve_target(cfg, str(other))


def test_subdirectory_of_allowed_is_accepted(tmp_path):
    allowed = tmp_path / 'proj'
    sub = allowed / 'src' / 'deep'
    sub.mkdir(parents=True)
    cfg = {'lan_exec_allowed_dirs': [{'path': str(allowed)}]}
    target, mode = resolve_target(cfg, str(sub))
    assert target == sub.resolve()
    assert mode == 'copy'          # 기본 모드는 사본


def test_sibling_prefix_collision_is_rejected(tmp_path):
    """`D:/proj-evil`이 `D:/proj` 화이트리스트를 통과하던 고전 startswith 결함 차단."""
    allowed = tmp_path / 'proj'
    evil = tmp_path / 'proj-evil'
    allowed.mkdir()
    evil.mkdir()
    cfg = {'lan_exec_allowed_dirs': [{'path': str(allowed)}]}
    with pytest.raises(SandboxError, match='허용되지 않은 폴더'):
        resolve_target(cfg, str(evil))


def test_traversal_out_of_allowed_is_rejected(tmp_path):
    """`allowed/../secret` 형태 탈출 — resolve() 후 비교라 차단된다."""
    allowed = tmp_path / 'ok'
    secret = tmp_path / 'secret'
    allowed.mkdir()
    secret.mkdir()
    cfg = {'lan_exec_allowed_dirs': [{'path': str(allowed)}]}
    with pytest.raises(SandboxError):
        resolve_target(cfg, str(allowed / '..' / 'secret'))


def test_symlink_escape_is_rejected(tmp_path):
    """[블로커였던 지점] 화이트리스트 안의 링크가 밖을 가리키면 거부.

    Windows에서 심볼릭 링크 생성은 권한이 필요해 실패하면 스킵한다 — 검증 자체가
    플랫폼 권한에 묶이면 CI가 조용히 통과하므로 스킵 사유를 명시한다.
    """
    allowed = tmp_path / 'ok'
    outside = tmp_path / 'outside'
    allowed.mkdir()
    outside.mkdir()
    link = allowed / 'escape'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('심볼릭 링크 생성 권한 없음 (Windows 개발자 모드/관리자 필요)')
    cfg = {'lan_exec_allowed_dirs': [{'path': str(allowed)}]}
    with pytest.raises(SandboxError, match='허용되지 않은 폴더'):
        resolve_target(cfg, str(link))


def test_direct_mode_is_opt_in(tmp_path):
    """mode를 명시하지 않으면 항상 copy — 실수로 원본이 열리지 않아야 한다."""
    d = tmp_path / 'p'
    d.mkdir()
    assert resolve_target({'lan_exec_allowed_dirs': [{'path': str(d)}]}, str(d))[1] == 'copy'
    assert resolve_target({'lan_exec_allowed_dirs': [{'path': str(d), 'mode': 'nonsense'}]},
                          str(d))[1] == 'copy'
    assert resolve_target({'lan_exec_allowed_dirs': [{'path': str(d), 'mode': 'direct'}]},
                          str(d))[1] == 'direct'


def test_allowed_dirs_accepts_shorthand_string(tmp_path):
    d = tmp_path / 'p'
    d.mkdir()
    entries = allowed_dirs({'lan_exec_allowed_dirs': [str(d)]})
    assert entries[0]['mode'] == 'copy'
    assert entries[0]['exists'] is True


# ── 작업공간 준비 ────────────────────────────────────────────────────────────

def test_direct_mode_uses_origin(tmp_path):
    origin = tmp_path / 'proj'
    origin.mkdir()
    ws = prepare_workspace(origin, 'direct', 'exec1', tmp_path / 'dd')
    assert ws.cwd == origin
    assert ws.is_copy is False
    ws.cleanup()                       # direct는 no-op — 원본이 남아야 한다
    assert origin.exists()


def test_copy_mode_isolates_origin(tmp_path):
    """사본 모드: cwd가 원본 밖이고, 원본 파일을 고쳐도 원본은 안 바뀐다."""
    origin = tmp_path / 'proj'
    origin.mkdir()
    (origin / 'a.txt').write_text('원본', encoding='utf-8')
    ws = prepare_workspace(origin, 'copy', 'exec2', tmp_path / 'dd')
    assert ws.is_copy is True
    assert ws.cwd != origin
    assert (ws.cwd / 'a.txt').read_text(encoding='utf-8') == '원본'

    (ws.cwd / 'a.txt').write_text('원격이 고침', encoding='utf-8')
    assert (origin / 'a.txt').read_text(encoding='utf-8') == '원본'
    assert 'a.txt' in ws.changed_files()


def test_copy_mode_excludes_secrets(tmp_path):
    """.env·키파일이 사본에 실리면 원격 실행자가 비밀을 읽는 새 구멍이 된다."""
    origin = tmp_path / 'proj'
    origin.mkdir()
    (origin / '.env').write_text('TOKEN=secret', encoding='utf-8')
    (origin / 'deploy.key').write_text('PRIVATE', encoding='utf-8')
    (origin / 'main.py').write_text('print(1)', encoding='utf-8')
    ws = prepare_workspace(origin, 'copy', 'exec3', tmp_path / 'dd')
    assert (ws.cwd / 'main.py').exists()
    assert not (ws.cwd / '.env').exists()
    assert not (ws.cwd / 'deploy.key').exists()


def test_workspace_lives_under_data_dir(tmp_path):
    """사본을 원본 안에 만들면 원격 작업이 원본 트리를 오염시킨다."""
    origin = tmp_path / 'proj'
    origin.mkdir()
    dd = tmp_path / 'dd'
    ws = prepare_workspace(origin, 'copy', 'exec4', dd)
    assert str(ws.cwd).startswith(str((dd / 'lan_workspaces').resolve()))


def test_cleanup_removes_copy_only(tmp_path):
    origin = tmp_path / 'proj'
    origin.mkdir()
    (origin / 'keep.txt').write_text('x', encoding='utf-8')
    ws = prepare_workspace(origin, 'copy', 'exec5', tmp_path / 'dd')
    ws.cleanup()
    assert not ws.cwd.exists()
    assert (origin / 'keep.txt').exists()


# ── deny 프로파일 ────────────────────────────────────────────────────────────

def test_settings_profile_is_absolute_and_denies_dangerous_commands(tmp_path):
    """[과거사고] 상대경로 --settings는 claude가 cwd 기준 해석 후 미발견 시 exit 1."""
    path = materialize_settings(tmp_path)
    assert path.is_absolute()
    written = json.loads(path.read_text(encoding='utf-8'))
    assert written == SANDBOX_SETTINGS
    deny = ' '.join(written['permissions']['deny'])
    for danger in ('git push', 'rm -rf', 'Remove-Item', 'git reset --hard'):
        assert danger in deny


def test_profile_never_grants_bypass():
    """defaultMode가 bypassPermissions로 바뀌면 격리가 무의미해진다 — 회귀 고정."""
    assert SANDBOX_SETTINGS['permissions']['defaultMode'] != 'bypassPermissions'
