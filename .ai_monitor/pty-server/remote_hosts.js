/**
 * FILE: remote_hosts.js
 * DESCRIPTION: SSH 별칭 목록 파싱 + 원격 PTY 실행 명령 조립.
 *   ~/.ssh/config의 Host 별칭을 읽어 UI에 띄울 원격 노드 목록을 만들고,
 *   선택된 별칭·모드를 node-pty가 그대로 spawn할 수 있는 (file, args)로 변환한다.
 *
 * [WHY 별칭만 다루는가 — 맥 이전 대비]
 *   IP·계정·키 경로를 코드나 config에 박으면 기기를 옮길 때마다 코드를 고쳐야 한다.
 *   접속 정보는 전부 ~/.ssh/config가 소유하고 여기서는 별칭 문자열만 다룬다.
 *   → 맥으로 이전할 때 옮길 것은 ssh config 파일 하나뿐이다.
 *
 * [WHY 셸을 거치지 않는가 — 명령 주입 차단]
 *   `sh -c "ssh " + alias` 형태로 조립하면 별칭에 셸 메타문자가 섞일 때 임의 명령이 실행된다.
 *   buildRemoteCommand는 항상 배열 인자를 돌려주고 호출부는 pty.spawn('ssh', args)로 쓴다.
 *   배열 인자는 셸 해석을 거치지 않으므로 주입 경로 자체가 없다. 여기에 더해 alias는
 *   listHosts()가 실제로 파싱해낸 목록에 있는 값만 허용한다(2차 방어).
 *
 * [불변식] mode는 MODES의 3종으로 고정. 새 모드를 늘릴 때도 임의 문자열을 받지 않는다.
 *
 * REVISION HISTORY:
 * - 2026-07-29 Claude: 최초 작성 — 레노버(APIS) 원격 터미널을 UI 슬롯에 붙이기 위한 Phase 1.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

// [제약] claude/codex는 TUI다. ssh에 -t가 없으면 원격에 PTY가 할당되지 않아
// 화면 제어 시퀀스가 먹히지 않고 커서만 깜빡이거나 출력이 뭉개진다.
// shell 모드는 대화형 셸 자체가 PTY를 요구하므로 역시 -t를 준다.
const MODES = {
  shell:  { label: '원격 셸',    remoteCmd: null },
  claude: { label: '원격 클로드', remoteCmd: 'claude' },
  codex:  { label: '원격 코덱스', remoteCmd: 'codex' },
};

function sshConfigPath() {
  // [WHY os.homedir()] 윈도우 C:\Users\x, 맥 /Users/x를 플랫폼 분기 없이 얻는다.
  return path.join(os.homedir(), '.ssh', 'config');
}

/**
 * ~/.ssh/config에서 접속 가능한 Host 별칭을 뽑는다.
 *
 * [제약] Include 지시자는 따라가지 않는다 — 이 프로젝트의 config는 단일 파일이고,
 *   Include를 재귀 파싱하면 경로 탈출 검증까지 필요해져 이득 대비 복잡도가 크다.
 *   Include를 쓰기 시작하면 여기서 목록이 비어 보이는 것으로 드러난다.
 *
 * @returns {Array<{alias:string, aliases:string[], hostName:string, user:string}>}
 */
