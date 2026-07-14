"""
오피스 모드 E2E 테스트 — Playwright (Python)
실행: python test_office_e2e.py
"""
import json
from playwright.sync_api import sync_playwright

import os as _os
BASE = _os.environ.get("BASE", "http://localhost:5180")
OFFICE_URL = _os.environ.get("OFFICE_URL", f"{BASE}/?page=office")
TIMEOUT = 15000

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        console_logs = []

        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        # 1. 페이지 로드
        print("=== 1. 페이지 로드 ===")
        page.goto(BASE, wait_until="domcontentloaded", timeout=TIMEOUT)
        print("  페이지 로드 완료")

        # 2. 오피스 세션 API 테스트
        print("\n=== 2. 오피스 세션 API 프록시 ===")
        sessions = page.evaluate("""async () => {
            try {
                const r = await fetch('/api/pty/office/sessions');
                return { status: r.status, data: await r.json() };
            } catch(e) { return { error: e.message }; }
        }""")
        print(f"  세션 목록: status={sessions.get('status')}, data={json.dumps(sessions.get('data', {}), ensure_ascii=False)[:200]}")
        if sessions.get("error"):
            errors.append(f"세션 목록 실패: {sessions['error']}")

        # 3. 세션 생성
        print("\n=== 3. 세션 생성 ===")
        spawn = page.evaluate("""async () => {
            try {
                const r = await fetch('/api/pty/office/spawn', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ agent: 'claude', yolo: true }),
                });
                return { status: r.status, data: await r.json() };
            } catch(e) { return { error: e.message }; }
        }""")
        sid = spawn.get("data", {}).get("sessionId")
        print(f"  생성 결과: status={spawn.get('status')}, sessionId={sid}")
        if not sid:
            errors.append(f"세션 생성 실패: {spawn}")

        # 4. 메시지 전송
        if sid:
            print(f"\n=== 4. {sid}에 메시지 전송 ===")
            write = page.evaluate(f"""async () => {{
                const r = await fetch('/api/pty/write/{sid}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ text: 'echo playwright-e2e-ok' }}),
                }});
                return {{ status: r.status, data: await r.json() }};
            }}""")
            print(f"  전송: status={write.get('status')}, data={write.get('data')}")

            # 5. 출력 읽기
            page.wait_for_timeout(2000)
            print(f"\n=== 5. {sid} 출력 읽기 ===")
            output = page.evaluate(f"""async () => {{
                const r = await fetch('/api/pty/output/{sid}?since=0&limit=5');
                return {{ status: r.status, data: await r.json() }};
            }}""")
            entries = output.get("data", {}).get("entries", [])
            seq = output.get("data", {}).get("latest_seq", 0)
            print(f"  출력: latest_seq={seq}, entries={len(entries)}")
            if len(entries) == 0:
                errors.append("출력 없음")

            # 정리
            page.evaluate(f"""async () => {{
                await fetch('/api/pty/terminate/{sid}', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                }});
            }}""")
            print(f"  {sid} 정리 완료")

        # 6. 클래식 세션 영향 확인
        print("\n=== 6. 클래식 세션 영향 확인 ===")
        classic = page.evaluate("""async () => {
            const r = await fetch('/api/pty/sessions');
            return await r.json();
        }""")
        running = {k: v["agent"] for k, v in classic.items() if v.get("running")}
        print(f"  클래식 실행 중: {running}")

        # 7. 오피스 모드 UI 전환 + 에러 확인
        print("\n=== 7. 오피스 모드 UI 로드 ===")
        page.goto(OFFICE_URL, wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(5000)  # React lazy 로드 대기
        print("  오피스 모드 로드 완료")

        page.screenshot(path="D:/vibe-coding/test_office_screenshot.png", full_page=True)
        print("  스크린샷: test_office_screenshot.png")

        # UI 에러 텍스트 확인
        ui_errors = page.evaluate("""() => {
            const body = document.body.textContent || '';
            const found = [];
            if (body.includes('세션 생성 실패')) found.push('세션 생성 실패');
            if (body.includes('연결 실패')) found.push('연결 실패');
            if (body.includes('꺼져 있어')) found.push('터미널 꺼져 있어');
            return found;
        }""")
        if ui_errors:
            errors.extend(ui_errors)
            print(f"  UI 에러: {ui_errors}")
        else:
            print("  UI 에러 없음")

        # 관련 콘솔 로그
        relevant = [l for l in console_logs if any(k in l.lower() for k in ["pty", "오피스", "office", "error", "fail", "실패"])]
        if relevant:
            print(f"\n관련 콘솔 로그 ({len(relevant)}건):")
            for l in relevant[:10]:
                print(f"  {l}")

        # 결과
        print("\n" + "=" * 50)
        if errors:
            print(f"FAIL — 에러 {len(errors)}건:")
            for e in errors:
                print(f"  - {e}")
        else:
            print("PASS — 오피스 모드 E2E 테스트 전부 통과!")
        print("=" * 50)

        browser.close()
        return len(errors) == 0

if __name__ == "__main__":
    import sys
    ok = run()
    sys.exit(0 if ok else 1)
