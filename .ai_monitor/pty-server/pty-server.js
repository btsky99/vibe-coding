/**
 * FILE: pty-server/pty-server.js
 * DESCRIPTION: node-pty 기반 PTY 마이크로서비스.
 *   Vibe Coding 대시보드의 터미널 백엔드를 담당합니다.
 *   WebSocket으로 xterm.js 프론트엔드와 통신하고,
 *   REST API로 Python 서버(agent_api, pty_api)와 세션 정보를 공유합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-22 Claude: 초기 구현 — Python pywinpty PTY 핸들러 대체
 */

'use strict';

const os = require('os');
const path = require('path');
const { URL } = require('url');
const pty = require('node-pty');
const WebSocket = require('ws');
const express = require('express');
const http = require('http');
const { spawn } = require('child_process');

// ── 설정 ──────────────────────────────────────────────────────────────────
const PTY_PORT = parseInt(process.env.PTY_PORT || '9001', 10);
const PYTHON_HTTP_PORT = parseInt(process.env.HTTP_PORT || '9000', 10);
const PROJECT_ROOT = process.env.PROJECT_ROOT || path.resolve(__dirname, '..', '..');

// Git Bash 경로 — Gemini/Codex는 bash에서 실행해야 셸 호환성 문제 방지
const BASH_EXE = 'C:\\Program Files\\Git\\usr\\bin\\bash.exe';
const fs = require('fs');
const BASH_AVAILABLE = fs.existsSync(BASH_EXE);

// ── 세션 저장소 ───────────────────────────────────────────────────────────
// Map<sessionId, { pty, socket, agent, yolo, started, cwd, lastLine, mainModel, bgModel, attached, detachedAt, detachTimer }>
const ptySessions = new Map();
// Map<sessionId, Array<{seq, text}>> — 최근 출력 버퍼 (최대 400줄)
const ptyOutputBuffers = new Map();
// Map<sessionId, number> — 출력 시퀀스 카운터
const ptyOutputSeq = new Map();

const OUTPUT_BUFFER_MAX = 400;
const REPLAY_LINES_ON_ATTACH = 200;
const DETACH_GRACE_MS = parseInt(process.env.PTY_DETACH_GRACE_MS || String(30 * 60 * 1000), 10);

// ── Phase 2-5.3b: idle TTL 워커 설정 ───────────────────────────────────────
// DETACH_GRACE_MS와 별도. DETACH_GRACE는 socket 끊긴 후 PTY 즉시 종료,
// TTL_MS는 attach 여부와 무관하게 lastInput/Output 누적 idle 기준.
const PTY_TTL_MS = parseInt(process.env.PTY_TTL_MS || String(60 * 60 * 1000), 10);
const PTY_IDLE_THRESHOLD_MS = parseInt(process.env.PTY_IDLE_THRESHOLD_MS || String(10 * 60 * 1000), 10);
const PTY_TTL_SWEEP_MS = parseInt(process.env.PTY_TTL_SWEEP_MS || String(5 * 60 * 1000), 10);

// ANSI 이스케이프 코드 제거용 정규식
const ANSI_ESCAPE = /\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;

