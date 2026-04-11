#!/usr/bin/env python3
# ────────────────────────────────────────────────────────────────────────────
# FILE: scripts/smoke_test.py
# DESCRIPTION: 로컬 EXE 빌드 후 smoke test 자동 실행.
#   EXE를 별도 프로세스로 기동 → 서버 응답 확인 → API 엔드포인트 테스트 → 종료.
#   /vibe-release 스킬의 Step 0.5에서 호출됨.
#
# REVISION HISTORY:
# - 2026-04-11 Claude: 최초 생성
# ────────────────────────────────────────────────────────────────────────────
"""로컬 EXE smoke test — 빌드된 EXE가 정상 기동되는지 검증."""

import subprocess
import sys
import time
import json
import os
import signal
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── 설정 ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / 'dist'
STARTUP_TIMEOUT = 30       # 서버 기동 대기 (초)
TEST_TIMEOUT = 5           # 개별 API 테스트 타임아웃 (초)
HEALTH_CHECK_INTERVAL = 1  # 헬스체크 폴링 간격 (초)


def find_exe() -> Path | None:
    """dist/ 디렉토리에서 가장 최근 빌드된 EXE를 찾습니다."""
    if not DIST_DIR.exists():
        return None
    exes = sorted(DIST_DIR.glob('vibe-coding-v*.exe'), key=lambda p: p.stat().st_mtime, reverse=True)
    return exes[0] if exes else None


def wait_for_server(port: int, timeout: int = STARTUP_TIMEOUT) -> bool:
    """서버가 응답할 때까지 폴링합니다."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urlopen(f'http://127.0.0.1:{port}/api/config', timeout=2)
            if resp.status == 200:
                return True
        except (URLError, OSError):
            pass
        time.sleep(HEALTH_CHECK_INTERVAL)
    return False


def find_server_port(proc: subprocess.Popen, timeout: int = STARTUP_TIMEOUT) -> int | None:
    """프로세스 stdout에서 HTTP 포트를 파싱합니다."""
    import re
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            time.sleep(0.1)
            continue
        line = line.strip()
        if line:
            print(f'  [exe] {line}')
        # "[*] 서버 포트 확정 — HTTP:9010, WS:9011" 패턴
        m = re.search(r'HTTP[:\s]*(\d+)', line)
        if m:
            return int(m.group(1))
    return None


def test_api(port: int, path: str, expected_keys: list[str] | None = None) -> tuple[bool, str]:
    """API 엔드포인트를 호출하고 응답을 검증합니다."""
    url = f'http://127.0.0.1:{port}{path}'
    try:
        req = Request(url)
        resp = urlopen(req, timeout=TEST_TIMEOUT)
        data = json.loads(resp.read().decode('utf-8'))
        if expected_keys:
            missing = [k for k in expected_keys if k not in data]
            if missing:
                return False, f'응답에 키 누락: {missing}'
        return True, 'OK'
    except Exception as e:
        return False, str(e)


def run_smoke_test(exe_path: Path) -> bool:
    """EXE를 실행하고 smoke test를 수행합니다."""
    print(f'\n[smoke] EXE 경로: {exe_path}')
    print(f'[smoke] 서버 기동 중... (최대 {STARTUP_TIMEOUT}초 대기)')

    # console 모드가 아닌 EXE는 stdout이 없으므로 직접 포트 스캔
    # ── 핵심: 개발 서버(9000~9050)와 완전 격리된 포트 대역 사용 ──
    # 개발 서버와 EXE가 같은 포트/DB를 쓰면 충돌 → 개발 터미널 크래시 위험
    SMOKE_PORT_BASE = 9100
    env = os.environ.copy()
    env['VIBE_SMOKE_TEST'] = '1'  # 서버에서 smoke test 모드 감지용
    env['VIBE_PORT_BASE'] = str(SMOKE_PORT_BASE)  # 격리된 포트 대역 강제

    # GUI EXE(runw)는 stdout이 없으므로 PIPE 대신 DEVNULL 사용 — 블로킹 방지
    proc = subprocess.Popen(
        [str(exe_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
    )

    port = None
    try:
        # 격리 포트 대역(9100~)에서 서버 기동 대기 — socket으로 빠른 스캔
        print(f'[smoke] 격리 포트 대역 {SMOKE_PORT_BASE}~{SMOKE_PORT_BASE+20} 스캔 중...')
        import socket
        _scan_start = time.time()
        while time.time() - _scan_start < STARTUP_TIMEOUT:
            if proc.poll() is not None:
                print(f'[smoke] FAIL — EXE 프로세스가 조기 종료됨 (exit code: {proc.returncode})')
                return False
            for p in range(SMOKE_PORT_BASE, SMOKE_PORT_BASE + 20):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                if s.connect_ex(('127.0.0.1', p)) == 0:
                    s.close()
                    # 소켓 열림 확인 후 HTTP API 응답까지 확인
                    try:
                        resp = urlopen(f'http://127.0.0.1:{p}/api/config', timeout=2)
                        if resp.status == 200:
                            port = p
                            break
                    except (URLError, OSError):
                        continue
                else:
                    s.close()
            if port:
                break
            time.sleep(HEALTH_CHECK_INTERVAL)

        if port is None:
            print('[smoke] FAIL — 서버 기동 실패 (포트 감지 불가)')
            return False

        print(f'[smoke] 서버 포트 감지: {port}')

        # 서버 안정화 대기
        if not wait_for_server(port, timeout=10):
            print('[smoke] FAIL — 서버가 health check에 응답하지 않음')
            return False

        # ── API 테스트 ──
        # 기본 서버 + DB 연동 + 하이브 마인드 + 제텔카스텐 통합 검증
        tests = [
            # 기본 서버
            ('/api/config', None),
            ('/api/agents', None),
            # DB 연동 (PostgreSQL)
            ('/api/hive/health', None),
            # 하이브 마인드
            ('/api/memory', None),
            ('/api/tasks', None),
            # 제텔카스텐 (Obsidian vault 연동)
            ('/api/zettel/notes', None),
        ]

        passed = 0
        failed = 0
        for path, keys in tests:
            ok, msg = test_api(port, path, keys)
            status = 'PASS' if ok else 'FAIL'
            print(f'  [{status}] GET {path} — {msg}')
            if ok:
                passed += 1
            else:
                failed += 1

        # 프론트엔드 로드 테스트
        try:
            resp = urlopen(f'http://127.0.0.1:{port}/', timeout=TEST_TIMEOUT)
            html = resp.read().decode('utf-8')
            if '<div id="root">' in html or 'vite' in html.lower() or '</html>' in html:
                print(f'  [PASS] GET / — 프론트엔드 HTML 로드 OK')
                passed += 1
            else:
                print(f'  [FAIL] GET / — HTML에 root div 없음')
                failed += 1
        except Exception as e:
            print(f'  [FAIL] GET / — {e}')
            failed += 1

        print(f'\n[smoke] 결과: {passed} passed, {failed} failed')
        return failed == 0

    finally:
        # 프로세스 종료
        print('[smoke] EXE 프로세스 종료 중...')
        try:
            if os.name == 'nt':
                # Windows: taskkill로 프로세스 트리 전체 종료
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    capture_output=True, timeout=10,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass
        proc.wait(timeout=10)
        print('[smoke] 정리 완료')


def main():
    exe = find_exe()
    if exe is None:
        print('[smoke] ERROR — dist/ 디렉토리에 EXE가 없습니다.')
        print('        먼저 `pyinstaller vibe-coding.spec --noconfirm`를 실행하세요.')
        sys.exit(1)

    success = run_smoke_test(exe)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
