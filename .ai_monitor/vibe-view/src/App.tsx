/**
 * ------------------------------------------------------------------------
 * 📄 파일명: App.tsx
 * 📂 메인 문서 링크: docs/README.md
 * 📝 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트.
 *          레이아웃 상태, 데이터 폴링, 플로팅 윈도우, 업데이트 관리를 담당하며,
 *          각 기능 영역은 독립 컴포넌트(TopMenuBar, ActivityBar, FileExplorer,
 *          MessageComposer, 각 패널)로 분리되어 있습니다.
 * REVISION HISTORY:
 * - 2026-03-02 Claude: TopMenuBar, ActivityBar, FileExplorer, MessageComposer 분리.
 *                      App.tsx 1303→~430줄로 감소. 상태/로직을 책임 영역별 컴포넌트로 이동.
 * - 2026-03-01 Claude: FileTreeNode, FloatingWindow, TerminalSlot을 독립 컴포넌트 파일로 분리.
 *                      공유 상수(API_BASE, getFileIcon 등)는 constants.ts로 이동.
 *                      App.tsx 2200→~1360줄로 감소.
 * - 2026-03-01 Claude: 각 패널 JSX를 독립 컴포넌트(MessagesPanel, TasksPanel, MemoryPanel,
 *                      OrchestratorPanel, HivePanel, GitPanel, McpPanel, SkillResultsPanel)로 교체.
 *                      배지 카운트는 콜백(onUnreadCount, onActiveCount 등)으로 수신하는 방식으로 전환.
 *                      skills 탭 및 Activity Bar 버튼 추가. App.tsx 3289→2197줄으로 대폭 감소.
 * - 2026-03-01 Claude: 파일 탐색기 가로 스크롤 추가 (overflow-auto + min-w-max 래퍼),
 *                      파일명 truncate→whitespace-nowrap 변경, 버튼 overflow-hidden 제거
 * - 2026-03-01 Claude: 사이드바 좌우 드래그 리사이즈 핸들 추가 (sidebarWidth 동적 상태, 150~600px),
 *                      오른쪽 터미널 영역 overflow-y-auto 스크롤 적용, 그리드 min-h-full로 변경
 * - 2026-03-01 Gemini CLI: 사이드바 VS Code 스타일 UI 복원 (인라인 편집, 호버 버튼 그룹)
 * - 2026-03-01 Gemini-2: 터미널 초기 레이아웃 2분할로 변경 및 뷰어 창 수동 리사이즈 핸들 도입
 * - 2026-02-24: 한글 입력 엔터 키 처리 로직 개선 반영
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Menu, ChevronRight, ChevronDown, RotateCw, X } from 'lucide-react';
/* ── 공유 상수/타입 ── */
import { API_BASE, OpenFile, TreeItem } from './constants';
/* ── 탭 패널 컴포넌트 — 각 탭 영역을 독립 파일로 관리 ── */
import MessagesPanel from './components/panels/MessagesPanel';
import TasksPanel from './components/panels/TasksPanel';
import MemoryPanel from './components/panels/MemoryPanel';
import OrchestratorPanel from './components/panels/OrchestratorPanel';
import MissionControlPanel from './components/panels/MissionControlPanel';
import HivePanel from './components/panels/HivePanel';
import GitPanel from './components/panels/GitPanel';
import McpPanel from './components/panels/McpPanel';
import SkillResultsPanel from './components/panels/SkillResultsPanel';
/* ── 레이아웃 컴포넌트 — App.tsx 2차 분리에서 추출 ── */
import TopMenuBar from './components/TopMenuBar';
import ActivityBar from './components/ActivityBar';
import FileExplorer from './components/FileExplorer';
import MessageComposer from './components/MessageComposer';
/* ── 유틸리티 컴포넌트 ── */
import FloatingWindow from './components/FloatingWindow';
import TerminalSlot from './components/TerminalSlot';
/* ── 공유 타입 ── */
import { LogRecord, AgentMessage, MemoryEntry } from './types';