// ── 프로젝트 격리 키 헬퍼 (Phase 2-5.3a) ──────────────────────────────────
// 백엔드 infra/project_context.py::slugify와 동일 규칙. 프로젝트 rename 비지원
// (config.json 편집 후 앱 재시작 필요. 슬러그 바뀌면 기존 풀 고립).
function slugifyProjectPath(p) {
  if (!p) return '';
  return String(p)
    .replace(/\\/g, '/')
    .replace(/:/g, '')
    .replace(/\//g, '--')
    .replace(/^-+/, '');
}

function sessionKey(projectId, slotId) {
  const pid = (projectId && String(projectId).trim()) || '_default';
  return `${pid}:${slotId}`;
}

function parseSessionKey(key) {
  const idx = String(key).indexOf(':');
  if (idx < 0) return { projectId: '_default', slotId: String(key) };
  return { projectId: key.slice(0, idx), slotId: key.slice(idx + 1) };
}

function _resolvePidFromQuery(searchParams, cwd) {
  const explicit = (searchParams && searchParams.get('project_id') || '').trim();
  if (explicit) return explicit;
  const fromCwd = slugifyProjectPath(cwd || '');
  return fromCwd || '_default';
}

// 로그 출력용: 키에서 슬롯 ID만 추출 (T1, T101, TO1 등 표기 유지).
function displayId(sessionId) {
  return parseSessionKey(sessionId).slotId;
}

function terminalLabel(slotId) {
  const sid = String(slotId || '').trim();
  return sid.startsWith('T') ? sid : `T${sid}`;
}

function agentHeartbeatId(agent, slotId) {
  return `${String(agent || 'unknown').toLowerCase()}:${terminalLabel(slotId)}`;
}

function meaningfulTaskLine(line) {
  const text = String(line || '')
    .replace(ANSI_ESCAPE, '')
    .replace(/[\x00-\x1f\x7f-\x9f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (text.length < 6) return '';
  if (/^[\u2800-\u28ff\s|/\\\-_.:;]+$/.test(text)) return '';
  if (/^(Bi|ought for|vibe-coding|[0-9]+;)/i.test(text)) return '';
  if (text.length > 220) return text.slice(0, 220);
  return text;
}

function updateSessionTaskFromLine(session, line, preferInput = false) {
  if (!session) return;
  const taskLine = meaningfulTaskLine(line);
  if (!taskLine) return;

  if (preferInput || !session.currentTask || /^(PTY|세션|\[PTY\])/i.test(session.currentTask)) {
    session.currentTask = taskLine;
    return;
  }

  if (/(진행|작업|수정|검증|테스트|빌드|커밋|완료|Phase|Task|TODO|plan|implement|fix|refactor)/i.test(taskLine)) {
    session.currentTask = taskLine;
  }
}

function sendPtyHeartbeat(sessionId, status = 'running', force = false) {
  const session = ptySessions.get(sessionId);
  if (!session || !session.agent) return;

  const now = Date.now();
  if (!force && session.lastHeartbeatAt && now - session.lastHeartbeatAt < 5000) return;
  session.lastHeartbeatAt = now;

  const payload = JSON.stringify({
    agent: session.agent,
    terminal_id: terminalLabel(session.slotId || displayId(sessionId)),
    agent_id: agentHeartbeatId(session.agent, session.slotId || displayId(sessionId)),
    status,
    current_task: session.currentTask || `[PTY] ${String(session.agent).toUpperCase()} 세션 활성`,
    project_id: session.projectId || parseSessionKey(sessionId).projectId,
    cwd: session.cwd || '',
    last_line: session.lastLine || '',
  });

  const req = http.request({
    hostname: '127.0.0.1',
    port: PYTHON_HTTP_PORT,
    path: '/api/agent/heartbeat',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
    timeout: 2000,
  });

  req.on('error', () => {});
  req.on('timeout', () => req.destroy());
  req.write(payload);
  req.end();
}

setInterval(() => {
  for (const sessionId of ptySessions.keys()) {
    sendPtyHeartbeat(sessionId, 'running');
  }
}, 15000);

// ── 출력 버퍼 관리 ────────────────────────────────────────────────────────
/**
 * PTY 출력을 세션 버퍼에 추가합니다.
 * ANSI 코드를 제거하고 줄 단위로 분리하여 저장합니다.
 * agent_api.py가 REST로 조회할 때 사용됩니다.
 */
function appendPtyOutput(sessionId, rawData) {
  if (!ptyOutputBuffers.has(sessionId)) return;

  const clean = rawData.replace(ANSI_ESCAPE, '').replace(/\r/g, '\n');
  const lines = clean.split('\n').filter(l => l.trim().length > 2);

  const buffer = ptyOutputBuffers.get(sessionId);
  let seq = ptyOutputSeq.get(sessionId) || 0;

  for (const line of lines) {
    seq++;
    buffer.push({ seq, text: line.trim().substring(0, 200) });
    // 버퍼 크기 제한
    if (buffer.length > OUTPUT_BUFFER_MAX) {
      buffer.shift();
    }
  }

  ptyOutputSeq.set(sessionId, seq);
}

/**
 * Codex PTY 스트림 정규화.
 * winpty가 가끔 CR을 이중으로 보내는 현상만 보정합니다.
 * xterm.js가 ANSI 코드를 직접 처리하므로 이스케이프는 그대로 통과.
 */
function normalizeCodexStream(data) {
  return data.replace(/\r\r\n/g, '\r\n');
}

function getSubmitEnterSequence(_agent) {
  // Telegram/REST injection should mirror the frontend terminal path:
  // a single Enter submits once. The old double-CR path could leave Codex/Gemini
  // waiting for one more manual Enter on subsequent prompts.
  return '\r';
}

function clearDetachTimer(session) {
  if (!session || !session.detachTimer) return;
  clearTimeout(session.detachTimer);
  session.detachTimer = null;
}

function clearSessionState(sessionId) {
  const session = ptySessions.get(sessionId);
  if (session) {
    clearDetachTimer(session);
  }
  ptySessions.delete(sessionId);
  ptyOutputBuffers.delete(sessionId);
  ptyOutputSeq.delete(sessionId);
}

function killSessionPty(sessionId, reason = 'terminated') {
  const session = ptySessions.get(sessionId);
  if (!session || !session.pty) return false;

  clearDetachTimer(session);
  console.log(`[PTY] 세션 종료 요청: T${displayId(sessionId)} reason=${reason}`);

  try {
    session.pty.kill();
    return true;
  } catch (err) {
    console.log(`[PTY] PTY 종료 실패: T${displayId(sessionId)} ${err.message}`);
    clearSessionState(sessionId);
    return false;
  }
}

function scheduleDetachedCleanup(sessionId) {
  const session = ptySessions.get(sessionId);
  if (!session) return;

  clearDetachTimer(session);
  session.attached = false;
  session.detachedAt = new Date().toISOString();
  session.detachTimer = setTimeout(() => {
    const current = ptySessions.get(sessionId);
    if (!current || current.attached) return;
    console.log(`[PTY] 재연결 유예시간 만료: T${displayId(sessionId)} -> PTY 종료`);
    killSessionPty(sessionId, 'detach_timeout');
  }, DETACH_GRACE_MS);
}

// ── Phase 2-5.3b: idle TTL 정리 헬퍼 ──────────────────────────────────────
// 정리 대상 조건:
//   - !attached            (사용자가 보고 있지 않음)
//   - !yolo                (장기 실행 의도 명시 면제)
//   - !slotId.startsWith('O')  (오피스 풀 면제 — 별도 정책)
//   - 세션 시작 후 TTL_MS 경과
//   - lastInputAt/lastOutputAt 모두 IDLE_THRESHOLD_MS 무변화
function isSessionIdleForCleanup(session, now) {
  if (!session) return false;
  if (session.attached) return false;
  if (session.yolo) return false;
  if (String(session.slotId || '').startsWith('O')) return false;

  // detachedAt이 명시된 persistent 세션만 정리 대상.
  // legacy 핸들러(handlePtyConnectionLegacy)는 detachedAt 필드를 쓰지 않으므로
  // 살아있는 동안 절대 자동 종료되지 않는다.
  const detachedMs = Date.parse(session.detachedAt || '');
  if (!Number.isFinite(detachedMs)) return false;
  if ((now - detachedMs) <= PTY_TTL_MS) return false;

  const lastIn = Number(session.lastInputAt) || 0;
  const lastOut = Number(session.lastOutputAt) || 0;
  if ((now - lastIn) <= PTY_IDLE_THRESHOLD_MS) return false;
  if ((now - lastOut) <= PTY_IDLE_THRESHOLD_MS) return false;

  return true;
}

function replayBufferedOutput(sessionId, ws) {
  const buffer = ptyOutputBuffers.get(sessionId) || [];
  if (!buffer.length || ws.readyState !== WebSocket.OPEN) return;

  const replay = buffer
    .slice(-REPLAY_LINES_ON_ATTACH)
    .map(entry => entry.text)
    .join('\r\n');

  if (!replay) return;

  ws.send(
    `\r\n\x1b[38;5;39m[HIVE] 기존 PTY 세션 T${displayId(sessionId)}에 재부착했습니다.\x1b[0m\r\n` +
    `\x1b[38;5;244m최근 출력 ${Math.min(buffer.length, REPLAY_LINES_ON_ATTACH)}줄을 복원합니다.\x1b[0m\r\n` +
    `${replay}\r\n`
  );
}

function attachSocketToSession(ws, sessionId, agent) {
  const session = ptySessions.get(sessionId);
  if (!session || !session.pty) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close(1011, 'PTY session missing');
    }
    return;
  }

  const ptyProcess = session.pty;
  let wsInputBuf = [];
  let wsInitDone = false;

  session.socket = ws;
  session.attached = true;
  session.detachedAt = '';
  clearDetachTimer(session);

  setTimeout(() => { wsInitDone = true; }, 1500);

  ws.on('message', (message) => {
    try {
      const msgStr = typeof message === 'string' ? message : message.toString('utf-8');

      if (msgStr.startsWith('{') && msgStr.endsWith('}')) {
        try {
          const data = JSON.parse(msgStr);
          if (data.type === 'resize') {
            const newCols = parseInt(data.cols, 10) || 80;
            const newRows = parseInt(data.rows, 10) || 24;
            ptyProcess.resize(newCols, newRows);
            return;
          }
        } catch (_) {
          // JSON 파싱 실패 시 일반 입력으로 처리
        }
      }

      // idle TTL 워커용: 사용자 키 입력 시각 갱신 (resize 제외)
      const inputSession = ptySessions.get(sessionId);
      if (inputSession) inputSession.lastInputAt = Date.now();

      const processed = msgStr.replace(/\r\n/g, '\r').replace(/\n/g, '\r');

      if (processed.includes('\r')) {
        const segments = processed.split('\r');
        for (let idx = 0; idx < segments.length; idx++) {
          const segment = segments[idx];
          if (segment) {
            if (wsInitDone) {
              if ((segment === '\x7f' || segment === '\x08') && wsInputBuf.length > 0) {
                wsInputBuf.pop();
              } else {
                wsInputBuf.push(segment);
              }
            }
            ptyProcess.write(segment);
          }

          if (idx < segments.length - 1) {
            if (wsInitDone && wsInputBuf.length > 0) {
              const completedLine = wsInputBuf.join('');
              wsInputBuf = [];
              const cleaned = completedLine.replace(/[\x00-\x1f\x7f-\x9f]/g, '').trim();
              const current = ptySessions.get(sessionId);
              if (current && cleaned.length >= 4) {
                updateSessionTaskFromLine(current, cleaned, true);
                sendPtyHeartbeat(sessionId, 'running', true);
              }
              if (cleaned.length >= 4 && !agent) {
                dispatchToAgent(cleaned, ptyProcess);
              }
            }

            const enterStr = getSubmitEnterSequence(agent);
            ptyProcess.write(enterStr);
          }
        }
      } else {
        if (wsInitDone) {
          if ((msgStr === '\x7f' || msgStr === '\x08') && wsInputBuf.length > 0) {
            wsInputBuf.pop();
          } else if (!processed.includes('\r')) {
            wsInputBuf.push(msgStr);
          }
        }
        ptyProcess.write(processed);
      }
    } catch (err) {
      console.error(`[WS ERROR] ${err.message}`);
    }
  });

  ws.on('close', (code) => {
    console.log(`[PTY] WebSocket 닫힘: T${displayId(sessionId)} code=${code}`);

    const current = ptySessions.get(sessionId);
    if (!current || current.socket !== ws) {
      return;
    }

    current.socket = null;

    if (code === 1000) {
      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} 연결 종료 (정상 종료) ───`,
          'success'
        );
      }
      killSessionPty(sessionId, 'client_close');
      return;
    }

    scheduleDetachedCleanup(sessionId);
  });

  ws.on('error', (err) => {
    console.error(`[WS ERROR] T${displayId(sessionId)}: ${err.message}`);
  });
}

// ── Python 서버에 세션 로그 전송 ──────────────────────────────────────────
/**
 * Python 서버의 /api/log 엔드포인트로 세션 시작/종료 로그를 전송합니다.
 * 실패해도 터미널 동작에는 영향 없도록 fire-and-forget 방식.
 */
function sendSessionLog(sessionId, agent, message, status) {
  const payload = JSON.stringify({
    session_id: sessionId,
    terminal_id: 'PTY_TERMINAL',
    agent: agent.charAt(0).toUpperCase() + agent.slice(1),
    trigger_msg: message,
    project: 'hive',
    status: status
  });

  const req = http.request({
    hostname: '127.0.0.1',
    port: PYTHON_HTTP_PORT,
    path: '/api/log',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload)
    }
  });

  req.on('error', (err) => {
    console.log(`[PTY] 세션 로그 전송 실패: ${err.message}`);
  });

  req.write(payload);
  req.end();
}

// ── Codex 모델 감지 ───────────────────────────────────────────────────────
function getCodexMainModel() {
  return process.env.CODEX_MODEL || '';
}

// ── WebSocket PTY 핸들러 ──────────────────────────────────────────────────
/**
 * 프론트엔드 TerminalSlot.tsx에서 WebSocket 연결이 들어오면
 * node-pty로 셸을 spawn하고 양방향 스트리밍을 설정합니다.
 *
 * URL 형식: /pty/slot{0-31}?agent={claude|gemini|codex}&cwd={path}&cols=80&rows=24&yolo=false&model=...&name=...
 *
 * 프로토콜:
 *   Client → Server: 일반 텍스트(키 입력) 또는 JSON({type:'resize',cols,rows})
 *   Server → Client: 일반 텍스트(PTY 출력, ANSI 포함)
 */
function handlePtyConnectionLegacy(ws, req) {
  let ptyProcess = null;
  let sessionId = null;
  let slotId = null;

  try {
    // ── URL 파싱 ──────────────────────────────────────────────────────
    const url = new URL(req.url, `http://127.0.0.1:${PTY_PORT}`);
    const agent = url.searchParams.get('agent') || '';
    // CWD 결정: 프론트엔드가 보낸 경로 → PROJECT_ROOT → 사용자 홈 순으로 폴백
    // pip 설치 환경에서 PROJECT_ROOT가 site-packages 하위라 유효하지 않을 수 있음
    // 에러 267 (ERROR_DIRECTORY) 방지를 위해 실제 존재하는 디렉토리인지 검증
    let cwd = url.searchParams.get('cwd') || PROJECT_ROOT;
    if (!fs.existsSync(cwd)) {
      console.log(`[PTY] CWD 유효하지 않음: ${cwd} → 사용자 홈으로 폴백`);
      cwd = os.homedir();
    }
    const cols = parseInt(url.searchParams.get('cols') || '80', 10);
    const rows = parseInt(url.searchParams.get('rows') || '24', 10);
    const isYolo = url.searchParams.get('yolo') === 'true';

    // ── 세션 ID 계산 (Phase 2-5.3a: 프로젝트 격리 복합 키) ──────────
    // slotId: 외부 표시/TERMINAL_ID env용 (T1, T8 등 — UI/wrapper 호환)
    // sessionId: 내부 Map 키 — `{project_id}:{slotId}` (탭별 풀 격리)
    const projectId = _resolvePidFromQuery(url.searchParams, cwd);
    const slotMatch = req.url.match(/\/pty\/slot(\d+)/);
    slotId = slotMatch ? String(parseInt(slotMatch[1], 10) + 1) : String(Date.now());
    sessionId = sessionKey(projectId, slotId);

    // ── 환경변수 구성 ─────────────────────────────────────────────────
    // Python 서버와 동일한 환경변수를 PTY 프로세스에 주입합니다.
    // TERMINAL_ID는 외부 약속(slot 번호) 유지 — wrapper/docs가 T1, T2 형식 기대.
    const env = Object.assign({}, process.env, {
      PYTHONIOENCODING: 'utf-8',
      LANG: 'ko_KR.UTF-8',
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      PYTHONLEGACYWINDOWSSTDIO: '0',
      TERMINAL_ID: slotId,
      // instructor 패키지의 deprecated google.generativeai FutureWarning 억제
      PYTHONWARNINGS: 'ignore::FutureWarning',
    });

    // 에이전트별 HIVE_AGENT 환경변수
    if (agent) {
      env.HIVE_AGENT = agent;
    }

    // Claude 비용 최적화: 백그라운드 작업에 Haiku 사용
    if (agent === 'claude' && !process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL) {
      env.ANTHROPIC_DEFAULT_HAIKU_MODEL = 'claude-haiku-4-5-20251001';
    }

    // ── 셸 선택 ───────────────────────────────────────────────────────
    // Claude: cmd.exe (정상 동작)
    // Gemini/Codex/Shell(개발용): Git Bash (CMD에서 실행 시 셸 호환성 에러 발생)
    let shell, shellArgs;
    if ((agent === 'gemini' || agent === 'codex' || agent === 'shell') && BASH_AVAILABLE) {
      shell = BASH_EXE;
      shellArgs = ['--login'];
    } else {
      shell = 'cmd.exe';
      shellArgs = [];
    }

    // ── node-pty 스폰 ─────────────────────────────────────────────────
    ptyProcess = pty.spawn(shell, shellArgs, {
      name: 'xterm-256color',
      cols: cols,
      rows: rows,
      cwd: cwd,
      env: env,
      // Windows ConPTY 사용 (node-pty 기본값)
      useConpty: true,
    });

    console.log(`[PTY] 세션 시작: T${slotId} agent=${agent} pid=${ptyProcess.pid} project=${projectId}`);

    // ── 에이전트별 시작 명령 ──────────────────────────────────────────
    if (agent === 'claude') {
      const yoloFlag = isYolo ? ' --dangerously-skip-permissions' : '';
      ptyProcess.write(`chcp 65001 >nul & claude${yoloFlag}\r\n`);
    } else if (agent === 'gemini') {
      const yoloFlag = isYolo ? ' -y' : '';
      ptyProcess.write(`gemini${yoloFlag}\n`);
    } else if (agent === 'codex') {
      const yoloFlag = isYolo ? ' --dangerously-bypass-approvals-and-sandbox' : '';
      const modelName = getCodexMainModel();
      const modelFlag = modelName ? ` --model ${modelName}` : '';
      // Preserve xterm scrollback for Codex's interactive TUI.
      ptyProcess.write(`codex --no-alt-screen${yoloFlag}${modelFlag}\n`);
    } else if (agent.startsWith('groupchat-')) {
      // 그룹챗 터미널 — LLM + 그룹 채팅 통합 모드
      const cli = agent.replace('groupchat-', '');
      // 원래 슬롯 번호 복원: slotId는 slot번호+1 형식 (예: slot101 → slotId=102 → slotNum=2)
      const slotNum = parseInt(slotId, 10) - 100;
      const termName = `T${slotNum}-${cli}`;
      ptyProcess.write(`chcp 65001 >nul & python -m llm_group_chat terminal --name ${termName} --cli ${cli}\r\n`);
    }

    // ── 세션 등록 ─────────────────────────────────────────────────────
    const mainModel = agent === 'claude'
      ? (process.env.ANTHROPIC_MODEL || 'sonnet-4-6')
      : '';
    const bgModel = agent === 'claude'
      ? (process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL || '')
      : '';

    ptySessions.set(sessionId, {
      pty: ptyProcess,
      agent: agent,
      yolo: isYolo,
      started: new Date().toISOString(),
      cwd: cwd,
      lastLine: '',
      currentTask: agent ? `[PTY] ${String(agent).toUpperCase()} 세션 활성` : '',
      mainModel: mainModel,
      bgModel: bgModel,
      projectId: projectId,
      slotId: slotId,
      lastInputAt: Date.now(),
      lastOutputAt: Date.now(),
    });
    ptyOutputBuffers.set(sessionId, []);
    ptyOutputSeq.set(sessionId, 0);

    // ── 세션 시작 로그 전송 ───────────────────────────────────────────
    if (agent) {
      const modeTag = isYolo ? '[YOLO]' : '[일반]';
      const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
      sendSessionLog(
        `pty_start_${sessionId}_${ts}`,
        agent,
        `─── ${agent.toUpperCase()} 세션 시작 ${modeTag} ───`,
        'running'
      );
      sendPtyHeartbeat(sessionId, 'running', true);
    }

    // ── PTY → WebSocket (출력 스트리밍) ───────────────────────────────
    ptyProcess.onData((data) => {
      // Codex 스트림 정규화 (이중 CR 보정)
      const streamData = agent === 'codex' ? normalizeCodexStream(data) : data;
      if (!streamData) return;

      // WebSocket으로 전송
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(streamData);
      }

      // 출력 버퍼에 추가 (REST API 조회용)
      appendPtyOutput(sessionId, streamData);

      // last_line 업데이트 (에이전트 패널 표시용)
      const session = ptySessions.get(sessionId);
      if (session) {
        session.lastOutputAt = Date.now();
        try {
          const clean = streamData.replace(ANSI_ESCAPE, '').replace(/\r/g, '\n');
          const lines = clean.split('\n').filter(l => l.trim().length > 2);
          if (lines.length > 0) {
            session.lastLine = lines[lines.length - 1].trim().substring(0, 120);
            updateSessionTaskFromLine(session, session.lastLine);
            sendPtyHeartbeat(sessionId, 'running');
          }
        } catch (_) {
          // last_line 업데이트 실패 시 무시 (메인 흐름 보호)
        }
      }
    });

    // ── PTY 종료 감지 ─────────────────────────────────────────────────
    ptyProcess.onExit(({ exitCode, signal }) => {
      console.log(`[PTY] 프로세스 종료: T${slotId} code=${exitCode} signal=${signal}`);

      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} 프로세스 종료 (exit=${exitCode}) ───`,
          'success'
        );
        sendPtyHeartbeat(sessionId, exitCode === 0 ? 'done' : 'error', true);
      }

      // 세션 정리
      ptySessions.delete(sessionId);
      ptyOutputBuffers.delete(sessionId);
      ptyOutputSeq.delete(sessionId);

      // WebSocket 닫기
      if (ws.readyState === WebSocket.OPEN) {
        ws.close(1000, 'PTY process exited');
      }
    });

    // ── WebSocket → PTY (입력 전달) ───────────────────────────────────
    // 입력 버퍼: 자율 에이전트 라우팅용 (빈 셸 터미널에서만 사용)
    let wsInputBuf = [];
    let wsInitDone = false;

    // 초기화 명령이 끝난 뒤 1.5초 후부터 인터셉션 활성화
    setTimeout(() => { wsInitDone = true; }, 1500);

    ws.on('message', (message) => {
      try {
        const msgStr = typeof message === 'string' ? message : message.toString('utf-8');

        // ── JSON 제어 메시지 처리 (리사이즈) ───────────────────────────
        if (msgStr.startsWith('{') && msgStr.endsWith('}')) {
          try {
            const data = JSON.parse(msgStr);
            if (data.type === 'resize') {
              const newCols = parseInt(data.cols, 10) || 80;
              const newRows = parseInt(data.rows, 10) || 24;
              ptyProcess.resize(newCols, newRows);
              return;
            }
          } catch (_) {
            // JSON 파싱 실패 → 일반 입력으로 처리
          }
        }

        // idle TTL 워커용: 사용자 키 입력 시각 갱신 (resize 제외)
        const inputSession = ptySessions.get(sessionId);
        if (inputSession) inputSession.lastInputAt = Date.now();

        // ── 입력 정규화 및 PTY 전달 ────────────────────────────────────
        const processed = msgStr.replace(/\r\n/g, '\r').replace(/\n/g, '\r');

        if (processed.includes('\r')) {
          // Enter 키 포함: 세그먼트별 처리
          const segments = processed.split('\r');
          for (let idx = 0; idx < segments.length; idx++) {
            const segment = segments[idx];
            if (segment) {
              // 버퍼에 누적 (자율 에이전트 라우팅용)
              if (wsInitDone) {
                if ((segment === '\x7f' || segment === '\x08') && wsInputBuf.length > 0) {
                  wsInputBuf.pop();
                } else {
                  wsInputBuf.push(segment);
                }
              }
              ptyProcess.write(segment);
            }
            // Enter 처리
            if (idx < segments.length - 1) {
              // 자율 에이전트 라우팅 (빈 셸 터미널에서만)
              if (wsInitDone && wsInputBuf.length > 0) {
                const completedLine = wsInputBuf.join('');
                wsInputBuf = [];
                const cleaned = completedLine.replace(/[\x00-\x1f\x7f-\x9f]/g, '').trim();
                const current = ptySessions.get(sessionId);
                if (current && cleaned.length >= 4) {
                  updateSessionTaskFromLine(current, cleaned, true);
                  sendPtyHeartbeat(sessionId, 'running', true);
                }
                if (cleaned.length >= 4 && !agent) {
                  dispatchToAgent(cleaned, ptyProcess);
                }
              }
              const enterStr = getSubmitEnterSequence(agent);
              ptyProcess.write(enterStr);
            }
          }
        } else {
          // 일반 문자: 버퍼에 누적 + PTY로 전달
          if (wsInitDone) {
            if ((msgStr === '\x7f' || msgStr === '\x08') && wsInputBuf.length > 0) {
              wsInputBuf.pop();
            } else if (!processed.includes('\r')) {
              wsInputBuf.push(msgStr);
            }
          }
          ptyProcess.write(processed);
        }
      } catch (err) {
        console.error(`[WS ERROR] ${err.message}`);
      }
    });

    // ── WebSocket 닫힘 처리 ───────────────────────────────────────────
    ws.on('close', () => {
      console.log(`[PTY] WebSocket 닫힘: T${slotId}`);

      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} 연결 종료 (WebSocket 닫힘) ───`,
          'success'
        );
      }

      // PTY 프로세스 종료
      try {
        ptyProcess.kill();
      } catch (_) {}

      // 세션 정리
      ptySessions.delete(sessionId);
      ptyOutputBuffers.delete(sessionId);
      ptyOutputSeq.delete(sessionId);
    });

    ws.on('error', (err) => {
      console.error(`[WS ERROR] T${slotId}: ${err.message}`);
    });

  } catch (err) {
    console.error(`[PTY] Init Error: ${err.message}`);
    if (ws.readyState === WebSocket.OPEN) {
      ws.close(1011, `PTY Init Error: ${err.message}`);
    }
  }
}

