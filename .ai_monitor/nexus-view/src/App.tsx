import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Menu, Terminal, CheckCircle2, RotateCw, XCircle, FolderTree, Folder, ChevronLeft, X } from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { LogRecord } from './types';

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [terminalCount, setTerminalCount] = useState(2);
  const [logs, setLogs] = useState<LogRecord[]>([]);

  // 파일 시스템 탐색 상태
  const [drives, setDrives] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState("D:/vibe-coding");
  const [directories, setDirectories] = useState<{ name: string, path: string }[]>([]);

  // 드라이브 목록 가져오기
  useEffect(() => {
    fetch('http://localhost:8000/api/drives')
      .then(res => res.json())
      .then(data => setDrives(data))
      .catch(() => { });
  }, []);

  // 현재 경로의 하위 폴더 가져오기
  useEffect(() => {
    if (!currentPath) return;
    fetch(`http://localhost:8000/api/dirs?path=${encodeURIComponent(currentPath)}`)
      .then(res => res.json())
      .then(data => setDirectories(data))
      .catch(() => { });
  }, [currentPath]);

  // 상위 폴더로 이동 로직
  const goUp = () => {
    const parts = currentPath.replace(/\\/g, '/').split('/').filter(Boolean);
    if (parts.length > 1) {
      // 일반 폴더 상위 이동
      parts.pop();
      let parentPath = parts.join('/');
      if (parts.length === 1 && parts[0].includes(':')) {
        parentPath += '/'; // 루트 드라이브 (예: D:/)
      }
      setCurrentPath(parentPath);
    }
  };

  // SSE 연동 (추후 파이썬 서버가 띄워질 `http://localhost:8000/stream` 주소)
  useEffect(() => {
    const sse = new EventSource('http://localhost:8000/stream');
    sse.onmessage = (e) => {
      try {
        const data: LogRecord = JSON.parse(e.data);
        setLogs(prev => [...prev.slice(-199), data]); // 최대 200개 유지
      } catch (err) { }
    };
    return () => sse.close();
  }, []);

  const toggleSidebar = () => setIsSidebarOpen(!isSidebarOpen);

  // 터미널 슬롯 (선택된 개수만큼)
  const slots = Array.from({ length: terminalCount }, (_, i) => i);

  return (
    <div className="flex h-screen w-full bg-background text-textMain overflow-hidden select-none">

      {/* Sidebar */}
      <motion.div
        initial={{ width: 0, opacity: 0 }}
        animate={{
          width: isSidebarOpen ? 260 : 0,
          opacity: isSidebarOpen ? 1 : 0
        }}
        transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
        className="h-full border-r border-white/20 bg-surface/50 backdrop-blur-md flex flex-col shrink-0 overflow-hidden"
      >
        <div className="h-14 border-b border-white/20 flex items-center px-4 shrink-0">
          <Activity className="w-5 h-5 text-accent mr-2" />
          <span className="font-semibold text-lg tracking-wide text-transparent bg-clip-text bg-gradient-to-r from-primary to-accent">바이브 코딩</span>
        </div>

        <div className="p-4 flex-1 flex flex-col overflow-hidden">
          <div className="text-xs font-semibold text-textMuted uppercase tracking-wider mb-3">Drives / Workspace</div>
          <select
            value={drives.find(d => currentPath.startsWith(d)) || currentPath}
            onChange={(e) => setCurrentPath(e.target.value)}
            className="w-full bg-[#1a1a26] border border-white/10 rounded-md py-1.5 px-3 text-sm focus:outline-none focus:border-primary transition-colors cursor-pointer mb-4 shrink-0"
          >
            <option value="D:/vibe-coding">vibe-coding (D:/vibe-coding)</option>
            {drives.map(drive => (
              <option key={drive} value={drive}>{drive}</option>
            ))}
          </select>

          <div className="text-xs font-semibold text-textMuted uppercase tracking-wider mb-3 flex items-center shrink-0">
            <FolderTree className="w-3.5 h-3.5 mr-1" /> Explorer ({currentPath})
          </div>
          <div className="flex-1 overflow-y-auto pr-1">
            <div className="space-y-1">
              <button
                onClick={goUp}
                className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-white/5 rounded text-sm text-textMuted hover:text-white transition-colors text-left"
              >
                <ChevronLeft className="w-4 h-4 text-primary" /> ..
              </button>
              {directories.map(dir => (
                <button
                  key={dir.path}
                  onClick={() => setCurrentPath(dir.path)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-white/5 rounded text-sm text-textMuted hover:text-white transition-colors text-left"
                >
                  <Folder className="w-4 h-4 text-accent" />
                  <span className="truncate">{dir.name}</span>
                </button>
              ))}
              {directories.length === 0 && (
                <div className="px-2 py-2 text-xs text-white/30 italic">No subdirectories</div>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <header className="h-14 border-b border-white/20 bg-surface/30 backdrop-blur-sm flex items-center justify-between px-4 shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={toggleSidebar}
              className="p-1.5 rounded-md hover:bg-white/10 transition-colors text-textMuted hover:text-white"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="h-5 w-px bg-white/10"></div>
            <div className="text-sm text-textMuted flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
              System Active
            </div>
          </div>

          <div className="flex items-center gap-1">
            {[1, 2, 3, 4].map(n => (
              <button
                key={n}
                onClick={() => setTerminalCount(n)}
                className={`w-7 h-7 rounded-md text-xs font-bold transition-colors ${
                  terminalCount === n
                    ? 'bg-primary text-white'
                    : 'bg-white/5 text-textMuted hover:bg-white/10 hover:text-white'
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </header>

        {/* Terminals Area */}
        <main className="flex-1 p-4 overflow-hidden">
          <div className={`h-full w-full gap-4 grid ${
            terminalCount === 1 ? 'grid-cols-1' :
            terminalCount === 2 ? 'grid-cols-2' :
            terminalCount === 3 ? 'grid-cols-3' :
            'grid-cols-2 grid-rows-2'
          }`}>
            {slots.map(slotId => (
              <TerminalSlot key={slotId} slotId={slotId} logs={logs} currentPath={currentPath} terminalCount={terminalCount} />
            ))}
          </div>
        </main>
      </div>
    </div>
  )
}

function TerminalSlot({ slotId, logs, currentPath, terminalCount }: { slotId: number, logs: LogRecord[], currentPath: string, terminalCount: number }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [isTerminalMode, setIsTerminalMode] = useState(false);
  const [activeAgent, setActiveAgent] = useState('');

  const launchAgent = (agent: string) => {
    setIsTerminalMode(true);
    setActiveAgent(agent);

    if (wsRef.current) wsRef.current.close();
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }

    setTimeout(() => {
      if (!xtermRef.current) return;
      const term = new XTerm({
        theme: { background: '#0a0a0f', foreground: '#e2e8f0', cursor: '#8b5cf6' },
        fontFamily: "'Fira Code', 'Consolas', monospace",
        fontSize: 12
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.open(xtermRef.current);
      fitAddon.fit();
      termRef.current = term;

      const wsParams = new URLSearchParams({
        agent,
        cwd: currentPath,
        cols: (term.cols || 80).toString(),
        rows: (term.rows || 24).toString()
      });

      const ws = new WebSocket(`ws://localhost:8001/pty/slot${slotId}?${wsParams.toString()}`);
      wsRef.current = ws;

      ws.onopen = () => {
        term.write(`\x1b[38;5;135m[바이브 코딩] Connected to ${agent} PTY\x1b[0m\r\n`);
      };

      ws.onmessage = async (e) => {
        if (e.data instanceof Blob) {
          const text = await e.data.text();
          term.write(text);
        } else {
          term.write(e.data);
        }
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        }
      });

      ws.onclose = () => {
        term.write('\x1b[31m\r\n[바이브 코딩] Connection Closed\x1b[0m\r\n');
      };

      const handleResize = () => {
        try { fitAddon.fit(); } catch { }
      };
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, 50);
  };

  const closeTerminal = () => {
    setIsTerminalMode(false);
    setActiveAgent('');
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (termRef.current) {
      termRef.current.dispose();
      termRef.current = null;
    }
  };

  // Hash 기반으로 로그를 슬롯에 분배
  const slotLogs = logs.filter(l => {
    let hash = 0;
    for (let i = 0; i < l.terminal_id.length; i++) hash = ((hash << 5) - hash) + l.terminal_id.charCodeAt(i);
    return Math.abs(hash) % terminalCount === slotId;
  });

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [slotLogs.length]);

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden flex-1 min-h-0">
      <div className="h-9 bg-black/40 border-b border-white/20 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center">
          <Terminal className="w-4 h-4 text-textMuted mr-2" />
          <span className="text-xs font-mono font-bold text-textMuted text-white/90">
            {isTerminalMode ? `${activeAgent.toUpperCase()} 터미널 ${slotId + 1}` : `터미널 ${slotId + 1}`}
          </span>
        </div>
        <div className="flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity" style={{ opacity: 1 }}>
          {!isTerminalMode ? (
            <>
              <button onClick={() => launchAgent('claude')} className="px-2 py-0.5 rounded bg-[#1a1a26] hover:bg-[#2a2a36] border border-white/10 hover:border-[#8b5cf6] text-[10px] text-white/80 transition-colors font-medium cursor-pointer">
                Claude Code
              </button>
              <button onClick={() => launchAgent('gemini')} className="px-2 py-0.5 rounded bg-[#1a1a26] hover:bg-[#2a2a36] border border-white/10 hover:border-[#3b82f6] text-[10px] text-white/80 transition-colors font-medium cursor-pointer">
                Gemini CLI
              </button>
            </>
          ) : (
            <button onClick={closeTerminal} className="px-2 py-0.5 rounded bg-red-500/20 hover:bg-red-500/40 border border-red-500/50 text-[10px] text-red-200 transition-colors font-medium flex items-center gap-1 cursor-pointer">
              <X className="w-3 h-3" /> 닫기
            </button>
          )}
        </div>
      </div>

      {isTerminalMode ? (
        <div className="flex-1 p-2 bg-[#0a0a0f] overflow-hidden relative">
          <div ref={xtermRef} className="absolute inset-0 p-2" />
        </div>
      ) : (
        <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto font-mono text-xs space-y-2">
          <AnimatePresence initial={false}>
            {slotLogs.map((log, idx) => (
              <motion.div
                key={`${log.session_id}-${idx}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-start gap-2"
              >
                <div className="shrink-0 mt-0.5">
                  {log.status === 'running' && <RotateCw className="w-3.5 h-3.5 text-primary animate-spin" />}
                  {log.status === 'success' && <CheckCircle2 className="w-3.5 h-3.5 text-success" />}
                  {log.status === 'failed' && <XCircle className="w-3.5 h-3.5 text-error" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-[#a78bfa] font-bold">[{log.agent}]</span>
                    <span className="text-textMuted">@ {log.project}</span>
                    <span className="text-xs text-white/60 ml-auto font-medium">{log.ts_start?.split('T')[1]?.substring(0, 8) || ''}</span>
                  </div>
                  <div className="text-[#cbd5e1] break-words">
                    {`> ${log.trigger}`}
                  </div>
                  {log.commit && (
                    <div className="text-[10px] text-primary/70 mt-1">
                      Commit: {log.commit}
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
            {slotLogs.length === 0 && (
              <div className="h-full flex items-center justify-center text-white/20">Waiting for logs...</div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

export default App;
