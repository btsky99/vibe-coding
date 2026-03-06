/**
 * ------------------------------------------------------------------------
 * 📄 파일명: TerminalSlot.tsx
 * 📝 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트.
 *          에이전트 선택 카드(Claude/Gemini), XTerm.js 터미널 실행, 자율 에이전트
 *          모니터링 뷰(상태/태스크/로그), 단축어 바, 슬래시 커맨드 팝업, 단축어 편집 모달을 담당합니다.
 * REVISION HISTORY:
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
  Terminal, X, Zap, ClipboardList, MessageSquare, Cpu, Trash2, Activity, CheckCircle2, Clock
} from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { API_BASE, WS_PORT, Shortcut, defaultShortcuts, SLASH_COMMANDS } from '../constants';
import { LogRecord, AgentMessage, Task } from '../types';

// 파이프라인 실행 단계 정의 — cli_agent.py의 _STAGE_ORDER와 동기화
const PIPELINE_STAGES = [
  { id: 'analyzing',  label: '분석' },
  { id: 'modifying',  label: '수정' },
  { id: 'verifying',  label: '검증' },
  { id: 'done',       label: '완료' },
];

interface TerminalSlotProps {
  slotId: number;
  logs: LogRecord[];
  currentPath: string;
  terminalCount: number;
  locks: Record<string, string>;
  messages: AgentMessage[];
  tasks: Task[];
  geminiUsage: any;
  // 터미널별 에이전트 파이프라인 상태 — App.tsx에서 /api/agent/terminals 폴링으로 수신
  agentTerminals?: Record<string, any>;
  // 오케스트레이터 스킬 체인 데이터 — /api/orchestrator/skill-chain 폴링
  orchestratorData?: { skill_registry?: any[]; terminals?: Record<string, any> };
}

export default function TerminalSlot({
  slotId, logs, currentPath, terminalCount, locks, messages, tasks, geminiUsage, agentTerminals, orchestratorData
}: TerminalSlotProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  // FitAddon 참조 보관 (모니터링 뷰 토글 시 xterm 재조정용)
  const fitAddonRef = useRef<FitAddon | null>(null);
  // ResizeObserver 참조: 터미널 컨테이너 크기 변화 자동 감지용
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [isTerminalMode, setIsTerminalMode] = useState(false);
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

  // 자율 에이전트 모니터링 뷰 표시 여부 — localStorage에서 마지막 상태 복원 (기본값: false)
  // 기본값 false: 터미널 화면 최대 확보, 필요 시 버튼으로 토글
  const [showMonitor, setShowMonitor] = useState<boolean>(() => {
    const saved = localStorage.getItem('hive_monitor_enabled');
    return saved === null ? false : saved === 'true';
  });

  // task_logs.jsonl 직접 폴링 — SSE 스트림 보완용
  // hive_hook 로그가 SSE에 즉시 반영 안 될 때 task_logs API로 실시간 보완
  const [taskLogs, setTaskLogs] = useState<Array<{timestamp: string; agent: string; terminal_id: string; task: string}>>([]);

  // Git 브랜치명 — 헤더에 현재 브랜치 표시 (cmux 스타일)
  const [gitBranch, setGitBranch] = useState<string>('');

  // 에이전트 완료 알림 — 이전 상태 추적용 ref (WORKING→IDLE 전환 시 브라우저 알림)
  const prevAgentStatus = useRef<string>('IDLE');

  // 이 터미널의 스킬 실행 결과 히스토리 — skill_results.jsonl에서 terminal_id 필터
  const [skillResults, setSkillResults] = useState<Array<{
    session_id: string; request: string; results: Array<{skill: string; status: string; summary: string}>;
    completed_at: string; terminal_id?: number;
  }>>([]);

  // 이 슬롯의 터미널 ID — cli_agent.py의 _terminals 키와 일치 (T1, T2, ...)
  const terminalId = `T${slotId + 1}`;

  // 이 슬롯의 에이전트 타입 (claude / gemini)
  const agentType = activeAgent.toLowerCase().includes('gemini') ? 'gemini' : 'claude';

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
        fontSize: 12,
        cursorBlink: true
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.loadAddon(new WebLinksAddon((_event, uri) => {
        window.open(uri, '_blank');
      }));
      term.open(xtermRef.current);
      fitAddon.fit();
      termRef.current = term;

      // 텍스트 드래그(선택) 시 자동 클립보드 복사
      term.onSelectionChange(() => {
        if (term.hasSelection()) {
          navigator.clipboard.writeText(term.getSelection());
        }
      });

      // 터미널 우클릭 시 클립보드 내용 붙여넣기
      xtermRef.current.addEventListener('contextmenu', async (e) => {
        e.preventDefault();
        try {
          const text = await navigator.clipboard.readText();
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(text);
          }
        } catch (err) {
          console.error('Failed to paste from clipboard', err);
        }
      });

      // ref에 저장하여 모니터링 뷰 토글 시에도 fit() 호출 가능하게
      fitAddonRef.current = fitAddon;
      // ResizeObserver: 터미널 컨테이너 크기 변화 감지 시 자동으로 xterm 재조정
      // 모니터링 뷰 열기/닫기로 컨테이너 높이가 바뀔 때마다 즉시 반응
      const termContainer = xtermRef.current.parentElement;
      if (termContainer) {
        const ro = new ResizeObserver(() => fitAddon.fit());
        ro.observe(termContainer);
        resizeObserverRef.current = ro;
      }
      // WebSocket에 yolo 상태 전달
      const wsParams = new URLSearchParams({
        agent,
        cwd: currentPath,
        cols: term.cols.toString(),
        rows: term.rows.toString(),
        yolo: yolo.toString()
      });
      const ws = new WebSocket(`ws://${window.location.hostname}:${WS_PORT}/pty/slot${slotId}?${wsParams.toString()}`);
      wsRef.current = ws;
      ws.onopen = () => {
        const modeText = yolo ? "\x1b[38;5;196m[YOLO MODE]\x1b[0m" : "\x1b[38;5;34m[NORMAL MODE]\x1b[0m";
        term.write(`\r\n\x1b[38;5;39m[HIVE] ${agent.toUpperCase()} ${modeText} 터미널 연결 성공\x1b[0m\r\n\x1b[38;5;244m> CWD: ${currentPath}\x1b[0m\r\n\r\n`);
      };
      ws.onmessage = async (e) => {
        const data = e.data instanceof Blob ? await e.data.text() : e.data;
        term.write(data);
      };
      term.onData(data => ws.readyState === WebSocket.OPEN && ws.send(data));
      // 창 크기 변경 시 터미널 재조정 (클린업 포함)
      const handleResize = () => fitAddon.fit();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, 50);
  };

  // 모니터링 뷰 토글 시 xterm 터미널 크기 재조정
  // ResizeObserver가 주 역할이며, 이 타이머는 폴백으로 이중 호출해 안정성 확보
  useEffect(() => {
    if (!fitAddonRef.current) return;
    const t1 = setTimeout(() => fitAddonRef.current?.fit(), 100);
    const t2 = setTimeout(() => fitAddonRef.current?.fit(), 350);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [showMonitor]);

  // task_logs.jsonl 직접 폴링 — 모니터링 뷰가 열려 있을 때만 3초마다 갱신
  // SSE 스트림은 SQLite 기반이라 hive_hook 로그가 지연될 수 있어 이 폴링으로 보완
  useEffect(() => {
    if (!showMonitor || !isTerminalMode) return;
    const fetchTaskLogs = () => {
      const agentParam = activeAgent.toLowerCase();
      fetch(`${API_BASE}/api/task-logs?agent=${agentParam}&limit=10`)
        .then(res => res.json())
        .then(data => setTaskLogs(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchTaskLogs();
    const iv = setInterval(fetchTaskLogs, 3000);
    return () => clearInterval(iv);
  }, [showMonitor, isTerminalMode, activeAgent]);

  // 이 터미널의 스킬 실행 결과 폴링 — 모니터링 뷰 활성 시 10초마다 갱신
  // terminal_id로 클라이언트 필터링하여 각 슬롯에 귀속된 결과만 표시
  useEffect(() => {
    if (!showMonitor || !isTerminalMode) return;
    const myTerminalNum = slotId + 1;
    const fetchSkillResults = () => {
      fetch(`${API_BASE}/api/skill-results`)
        .then(res => res.json())
        .then(data => {
          if (!Array.isArray(data)) return;
          // terminal_id가 이 슬롯 번호와 일치하거나,
          // terminal_id=0(TERMINAL_ID 미설정)인 경우 agent 필드로 에이전트 타입 매칭 → 해당 터미널에 표시
          // agent 필드도 없으면(구 포맷) 모든 터미널에 표시 (skill_orchestrator가 terminal_id 없이 실행될 때)
          const filtered = data.filter((s: any) => {
            if (s.terminal_id === myTerminalNum) return true;
            if (s.terminal_id === 0 || s.terminal_id == null) {
              if (s.agent) return s.agent.toLowerCase().includes(agentType);
              return true; // 구 포맷 폴백: agent 미설정 결과는 모든 터미널에 표시
            }
            return false;
          });
          setSkillResults(filtered.slice(-5)); // 최근 5건만 유지
        })
        .catch(() => {});
    };
    fetchSkillResults();
    const iv = setInterval(fetchSkillResults, 10000);
    return () => clearInterval(iv);
  }, [showMonitor, isTerminalMode, slotId, agentType]);

  const closeTerminal = () => {
    setIsTerminalMode(false);
    fitAddonRef.current = null;
    // ResizeObserver 해제 (메모리 누수 방지)
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (wsRef.current) wsRef.current.close();
    if (termRef.current) termRef.current.dispose();
  };

  const handleSend = (text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    // 전송할 텍스트 끝의 줄바꿈 문자를 제거하여 중복 입력을 방지합니다.
    const cleanText = text.replace(/[\r\n]+$/, '');
    // 윈도우 PTY(winpty) + cmd.exe 환경에서는 \r\n (CRLF)이 실제 Enter 키 입력과 동일합니다.
    wsRef.current.send(cleanText.replace(/\n/g, '\r\n') + '\r\n');
    setInputValue('');
    termRef.current?.focus();
  };

  // 터미널 실행 중이면 활성 에이전트 이름으로 로그 필터링 (정확한 귀속)
  // 유휴 상태이면 해시 기반 분배 (배경 로그 표시용)
  const slotLogs = isTerminalMode
    ? logs.filter(l => l.agent?.toLowerCase() === activeAgent.toLowerCase())
    : logs.filter(l => {
        let hash = 0;
        for (let i = 0; i < l.terminal_id.length; i++) hash = ((hash << 5) - hash) + l.terminal_id.charCodeAt(i);
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
        .catch(() => {});
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
  // termData.status === 'running': 외부 Gemini 감지(_detect_external_gemini) 포함, 서버가 실행 중으로 판단한 경우 RUNNING 표시
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
    <div className={`h-full bg-[#252526] ${ringClass} rounded-md flex flex-col overflow-hidden shadow-inner relative transition-all duration-700`}>
      {/* 터미널 헤더 — 슬롯 번호, 에이전트명, 락/작업/메시지 배지 */}
      <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2 max-w-[60%] overflow-hidden">
          <Terminal className="w-3 h-3 text-accent shrink-0" />
          <span className="text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider truncate">
            {isTerminalMode ? `터미널 ${slotId + 1} - ${activeAgent}` : `터미널 ${slotId + 1}`}
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
            {/* Gemini 컨텍스트 사용량 표시 (에이전트가 gemini일 때만) */}
            {activeAgent.toLowerCase().includes('gemini') && geminiUsage && (
              <div className="flex items-center gap-2 mr-2 px-2 py-0.5 bg-accent/10 border border-accent/20 rounded text-[9px] text-accent animate-in fade-in duration-500">
                <div className="flex flex-col items-end leading-none gap-0.5">
                  <span className="font-bold opacity-80 uppercase text-[8px]">Context</span>
                  <span className="font-black">{(geminiUsage.total_tokens / 1000).toFixed(1)}K / {(geminiUsage.context_window / 1000).toFixed(1)}K</span>
                </div>
                <div className="w-12 h-1.5 bg-black/40 rounded-full overflow-hidden border border-white/5 relative">
                  <div
                    className={`h-full transition-all duration-1000 ${geminiUsage.percentage > 80 ? 'bg-red-500' : geminiUsage.percentage > 50 ? 'bg-yellow-500' : 'bg-accent'}`}
                    style={{ width: `${Math.min(100, geminiUsage.percentage)}%` }}
                  />
                </div>
                <span className="font-bold w-6 text-right">{Math.round(geminiUsage.percentage)}%</span>
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

      {isTerminalMode ? (
        <div className="flex-1 flex flex-col min-h-0 bg-[#1e1e1e]">

          {/* ── 자율 에이전트 모니터링 뷰 (상단 영역, 구 파일뷰어 자리) ── */}
          {showMonitor && (
            <div className="max-h-[280px] border-b border-black/40 bg-[#1a1a1a] flex flex-col shrink-0 overflow-y-auto custom-scrollbar">

              {/* 모니터링 헤더: 에이전트명 + 상태 뱃지 */}
              <div className="h-6 bg-[#2d2d2d] px-2 flex items-center justify-between shrink-0 border-b border-white/5">
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

              {/* 파이프라인 실행 단계 표시 — 현재 단계가 초록 원형으로 강조 */}
              <div className="flex items-center justify-center gap-0 px-3 py-2 shrink-0">
                {PIPELINE_STAGES.map((stage, idx) => {
                  // IDLE이거나 done인데 실제 작업 중이 아니면 파이프라인 전부 grey (완료 잔류 방지)
                  const isIdle = agentStatus === 'IDLE';
                  const stageIdx = isIdle ? -1 : PIPELINE_STAGES.findIndex(s => s.id === pipelineStage);
                  const isActive = !isIdle && stage.id === pipelineStage;
                  const isPast   = stageIdx > idx;
                  return (
                    <div key={stage.id} className="flex items-center">
                      {/* 단계 원형 버튼 */}
                      <div className={`flex flex-col items-center gap-0.5 w-14`}>
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all ${
                          isActive ? 'border-green-400 bg-green-400/20 shadow-[0_0_8px_2px_rgba(74,222,128,0.4)]' :
                          isPast   ? 'border-green-600/50 bg-green-900/20' :
                                     'border-white/10 bg-white/5'
                        }`}>
                          <CheckCircle2 className={`w-3.5 h-3.5 ${isActive ? 'text-green-400' : isPast ? 'text-green-600/60' : 'text-white/20'}`} />
                        </div>
                        <span className={`text-[9px] font-bold ${isActive ? 'text-green-400' : isPast ? 'text-green-600/60' : 'text-white/25'}`}>
                          {stage.label}
                        </span>
                      </div>
                      {/* 단계 간 구분선 (마지막 이후 제외) */}
                      {idx < PIPELINE_STAGES.length - 1 && (
                        <div className={`w-4 h-px mb-4 ${isPast || isActive ? 'bg-green-600/50' : 'bg-white/10'}`} />
                      )}
                    </div>
                  );
                })}
              </div>

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

              {/* 모니터링 본문 */}
              <div className="flex-1 overflow-hidden flex flex-col px-2 pb-2 gap-1">

                {/* 현재 작업 — agentTerminals의 task 우선, 없으면 태스크 보드 조회 */}
                <div className="text-[8px] text-white/20 font-bold uppercase tracking-widest shrink-0">현재 작업</div>
                <div className="flex items-start gap-2 shrink-0">
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
                        대기 중: {myPendingTasks[0].title ?? '작업 대기'}
                      </span>
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-3 h-3 text-[#555] mt-0.5 shrink-0" />
                      <span className="text-[10px] text-[#555] font-mono">할당된 태스크 없음</span>
                    </>
                  )}
                </div>

                {/* 최근 메시지 (있을 때만) */}
                {recentAgentMsgs.length > 0 && (
                  <div className="flex items-start gap-2 shrink-0 px-1.5 py-1 bg-primary/5 border border-primary/20 rounded">
                    <MessageSquare className="w-3 h-3 text-primary mt-0.5 shrink-0" />
                    <span className="text-[10px] text-primary/80 leading-tight truncate">
                      {recentAgentMsgs[recentAgentMsgs.length - 1].content}
                    </span>
                  </div>
                )}

                {/* 최근 활동 — raw 커맨드 로그 제외, 의미 있는 작업 이벤트만 표시
                    [명령 실행]/[명령 완료]/시스템 메시지 필터링 → 수정·분석·검증 이벤트만 노출 */}
                {(() => {
                  // 제외 패턴: raw 커맨드 실행 로그 + 시스템 내부 메시지
                  const NOISE = [
                    '[명령 실행]', '[명령 완료]', '─── ', '[메시지 수신]',
                    '[하이브 컨텍스트]', '[지시]', '자동 주입', '읽음:',
                  ];
                  const filtered = taskLogs.filter(log =>
                    log.task && !NOISE.some(p => log.task.includes(p))
                  );
                  if (filtered.length === 0) return null;
                  return (
                    <div className="flex flex-col gap-0.5 border-t border-white/5 pt-1 mt-0.5">
                      <div className="text-[8px] text-white/15 font-bold uppercase tracking-widest">── 최근 활동</div>
                      {filtered.slice(-5).reverse().map((log, idx) => {
                        // 완료 항목은 초록, 시작/진행은 노란색으로 구분
                        const isDone = log.task.includes('완료') || log.task.includes('✓');
                        const color = isDone ? 'text-green-400/70' : 'text-yellow-300/60';
                        return (
                          <div key={idx} className="flex items-baseline gap-2 min-w-0">
                            <span className="text-[9px] text-[#555] font-mono shrink-0 w-14">
                              {log.timestamp
                                ? new Date(log.timestamp).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
                                : '--:--'}
                            </span>
                            <span className={`text-[9px] font-mono truncate leading-tight ${color}`}>
                              {log.task}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* ── 스킬 실행 결과 (이 터미널 귀속 히스토리) ── */}
                {skillResults.length > 0 && (
                  <div className="mt-1 flex flex-col gap-1">
                    <div className="text-[8px] text-white/15 font-bold uppercase tracking-widest shrink-0">── 스킬 실행 기록</div>
                    {skillResults.slice().reverse().map((session, idx) => {
                      const doneCount = session.results.filter(r => r.status === 'done').length;
                      return (
                        <div key={idx} className="rounded border border-white/8 bg-white/2 px-1.5 py-1 flex flex-col gap-0.5">
                          {/* 요청 원문 */}
                          <span className="text-[9px] text-white/60 leading-tight truncate">{session.request}</span>
                          {/* 스킬 배지 목록 */}
                          <div className="flex flex-wrap gap-1">
                            {session.results.map((r, i) => {
                              const shortName = r.skill.replace('vibe-', '');
                              const s = r.status;
                              const colorCls = s === 'done'    ? 'border-green-500/50 text-green-400 bg-green-500/10'
                                             : s === 'error'   ? 'border-red-500/50 text-red-400 bg-red-500/10'
                                             : s === 'skipped' ? 'border-white/10 text-white/30 bg-white/5'
                                             :                   'border-yellow-400/60 text-yellow-300 bg-yellow-400/10';
                              const icon = s === 'done' ? '✓' : s === 'error' ? '✗' : s === 'skipped' ? '—' : '●';
                              return (
                                <span key={i} className={`text-[8px] font-bold px-1 py-0.5 rounded border ${colorCls}`} title={r.summary}>
                                  {icon} {shortName}
                                </span>
                              );
                            })}
                          </div>
                          {/* 완료율 + 시각 */}
                          <div className="flex items-center justify-between">
                            <span className={`text-[8px] font-bold ${doneCount === session.results.length ? 'text-green-400' : 'text-[#858585]'}`}>
                              {doneCount}/{session.results.length} 완료
                            </span>
                            <span className="text-[8px] text-[#444] font-mono">
                              {session.completed_at ? new Date(session.completed_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : ''}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* overflow-hidden: fit() 재조정 전 xterm이 컨테이너를 넘치는 시각적 오버플로우 차단 */}
          <div className="flex-1 relative min-h-0 overflow-hidden"><div ref={xtermRef} className="absolute inset-0 p-2" /></div>

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
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    // 엔터 키 입력 시 즉시 기본 줄바꿈 동작을 차단합니다.
                    e.preventDefault();
                    // 명령어를 즉시 전송합니다. (한글 입력 시에도 엔터 한 번으로 전송되도록 복원)
                    if (inputValue.trim()) {
                      handleSend(inputValue);
                      // 전송 후 입력창을 확실히 비웁니다.
                      setTimeout(() => setInputValue(''), 0);
                    }
                  }
                }}
                placeholder="터미널 명령어 전송 (한글 완벽 지원, 엔터:전송, 쉬프트+엔터:줄바꿈)..."
                rows={Math.max(1, Math.min(8, inputValue.split('\n').length))}
                className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-xs focus:outline-none focus:border-primary text-white transition-all resize-none custom-scrollbar leading-relaxed h-auto"
              />
              {/* 슬래시 커맨드 퀵 팝업 버튼 */}
              <div className="relative">
                <button
                  onClick={() => setShowSlashMenu(v => !v)}
                  className={`px-2.5 py-2 rounded text-xs font-bold border transition-all ${showSlashMenu ? 'bg-primary text-white border-primary' : 'bg-[#3c3c3c] text-[#cccccc] border-white/10 hover:bg-white/10'}`}
                  title="슬래시 커맨드 목록"
                >
                  /
                </button>
                {/* 슬래시 커맨드 팝업 */}
                {showSlashMenu && (
                  <div className="absolute bottom-full right-0 mb-1 w-72 bg-[#252526] border border-white/15 rounded-md shadow-2xl z-50 overflow-hidden">
                    <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center px-3 gap-1.5">
                      <span className="text-primary font-bold text-[11px]">/</span>
                      <span className="text-[11px] font-bold text-[#cccccc] uppercase tracking-wider">
                        {activeAgent.toUpperCase()} 슬래시 커맨드
                      </span>
                    </div>
                    <div className="max-h-64 overflow-y-auto custom-scrollbar py-1">
                      {/* 카테고리별 그룹핑 */}
                      {['설정', '작업', '도움말'].map(cat => {
                        const cmds = (SLASH_COMMANDS[activeAgent] ?? SLASH_COMMANDS['claude'])
                          .filter(c => c.category === cat);
                        if (!cmds.length) return null;
                        return (
                          <div key={cat}>
                            <div className="px-3 py-0.5 text-[9px] font-bold uppercase tracking-widest text-white/25">{cat}</div>
                            {cmds.map(sc => (
                              <button
                                key={sc.cmd}
                                onClick={() => { setInputValue(sc.cmd + ' '); setShowSlashMenu(false); }}
                                className="w-full flex items-center gap-3 px-3 py-1.5 hover:bg-primary/20 text-left group transition-colors"
                              >
                                <span className="text-primary font-mono text-[11px] font-bold w-24 shrink-0 group-hover:text-white transition-colors">{sc.cmd}</span>
                                <span className="text-[#969696] text-[10px] group-hover:text-[#cccccc] transition-colors leading-tight">{sc.desc}</span>
                              </button>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
              <button
                onClick={() => handleSend(inputValue)}
                className="px-4 py-2 bg-primary/80 hover:bg-primary text-white rounded text-xs font-bold transition-colors shadow-sm"
              >
                전송
              </button>
            </div>
          </div>
        </div>
      ) : (
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

              {/* Gemini Card */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                whileHover={{ scale: 1.02, translateY: -5 }}
                className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-accent/50 group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                  <Terminal className="w-12 h-12 text-accent" />
                </div>
                <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-2 group-hover:bg-accent/20 transition-colors shadow-inner">
                  <Terminal className="w-8 h-8 text-accent" />
                </div>
                <div className="text-center">
                  <h3 className="text-xl font-black text-white tracking-tighter mb-1">GEMINI CLI</h3>
                  <p className="text-[10px] text-accent font-bold uppercase tracking-widest opacity-60">High Speed Reasoning</p>
                </div>
                <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
                  Google의 초거대 언어 모델 기반 고속 추론 도구.<br/>빠른 프로토타이핑과 넓은 컨텍스트를 제공합니다.
                </p>
                <div className="flex flex-col w-full gap-2 mt-4">
                  <button
                    onClick={() => launchAgent('gemini', false)}
                    className="w-full py-2.5 bg-[#3c3c3c] hover:bg-white/10 rounded-xl text-[11px] font-bold transition-all border border-white/5 flex items-center justify-center gap-2 group/btn"
                  >
                    Gemini 일반 모드
                  </button>
                  <button
                    onClick={() => launchAgent('gemini', true)}
                    className="w-full py-2.5 bg-primary/20 hover:bg-primary/40 text-primary rounded-xl text-[11px] font-black transition-all border border-primary/30 flex items-center justify-center gap-2 shadow-lg shadow-primary/10"
                  >
                    <Zap className="w-3.5 h-3.5 fill-current" /> Gemini 욜로(YOLO)
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

      {/* 단축어 편집 모달 팝업 */}
      {showShortcutEditor && (
        <div className="absolute inset-0 bg-black/80 z-50 flex items-center justify-center p-2">
          <div className="bg-[#252526] border border-black/40 shadow-2xl rounded-md flex flex-col w-full max-w-md max-h-full">
            <div className="h-8 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
              <span className="text-xs font-bold text-[#cccccc]">단축어 편집 (개인화)</span>
              <button onClick={() => setShowShortcutEditor(false)} className="p-1 hover:bg-white/10 rounded text-[#cccccc]"><X className="w-4 h-4" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
              {shortcuts.map((sc, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input value={sc.label} onChange={e => { const n = [...shortcuts]; n[i].label = e.target.value; saveShortcuts(n); }} placeholder="버튼 이름" className="w-1/3 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-xs text-white focus:border-primary focus:outline-none transition-colors" />
                  <input value={sc.cmd} onChange={e => { const n = [...shortcuts]; n[i].cmd = e.target.value; saveShortcuts(n); }} placeholder="실행할 명령어" className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-xs text-white font-mono focus:border-primary focus:outline-none transition-colors" />
                  <button onClick={() => { const n = shortcuts.filter((_, idx) => idx !== i); saveShortcuts(n); }} className="p-1.5 text-red-400 hover:bg-red-400/20 rounded transition-colors"><Trash2 className="w-4 h-4" /></button>
                </div>
              ))}
              <button onClick={() => saveShortcuts([...shortcuts, {label: '새 단축어', cmd: ''}])} className="w-full py-2 mt-2 border border-dashed border-white/20 hover:border-white/40 hover:bg-white/5 rounded text-xs text-[#cccccc] transition-colors">
                + 새 단축어 추가
              </button>
            </div>
            <div className="p-3 border-t border-black/40 flex justify-end gap-2 shrink-0">
              <button onClick={() => { if(confirm('모든 단축어를 기본값으로 초기화하시겠습니까?')) saveShortcuts(defaultShortcuts); }} className="px-3 py-1.5 hover:bg-white/5 text-xs text-[#cccccc] rounded transition-colors">기본값 복원</button>
              <button onClick={() => setShowShortcutEditor(false)} className="px-4 py-1.5 bg-primary hover:bg-primary/80 text-white rounded text-xs font-bold transition-colors">닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
