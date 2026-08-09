"""
FILE: src/lan_sandbox.py
DESCRIPTION: 원격 claude 실행의 폴더 격리 계층 — 허용 폴더 화이트리스트 검증 +
             모드별 작업공간(copy=사본/direct=원본) 준비 + deny 권한 프로파일 생성.
             LAN 원격실행(api/lan_api.py)과 자율 데몬(infra/heartbeat_daemon.py)이 공용한다.

REVISION HISTORY:
- 2026-07-30 Claude: 신설. 원격실행이 --dangerously-skip-permissions로 수신 PC의 프로젝트
                     루트를 무제한 편집할 수 있던 구멍(3중 게이트는 '누가'만 막고 '무엇을'은
                     무제한이었음)을 막기 위한 격리 계층. heartbeat의 deny 프로파일을 정본으로 흡수.
"""
# [WHY 별도 모듈] lan_api(원격실행)와 heartbeat_daemon(자율실행)이 같은 문제를 각자 풀면
#   프로파일이 갈라져 한쪽만 강화되는 사고가 난다. 여기가 정본이고 양쪽이 import 한다.
# [제약] project_id 비의존 — LAN 계층 전체가 이식성 전제([[feedback-vibe-essence]]).
import json
import os
import shutil
import subprocess
from pathlib import Path

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

# ── 샌드박스 권한 프로파일 ───────────────────────────────────────────────────
# [WHY] 파일로 배포하지 않고 상수→런타임 materialize — .ai_monitor/config/ 신규 디렉토리를
# 만들면 spec datas + CI --add-data 양쪽 갱신이 필요(v3.7.215~218 사고). data_dir은 이미
# 런타임 쓰기 경로라 frozen 모드에서도 안전.
# [제약 — 반드시 알 것] deny 규칙은 Bash 접두 매칭이다. Edit/Write 도구는 이걸로 못 막는다.
# 따라서 direct 모드에서 절대경로 Edit로 cwd 밖을 고치는 것은 프로파일이 아니라
# defaultMode(cwd 밖 자동승인 안 함) 성질에만 의존한다 = 완전 격리 아님.
# 완전 격리가 필요하면 copy 모드를 써야 한다.
SANDBOX_SETTINGS = {
    "permissions": {
        "defaultMode": "acceptEdits",
        "deny": [
            "Bash(git push:*)",
            "Bash(git push)",
            "Bash(gh pr merge:*)",
            "Bash(git merge:*)",
            "Bash(git rebase:*)",
            "Bash(git tag:*)",
            "Bash(git reset --hard:*)",
            "Bash(git worktree:*)",
            "Bash(rm -rf:*)",
            "Bash(rmdir:*)",
            "Bash(Remove-Item:*)",
            "Bash(del:*)",
            "Bash(pyinstaller:*)",
        ],
    },
}

# copy 모드 복사 제외 — 비밀·대용량·재생성 가능 산출물.
# [WHY] 사본 격리의 목적은 '원본 보호'지만, 사본에 .env/키가 실리면 원격 실행자가 비밀을
# 읽어가는 새 구멍이 된다. git 저장소면 worktree(추적 파일만)가 이 문제를 구조적으로 회피한다.
_COPY_EXCLUDE = shutil.ignore_patterns(
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build',
    '.env', '.env.*', '*.pem', '*.key', '*.pfx', 'id_rsa*', '*.log',
)

# copy 모드 용량 상한 — 초과 시 거부(디스크 폭주/수십분 복사 차단).
_COPY_MAX_BYTES = 500 * 1024 * 1024


class SandboxError(Exception):
    """화이트리스트 위반·작업공간 준비 실패. 메시지는 요청자에게 그대로 노출된다."""


def materialize_settings(data_dir: Path, name: str = 'sandbox_settings.json') -> Path:
    """deny 프로파일을 실제 파일로 떨어뜨리고 절대경로를 반환.

    [과거사고] 상대경로로 --settings를 넘기면 claude가 cwd 기준으로 해석해 settings 미발견 시
    즉시 exit 1 (2026-07-17 스모크 실측). 반드시 resolve()된 절대경로를 넘긴다.
    """
    path = (Path(data_dir) / name).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SANDBOX_SETTINGS, indent=2), encoding='utf-8')
    return path


