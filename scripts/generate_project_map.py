"""
FILE: scripts/generate_project_map.py
DESCRIPTION: PROJECT_MAP.md 자동 생성 스크립트.
             실제 파일 구조를 스캔하여 PROJECT_MAP.md를 자동 갱신합니다.
             문서 드리프트를 방지하기 위해 파일 시스템을 진실의 원천으로 사용합니다.

REVISION HISTORY:
- 2026-06-07 Claude: Claude 통합 섹션(.claude/skills/, .claude/agents/) 자동 생성 추가.
  [과거사고] 2026-06-07 수동 추가한 Claude 통합 섹션이 자동 재생성 시 즉시 사라지는 사고 발생 — 자동 스크립트에 누락된 섹션은 무조건 사라짐을 입증.
- 2026-04-15 Claude: stdout UTF-8 강제 — Windows CP949 환경에서 ✅ 이모지 print
  실패로 인해 17일째 자동 갱신 안 되던 근본 원인 수정
- 2026-03-22 Claude: 최초 생성 — 5축 모듈 맵 기반 자동 생성
"""

import os
import sys
import time
from pathlib import Path

# Windows CP949 콘솔에서도 이모지 출력 가능하도록 stdout/stderr UTF-8 강제.
# 이 한 줄이 빠져있어 매번 print의 ✅ 이모지에서 UnicodeEncodeError로 죽었음.
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


# ── 콘솔 숨김 subprocess (규칙: 인라인 CREATE_NO_WINDOW 금지, infra/proc 이 단일 소스) ──
# [WHY try/except] 이 스크립트는 다른 프로젝트에 복사돼 단독 실행될 수 있다(_resolve_root ②).
#   그 환경엔 infra 패키지가 없으므로, import 실패를 기능 중단으로 만들면 맵 생성 자체가
#   죽는다. 이식 환경에서는 같은 규약(creationflags 기본 주입)의 최소 대체를 쓴다.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.ai_monitor'))
    from infra.proc import run as _proc_run
