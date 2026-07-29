#!/usr/bin/env node
/**
 * FILE: scripts/remote.js
 * DESCRIPTION: 터미널에서 원격 노드를 골라 접속하는 대화형 런처.
 *   대시보드 앱을 띄우지 않고도 ssh 별칭 목록을 보고 셸/클로드/코덱스를 선택해 붙는다.
 *
 * 사용법:
 *   node scripts/remote.js              # 대화형 선택
 *   node scripts/remote.js lenovo       # 별칭 지정 → 모드만 선택
 *   node scripts/remote.js lenovo claude # 즉시 접속 (선택 없음)
 *   node scripts/remote.js --list       # 목록만 출력하고 종료
 *
 * [WHY Node인가 — 중복 방지]
 *   ssh config 파싱·별칭 규칙(와일드카드 제외, 다중 별칭 대표 선정)·모드 화이트리스트는
 *   이미 pty-server/remote_hosts.js가 소유한다. 파이썬으로 다시 짜면 규칙이 두 벌이 되어
 *   한쪽만 고치는 순간 UI와 CLI의 접속 대상이 달라진다. 같은 모듈을 require해 단일 소스를 지킨다.
 *
 * [제약] 이 스크립트는 stdio를 그대로 물려주므로(inherit) TUI(claude/codex)가 정상 동작한다.
 *   PTY를 흉내 낼 필요가 없다 — 현재 터미널이 이미 PTY다.
 *
 * REVISION HISTORY:
 * - 2026-07-29 Claude: 최초 작성 — 레노버(APIS) 이전에 따른 터미널 기반 원격 접속 수단.
 */

'use strict';

const path = require('path');
const readline = require('readline');
const { spawn } = require('child_process');

// [제약] 프로젝트 루트 기준 상대 경로 — 설치 위치가 어디든 동작해야 한다(하드코딩 금지).
const remoteHosts = require(path.join(__dirname, '..', '.ai_monitor', 'pty-server', 'remote_hosts'));

const C = {
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
  bold: (s) => `\x1b[1m${s}\x1b[0m`,
  cyan: (s) => `\x1b[36m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  yellow: (s) => `\x1b[33m${s}\x1b[0m`,
};

function printHosts(hosts) {
  console.log('');
  console.log(C.bold('  원격 노드'));
  hosts.forEach((h, i) => {
    const addr = `${h.user ? h.user + '@' : ''}${h.hostName || '-'}`;
    const extra = h.aliases.length > 1 ? C.dim(` (${h.aliases.slice(1).join(', ')})`) : '';
    console.log(`   ${C.cyan(String(i + 1))}. ${C.bold(h.alias)}${extra}  ${C.dim(addr)}`);
  });
  console.log('');
}

function ask(rl, q) {
  return new Promise((resolve) => rl.question(q, (a) => resolve(a.trim())));
}

async function main() {
  const argv = process.argv.slice(2);

  if (!remoteHosts.hasSsh()) {
    console.error(C.red('[중단] ssh 실행파일을 찾을 수 없어. (윈도우: OpenSSH 클라이언트 설치 필요)'));
    process.exit(1);
  }

  const hosts = remoteHosts.listHosts();
  if (hosts.length === 0) {
    console.error(C.yellow('[안내] ssh config에 접속 가능한 Host가 없어. 별칭을 먼저 등록해줘.'));
    process.exit(1);
  }

  if (argv.includes('--list') || argv.includes('-l')) {
    printHosts(hosts);
    process.exit(0);
  }

  const modeIds = Object.keys(remoteHosts.MODES);
  let alias = argv[0];
  let mode = argv[1];

  // ── 별칭 선택 ─────────────────────────────────────────────────────────────
  if (!alias) {
    printHosts(hosts);
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const ans = await ask(rl, `  접속할 노드 번호 (1-${hosts.length}, 그냥 Enter=1): `);
    rl.close();
    const idx = ans === '' ? 0 : parseInt(ans, 10) - 1;
    if (!(idx >= 0 && idx < hosts.length)) {
      console.error(C.red('  잘못된 번호야.'));
      process.exit(1);
    }
    alias = hosts[idx].alias;
  }

  // ── 모드 선택 ─────────────────────────────────────────────────────────────
  if (!mode) {
    console.log('');
    modeIds.forEach((id, i) => {
      console.log(`   ${C.cyan(String(i + 1))}. ${remoteHosts.MODES[id].label} ${C.dim(`(${id})`)}`);
    });
    console.log('');
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const ans = await ask(rl, `  실행할 것 (1-${modeIds.length}, 그냥 Enter=1): `);
    rl.close();
    const idx = ans === '' ? 0 : parseInt(ans, 10) - 1;
    if (!(idx >= 0 && idx < modeIds.length)) {
      console.error(C.red('  잘못된 번호야.'));
      process.exit(1);
    }
    mode = modeIds[idx];
  }

  // ── 접속 ──────────────────────────────────────────────────────────────────
  let cmd;
  try {
    cmd = remoteHosts.buildRemoteCommand(alias, mode);
  } catch (e) {
    console.error(C.red(`  [접속 불가] ${e.message}`));
    process.exit(1);
  }

  console.log(C.green(`\n  → ${alias} / ${remoteHosts.MODES[mode].label} 접속 중...\n`));

  // [WHY stdio: 'inherit'] 현재 터미널의 입출력을 그대로 물려줘야 원격 TUI가 화면을 그린다.
  //   파이프로 받으면 claude/codex 화면이 깨진다.
  const child = spawn(cmd.file, cmd.args, { stdio: 'inherit' });
  child.on('exit', (code) => process.exit(code === null ? 1 : code));
  child.on('error', (err) => {
    console.error(C.red(`  [실행 실패] ${err.message}`));
    process.exit(1);
  });
}

main().catch((e) => {
  console.error(C.red(`[오류] ${e.message}`));
  process.exit(1);
});