function listHosts() {
  const cfg = sshConfigPath();
  // [WHY 빈 배열] config가 없는 것은 오류가 아니라 "원격 노드 미설정" 상태다.
  // 맥 새 기기나 SSH를 안 쓰는 사용자에게 에러를 띄우면 안 된다.
  if (!fs.existsSync(cfg)) return [];

  let text;
  try {
    text = fs.readFileSync(cfg, 'utf8');
  } catch (e) {
    console.log(`[REMOTE] ssh config 읽기 실패(무시): ${e.message}`);
    return [];
  }

  const hosts = [];
  let current = null;

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    // ssh_config의 키워드는 대소문자를 구분하지 않는다(Host/host/HOST 전부 유효).
    const m = line.match(/^(\S+)\s+(.*)$/);
    if (!m) continue;
    const key = m[1].toLowerCase();
    const value = m[2].trim();

    if (key === 'host') {
      const aliases = value.split(/\s+/).filter(Boolean);
      // [WHY 와일드카드 제외] `Host *`는 전역 기본값 블록이지 접속 대상이 아니다.
      // 이걸 목록에 넣으면 UI에 접속 불가능한 카드가 뜬다.
      const concrete = aliases.filter((a) => !a.includes('*') && !a.includes('?'));
      if (concrete.length === 0) { current = null; continue; }
      // 대표 별칭 = 첫 번째. 나머지는 같은 기기의 다른 이름이므로 카드를 늘리지 않는다.
      current = { alias: concrete[0], aliases: concrete, hostName: '', user: '' };
      hosts.push(current);
    } else if (current && key === 'hostname') {
      current.hostName = value;
    } else if (current && key === 'user') {
      current.user = value;
    }
  }

  return hosts;
}

/**
 * ssh 실행 파일이 있는지 확인한다.
 *
 * [과거사고 2026-07-29] 레노버에 OpenSSH **Server**만 깔려 있고 Client가 없어
 *   ssh/ssh-keygen이 CommandNotFoundException으로 죽었다. 윈도우에서 서버와 클라이언트는
 *   별개 Capability라 sshd가 멀쩡히 돌아도 ssh가 없을 수 있다.
 *   → 이 값이 false면 UI가 카드를 비활성으로 그려 "왜 안 되지"를 없앤다.
 */
function resolveSshPath() {
  // [🔴 과거사고 2026-07-29] pty.spawn('ssh', ...)로 이름만 넘기면 node-pty(윈도우 ConPTY)가
  //   PATH 탐색을 하지 않아 `File not found:` 로 즉사한다. 셸을 거치지 않는 대가로
  //   실행파일 해석을 우리가 해야 한다 → 항상 절대경로를 넘긴다.
  const exe = process.platform === 'win32' ? 'ssh.exe' : 'ssh';
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  for (const d of dirs) {
    try {
      const p = path.join(d, exe);
      if (fs.existsSync(p)) return p;
    } catch (_) { /* 접근 불가 디렉토리는 건너뛴다 */ }
  }
  return null;
}

function hasSsh() {
  return resolveSshPath() !== null;
}

/**
 * 원격 실행 명령을 조립한다. 반환값은 pty.spawn(file, args)에 그대로 넣는다.
 *
 * @param {string} alias  ~/.ssh/config에 존재하는 Host 별칭
 * @param {string} mode   'shell' | 'claude' | 'codex'
 * @returns {{file:string, args:string[]}}
 * @throws {Error} 별칭이 목록에 없거나 모드가 허용되지 않을 때
 */
function buildRemoteCommand(alias, mode) {
  if (!MODES[mode]) {
    throw new Error(`허용되지 않은 원격 모드: ${mode}`);
  }
  // [불변식] 화이트리스트 검증 — 사용자가 보낸 별칭을 그대로 신뢰하지 않는다.
  // 배열 인자라 셸 주입은 이미 불가능하지만, 존재하지 않는 호스트로 spawn해
  // 알 수 없는 에러를 터뜨리는 것보다 여기서 끊는 편이 진단이 쉽다.
  const known = listHosts().some((h) => h.aliases.includes(alias));
  if (!known) {
    throw new Error(`ssh config에 없는 별칭: ${alias}`);
  }

  const sshPath = resolveSshPath();
  if (!sshPath) {
    throw new Error('ssh 실행파일을 찾을 수 없음 (윈도우: OpenSSH 클라이언트 미설치)');
  }

  const remoteCmd = MODES[mode].remoteCmd;
  // -t: 원격에 PTY 강제 할당. 로컬이 이미 PTY라도 ssh는 명령 지정 시 기본으로 PTY를 안 준다.
  const args = remoteCmd ? ['-t', alias, remoteCmd] : ['-t', alias];
  return { file: sshPath, args };
}

module.exports = { listHosts, hasSsh, resolveSshPath, buildRemoteCommand, MODES };
