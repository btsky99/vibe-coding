/**
 * ------------------------------------------------------------------------
 * 📄 파일명: TerminalSlot.tsx
 * 📝 설명: 하이브 대시보드의 단일 터미널 슬롯 컴포넌트.
 *          에이전트 선택 카드(Claude/Gemini), XTerm.js 터미널 실행, 활성 파일 뷰어,
 *          단축어 바, 슬래시 커맨드 팝업, 단축어 편집 모달을 모두 담당합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리. constants.ts의 공유 상수 사용.
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Terminal, X, Zap, ClipboardList, MessageSquare, Cpu, Trash2
} from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import VibeEditor from './VibeEditor';
import { API_BASE, WS_PORT, getFileIcon, Shortcut, defaultShortcuts, SLASH_COMMANDS } from '../constants';
import { LogRecord, AgentMessage, Task } from '../types';

interface TerminalSlotProps {
  slotId: number;
  logs: LogRecord[];
  currentPath: string;
  terminalCount: number;
  locks: Record<string, string>;
  messages: AgentMessage[];
  tasks: Task[];
  geminiUsage: any;
}

export default function TerminalSlot({
  slotId, logs, currentPath, terminalCount, locks, messages, tasks, geminiUsage
}: TerminalSlotProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  // FitAddon 참조 보관 (파일 뷰어 토글 시 재조정용)
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

  // Active File Viewer State — 에이전트가 수정 중인 파일을 실시간으로 표시
  const [showActiveFile, setShowActiveFile] = useState(false);
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
  const [activeFileContent, setActiveFileContent] = useState<string>('');
  const [isActiveFileLoading, setIsActiveFileLoading] = useState(false);

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

      // ref에 저장하여 파일 뷰어 토글 시에도 fit() 호출 가능하게
      fitAddonRef.current = fitAddon;
      // ResizeObserver: 터미널 컨테이너 크기 변화 감지 시 자동으로 xterm 재조정
      // 파일 뷰어 열기/닫기로 컨테이너 높이가 바뀔 때마다 즉시 반응
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

        // 정규식으로 터미널 출력에서 파일 경로 추출 (ANSI/OSC 코드 완전 제거 후)
        // CSI 시퀀스(\x1b[...), OSC 시퀀스(\x1b]...\x07 또는 \x1b\\), DCS/기타 시퀀스 모두 처리
        const ansiRegex = /\x1b\][\s\S]*?(?:\x1b\\|\x07)|\x1b[PX^_][\s\S]*?\x1b\\|[\x1b\x9b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><~]/g;
        const cleanData = data.replace(ansiRegex, '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
        const pathRegex = /(?:[a-zA-Z]:[\\\/](?:[\w.\-]+[\\\/])*[\w.\-]+|(?:[\w.\-]+[\\\/])+[\w.\-]+)\.(?:jsx?|tsx?|py|css|html?|md|json|ya?ml|toml|cfg|ini|sh|bat|ps1|vue|svelte)/g;
        const matches = cleanData.match(pathRegex);
        if (matches && matches.length > 0) {
          const matchedPath = matches[matches.length - 1];
          setActiveFilePath(matchedPath);
        }
      };
      term.onData(data => ws.readyState === WebSocket.OPEN && ws.send(data));
      // 창 크기 변경 시 터미널 재조정 (클린업 포함)
      const handleResize = () => fitAddon.fit();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, 50);
  };

  // 주기적으로 활성 파일 내용 갱신 (뷰어가 열려있을 때만, 이미지 파일 제외)
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const isImage = activeFilePath ? /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(activeFilePath) : false;
    if (showActiveFile && activeFilePath && !isImage) {
      const fetchFile = () => {
        setIsActiveFileLoading(true);
        // 상대 경로일 경우 CWD 기준으로 요청
        const targetPath = activeFilePath.includes(':') || activeFilePath.startsWith('/')
          ? activeFilePath
          : `${currentPath}/${activeFilePath}`;

        fetch(`http://${window.location.hostname}:${window.location.port}/api/read-file?path=${encodeURIComponent(targetPath)}`)
          .then(res => res.json())
          .then(data => {
            if (!data.error) setActiveFileContent(data.content);
          })
          .catch(() => {})
          .finally(() => setIsActiveFileLoading(false));
      };
      fetchFile();
      interval = setInterval(fetchFile, 3000); // 3초마다 갱신
    }
    return () => clearInterval(interval);
  }, [showActiveFile, activeFilePath, currentPath]);

  // 파일 뷰어 토글 시 xterm 터미널 크기 재조정
  // ResizeObserver가 주 역할이며, 이 타이머는 폴백으로 이중 호출해 안정성 확보
  useEffect(() => {
    if (!fitAddonRef.current) return;
    const t1 = setTimeout(() => fitAddonRef.current?.fit(), 100);
    const t2 = setTimeout(() => fitAddonRef.current?.fit(), 350);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [showActiveFile]);

  const closeTerminal = () => {
    setIsTerminalMode(false);
    setShowActiveFile(false);
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

  // 로그를 슬롯 ID에 따라 분배 (해시 기반, 터미널 수로 모듈로 연산)
  const slotLogs = logs.filter(l => {
    let hash = 0;
    for (let i = 0; i < l.terminal_id.length; i++) hash = ((hash << 5) - hash) + l.terminal_id.charCodeAt(i);
    return Math.abs(hash) % terminalCount === slotId;
  });

  // 새 로그 도착 시 자동 스크롤
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [slotLogs.length]);

  return (
    // h-full: 그리드 셀 높이를 명시적으로 채워야 flex 자식들이 올바른 높이를 전달받음
    <div className="h-full bg-[#252526] border border-black/40 rounded-md flex flex-col overflow-hidden shadow-inner relative">
      {/* 터미널 헤더 — 슬롯 번호, 에이전트명, 락/작업/메시지 배지 */}
      <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2 max-w-[60%] overflow-hidden">
          <Terminal className="w-3 h-3 text-accent shrink-0" />
          <span className="text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider truncate">
            {isTerminalMode ? `터미널 ${slotId + 1} - ${activeAgent}` : `터미널 ${slotId + 1}`}
          </span>
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

            <button
              onClick={() => setShowActiveFile(!showActiveFile)}
              className={`px-2 py-0.5 rounded text-[9px] border transition-all font-bold ${showActiveFile ? 'bg-primary/40 border-primary text-white' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
              title="현재 에이전트가 수정중인 파일 보기"
            >
              👀 파일 뷰어
            </button>
            <button onClick={closeTerminal} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>

      {isTerminalMode ? (
        <div className="flex-1 flex flex-col min-h-0 bg-[#1e1e1e]">
          {/* 활성 파일 뷰어 (상단 1/3 영역) */}
          {showActiveFile && (
            <div
              className="h-1/3 min-h-[100px] border-b border-black/40 bg-[#1a1a1a] flex flex-col shrink-0 relative"
              style={{ resize: 'vertical', overflow: 'hidden' }}
            >
              <div className="h-6 bg-[#2d2d2d] px-2 flex items-center justify-between text-[10px] text-[#cccccc] shrink-0 border-b border-white/5 cursor-row-resize pointer-events-none">
                <span className="truncate flex items-center gap-1 opacity-80 pointer-events-auto">
                  {getFileIcon(activeFilePath || '')}
                  {activeFilePath ? activeFilePath : "감지된 파일 없음..."}
                </span>
                {isActiveFileLoading && <span className="text-[#3794ef] animate-pulse pointer-events-auto">●</span>}
              </div>
              <div className="flex-1 overflow-auto p-2 custom-scrollbar flex items-center justify-center">
                {/* 이미지 파일이면 img 태그로, 아니면 코드 뷰어로 */}
                {activeFilePath && /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(activeFilePath)
                  ? <img
                      src={`${API_BASE}/api/image-file?path=${encodeURIComponent(activeFilePath.includes(':') || activeFilePath.startsWith('/') ? activeFilePath : `${currentPath}/${activeFilePath}`)}`}
                      alt={activeFilePath}
                      className="max-w-full max-h-full object-contain"
                      style={{ imageRendering: 'auto' }}
                    />
                  : activeFileContent
                    ? <VibeEditor path={activeFilePath || ''} content={activeFileContent} isReadOnly={true} />
                    : <span className="font-mono text-[11px] text-[#cccccc] italic opacity-40">에이전트가 파일을 수정하거나 경로를 출력할 때까지 대기 중...</span>
                }
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
          <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-1.5 custom-scrollbar blur-[4px] opacity-10 pointer-events-none scale-95 origin-center">
            {slotLogs.map((log, idx) => (
              <div key={idx} className="flex items-start gap-2 border-l-2 border-primary/30 pl-2 py-0.5 bg-white/2 rounded-r">
                <span className="text-primary font-bold whitespace-nowrap opacity-80">[{log.agent}]</span>
                <span className="flex-1 text-[#cccccc] break-all leading-relaxed whitespace-pre-wrap">{log.trigger}</span>
              </div>
            ))}
            {slotLogs.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-white/10 italic">
                <Cpu className="w-8 h-8 mb-2 opacity-10" />
                System ready...
              </div>
            )}
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