def allowed_dirs(config: dict) -> list[dict]:
    """설정의 허용 폴더 목록을 정규화해 반환. [{path, mode, label, exists}]

    mode: 'copy'(사본에서 작업, 기본) | 'direct'(원본 폴더에서 직접 편집)
    [WHY 기본 copy] 잘못 등록해도 원본이 안 깨지는 쪽이 안전한 기본값.
    """
    out = []
    for item in config.get('lan_exec_allowed_dirs', []) or []:
        if isinstance(item, str):          # 축약 표기 허용: "D:/proj" → copy 모드
            item = {'path': item}
        if not isinstance(item, dict):
            continue
        raw = str(item.get('path', '')).strip()
        if not raw:
            continue
        mode = 'direct' if item.get('mode') == 'direct' else 'copy'
        p = Path(raw)
        out.append({
            'path': raw,
            'mode': mode,
            'label': str(item.get('label', '') or p.name),
            'exists': p.is_dir(),
        })
    return out


def _normcase(p: Path) -> str:
    """Windows 대소문자 무시 비교용 정규화. Path 비교는 대소문자를 구분해 우회를 허용한다."""
    return os.path.normcase(str(p))


def _is_within(child: Path, parent: Path) -> bool:
    """child가 parent 이하인지 — 양쪽 모두 resolve() 완료 상태를 전제한다.

    [보안] 문자열 startswith 단독 비교는 `D:/proj-evil`이 `D:/proj`를 통과시키는 고전 결함이라
    경로 구분자를 붙여 비교한다.
    """
    c, pa = _normcase(child), _normcase(parent)
    if c == pa:
        return True
    return c.startswith(pa.rstrip(os.sep) + os.sep)


def resolve_target(config: dict, requested: str) -> tuple[Path, str]:
    """요청 폴더가 화이트리스트 이하인지 검증하고 (실제경로, 모드)를 반환.

    [보안 — 블로커였던 지점] resolve()를 **비교 전에** 반드시 수행한다. Windows
    junction/symlink는 화이트리스트 안에 있으면서 실제로는 밖(C:/Users/... 등)을 가리킬 수
    있어, 원문 문자열로 비교하면 화이트리스트가 통째로 무력화된다.
    (이 저장소에 junction 관련 사고 이력 있음 — vault sync의 sync_manager.py 제거 건.)

    Raises:
        SandboxError: 화이트리스트 미등록/경로 없음/junction 탈출.
    """
    entries = allowed_dirs(config)
    if not entries:
        raise SandboxError('이 PC에 허용된 작업 폴더가 없습니다 (LAN 패널에서 폴더를 등록하세요)')

    raw = (requested or '').strip()
    if not raw:
        raise SandboxError('작업 폴더를 지정해야 합니다')

    try:
        target = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as e:
        raise SandboxError(f'경로를 찾을 수 없습니다: {raw}') from e
    if not target.is_dir():
        raise SandboxError(f'폴더가 아닙니다: {raw}')

    for ent in entries:
        try:
            allowed = Path(ent['path']).resolve(strict=True)
        except (OSError, RuntimeError):
            continue        # 등록됐지만 지금 없는 폴더(외장/네트워크 드라이브) — 건너뜀
        if _is_within(target, allowed):
            return target, ent['mode']

    raise SandboxError(f'허용되지 않은 폴더입니다: {target}')


class Workspace:
    """준비된 작업공간. cwd에서 claude를 실행하고, 끝나면 finish()로 정리/변경목록을 얻는다.

    [불변식] is_copy=True인 경우에만 cwd != origin. direct 모드는 cwd == origin이라
    cleanup이 원본을 지우면 안 된다 — finish()가 is_copy로 분기하는 이유.
    """

    def __init__(self, origin: Path, cwd: Path, mode: str, kind: str):
        self.origin = origin
        self.cwd = cwd
        self.mode = mode
        self.kind = kind          # 'direct' | 'worktree' | 'copy'

    @property
    def is_copy(self) -> bool:
        return self.kind in ('worktree', 'copy')

    def changed_files(self) -> list[str]:
        """작업공간에서 변경/추가된 파일 목록(상대경로)."""
        if self.kind == 'worktree':
            ok, out = _git(self.cwd, 'status', '--porcelain')
            if not ok:
                return []
            return [ln[3:].strip() for ln in out.splitlines() if ln.strip()]
        if self.kind == 'copy':
            return _diff_by_stat(self.origin, self.cwd)
        return []                 # direct — 원본을 직접 고쳤으므로 git이 이미 알고 있음

    def finish(self, keep: bool = True) -> list[str]:
        """변경목록을 뽑고 사본을 정리한다. keep=True면 사본을 남겨 사람이 직접 확인 가능.

        [WHY keep 기본 True] 사본을 즉시 지우면 원격 작업 결과가 통째로 사라진다. Phase A는
        '자동 반영' 없이 '사람이 보고 반영'이 계약이므로 산출물을 남기는 쪽이 기본.
        """
        changed = self.changed_files()
        if not keep and self.is_copy:
            self.cleanup()
        return changed

    def cleanup(self) -> None:
        """사본 작업공간 제거. direct 모드에서는 아무것도 하지 않는다(원본 보호)."""
        if not self.is_copy:
            return
        if self.kind == 'worktree':
            _git(self.origin, 'worktree', 'remove', '--force', str(self.cwd))
            if self.cwd.exists():
                shutil.rmtree(self.cwd, ignore_errors=True)
        else:
            shutil.rmtree(self.cwd, ignore_errors=True)