except ImportError:
    import subprocess as _sp

    _NO_WINDOW = getattr(_sp, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0

    def _proc_run(cmd, **kwargs):
        kwargs.setdefault('creationflags', _NO_WINDOW)
        return _sp.run(cmd, **kwargs)


# ── 프로젝트 루트 ─────────────────────────────────────────────────────────
def _resolve_root() -> Path:
    """맵을 생성할 대상 프로젝트 루트를 결정한다.

    [WHY 단순 __file__ 기준이 아닌가] 이 스크립트는 세 방식으로 실행된다:
      ① 이 저장소에서 직접 (`python scripts/generate_project_map.py`)
      ② 다른 프로젝트에 복사돼서 (이식 — 그 프로젝트의 scripts/에 놓임)
      ③ **문서 생성 데몬이 다른 프로젝트를 대상으로** (daemons.py가 vibe-coding의 스크립트를
         `cwd=대상 프로젝트`로 실행) ← ①②만 고려하면 이 경우 vibe-coding 자신의 맵을
         덮어써서 대상 프로젝트에는 맵이 영원히 생기지 않는다.
    그래서 우선순위: VIBE_MAP_ROOT(명시) → cwd가 스크립트 저장소와 다른 git 저장소면 cwd →
    스크립트 위치 기준(기본).
    """
    env_root = os.environ.get('VIBE_MAP_ROOT', '').strip()
    if env_root:
        return Path(env_root).resolve()
    script_root = Path(__file__).resolve().parent.parent
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return script_root
    if cwd != script_root and (cwd / '.git').exists():
        return cwd
    return script_root


PROJECT_ROOT = _resolve_root()
_TOUCHED: set = set()   # 최근 7일 변경 파일 basename — generate()에서 1회 채움

def count_lines(filepath: Path) -> int:
    """파일의 줄 수를 반환합니다."""
    try:
        return sum(1 for _ in open(filepath, encoding='utf-8', errors='replace'))
    except Exception:
        return 0


# ── 설명 수집 ─────────────────────────────────────────────────────────────
# [WHY 하드코딩 폐기 2026-07-30] 이전에는 103항목 dict를 손으로 유지했다. 실측 결과
#   61개가 파일 헤더와 순수 중복이었고, 19개는 **이미 삭제된 파일**을 가리키는 죽은 항목,
#   신규 파일은 아무도 등록하지 않아 212행 중 37%만 설명이 있었다. 규칙 5가 모든 코드
#   파일에 표준 헤더를 의무화하므로 헤더가 유일한 진실의 원천이다.
#   ⚠️ 여기에 코드 파일 설명을 다시 적지 말 것 — 등록 누락/삭제 추적 실패로 즉시 낡는다.
# [예외] .md/.spec/.iss/.bat/.json/.yml은 표준 헤더 규약이 없어 아래에서만 관리한다.
MANUAL_DESCRIPTIONS = {
    "PROJECT_MAP.md": "프로젝트 전체 지도 및 파일 역할 가이드 (이 파일)",
    "RULES.md": "에이전트 행동 수칙, 한글 주석/커밋 표준, 하이브 마인드 운영 원칙",
    "CLAUDE.md": "Claude Code 전용 프로젝트 가이드",
    "AGENTS.md": "멀티 에이전트 설정 및 협업 프로토콜 정의",
    "HIVEMIND.md": "하이브 마인드 실시간 상태 문서 (자동 생성)",
    "CODEX_GUIDE.md": "코덱스(Codex) 에이전트 퀵 스타트 및 통합 사용 설명서",
    "ai_monitor_plan.md": "하이브 마인드 고도화 및 신규 기능 구현 로드맵",
    "vibe-coding.spec": "PyInstaller 실행 파일 빌드 설정",
    "vibe-coding-setup.iss": "Inno Setup 인스톨러 생성 스크립트",
    "run_vibe.bat": "하이브 서버 및 대시보드 실행 배치 파일",
    "docs/VIBE_PROJECT_GUIDE.md": "하이브 마인드 운영 및 아키텍처 통합 가이드",
    "docs/API_SPEC.md": "REST API 엔드포인트 및 통신 규격 상세 명세",
    "docs/CODEX_HARDENING.md": "Codex 경로 고도화 적용 내용과 재적용 조건",
    "docs/CODEX_RUNTIME_SETUP.md": "설치 후 PC별 Codex 런타임 설정 및 운영 가이드",
    "soft_manifest.json": "soft 채널 풀빌드 게이트 (min_exe — 의존성 변경 시 소스 업데이트 차단)",
    # _version.py는 릴리즈 파이프라인이 덮어쓰는 1줄 생성물이라 헤더를 넣을 수 없다.
    "_version.py": "앱 버전 단일 소스 (릴리즈 파이프라인이 자동 갱신 — 수동 편집 금지)",
}

# 헤더 파싱 결과 캐시 — 같은 파일이 여러 섹션(코어/카테고리/기타)에 중복 노출되므로 IO 절약.
_DESC_CACHE: dict = {}


def _header_description(path: Path) -> str:
    """파일 헤더에서 한 줄 설명을 추출한다.

    지원 규약 2종 (이 저장소에 실제로 쓰이는 것만):
      - `DESCRIPTION:` — Python/설정 파일. 값이 비면 다음 들여쓴 줄을 이어 받는다.
      - `📝` — vibe-view의 .tsx/.ts 헤더 관행(`* 📝 설명`).
    [제약] 앞 40줄만 읽는다 — 본문까지 훑으면 5000줄급 파일에서 생성이 눈에 띄게 느려진다.
    [제약] 표의 셀로 들어가므로 `|`는 반드시 이스케이프. 안 하면 마크다운 표가 깨진다.
    """
    key = str(path)
    if key in _DESC_CACHE:
        return _DESC_CACHE[key]
    desc = ''
    try:
        with path.open('r', encoding='utf-8', errors='replace') as fh:
            head = [next(fh, '') for _ in range(40)]
        for i, raw in enumerate(head):
            ln = raw.strip().lstrip('*#/ ').strip()
            if 'DESCRIPTION:' in raw:
                val = raw.split('DESCRIPTION:', 1)[1].strip()
                if not val:                      # 멀티라인 — 다음 비지 않은 줄 채택
                    for nxt in head[i + 1:]:
                        cand = nxt.strip().lstrip('*#/ ').strip()
                        if cand:
                            val = cand
                            break
                desc = val
                break
            if ln.startswith('📝'):
                desc = ln[1:].strip() or ''
                if desc:
                    break
    except Exception:
        desc = ''                                # 읽기 실패는 빈 설명 — 생성 자체를 막지 않는다
    desc = desc.replace('|', '\\|').strip()
    if len(desc) > 130:
        desc = desc[:127].rstrip() + '…'
    _DESC_CACHE[key] = desc
    return desc


def _git(*args, timeout=20) -> str:
    """git 호출 — 실패/미설치/비저장소는 빈 문자열. 맵 생성을 절대 막지 않는다.

    [🔴 과거사고 2026-08-09] subprocess.run 을 직접 부르면 호출마다 검은 cmd 창이 뜬다.
      CREATE_NO_WINDOW 는 부모에서 자식으로 상속되지 않으므로, 콘솔 없는 데몬이 띄워도
      자식 git.exe 는 새 콘솔을 받는다. 이 함수는 한 번의 맵 생성에서 5회 불리고
      데몬이 30분마다 돌리므로, 그대로 두면 창이 연달아 깜빡인다.
    """
    try:
        r = _proc_run(['git', '-C', str(PROJECT_ROOT), *args], capture_output=True,
                      text=True, encoding='utf-8', errors='replace', timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _recent_touched(days: int = 7) -> set:
    """최근 N일 안에 커밋에서 변경된 파일 basename 집합 — 표의 🔨 배지 근거.

    [WHY basename] 표의 각 섹션이 서로 다른 기준 경로(.ai_monitor/, scripts/)로 파일명을
    표기하므로 전체 경로로는 매칭이 안 된다. 동명 파일 오탐 가능성은 배지 용도라 수용.
    """
    out = _git('log', f'--since={days}.days', '--name-only', '--pretty=format:')
    return {Path(ln).name for ln in out.splitlines() if ln.strip()}


def _badge(name: str) -> str:
    """표의 파일명 뒤에 붙는 상태 배지. 지금은 최근 변경(🔨)만 — 근거는 git log 7일.

    [WHY 표 안에] LLM이 "어디까지 했나"를 알려면 파일 목록과 최근 활동이 같은 줄에 있어야 한다.
      별도 섹션으로 빼면 두 표를 눈으로 조인해야 해서 실효가 없다.
    """
    return ' 🔨' if name in _TOUCHED else ''


def _nav_block() -> list:
    """맵 최상단 내비게이션 — "지금 어디고, 무엇이 진행 중이고, 뭐가 터졌는지".

    [WHY 맵 안에 넣나] 규칙 7이 별도 설명 문서 신규 생성을 금지한다. 또한 LLM이 세션 시작에
      읽는 파일이 하나여야 실효가 있다 — 파일이 갈라지면 한쪽이 반드시 낡는다.
    [불변식] git은 항상 시도, DB(체크포인트·사고)는 **있으면 쓰고 없으면 조용히 생략**한다.
      바이브 코딩은 PG 없는 다른 프로젝트에서도 동작해야 한다([[feedback-vibe-essence]]).
    """
    out = ['## 🧭 현재 상황 (내비게이션)', '']
    out.append('> 이 블록은 자동 생성된다. 파일 구조는 아래 지도, **작업 맥락은 여기**를 먼저 읽을 것.')
    out.append('')

    branch = _git('rev-parse', '--abbrev-ref', 'HEAD') or '(unknown)'
    dirty = [ln for ln in _git('status', '--porcelain').splitlines() if ln.strip()]
    unpushed = [ln for ln in _git('log', '--oneline', '@{u}..HEAD').splitlines() if ln.strip()]
    out.append(f'- **브랜치**: `{branch}` · 미커밋 {len(dirty)}개 · 미푸시 {len(unpushed)}커밋')

    recent = _git('log', '-5', '--pretty=format:%h|%ad|%s', '--date=short')
    if recent:
        out.append('- **최근 커밋**')
        for ln in recent.splitlines():
            parts = ln.split('|', 2)
            if len(parts) == 3:
                out.append(f'  - `{parts[0]}` {parts[1]} — {parts[2]}')
    out.append('')

    # ── DB 연동(옵션) — 체크포인트/사고 ─────────────────────────────────
    ctx = _db_context()
    if ctx.get('checkpoints'):
        out.append('### 📍 최근 체크포인트 (중단 지점)')
        for c in ctx['checkpoints']:
            out.append(f"- **{c.get('ts', '')}** 의도: {c.get('intent', '')}")
            if c.get('decision'):
                out.append(f"  - 결정: {c['decision']}")
            if c.get('next'):
                out.append(f"  - 다음: {c['next']}")
        out.append('')
    if ctx.get('incidents'):
        out.append('### ⚠️ 최근 사고 (같은 실수 반복 금지)')
        for i in ctx['incidents']:
            out.append(f"- **{i.get('error', '')[:90]}**")
            out.append(f"  - 원인: {i.get('cause', '')[:150]}")
            out.append(f"  - 수정: {i.get('fix', '')[:150]}")
        out.append('')
    if ctx.get('hotspots'):
        out.append('### 🔥 사고다발 파일 — 수정 전 `incident.py search` 필독')
        for h in ctx['hotspots']:
            out.append(f"- `{h['file']}` — 30일 내 {h['count']}건")
        out.append('')
    if ctx.get('error'):
        out.append(f"> DB 미연결 — 체크포인트/사고 생략 ({ctx['error']})")
        out.append('')
    return out


def _db_context() -> dict:
    """PG에서 체크포인트·사고·사고다발 파일을 읽는다. 실패는 전부 흡수.

    [제약] 이 스크립트는 30분 데몬과 CI 양쪽에서 돌고, PG가 없는 외부 프로젝트에서도 돈다.
      따라서 import 실패/연결 실패/스키마 부재를 모두 정상 경로로 취급하고 error만 남긴다.
    """
    res: dict = {}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / '.ai_monitor'))
        from src.pg_base import query_rows                   # noqa: E402

        # [WHY project_id 필터 없음] DB가 프로젝트당 하나(vibe_<슬러그>)로 이미 분리돼 있어
        #   연결 자체가 프로젝트 경계다. 필터를 또 걸면 슬러그 표기가 어긋날 때 조용히 0건이 된다
        #   (설치본 빈 패널 사고와 같은 계열의 함정).
        # [제약] query_rows는 예외를 내부에서 흡수하고 []를 돌려준다 → 테이블/컬럼명이 틀려도
        #   에러가 아니라 "0건"으로 보인다. 그래서 아래 col_ok로 스키마 존재를 따로 확인한다.
        rows = query_rows(
            "SELECT intent, next_step, decisions::text AS dec, "
            "to_char(updated_at, 'MM-DD HH24:MI') AS ts "
            "FROM active_session_context WHERE intent <> '' "
            "ORDER BY updated_at DESC LIMIT 3;") or []
        res['checkpoints'] = [{'intent': r.get('intent', ''), 'decision': _first_json(r.get('dec')),
                               'next': r.get('next_step', ''), 'ts': r.get('ts', '')}
                              for r in rows]
        rows = query_rows(
            "SELECT error_text, root_cause, fix_description FROM incident_ledger "
            "ORDER BY last_seen_at DESC LIMIT 3;") or []
        res['incidents'] = [{'error': r.get('error_text', ''), 'cause': r.get('root_cause', ''),
                             'fix': r.get('fix_description', '')} for r in rows]
        # files는 JSONB 배열 → unnest가 아니라 jsonb_array_elements_text.
        rows = query_rows(
            "SELECT jsonb_array_elements_text(files) AS f, COUNT(*) AS c "
            "FROM incident_ledger WHERE last_seen_at > now() - interval '30 days' "
            "GROUP BY 1 HAVING COUNT(*) >= 3 ORDER BY c DESC LIMIT 5;") or []
        res['hotspots'] = [{'file': r.get('f', ''), 'count': r.get('c', 0)} for r in rows]

        if not (res['checkpoints'] or res['incidents']):
            probe = query_rows("SELECT 1 AS ok FROM incident_ledger LIMIT 1;")
            if probe is None or probe == []:
                res['error'] = 'DB 연결 또는 스키마 없음 (PG 미기동/미초기화)'
    except Exception as e:
        res['error'] = str(e)[:120]
    return res