// ── 자율 에이전트 라우팅 (빈 셸 터미널용) ─────────────────────────────────
/**
 * PTY 터미널에 에이전트(claude/gemini 등)가 실행되지 않은 빈 셸에서
 * 사용자 입력을 cli_agent.py로 자동 라우팅합니다.
 * 에이전트가 이미 실행 중인 경우 라우팅하지 않습니다.
 */
function handlePersistentPtyConnection(ws, req) {
  let ptyProcess = null;
  let sessionId = null;
  let slotId = null;

  try {
    const url = new URL(req.url, `http://127.0.0.1:${PTY_PORT}`);
    const agent = url.searchParams.get('agent') || '';
    let cwd = url.searchParams.get('cwd') || PROJECT_ROOT;
    if (!fs.existsSync(cwd)) {
      console.log(`[PTY] CWD invalid: ${cwd} -> fallback to home`);
      cwd = os.homedir();
    }
    const cols = parseInt(url.searchParams.get('cols') || '80', 10);
    const rows = parseInt(url.searchParams.get('rows') || '24', 10);
    const isYolo = url.searchParams.get('yolo') === 'true';
    // 오피스 모드 워크스페이스 프로필: 모델 및 슬롯 이름
    const requestedModel = url.searchParams.get('model') || '';
    const slotName = url.searchParams.get('name') || '';

    // Phase 2-5.3a: 프로젝트 격리 복합 키
    const projectId = _resolvePidFromQuery(url.searchParams, cwd);
    const slotMatch = req.url.match(/\/pty\/slot(\d+)/);
    slotId = slotMatch ? String(parseInt(slotMatch[1], 10) + 1) : String(Date.now());
    sessionId = sessionKey(projectId, slotId);

    const existingSession = ptySessions.get(sessionId);
    if (existingSession && existingSession.pty) {
      if (existingSession.agent && agent && existingSession.agent !== agent) {
        ws.close(1013, `Slot busy with ${existingSession.agent}`);
        return;
      }

      if (existingSession.socket && existingSession.socket !== ws && existingSession.socket.readyState === WebSocket.OPEN) {
        try {
          existingSession.socket.close(1012, 'Replaced by newer attachment');
        } catch (_) {}
      }

      attachSocketToSession(ws, sessionId, existingSession.agent || agent);
      try {
        existingSession.pty.resize(cols, rows);
      } catch (_) {}
      console.log(`[PTY] existing session reattached: T${slotId} agent=${existingSession.agent} project=${projectId}`);
      replayBufferedOutput(sessionId, ws);
      return;
    }

    const env = Object.assign({}, process.env, {
      PYTHONIOENCODING: 'utf-8',
      LANG: 'ko_KR.UTF-8',
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      PYTHONLEGACYWINDOWSSTDIO: '0',
      TERMINAL_ID: slotId,
      // instructor 패키지의 deprecated google.generativeai FutureWarning 억제
      PYTHONWARNINGS: 'ignore::FutureWarning',
    });

    if (agent) {
      env.HIVE_AGENT = agent;
    }

    if (agent === 'claude' && !process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL) {
      env.ANTHROPIC_DEFAULT_HAIKU_MODEL = 'claude-haiku-4-5-20251001';
    }

    let shell, shellArgs;
    if ((agent === 'gemini' || agent === 'codex') && BASH_AVAILABLE) {
      shell = BASH_EXE;
      shellArgs = ['--login'];
    } else {
      shell = 'cmd.exe';
      shellArgs = [];
    }

    ptyProcess = pty.spawn(shell, shellArgs, {
      name: 'xterm-256color',
      cols: cols,
      rows: rows,
      cwd: cwd,
      env: env,
      useConpty: true,
    });

    console.log(`[PTY] session started: T${slotId} agent=${agent} pid=${ptyProcess.pid} project=${projectId}`);

    if (agent === 'claude') {
      const yoloFlag = isYolo ? ' --dangerously-skip-permissions' : '';
      const modelFlag = requestedModel ? ` --model ${requestedModel}` : '';
      ptyProcess.write(`chcp 65001 >nul & claude${yoloFlag}${modelFlag}\r\n`);
    } else if (agent === 'gemini') {
      const yoloFlag = isYolo ? ' -y' : '';
      const modelFlag = requestedModel ? ` --model ${requestedModel}` : '';
      ptyProcess.write(`gemini${yoloFlag}${modelFlag}\n`);
    } else if (agent === 'codex') {
      const yoloFlag = isYolo ? ' --dangerously-bypass-approvals-and-sandbox' : '';
      const modelName = requestedModel || getCodexMainModel();
      const modelFlag = modelName ? ` --model ${modelName}` : '';
      ptyProcess.write(`codex --no-alt-screen${yoloFlag}${modelFlag}\n`);
    } else if (agent.startsWith('groupchat-')) {
      const cli = agent.replace('groupchat-', '');
      const slotNum = parseInt(slotId, 10) - 100;
      const termName = `T${slotNum}-${cli}`;
      ptyProcess.write(`chcp 65001 >nul & python -m llm_group_chat terminal --name ${termName} --cli ${cli}\r\n`);
    }

    const mainModel = requestedModel || (agent === 'claude'
      ? (process.env.ANTHROPIC_MODEL || 'sonnet-4-6')
      : '');
    const bgModel = agent === 'claude'
      ? (process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL || '')
      : '';

    ptySessions.set(sessionId, {
      pty: ptyProcess,
      socket: ws,
      agent: agent,
      yolo: isYolo,
      started: new Date().toISOString(),
      cwd: cwd,
      lastLine: '',
      currentTask: agent ? `[PTY] ${String(agent).toUpperCase()} 세션 활성` : '',
      mainModel: mainModel,
      bgModel: bgModel,
      slotName: slotName,
      attached: true,
      detachedAt: '',
      detachTimer: null,
      projectId: projectId,
      slotId: slotId,
      lastInputAt: Date.now(),
      lastOutputAt: Date.now(),
    });
    ptyOutputBuffers.set(sessionId, []);
    ptyOutputSeq.set(sessionId, 0);

    if (agent) {
      const modeTag = isYolo ? '[YOLO]' : '[NORMAL]';
      const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
      sendSessionLog(
        `pty_start_${sessionId}_${ts}`,
        agent,
        `─── ${agent.toUpperCase()} session started ${modeTag} ───`,
        'running'
      );
      sendPtyHeartbeat(sessionId, 'running', true);
    }

    ptyProcess.onData((data) => {
      const streamData = agent === 'codex' ? normalizeCodexStream(data) : data;
      if (!streamData) return;

      const activeSession = ptySessions.get(sessionId);
      const activeSocket = activeSession && activeSession.socket;
      if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(streamData);
      }

      appendPtyOutput(sessionId, streamData);

      const session = ptySessions.get(sessionId);
      if (session) {
        session.lastOutputAt = Date.now();
        try {
          const clean = streamData.replace(ANSI_ESCAPE, '').replace(/\r/g, '\n');
          const lines = clean.split('\n').filter(l => l.trim().length > 2);
          if (lines.length > 0) {
            session.lastLine = lines[lines.length - 1].trim().substring(0, 120);
            updateSessionTaskFromLine(session, session.lastLine);
            sendPtyHeartbeat(sessionId, 'running');
          }
        } catch (_) {}
      }
    });

    ptyProcess.onExit(({ exitCode, signal }) => {
      console.log(`[PTY] process exit: T${slotId} code=${exitCode} signal=${signal}`);

      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} process exited (exit=${exitCode}) ───`,
          'success'
        );
        sendPtyHeartbeat(sessionId, exitCode === 0 ? 'done' : 'error', true);
      }

      const activeSession = ptySessions.get(sessionId);
      const activeSocket = activeSession && activeSession.socket;
      clearSessionState(sessionId);

      if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.close(1000, 'PTY process exited');
      }
    });

    attachSocketToSession(ws, sessionId, agent);
  } catch (err) {
    console.error(`[PTY] Init Error: ${err.message}`);
    if (ws.readyState === WebSocket.OPEN) {
      ws.close(1011, `PTY Init Error: ${err.message}`);
    }
  }
}

function dispatchToAgent(instruction, ptyProcess) {
  if (instruction.length < 4) return;

  const scriptsDir = path.resolve(__dirname, '..', '..', 'scripts');
  const cliAgentPy = path.join(scriptsDir, 'cli_agent.py');

  const childEnv = Object.assign({}, process.env, {
    CLI_AGENT_JSON_STDOUT: '1'
  });

  try {
    const proc = spawn(process.env.PYTHON_EXE || 'python', [cliAgentPy, instruction, 'auto'], {
      cwd: path.resolve(__dirname, '..', '..'),
      env: childEnv,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });

    proc.stdout.on('data', (data) => {
      const lines = data.toString('utf-8').split('\n');
      for (const rawLine of lines) {
        const trimmed = rawLine.trim();
        if (!trimmed) continue;
        try {
          const event = JSON.parse(trimmed);
          const line = event.line || '';
          if (line) {
            ptyProcess.write(line + '\r\n');
          } else if (event.type === 'done') {
            ptyProcess.write(`[agent:${event.status || 'done'}]\r\n`);
          }
        } catch (_) {
          ptyProcess.write(trimmed + '\r\n');
        }
      }
    });

    proc.on('error', (err) => {
      console.log(`[PTY→AGENT] 라우팅 실패: ${err.message}`);
    });

    console.log(`[PTY→AGENT] 자율 에이전트 라우팅: ${instruction.substring(0, 60)}`);
  } catch (err) {
    console.log(`[PTY→AGENT] spawn 실패: ${err.message}`);
  }
}

// ── REST API (Express) ────────────────────────────────────────────────────
const app = express();
app.use(express.json());

// CORS 허용 (Python 서버 및 프론트엔드에서 접근)
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

/**
 * GET /api/pty/sessions
 * PTY 세션 스냅샷. Phase 2-5.3a부터 ?project_id= 쿼리로 프로젝트별 필터.
 *   - project_id 명시: 해당 프로젝트의 슬롯 1~32만 반환 (오피스 O* 제외)
 *   - 누락: _default 풀 + 그 외 모든 프로젝트 통합 응답 (관리용)
 * Python 서버의 agent_api.py, pty_api.py가 이 엔드포인트를 호출합니다.
 */
app.get('/api/pty/sessions', (req, res) => {
  const requestedPid = (req.query.project_id || '').trim();
  const terminals = {};
  const nowMs = Date.now();

  // Phase 2-5.3b: idle_seconds = 마지막 키 입력/출력 중 최근 값으로부터의 초.
  function idleSecondsOf(info) {
    if (!info) return 0;
    const last = Math.max(Number(info.lastInputAt) || 0, Number(info.lastOutputAt) || 0);
    if (!last) return 0;
    return Math.max(0, Math.floor((nowMs - last) / 1000));
  }

  if (requestedPid) {
    // 단일 프로젝트 필터
    for (let slot = 1; slot <= 32; slot++) {
      const info = ptySessions.get(sessionKey(requestedPid, String(slot)));
      if (slot > 8 && !info) continue;
      terminals[`T${slot}`] = {
        running: !!info,
        attached: info ? !!info.attached : false,
        agent: info ? info.agent : '',
        yolo: info ? info.yolo : false,
        started: info ? info.started : '',
        cwd: info ? info.cwd : '',
        last_line: info ? info.lastLine : '',
        main_model: info ? info.mainModel : '',
        bg_model: info ? info.bgModel : '',
        slot_name: info ? (info.slotName || '') : '',
        detached_at: info ? info.detachedAt : '',
        project_id: requestedPid,
        last_input_at: info ? (Number(info.lastInputAt) || 0) : 0,
        last_output_at: info ? (Number(info.lastOutputAt) || 0) : 0,
        idle_seconds: idleSecondsOf(info),
      };
    }
  } else {
    // 전체 통합 응답: 슬롯 키 + 프로젝트 ID 함께 노출
    // _default 풀의 1~8은 클래식 호환을 위해 T1~T8로 노출 (project_id='_default')
    const seenSlots = new Set();
    for (const [key, info] of ptySessions.entries()) {
      const { projectId, slotId } = parseSessionKey(key);
      // 오피스 O* 슬롯은 office/sessions로 별도 노출 — 여기서는 제외
      if (String(slotId).startsWith('O')) continue;
      const label = projectId === '_default' ? `T${slotId}` : `T${slotId}@${projectId}`;
      seenSlots.add(label);
      terminals[label] = {
        running: !!info,
        attached: !!info.attached,
        agent: info.agent || '',
        yolo: info.yolo || false,
        started: info.started || '',
        cwd: info.cwd || '',
        last_line: info.lastLine || '',
        main_model: info.mainModel || '',
        bg_model: info.bgModel || '',
        slot_name: info.slotName || '',
        detached_at: info.detachedAt || '',
        project_id: projectId,
        last_input_at: Number(info.lastInputAt) || 0,
        last_output_at: Number(info.lastOutputAt) || 0,
        idle_seconds: idleSecondsOf(info),
      };
    }
    // 클래식 호환: _default 풀의 1~8 슬롯이 비어있으면 빈 항목으로 채움
    for (let slot = 1; slot <= 8; slot++) {
      const label = `T${slot}`;
      if (!seenSlots.has(label)) {
        terminals[label] = {
          running: false, attached: false, agent: '', yolo: false,
          started: '', cwd: '', last_line: '', main_model: '', bg_model: '',
          slot_name: '', detached_at: '', project_id: '_default',
          last_input_at: 0, last_output_at: 0, idle_seconds: 0,
        };
      }
    }
  }
  res.json(terminals);
});

/**
 * GET /api/pty/sessions/summary
 * Phase 2-5.3c: 프로젝트 ID별 활성 세션 집계.
 *   - agent_count: 에이전트가 붙어 실제로 실행 중인 슬롯 수 (오피스 O* 제외)
 *   - total: 해당 프로젝트가 가진 PTY 슬롯 총 개수 (오피스 포함)
 * 프론트엔드 TopMenuBar 탭 배지가 10초 폴링으로 호출.
 * 응답 예: { "D--vibe-coding": { agent_count: 2, total: 3 }, "_default": { agent_count: 0, total: 0 } }
 */
app.get('/api/pty/sessions/summary', (req, res) => {
  const summary = {};
  for (const [key, info] of ptySessions.entries()) {
    const { projectId, slotId } = parseSessionKey(key);
    if (!summary[projectId]) summary[projectId] = { agent_count: 0, total: 0 };
    summary[projectId].total += 1;
    const isOffice = String(slotId).startsWith('O');
    if (!isOffice && info && info.agent) {
      summary[projectId].agent_count += 1;
    }
  }
  res.json(summary);
});

/**
 * DELETE /api/pty/sessions
 * Phase 2-5.3a: 특정 프로젝트의 모든 PTY 세션을 일괄 종료합니다.
 * 프론트에서 탭 닫기/프로젝트 제거 시 호출. 오피스 O* 슬롯은 별도 라이프사이클이라 제외.
 * query: project_id (필수)
 * 응답: { cleaned: N, project_id, skipped_office: M }
 */
app.delete('/api/pty/sessions', (req, res) => {
  const requestedPid = (req.query.project_id || '').trim();
  if (!requestedPid) {
    return res.status(400).json({ error: 'missing_project_id' });
  }
  let cleaned = 0;
  let skippedOffice = 0;
  const targets = [];
  for (const [key, info] of ptySessions.entries()) {
    const { projectId, slotId } = parseSessionKey(key);
    if (projectId !== requestedPid) continue;
    if (String(slotId).startsWith('O')) { skippedOffice++; continue; }
    targets.push({ key, hasPty: !!(info && info.pty) });
  }
  for (const { key, hasPty } of targets) {
    if (hasPty) killSessionPty(key, 'project_removed');
    clearSessionState(key);
    cleaned++;
  }
  res.json({ cleaned, project_id: requestedPid, skipped_office: skippedOffice });
});

/**
 * GET /api/pty/models
 * 각 CLI에서 사용 가능한 모델 목록을 반환합니다.
 * 오피스 모드 워크스페이스 프로필의 모델 선택 드롭다운에서 사용합니다.
 */
app.get('/api/pty/models', (req, res) => {
  res.json({
    claude: [
      { id: 'claude-opus-4-6', label: 'Opus 4.6 (최강)' },
      { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6 (균형)' },
      { id: 'claude-haiku-4-5', label: 'Haiku 4.5 (경량)' },
    ],
    // 2026-04 기준 최신 모델. useCliModels.ts 폴백과 반드시 동기화 유지.
    gemini: [
      { id: 'gemini-3.1-pro', label: '3.1 Pro (최강)' },
      { id: 'gemini-3.1-flash', label: '3.1 Flash (빠름)' },
      { id: 'gemini-3.1-flash-lite', label: '3.1 Flash-Lite (저지연)' },
      { id: 'gemini-2.5-pro', label: '2.5 Pro (레거시)' },
    ],
    codex: [
      { id: 'gpt-5.3-codex', label: 'GPT-5.3-Codex (최강)' },
      { id: 'gpt-5.3-codex-spark', label: 'GPT-5.3-Codex Spark (실시간)' },
      { id: 'gpt-5.4', label: 'GPT-5.4 (범용)' },
      { id: 'gpt-5.4-mini', label: 'GPT-5.4 Mini (빠름)' },
      { id: 'gpt-5.2-codex', label: 'GPT-5.2-Codex (이전 세대)' },
    ],
  });
});

// Phase 2-5.3a: 단건 조작 엔드포인트의 target → 내부 키 변환.
// O*로 시작하는 슬롯(오피스)은 키에 project_id prefix 없는 단독 키로 별도 처리.
function _resolveSessionKey(target, queryPid) {
  const slotId = String(target);
  if (slotId.startsWith('O')) {
    // 오피스 세션: 기존에는 평탄 키 'O*'였지만 spawn에서 sessionKey로 묶이도록 변경됨.
    // 호환을 위해 두 가지 모두 시도 — 새 키 우선, 없으면 평탄 키 폴백.
    const pid = (queryPid || '_default').trim() || '_default';
    const newKey = sessionKey(pid, slotId);
    if (ptySessions.has(newKey)) return newKey;
    // 평탄 키 폴백 (구버전 office 세션 호환)
    if (ptySessions.has(slotId)) return slotId;
    return newKey;
  }
  return sessionKey((queryPid || '_default').trim() || '_default', slotId);
}

/**
 * GET /api/pty/output/:id
 * 특정 세션의 출력 버퍼를 반환합니다.
 * query: project_id, since (시퀀스 번호), limit (최대 줄 수)
 */
app.get('/api/pty/output/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const since = parseInt(req.query.since || '0', 10);
  const limit = Math.max(1, Math.min(parseInt(req.query.limit || '80', 10), 200));
  const key = _resolveSessionKey(target, req.query.project_id);

  const buffer = ptyOutputBuffers.get(key) || [];
  const filtered = buffer.filter(entry => entry.seq > since).slice(0, limit);
  const latestSeq = buffer.length > 0 ? buffer[buffer.length - 1].seq : 0;
  const info = ptySessions.get(key);

  res.json({
    terminal_id: `T${target}`,
    entries: filtered,
    latest_seq: latestSeq,
    running: ptySessions.has(key),
    attached: !!(info && info.attached),
  });
});

/**
 * POST /api/pty/interrupt/:id
 * 특정 세션에 SIGINT(Ctrl+C)를 전송합니다.
 * query: project_id (Phase 2-5.3a)
 */
app.post('/api/pty/interrupt/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const key = _resolveSessionKey(target, req.query.project_id);
  const info = ptySessions.get(key);
  if (!info || !info.pty) {
    return res.status(404).json({ error: 'not_running', terminal_id: `T${target}` });
  }

  try {
    info.pty.write('\x03');
    res.json({ status: 'interrupted', terminal_id: `T${target}` });
  } catch (err) {
    res.status(500).json({ error: 'interrupt_failed', detail: err.message });
  }
});

/**
 * POST /api/pty/terminate/:id
 * 특정 세션의 PTY 프로세스를 강제 종료합니다.
 * query: project_id (Phase 2-5.3a)
 */
app.post('/api/pty/terminate/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const key = _resolveSessionKey(target, req.query.project_id);
  const info = ptySessions.get(key);
  if (!info || !info.pty) {
    return res.status(404).json({ error: 'not_running', terminal_id: `T${target}` });
  }

  if (!killSessionPty(key, 'api_terminate')) {
    return res.status(500).json({ error: 'terminate_failed', detail: 'killSessionPty failed' });
  }

  res.json({ status: 'terminated', terminal_id: `T${target}` });
});

/**
 * POST /api/pty/write/:id
 * 특정 세션의 PTY에 텍스트를 직접 입력합니다.
 * body: { "text": "입력할 텍스트" }
 * query: project_id (Phase 2-5.3a)
 * 텔레그램 브릿지에서 기존 터미널의 Claude Code에 메시지를 주입하는 데 사용.
 */
app.post('/api/pty/write/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const key = _resolveSessionKey(target, req.query.project_id);
  const info = ptySessions.get(key);
  if (!info || !info.pty) {
    return res.status(404).json({ error: 'not_running', terminal_id: `T${target}` });
  }

  const text = req.body && req.body.text;
  if (!text) {
    return res.status(400).json({ error: 'missing_text' });
  }

  try {
    // 텍스트 + Enter 키 전송
    const enterStr = getSubmitEnterSequence(info.agent);
    info.pty.write(text);
    info.pty.write(enterStr);
    res.json({ status: 'written', terminal_id: `T${target}`, length: text.length });
  } catch (err) {
    res.status(500).json({ error: 'write_failed', detail: err.message });
  }
});

/**
 * POST /api/pty/office/spawn
 * 오피스 전용 PTY 세션 생성 (클래식 T1~T8과 완전 분리).
 * body: { agent: 'claude', yolo: true, model: 'claude-sonnet-4-6', project_id?: 'D--vibe-coding' }
 * 세션 ID(slot): O1, O2, ... (Office namespace) — 내부 키는 {pid}:O{N} (Phase 2-5.3a)
 * 본 정책(TTL/배지)에서는 slotId가 'O'로 시작하면 자연 제외.
 */
app.post('/api/pty/office/spawn', (req, res) => {
  const agent = (req.body && req.body.agent) || 'claude';
  const isYolo = !!(req.body && req.body.yolo);
  const requestedCwd = req.body && req.body.cwd;
  const cwd = (requestedCwd && fs.existsSync(requestedCwd)) ? requestedCwd : PROJECT_ROOT;

  // 프로젝트 ID 결정: body.project_id → cwd slugify → _default 폴백
  const projectId = ((req.body && req.body.project_id) || '').trim() ||
                    slugifyProjectPath(cwd) || '_default';

  // 오피스 슬롯 ID 할당 (O1, O2, ...) — 동일 프로젝트 내 충돌만 검사
  let officeId = 1;
  while (ptySessions.has(sessionKey(projectId, `O${officeId}`))) officeId++;
  const slotId = `O${officeId}`;
  const sessionId = sessionKey(projectId, slotId);

  const env = Object.assign({}, process.env, {
    PYTHONIOENCODING: 'utf-8',
    LANG: 'ko_KR.UTF-8',
    TERM: 'xterm-256color',
    COLORTERM: 'truecolor',
    TERMINAL_ID: slotId,
    HIVE_AGENT: agent,
    OFFICE_MODE: 'true',
  });

  // 셸 선택
  let shell, shellArgs;
  if ((agent === 'gemini' || agent === 'codex') && BASH_AVAILABLE) {
    shell = BASH_EXE;
    shellArgs = ['--login'];
  } else {
    shell = 'cmd.exe';
    shellArgs = [];
  }

  try {
    const ptyProcess = pty.spawn(shell, shellArgs, {
      name: 'xterm-256color',
      cols: 120,
      rows: 40,
      cwd: cwd,
      env: env,
      useConpty: true,
    });

    console.log(`[PTY-Office] 세션 시작: ${slotId} agent=${agent} pid=${ptyProcess.pid} project=${projectId}`);

    // 에이전트 시작 명령 — 새 대화를 즉시 시작 (--resume 없이 실행)
    if (agent === 'claude') {
      const yoloFlag = isYolo ? ' --dangerously-skip-permissions' : '';
      ptyProcess.write(`chcp 65001 >nul & claude${yoloFlag}\r\n`);
    } else if (agent === 'gemini') {
      const yoloFlag = isYolo ? ' -y' : '';
      ptyProcess.write(`gemini${yoloFlag}\n`);
    } else if (agent === 'codex') {
      const yoloFlag = isYolo ? ' --dangerously-bypass-approvals-and-sandbox' : '';
      ptyProcess.write(`codex --no-alt-screen${yoloFlag}\n`);
    }

    // 세션 등록
    ptySessions.set(sessionId, {
      pty: ptyProcess,
      socket: null,      // 오피스 세션은 WebSocket 없음 (REST only)
      agent: agent,
      yolo: isYolo,
      started: new Date().toISOString(),
      cwd: cwd,
      lastLine: '',
      mainModel: req.body?.model || '',
      bgModel: '',
      attached: false,
      detachedAt: '',
      detachTimer: null,
      slotName: `Office-${agent}`,
      namespace: 'office',  // 오피스 네임스페이스 표시
      projectId: projectId,
      slotId: slotId,
    });

    // 출력 버퍼 초기화
    ptyOutputBuffers.set(sessionId, []);
    ptyOutputSeq.set(sessionId, 0);

    // PTY 출력 캡처
    ptyProcess.onData((data) => {
      appendPtyOutput(sessionId, data);
      const info = ptySessions.get(sessionId);
      if (info) {
        const clean = data.replace(/\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g, '').trim();
        if (clean.length > 2) info.lastLine = clean.substring(0, 120);
      }
    });

    ptyProcess.onExit(({ exitCode }) => {
      console.log(`[PTY-Office] 세션 종료: ${slotId} exitCode=${exitCode} project=${projectId}`);
      ptySessions.delete(sessionId);
      ptyOutputBuffers.delete(sessionId);
      ptyOutputSeq.delete(sessionId);
    });

    // sessionId 응답: 호환을 위해 slotId(O*) 그대로 반환 — 클라이언트는 단건 조작에 ?project_id= 첨부.
    res.json({ status: 'spawned', sessionId: slotId, agent, pid: ptyProcess.pid, project_id: projectId });
  } catch (err) {
    console.error(`[PTY-Office] 스폰 실패:`, err);
    res.status(500).json({ error: 'spawn_failed', detail: err.message });
  }
});

/**
 * GET /api/pty/office/sessions
 * 오피스 전용 세션 목록만 반환 (slot O1, O2, ...).
 * Phase 2-5.3a: 내부 키는 {pid}:O{N}이지만 응답 키는 호환을 위해 slotId(O*) 단독 사용.
 * query: project_id 명시하면 해당 프로젝트만, 누락 시 모든 프로젝트의 오피스 세션 통합.
 */
app.get('/api/pty/office/sessions', (req, res) => {
  const requestedPid = (req.query.project_id || '').trim();
  const sessions = {};
  for (const [key, info] of ptySessions.entries()) {
    const { projectId, slotId } = parseSessionKey(key);
    if (!String(slotId).startsWith('O')) continue;
    if (requestedPid && projectId !== requestedPid) continue;
    // 응답 키: 단일 프로젝트 필터 시 slotId 단독, 통합 시 슬롯@프로젝트 라벨
    const respKey = requestedPid ? slotId : (projectId === '_default' ? slotId : `${slotId}@${projectId}`);
    sessions[respKey] = {
      running: !!(info.pty),
      agent: info.agent || '',
      slot_name: info.slotName || '',
      last_line: info.lastLine || '',
      main_model: info.mainModel || '',
      namespace: 'office',
      project_id: projectId,
    };
  }
  res.json(sessions);
});

/**
 * GET /health
 * 헬스체크 엔드포인트 — Python 서버가 Node PTY 서버 생존 확인용
 */
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    sessions: ptySessions.size,
    uptime: process.uptime(),
  });
});

// ── 서버 시작 ─────────────────────────────────────────────────────────────
const server = http.createServer(app);

// WebSocket 서버를 HTTP 서버에 결합 (동일 포트에서 REST + WS 모두 처리)
const wss = new WebSocket.Server({
  server: server,
  path: undefined,  // 모든 경로에서 업그레이드 허용 (아래 verifyClient에서 필터링)
  verifyClient: (info) => {
    // /pty/slot 경로만 WebSocket 업그레이드 허용
    return info.req.url && info.req.url.startsWith('/pty/slot');
  },
  // ping/pong으로 연결 유지 (30초 간격, 10초 타임아웃)
  // ws 라이브러리에서는 수동으로 구현
});

// WebSocket ping/pong 생존 확인 (30초 간격)
const PING_INTERVAL = 30000;
const PONG_TIMEOUT = 10000;

setInterval(() => {
  wss.clients.forEach((ws) => {
    if (ws.isAlive === false) {
      console.log('[PTY] ping 타임아웃 — WebSocket 연결 종료');
      return ws.terminate();
    }
    ws.isAlive = false;
    ws.ping();
  });
}, PING_INTERVAL);

wss.on('connection', (ws, req) => {
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });
  handlePersistentPtyConnection(ws, req);
});

// ── Phase 2-5.3b: TTL 스윕 워커 ───────────────────────────────────────────
// PTY_TTL_SWEEP_MS마다 ptySessions 순회 → idle 세션 자동 종료.
// yolo/오피스 면제는 isSessionIdleForCleanup이 처리.
let ttlSweepTimer = null;
function startTtlSweepWorker() {
  if (ttlSweepTimer) return;
  ttlSweepTimer = setInterval(() => {
    const now = Date.now();
    for (const [key, info] of ptySessions.entries()) {
      if (isSessionIdleForCleanup(info, now)) {
        const idleSec = Math.floor((now - Math.max(Number(info.lastInputAt) || 0, Number(info.lastOutputAt) || 0)) / 1000);
        console.log(`[PTY] TTL cleanup: ${key} idle=${idleSec}s`);
        killSessionPty(key, 'ttl_cleanup');
      }
    }
  }, PTY_TTL_SWEEP_MS);
  if (typeof ttlSweepTimer.unref === 'function') ttlSweepTimer.unref();
  console.log(`[PTY] TTL sweep worker started (TTL=${PTY_TTL_MS}ms idle=${PTY_IDLE_THRESHOLD_MS}ms sweep=${PTY_TTL_SWEEP_MS}ms)`);
}

function stopTtlSweepWorker() {
  if (!ttlSweepTimer) return;
  clearInterval(ttlSweepTimer);
  ttlSweepTimer = null;
}

// ── 프로세스 종료 시 모든 PTY 세션 정리 ───────────────────────────────────
function cleanupAllSessions() {
  stopTtlSweepWorker();
  console.log(`[PTY] 서버 종료 — ${ptySessions.size}개 세션 정리 중...`);
  for (const [sid] of ptySessions.entries()) {
    killSessionPty(sid, 'server_shutdown');
    console.log(`[cleanup] PTY 세션 종료: T${sid}`);
  }
}

/**
 * POST /api/pty/shutdown
 * Python 서버가 종료 시 호출 — 모든 PTY 세션을 정리한 뒤 프로세스 종료.
 * taskkill /F 강제 종료 전에 이 엔드포인트를 먼저 호출하면
 * conhost.exe/cmd.exe 고아 프로세스(빈 터미널 창)가 남지 않습니다.
 */
app.post('/api/pty/shutdown', (req, res) => {
  const count = ptySessions.size;
  console.log('[PTY] Shutdown 요청 수신 — 모든 세션 정리 후 종료합니다.');
  cleanupAllSessions();
  res.json({ status: 'shutdown', sessions_cleaned: count });
  // 응답 전송 완료 후 프로세스 종료 (약간의 지연으로 응답이 클라이언트에 도달하도록 보장)
  setTimeout(() => { process.exit(0); }, 300);
});

process.on('SIGTERM', () => { cleanupAllSessions(); process.exit(0); });
process.on('SIGINT', () => { cleanupAllSessions(); process.exit(0); });
process.on('exit', () => { cleanupAllSessions(); });

// ── 리스닝 시작 ───────────────────────────────────────────────────────────
server.listen(PTY_PORT, '127.0.0.1', () => {
  console.log(`[PTY Server] node-pty WebSocket + REST on port ${PTY_PORT}`);
  console.log(`[PTY Server] WS: ws://127.0.0.1:${PTY_PORT}/pty/slot{N}`);
  console.log(`[PTY Server] REST: http://127.0.0.1:${PTY_PORT}/api/pty/*`);
  startTtlSweepWorker();
});
