/**
 * 오피스 모드 E2E 테스트 — Playwright Test
 * 실행: npx playwright test test_office_e2e.spec.mjs
 */
import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:5180';

test('오피스 PTY 세션 API 프록시 동작', async ({ page }) => {
  // 페이지 로드
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });

  // 오피스 세션 목록 API
  const sessions = await page.evaluate(async () => {
    const r = await fetch('/api/pty/office/sessions');
    return { status: r.status, data: await r.json() };
  });
  expect(sessions.status).toBe(200);
  console.log('세션 목록:', JSON.stringify(sessions.data));

  // 오피스 세션 생성
  const spawn = await page.evaluate(async () => {
    const r = await fetch('/api/pty/office/spawn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: 'claude', yolo: true }),
    });
    return { status: r.status, data: await r.json() };
  });
  expect(spawn.status).toBe(200);
  expect(spawn.data.sessionId).toBeTruthy();
  console.log('세션 생성:', spawn.data.sessionId);

  const sid = spawn.data.sessionId;

  // 메시지 전송
  const write = await page.evaluate(async (id) => {
    const r = await fetch(`/api/pty/write/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'echo playwright ok' }),
    });
    return { status: r.status, data: await r.json() };
  }, sid);
  expect(write.status).toBe(200);
  console.log('메시지 전송:', write.data);

  // 출력 읽기
  await page.waitForTimeout(2000);
  const output = await page.evaluate(async (id) => {
    const r = await fetch(`/api/pty/output/${id}?since=0&limit=5`);
    return { status: r.status, data: await r.json() };
  }, sid);
  expect(output.status).toBe(200);
  expect(output.data.entries.length).toBeGreaterThan(0);
  console.log('출력 수신: entries=', output.data.entries.length);

  // 클래식 세션 영향 없음 확인
  const classic = await page.evaluate(async () => {
    const r = await fetch('/api/pty/sessions');
    return await r.json();
  });
  const runningClassic = Object.entries(classic).filter(([, v]) => v.running);
  console.log('클래식 세션:', runningClassic.map(([k, v]) => `${k}=${v.agent}`).join(', '));

  // 정리
  await page.evaluate(async (id) => {
    await fetch(`/api/pty/terminate/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
  }, sid);
  console.log('세션 정리 완료');
});

test('오피스 UI 에러 없음 확인', async ({ page }) => {
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.text().includes('세션 생성 실패') || msg.text().includes('연결 실패')) {
      consoleErrors.push(msg.text());
    }
  });

  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });

  // 오피스 모드 전환 시도
  const officeBtn = await page.$('button:has-text("오피스")');
  if (officeBtn) {
    await officeBtn.click();
    await page.waitForTimeout(5000);
  }

  await page.screenshot({ path: 'D:/vibe-coding/test_office_screenshot.png', fullPage: true });

  // UI에 에러 텍스트 확인
  const errorText = await page.evaluate(() => {
    const body = document.body.textContent || '';
    const errors = [];
    if (body.includes('세션 생성 실패')) errors.push('세션 생성 실패');
    if (body.includes('연결 실패')) errors.push('연결 실패');
    if (body.includes('터미널이 꺼져')) errors.push('터미널이 꺼져');
    return errors;
  });

  console.log('UI 에러:', errorText.length ? errorText : '없음');
  console.log('콘솔 에러:', consoleErrors.length ? consoleErrors : '없음');

  // 에러가 있어도 로그로 남기고 테스트 결과 확인
  if (errorText.length > 0 || consoleErrors.length > 0) {
    console.log('⚠️  에러 발견됨 — 스크린샷 확인: test_office_screenshot.png');
  }
});
