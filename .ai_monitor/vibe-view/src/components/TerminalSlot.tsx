/**
 * ------------------------------------------------------------------------
 * 📄 파일명: TerminalSlot.tsx
 * 📝 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트.
 *          에이전트 선택 카드(Claude/Antigravity), XTerm.js 터미널 실행, 자율 에이전트
 *          모니터링 뷰(상태/태스크/로그), 단축어 바, 슬래시 커맨드 팝업, 단축어 편집 모달을 담당합니다.
 * REVISION HISTORY:
 * - 2026-03-26 Claude: xterm.js 스크롤 전면 수정 — scrollback 10000줄, smoothScrollDuration 100ms,
 *                      scrollOnUserInput true 추가. 컨테이너 overflow-hidden 제거로 xterm 내장 스크롤바 활성화.
 *                      Antigravity/Codex 긴 출력 시 이전 내용 확인 불가 문제 해결.
 * - 2026-03-20 Claude: 장시간 idle 시 WS 끊김 → 자동 재연결 + 서버 ping/pong keepalive.
 *                      onclose에서 지수 백오프(1s~30s, 최대 10회)로 자동 재연결. 서버에 ping_interval=30s 추가.
 * - 2026-03-15 Claude: 절전/노트북 덮개 복귀 시 WebSocket 자동 재연결 — visibilitychange 이벤트 감지.
 *                      isTerminalMode=true && hasAttachedTerminal=false 상태에서 화면 복귀 시 launchAgent 자동 호출.
 *                      근본 원인: ws.onclose가 hasAttachedTerminal=false로 하지만 isTerminalMode는 유지 → 팝업 무한 표시 버그.
 * - 2026-03-08 Claude: 서버 실행 상태 자동 감지 — agentTerminals 폴링으로 LLM 실행 중인 슬롯 자동 터미널 모드 전환.
 *                      isTerminalMode=false 상태에서 T${slotId+1}.status==='running'이면 선택 카드 건너뛰고 모니터링 뷰 표시.
 * - 2026-03-08 Claude: Codex CLI 에이전트 선택 카드 추가 — Code2 아이콘 + 오렌지 색상테마.
 *                      launchAgent('codex', yolo) 연결 완료. 백엔드 codex 케이스는 이미 존재함.
 * - 2026-03-07 Claude: 모니터링 뷰 슬림화 — max-h 280px→160px, 헤더 h-6→h-5로 축소.
 *                      파이프라인 단계 표시는 ActivityBar LED 링으로 통합 완료.
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리. constants.ts의 공유 상수 사용.
 * - 2026-03-05 Claude: 파일 뷰어 제거 → 자율 에이전트 모니터링 뷰로 교체.
 *                      showActiveFile → showMonitor, 파일 fetch 로직 완전 삭제.
 *                      모니터링 뷰: 에이전트 상태/현재 태스크/최근 로그5줄/최신 메시지 표시.
 * - 2026-03-05 Claude: 모니터링 뷰에 터미널별 스킬 실행 기록 추가.
 *                      skill_results.jsonl에서 terminal_id 필터링 → 각 슬롯 귀속 결과 표시.
 *                      모니터링 높이 h-[160px] 고정 → max-h-[280px] 스크롤로 변경.
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Terminal, TerminalSquare, X, Zap, ClipboardList, MessageSquare, Cpu, Trash2, Activity, CheckCircle2, Clock, Code2, Orbit
} from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { API_BASE, WS_PORT, Shortcut, defaultShortcuts, SLASH_COMMANDS } from '../constants';
import { LogRecord, AgentMessage, Task } from '../types';
import { slugifyProjectPath } from '../lib/projectContext';
import ChatSlot from './ChatSlot';
import ShortcutEditModal from './terminal/ShortcutEditModal';
import SlashCommandMenu from './terminal/SlashCommandMenu';

// 파이프라인 단계 정의는 이제 ActivityBar로 통합되었습니다.

interface TerminalSlotProps {
  slotId: number;
  logs: LogRecord[];
  currentPath: string;
  terminalCount: number;
  locks: Record<string, string>;
  messages: AgentMessage[];
  tasks: Task[];
  antigravityUsage: any;
  // Claude Code 세션 컨텍스트 사용량 — 컬러 블록 바 표시용
  claudeUsage: {
    input_tokens: number; output_tokens: number; cache_read: number; cache_write: number;
    context_used?: number;  // [2026-04-21] input + cache_read + cache_write (캐시 포함 실제 점유)
    model: string; context_window: number; percentage: number; last_ts: string;
    // [2026-04-21] 5시간 sliding window 집계 (쿼터 한도 모르므로 절대값만)
    last_5h_tokens?: number;
    last_5h_messages?: number;
    last_5h_oldest_ts?: string;
  } | null;
  // 터미널별 에이전트 파이프라인 상태 — App.tsx에서 /api/agent/terminals 폴링으로 수신
  agentTerminals?: Record<string, any>;
  // 오케스트레이터 스킬 체인 데이터 — /api/orchestrator/skill-chain 폴링
  orchestratorData?: { skill_registry?: any[]; terminals?: Record<string, any> };
  // 하이브 활동 이벤트 — /api/hive/activity 폴링 (memory_write/orchestrate 여부 표시용)
  hiveActivity?: Array<{ timestamp: string; agent: string; type: string; task: string }>;
  // 오피스 워크스페이스 프로필: 슬롯 사용자 지정 이름
  slotName?: string;
  // 오피스 워크스페이스 프로필: 선택된 모델 ID
  slotModel?: string;
  // 오피스 워크스페이스 프로필: 선택된 CLI (claude/antigravity/codex)
  slotCli?: string;
}

export default function TerminalSlot({
  slotId, logs, currentPath, terminalCount, locks, messages, tasks, antigravityUsage, claudeUsage, agentTerminals, orchestratorData, hiveActivity, slotName, slotModel, slotCli
}: TerminalSlotProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isComposingRef = useRef(false);
  // FitAddon 참조 보관 (모니터링 뷰 토글 시 xterm 재조정용)
  const fitAddonRef = useRef<FitAddon | null>(null);
  // ResizeObserver 참조: 터미널 컨테이너 크기 변화 자동 감지용
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  // [버그수정 2026-03-20] WebSocket 자동 재연결 타이머 참조
  const wsReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsReconnectAttemptRef = useRef(0);

  const [isTerminalMode, setIsTerminalMode] = useState(false);
  const [hasAttachedTerminal, setHasAttachedTerminal] = useState(false);
  const [activeAgent, setActiveAgent] = useState('');
  const [inputValue, setInputValue] = useState('');
  const [shortcuts, setShortcuts] = useState<Shortcut[]>(() => {
    try {
      const saved = localStorage.getItem('hive_shortcuts');
      return saved ? JSON.parse(saved) : defaultShortcuts;
    } catch { return defaultShortcuts; }
  });
  const [showShortcutEditor, setShowShortcutEditor] = useState(false);
  // 슬래시 커맨드 팝업 표시 여부
  const [showSlashMenu, setShowSlashMenu] = useState(false);

  // 터미널 우클릭 컨텍스트 메뉴 위치 및 선택 유무 상태
  // null이면 메뉴 닫힘, {x,y,hasSelection}이면 해당 위치에 메뉴 표시
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; hasSelection: boolean } | null>(null);

  // Claude 컨텍스트 바 상세 토글 (클릭 시 In/Out/Cache 2행 표시)
  const [showCtxDetail, setShowCtxDetail] = useState(false);

  // 자율 에이전트 모니터링 뷰 표시 여부 — localStorage에서 마지막 상태 복원 (기본값: false)
  // 기본값 false: 터미널 화면 최대 확보, 필요 시 버튼으로 토글
  const [showMonitor, setShowMonitor] = useState<boolean>(() => {
    const saved = localStorage.getItem('hive_monitor_enabled');
    return saved === null ? false : saved === 'true';
  });

  // Git 브랜치명 — 헤더에 현재 브랜치 표시 (cmux 스타일)
  const [gitBranch, setGitBranch] = useState<string>('');

  // 에이전트 완료 알림 — 이전 상태 추적용 ref (WORKING→IDLE 전환 시 브라우저 알림)
  const prevAgentStatus = useRef<string>('IDLE');

  // 이 슬롯의 터미널 ID — cli_agent.py의 _terminals 키와 일치 (T1, T2, ...)
  const terminalId = `T${slotId + 1}`;
  // 오피스 프로필 사용자 이름 (없으면 T1 등 기본값)
  const displayName = slotName || terminalId;

  // 이 슬롯의 에이전트 타입 (claude / antigravity / codex)
  // [버그수정 2026-03-08] Codex가 'claude'로 분류되어 T1 데이터를 T3에 표시하는 문제 수정
  const agentType = activeAgent.toLowerCase().includes('antigravity') ? 'antigravity'
    : activeAgent.toLowerCase().includes('codex') ? 'codex'
    : 'claude';

  // 이 슬롯의 데이터 결정 전략:
  // 1순위) 같은 ID의 터미널 데이터 (terminalId 일치)
  // 2순위) 같은 에이전트 타입 중 가장 최근 활성 터미널 (TERMINAL_ID 환경변수 불일치 대응)
  //        → 예: 사용자가 TERMINAL_ID=2로 Claude 실행 → T2 데이터를 UI슬롯1(T1)에서도 볼 수 있게
  const termDataById = agentTerminals?.[terminalId] as any;
  // T1 데이터가 있어도 cli(에이전트 타입)가 다르면 폴백 — 슬롯 번호≠TERMINAL_ID 환경변수 대응
  const slotMatchesAgent = termDataById && termDataById.cli === agentType;
  const termDataByAgent = !slotMatchesAgent
    ? (Object.values(agentTerminals ?? {}) as any[])
        .filter((t: any) => t.cli === agentType && t.status === 'running')
        .sort((a: any, b: any) => (b.ts ?? '').localeCompare(a.ts ?? ''))
        [0] ?? {}
    : null;
  const termData: any = slotMatchesAgent ? termDataById : (termDataByAgent ?? {});

  const pipelineStage = termData.pipeline_stage ?? 'idle';
  // 현재 실행 중인 태스크 설명 — 완료(done)된 경우 표시 안 함 (사용자 지시문이 잔류하는 문제 방지)
  const liveTask: string | null = (termData.task && termData.task !== '[외부]' && termData.status !== 'done')
    ? termData.task
    : null;

  // 오케스트레이터 스킬 체인 — 이 터미널에 할당된 체인 (slotId+1 = 터미널 번호)
  const chainData = orchestratorData?.terminals?.[String(slotId + 1)] ?? null;
  const chainSteps: any[] = chainData?.steps ?? [];
  const chainRequest: string = chainData?.request ?? '';

  // 현재 에이전트가 잠근 파일 찾기
  const lockedFileByAgent = Object.entries(locks).find(([_, owner]) => owner === activeAgent)?.[0];

  // 이 에이전트에게 할당된 진행 중 / 대기 작업 수
  const myPendingTasks = isTerminalMode
    ? tasks.filter(t => (t.assigned_to === activeAgent || t.assigned_to === 'all') && t.status !== 'done')
    : [];

  // 현재 에이전트에게 온 최근 메시지 (최근 10분 이내, 터미널 실행 중일 때만 표시)
  const recentAgentMsgs = isTerminalMode ? messages.filter(m => {
    const isForMe = m.to === activeAgent || m.to === 'all';
    const isRecent = (Date.now() - new Date(m.timestamp).getTime()) < 10 * 60 * 1000;
    return isForMe && isRecent;
  }) : [];

  const saveShortcuts = (newShortcuts: Shortcut[]) => {
    setShortcuts(newShortcuts);
    localStorage.setItem('hive_shortcuts', JSON.stringify(newShortcuts));
  };

  // XTerm 인스턴스 생성 + WebSocket PTY 연결 + ResizeObserver 등록
  const launchAgent = (agent: string, yolo: boolean = false) => {
    // 기존 터미널이 살아있으면 먼저 정리 — dispose 없이 덮어쓰면
    // 이전 xterm 캔버스가 DOM에 남아 잔상(이중 삼중 출력) 현상 발생
    // [버그수정 2026-03-20] 재연결 타이머 정리 (새 연결 시작 전)
    if (wsReconnectTimerRef.current) {
      clearTimeout(wsReconnectTimerRef.current);
      wsReconnectTimerRef.current = null;
    }
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    // xterm이 DOM에 주입한 캔버스/래퍼 엘리먼트 제거 (dispose만으론 DOM 잔여물 남음)
    if (xtermRef.current) {
      xtermRef.current.innerHTML = '';
    }

    setIsTerminalMode(true);
    setActiveAgent(agent);
    // 터미널 재시작 시 localStorage 기반으로 모니터링 뷰 상태 복원
    // closeTerminal이 isTerminalMode만 false로 하므로, showMonitor를 명시적으로 동기화
    setShowMonitor(localStorage.getItem('hive_monitor_enabled') !== 'false');

    setTimeout(() => {
      if (!xtermRef.current) return;
      const term = new XTerm({
        theme: { background: '#1e1e1e', foreground: '#cccccc', cursor: '#3794ef', selectionBackground: '#3794ef55' },
        fontFamily: "'Fira Code', 'Consolas', monospace",
        fontSize: 13,
        cursorBlink: true,
        // 스크롤 설정 — 이전 출력 확인 가능하도록 충분한 버퍼 확보
        scrollback: 10000,
        smoothScrollDuration: 100,
        scrollOnUserInput: true
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.loadAddon(new WebLinksAddon((_event, uri) => {
        fetch(`${API_BASE}/api/open-external`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: uri }),
        }).catch(() => {
          window.open(uri, '_blank', 'noopener,noreferrer');
        });
      }));
      term.open(xtermRef.current);
      fitAddon.fit();
      termRef.current = term;

      // 클립보드 복사 헬퍼 — navigator.clipboard API 실패 시 execCommand 폴백
      const copyToClipboard = async (text: string) => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          // pywebview 등 Clipboard API 미지원 환경 폴백
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }
      };

      // 텍스트 드래그(선택) 시 자동 클립보드 복사
      term.onSelectionChange(() => {
        if (term.hasSelection()) {
          copyToClipboard(term.getSelection());
        }
      });

      // 터미널 우클릭: 컨텍스트 메뉴 표시
      // 텍스트 선택 유무를 메뉴 state에 전달 → JSX에서 복사/붙여넣기 버튼 구성
      xtermRef.current.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        setCtxMenu({ x: e.clientX, y: e.clientY, hasSelection: term.hasSelection() });
      });

      // ref에 저장하여 모니터링 뷰 토글 시에도 fit() 호출 가능하게
      fitAddonRef.current = fitAddon;
      // ResizeObserver: 터미널 컨테이너 크기 변화 감지 시 자동으로 xterm 재조정
      // 모니터링 뷰 열기/닫기로 컨테이너 높이가 바뀔 때마다 즉시 반응
      const termContainer = xtermRef.current;
      if (termContainer) {
        const ro = new ResizeObserver(() => fitAddon.fit());
        ro.observe(termContainer);
        resizeObserverRef.current = ro;
      }
      // WebSocket에 yolo/model/name + project_id 상태 전달 (Phase 2-5.3a)
      const projectId = slugifyProjectPath(currentPath);
      const wsParams = new URLSearchParams({
        agent: slotCli || agent,
        cwd: currentPath,
        cols: term.cols.toString(),
        rows: term.rows.toString(),
        yolo: yolo.toString(),
        ...(projectId ? { project_id: projectId } : {}),
        ...(slotModel ? { model: slotModel } : {}),
        ...(slotName ? { name: slotName } : {}),
      });
      const ws = new WebSocket(`ws://${window.location.hostname}:${WS_PORT}/pty/slot${slotId}?${wsParams.toString()}`);
      wsRef.current = ws;
      ws.onopen = () => {
        setHasAttachedTerminal(true);
        // 재연결 성공 시 카운터 리셋
        wsReconnectAttemptRef.current = 0;
        const modeText = yolo ? "\x1b[38;5;196m[YOLO MODE]\x1b[0m" : "\x1b[38;5;34m[NORMAL MODE]\x1b[0m";
        term.write(`\r\n\x1b[38;5;39m[HIVE] ${agent.toUpperCase()} ${modeText} 터미널 연결 성공 \x1b[38;5;245m[node-pty]\x1b[0m\r\n\x1b[38;5;244m> CWD: ${currentPath}\x1b[0m\r\n\r\n`);
        // WS 연결 직후 현재 터미널 크기를 PTY에 전달
        // ResizeObserver가 WS 연결 전에 fire됐을 경우 누락된 resize를 보정
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      };
      // [버그수정 2026-03-20] 장시간 idle 시 WS 끊김 → 자동 재연결
      // 원인: OS TCP keepalive 타임아웃 또는 네트워크 일시 단절로 WS가 닫힘.
      // 해결: onclose에서 지수 백오프(1s→2s→4s...최대30s)로 자동 재연결 시도.
      //       사용자가 명시적으로 터미널을 닫은 경우(cleanupTerminal)는 재연결하지 않음.
      // [2026-03-30 Claude] Stale closure 버그 수정 — hasAttachedTerminal 대신 ref 사용
      // 기존: onclose 콜백이 클로저 시점의 hasAttachedTerminal(항상 false)을 캡처
      // → 정상 연결 중에도 재연결 시도 가능 (무한 재연결 루프 위험)
      // 수정: wsRef.current?.readyState로 실제 연결 상태를 직접 확인
      ws.onclose = (event) => {
        setHasAttachedTerminal(false);
        // code 1000(정상종료) 또는 터미널 모드가 꺼진 경우 재연결하지 않음
        if (event.code === 1000) return;
        // 지수 백오프: 1s, 2s, 4s, 8s, 16s, 30s (최대)
        const attempt = wsReconnectAttemptRef.current;
        const delay = Math.min(1000 * Math.pow(2, attempt), 30000);
        wsReconnectAttemptRef.current = attempt + 1;
        if (attempt < 10) {
          term.write(`\r\n\x1b[38;5;208m[HIVE] 연결 끊김 — ${delay / 1000}초 후 자동 재연결 (${attempt + 1}/10)\x1b[0m\r\n`);
          wsReconnectTimerRef.current = setTimeout(() => {
            // ref 기반으로 실제 상태 확인 — stale closure 방지
            const currentWs = wsRef.current;
            const isAlreadyConnected = currentWs && currentWs.readyState === WebSocket.OPEN;
            if (termRef.current && !isAlreadyConnected) {
              launchAgent(agent, false);
            }
          }, delay);
        }
      };
      ws.onmessage = async (e) => {
        const data = e.data instanceof Blob ? await e.data.text() : e.data;
        term.write(data);
      };
      term.onData(data => ws.readyState === WebSocket.OPEN && ws.send(data));
      // xterm cols/rows가 바뀔 때마다 서버 PTY에 SIGWINCH 전달
      // fitAddon.fit() → term.onResize 순으로 발생하므로 여기서 resize 메시지 전송
      term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
      });
      // 창 크기 변경 시 터미널 재조정 (클린업 포함)
      const handleResize = () => fitAddon.fit();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, 50);
  };

  // 컨텍스트 메뉴가 열려 있을 때 바깥 클릭 시 닫기
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [ctxMenu]);

  // 모니터링 뷰 토글 시 xterm 터미널 크기 재조정
  // ResizeObserver가 주 역할이며, 이 타이머는 폴백으로 이중 호출해 안정성 확보
  useEffect(() => {
    if (!fitAddonRef.current) return;
    const fitNow = () => {
      fitAddonRef.current?.fit();
      termRef.current?.scrollToBottom();
    };
    const raf1 = requestAnimationFrame(fitNow);
    const raf2 = requestAnimationFrame(() => requestAnimationFrame(fitNow));
    const t1 = setTimeout(fitNow, 100);
    const t2 = setTimeout(fitNow, 350);
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [showMonitor]);


  const closeTerminal = () => {
    // [버그수정 2026-03-20] 명시적 종료 시 재연결 타이머 정리
    if (wsReconnectTimerRef.current) {
      clearTimeout(wsReconnectTimerRef.current);
      wsReconnectTimerRef.current = null;
    }
    wsReconnectAttemptRef.current = 0;
    setIsTerminalMode(false);
    setHasAttachedTerminal(false);
    fitAddonRef.current = null;
    // ResizeObserver 해제 (메모리 누수 방지)
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (wsRef.current) wsRef.current.close(1000);  // 1000=정상종료 → onclose에서 재연결 안 함
    if (termRef.current) termRef.current.dispose();
  };

  const handleSend = (text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    const ws = wsRef.current;
    const cleanText = text.replace(/[\r\n]+$/, '');
    if (!cleanText) return;

    const lines = cleanText.replace(/\r\n/g, '\n').split('\n');
    for (const line of lines) {
      ws.send(`${line}\r`);
    }
    setInputValue('');
    termRef.current?.focus();
  };

  // 터미널 실행 중이면 활성 에이전트 이름으로 로그 필터링 (정확한 귀속)
  // 유휴 상태이면 해시 기반 분배 (배경 로그 표시용)
  const slotLogs = isTerminalMode
    ? logs.filter(l => l.agent?.toLowerCase() === activeAgent.toLowerCase())
    : logs.filter(l => {
        let hash = 0;
        // [버그수정] terminal_id가 null/undefined일 때 .length 접근 → TypeError 방어
        const tid = l.terminal_id ?? '';
        for (let i = 0; i < tid.length; i++) hash = ((hash << 5) - hash) + tid.charCodeAt(i);
        return Math.abs(hash) % terminalCount === slotId;
      });

  // 새 로그 도착 시 자동 스크롤
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [slotLogs.length]);

  // Git 브랜치 폴링 — 터미널 실행 중일 때 5초마다 현재 브랜치 확인
  useEffect(() => {
    if (!isTerminalMode) return;
    const fetchBranch = () => {
      fetch(`${API_BASE}/api/git/status`)
        .then(res => res.json())
        .then(data => { if (data.branch) setGitBranch(data.branch); })
        .catch((err) => console.error('[TerminalSlot] fetch error:', err));
    };
    fetchBranch();
    const iv = setInterval(fetchBranch, 5000);
    return () => clearInterval(iv);
  }, [isTerminalMode]);

  // 모니터링 뷰: 에이전트 상태 계산
  // 최근 30초 이내 로그가 있으면 RUNNING, 태스크 진행 중이면 WORKING, 그 외 IDLE
  const now = Date.now();
  const recentLog = slotLogs.find(l => (now - new Date(l.ts_start ?? 0).getTime()) < 30_000);
  const inProgressTask = myPendingTasks.find(t => t.status === 'in_progress');
  // pipelineStage도 agentStatus 판단에 반영 — hook에서 modifying/analyzing 단계면 WORKING 표시
  const isActiveStage = ['analyzing', 'modifying', 'verifying'].includes(pipelineStage);
  // termData.status === 'running': 외부 Antigravity 감지(_detect_external_antigravity) 포함, 서버가 실행 중으로 판단한 경우 RUNNING 표시
  const isServerRunning = termData.status === 'running' || termData.status === 'started';
  const agentStatus = isActiveStage ? 'WORKING' : inProgressTask ? 'WORKING' : recentLog ? 'RUNNING' : isServerRunning ? 'RUNNING' : 'IDLE';
  const statusColor = agentStatus === 'WORKING' ? 'text-yellow-400' : agentStatus === 'RUNNING' ? 'text-green-400' : 'text-[#858585]';
  const statusDot = agentStatus === 'IDLE' ? 'bg-[#555]' : agentStatus === 'RUNNING' ? 'bg-green-400 animate-pulse' : 'bg-yellow-400 animate-pulse';

  // 에이전트 완료 알림 — WORKING/RUNNING → IDLE 전환 시 브라우저 알림 발송 (cmux 알림 시스템)
  useEffect(() => {
    if (!isTerminalMode) return;
    const prev = prevAgentStatus.current;
    if ((prev === 'WORKING' || prev === 'RUNNING') && agentStatus === 'IDLE') {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`[T${slotId + 1}] ${activeAgent} 작업 완료`, {
          body: liveTask ?? '에이전트가 작업을 완료했습니다.',
          icon: '/favicon.ico',
        });
      } else if ('Notification' in window && Notification.permission !== 'denied') {
        Notification.requestPermission();
      }
    }
    prevAgentStatus.current = agentStatus;
  }, [agentStatus, isTerminalMode, activeAgent, slotId, liveTask]);

  // 서버 실행 상태 자동 감지 — agentTerminals 폴링(3초) 결과에 따라 터미널 모드 자동 전환
  // 사용자가 버튼을 누르지 않아도 서버에서 LLM이 실행 중이면 선택 카드를 건너뜁니다.
  // 반대로 idle/done 전환 시에는 자동 복귀하지 않음 (출력 내용 보존, 사용자가 직접 닫기)
  // [버그수정 2026-03-08] isTerminalMode=true여도 activeAgent는 항상 서버 cli에 동기화해야 함.
  // 이전에 Claude로 실행 후 Codex로 재시작하면 activeAgent='claude' 잔류 → T1 데이터 표시 버그.
  useEffect(() => {
    const serverStatus = agentTerminals?.[terminalId];
    if (serverStatus?.status === 'running' || serverStatus?.status === 'started') {
      const detectedCli = serverStatus.cli ?? 'claude';
      // activeAgent는 항상 갱신 — 에이전트 타입이 바뀌어도 올바른 termData 선택 보장
      if (detectedCli) setActiveAgent(detectedCli);
      if (!isTerminalMode && !hasAttachedTerminal) {
        setShowMonitor(true); // 모니터링 뷰 자동 활성화 (XTerm 없이도 상태 확인 가능)
      }
    }
  }, [agentTerminals, terminalId, isTerminalMode, hasAttachedTerminal]);

  // [버그수정 2026-03-15] 절전/노트북 덮개 복귀 시 WebSocket 자동 재연결
  // 원인: PC 절전 또는 노트북 덮개 닫기 → 열기 시 WebSocket이 끊어지면
  //       ws.onclose → hasAttachedTerminal=false 되지만 isTerminalMode=true 유지됨.
  //       visibilitychange 이벤트 미처리로 인해 "터미널 출력 연결이 아직 없습니다" 팝업이 계속 떠 있음.
  // 해결: visibilitychange 이벤트로 화면 복귀를 감지하고 터미널 자동 재연결.
  useEffect(() => {
    if (!isTerminalMode) return;
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && !hasAttachedTerminal) {
        // 화면이 다시 켜질 때 WS가 끊어진 상태이면 같은 에이전트로 자동 재연결
        launchAgent(activeAgent || 'claude', false);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [isTerminalMode, hasAttachedTerminal, activeAgent]);

  // 알림 링 글로우 — 에이전트 상태에 따라 패널 테두리 색상/그림자 변경 (cmux 스타일)
  const ringClass = !isTerminalMode
    ? 'border border-black/40'
    : agentStatus === 'WORKING'
      ? 'border border-yellow-400/50 shadow-[0_0_12px_2px_rgba(234,179,8,0.25)]'
      : agentStatus === 'RUNNING'
        ? 'border border-blue-400/50 shadow-[0_0_12px_2px_rgba(96,165,250,0.2)]'
        : 'border border-black/40';

  return (
    // h-full: 그리드 셀 높이를 명시적으로 채워야 flex 자식들이 올바른 높이를 전달받음
    <div className={`h-full min-w-0 min-h-0 bg-[#252526] ${ringClass} rounded-md flex flex-col overflow-hidden shadow-inner relative transition-all duration-700`}>
      {/* 터미널 헤더 — 슬롯 번호, 에이전트명, 락/작업/메시지 배지 */}
      <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2 max-w-[60%] overflow-hidden">
          <Terminal className="w-3 h-3 text-accent shrink-0" />
          <span className="text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider truncate">
            {isTerminalMode ? `${displayName} - ${activeAgent}` : displayName}
          </span>
          {/* Git 브랜치 배지 — cmux 스타일 수직 탭 컨텍스트 정보 */}
          {gitBranch && (
            <span className="text-[8px] font-mono text-accent/70 bg-accent/10 border border-accent/20 px-1.5 py-0.5 rounded shrink-0">
              {gitBranch}
            </span>
          )}
          {lockedFileByAgent && (
            <div className="flex items-center gap-1.5 ml-2 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] text-yellow-500 animate-pulse shrink-0">
              <Zap className="w-2.5 h-2.5" />
              <span className="font-mono">LOCK: {lockedFileByAgent.split(/[\\\/]/).pop()}</span>
            </div>
          )}
          {/* 이 에이전트에게 할당된 작업 수 배지 */}
          {myPendingTasks.length > 0 && (
            <div
              className="flex items-center gap-1 ml-1 px-1.5 py-0.5 bg-yellow-500/10 border border-yellow-500/30 rounded text-[9px] text-yellow-400 shrink-0"
              title={myPendingTasks.map(t => t.title).join(', ')}
            >
              <ClipboardList className="w-2.5 h-2.5" />
              <span>{myPendingTasks.length}개 작업</span>
            </div>
          )}
          {/* 이 에이전트에게 온 최근 메시지 알림 배지 */}
          {recentAgentMsgs.length > 0 && (
            <div
              className="flex items-center gap-1 ml-1 px-1.5 py-0.5 bg-primary/10 border border-primary/30 rounded text-[9px] text-primary shrink-0 animate-pulse"
              title={recentAgentMsgs[recentAgentMsgs.length - 1].content}
            >
              <MessageSquare className="w-2.5 h-2.5" />
              <span>{recentAgentMsgs.length}개 메시지</span>
            </div>
          )}
        </div>
        {!isTerminalMode ? (
          <div className="flex gap-2 items-center">
            <span className="text-[9px] text-[#858585] font-bold mr-1">에이전트 선택 대기 중...</span>
          </div>
        ) : (
          <div className="flex gap-2 items-center">
            {/* Claude Code 모델 배지 — main_model / bg_model 표시 (Claude 에이전트 실행 중일 때만) */}
            {agentType === 'claude' && termData.main_model && (
              <div className="flex items-center gap-1 px-1.5 py-0.5 bg-[#1a1a2e]/80 border border-blue-500/20 rounded text-[8px] text-blue-300/80 font-mono">
                <span className="opacity-60">M:</span>
                <span className="font-bold">{String(termData.main_model).replace('claude-', '').replace(/-\d{8}$/, '')}</span>
                {termData.bg_model && (
                  <>
                    <span className="opacity-40 mx-0.5">|</span>
                    <span className="opacity-60">BG:</span>
                    <span className="font-bold text-green-300/70">{String(termData.bg_model).replace('claude-', '').replace(/-\d{8}$/, '')}</span>
                  </>
                )}
              </div>
            )}

            {/* Antigravity 컨텍스트 사용량 표시 (에이전트가 antigravity일 때만) */}
            {activeAgent.toLowerCase().includes('antigravity') && antigravityUsage && (
              <div className="flex items-center gap-2 mr-2 px-2 py-0.5 bg-accent/10 border border-accent/20 rounded text-[9px] text-accent animate-in fade-in duration-500">
                <div className="flex flex-col items-end leading-none gap-0.5">
                  <span className="font-bold opacity-80 uppercase text-[8px]">Context</span>
                  <span className="font-black">{((antigravityUsage.total_tokens ?? 0) / 1000).toFixed(1)}K / {((antigravityUsage.context_window ?? 0) / 1000).toFixed(1)}K</span>
                </div>
                <div className="w-12 h-1.5 bg-black/40 rounded-full overflow-hidden border border-white/5 relative">
                  <div
                    className={`h-full transition-all duration-1000 ${antigravityUsage.percentage > 80 ? 'bg-red-500' : antigravityUsage.percentage > 50 ? 'bg-yellow-500' : 'bg-accent'}`}
                    style={{ width: `${Math.min(100, antigravityUsage.percentage)}%` }}
                  />
                </div>
                <span className="font-bold w-6 text-right">{Math.round(antigravityUsage.percentage ?? 0)}%</span>
              </div>
            )}

            {/* 자율 에이전트 모니터링 뷰 토글 버튼 — 상태를 localStorage에 저장하여 다음 실행 시 복원 */}
            <button
              onClick={() => { const next = !showMonitor; setShowMonitor(next); localStorage.setItem('hive_monitor_enabled', String(next)); }}
              className={`px-2 py-0.5 rounded text-[9px] border transition-all font-bold flex items-center gap-1 ${showMonitor ? 'bg-green-500/20 border-green-500/50 text-green-400' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
              title="자율 에이전트 실시간 모니터링"
            >
              <Activity className="w-2.5 h-2.5" />
              모니터링
            </button>
            <button onClick={closeTerminal} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>

      {/* ── Claude 컨텍스트 컬러 블록 바 — 클릭 시 상세 팝업 (리팩토링 복원 2026-03-26) ── */}
      {isTerminalMode && agentType === 'claude' && (() => {
        const ctx = claudeUsage;
        const CTX_MAX = ctx?.context_window ?? 200000;
        const inputTok = ctx?.input_tokens ?? 0;
        const outputTok = ctx?.output_tokens ?? 0;
        const cacheRead = ctx?.cache_read ?? 0;
        const cacheWrite = ctx?.cache_write ?? 0;
        // [2026-04-21] 실제 컨텍스트 점유 = 현재 턴 input + 캐시 히트 + 캐시 생성.
        // Claude Code CLI `/context` 와 동일. 서버가 context_used를 주면 그대로 쓰고
        // 없으면(구 응답) 프론트에서 합산한다.
        const usedTok = ctx?.context_used ?? (inputTok + cacheRead + cacheWrite);
        const ctxPct = ctx ? Math.round((usedTok / CTX_MAX) * 100) : 0;
        const freeTok = Math.max(0, CTX_MAX - usedTok);

        // 각 토큰 타입의 컨텍스트 점유 %
        const cacheReadPct = Math.min(100, (cacheRead / CTX_MAX) * 100);
        const cacheWritePct = Math.min(100, (cacheWrite / CTX_MAX) * 100);
        const inputOnlyPct = Math.max(0, ctxPct - cacheReadPct - cacheWritePct);
        const freePct = Math.max(0, 100 - ctxPct);

        // 배경 & 경고 색
        const dangerBg = ctxPct >= 80 ? 'bg-red-950/30 border-red-500/15'
          : ctxPct >= 60 ? 'bg-yellow-950/30 border-yellow-500/15'
          : 'bg-[#0d1117] border-white/5';
        const modelColor = ctxPct >= 80 ? '#f87171' : ctxPct >= 60 ? '#facc15' : '#a3e635';

        // 모델명 단축
        const modelShort = ctx?.model
          ? ctx.model.replace(/^claude-/, '').replace(/-(\d)/, ' $1').replace(/-latest$/, '').replace(/-\d{8}$/, '').replace(/\b\w/g, c => c.toUpperCase())
          : 'Claude';
        const maxLabel = CTX_MAX >= 1_000_000 ? `${CTX_MAX / 1_000_000}M` : `${CTX_MAX / 1000}k`;
        const usedLabel = `${Math.round(usedTok / 1000)}k`;

        // 블록 그리드 색상 결정 (100개 블록, 각 1%)
        const getBlockColor = (idx: number) => {
          const p = idx + 1;
          if (p <= cacheReadPct) return '#22d3ee';
          if (p <= cacheReadPct + cacheWritePct) return '#4ade80';
          if (p <= cacheReadPct + cacheWritePct + inputOnlyPct) return '#fbbf24';
          return '#1e2130';
        };

        // 상대 시간
        const ctxRelTime = (() => {
          if (!ctx?.last_ts) return '';
          const diff = Math.floor((Date.now() - new Date(ctx.last_ts).getTime()) / 1000);
          if (diff < 60) return `${diff}초 전`;
          if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
          if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
          return `${Math.floor(diff / 86400)}일 전`;
        })();

        // 카테고리 목록
        const pureInput = Math.max(0, inputTok - cacheRead - cacheWrite);
        const categories = [
          { label: '입력 토큰', tok: pureInput, pct: inputOnlyPct, color: '#fbbf24' },
          ...(cacheWrite > 0 ? [{ label: '캐시 쓰기', tok: cacheWrite, pct: cacheWritePct, color: '#4ade80' }] : []),
          ...(cacheRead > 0 ? [{ label: '캐시 읽기', tok: cacheRead, pct: cacheReadPct, color: '#22d3ee' }] : []),
          { label: '출력 누적', tok: outputTok, pct: Math.round((outputTok / CTX_MAX) * 100), color: '#888' },
          { label: '여유 공간', tok: freeTok, pct: freePct, color: '#2a2d3a' },
        ];
        const fmtTok = (t: number) => t >= 1000 ? `${(t / 1000).toFixed(1)}k` : `${t}`;

        return (
          <div className="relative shrink-0">
            {/* 단일 행 바 (항상 표시) */}
            <div
              className={`border-b px-3 py-[3px] flex items-center gap-2 font-mono text-[10px] overflow-hidden cursor-pointer select-none transition-colors hover:brightness-110 ${dangerBg}`}
              onClick={() => setShowCtxDetail(p => !p)}
              title="클릭하여 컨텍스트 상세 보기"
            >
              {/* 컬러 블록 바: 20개 █, 각 5% */}
              <div className="flex shrink-0 leading-none">
                {Array.from({ length: 20 }, (_, idx) => {
                  const p = (idx + 1) * 5;
                  const color = p <= cacheReadPct ? '#22d3ee'
                    : p <= cacheReadPct + cacheWritePct ? '#4ade80'
                    : p <= ctxPct ? '#fbbf24'
                    : '#2a2d3a';
                  return <span key={idx} style={{ color, fontSize: 11, letterSpacing: '-0.5px' }}>█</span>;
                })}
              </div>
              {/* 텍스트: 모델명 (컨텍스트 크기) · 사용량 */}
              <div className="flex items-center gap-0 whitespace-nowrap flex-1 min-w-0">
                <span className="font-semibold" style={{ color: modelColor }}>{modelShort}</span>
                <span className="text-[#555] ml-1 text-[9px]">({maxLabel} context)</span>
                <span className="text-[#444] mx-1.5">·</span>
                <span className="text-[#ccc]">{usedLabel}/{maxLabel} tokens ({ctxPct}%)</span>
                {ctx && ctxRelTime && <span className="text-[#333] ml-2 text-[9px]">{ctxRelTime}</span>}
                <span className="ml-auto text-[#333] text-[8px]">{showCtxDetail ? '▲' : '▼'}</span>
              </div>
              {!ctx && <span className="text-[9px] text-[#333] italic">Claude Code 세션 대기 중...</span>}
            </div>
            {/* 데이터 없을 때 2행: No usage data yet */}
            {!ctx && (
              <div className="border-b border-white/5 bg-[#0d1117] px-3 py-[2px] font-mono text-[9px] text-[#444] italic">
                No usage data yet
              </div>
            )}
            {/* 데이터 있을 때 2행: In / Out / Cache+ / Cache~ · 5h 누적 */}
            {ctx && (
              <div className="border-b border-white/5 bg-[#0d1117] px-3 py-[2px] font-mono text-[9px] text-[#888] flex items-center gap-3 flex-wrap">
                <span>In: <span className="text-[#fbbf24]">{fmtTok(inputTok)}</span></span>
                <span>Out: <span className="text-[#ccc]">{fmtTok(outputTok)}</span></span>
                {cacheWrite > 0 && <span>Cache+: <span className="text-[#4ade80]">{fmtTok(cacheWrite)}</span></span>}
                {cacheRead > 0 && <span>Cache~: <span className="text-[#22d3ee]">{fmtTok(cacheRead)}</span></span>}
                {(ctx.last_5h_tokens ?? 0) > 0 && (
                  <span className="ml-auto text-[#666]" title="지난 5시간 누적 (cwd 일치 세션)">
                    5h: <span className="text-[#a3e635]">{fmtTok(ctx.last_5h_tokens ?? 0)}</span>
                    <span className="text-[#444] ml-1">· {ctx.last_5h_messages ?? 0}회</span>
                  </span>
                )}
              </div>
            )}

            {/* 상세 팝업: /context 스타일 블록 그리드 + 카테고리 + 5h sliding (클릭 토글) */}
            {showCtxDetail && ctx && (() => {
              // 5시간 집계 리셋 시각 계산: oldest_ts + 5h
              const oldestMs = ctx.last_5h_oldest_ts ? new Date(ctx.last_5h_oldest_ts).getTime() : 0;
              const resetLabel = oldestMs
                ? (() => {
                    const remainSec = Math.max(0, Math.floor((oldestMs + 5 * 3600 * 1000 - Date.now()) / 1000));
                    if (remainSec <= 0) return '곧 초기화';
                    const h = Math.floor(remainSec / 3600);
                    const m = Math.floor((remainSec % 3600) / 60);
                    return h > 0 ? `${h}h ${m}m 후` : `${m}m 후`;
                  })()
                : '';
              return (
                <div className="absolute top-full left-0 right-0 z-50 bg-[#0d1117] border-b border-x border-white/10 shadow-2xl font-mono text-[10px] px-3 pt-2 pb-3 space-y-3">
                  {/* ── 상단 프로그레스 바 — CLI /context 스타일 ── */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[#ccc] font-bold text-[11px]">컨텍스트 창</span>
                      <span className="text-[#ccc] text-[10px]">
                        {usedLabel}/{maxLabel} ({ctxPct}%)
                      </span>
                    </div>
                    <div className="h-2 bg-[#1a1a2e] rounded-full overflow-hidden flex">
                      {/* 캐시 읽기 · 쓰기 · 입력 순서로 쌓인 스택형 프로그레스 */}
                      <div style={{ width: `${cacheReadPct}%`, backgroundColor: '#22d3ee' }} />
                      <div style={{ width: `${cacheWritePct}%`, backgroundColor: '#4ade80' }} />
                      <div style={{ width: `${inputOnlyPct}%`, backgroundColor: '#fbbf24' }} />
                    </div>
                  </div>

                  {/* ── 5시간 sliding window (쿼터 한도 없음, 절대값만) ── */}
                  {(ctx.last_5h_tokens ?? 0) > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[#ccc] font-bold text-[11px]">5시간 누적 사용량</span>
                        <span className="text-[#888] text-[10px]">
                          {fmtTok(ctx.last_5h_tokens ?? 0)} tokens · {ctx.last_5h_messages ?? 0}회
                          {resetLabel && <span className="text-[#555] ml-2">· {resetLabel} 롤오프</span>}
                        </span>
                      </div>
                      <div className="text-[9px] text-[#555] leading-tight">
                        cwd 일치 세션의 지난 5h assistant usage 합계.
                        쿼터 한도 정보는 Anthropic Admin API 필요.
                      </div>
                    </div>
                  )}

                  {/* ── 카테고리별 사용량 ── */}
                  <div className="pt-1 space-y-[3px]">
                    <div className="text-[#444] text-[9px] mb-1">카테고리별 사용량</div>
                    {categories.map(cat => (
                      <div key={cat.label} className="flex items-center gap-1">
                        <span style={{ color: cat.color, fontSize: 9 }}>█</span>
                        <span className="text-[#999] w-14">{cat.label}</span>
                        <span className="text-[#ccc] w-10 text-right">{fmtTok(cat.tok)}</span>
                        <div className="flex-1 h-1 bg-[#1a1a2e] rounded-full overflow-hidden ml-1">
                          <div className="h-full rounded-full" style={{ width: `${Math.min(100, cat.pct)}%`, backgroundColor: cat.color }} />
                        </div>
                        <span className="text-[#555] w-8 text-right">{Math.round(cat.pct)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
        );
      })()}

      {/* ── 터미널 뷰: isTerminalMode일 때 표시, 채팅 전환 시 hidden으로 유지 (unmount 안 함) ── */}
      {isTerminalMode && (
        <div className="flex-1 min-w-0 flex flex-col min-h-0 bg-[#1e1e1e]">

          {/* ── 자율 에이전트 모니터링 뷰 (상단 영역, 구 파일뷰어 자리) ── */}
          {showMonitor && (
            <div className="max-h-[160px] border-b border-black/40 bg-[#1a1a1a] flex flex-col shrink-0 overflow-y-auto custom-scrollbar">

              {/* 모니터링 헤더: 에이전트명 + 상태 뱃지 (슬림화) */}
              <div className="h-5 bg-[#2d2d2d] px-2 flex items-center justify-between shrink-0 border-b border-white/5">
                <div className="flex items-center gap-2">
                  <Activity className="w-3 h-3 text-green-400" />
                  <span className="text-[10px] font-bold text-[#cccccc] uppercase tracking-wider">
                    {activeAgent.toUpperCase()} 모니터링
                  </span>
                </div>
                {/* 에이전트 상태 뱃지 */}
                <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[9px] font-bold ${statusColor}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
                  {agentStatus}
                </div>
              </div>

              {/* 파이프라인 단계 표시는 이제 ActivityBar(왼쪽 메뉴)로 통합되어 여기서 제거되었습니다. */}

              {/* 오케스트레이터 스킬 체인 (있을 때만 표시) */}
              {chainSteps.length > 0 && (
                <div className="px-2 pb-1 shrink-0 border-b border-white/5">
                  {/* 요청 문구 (있을 때만) */}
                  {chainRequest && (
                    <div className="text-[8px] text-white/25 font-mono truncate mb-1">{chainRequest}</div>
                  )}
                  {/* 스킬 단계 배지 목록 */}
                  <div className="flex flex-wrap gap-1">
                    {chainSteps.map((step: any, idx: number) => {
                      const s = step.status as string;
                      const isRunning = s === 'running';
                      const isDone    = s === 'done';
                      const isFailed  = s === 'failed';
                      const colorCls  = isRunning ? 'border-yellow-400/60 text-yellow-300 bg-yellow-400/10 animate-pulse'
                                      : isDone    ? 'border-green-500/50 text-green-400 bg-green-500/10'
                                      : isFailed  ? 'border-red-500/50 text-red-400 bg-red-500/10'
                                      :             'border-white/10 text-white/30 bg-white/5';
                      const icon = isRunning ? '●' : isDone ? '✓' : isFailed ? '✗' : '○';
                      // skill_name을 한글 단축어로 변환 ('vibe-debug' → '디버그' 등)
                      const SKILL_KO: Record<string, string> = {
                        'debug': '디버그', 'tdd': 'TDD', 'brainstorm': '아이디어',
                        'write-plan': '계획작성', 'execute-plan': '계획실행',
                        'code-review': '코드리뷰', 'release': '릴리스',
                      };
                      const rawKey = (step.skill_name as string).replace(/^vibe-/, '');
                      const label = SKILL_KO[rawKey] ?? rawKey;
                      return (
                        <div
                          key={idx}
                          className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[9px] font-mono font-bold ${colorCls}`}
                          title={`${step.skill_name} (${s})`}
                        >
                          <span>{icon}</span>
                          <span>{label}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 모니터링 본문 — 오케스트레이션 + 하이브 저장 상태 중심으로 재설계 */}
              <div className="flex-1 overflow-hidden flex flex-col px-2 pb-2 gap-1.5">

                {/* ── 현재 작업 ── */}
                <div className="flex items-start gap-2 shrink-0 mt-1">
                  {liveTask ? (
                    <>
                      <Clock className="w-3 h-3 text-yellow-400 mt-0.5 shrink-0" />
                      <span className="text-[10px] text-yellow-300 font-mono leading-tight truncate">
                        {liveTask}
                      </span>
                    </>
                  ) : inProgressTask ? (
                    <>
                      <Clock className="w-3 h-3 text-yellow-400 mt-0.5 shrink-0" />
                      <span className="text-[10px] text-yellow-300 font-mono leading-tight truncate">
                        {inProgressTask.title ?? '태스크 진행 중...'}
                      </span>
                    </>
                  ) : myPendingTasks.length > 0 ? (
                    <>
                      <ClipboardList className="w-3 h-3 text-[#858585] mt-0.5 shrink-0" />
                      <span className="text-[10px] text-[#858585] font-mono leading-tight truncate">
                        대기: {myPendingTasks[0].title ?? '작업 대기'}
                      </span>
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-3 h-3 text-[#555] mt-0.5 shrink-0" />
                      <span className="text-[10px] text-[#555] font-mono">할당된 태스크 없음</span>
                    </>
                  )}
                </div>

                {/* ── 하이브 저장 상태 — memory_write / orchestrate 최근 이벤트 ── */}
                {(() => {
                  const acts = hiveActivity ?? [];
                  // memory_write: 가장 최근 메모리 저장 이벤트
                  const lastWrite = acts.find(a => a.type === 'memory_write');
                  // orchestrate: 가장 최근 오케스트레이션 이벤트
                  const lastOrch = acts.find(a => a.type === 'orchestrate');
                  // 5분 이내 이벤트는 "방금" 표시
                  const fmtTime = (ts: string) => {
                    const diffMs = Date.now() - new Date(ts).getTime();
                    if (diffMs < 60000) return '방금';
                    if (diffMs < 300000) return `${Math.floor(diffMs/60000)}분 전`;
                    return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
                  };
                  return (
                    <div className="flex flex-col gap-0.5 border-t border-white/5 pt-1.5 shrink-0">
                      <div className="text-[8px] text-white/20 font-bold uppercase tracking-widest mb-0.5">하이브 상태</div>
                      {/* 하이브 메모리 저장 상태 */}
                      <div className="flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${lastWrite ? 'bg-green-400' : 'bg-[#444]'}`} />
                        <span className="text-[9px] text-[#888] font-mono">메모리 저장</span>
                        {lastWrite ? (
                          <span className="text-[9px] text-green-400 font-mono ml-auto">{fmtTime(lastWrite.timestamp)}</span>
                        ) : (
                          <span className="text-[9px] text-[#444] font-mono ml-auto">없음</span>
                        )}
                      </div>
                      {/* 오케스트레이션 실행 상태 */}
                      <div className="flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${chainSteps.length > 0 ? 'bg-yellow-400 animate-pulse' : lastOrch ? 'bg-blue-400' : 'bg-[#444]'}`} />
                        <span className="text-[9px] text-[#888] font-mono">오케스트레이션</span>
                        {chainSteps.length > 0 ? (
                          <span className="text-[9px] text-yellow-300 font-mono ml-auto animate-pulse">실행 중</span>
                        ) : lastOrch ? (
                          <span className="text-[9px] text-blue-400 font-mono ml-auto">{fmtTime(lastOrch.timestamp)}</span>
                        ) : (
                          <span className="text-[9px] text-[#444] font-mono ml-auto">없음</span>
                        )}
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          )}

          {/* xterm.js v6 내장 스크롤바 사용 — 외부 overflow-hidden 제거하여 스크롤 활성화 */}
          <div className="flex-1 relative min-w-0 min-h-0">
            <div className="absolute inset-0 p-2">
              <div ref={xtermRef} className="h-full w-full" />
            </div>
            {!hasAttachedTerminal && (
              <div className="absolute inset-0 flex items-center justify-center p-6">
                <div className="max-w-md rounded-2xl border border-white/10 bg-[#252526] px-5 py-4 text-left shadow-2xl">
                  <div className="text-[12px] font-bold text-white">터미널 출력 연결이 아직 없습니다.</div>
                  <div className="mt-2 text-[11px] leading-relaxed text-[#b8b8b8]">
                    실행 상태는 감지됐지만 이 슬롯에 실제 터미널 화면이 붙지 않아 빈 화면처럼 보일 수 있습니다.
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      onClick={() => launchAgent(activeAgent || 'claude', false)}
                      className="rounded bg-primary px-3 py-1.5 text-[11px] font-bold text-white transition-colors hover:bg-primary/80"
                    >
                      이 슬롯에서 새 터미널 열기
                    </button>
                    <button
                      onClick={() => setIsTerminalMode(false)}
                      className="rounded border border-white/10 px-3 py-1.5 text-[11px] font-bold text-[#cccccc] transition-colors hover:bg-white/5"
                    >
                      선택 화면으로 돌아가기
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 터미널 한글 입력 및 단축어 바 */}
          <div className="p-2 border-t border-black/40 bg-[#252526] shrink-0 flex flex-col gap-2 z-10">
            <div className="flex gap-1.5 overflow-x-auto custom-scrollbar pb-0.5 opacity-80 hover:opacity-100 transition-opacity items-center">
              <button onClick={() => setShowShortcutEditor(true)} className="px-2 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[10px] whitespace-nowrap border border-primary/30 font-bold transition-colors">✏️ 편집</button>
              {shortcuts.map((sc, i) => (
                <button key={i} onClick={() => handleSend(sc.cmd)} className="px-2 py-0.5 bg-[#3c3c3c] hover:bg-white/10 rounded text-[10px] whitespace-nowrap border border-white/5 transition-colors" title={sc.cmd}>
                  {sc.label}
                </button>
              ))}
            </div>
            <div className="flex gap-2 items-end relative">
              <textarea
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={() => {
                  isComposingRef.current = false;
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) {
                      return;
                    }
                    // 엔터 키 입력 시 즉시 기본 줄바꿈 동작을 차단합니다.
                    e.preventDefault();
                    // 명령어를 즉시 전송합니다. (한글 입력 시에도 엔터 한 번으로 전송되도록 복원)
                    if (inputValue.trim()) {
                      handleSend(inputValue);
                      // 전송 후 입력창을 확실히 비웁니다.
                    }
                  }
                }}
                placeholder="터미널 명령어 전송 (한글 완벽 지원, 엔터:전송, 쉬프트+엔터:줄바꿈)..."
                rows={2}
                className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-xs focus:outline-none focus:border-primary text-white resize-none custom-scrollbar leading-relaxed"
              />
              <SlashCommandMenu
                activeAgent={activeAgent}
                showSlashMenu={showSlashMenu}
                setShowSlashMenu={setShowSlashMenu}
                onSelect={(cmd) => setInputValue(cmd + ' ')}
              />
              <button
                onClick={() => handleSend(inputValue)}
                className="px-4 py-2 bg-primary/80 hover:bg-primary text-white rounded text-xs font-bold transition-colors shadow-sm"
              >
                전송
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 터미널 우클릭 컨텍스트 메뉴 */}
      {ctxMenu && (
        <div
          className="fixed z-[9999] bg-[#2d2d2d] border border-white/20 rounded shadow-xl text-xs text-white min-w-[120px] py-1"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onMouseLeave={() => setCtxMenu(null)}
        >
          {ctxMenu.hasSelection && (
            <button
              className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
              onClick={async () => {
                try {
                  const activeTerm = termRef.current;
                  if (activeTerm) {
                    const sel = activeTerm.getSelection();
                    try {
                      await navigator.clipboard.writeText(sel);
                    } catch {
                      const ta = document.createElement('textarea');
                      ta.value = sel;
                      ta.style.position = 'fixed';
                      ta.style.left = '-9999px';
                      document.body.appendChild(ta);
                      ta.select();
                      document.execCommand('copy');
                      document.body.removeChild(ta);
                    }
                    activeTerm.clearSelection();
                  }
                } catch (err) { console.error(err); }
                setCtxMenu(null);
              }}
            >
              복사
            </button>
          )}
          <button
            className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
            onClick={async () => {
              try {
                const text = await navigator.clipboard.readText();
                const activeWs = wsRef.current;
                if (activeWs && activeWs.readyState === WebSocket.OPEN) {
                  activeWs.send(text);
                }
              } catch (err) { console.error(err); }
              setCtxMenu(null);
            }}
          >
            붙여넣기
          </button>
        </div>
      )}

      {/* ── 에이전트 선택 카드 UI (터미널 미실행 + 채팅 모드 아닐 때만 표시) ── */}
      {!isTerminalMode && (
        <div className="flex-1 flex flex-col relative overflow-hidden bg-[#1a1a1a]">
          {/* 중앙 에이전트 선택 카드 UI */}
          <div className="absolute inset-0 flex items-center justify-center p-6 z-10 bg-black/20 backdrop-blur-[2px]">
            <div className="flex flex-col md:flex-row gap-6 max-w-4xl w-full">

              {/* Claude Card */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                whileHover={{ scale: 1.02, translateY: -5 }}
                className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-success/50 group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                  <Cpu className="w-12 h-12 text-success" />
                </div>
                <div className="w-16 h-16 rounded-2xl bg-success/10 flex items-center justify-center mb-2 group-hover:bg-success/20 transition-colors shadow-inner">
                  <Cpu className="w-8 h-8 text-success" />
                </div>
                <div className="text-center">
                  <h3 className="text-xl font-black text-white tracking-tighter mb-1">CLAUDE CODE</h3>
                  <p className="text-[10px] text-success font-bold uppercase tracking-widest opacity-60">High Precision Agent</p>
                </div>
                <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
                  Anthropic의 최신 모델을 기반으로 한 정밀 코딩 도구.<br/>복잡한 리팩토링과 설계에 최적화되어 있습니다.
                </p>
                <div className="flex flex-col w-full gap-2 mt-4">
                  <button
                    onClick={() => launchAgent('claude', false)}
                    className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
                  >
                    Claude 일반 모드
                  </button>
                  <button
                    onClick={() => launchAgent('claude', true)}
                    className="w-full py-2.5 bg-primary/20 hover:bg-primary/40 text-primary rounded-xl text-[11px] font-black transition-all border border-primary/30 flex items-center justify-center gap-2 shadow-lg shadow-primary/10"
                  >
                    <Zap className="w-3.5 h-3.5 fill-current" /> Claude 욜로(YOLO)
                  </button>
                </div>
              </motion.div>

              {/* Antigravity Card (식별자 'gemini'는 Phase 1 alias 정책으로 유지) */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                whileHover={{ scale: 1.02, translateY: -5 }}
                className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-indigo-400/50 group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                  <Orbit className="w-12 h-12 text-indigo-400" />
                </div>
                <div className="w-16 h-16 rounded-2xl bg-indigo-400/10 flex items-center justify-center mb-2 group-hover:bg-indigo-400/20 transition-colors shadow-inner">
                  <Orbit className="w-8 h-8 text-indigo-400" />
                </div>
                <div className="text-center">
                  <h3 className="text-xl font-black text-white tracking-tighter mb-1">ANTIGRAVITY</h3>
                  <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-widest opacity-60">Agentic Code Pilot</p>
                </div>
                <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
                  Google의 차세대 에이전트 CLI.<br/>비대화형 실행과 멀티스텝 자동화에 최적화됐습니다.
                </p>
                <div className="flex flex-col w-full gap-2 mt-4">
                  <button
                    onClick={() => launchAgent('antigravity', false)}
                    className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
                  >
                    Antigravity 일반 모드
                  </button>
                  <button
                    onClick={() => launchAgent('antigravity', true)}
                    className="w-full py-2.5 bg-indigo-400/20 hover:bg-indigo-400/40 text-indigo-300 rounded-xl text-[11px] font-black transition-all border border-indigo-400/30 flex items-center justify-center gap-2 shadow-lg shadow-indigo-400/10"
                  >
                    <Zap className="w-3.5 h-3.5 fill-current" /> Antigravity 욜로(YOLO)
                  </button>
                </div>
              </motion.div>

              {/* Codex Card */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                whileHover={{ scale: 1.02, translateY: -5 }}
                className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-orange-400/50 group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                  <Code2 className="w-12 h-12 text-orange-400" />
                </div>
                <div className="w-16 h-16 rounded-2xl bg-orange-400/10 flex items-center justify-center mb-2 group-hover:bg-orange-400/20 transition-colors shadow-inner">
                  <Code2 className="w-8 h-8 text-orange-400" />
                </div>
                <div className="text-center">
                  <h3 className="text-xl font-black text-white tracking-tighter mb-1">CODEX CLI</h3>
                  <p className="text-[10px] text-orange-400 font-bold uppercase tracking-widest opacity-60">OpenAI Agentic Coder</p>
                </div>
                <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
                  OpenAI의 자율 코딩 에이전트.<br/>코드 생성·수정·실행을 자동으로 처리합니다.
                </p>
                <div className="flex flex-col w-full gap-2 mt-4">
                  <button
                    onClick={() => launchAgent('codex', false)}
                    className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
                  >
                    Codex 일반 모드
                  </button>
                  <button
                    onClick={() => launchAgent('codex', true)}
                    className="w-full py-2.5 bg-orange-400/20 hover:bg-orange-400/40 text-orange-400 rounded-xl text-[11px] font-black transition-all border border-orange-400/30 flex items-center justify-center gap-2 shadow-lg shadow-orange-400/10"
                  >
                    <Zap className="w-3.5 h-3.5 fill-current" /> Codex 욜로(YOLO)
                  </button>
                  {/* Codex CLI 미설치 시 npm 전역 설치 버튼 */}
                  <button
                    onClick={() => fetch(`${API_BASE}/api/install-codex-cli`, { method: 'POST' })}
                    className="w-full py-1.5 bg-transparent hover:bg-white/5 rounded-xl text-[10px] font-bold transition-all border border-white/5 text-[#555] hover:text-[#888] flex items-center justify-center gap-1.5"
                  >
                    <Code2 className="w-3 h-3" /> Codex CLI 설치 (npm)
                  </button>
                </div>
              </motion.div>



            </div>
          </div>

          {/* 배경 로그 (블러 처리하여 생동감 부여) */}
          <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-1 custom-scrollbar opacity-20">
            {slotLogs.slice(-30).map((log, idx) => (
              <div key={idx} className="flex items-start gap-2 border-l border-primary/20 pl-2 py-0.5">
                <span className="text-primary/60 font-bold whitespace-nowrap">[{log.agent}]</span>
                <span className="flex-1 text-[#aaaaaa] break-all leading-relaxed whitespace-pre-wrap">{log.trigger}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 단축어 편집 모달 팝업 — 별도 컴포넌트로 분리 */}
      {showShortcutEditor && (
        <ShortcutEditModal
          shortcuts={shortcuts}
          saveShortcuts={saveShortcuts}
          onClose={() => setShowShortcutEditor(false)}
        />
      )}
    </div>
  );
}
