const puppeteer = require('puppeteer');

(async () => {
    console.log("[HIVE VISION] 브라우저(Chrome) 엔진 기동 중...");
    const browser = await puppeteer.launch({ headless: "new" });
    const page = await browser.newPage();
    
    try {
        console.log("[HIVE VISION] http://localhost:8000 접속 시도 중...");
        await page.goto('http://localhost:8000', { waitUntil: 'domcontentloaded', timeout: 10000 });
        
        console.log("[HIVE VISION] React 앱 렌더링 대기 중...");
        await page.waitForSelector('.flex.h-screen', { timeout: 5000 });
        
        console.log("[HIVE VISION] 화면 렌더링 완료. 상단 메뉴바(Header) 분석 시작...");
        
        // 최상단 메뉴바의 텍스트들 추출
        const menuItems = await page.evaluate(() => {
            const menuBar = document.querySelector('.bg-\\[\\#323233\\]'); 
            if (!menuBar) return null;
            
            const buttons = Array.from(menuBar.querySelectorAll('button'));
            return buttons.map(b => b.textContent.trim());
        });
        
        if (menuItems && menuItems.length > 0) {
            console.log("=============================================");
            console.log("[검증 성공] 상단 메뉴바가 완벽하게 렌더링되었습니다!");
            console.log("발견된 메뉴들:", menuItems.join(' | '));
            
            if (menuItems.includes('AI Tools')) {
                console.log("100% 검증 완료: 'AI Tools' 메뉴가 정상적으로 출력되고 있습니다!");
            } else {
                console.log("경고: 'AI Tools' 메뉴가 보이지 않습니다.");
            }
            console.log("=============================================");
        } else {
            console.log("[검증 실패] 상단 메뉴바 요소를 찾지 못했습니다.");
        }
        
    } catch (e) {
        console.log("[접속 오류] 서버가 죽어 있거나 렌더링에 실패했습니다:", e.message);
    } finally {
        await browser.close();
    }
})();