def _git(cwd: Path, *args: str) -> tuple[bool, str]:
    """git 호출 — heartbeat의 _git과 동일 계약(성공여부, 출력). 60초 상한.

    [🔴 2026-08-09] proc.run 필수 — subprocess.run 직호출은 호출마다 검은 cmd 창을 띄운다
      (CREATE_NO_WINDOW 는 자식에게 상속되지 않는다). 원격 실행은 한 번에 여러 번 부른다.
    """
    try:
        r = proc.run(['git', '-C', str(cwd), *args], capture_output=True,
                     text=True, encoding='utf-8', errors='replace', timeout=60)
        return r.returncode == 0, (r.stdout or '') + (r.stderr or '')
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _is_git_repo(path: Path) -> bool:
    ok, out = _git(path, 'rev-parse', '--is-inside-work-tree')
    return ok and out.strip().startswith('true')


def _dir_size(path: Path) -> int:
    """복사 전 용량 확인 — 제외 대상은 세지 않는다(node_modules가 대부분을 차지)."""
    total = 0
    skip = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
        if total > _COPY_MAX_BYTES:
            return total          # 조기 반환 — 거부가 확정된 뒤 계속 셀 이유 없음
    return total


def _diff_by_stat(origin: Path, copy: Path) -> list[str]:
    """copy 모드 변경 감지 — (크기, mtime) 비교. git이 없는 폴더용 폴백.

    [제약] 내용이 같은 크기로 바뀌고 mtime까지 보존된 경우는 놓친다. 해시 전수 비교는
    대형 폴더에서 비용이 커서, '사람이 검토한다'는 Phase A 계약 하에 stat 비교로 충분하다고 판단.
    """
    changed: list[str] = []
    skip = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}
    for root, dirs, files in os.walk(copy):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            cp = Path(root) / f
            rel = cp.relative_to(copy)
            op = origin / rel
            try:
                if not op.exists():
                    changed.append(str(rel).replace('\\', '/'))
                    continue
                cs, os_ = cp.stat(), op.stat()
                if cs.st_size != os_.st_size or int(cs.st_mtime) != int(os_.st_mtime):
                    changed.append(str(rel).replace('\\', '/'))
            except OSError:
                pass
    return sorted(changed)


def prepare_workspace(target: Path, mode: str, exec_id: str, data_dir: Path) -> Workspace:
    """모드에 맞는 작업공간을 준비한다.

    - direct: 원본 폴더 그대로 (사용자가 명시적으로 등록한 경우만)
    - copy + git 저장소: `git worktree add --detach` — 추적 파일만 나타나므로 .env/키가
      구조적으로 배제되고 복사 비용도 거의 없다(하드링크). copy 모드의 우선 경로.
    - copy + 비-git: copytree(제외 패턴 + 용량 상한)

    [불변식] 작업공간은 항상 data_dir/lan_workspaces/<exec_id> 이하에 만든다. 원본 안에
    만들면 원격 작업이 원본 트리를 오염시키고 git status를 더럽힌다.
    """
    if mode == 'direct':
        return Workspace(target, target, mode, 'direct')

    base = (Path(data_dir) / 'lan_workspaces').resolve()
    base.mkdir(parents=True, exist_ok=True)
    wt = base / exec_id
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)

    if _is_git_repo(target):
        ok, out = _git(target, 'worktree', 'add', '--detach', str(wt), 'HEAD')
        if ok:
            return Workspace(target, wt, mode, 'worktree')
        # worktree 실패(얕은 클론/잠금 등) → copytree 폴백. 실패 원인은 요청자에게 안 숨긴다.
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)

    size = _dir_size(target)
    if size > _COPY_MAX_BYTES:
        raise SandboxError(
            f'폴더가 너무 큽니다 ({size // (1024 * 1024)}MB > {_COPY_MAX_BYTES // (1024 * 1024)}MB). '
            'git 저장소면 worktree로 즉시 처리되니 git init을 권합니다.')
    try:
        shutil.copytree(target, wt, ignore=_COPY_EXCLUDE, symlinks=False)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(wt, ignore_errors=True)
        raise SandboxError(f'작업공간 복사 실패: {e}') from e
    return Workspace(target, wt, mode, 'copy')
