/*
 * FILE: scripts/mobile_agent_bot.js
 * DESCRIPTION: Termux 노드에서 Telegram 메시지를 Codex 또는 Antigravity CLI로 전달한다.
 *
 * REVISION HISTORY:
 * - 2026-07-26 Codex: APIS2(Codex)와 APIS3(Antigravity) 공용 브릿지 최초 작성.
 */

'use strict';

const fs = require('fs');
const { execFile } = require('child_process');

const home = process.env.HOME;
const token = fs.readFileSync(`${home}/.apis_bot_token`, 'utf8').trim();
const owner = fs.readFileSync(`${home}/.apis_owner`, 'utf8').trim();
const agent = (process.env.APIS_AGENT || fs.readFileSync(`${home}/.apis_agent`, 'utf8').trim()).toLowerCase();
const name = process.env.APIS_NAME || fs.readFileSync(`${home}/.apis_name`, 'utf8').trim();
const api = `https://api.telegram.org/bot${token}`;

let offset = 0;
let busy = false;

const log = (message) => console.log(`[${new Date().toISOString()}] ${message}`);

async function telegram(method, body = {}) {
  const response = await fetch(`${api}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!payload.ok) throw new Error(`${method}: ${payload.description || 'Telegram API error'}`);
  return payload.result;
}

async function send(chatId, text) {
  const value = String(text || '응답이 비어 있습니다.');
  for (let index = 0; index < value.length; index += 3900) {
    await telegram('sendMessage', { chat_id: chatId, text: value.slice(index, index + 3900) });
  }
}

function command(prompt) {
  if (agent === 'codex') {
    return {
      file: 'codex',
      args: ['exec', '--skip-git-repo-check', '--color', 'never', prompt],
    };
  }
  if (agent === 'antigravity') {
    return {
      file: 'antigravity',
      args: ['-p', prompt, '--print-timeout', '10m'],
    };
  }
  throw new Error(`지원하지 않는 에이전트: ${agent}`);
}

function run(prompt) {
  const selected = command(prompt);
  return new Promise((resolve, reject) => {
    execFile(selected.file, selected.args, {
      cwd: `${home}/work`,
      timeout: 10 * 60 * 1000,
      maxBuffer: 8 * 1024 * 1024,
      env: process.env,
    }, (error, stdout, stderr) => {
      const output = String(stdout || '').trim() || String(stderr || '').trim();
      if (error && !output) return reject(error);
      resolve(output || `${name} 실행이 완료됐지만 출력이 없습니다.`);
    });
  });
}

async function handle(message) {
  const chatId = String(message.chat?.id || '');
  const text = String(message.text || '').trim();
  if (!chatId || !text) return;
  if (chatId !== owner) {
    log(`거부된 접근: ${chatId}`);
    return;
  }
  if (text === '/start' || text === '/status') {
    await send(chatId, `${name} 온라인\n에이전트: ${agent}\n상태: ${busy ? '작업 중' : '대기'}`);
    return;
  }
  if (busy) {
    await send(chatId, `${name}이(가) 이미 작업 중입니다.`);
    return;
  }
  busy = true;
  await send(chatId, `${name} 작업을 시작합니다.`);
  try {
    await send(chatId, await run(text));
  } catch (error) {
    await send(chatId, `${name} 실행 오류: ${error.message}`);
  } finally {
    busy = false;
  }
}

async function poll() {
  while (true) {
    try {
      const updates = await telegram('getUpdates', { offset, timeout: 25, allowed_updates: ['message'] });
      for (const update of updates) {
        offset = update.update_id + 1;
        await handle(update.message || {});
      }
    } catch (error) {
      log(error.message);
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }
}

telegram('getMe')
  .then(bot => {
    log(`${name} 시작 (@${bot.username}, ${agent})`);
    return poll();
  })
  .catch(error => {
    log(`시작 실패: ${error.message}`);
    process.exitCode = 1;
  });
