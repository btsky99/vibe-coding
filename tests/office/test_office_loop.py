"""
오피스 모드 반복 테스트 루프
- dev 서버 자동 시작/종료
- E2E 테스트 반복 실행 (최대 10회 또는 3회 연속 성공까지)
- 결과를 test_office_report.md에 저장
"""
import subprocess
import time
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]

VITE_PORT = 5190
VITE_DIR = str(_REPO_ROOT / ".ai_monitor" / "vibe-view")
REPORT_PATH = str(_HERE / "test_office_report.md")
PYTHON312 = os.environ.get(
    "PYTHON312",
    r"C:\Users\com\AppData\Local\Programs\Python\Python312\python.exe",
)
TEST_SCRIPT = str(_HERE / "test_office_e2e.py")
MAX_ROUNDS = 10
CONSECUTIVE_PASS_TARGET = 3

PTY_BASE = "http://127.0.0.1:9001"
DEV_BASE = f"http://localhost:{VITE_PORT}"


def check_pty_server():
    """PTY 서버 생존 확인"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{PTY_BASE}/health", timeout=3) as r:
            data = json.loads(r.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def check_dev_server():
    """Vite dev 서버 생존 확인"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{DEV_BASE}/", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def start_dev_server():
    """Vite dev 서버 시작"""
    proc = subprocess.Popen(
        ["npx", "vite", "dev", "--port", str(VITE_PORT)],
        cwd=VITE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    # 서버 준비 대기
    for _ in range(15):
        time.sleep(2)
        if check_dev_server():
            return proc
    return proc


def stop_dev_server(proc):
    """Vite dev 서버 종료"""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.kill(proc.pid, signal.SIGTERM)
    except Exception:
        pass


def run_api_test():
    """API 레벨 테스트 (Playwright 없이)"""
    import urllib.request
    results = {}

    # 1. 오피스 세션 목록
    try:
        with urllib.request.urlopen(f"{DEV_BASE}/api/pty/office/sessions", timeout=5) as r:
            data = json.loads(r.read())
            results["sessions_list"] = {"pass": r.status == 200, "data": str(data)[:200]}
    except Exception as e:
        results["sessions_list"] = {"pass": False, "error": str(e)}

    # 2. 세션 생성
    sid = None
    try:
        req = urllib.request.Request(
            f"{DEV_BASE}/api/pty/office/spawn",
            data=json.dumps({"agent": "claude", "yolo": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            sid = data.get("sessionId")
            results["spawn"] = {"pass": bool(sid), "sessionId": sid}
    except Exception as e:
        results["spawn"] = {"pass": False, "error": str(e)}

    # 3. 메시지 전송
    if sid:
        try:
            req = urllib.request.Request(
                f"{DEV_BASE}/api/pty/write/{sid}",
                data=json.dumps({"text": "echo loop-test-ok"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                results["write"] = {"pass": data.get("status") == "written"}
        except Exception as e:
            results["write"] = {"pass": False, "error": str(e)}

        # 4. 출력 읽기
        time.sleep(2)
        try:
            with urllib.request.urlopen(f"{DEV_BASE}/api/pty/output/{sid}?since=0&limit=5", timeout=5) as r:
                data = json.loads(r.read())
                entries = len(data.get("entries", []))
                results["output"] = {"pass": entries > 0, "entries": entries}
        except Exception as e:
            results["output"] = {"pass": False, "error": str(e)}

        # 5. 클래식 세션 영향 확인
        try:
            with urllib.request.urlopen(f"{DEV_BASE}/api/pty/sessions", timeout=5) as r:
                data = json.loads(r.read())
                running = {k: v["agent"] for k, v in data.items() if v.get("running")}
                results["classic_ok"] = {"pass": True, "running": running}
        except Exception as e:
            results["classic_ok"] = {"pass": False, "error": str(e)}

        # 정리
        try:
            req = urllib.request.Request(
                f"{DEV_BASE}/api/pty/terminate/{sid}",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    all_pass = all(r.get("pass", False) for r in results.values())
    return all_pass, results


def run_playwright_test():
    """Playwright UI 테스트"""
    try:
        env = os.environ.copy()
        env["BASE"] = DEV_BASE
        env["OFFICE_URL"] = f"{DEV_BASE}/?page=office"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [PYTHON312, TEST_SCRIPT],
            capture_output=True, timeout=60,
            env=env,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")[-500:] if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace")[-300:] if result.stderr else ""
        passed = result.returncode == 0
        return passed, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)


def main():
    report_lines = []
    report_lines.append("# 오피스 모드 E2E 테스트 보고서\n")
    report_lines.append(f"**실행 시각:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report_lines.append(f"**테스트 서버:** localhost:{VITE_PORT}\n")
    report_lines.append("")

    # PTY 서버 확인
    if not check_pty_server():
        report_lines.append("## ❌ PTY 서버 미실행\nPTY 서버(9001)가 응답하지 않습니다.\n")
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        print("PTY 서버 미실행 — 종료")
        return

    # Dev 서버 시작
    print("Vite dev 서버 시작 중...")
    vite_proc = start_dev_server()
    if not check_dev_server():
        report_lines.append("## ❌ Vite dev 서버 시작 실패\n")
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        stop_dev_server(vite_proc)
        print("Vite dev 서버 시작 실패 — 종료")
        return

    print(f"Dev 서버 실행 중 (port {VITE_PORT})")
    report_lines.append("## 테스트 라운드\n")
    report_lines.append("| 라운드 | API 테스트 | Playwright | 시각 |")
    report_lines.append("|--------|-----------|------------|------|")

    consecutive_pass = 0
    total_pass = 0
    total_fail = 0

    for i in range(1, MAX_ROUNDS + 1):
        print(f"\n--- 라운드 {i}/{MAX_ROUNDS} ---")

        # Dev 서버 생존 확인 — 죽었으면 재시작
        if not check_dev_server():
            print("  ⚠️  Dev 서버 죽음 감지 — 재시작 중...")
            stop_dev_server(vite_proc)
            time.sleep(3)
            vite_proc = start_dev_server()
            if not check_dev_server():
                report_lines.append(f"| {i} | ❌ DEV서버 재시작 실패 | ❌ | {datetime.now().strftime('%H:%M:%S')} |")
                total_fail += 1
                consecutive_pass = 0
                continue
            print("  Dev 서버 재시작 완료")

        # API 테스트
        api_pass, api_results = run_api_test()
        api_status = "PASS" if api_pass else "FAIL"
        print(f"  API: {api_status}")
        for k, v in api_results.items():
            status = "✓" if v.get("pass") else "✗"
            print(f"    {status} {k}")

        # Playwright 테스트
        pw_pass, pw_stdout, pw_stderr = run_playwright_test()
        pw_status = "PASS" if pw_pass else "FAIL"
        print(f"  Playwright: {pw_status}")

        now = datetime.now().strftime("%H:%M:%S")
        overall = api_pass and pw_pass

        if overall:
            consecutive_pass += 1
            total_pass += 1
            report_lines.append(f"| {i} | ✅ PASS | ✅ PASS | {now} |")
        else:
            consecutive_pass = 0
            total_fail += 1
            api_detail = ", ".join(k for k, v in api_results.items() if not v.get("pass"))
            report_lines.append(f"| {i} | {'✅' if api_pass else '❌'} {api_status} ({api_detail}) | {'✅' if pw_pass else '❌'} {pw_status} | {now} |")

        print(f"  연속 통과: {consecutive_pass}/{CONSECUTIVE_PASS_TARGET}")

        if consecutive_pass >= CONSECUTIVE_PASS_TARGET:
            print(f"\n🎉 {CONSECUTIVE_PASS_TARGET}회 연속 통과 — 테스트 종료!")
            break

        # 다음 라운드 전 대기
        if i < MAX_ROUNDS:
            time.sleep(10)

    # 결과 요약
    report_lines.append("")
    report_lines.append("## 결과 요약\n")
    report_lines.append(f"- **총 라운드:** {total_pass + total_fail}")
    report_lines.append(f"- **통과:** {total_pass}")
    report_lines.append(f"- **실패:** {total_fail}")
    report_lines.append(f"- **연속 통과:** {consecutive_pass}")

    if consecutive_pass >= CONSECUTIVE_PASS_TARGET:
        report_lines.append(f"\n### ✅ 안정성 확인 완료")
        report_lines.append(f"{CONSECUTIVE_PASS_TARGET}회 연속 통과로 오피스 모드 안정성이 확인되었습니다.")
    else:
        report_lines.append(f"\n### ⚠️ 불안정")
        report_lines.append(f"{MAX_ROUNDS}회 시도 중 {CONSECUTIVE_PASS_TARGET}회 연속 통과에 도달하지 못했습니다.")

    report_lines.append(f"\n**완료 시각:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 보고서 저장
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"\n보고서 저장: {REPORT_PATH}")

    # Dev 서버 종료
    stop_dev_server(vite_proc)
    print("Dev 서버 종료 완료")


if __name__ == "__main__":
    main()