def _generic_sections(now: str) -> list:
    """외부 프로젝트용 범용 맵 — `.ai_monitor`가 없는 곳에서 쓰인다.

    [WHY 별도 경로] 이 스크립트를 다른 프로젝트에 그대로 복사해도 동작해야 한다
      ([[feedback-vibe-essence]] 이식성). vibe 전용 섹션(.ai_monitor/vibe-view/스크립트 카테고리)을
      조건문으로 덧대면 들여쓰기가 깊어지고 회귀 위험이 커지므로, 진입부에서 분기한다.
    [불변식] 내비게이션 블록은 두 경로가 공유한다 — 그게 이 파일의 핵심 가치라서.
    """
    SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build',
            '.next', 'target', '.idea', '.vscode', 'coverage', '.pytest_cache'}
    CODE = {'.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java', '.rb', '.php',
            '.c', '.cpp', '.h', '.cs', '.kt', '.swift', '.sh', '.ps1'}
    out: list = []

    # 루트 문서
    docs = [f for f in sorted(PROJECT_ROOT.iterdir())
            if f.is_file() and f.suffix == '.md' and not f.name.startswith('.')]
    if docs:
        out += ['## 📜 루트 문서', '| 파일 | 설명 |', '|------|------|']
        out += [f"| `{f.name}`{_badge(f.name)} | {get_description(f.name, f.name, f)} |" for f in docs]
        out.append('')

    # 소스 디렉토리별 표 — 상위 2단계까지만(그 아래는 파일 수가 폭발해 맵이 못 쓰게 됨)
    def _scan(d: Path, depth: int) -> list:
        rows = []
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return rows
        files = [f for f in entries if f.is_file() and f.suffix in CODE]
        if files:
            rel = d.relative_to(PROJECT_ROOT).as_posix() or '.'
            rows += [f'### `{rel}/`', '| 파일 | 줄 수 | 설명 |', '|------|------|------|']
            for f in files:
                rows.append(f"| `{f.name}`{_badge(f.name)} | {count_lines(f)} | "
                            f"{get_description(f.name, f.name, f)} |")
            rows.append('')
        if depth > 0:
            for sub in entries:
                if sub.is_dir() and sub.name not in SKIP and not sub.name.startswith('.'):
                    rows += _scan(sub, depth - 1)
        return rows

    body = _scan(PROJECT_ROOT, 2)
    if body:
        out.append('## 📂 소스')
        out += body

    # .claude 스킬 — 외부 프로젝트에도 install_skills.py로 복사되므로 노출 가치가 있다
    skills = PROJECT_ROOT / '.claude' / 'skills'
    if skills.exists():
        names = [d.name for d in sorted(skills.iterdir()) if d.is_dir()]
        if names:
            out += ['## 🤖 Claude 스킬 (.claude/skills/)', '',
                    ', '.join(f'`{n}`' for n in names), '']
    out += ['---', f'> 자동 생성 완료: {now}']
    return out


