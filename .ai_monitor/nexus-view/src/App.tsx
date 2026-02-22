import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { 
  Activity, Menu, Terminal, RotateCw, 
  Folder, ChevronLeft, X, Zap, Search, Settings, 
  Files, Cpu, Info, ChevronRight, ChevronDown,
  Trash2, LayoutDashboard, FileText
} from 'lucide-react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { LogRecord } from './types';

export interface Shortcut { label: string; cmd: string; }
const defaultShortcuts: Shortcut[] = [
  { label: '마스터 호출', cmd: 'gemini --skill master' },
  { label: '🧹 화면 지우기', cmd: '/clear' },
  { label: '깃 커밋', cmd: 'git add . && git commit -m "update"' },
  { label: '깃 푸시', cmd: 'git push' },
  { label: '문서 업데이트', cmd: 'gemini "현재까지 진행 상황 문서 업데이트"' },
];

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('explorer');
  const [layoutMode, setLayoutMode] = useState<'1' | '2' | '3' | '4-col' | '2x2'>('2');
  const terminalCount = layoutMode === '1' ? 1 : layoutMode === '2' ? 2 : layoutMode === '3' ? 3 : 4;
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);

  // 좀비 서버 방지용 하트비트 (창 닫히면 서버 15초 뒤 자동 종료)
  useEffect(() => {
    const interval = setInterval(() => {
      fetch('http://localhost:8000/api/heartbeat').catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // 파일 시스템 탐색 상태
  const [drives, setDrives] = useState<string[]>([]);
  const [currentPath, setCurrentPath] = useState("D:/vibe-coding");
  const [items, setItems] = useState<{ name: string, path: string, isDir: boolean }[]>([]);

  // 드라이브 목록 가져오기
  useEffect(() => {
    fetch('http://localhost:8000/api/drives')
      .then(res => res.json())
      .then(data => setDrives(data))
      .catch(() => { });
  }, []);

  // 현재 경로의 항목(폴더/파일) 가져오기
  const refreshItems = () => {
    if (!currentPath) return;
    fetch(`http://localhost:8000/api/files?path=${encodeURIComponent(currentPath)}`)
      .then(res => res.json())
      .then(data => setItems(data))
      .catch(() => { });
  };

  useEffect(() => {
    refreshItems();
  }, [currentPath]);

  // 스킬 및 도구 설치 로직
  const installSkills = () => {
    if (!currentPath) return;
    if (confirm(`현재 프로젝트(${currentPath})에 하이브 마인드 베이스 스킬을 설치하시겠습니까?`)) {
      fetch(`http://localhost:8000/api/install-skills?path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(data => { alert(data.message); refreshItems(); })
        .catch(err => alert("설치 실패: " + err));
    }
    setActiveMenu(null);
  };

  const installTool = (tool: string) => {
    const url = tool === 'gemini' ? 'http://localhost:8000/api/install-gemini-cli' : 'http://localhost:8000/api/install-claude-code';
    fetch(url).then(res => res.json()).then(data => alert(data.message)).catch(err => alert(err));
    setActiveMenu(null);
  };

  const goUp = () => {
    const parts = currentPath.replace(/\\/g, '/').split('/').filter(Boolean);
    if (parts.length > 1) {
      parts.pop();
      let parentPath = parts.join('/');
      if (parts.length === 1 && parts[0].includes(':')) parentPath += '/';
      setCurrentPath(parentPath);
    }
  };

  useEffect(() => {
    const sse = new EventSource('http://localhost:8000/stream');
    sse.onmessage = (e) => {
      try {
        const data: LogRecord = JSON.parse(e.data);
        setLogs(prev => [...prev.slice(-199), data]);
      } catch (err) { }
    };
    return () => sse.close();
  }, []);

  const slots = Array.from({ length: terminalCount }, (_, i) => i);

  return (
    <div className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden select-none font-sans flex-col" onClick={() => setActiveMenu(null)}>
      
      {/* 🟢 Top Menu Bar (IDE Style - 최상단 고정) */}
      <div className="h-7 bg-[#323233] flex items-center px-2 gap-0.5 text-[12px] border-b border-black/30 shrink-0 z-50 shadow-lg">
        <Activity className="w-3.5 h-3.5 text-primary mx-2" />
        {['파일', '편집', '보기', 'AI 도구', '도움말'].map(menu => (
          <div key={menu} className="relative">
            <button 
              onClick={(e) => { e.stopPropagation(); setActiveMenu(activeMenu === menu ? null : menu); }}
              onMouseEnter={() => activeMenu && setActiveMenu(menu)}
              className={`px-2 py-0.5 rounded transition-colors ${activeMenu === menu ? 'bg-[#444444] text-white' : 'hover:bg-white/10'}`}
            >
              {menu}
            </button>
            
            {/* 파일 메뉴 (종료 기능 포함) */}
            {activeMenu === menu && menu === '파일' && (
              <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <button 
                  onClick={() => {
                    if (confirm("시스템을 완전히 종료하시겠습니까? (백그라운드 서버도 종료됩니다)")) {
                      fetch('http://localhost:8000/api/shutdown')
                        .then(() => { alert("서버가 종료되었습니다. 창을 닫아주세요."); window.close(); })
                        .catch(() => { alert("서버 종료 신호 전송 실패"); });
                    }
                    setActiveMenu(null);
                  }} 
                  className="w-full text-left px-4 py-1.5 hover:bg-red-500/20 text-red-400 flex items-center gap-2"
                >
                  <X className="w-3.5 h-3.5" /> 시스템 완전 종료
                </button>
              </div>
            )}

            {/* 편집 메뉴 */}
            {activeMenu === menu && menu === '편집' && (
              <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <button onClick={() => { setLogs([]); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Trash2 className="w-3.5 h-3.5 text-[#e8a87c]" /> 로그 비우기
                </button>
              </div>
            )}

            {/* 보기 메뉴 */}
            {activeMenu === menu && menu === '보기' && (
              <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <button onClick={() => { setIsSidebarOpen(!isSidebarOpen); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Menu className="w-3.5 h-3.5 text-[#3794ef]" /> 사이드바 {isSidebarOpen ? '숨기기' : '보이기'}
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">터미널 레이아웃</div>
                {(['1', '2', '3', '4-col', '2x2'] as const).map(mode => (
                  <button key={mode} onClick={() => { setLayoutMode(mode); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                    <LayoutDashboard className="w-3.5 h-3.5 text-[#cccccc]" /> 
                    {mode === '4-col' ? '4 분할 (세로 열)' : mode === '2x2' ? '4 분할 (격자 2x2)' : `${mode} 분할 뷰`}
                  </button>
                ))}
              </div>
            )}

            {/* AI 도구 메뉴 */}
            {activeMenu === menu && menu === 'AI 도구' && (
              <div className="absolute top-full left-0 w-64 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">하이브 마인드 코어</div>
                <button onClick={installSkills} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center justify-between group">
                  <div className="flex items-center gap-2">
                    <Zap className="w-3.5 h-3.5 text-primary" /> 
                    <span>하이브 스킬 설치 (현재 프로젝트)</span>
                  </div>
                  <span className="text-[9px] text-white/30 group-hover:text-white/60 font-mono italic">Recommended</span>
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">글로벌 CLI 도구</div>
                <button onClick={() => installTool('gemini')} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2">
                  <Terminal className="w-3.5 h-3.5 text-accent" /> 
                  <span>Gemini CLI 설치 (npm -g)</span>
                </button>
                <button onClick={() => installTool('claude')} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-success" /> 
                  <span>Claude Code 설치 (npm -g)</span>
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button onClick={() => window.location.reload()} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2">
                  <RotateCw className="w-3.5 h-3.5 text-[#3794ef]" /> 
                  <span>대시보드 새로고침</span>
                </button>
              </div>
            )}

            {/* 도움말 메뉴 */}
            {activeMenu === menu && menu === '도움말' && (
              <div className="absolute top-full left-0 w-48 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <button onClick={() => { alert("Nexus View v1.0.0\n하이브 마인드 중앙 지휘소"); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Info className="w-3.5 h-3.5 text-[#3794ef]" /> 버전 정보
                </button>
              </div>
            )}
          </div>
        ))}
        <div className="ml-auto flex items-center gap-3 text-[11px] text-[#969696] px-4 font-mono overflow-hidden">
           <span className="truncate opacity-50">{currentPath}</span>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Activity Bar (VS Code Style) */}
        <div className="w-12 h-full bg-[#333333] border-r border-black/40 flex flex-col items-center py-4 gap-4 shrink-0">
          <button onClick={() => { setActiveTab('explorer'); setIsSidebarOpen(true); }} className={`p-2 transition-colors ${activeTab === 'explorer' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Files className="w-6 h-6" />
          </button>
          <button onClick={() => { setActiveTab('search'); setIsSidebarOpen(true); }} className={`p-2 transition-colors ${activeTab === 'search' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Search className="w-6 h-6" />
          </button>
          <button onClick={() => { setActiveTab('hive'); setIsSidebarOpen(true); }} className={`p-2 transition-colors ${activeTab === 'hive' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Zap className="w-6 h-6" />
          </button>
          <div className="mt-auto flex flex-col gap-4">
            <button className="p-2 text-[#858585] hover:text-white transition-colors"><Info className="w-6 h-6" /></button>
            <button className="p-2 text-[#858585] hover:text-white transition-colors"><Settings className="w-6 h-6" /></button>
          </div>
        </div>

        {/* Sidebar (Explorer) */}
        <motion.div
          animate={{ width: isSidebarOpen ? 260 : 0, opacity: isSidebarOpen ? 1 : 0 }}
          className="h-full bg-[#252526] border-r border-black/40 flex flex-col overflow-hidden"
        >
          <div className="h-9 px-4 flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb] shrink-0 border-b border-black/10">
            <span className="flex items-center gap-1.5"><ChevronDown className="w-3.5 h-3.5" />{activeTab === 'explorer' ? 'Explorer' : activeTab === 'search' ? 'Search' : 'Hive Mind'}</span>
            <button onClick={() => setIsSidebarOpen(false)} className="hover:bg-white/10 p-0.5 rounded transition-colors"><X className="w-4 h-4" /></button>
          </div>

          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            <select
              value={drives.find(d => currentPath.startsWith(d)) || currentPath}
              onChange={(e) => setCurrentPath(e.target.value)}
              className="w-full bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded px-2 py-1.5 text-xs focus:outline-none transition-all cursor-pointer mb-4"
            >
              <option value="D:/vibe-coding">vibe-coding</option>
              {drives.map(drive => <option key={drive} value={drive}>{drive}</option>)}
            </select>

            <div className="flex-1 overflow-y-auto space-y-0.5 custom-scrollbar border-t border-white/5 pt-2">
              <button onClick={goUp} className="w-full flex items-center gap-2 px-2 py-1 hover:bg-[#2a2d2e] rounded text-xs transition-colors group">
                <ChevronLeft className="w-4 h-4 text-[#3794ef] group-hover:-translate-x-1 transition-transform" /> ..
              </button>
              {items.map(item => (
                <button
                  key={item.path}
                  onClick={() => item.isDir ? setCurrentPath(item.path) : null}
                  className={`w-full flex items-center gap-2 px-2 py-1 hover:bg-[#2a2d2e] rounded text-xs transition-colors ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] cursor-default'}`}
                >
                  {item.isDir ? <Folder className="w-4 h-4 text-[#e8a87c]" /> : <FileText className="w-4 h-4 text-[#a0a0a0]" />}
                  <span className="truncate">{item.name}</span>
                </button>
              ))}
            </div>
          </div>
        </motion.div>

        {/* Main Area */}
        <div className="flex-1 flex flex-col min-w-0">
          
          {/* Header Bar (Breadcrumbs & Controls) */}
          <header className="h-9 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-4 shrink-0">
            <div className="flex items-center gap-2 overflow-hidden mr-4">
              {!isSidebarOpen && <button onClick={() => setIsSidebarOpen(true)} className="p-1 hover:bg-white/10 rounded"><Menu className="w-4 h-4" /></button>}
              <div className="text-[11px] text-[#969696] truncate font-mono flex items-center">
                {currentPath.split('/').filter(Boolean).map((p, i) => (
                  <span key={i} className="flex items-center"><ChevronRight className="w-3 h-3 mx-1 text-white/20" />{p}</span>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button onClick={refreshItems} className="p-1.5 hover:bg-white/10 rounded text-primary hover:text-white transition-all hover:rotate-180 duration-500" title="Refresh Files">
                <RotateCw className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-1 bg-black/30 rounded-md p-0.5 ml-1 border border-white/5">
                {(['1', '2', '3', '4-col', '2x2'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setLayoutMode(mode)}
                    className={`px-1.5 h-5 rounded text-[10px] font-bold transition-all ${layoutMode === mode ? 'bg-primary text-white' : 'hover:bg-white/5 text-[#858585]'}`}
                    title={mode === '4-col' ? '4 Split (Columns)' : mode === '2x2' ? '4 Split (Grid)' : `${mode} Split`}
                  >
                    {mode === '4-col' ? '4||' : mode === '2x2' ? '4::' : mode}
                  </button>
                ))}
              </div>
            </div>
          </header>

          {/* Terminals Area */}
          <main className="flex-1 p-2 overflow-hidden bg-[#1e1e1e]">
            <div className={`h-full w-full gap-2 grid ${
              layoutMode === '1' ? 'grid-cols-1' :
              layoutMode === '2' ? 'grid-cols-2' :
              layoutMode === '3' ? 'grid-cols-3' :
              layoutMode === '4-col' ? 'grid-cols-4' :
              'grid-cols-2 grid-rows-2'
            }`}>
              {slots.map(slotId => (
                <TerminalSlot key={slotId} slotId={slotId} logs={logs} currentPath={currentPath} terminalCount={terminalCount} />
              ))}
            </div>
          </main>
        </div>
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
  const [inputValue, setInputValue] = useState('');
  const [shortcuts, setShortcuts] = useState<Shortcut[]>(() => {
    try {
      const saved = localStorage.getItem('hive_shortcuts');
      return saved ? JSON.parse(saved) : defaultShortcuts;
    } catch { return defaultShortcuts; }
  });
  const [showShortcutEditor, setShowShortcutEditor] = useState(false);

  const saveShortcuts = (newShortcuts: Shortcut[]) => {
    setShortcuts(newShortcuts);
    localStorage.setItem('hive_shortcuts', JSON.stringify(newShortcuts));
  };

  const launchAgent = (agent: string) => {
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
      term.open(xtermRef.current);
      fitAddon.fit();
      termRef.current = term;
      const wsParams = new URLSearchParams({ agent, cwd: currentPath, cols: term.cols.toString(), rows: term.rows.toString() });
      const ws = new WebSocket(`ws://localhost:8001/pty/slot${slotId}?${wsParams.toString()}`);
      wsRef.current = ws;
      ws.onopen = () => term.write(`\r\n\x1b[38;5;39m[HIVE] ${agent.toUpperCase()} 터미널 연결 성공\x1b[0m\r\n\x1b[38;5;244m> CWD: ${currentPath}\x1b[0m\r\n\r\n`);
      ws.onmessage = async (e) => term.write(e.data instanceof Blob ? await e.data.text() : e.data);
      term.onData(data => ws.readyState === WebSocket.OPEN && ws.send(data));
      window.addEventListener('resize', () => fitAddon.fit());
    }, 50);
  };

  const closeTerminal = () => {
    setIsTerminalMode(false);
    if (wsRef.current) wsRef.current.close();
    if (termRef.current) termRef.current.dispose();
  };

  const handleSend = (text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(text + '\r');
    setInputValue('');
    termRef.current?.focus();
  };

  const slotLogs = logs.filter(l => {
    let hash = 0;
    for (let i = 0; i < l.terminal_id.length; i++) hash = ((hash << 5) - hash) + l.terminal_id.charCodeAt(i);
    return Math.abs(hash) % terminalCount === slotId;
  });

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [slotLogs.length]);

  return (
    <div className="bg-[#252526] border border-black/40 rounded-md flex flex-col overflow-hidden shadow-inner relative">
      <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-3 h-3 text-accent" />
          <span className="text-[10px] font-bold text-[#bbbbbb] uppercase tracking-wider">{isTerminalMode ? `Terminal ${slotId + 1} - ${activeAgent}` : `Terminal ${slotId + 1}`}</span>
        </div>
        {!isTerminalMode ? (
          <div className="flex gap-1">
            <button onClick={() => launchAgent('claude')} className="px-2 py-0.5 bg-[#3c3c3c] hover:bg-primary/40 rounded text-[9px] border border-white/5 transition-all font-bold">CLAUDE</button>
            <button onClick={() => launchAgent('gemini')} className="px-2 py-0.5 bg-[#3c3c3c] hover:bg-primary/40 rounded text-[9px] border border-white/5 transition-all font-bold">GEMINI</button>
          </div>
        ) : (
          <button onClick={closeTerminal} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
        )}
      </div>
      {isTerminalMode ? (
        <div className="flex-1 flex flex-col min-h-0 bg-[#1e1e1e]">
          <div className="flex-1 relative min-h-0"><div ref={xtermRef} className="absolute inset-0 p-2" /></div>
          
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
            <div className="flex gap-2 items-center">
              <input 
                type="text" 
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSend(inputValue); }}
                placeholder="터미널 명령어 전송 (한글 완벽 지원)..."
                className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-xs focus:outline-none focus:border-primary text-white transition-colors"
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
      ) : (
        <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-1.5 custom-scrollbar bg-[#1a1a1a]">
          {slotLogs.map((log, idx) => (
            <div key={idx} className="flex items-start gap-2 border-l-2 border-primary/30 pl-2 py-0.5 bg-white/2 rounded-r">
              <span className="text-primary font-bold whitespace-nowrap opacity-80">[{log.agent}]</span>
              <span className="flex-1 text-[#cccccc] break-all leading-relaxed">{log.trigger}</span>
            </div>
          ))}
          {slotLogs.length === 0 && <div className="h-full flex flex-col items-center justify-center text-white/10 italic">
            <Cpu className="w-8 h-8 mb-2 opacity-10" />
            Waiting for neural activity...
          </div>}
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
  )
}

export default App;
