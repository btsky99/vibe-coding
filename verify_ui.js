const puppeteer = require('puppeteer');

(async () => {
    console.log("[HIVE VISION] 브라우저(Chrome) 엔진 기동 중...");
    const browser = await puppeteer.launch({ 
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();
    
    // 화면 크기 설정 (일반적인 모니터 해상도)
    await page.setViewport({ width: 1280, height: 800 });
    
    try {
        console.log("[HIVE VISION] http://localhost:8000 접속 시도 중...");
        await page.goto('http://localhost:8000', { waitUntil: 'networkidle2', timeout: 30000 });
        
        console.log("[HIVE VISION] React 앱 렌더링 대기 중...");
        await page.waitForSelector('.flex.h-screen', { timeout: 10000 });
        
        // 1. 터미널 모드 진입 시도 (첫 번째 터미널의 CLAUDE 버튼 클릭)
        console.log("[HIVE VISION] 터미널 모드 활성화 시도 (CLAUDE 버튼 클릭)...");
        const claudeBtn = await page.$('button:link-text("CLAUDE")'); // 실제 버튼 텍스트로 찾기
        
        // 텍스트로 버튼을 찾기 위해 evaluate 사용
        await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const target = buttons.find(b => b.textContent.trim() === 'CLAUDE');
            if (target) target.click();
        });
        
        await new Promise(r => setTimeout(r, 2000)); // 렌더링 대기
        
        console.log("[HIVE VISION] 하단 요소 검증 시작...");
        
        const uiStatus = await page.evaluate(() => {
            const results = {
                topMenuBar: false,
                terminalInputBar: false,
                isInputBarVisible: false,
                inputBarRect: null,
                viewportHeight: window.innerHeight,
                bottomCuttingDetected: false
            };
            
            // 상단 메뉴바 체크
            const menuBar = document.querySelector('.h-7.bg-\\[\\#323233\\]');
            results.topMenuBar = !!menuBar;
            
            // 하단 입력 바 체크
            const inputBar = document.querySelector('input[placeholder*="터미널 명령어 전송"]');
            if (inputBar) {
                const parentContainer = inputBar.closest('.border-t');
                results.terminalInputBar = !!parentContainer;
                
                if (parentContainer) {
                    const rect = parentContainer.getBoundingClientRect();
                    results.inputBarRect = {
                        top: rect.top,
                        bottom: rect.bottom,
                        height: rect.height
                    };
                    
                    // 하단 잘림 판단: 요소의 bottom이 뷰포트 height보다 크면 잘린 것임
                    if (rect.bottom > window.innerHeight) {
                        results.bottomCuttingDetected = true;
                    }
                    
                    // 가시성 판단: 높이가 0보다 크고 화면 안에 있음
                    results.isInputBarVisible = rect.height > 0 && rect.top < window.innerHeight;
                }
            }
            
            return results;
        });
        
        console.log("================ UI 검증 리포트 ================");
        console.log(`[상단 메뉴바] ${uiStatus.topMenuBar ? '✅ 정상' : '❌ 미발견'}`);
        console.log(`[하단 입력바] ${uiStatus.terminalInputBar ? '✅ 발견' : '❌ 미발견'}`);
        
        if (uiStatus.terminalInputBar) {
            console.log(`[입력바 가시성] ${uiStatus.isInputBarVisible ? '✅ 보임' : '❌ 안보임'}`);
            console.log(`[하단 잘림 현상] ${uiStatus.bottomCuttingDetected ? '🚨 탐지됨 (FAIL)' : '✅ 없음 (PASS)'}`);
            console.log(` - 뷰포트 높이: ${uiStatus.viewportHeight}px`);
            console.log(` - 입력바 위치(Bottom): ${uiStatus.inputBarRect.bottom}px`);
        }
        
        // 스크린샷 저장
        await page.screenshot({ path: 'temp_screenshot_final.png', fullPage: false });
        console.log("[HIVE VISION] 스크린샷 저장 완료: temp_screenshot_final.png");
        console.log("================================================");
        
    } catch (e) {
        console.log("[검증 오류] 테스트 실행 중 오류 발생:", e.message);
    } finally {
        await browser.close();
    }
})();