def _first_json(raw) -> str:
    """decisions(JSONB 배열 텍스트)에서 첫 항목만 뽑는다. 파싱 실패는 원문 절단으로 폴백."""
    if not raw:
        return ''
    try:
        import json
        v = json.loads(raw)
        if isinstance(v, list) and v:
            return str(v[0])[:150]
        if isinstance(v, str):
            return v[:150]
    except Exception:
        pass
    return str(raw)[:150]


def get_description(rel_path: str, filename: str, path: Path = None) -> str:
    """설명 조회 — 헤더 우선, 비-코드 파일만 MANUAL_DESCRIPTIONS 폴백.

    [불변식] path를 넘기지 않으면 헤더를 볼 수 없다. 호출부는 항상 실제 Path를 넘길 것.
    """
    if path is not None:
        d = _header_description(path)
        if d:
            return d
    return MANUAL_DESCRIPTIONS.get(rel_path) or MANUAL_DESCRIPTIONS.get(filename) or ''


def scan_section(base: Path, rel_dir: str, extensions: tuple, skip_dirs: set = None) -> list:
    """디렉토리를 스캔하여 (상대경로, 줄수, 설명) 리스트를 반환합니다."""
    skip_dirs = skip_dirs or set()
    target = base / rel_dir if rel_dir else base
    if not target.exists():
        return []

    results = []
    for item in sorted(target.iterdir()):
        if item.name.startswith('.') or item.name.startswith('__'):
            continue
        if item.is_dir() and item.name in skip_dirs:
            continue
        if item.is_file() and item.suffix in extensions:
            rel = str(item.relative_to(base)).replace('\\', '/')
            lines = count_lines(item)
            desc = get_description(rel, item.name, item)
            results.append((rel, lines, desc))
    return results


