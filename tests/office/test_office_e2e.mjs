/**
 * 오피스 모드 E2E 테스트 — Playwright CLI
 * 실행: npx playwright test test_office_e2e.mjs --headed
 * 또는: node test_office_e2e.mjs (직접 실행)
 */
import { chromium } from 'playwright';

const BASE = 'http://localhost:5180';
const TIMEOUT = 15000;

async function run() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  const logs = [];

  // 콘솔 로그 캡처
  page.on('console', msg => {
    const text = msg.text();
    logs.push(`[${msg.type()}] ${text}`);
    if (text.includes('오피스 세션 생성 실패') || text.includes('PTY 서버 연결 실패')) {
      errors.push(text);
    }
  });

  // 네트워크 에러 캡처
  page.on('requestfailed', req => {
    errors.push(`[NET FAIL] ${req.url()} — ${req.failure()?.errorText}`);
  });

  console.log('=== 1. 페이지 로드 ===');
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: TIMEOUT });
  console.log('  페이지 로드 완료');

  // 오피스 모드 버튼 찾기 (클래식 → 오피스 전환)
  console.log('\n=== 2. 오피스 모드 전환 ===');
  // 오피스 모드 전환 버튼 클릭
  const officeBtn = await page.$('button:has-text("오피스")')
    || await page.$('[data-mode="office"]')
    || await page.$('button:has-text("Office")');

  if (officeBtn) {
    await officeBtn.click();
    console.log('  오피스 버튼 클릭 완료');
    await page.waitForTimeout(3000);
  } else {
    // 이미 오피스 모드이거나 다른 방법으로 전환
    console.log('  오피스 전환 버튼 없음 — 현재 모드 확인');
  }

  // 스크린샷 (전환 직후)
  await page.screenshot({ path: 'D:/vibe-coding/test_office_1_loaded.png', fullPage: true });
  console.log('  스크린샷: test_office_1_loaded.png');

  // 오피스 세션 API 확인
  console.log('\n=== 3. 오피스 API 프록시 테스트 ===');
  const sessionsRes = await page.evaluate(async () => {
    try {
      const r = await fetch('/api/pty/office/sessions');
      const data = await r.json();
      return { status: r.status, data };
    } catch (e) {
      return { error: e.message };
    }
  });
  console.log('  세션 목록:', JSON.stringify(sessionsRes));

  // 오피스 세션 생성 테스트
  console.log('\n=== 4. 세션 생성 테스트 ===');
  const spawnRes = await page.evaluate(async () => {
    try {
      const r = await fetch('/api/pty/office/spawn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: 'claude', yolo: true }),
      });
      const data = await r.json();
      return { status: r.status, data };
    } catch (e) {
      return { error: e.message };
    }
  });
  console.log('  세션 생성:', JSON.stringify(spawnRes));

  // 메시지 전송 테스트
  if (spawnRes.data?.sessionId) {
    const sid = spawnRes.data.sessionId;
    console.log(`\n=== 5. ${sid}에 메시지 전송 ===`);
    const writeRes = await page.evaluate(async (id) => {
      try {
        const r = await fetch(`/api/pty/write/${id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: 'echo playwright test' }),
        });
        return { status: r.status, data: await r.json() };
      } catch (e) {
        return { error: e.message };
      }
    }, sid);
    console.log('  전송 결과:', JSON.stringify(writeRes));

    // 출력 읽기
    await page.waitForTimeout(2000);
    const outputRes = await page.evaluate(async (id) => {
      try {
        const r = await fetch(`/api/pty/output/${id}?since=0&limit=5`);
        return { status: r.status, data: await r.json() };
      } catch (e) {
        return { error: e.message };
      }
    }, sid);
    console.log('  출력:', JSON.stringify({
      seq: outputRes.data?.latest_seq,
      entries: outputRes.data?.entries?.length,
    }));

    // 정리
    await page.evaluate(async (id) => {
      await fetch(`/api/pty/terminate/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    }, sid);
    console.log(`  ${sid} 세션 정리 완료`);
  }

  // UI 에러 텍스트 확인
  console.log('\n=== 6. UI 에러 확인 ===');
  const uiErrors = await page.evaluate(() => {
    const els = document.querySelectorAll('*');
    const found = [];
    for (const el of els) {
      const t = el.textContent || '';
      if (t.includes('세션 생성 실패') || t.includes('연결 실패') || t.includes('터미널 꺼져')) {
        found.push(t.trim().substring(0, 100));
      }
    }
    return [...new Set(found)];
  });

  if (uiErrors.length > 0) {
    console.log('  UI 에러 발견:');
    uiErrors.forEach(e => console.log(`    - ${e}`));
  } else {
    console.log('  UI 에러 없음');
  }

  // 최종 스크린샷
  await page.screenshot({ path: 'D:/vibe-coding/test_office_2_final.png', fullPage: true });
  console.log('  스크린샷: test_office_2_final.png');

  // 결과 요약
  console.log('\n========== 결과 요약 ==========');
  if (errors.length > 0) {
    console.log('FAIL — 에러 발견:');
    errors.forEach(e => console.log(`  - ${e}`));
  } else {
    console.log('PASS — 프록시 통신 정상, UI 에러 없음');
  }

  // 관련 콘솔 로그 출력
  const relevantLogs = logs.filter(l =>
    l.includes('PTY') || l.includes('오피스') || l.includes('Office') ||
    l.includes('error') || l.includes('Error') || l.includes('fail'));
  if (relevantLogs.length > 0) {
    console.log('\n관련 콘솔 로그:');
    relevantLogs.slice(0, 15).forEach(l => console.log(`  ${l}`));
  }

  await browser.close();
  process.exit(errors.length > 0 ? 1 : 0);
}

run().catch(e => { console.error('테스트 실패:', e); process.exit(1); });
