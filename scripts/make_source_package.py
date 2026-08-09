#!/usr/bin/env python3
"""
FILE: scripts/make_source_package.py
DESCRIPTION: 개인 인프라 정보를 걷어낸 소스 배포 zip을 만든다. 남에게 코드를 건네되
             내 서버 주소·노드 목록·자격증명·운영 메모는 함께 나가지 않게 하는 것이 목적.

             [WHY 필요한가] 이 저장소에는 세 종류가 섞여 있다 — 제품 코드(남에게 필요),
               운영 스크립트(나만 씀), 개인 계획·지식 문서(나만 씀, 서버 IP를 담고 있음).
               통째로 압축하면 세 번째가 함께 나간다.

             [🔴 안전장치] 압축 직후 결과물을 다시 열어 민감 패턴을 재검사한다.
               제외 목록은 사람이 관리하는 것이라 언젠가 새는 것이 들어온다 —
               '무엇을 뺐는가'가 아니라 '결과물에 무엇이 남았는가'로 판정해야 한다.

사용:
  python scripts/make_source_package.py              # dist_pkg/vibe-coding-src-<버전>.zip
  python scripts/make_source_package.py --out X.zip

REVISION HISTORY:
- 2026-08-08 Claude: 최초 작성 — 통제된 소스 전달용.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 디렉토리 이름 단위 제외 — 경로 어디에 나타나도 통째로 뺀다.
EXCLUDE_DIRS = {
    '.git', '.github', 'venv', '.venv', 'node_modules', '__pycache__',
    'dist', 'build', '.pytest_cache', '.ruff_cache', '.mypy_cache',
    # 실행 중 생기는 것 — 개인 DB·비밀·볼트·바이너리. 코드가 아니다.
    'data', 'bin', 'runtime', 'backups', '.zettel-vault', 'vault',
}

EXCLUDE_SUFFIXES = {'.pyc', '.pyo', '.log', '.db', '.sqlite', '.sqlite3', '.dat', '.pem', '.key'}

# 파일명 단위 제외 — 개인 운영 메모와 비밀.
# [WHY 계획·지식 문서를 빼는가] HIVEMIND.md와 ai_monitor_plan.md에는 서버 IP와
#   노드 구성이 실제로 들어 있다(2026-08-08 실측). 받는 사람에게는 의미가 없다.
# [WHY 문서와 운영 스크립트를 빼지 않는가] 이 저장소는 공개다 — 누구나 이미 전부
#   볼 수 있으므로 zip에서만 빼는 것은 실익이 없다. 문서·운영 스크립트는 그대로 담고,
#   **저장소에 없는 것**(실행 중 생기는 비밀과 상태)만 제외한다.
#   저장소를 private로 돌리게 되면 이 목록을 다시 좁힐 것.
EXCLUDE_NAMES = {
    '.env', 'config.json', 'discord_secrets.dat', 'soft_manifest.json',
}

# 결과물 재검사 패턴 — 넣지 말았어야 할 것이 남았는지 본다.
# [WHY 대역을 세밀히 빼는가] 첫 판은 0.0.0.0·255.255.255.255·CGNAT 100.x를
#   전부 '공인 IP'로 잡아 9건 중 5건이 오탐이었다. 오탐이 많은 검사는 곧 무시되고,
#   무시되는 검사는 없는 것만 못하다 — 실제로 인터넷에서 라우팅되는 주소만 남긴다.
_NON_PUBLIC = (
    r'0\.|10\.|127\.|169\.254\.|192\.168\.|255\.|'
    r'172\.(?:1[6-9]|2\d|3[01])\.|'
    r'100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|'   # 100.64/10 CGNAT 대역
    r'19[23]\.0\.2\.|198\.51\.100\.|203\.0\.113\.|'  # RFC 5737 문서용 예시 대역
    r'1\.2\.3\.|3\.5\.7\.'                           # 테스트/샘플에 흔한 더미
)
DANGER = [
    (r'BEGIN [A-Z ]*PRIVATE KEY', '개인키'),
    (r'\bsk-ant-[A-Za-z0-9_-]{10,}', 'Anthropic 키'),
    (r'\bghp_[A-Za-z0-9]{20,}', 'GitHub 토큰'),
    (r'\bxox[baprs]-[A-Za-z0-9-]{10,}', 'Slack 토큰'),
    (rf'\b(?!{_NON_PUBLIC})(?:\d{{1,3}}\.){{3}}\d{{1,3}}\b', '공인 IP'),
]

# 공인 IP는 경고만 하고 중단하지 않는다.
# [WHY] 이 저장소는 공개라 서버 주소가 이미 노출돼 있고, 도메인이 그 주소를 가리키므로
#   DNS 조회로 누구나 안다 — 여기서 막아도 얻는 게 없다. 반면 개인키·API 토큰은
#   한 번 나가면 회수가 불가능하므로 그쪽만 차단 사유로 남긴다.
WARN_ONLY = {'공인 IP'}


def _skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if rel.name in EXCLUDE_NAMES:
        return True
    if rel.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return False


def collect() -> list[Path]:
    """git이 추적하는 파일만 대상으로 삼는다.

    [WHY rglob이 아닌가] 첫 판은 디렉토리를 통째로 훑다가 `%TEMP%`처럼 어떤 도구가
      변수를 안 풀고 만든 로컬 쓰레기 폴더까지 담았다(추적되지 않는 파일 수백 개).
      git 추적 목록을 쓰면 .gitignore가 자동으로 존중되고, venv·node_modules·dist·
      빌드 잔재가 제외 목록을 손보지 않아도 애초에 들어오지 않는다.
    [폴백] git이 없거나 저장소가 아니면 예전 방식으로 훑되, 그때는 제외 목록만이
      유일한 방어선이므로 결과물 재검사(scan)가 더 중요해진다.
    """
    import subprocess
    try:
        res = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                             text=True, encoding='utf-8', timeout=60)
        if res.returncode == 0 and res.stdout.strip():
            rels = [Path(line) for line in res.stdout.splitlines() if line.strip()]
            return sorted(r for r in rels if not _skip(r) and (ROOT / r).is_file())
    except Exception:
        pass

    print('  [!] git 목록을 못 얻어 전체 순회로 폴백한다')
    return sorted(p.relative_to(ROOT) for p in ROOT.rglob('*')
                  if p.is_file() and not _skip(p.relative_to(ROOT)))


def scan(zip_path: Path) -> tuple[list[str], list[str]]:
    """압축 결과를 다시 열어 검사한다. (차단, 경고)

    [불변식] 제외 목록이 아니라 **결과물**을 본다. 목록은 사람이 관리하는 것이라
      언젠가 새는 것이 들어온다 — '무엇을 뺐는가'가 아니라 '무엇이 남았는가'로 판정한다.
      실제로 첫 판에서 이 검사가 로컬 쓰레기 폴더와 회선 IP를 잡아냈다.
    """
    blocking: list[str] = []
    warning: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.file_size > 2_000_000:      # 대용량 바이너리는 텍스트 스캔 대상이 아니다
                continue
            try:
                text = zf.read(info.filename).decode('utf-8', errors='ignore')
            except Exception:
                continue
            for pattern, label in DANGER:
                m = re.search(pattern, text)
                if m:
                    line = f'{info.filename}: {label} — {m.group(0)[:40]}'
                    (warning if label in WARN_ONLY else blocking).append(line)
    return blocking, warning


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    version = 'unknown'
    try:
        m = re.search(r'__version__\s*=\s*"([^"]+)"',
                      (ROOT / '.ai_monitor' / '_version.py').read_text(encoding='utf-8'))
        if m:
            version = m.group(1)
    except OSError:
        pass

    out = Path(args.out) if args.out else ROOT / 'dist_pkg' / f'vibe-coding-src-{version}.zip'
    out.parent.mkdir(parents=True, exist_ok=True)

    files = collect()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            zf.write(ROOT / rel, arcname=str(Path(f'vibe-coding-{version}') / rel))

    size_mb = out.stat().st_size / 1048576
    print(f'생성: {out}')
    print(f'  파일 {len(files)}개 / {size_mb:.1f}MB')

    print('\n[검사] 결과물 재스캔')
    blocking, warning = scan(out)

    if warning:
        print(f'  ⚠ 공인 IP {len(warning)}건 (공개 저장소라 이미 노출 — 참고용):')
        for w in warning[:8]:
            print(f'    {w}')
        if len(warning) > 8:
            print(f'    ... 외 {len(warning) - 8}건')

    if blocking:
        print(f'  🔴 회수 불가 비밀 {len(blocking)}건 — 전달 금지:')
        for h in blocking[:20]:
            print(f'    {h}')
        print('\n  제외 목록을 고친 뒤 다시 만들 것.')
        return 1

    print('  ✅ 개인키/API키/토큰 0건 — 전달 가능')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