def generate():
    """PROJECT_MAP.md를 생성합니다."""
    global _TOUCHED
    _TOUCHED = _recent_touched(7)
    now = time.strftime('%Y-%m-%d %H:%M')
    lines = []
    # 제목은 대상 프로젝트 폴더명 — 이식된 곳에서 'Vibe Coding'으로 나오면 오해를 부른다.
    lines.append(f"# 🗺️ {PROJECT_ROOT.name} 프로젝트 맵 (PROJECT_MAP.md)")
    lines.append(f"")
    lines.append(f"> 자동 생성: `python scripts/generate_project_map.py` | {now}")
    lines.append(f"> 문서 드리프트 방지를 위해 파일 시스템을 스캔하여 자동 갱신합니다.")
    lines.append(f"> 설명은 각 파일의 표준 헤더(`DESCRIPTION:` / `📝`)에서 자동 수집합니다 — "
                 f"여기 손으로 적지 말고 **파일 헤더를 고치세요**.")
    lines.append(f"")
    lines.extend(_nav_block())
    lines.append("🔨 = 최근 7일 내 변경된 파일")
    lines.append("")

    # [이식성] vibe-coding 전용 레이아웃(.ai_monitor)이 없으면 범용 스캔으로 분기하고 종료.
    #   이 스크립트만 복사해도 다른 프로젝트에서 그대로 동작해야 한다.
    if not (PROJECT_ROOT / ".ai_monitor").exists():
        lines.extend(_generic_sections(now))
        out_generic = PROJECT_ROOT / "PROJECT_MAP.md"
        out_generic.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f"✅ PROJECT_MAP.md 갱신 완료 — 범용 모드 ({len(lines)}줄)")
        return

    # ── 1. 루트 문서 ──
    lines.append("## 📜 루트 문서")
    lines.append("| 파일 | 설명 |")
    lines.append("|------|------|")
    root_docs = [f for f in PROJECT_ROOT.iterdir()
                 if f.is_file() and f.suffix == '.md' and not f.name.startswith('.')]
    root_docs.sort(key=lambda x: x.name)
    for f in root_docs:
        desc = get_description(f.name, f.name, f)
        lines.append(f"| `{f.name}` | {desc} |")
    # docs/ 하위
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.exists():
        for f in sorted(docs_dir.iterdir()):
            if f.is_file() and f.suffix == '.md':
                rel = f"docs/{f.name}"
                desc = get_description(rel, f.name, f)
                lines.append(f"| `{rel}` | {desc} |")
    lines.append("")

    # ── 2. 서버 & API ──
    lines.append("## 🖥️ 서버 & API (.ai_monitor/)")
    ai_dir = PROJECT_ROOT / ".ai_monitor"

    lines.append("### 서버 코어")
    lines.append("| 파일 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    core_files = ['server.py', 'boot.py', 'soft_updater.py', '_version.py',
                  'mission_control.py', 'mission_control_ui.py']
    for name in core_files:
        fp = ai_dir / name
        if fp.exists():
            lc = count_lines(fp)
            desc = get_description(name, name, fp)
            lines.append(f"| `{name}`{_badge(name)} | {lc} | {desc} |")
    # soft_manifest.json은 리포 루트 파일이지만 boot.py/soft_updater.py와 한 몸의 규약이라 코어 표에 노출
    _mf = PROJECT_ROOT / 'soft_manifest.json'
    if _mf.exists():
        lines.append(f"| `soft_manifest.json` (루트) | {count_lines(_mf)} | "
                     f"{get_description('soft_manifest.json', 'soft_manifest.json', _mf)} |")

    lines.append("")
    lines.append("### API 모듈 (.ai_monitor/api/)")
    lines.append("| 모듈 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    api_dir = ai_dir / "api"
    if api_dir.exists():
        for f in sorted(api_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name != '__init__.py':
                rel = f"api/{f.name}"
                lc = count_lines(f)
                desc = get_description(rel, f.name, f)
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")

    lines.append("")
    lines.append("### 데이터 계층 (.ai_monitor/src/)")
    lines.append("| 모듈 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    src_dir = ai_dir / "src"
    if src_dir.exists():
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name != '__init__.py':
                rel = f"src/{f.name}"
                lc = count_lines(f)
                desc = get_description(rel, f.name, f)
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")
    lines.append("")

    # [과거사고 2026-08-02] infra/ 섹션이 통째로 빠져 있었다 — proc.py(콘솔 숨김 표준 래퍼),
    #   daemons.py, pty_process.py 등 부팅·프로세스 핵심 모듈이 지도에 하나도 없어
    #   다음 세션 LLM이 "그 기능이 어디 있지"를 매번 grep으로 찾아야 했다.
    lines.append("### 인프라 계층 (.ai_monitor/infra/)")
    lines.append("| 모듈 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    infra_dir = ai_dir / "infra"
    if infra_dir.exists():
        for f in sorted(infra_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name != '__init__.py':
                rel = f"infra/{f.name}"
                lc = count_lines(f)
                desc = get_description(rel, f.name, f)
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")
    lines.append("")

    # ── 3. Scripts ──
    lines.append("## ⚙️ 스크립트 (scripts/)")
    scripts_dir = PROJECT_ROOT / "scripts"

    # 카테고리별 그룹핑
    categories = {
        "에이전트/터미널": ["cli_agent.py", "agent_shell.py", "terminal_agent.py",
                           "agent_launcher.py", "agent_detector.py", "agent_protocol.py"],
        "하이브/협업": ["orchestrator.py", "hive_debate.py", "hive_bridge.py",
                        "memory.py", "worktree_manager.py", "generate_hivemind_doc.py", "analyze_hive.py"],
        "훅/이벤트": ["hive_hook.py", "hook_bridge.py", "claude_hook.py", "antigravity_hook.py"],
        "통신/ITCP": ["itcp.py", "send_message.py"],
        "검증/가드": ["safety_guard.py", "completion_guard.py", "drift_detector.py",
                      "plan_validator.py", "rules_validator.py"],
        "스킬 관리": ["skill_orchestrator.py", "skill_manager.py", "skill_analyzer.py",
                      "skill_predictor.py", "skill_ab_test.py"],
        "모니터링": ["hive_watchdog.py", "claude_watchdog.py"],
        "유틸리티": ["vibe_cli.py", "task.py", "auto_version.py", "auto_release.py",
                     "lock_manager.py", "osc_parser.py", "git_visualizer.py", "screenshot_analyzer.py",
                     "generate_project_map.py"],
        "인프라": ["pg_manager.py", "setup_hive_pg.py", "install_codex.py"],
    }

    categorized = set()
    for cat_name, cat_files in categories.items():
        lines.append(f"### {cat_name}")
        lines.append("| 파일 | 줄 수 | 설명 |")
        lines.append("|------|------|------|")
        for name in cat_files:
            fp = scripts_dir / name
            if fp.exists():
                lc = count_lines(fp)
                desc = get_description(f"scripts/{name}", name, fp)
                lines.append(f"| `{name}`{_badge(name)} | {lc} | {desc} |")
                categorized.add(name)
        lines.append("")

    # 미분류 파일
    uncategorized = []
    if scripts_dir.exists():
        for f in sorted(scripts_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name not in categorized and not f.name.startswith('__'):
                uncategorized.append(f)
    if uncategorized:
        lines.append("### 기타")
        lines.append("| 파일 | 줄 수 | 설명 |")
        lines.append("|------|------|------|")
        for f in uncategorized:
            lc = count_lines(f)
            desc = get_description(f"scripts/{f.name}", f.name, f)
            lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")
        lines.append("")

    # ── 4. 프론트엔드 ──
    lines.append("## 🎨 프론트엔드 (.ai_monitor/vibe-view/src/)")
    vv_src = ai_dir / "vibe-view" / "src"

    lines.append("### 코어")
    lines.append("| 파일 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    core_tsx = ['App.tsx', 'main.tsx', 'types.ts', 'constants.tsx']
    for name in core_tsx:
        fp = vv_src / name
        if fp.exists():
            lc = count_lines(fp)
            desc = get_description(name, name, fp)
            lines.append(f"| `{name}`{_badge(name)} | {lc} | {desc} |")
    lines.append("")

    lines.append("### 컴포넌트 (components/)")
    lines.append("| 컴포넌트 | 줄 수 | 설명 |")
    lines.append("|----------|------|------|")
    comp_dir = vv_src / "components"
    if comp_dir.exists():
        for f in sorted(comp_dir.iterdir()):
            if f.is_file() and f.suffix in ('.tsx', '.ts') and '.test.' not in f.name:
                lc = count_lines(f)
                desc = get_description(f.name, f.name, f)
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")
    lines.append("")

    lines.append("### 패널 컴포넌트 (components/panels/)")
    lines.append("| 패널 | 줄 수 | 설명 |")
    lines.append("|------|------|------|")
    panels_dir = comp_dir / "panels" if comp_dir.exists() else None
    if panels_dir and panels_dir.exists():
        for f in sorted(panels_dir.iterdir()):
            if f.is_file() and f.suffix == '.tsx':
                lc = count_lines(f)
                desc = get_description(f.name, f.name, f)
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {desc} |")
    lines.append("")

    # ── 5. 테스트 ──
    lines.append("## 🧪 테스트 (tests/)")
    lines.append("| 파일 | 줄 수 | 테스트 대상 |")
    lines.append("|------|------|------------|")
    tests_dir = PROJECT_ROOT / "tests"
    # [WHY 하드코딩 폐기] 여기도 3항목짜리 손 관리 맵이라 신규 테스트가 전부 빈칸이었다
    #   (2026-07-30 실측: 테스트 26개 중 23개 빈칸). 테스트 파일의 표준 헤더 DESCRIPTION이
    #   곧 "무엇을 검증하는가"이므로 헤더를 1순위로 쓴다. 아래 맵은 헤더 없는 구파일 폴백.
    test_targets = {
        "test_agent_api.py": "api/agent_api.py",
        "test_itcp_context.py": "scripts/itcp.py 컨텍스트 빌딩",
        "test_itcp_fallback.py": "scripts/itcp.py 폴백 경로",
    }
    if tests_dir.exists():
        for f in sorted(tests_dir.iterdir()):
            if f.is_file() and f.suffix == '.py' and f.name.startswith('test_'):
                lc = count_lines(f)
                target = _header_description(f) or test_targets.get(f.name, "")
                lines.append(f"| `{f.name}`{_badge(f.name)} | {lc} | {target} |")
    # 프론트엔드 테스트
    if comp_dir and comp_dir.exists():
        for f in comp_dir.rglob('*.test.tsx'):
            lc = count_lines(f)
            lines.append(f"| `{f.name}` | {lc} | {f.stem.replace('.test', '')} 컴포넌트 |")
    lines.append("")

    # ── 6. Claude 통합 (.claude/) ──
    # [WHY] vibe-* 슬래시 스킬과 Subagent 위임 매핑을 PROJECT_MAP에 노출해야
    # 신규 멤버가 "어떤 스킬을 부르면 어떤 subagent가 도는지" 한눈에 파악 가능.
    # [과거사고] 2026-06-07: 수동 추가 섹션이 자동 재생성 시 사라짐 → 자동 생성으로 흡수.
    claude_dir = PROJECT_ROOT / ".claude"
    skills_dir = claude_dir / "skills"
    agents_dir = claude_dir / "agents"
    if skills_dir.exists() or agents_dir.exists():
        lines.append("## 🤖 Claude 통합 (.claude/)")

        if skills_dir.exists():
            lines.append("### Skills (.claude/skills/) — Slash 명령 워크플로우")
            lines.append("| 스킬 | 설명 |")
            lines.append("|------|------|")
            for d in sorted(skills_dir.iterdir()):
                if not d.is_dir() or d.name.startswith('.') or d.name.startswith('__'):
                    continue
                skill_md = d / "SKILL.md"
                desc = ""
                if skill_md.exists():
                    # frontmatter의 description: 줄 파싱.
                    # [제약] 정식 YAML 파서 안 씀 — 시작/끝 마커 사이만 보고 description: 키 추출.
                    # [멀티라인] `description: >` 또는 `description: |` 다음 들여쓴 줄 첫 문장 1개만 채택.
                    try:
                        text = skill_md.read_text(encoding='utf-8', errors='replace')
                        in_fm = False
                        capture_next = False
                        for ln in text.splitlines():
                            if ln.strip() == '---':
                                if in_fm:
                                    break
                                in_fm = True
                                continue
                            if not in_fm:
                                continue
                            if capture_next:
                                if ln.strip():
                                    desc = ln.strip()
                                    break
                                continue
                            if ln.strip().startswith('description:'):
                                val = ln.split(':', 1)[1].strip()
                                if val and val not in ('>', '|', '|-', '>-'):
                                    desc = val.strip('"').strip("'")
                                    break
                                # 멀티라인 마커 — 다음 비어있지 않은 들여쓴 줄을 채택.
                                capture_next = True
                    except Exception:
                        pass
                lines.append(f"| `{d.name}` | {desc} |")
            lines.append("")

        if agents_dir.exists():
            lines.append("### Subagents (.claude/agents/) — 위임 대상")
            lines.append("| Agent | 매핑 스킬 |")
            lines.append("|-------|-----------|")
            # vibe-* 스킬 ↔ subagent 라우팅. agents/README.md와 동기 유지.
            agent_routing = {
                "code-reviewer": "/vibe-code-review",
                "security-auditor": "/vibe-security",
                "debugger": "/vibe-debug",
            }
            for f in sorted(agents_dir.iterdir()):
                if not f.is_file() or f.suffix != '.md' or f.name == 'README.md':
                    continue
                agent_name = f.stem
                mapping = agent_routing.get(agent_name, "(매핑 미정)")
                lines.append(f"| `{agent_name}` | {mapping} |")
            lines.append("")
            lines.append("> 라우팅 정책 상세: [`.claude/agents/README.md`](.claude/agents/README.md)")
            lines.append("")

    # ── 7. 빌드/CI ──
    lines.append("## 🏗️ 빌드 & CI")
    lines.append("| 파일 | 설명 |")
    lines.append("|------|------|")
    build_files = [
        ("vibe-coding.spec", "PyInstaller 실행 파일 빌드 설정"),
        ("vibe-coding-setup.iss", "Inno Setup 인스톨러 생성 스크립트"),
        (".github/workflows/build-release.yml", "GitHub Actions 빌드 & 릴리즈 워크플로우"),
        ("run_vibe.bat", "하이브 서버 및 대시보드 실행 배치 파일"),
    ]
    for path, desc in build_files:
        fp = PROJECT_ROOT / path
        if fp.exists():
            lines.append(f"| `{path}` | {desc} |")
    lines.append("")

    # ── 통계 ──
    lines.append("---")
    lines.append(f"> 자동 생성 완료: {now}")

    # 파일 작성
    output = PROJECT_ROOT / "PROJECT_MAP.md"
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"✅ PROJECT_MAP.md 갱신 완료 ({len(lines)}줄)")


if __name__ == '__main__':
    generate()

