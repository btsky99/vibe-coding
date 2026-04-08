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

// ANSI 이스케이프 코드 제거용 정규식
const ANSI_ESCAPE = /\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;

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
  console.log(`[PTY] 세션 종료 요청: T${sessionId} reason=${reason}`);

  try {
    session.pty.kill();
    return true;
  } catch (err) {
    console.log(`[PTY] PTY 종료 실패: T${sessionId} ${err.message}`);
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
    console.log(`[PTY] 재연결 유예시간 만료: T${sessionId} -> PTY 종료`);
    killSessionPty(sessionId, 'detach_timeout');
  }, DETACH_GRACE_MS);
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
    `\r\n\x1b[38;5;39m[HIVE] 기존 PTY 세션 T${sessionId}에 재부착했습니다.\x1b[0m\r\n` +
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
    console.log(`[PTY] WebSocket 닫힘: T${sessionId} code=${code}`);

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
    console.error(`[WS ERROR] T${sessionId}: ${err.message}`);
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

    // ── 세션 ID 계산 (슬롯 번호 + 1, UI 터미널 번호와 일치) ─────────
    const slotMatch = req.url.match(/\/pty\/slot(\d+)/);
    sessionId = slotMatch ? String(parseInt(slotMatch[1], 10) + 1) : String(Date.now());

    // ── 환경변수 구성 ─────────────────────────────────────────────────
    // Python 서버와 동일한 환경변수를 PTY 프로세스에 주입합니다.
    const env = Object.assign({}, process.env, {
      PYTHONIOENCODING: 'utf-8',
      LANG: 'ko_KR.UTF-8',
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      PYTHONLEGACYWINDOWSSTDIO: '0',
      TERMINAL_ID: sessionId,
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

    console.log(`[PTY] 세션 시작: T${sessionId} agent=${agent} shell=${path.basename(shell)} pid=${ptyProcess.pid}`);

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
      // 원래 슬롯 번호 사용: sessionId는 slotId+100 기반이므로 -100하여 원래 번호 복원
      // 예: slot101 → sessionId=102 → slotNum=2 → T2-gemini
      const slotNum = parseInt(sessionId, 10) - 100;
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
      mainModel: mainModel,
      bgModel: bgModel,
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
        try {
          const clean = streamData.replace(ANSI_ESCAPE, '').replace(/\r/g, '\n');
          const lines = clean.split('\n').filter(l => l.trim().length > 2);
          if (lines.length > 0) {
            session.lastLine = lines[lines.length - 1].trim().substring(0, 120);
          }
        } catch (_) {
          // last_line 업데이트 실패 시 무시 (메인 흐름 보호)
        }
      }
    });

    // ── PTY 종료 감지 ─────────────────────────────────────────────────
    ptyProcess.onExit(({ exitCode, signal }) => {
      console.log(`[PTY] 프로세스 종료: T${sessionId} code=${exitCode} signal=${signal}`);

      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} 프로세스 종료 (exit=${exitCode}) ───`,
          'success'
        );
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
      console.log(`[PTY] WebSocket 닫힘: T${sessionId}`);

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
      console.error(`[WS ERROR] T${sessionId}: ${err.message}`);
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

    const slotMatch = req.url.match(/\/pty\/slot(\d+)/);
    sessionId = slotMatch ? String(parseInt(slotMatch[1], 10) + 1) : String(Date.now());

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
      console.log(`[PTY] existing session reattached: T${sessionId} agent=${existingSession.agent}`);
      replayBufferedOutput(sessionId, ws);
      return;
    }

    const env = Object.assign({}, process.env, {
      PYTHONIOENCODING: 'utf-8',
      LANG: 'ko_KR.UTF-8',
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      PYTHONLEGACYWINDOWSSTDIO: '0',
      TERMINAL_ID: sessionId,
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

    console.log(`[PTY] session started: T${sessionId} agent=${agent} shell=${path.basename(shell)} pid=${ptyProcess.pid}`);

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
      const slotNum = parseInt(sessionId, 10) - 100;
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
      mainModel: mainModel,
      bgModel: bgModel,
      slotName: slotName,
      attached: true,
      detachedAt: '',
      detachTimer: null,
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
        try {
          const clean = streamData.replace(ANSI_ESCAPE, '').replace(/\r/g, '\n');
          const lines = clean.split('\n').filter(l => l.trim().length > 2);
          if (lines.length > 0) {
            session.lastLine = lines[lines.length - 1].trim().substring(0, 120);
          }
        } catch (_) {}
      }
    });

    ptyProcess.onExit(({ exitCode, signal }) => {
      console.log(`[PTY] process exit: T${sessionId} code=${exitCode} signal=${signal}`);

      if (agent) {
        const ts = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
        sendSessionLog(
          `pty_end_${sessionId}_${ts}`,
          agent,
          `─── ${agent.toUpperCase()} process exited (exit=${exitCode}) ───`,
          'success'
        );
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
 * 전체 PTY 세션 스냅샷을 반환합니다.
 * Python 서버의 agent_api.py, pty_api.py가 이 엔드포인트를 호출합니다.
 */
app.get('/api/pty/sessions', (req, res) => {
  const terminals = {};
  // 클래식 모드 호환: 슬롯 1~8은 항상 반환
  // 오피스 모드: 슬롯 9~32는 실제 세션이 있는 경우만 반환
  for (let slot = 1; slot <= 32; slot++) {
    const info = ptySessions.get(String(slot));
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
    };
  }
  res.json(terminals);
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
    gemini: [
      { id: 'gemini-2.5-pro', label: '2.5 Pro (최강)' },
      { id: 'gemini-2.5-flash', label: '2.5 Flash (빠름)' },
      { id: 'gemini-2.0-flash', label: '2.0 Flash (저지연)' },
    ],
    codex: [
      { id: 'o4-mini', label: 'o4-mini (기본)' },
      { id: 'o3', label: 'o3 (고급 추론)' },
      { id: 'gpt-4.1', label: 'GPT-4.1 (플래그십)' },
      { id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini (빠름)' },
      { id: 'gpt-4.1-nano', label: 'GPT-4.1 Nano (최경량)' },
    ],
  });
});

/**
 * GET /api/pty/output/:id
 * 특정 세션의 출력 버퍼를 반환합니다.
 * query: since (시퀀스 번호), limit (최대 줄 수)
 */
app.get('/api/pty/output/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const since = parseInt(req.query.since || '0', 10);
  const limit = Math.max(1, Math.min(parseInt(req.query.limit || '80', 10), 200));

  const buffer = ptyOutputBuffers.get(target) || [];
  const filtered = buffer.filter(entry => entry.seq > since).slice(0, limit);
  const latestSeq = buffer.length > 0 ? buffer[buffer.length - 1].seq : 0;
  const info = ptySessions.get(target);

  res.json({
    terminal_id: `T${target}`,
    entries: filtered,
    latest_seq: latestSeq,
    running: ptySessions.has(target),
    attached: !!(info && info.attached),
  });
});

/**
 * POST /api/pty/interrupt/:id
 * 특정 세션에 SIGINT(Ctrl+C)를 전송합니다.
 */
app.post('/api/pty/interrupt/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const info = ptySessions.get(target);
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
 */
app.post('/api/pty/terminate/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const info = ptySessions.get(target);
  if (!info || !info.pty) {
    return res.status(404).json({ error: 'not_running', terminal_id: `T${target}` });
  }

  if (!killSessionPty(target, 'api_terminate')) {
    return res.status(500).json({ error: 'terminate_failed', detail: 'killSessionPty failed' });
  }

  res.json({ status: 'terminated', terminal_id: `T${target}` });
});

/**
 * POST /api/pty/write/:id
 * 특정 세션의 PTY에 텍스트를 직접 입력합니다.
 * body: { "text": "입력할 텍스트" }
 * 텔레그램 브릿지에서 기존 터미널의 Claude Code에 메시지를 주입하는 데 사용.
 */
app.post('/api/pty/write/:id', (req, res) => {
  let target = req.params.id.toUpperCase();
  if (target.startsWith('T')) target = target.substring(1);

  const info = ptySessions.get(target);
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

// ── 프로세스 종료 시 모든 PTY 세션 정리 ───────────────────────────────────
function cleanupAllSessions() {
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
});
