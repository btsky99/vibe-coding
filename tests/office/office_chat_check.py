"""오피스 채팅 E2E 테스트 — ready 상태 대기 포함"""
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5190/?page=office"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        print("1. 오피스 모드 로드...")
        page.goto(BASE, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        # 2. "에이전트 부팅 중..." placeholder 대기 → ready 전환 대기 (최대 90초)
        print("2. 에이전트 부팅 대기...")
        ready = False
        for i in range(30):
            page.wait_for_timeout(3000)
            inp = page.query_selector('aside input, aside textarea')
            if inp:
                ph = inp.get_attribute('placeholder') or ''
                disabled = inp.get_attribute('disabled') is not None
                print(f"   [{(i+1)*3}초] placeholder='{ph}', disabled={disabled}")
                if '에게...' in ph and not disabled:
                    print("   ✅ ready 상태!")
                    ready = True
                    break
            page.screenshot(path=f"D:/vibe-coding/test_chat_boot_{(i+1)*3}s.png")

        if not ready:
            print("   ❌ 90초 내 ready 안 됨")
            page.screenshot(path="D:/vibe-coding/test_chat_boot_fail.png")
            browser.close()
            return

        # 3. 메시지 전송
        print("3. 메시지 전송...")
        inp = page.query_selector('aside input, aside textarea')
        inp.click()
        inp.fill("안녕 한줄로 자기소개해")
        inp.press("Enter")
        page.screenshot(path="D:/vibe-coding/test_chat_sent.png")

        # 4. 응답 대기 (최대 60초)
        print("4. 응답 대기...")
        for i in range(12):
            page.wait_for_timeout(5000)
            aside = page.query_selector('aside')
            if aside:
                text = aside.inner_text()
                lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 15]
                # "안녕"이 아닌 한글 응답 찾기
                for line in lines:
                    has_korean = any(0xAC00 <= ord(c) <= 0xD7A3 for c in line)
                    if has_korean and '안녕 한줄' not in line and '에게...' not in line and '부팅' not in line:
                        print(f"   [{(i+1)*5}초] 응답: {line[:100]}")
                        page.screenshot(path="D:/vibe-coding/test_chat_response.png")
                        print("   ✅ 응답 수신!")
                        browser.close()
                        return
            print(f"   [{(i+1)*5}초] 대기 중...")

        page.screenshot(path="D:/vibe-coding/test_chat_no_response.png")
        print("   ❌ 60초 내 응답 없음")
        browser.close()

if __name__ == "__main__":
    run()