// 레이아웃 모드 타입 정의 — TopMenuBar와 공유
type LayoutMode = '1' | '2' | '3' | '4' | '2x2' | '6' | '8';

function App() {
  // ─── 레이아웃 상태 ────────────────────────────────────────────────────
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('explorer');
  // activeMenu: 상단 메뉴 드롭다운 활성 상태 — 루트 div 클릭으로 닫기 위해 App에서 관리
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  // 사이드바 너비 — 드래그 리사이즈로 동적 조절 (최소 150px, 최대 600px)
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const isResizingSidebar = useRef(false);
  const sidebarResizeStartX = useRef(0);
  const sidebarResizeStartWidth = useRef(260);
  // 터미널 레이아웃 모드 — '2x2'는 parseInt 불가, 직접 매핑
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('2');
  const terminalCountMap: Record<string, number> = { '1':1, '2':2, '3':3, '4':4, '2x2':4, '6':6, '8':8 };
  const terminalCount = terminalCountMap[layoutMode] ?? 2;

  // ─── 앱 버전 + 업데이트 상태 ─────────────────────────────────────────
  const [appVersion, setAppVersion] = useState<string>('...');
  const [updateReady, setUpdateReady] = useState<{ version: string } | null>(null);
  const [updateApplying, setUpdateApplying] = useState(false);
  const [updateChecking, setUpdateChecking] = useState(false);

  // ─── 패널 배지 카운트 — 각 패널 콜백으로 수신 ────────────────────────
  const [unreadMsgCount, setUnreadMsgCount] = useState(0);
  const [activeTaskCount, setActiveTaskCount] = useState(0);
  const [totalGitChanges, setTotalGitChanges] = useState(0);
  const [conflictCount, setConflictCount] = useState(0);
  const [orchWarningCount, setOrchWarningCount] = useState(0);

  // ─── 데이터 스트림 (TerminalSlot + Activity Bar 배지용) ───────────────
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [skillChain, setSkillChain] = useState<{ status: string }>({ status: 'idle' });
  const [mcpInstalled, setMcpInstalled] = useState<string[]>([]);
  const [geminiUsage, setGeminiUsage] = useState<{
    total_tokens: number; context_window: number; percentage: number
  } | null>(null);
  const [locks, setLocks] = useState<Record<string, string>>({});

  // ─── 현재 탐색 경로 — FileExplorer/GitPanel/TerminalSlot/MemoryPanel 공유 ──
  const [currentPath, setCurrentPath] = useState('');

  // ─── 플로팅 윈도우 상태 (파일 퀵 뷰) ─────────────────────────────────
  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [maxZIndex, setMaxZIndex] = useState(100);

  // ─── 파일 목록 강제 새로고침 트리거 (헤더 새로고침 버튼 → FileExplorer) ──
  const [fileRefreshKey, setFileRefreshKey] = useState(0);

  // ═══ useEffects — 데이터 폴링 및 시스템 유지 ═══════════════════════════

  // 좀비 서버 방지 하트비트 — 창이 닫히면 서버 5초 뒤 자동 종료
  useEffect(() => {
    const sendHeartbeat = () => fetch(`${API_BASE}/api/heartbeat`).catch(() => {});
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, 2000);
    return () => clearInterval(interval);
  }, []);

  // SSE 로그 스트림 — 터미널별 실행 이벤트 실시간 수신 (최대 200개 유지)
  useEffect(() => {
    const sse = new EventSource(`${API_BASE}/stream`);
    sse.onmessage = (e) => {
      try {
        const data: LogRecord = JSON.parse(e.data);
        setLogs(prev => [...prev.slice(-199), data]);
      } catch {}
    };
    return () => sse.close();
  }, []);

  // 파일 락 폴링 (3초) — TerminalSlot 파일 편집 충돌 방지용
  useEffect(() => {
    const fetchLocks = () => {
      fetch(`${API_BASE}/api/locks`)
        .then(res => res.json())
        .then(data => setLocks(data))
        .catch(() => {});
    };
    fetchLocks();
    const interval = setInterval(fetchLocks, 3000);
    return () => clearInterval(interval);
  }, []);

  // 에이전트 간 메시지 폴링 (3초) — TerminalSlot 활성 메시지 표시용
  useEffect(() => {
    const fetchMessages = () => {
      fetch(`${API_BASE}/api/messages`)
        .then(res => res.json())
        .then(data => setMessages(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchMessages();
    const interval = setInterval(fetchMessages, 3000);
    return () => clearInterval(interval);
  }, []);

  // 공유 메모리 폴링 (5초) — Activity Bar 배지(memory.length)용
  useEffect(() => {
    const fetchMemory = () => {
      fetch(`${API_BASE}/api/memory`)
        .then(res => res.json())
        .then(data => setMemory(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchMemory();
    const interval = setInterval(fetchMemory, 5000);
    return () => clearInterval(interval);
  }, []);

  // 스킬 체인 상태 폴링 (3초) — Activity Bar 오케스트레이터 탭 펄스 배지용
  useEffect(() => {
    const fetchChain = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then(data => setSkillChain(data))
        .catch(() => {});
    };
    fetchChain();
    const interval = setInterval(fetchChain, 3000);
    return () => clearInterval(interval);
  }, []);

  // MCP 설치 현황 폴링 (5초) — Activity Bar 배지(mcpInstalled.length)용
  useEffect(() => {
    const fetchInstalled = () => {
      fetch(`${API_BASE}/api/mcp/installed?tool=claude&scope=global`)
        .then(res => res.json())
        .then(data => setMcpInstalled(data.installed ?? []))
        .catch(() => {});
    };
    fetchInstalled();
    const interval = setInterval(fetchInstalled, 5000);
    return () => clearInterval(interval);
  }, []);

  // Gemini 컨텍스트 사용량 폴링 (10초) — TerminalSlot 게이지용
  useEffect(() => {
    const fetchUsage = () => {
      fetch(`${API_BASE}/api/gemini-context-usage`)
        .then(res => res.json())
        .then(data => { if (!data.error) setGeminiUsage(data); })
        .catch(() => {});
    };
    fetchUsage();
    const interval = setInterval(fetchUsage, 10000);
    return () => clearInterval(interval);
  }, []);

  // 앱 버전 로드 — 서버 project-info에서 동적 로드 (하드코딩 금지)
  useEffect(() => {
    fetch(`${API_BASE}/api/project-info`)
      .then(res => res.json())
      .then(data => { if (data.version) setAppVersion(data.version); })
      .catch(() => {});
  }, []);

  // 업데이트 준비 여부 폴링 (30초) — updateReady 상태 갱신
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/api/check-update-ready`)
        .then(res => res.json())
        .then(data => setUpdateReady(data?.ready ? { version: data.version } : null))
        .catch(() => {});
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  // 사이드바 드래그 리사이즈 — document 전역 이벤트로 처리
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizingSidebar.current) return;
      const dx = e.clientX - sidebarResizeStartX.current;
      const newWidth = Math.min(600, Math.max(150, sidebarResizeStartWidth.current + dx));
      setSidebarWidth(newWidth);
    };
    const handleMouseUp = () => {
      if (isResizingSidebar.current) {
        isResizingSidebar.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  // ═══ 이벤트 핸들러 ═══════════════════════════════════════════════════

  // 사이드바 리사이즈 핸들 마우스다운
  const handleSidebarResizeMouseDown = (e: React.MouseEvent) => {
    isResizingSidebar.current = true;
    sidebarResizeStartX.current = e.clientX;
    sidebarResizeStartWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  };

  // 업데이트 수동 확인 — 백그라운드 다운로드 트리거 후 5초 간격으로 최대 6회 폴링
  const triggerUpdateCheck = () => {
    setUpdateChecking(true);
    fetch(`${API_BASE}/api/trigger-update-check`)
      .then(res => res.json())
      .then(() => {
        let tries = 0;
        const poll = setInterval(() => {
          tries++;
          fetch(`${API_BASE}/api/check-update-ready`)
            .then(res => res.json())
            .then(data => {
              if (data?.ready) {
                setUpdateReady({ version: data.version });
                clearInterval(poll);
                setUpdateChecking(false);
              } else if (tries >= 6) {
                clearInterval(poll);
                setUpdateChecking(false);
              }
            })
            .catch(() => { clearInterval(poll); setUpdateChecking(false); });
        }, 5000);
      })
      .catch(() => setUpdateChecking(false));
  };

  // 업데이트 적용
  const applyUpdate = () => {
    setUpdateApplying(true);
    fetch(`${API_BASE}/api/apply-update`, { method: 'POST' })
      .then(res => res.json())
      .then(() => setUpdateReady(null))
      .catch(() => {})
      .finally(() => setUpdateApplying(false));
  };

  // 폴더 열기 — TopMenuBar "파일 → 폴더 열기" 전용 (FileExplorer 자체 버튼과 별개)
  const openFolder = () => {
    fetch(`${API_BASE}/api/select-folder`, { method: 'POST' })
      .then(res => res.json())
      .then(data => { if (data.status === 'success' && data.path) setCurrentPath(data.path); })
      .catch(err => alert('폴더 선택 오류: ' + err));
  };

  // 스킬 설치 — 현재 프로젝트에 하이브 마인드 스킬 설치
  const installSkills = () => {
    if (!currentPath) return;
    if (confirm(`현재 프로젝트(${currentPath})에 하이브 마인드 베이스 스킬을 설치하시겠습니까?`)) {
      fetch(`${API_BASE}/api/install-skills?path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(data => { alert(data.message); })
        .catch(err => alert('설치 실패: ' + err));
    }
    setActiveMenu(null);
  };

  // AI 도구 글로벌 설치 (Gemini CLI / Claude Code)
  const installTool = (tool: string) => {
    const url = tool === 'gemini'
      ? `${API_BASE}/api/install-gemini-cli`
      : `${API_BASE}/api/install-claude-code`;
    fetch(url).then(res => res.json()).then(data => alert(data.message)).catch(err => alert(err));
    setActiveMenu(null);
  };

  // 도움말 문서 — 플로팅 윈도우로 열기 (이미 열린 경우 앞으로 가져오기)
  const openHelpDoc = (topic: string, title: string) => {
    const existing = openFiles.find(f => f.path === `help:${topic}`);
    if (existing) { bringToFront(existing.id); return; }
    const newId = Date.now().toString();
    const newZIndex = maxZIndex + 1;
    setMaxZIndex(newZIndex);
    setOpenFiles(prev => [...prev, {
      id: newId, name: title, path: `help:${topic}`,
      content: 'Loading...', isLoading: true, zIndex: newZIndex
    }]);
    fetch(`${API_BASE}/api/help?topic=${topic}`)
      .then(res => res.json())
      .then(data => {
        setOpenFiles(prev => prev.map(f => f.id === newId
          ? { ...f, content: data.error ? `Error: ${data.error}` : data.content, isLoading: false }
          : f));
      })
      .catch(err => {
        setOpenFiles(prev => prev.map(f => f.id === newId
          ? { ...f, content: `Failed to load: ${err}`, isLoading: false }
          : f));
      });
    setActiveMenu(null);
  };

  // ─── 플로팅 윈도우 조작 ────────────────────────────────────────────────
  const bringToFront = (id: string) => {
    setMaxZIndex(prev => prev + 1);
    setOpenFiles(prev => prev.map(f => f.id === id ? { ...f, zIndex: maxZIndex + 1 } : f));
  };

  const closeFile = (id: string) => setOpenFiles(prev => prev.filter(f => f.id !== id));

  const updateFileContent = (id: string, newContent: string) =>
    setOpenFiles(prev => prev.map(f => f.id === id ? { ...f, content: newContent } : f));

  // 파일 저장 API 호출
  const handleSaveFile = (path: string, content: string) => {
    const targetPath = path.includes(':') || path.startsWith('/') || path.startsWith('\\')
      ? path
      : `${currentPath}/${path}`.replace(/\/+/g, '/');
    fetch(`${API_BASE}/api/save-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: targetPath, content })
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') alert(`✅ 저장 완료: ${path.split(/[\\/]/).pop()}`);
        else alert('❌ 저장 실패: ' + (data.message || '알 수 없는 오류'));
      })
      .catch(() => alert('🚨 저장 중 네트워크 오류가 발생했습니다.'));
  };

  // FileExplorer의 onOpenFile 콜백 — 파일 클릭 시 FloatingWindow 생성
  const handleOpenFile = (item: TreeItem) => {
    const existing = openFiles.find(f => f.path === item.path);
    if (existing) { bringToFront(existing.id); return; }
    const newId = Date.now().toString();
    const newZIndex = maxZIndex + 1;
    setMaxZIndex(newZIndex);
    const isImg = /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(item.name);
    setOpenFiles(prev => [...prev, {
      id: newId, name: item.name, path: item.path,
      content: isImg ? '' : 'Loading...', isLoading: !isImg, zIndex: newZIndex
    }]);
    if (!isImg) {
      fetch(`${API_BASE}/api/read-file?path=${encodeURIComponent(item.path)}`)
        .then(res => res.json())
        .then(data => {
          setOpenFiles(prev => prev.map(f => f.id === newId
            ? { ...f, content: data.error ? `Error: ${data.error}` : data.content, isLoading: false }
            : f));
        })
        .catch(err => {
          setOpenFiles(prev => prev.map(f => f.id === newId
            ? { ...f, content: `Failed to load file: ${err}`, isLoading: false }
            : f));
        });
    }
  };

  // 터미널 슬롯 인덱스 배열
  const slots = Array.from({ length: terminalCount }, (_, i) => i);

  // 사이드바 탭 제목 매핑
  const sidebarTitle = {
    explorer: 'Explorer', search: 'Search',
    'mission-control': 'Mission Control',
    messages: '메시지 채널', tasks: '태스크 보드',
    memory: '공유 메모리', git: 'Git 감시',
    mcp: 'MCP 관리자', skills: '스킬 결과',
    orchestrate: 'AI 오케스트레이터', hive: '하이브 진단',
  }[activeTab] ?? activeTab;

  return (
    <div
      className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden select-none font-sans flex-col"
      onClick={() => setActiveMenu(null)}
    >
      {/* ── 업데이트 알림 배너 (updateReady 상태일 때만 표시) ── */}
      {updateReady && (
        <div className="flex items-center justify-between px-3 py-1 bg-primary/20 border-b border-primary/40 shrink-0 z-50">
          <span className="text-[10px] text-primary font-bold">
            새 버전 <span className="font-mono">{updateReady.version}</span> 업데이트 준비 완료
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={applyUpdate}
              disabled={updateApplying}
              className="text-[9px] font-bold px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/80 disabled:opacity-50 transition-colors"
            >
              {updateApplying ? '적용 중...' : '지금 업데이트'}
            </button>
            <button
              onClick={() => setUpdateReady(null)}
              className="text-[9px] text-white/40 hover:text-white/70 transition-colors"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* ── 상단 메뉴바 컴포넌트 ── */}
      <TopMenuBar
        activeMenu={activeMenu}
        setActiveMenu={setActiveMenu}
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        setLayoutMode={setLayoutMode}
        appVersion={appVersion}
        updateReady={updateReady}
        updateApplying={updateApplying}
        updateChecking={updateChecking}
        onApplyUpdate={applyUpdate}
        onTriggerUpdateCheck={triggerUpdateCheck}
        onOpenFolder={openFolder}
        onInstallSkills={installSkills}
        onInstallTool={installTool}
        onOpenHelpDoc={openHelpDoc}
        onClearLogs={() => setLogs([])}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* ── 좌측 액티비티 바 컴포넌트 ── */}
        <ActivityBar
          activeTab={activeTab}
          onTabChange={(tab) => { setActiveTab(tab); setIsSidebarOpen(true); }}
          skillChainStatus={skillChain.status}
          orchWarningCount={orchWarningCount}
          unreadMsgCount={unreadMsgCount}
          activeTaskCount={activeTaskCount}
          memoryCount={memory.length}
          conflictCount={conflictCount}
          totalGitChanges={totalGitChanges}
          mcpCount={mcpInstalled.length}
          isThinking={skillChain.status === 'running'}
        />

        {/* ── 사이드바 — 탭 패널 + 메시지 작성창 ── */}
        <motion.div
          animate={{ width: isSidebarOpen ? sidebarWidth : 0, opacity: isSidebarOpen ? 1 : 0 }}
          className="h-full bg-[#252526] border-r border-black/40 flex flex-col overflow-hidden"
          style={{ minWidth: isSidebarOpen ? 150 : 0 }}
        >
          {/* 사이드바 헤더 — 현재 탭 제목 + 닫기 버튼 */}
          <div className="h-9 px-4 flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb] shrink-0 border-b border-black/10">
            <span className="flex items-center gap-1.5">
              <ChevronDown className="w-3.5 h-3.5" />{sidebarTitle}
            </span>
            <button
              onClick={() => setIsSidebarOpen(false)}
              className="hover:bg-white/10 p-0.5 rounded transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* 패널 컨텐츠 + 메시지 작성창 */}
          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            {activeTab === 'messages' ? (
              /* 메시지 채널 패널 */
              <MessagesPanel onUnreadCount={setUnreadMsgCount} />
            ) : activeTab === 'tasks' ? (
              /* 태스크 보드 패널 */
              <TasksPanel onActiveCount={setActiveTaskCount} />
            ) : activeTab === 'memory' ? (
              /* 공유 메모리 패널 */
              <MemoryPanel currentProjectName={currentPath.split(/[/\\]/).filter(Boolean).pop()} />
            ) : activeTab === 'orchestrate' ? (
              /* AI 오케스트레이터 패널 */
              <OrchestratorPanel onWarningCount={setOrchWarningCount} />
            ) : activeTab === 'mission-control' ? (
              /* Mission Control 패널 */
              <MissionControlPanel />
            ) : activeTab === 'hive' ? (
              /* 하이브 진단 패널 */
              <HivePanel />
            ) : activeTab === 'git' ? (
              /* Git 감시 패널 */
              <GitPanel
                currentPath={currentPath}
                onChangesCount={(c, conf) => { setTotalGitChanges(c); setConflictCount(conf); }}
              />
            ) : activeTab === 'mcp' ? (
              /* MCP 관리자 패널 */
              <McpPanel />
            ) : activeTab === 'skills' ? (
              /* 스킬 실행 결과 패널 */
              <SkillResultsPanel />
            ) : (
              /* 파일 탐색기 — FileExplorer 컴포넌트로 분리 */
              <FileExplorer
                currentPath={currentPath}
                onPathChange={setCurrentPath}
                onOpenFile={handleOpenFile}
                refreshKey={fileRefreshKey}
              />
            )}

            {/* 에이전트 간 메시지 작성 — messages 탭은 MessagesPanel 내부 폼 사용, 나머지 탭 공통 */}
            {activeTab !== 'messages' && <MessageComposer />}
          </div>
        </motion.div>

        {/* ── 사이드바 드래그 리사이즈 핸들 ── */}
        {isSidebarOpen && (
          <div
            onMouseDown={handleSidebarResizeMouseDown}
            className="w-1 h-full cursor-col-resize shrink-0 hover:bg-primary/60 transition-colors bg-black/20 z-20 group"
            title="드래그하여 탐색기 너비 조절"
          >
            <div className="w-full h-full group-hover:bg-primary/40 transition-colors" />
          </div>
        )}

        {/* ── 메인 영역 (브레드크럼 헤더 + 터미널 그리드) ── */}
        <div className="flex-1 flex flex-col min-w-0" onClick={() => {}}>
          {/* 브레드크럼 헤더 + 레이아웃 컨트롤 */}
          <header className="h-9 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-4 shrink-0">
            <div className="flex items-center gap-2 overflow-hidden mr-4">
              {!isSidebarOpen && (
                <button onClick={() => setIsSidebarOpen(true)} className="p-1 hover:bg-white/10 rounded">
                  <Menu className="w-4 h-4" />
                </button>
              )}
              {/* 경로 브레드크럼 */}
              <div className="text-[11px] text-[#969696] truncate font-mono flex items-center">
                {currentPath.split('/').filter(Boolean).map((p, i) => (
                  <span key={i} className="flex items-center">
                    <ChevronRight className="w-3 h-3 mx-1 text-white/20" />{p}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {/* 파일 목록 새로고침 — fileRefreshKey 증가로 FileExplorer에 신호 */}
              <button
                onClick={() => setFileRefreshKey(k => k + 1)}
                className="p-1.5 hover:bg-white/10 rounded text-primary hover:text-white transition-all hover:rotate-180 duration-500"
                title="Refresh Files"
              >
                <RotateCw className="w-4 h-4" />
              </button>
              {/* 레이아웃 전환 버튼 그룹 */}
              <div className="flex items-center gap-1 bg-black/30 rounded-md p-0.5 ml-1 border border-white/5 flex-wrap">
                {(['1', '2', '3', '4', '2x2', '6', '8'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setLayoutMode(mode)}
                    className={`px-1.5 h-5 rounded text-[10px] font-bold transition-all ${layoutMode === mode ? 'bg-primary text-white' : 'hover:bg-white/5 text-[#858585]'}`}
                    title={mode === '4' ? '4 분할 (가로 4열)' : mode === '2x2' ? '4 분할 (2×2 격자)' : mode === '6' ? '6 분할 (3×2 격자)' : mode === '8' ? '8 분할 (4×2 격자)' : `${mode} 분할`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
          </header>

          {/* 터미널 그리드 — layoutMode에 따른 열/행 분할 */}
          <main className="flex-1 p-2 overflow-y-auto custom-scrollbar bg-[#1e1e1e]">
            <div className={`min-h-full w-full gap-2 grid ${
              layoutMode === '1' ? 'grid-cols-1' :
              layoutMode === '2' ? 'grid-cols-2' :
              layoutMode === '3' ? 'grid-cols-3' :
              layoutMode === '4' ? 'grid-cols-4' :
              layoutMode === '2x2' ? 'grid-cols-2 grid-rows-2' :
              layoutMode === '6' ? 'grid-cols-3 grid-rows-2' :
              'grid-cols-4 grid-rows-2'
            }`}>
              {slots.map(slotId => (
                <TerminalSlot
                  key={slotId}
                  slotId={slotId}
                  logs={logs}
                  currentPath={currentPath}
                  terminalCount={terminalCount}
                  locks={locks}
                  messages={messages}
                  tasks={[]}
                  geminiUsage={geminiUsage}
                />
              ))}
            </div>
          </main>
        </div>
      </div>

      {/* ── 파일 퀵 뷰 플로팅 윈도우들 ── */}
      {openFiles.map((file, idx) => (
        <FloatingWindow
          key={file.id}
          file={file}
          idx={idx}
          bringToFront={bringToFront}
          closeFile={closeFile}
          updateFileContent={updateFileContent}
          handleSaveFile={handleSaveFile}
        />
      ))}
    </div>
  );
}

export default App;
