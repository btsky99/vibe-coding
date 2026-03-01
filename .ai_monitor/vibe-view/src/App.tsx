/**
 * ------------------------------------------------------------------------
 * 📄 파일명: App.tsx
 * 📂 메인 문서 링크: docs/README.md
 * 🔗 개별 상세 문서: docs/App.tsx.md
 * 📝 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트로, 파일 탐색기, 다중 윈도우 퀵 뷰, 
 *          터미널 분할 화면 및 활성 파일 뷰어를 관리하는 메인 파일입니다.
 * REVISION HISTORY:
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
import {
  Menu, Terminal, RotateCw,
  ChevronLeft, X, Zap, Search, Settings,
  Files, Cpu, Info, ChevronRight, ChevronDown,
  Trash2, LayoutDashboard, MessageSquare, ClipboardList, Plus, Brain,
  GitBranch, Package, Send, Edit3, Network
} from 'lucide-react';
import { VscFile, VscFolder, VscFolderOpened, VscNewFolder, VscTrash } from 'react-icons/vsc';
/* ── 공유 상수/타입 — constants.ts에서 중앙 관리 ── */
import { API_BASE, getFileIcon, OpenFile } from './constants';
/* ── 패널 컴포넌트 import — 각 탭 패널을 독립 컴포넌트로 분리하여 App.tsx 가독성 향상 ── */
import MessagesPanel from './components/panels/MessagesPanel';
import TasksPanel from './components/panels/TasksPanel';
import MemoryPanel from './components/panels/MemoryPanel';
import OrchestratorPanel from './components/panels/OrchestratorPanel';
import HivePanel from './components/panels/HivePanel';
import GitPanel from './components/panels/GitPanel';
import McpPanel from './components/panels/McpPanel';
import SkillResultsPanel from './components/panels/SkillResultsPanel';
/* ── 분리된 서브 컴포넌트 import — FileTreeNode/FloatingWindow/TerminalSlot 각자 파일로 분리 ── */
import FileTreeNode from './components/FileTreeNode';
import FloatingWindow from './components/FloatingWindow';
import TerminalSlot from './components/TerminalSlot';
/* LogRecord/AgentMessage: App 레벨 상태 타입에 사용, MemoryEntry: 공유 메모리 배지용 */
import { LogRecord, AgentMessage, MemoryEntry } from './types';

// API_BASE, WS_PORT, getFileIcon, OpenFile, Shortcut, defaultShortcuts, SLASH_COMMANDS →
// constants.ts로 이동됨. App.tsx는 constants.ts에서 임포트하여 사용합니다.

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('explorer');
  // ─── 패널 컴포넌트에서 콜백으로 전달받는 배지 카운트 상태 ────────────────────────
  // 각 패널이 독립 컴포넌트로 분리되어 있으므로, 배지 표시에 필요한 카운트를 콜백으로 받아 App 레벨에서 관리
  const [unreadMsgCount, setUnreadMsgCount] = useState(0);
  const [activeTaskCount, setActiveTaskCount] = useState(0);
  const [totalGitChanges, setTotalGitChanges] = useState(0);
  const [conflictCount, setConflictCount] = useState(0);
  const [orchWarningCount, setOrchWarningCount] = useState(0);
  // 사이드바 너비 — 드래그 리사이즈로 동적 조절 (최소 150px, 최대 600px)
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const isResizingSidebar = useRef(false);
  const sidebarResizeStartX = useRef(0);
  const sidebarResizeStartWidth = useRef(260);
  // 레이아웃 모드: 1, 2, 3, 4(가로4열), 2x2(2×2격자), 6(3×2격자), 8(4×2격자)
  const [layoutMode, setLayoutMode] = useState<'1' | '2' | '3' | '4' | '2x2' | '6' | '8'>('2');
  // '2x2'는 parseInt 불가 → 직접 매핑
  const terminalCountMap: Record<string, number> = { '1':1, '2':2, '3':3, '4':4, '2x2':4, '6':6, '8':8 };
  const terminalCount = terminalCountMap[layoutMode] ?? 2;
  const [appVersion, setAppVersion] = useState<string>('...');
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [locks, setLocks] = useState<Record<string, string>>({});
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  // 파일 락(Lock) 상태 폴링
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

  // 사이드바 좌우 드래그 리사이즈 — document 전역 이벤트로 처리
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

  // 사이드바 리사이즈 핸들 마우스다운 처리 함수
  const handleSidebarResizeMouseDown = (e: React.MouseEvent) => {
    isResizingSidebar.current = true;
    sidebarResizeStartX.current = e.clientX;
    sidebarResizeStartWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  };

  // ─── 에이전트 간 메시지 채널 상태 ───────────────────────────────────
  // messages는 sendMessage 함수(사이드바 하단 고정 입력창)와 터미널 모드에서 사용
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [msgFrom, setMsgFrom] = useState('claude');
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');

  // 메시지 채널 폴링 (3초 간격) — 메시지 목록은 MessagesPanel 내부에서 관리되나,
  // sendMessage 함수가 App 레벨에 남아 있으므로 최신 메시지 조회용으로 유지
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

  // ─── 공유 메모리(SQLite) 상태 — Activity Bar 배지(memory.length)용 최소 폴링 유지 ─────
  // 나머지 메모리 편집 로직은 MemoryPanel 내부로 이동됨
  const [memory, setMemory] = useState<MemoryEntry[]>([]);

  // 공유 메모리 폴링 (5초 간격) — memory.length 배지 갱신용
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

  // ─── 스킬 체인 실행 상태 (AI 오케스트레이터) ───────────────────────────────
  // skillChain은 Activity Bar의 "실행 중" 펄스 애니메이션 배지에 사용
  // vibe-orchestrate 스킬이 저장한 skill_chain.json을 3초마다 폴링
  // 대시보드에 실행 흐름(skill1 → skill2 → skill3) 실시간 표시
  const [skillChain, setSkillChain] = useState<{
    status: string;
    request?: string;
    plan?: string[];
    current_step?: number;
    results?: { skill: string; status: string; summary: string }[];
    started_at?: string;
    updated_at?: string;
  }>({ status: 'idle' });

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

  // ─── MCP 관리자 상태 — Activity Bar 배지(mcpInstalled.length)용으로 폴링 유지 ─────────
  // mcpCatalog, mcpTool, mcpScope 등은 McpPanel 내부로 이동됨
  const [mcpInstalled, setMcpInstalled] = useState<string[]>([]);

  // MCP 설치 현황 폴링 (5초 간격) — mcpInstalled.length 배지 갱신용 (global/claude 기준)
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

  // ─── Gemini 컨텍스트 사용량 — TerminalSlot 컴포넌트의 컨텍스트 게이지에 사용 ─────────
  const [geminiUsage, setGeminiUsage] = useState<{ total_tokens: number, context_window: number, percentage: number } | null>(null);

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

  // 메시지 전송
  const sendMessage = () => {
    if (!msgContent.trim()) return;
    const cleanContent = msgContent.replace(/[\r\n]+$/, '');
    fetch(`${API_BASE}/api/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: msgFrom, to: msgTo, type: msgType, content: cleanContent }),
    })
      .then(res => res.json())
      .then(() => {
        setMsgContent('');
        return fetch(`${API_BASE}/api/messages`);
      })
      .then(res => res.json())
      .then(data => setMessages(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // Quick View 팝업 상태 (다중 창 지원)
  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [maxZIndex, setMaxZIndex] = useState(100);

  const bringToFront = (id: string) => {
    setMaxZIndex(prev => prev + 1);
    setOpenFiles(prev => prev.map(f => f.id === id ? { ...f, zIndex: maxZIndex + 1 } : f));
  };

  const closeFile = (id: string) => {
    setOpenFiles(prev => prev.filter(f => f.id !== id));
  };

  // 파일 내용 실시간 업데이트 (에디터용)
  const updateFileContent = (id: string, newContent: string) => {
    setOpenFiles(prev => prev.map(f => f.id === id ? { ...f, content: newContent } : f));
  };

  // 파일 저장 API 호출
  const handleSaveFile = (path: string, content: string) => {
    // 이미 절대경로라면 그대로 쓰고, 아니면 currentPath와 병합
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
        if (data.status === 'success') {
          console.log('💾 File saved:', data.path);
          // 저장 성공 알림 (시스템 알림 대신 간단한 콘솔/상태 표시가 좋으나 현재 구조상 alert 활용)
          alert(`✅ 저장 완료: ${path.split(/[\\/]/).pop()}`);
        } else {
          console.error('❌ Save failed:', data.message);
          alert('❌ 저장 실패: ' + (data.message || '알 수 없는 오류'));
        }
      })
      .catch(err => {
        console.error('🚨 Save error:', err);
        alert('🚨 저장 중 네트워크 오류가 발생했습니다.');
      });
  };

  const openHelpDoc = (topic: string, title: string) => {
    const existing = openFiles.find(f => f.path === `help:${topic}`);
    if (existing) { bringToFront(existing.id); return; }
    const newId = Date.now().toString();
    const newZIndex = maxZIndex + 1;
    setMaxZIndex(newZIndex);
    setOpenFiles(prev => [...prev, { id: newId, name: title, path: `help:${topic}`, content: 'Loading...', isLoading: true, zIndex: newZIndex }]);
    fetch(`${API_BASE}/api/help?topic=${topic}`)
      .then(res => res.json())
      .then(data => {
        setOpenFiles(prev => prev.map(f => f.id === newId ? { ...f, content: data.error ? `Error: ${data.error}` : data.content, isLoading: false } : f));
      })
      .catch(err => {
        setOpenFiles(prev => prev.map(f => f.id === newId ? { ...f, content: `Failed to load: ${err}`, isLoading: false } : f));
      });
    setActiveMenu(null);
  };

  // 좀비 서버 방지용 하트비트 (창 닫히면 서버 5초 뒤 자동 종료)
  useEffect(() => {
    const sendHeartbeat = () => fetch(`${API_BASE}/api/heartbeat`).catch(() => {});
    sendHeartbeat(); // 즉시 전송
    const interval = setInterval(sendHeartbeat, 2000); // 2초마다 전송
    return () => clearInterval(interval);
  }, []);

  // ─── 업데이트 알림 상태 ───────────────────────────────────────────────────
  const [updateReady, setUpdateReady] = useState<{ version: string } | null>(null);
  const [updateApplying, setUpdateApplying] = useState(false);
  // 업데이트 확인 중 상태 (수동 버튼 클릭 시)
  const [updateChecking, setUpdateChecking] = useState(false);

  // 30초마다 업데이트 준비 여부 확인
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

  // 수동 업데이트 확인 — 백그라운드 다운로드 트리거 후 30초 내 결과 폴링
  const triggerUpdateCheck = () => {
    setUpdateChecking(true);
    fetch(`${API_BASE}/api/trigger-update-check`)
      .then(res => res.json())
      .then(() => {
        // 트리거 후 5초 뒤부터 최대 6회(30초) 폴링
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

  const applyUpdate = () => {
    setUpdateApplying(true);
    fetch(`${API_BASE}/api/apply-update`, { method: 'POST' })
      .then(res => res.json())
      .then(() => setUpdateReady(null))
      .catch(() => {})
      .finally(() => setUpdateApplying(false));
  };

  // 파일 시스템 탐색 상태
  const [drives, setDrives] = useState<string[]>([]);
  // 초기값 빈 문자열 — api/config의 last_path 또는 api/projects 첫 항목으로 채워짐 (하드코딩 제거)
  const [currentPath, setCurrentPath] = useState("");
  const [initialConfigLoaded, setInitialConfigLoaded] = useState(false);
  const [items, setItems] = useState<{ name: string, path: string, isDir: boolean }[]>([]);
  // 최근 방문 프로젝트 목록 — api/projects에서 로드, 드롭다운에 표시
  const [recentProjects, setRecentProjects] = useState<string[]>([]);

  // 초기 설정 로드 (마지막 경로 기억) + 서버 버전 + 최근 프로젝트 목록 동적 로드
  useEffect(() => {
    // 서버에서 실제 버전 정보 가져오기 (하드코딩 방지)
    fetch(`${API_BASE}/api/project-info`)
      .then(res => res.json())
      .then(data => { if (data.version) setAppVersion(data.version); })
      .catch(() => {});

    // 최근 프로젝트 목록 로드 — 드롭다운에 표시
    fetch(`${API_BASE}/api/projects`)
      .then(res => res.json())
      .then(data => { if (Array.isArray(data)) setRecentProjects(data); })
      .catch(() => {});

    // 마지막 경로 로드 — 없으면 최근 프로젝트 첫 항목으로 폴백
    fetch(`${API_BASE}/api/config`)
      .then(res => res.json())
      .then(data => {
        if (data.last_path) {
          setCurrentPath(data.last_path);
        }
        // last_path 없어도 initialConfigLoaded=true로 설정 (드라이브 탐색 가능하도록)
        setInitialConfigLoaded(true);
      })
      .catch(() => setInitialConfigLoaded(true));
  }, []);

  // 경로 변경 시 config 저장 + 최근 프로젝트 목록 갱신
  useEffect(() => {
    if (!initialConfigLoaded || !currentPath) return;

    // 1) 마지막 경로 config에 저장
    fetch(`${API_BASE}/api/config/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_path: currentPath })
    }).catch(() => {});

    // 2) 드라이브 루트(예: "D:/")가 아닌 실제 프로젝트 경로만 최근 목록에 저장
    // 드라이브 루트는 탐색 중간 경로라 프로젝트로 간주하지 않음
    const isDriveRoot = /^[A-Za-z]:\/+$/.test(currentPath);
    if (!isDriveRoot) {
      fetch(`${API_BASE}/api/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentPath })
      })
        .then(res => res.json())
        .then(data => { if (Array.isArray(data.projects)) setRecentProjects(data.projects); })
        .catch(() => {});
    }
  }, [currentPath, initialConfigLoaded]);

  const openFolder = () => {
    fetch(`${API_BASE}/api/select-folder`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success' && data.path) {
          setCurrentPath(data.path);
        }
      })
      .catch(err => alert("폴더 선택 오류: " + err));
  };

  const [treeMode, setTreeMode] = useState(true);
  const [treeExpanded, setTreeExpanded] = useState<Record<string, boolean>>({});
  const [treeChildren, setTreeChildren] = useState<Record<string, { name: string; path: string; isDir: boolean }[]>>({});

  // ─── 컨텍스트 메뉴 상태 ──────────────────────────────────────────────────
  const [contextMenu, setContextMenu] = useState<{ x: number, y: number, path: string, isDir: boolean } | null>(null);

  // currentPath 변경 시 트리 초기화 (Git 감시 경로 동기화는 GitPanel 내부에서 처리)
  useEffect(() => { setTreeExpanded({}); setTreeChildren({}); }, [currentPath]);

  // 트리 데이터 갱신
  const refreshTree = (parentPath: string) => {
    fetch(`${API_BASE}/api/files?path=${encodeURIComponent(parentPath)}`)
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setTreeChildren(prev => ({ ...prev, [parentPath]: data }));
        }
      })
      .catch(() => {});
  };

  // 파일/폴더 생성 및 삭제 API
  const createFile = (parentPath: string) => {
    const name = prompt("새 파일 이름:");
    if (!name) return;
    fetch(`${API_BASE}/api/files/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: `${parentPath}/${name}`, is_dir: false })
    }).then(() => refreshTree(parentPath));
  };

  const createFolder = (parentPath: string) => {
    const name = prompt("새 폴더 이름:");
    if (!name) return;
    fetch(`${API_BASE}/api/files/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: `${parentPath}/${name}`, is_dir: true })
    }).then(() => refreshTree(parentPath));
  };

  const deleteFile = (path: string, isDir: boolean) => {
    if (!confirm(`${isDir ? '폴더' : '파일'}을(를) 삭제하시겠습니까?\n${path}`)) return;
    const parentPath = path.split(/[\\\/]/).slice(0, -1).join('/');
    fetch(`${API_BASE}/api/files/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    }).then(() => {
      if (parentPath) refreshTree(parentPath);
      else refreshItems();
    });
  };

  const renameFile = (src: string, dest: string) => {
    return fetch(`${API_BASE}/api/file-rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src, dest })
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          const parentPath = src.split(/[\\\/]/).slice(0, -1).join('/');
          if (parentPath) refreshTree(parentPath);
          else refreshItems();
          return true;
        } else {
          alert("이름 변경 오류: " + data.message);
          return false;
        }
      })
      .catch(err => {
        alert("이름 변경 오류: " + err);
        return false;
      });
  };

  // 드라이브 목록 가져오기
  useEffect(() => {
    fetch(`${API_BASE}/api/drives`)
      .then(res => res.json())
      .then(data => setDrives(data))
      .catch(() => { });
  }, []);

  // 현재 경로의 항목(폴더/파일) 가져오기
  const refreshItems = () => {
    if (!currentPath) return;
    fetch(`${API_BASE}/api/files?path=${encodeURIComponent(currentPath)}`)
      .then(res => res.json())
      .then(data => setItems(data))
      .catch(() => { });
  };

  const handleTreeToggle = (path: string) => {
    if (treeExpanded[path]) {
      setTreeExpanded(prev => ({ ...prev, [path]: false }));
    } else {
      setTreeExpanded(prev => ({ ...prev, [path]: true }));
      if (!treeChildren[path]) {
        fetch(`${API_BASE}/api/files?path=${encodeURIComponent(path)}`)
          .then(res => res.json())
          .then(data => { if (Array.isArray(data)) setTreeChildren(prev => ({ ...prev, [path]: data })); })
          .catch(() => {});
      }
    }
  };

  const handleFileClick = (item: {name: string, path: string, isDir: boolean}) => {
    setSelectedPath(item.path);
    if (item.isDir) {
      setCurrentPath(item.path);
    } else {
      const existing = openFiles.find(f => f.path === item.path);
      if (existing) {
        bringToFront(existing.id);
        return;
      }
      
      const newId = Date.now().toString();
      const newZIndex = maxZIndex + 1;
      setMaxZIndex(newZIndex);
      
      const isImg = /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(item.name);
      setOpenFiles(prev => [...prev, {
        id: newId,
        name: item.name,
        path: item.path,
        content: isImg ? '' : 'Loading...',
        isLoading: !isImg,
        zIndex: newZIndex
      }]);

      if (!isImg) {
        fetch(`${API_BASE}/api/read-file?path=${encodeURIComponent(item.path)}`)
          .then(res => res.json())
          .then(data => {
            setOpenFiles(prev => prev.map(f => f.id === newId ? {
              ...f,
              content: data.error ? `Error: ${data.error}` : data.content,
              isLoading: false
            } : f));
          })
          .catch(err => {
            setOpenFiles(prev => prev.map(f => f.id === newId ? {
              ...f,
              content: `Failed to load file: ${err}`,
              isLoading: false
            } : f));
          });
      }
    }
  };

  useEffect(() => {
    refreshItems();
  }, [currentPath]);

  // 스킬 및 도구 설치 로직
  const installSkills = () => {
    if (!currentPath) return;
    if (confirm(`현재 프로젝트(${currentPath})에 하이브 마인드 베이스 스킬을 설치하시겠습니까?`)) {
      fetch(`${API_BASE}/api/install-skills?path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(data => { alert(data.message); refreshItems(); })
        .catch(err => alert("설치 실패: " + err));
    }
    setActiveMenu(null);
  };

  const installTool = (tool: string) => {
    const url = tool === 'gemini' ? `${API_BASE}/api/install-gemini-cli` : `${API_BASE}/api/install-claude-code`;
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
    const sse = new EventSource(`${API_BASE}/stream`);
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
      
      {/* 업데이트 알림 배너 */}
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

      {/* 🟢 Top Menu Bar (IDE Style - 최상단 고정) */}
      <div className="h-7 bg-[#323233] flex items-center px-2 gap-0.5 text-[12px] border-b border-black/30 shrink-0 z-50 shadow-lg">
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
                  onClick={() => { openFolder(); setActiveMenu(null); }} 
                  className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
                >
                  <VscFolderOpened className="w-3.5 h-3.5 text-[#dcb67a]" /> 폴더 열기...
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button 
                  onClick={() => {
                    if (confirm("시스템을 완전히 종료하시겠습니까? (백그라운드 서버도 종료됩니다)")) {
                      fetch(`${API_BASE}/api/shutdown`)
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
                {(['1', '2', '3', '4', '2x2', '6', '8'] as const).map(mode => (
                  <button key={mode} onClick={() => { setLayoutMode(mode); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                    <LayoutDashboard className="w-3.5 h-3.5 text-[#cccccc]" />
                    {mode === '1' ? '1 분할 뷰' : mode === '2' ? '2 분할 뷰' : mode === '3' ? '3 분할 뷰' : mode === '4' ? '4 분할 (가로 4열)' : mode === '2x2' ? '4 분할 (2×2 격자)' : mode === '6' ? '6 분할 (3×2 격자)' : '8 분할 (4×2 격자)'}
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
              <div className="absolute top-full left-0 w-56 bg-[#252526] border border-black/40 shadow-2xl rounded-b z-[100] py-1 animate-in fade-in slide-in-from-top-1">
                <div className="px-3 py-1 text-[10px] text-textMuted font-bold uppercase tracking-wider opacity-60">사용 설명서</div>
                <button onClick={() => openHelpDoc('claude-code', 'Claude Code 사용 설명서')} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-success" /> Claude Code 사용법
                </button>
                <button onClick={() => openHelpDoc('gemini-cli', 'Gemini CLI 사용 설명서')} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Terminal className="w-3.5 h-3.5 text-accent" /> Gemini CLI 사용법
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button onClick={() => { alert("바이브 코딩(Vibe Coding) v3.6.3\n하이브 마인드 중앙 지휘소"); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Info className="w-3.5 h-3.5 text-[#3794ef]" /> 버전 정보
                </button>
              </div>
            )}
          </div>
        ))}
        <div className="ml-auto flex items-center gap-2 text-[11px] text-[#969696] px-2 font-mono overflow-hidden">
          {/* 업데이트 적용 버튼 — updateReady 상태일 때만 표시 */}
          {updateReady && (
            <button
              onClick={applyUpdate}
              disabled={updateApplying}
              className="shrink-0 text-[9px] font-bold px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/80 disabled:opacity-50 transition-colors animate-pulse"
              title={`새 버전 ${updateReady.version} 업데이트 준비 완료`}
            >
              {updateApplying ? '적용 중...' : `↑ ${updateReady.version}`}
            </button>
          )}
          {/* 업데이트 확인 버튼 — 항상 표시 (배포 버전에서만 실제 동작) */}
          <button
            onClick={triggerUpdateCheck}
            disabled={updateChecking || !!updateReady}
            className="shrink-0 text-[9px] px-1.5 py-0.5 rounded border border-white/10 text-white/40 hover:text-white/70 hover:border-white/30 disabled:opacity-30 transition-colors"
            title="업데이트 확인"
          >
            {updateChecking ? '확인 중...' : '업데이트 확인'}
          </button>
          {/* 버전 배지 — 서버 _version.py에서 동적 로드 (하드코딩 금지) */}
          <span className="shrink-0 text-[9px] bg-primary/20 text-primary px-1.5 py-0.5 rounded border border-primary/30 font-mono">v{appVersion}</span>
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
          {/* AI 오케스트레이터 탭 — 스킬 체인 실행/모니터링 */}
          <button onClick={() => { setActiveTab('orchestrate'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'orchestrate' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Network className="w-6 h-6" />
            {skillChain.status === 'running' && (
              <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-primary rounded-full animate-pulse" />
            )}
          </button>
          {/* 하이브 진단 탭 — 에이전트 상태 + 시스템 헬스 */}
          <button onClick={() => { setActiveTab('hive'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'hive' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Zap className="w-6 h-6" />
            {orchWarningCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-orange-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {orchWarningCount > 9 ? '9+' : orchWarningCount}
              </span>
            )}
          </button>
          {/* 메시지 채널 탭 — 읽지 않은 메시지 수 배지 표시 */}
          <button onClick={() => { setActiveTab('messages'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'messages' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <MessageSquare className="w-6 h-6" />
            {unreadMsgCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {unreadMsgCount > 9 ? '9+' : unreadMsgCount}
              </span>
            )}
          </button>
          {/* 태스크 보드 탭 — 활성 작업 수 배지 표시 */}
          <button onClick={() => { setActiveTab('tasks'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'tasks' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <ClipboardList className="w-6 h-6" />
            {activeTaskCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-yellow-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {activeTaskCount > 9 ? '9+' : activeTaskCount}
              </span>
            )}
          </button>
          {/* 공유 메모리 탭 */}
          <button onClick={() => { setActiveTab('memory'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'memory' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Brain className="w-6 h-6" />
            {memory.length > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-cyan-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {memory.length > 99 ? '99+' : memory.length}
              </span>
            )}
          </button>
          {/* Git 감시 탭 — 충돌 또는 커밋할 항목 배지 표시 */}
          <button onClick={() => { setActiveTab('git'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'git' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <GitBranch className="w-6 h-6" />
            {conflictCount > 0 ? (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none animate-pulse">
                {conflictCount > 9 ? '9+' : conflictCount}
              </span>
            ) : totalGitChanges > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-cyan-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {totalGitChanges > 99 ? '99+' : totalGitChanges}
              </span>
            )}
          </button>
          {/* MCP 관리자 탭 — 설치된 MCP 수 배지 */}
          <button onClick={() => { setActiveTab('mcp'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'mcp' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <Package className="w-6 h-6" />
            {mcpInstalled.length > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-purple-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {mcpInstalled.length > 9 ? '9+' : mcpInstalled.length}
              </span>
            )}
          </button>
          {/* 스킬 실행 결과 탭 — 스킬 결과 패널 표시 */}
          <button onClick={() => { setActiveTab('skills'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'skills' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="스킬 실행 결과">
            <Zap className="w-5 h-5" />
          </button>
          <div className="mt-auto flex flex-col gap-4">
            <button className="p-2 text-[#858585] hover:text-white transition-colors"><Info className="w-6 h-6" /></button>
            <button className="p-2 text-[#858585] hover:text-white transition-colors"><Settings className="w-6 h-6" /></button>
          </div>
        </div>

        {/* Sidebar (Explorer) — 너비는 sidebarWidth 상태로 동적 조절 */}
        <motion.div
          animate={{ width: isSidebarOpen ? sidebarWidth : 0, opacity: isSidebarOpen ? 1 : 0 }}
          className="h-full bg-[#252526] border-r border-black/40 flex flex-col overflow-hidden"
          style={{ minWidth: isSidebarOpen ? 150 : 0 }}
        >
          <div className="h-9 px-4 flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb] shrink-0 border-b border-black/10">
            <span className="flex items-center gap-1.5"><ChevronDown className="w-3.5 h-3.5" />{activeTab === 'explorer' ? 'Explorer' : activeTab === 'search' ? 'Search' : activeTab === 'messages' ? '메시지 채널' : activeTab === 'tasks' ? '태스크 보드' : activeTab === 'memory' ? '공유 메모리' : activeTab === 'git' ? 'Git 감시' : activeTab === 'mcp' ? 'MCP 관리자' : activeTab === 'skills' ? '스킬 결과' : activeTab === 'orchestrate' ? 'AI 오케스트레이터' : '하이브 진단'}</span>
            <button onClick={() => setIsSidebarOpen(false)} className="hover:bg-white/10 p-0.5 rounded transition-colors"><X className="w-4 h-4" /></button>
          </div>

          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            {/* 메시지 채널 패널 — MessagesPanel 컴포넌트로 분리 (배지 카운트는 콜백으로 수신) */}
            {activeTab === 'messages' ? (
              <MessagesPanel onUnreadCount={setUnreadMsgCount} />
            ) : activeTab === 'tasks' ? (
              /* 태스크 보드 패널 — TasksPanel 컴포넌트로 분리 */
              <TasksPanel onActiveCount={setActiveTaskCount} />
            ) : activeTab === 'memory' ? (
              /* 공유 메모리 패널 — MemoryPanel 컴포넌트로 분리 */
              <MemoryPanel currentProjectName={currentPath.split(/[/\\]/).filter(Boolean).pop()} />
            ) : activeTab === 'orchestrate' ? (
              /* AI 오케스트레이터 패널 — OrchestratorPanel 컴포넌트로 분리 */
              <OrchestratorPanel onWarningCount={setOrchWarningCount} />
            ) : activeTab === 'hive' ? (
              /* 하이브 진단 패널 — HivePanel 컴포넌트로 분리 */
              <HivePanel />
            ) : activeTab === 'git' ? (
              /* Git 감시 패널 — GitPanel 컴포넌트로 분리 (충돌/변경 수는 콜백으로 수신) */
              <GitPanel
                currentPath={currentPath}
                onChangesCount={(c, conf) => { setTotalGitChanges(c); setConflictCount(conf); }}
              />
            ) : activeTab === 'mcp' ? (
              /* MCP 관리자 패널 — McpPanel 컴포넌트로 분리 */
              <McpPanel />
            ) : activeTab === 'skills' ? (
              /* 스킬 실행 결과 패널 — SkillResultsPanel 컴포넌트로 분리 */
              <SkillResultsPanel />
            ) : (
              /* ── 파일 탐색기 ── */
              <>
                {/* 드라이브 선택 + 트리/플랫 토글 */}
                <div className="flex items-center gap-1 mb-2">
                  <button
                    onClick={openFolder}
                    className="p-1.5 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded text-[#dcb67a] transition-all shrink-0"
                    title="프로젝트 폴더 열기"
                  >
                    <VscFolderOpened className="w-4 h-4" />
                  </button>
                  <select
                    value={
                      // 현재 경로와 일치하는 최근 프로젝트를 우선 매칭 (정확히 같거나 하위 경로)
                      // 그 다음 드라이브 루트 매칭 (예: D:/) — 하드코딩 제거
                      recentProjects.find(p => currentPath === p || currentPath.startsWith(p + '/') || currentPath.startsWith(p + '\\'))
                        || drives.find(d => currentPath.startsWith(d))
                        || currentPath
                    }
                    onChange={(e) => setCurrentPath(e.target.value)}
                    className="flex-1 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded px-2 py-1.5 text-xs focus:outline-none transition-all cursor-pointer"
                  >
                    {/* 최근 프로젝트 — 선택 시 해당 프로젝트 루트로 즉시 이동 */}
                    {recentProjects.length > 0 && (
                      <optgroup label="📁 최근 프로젝트">
                        {recentProjects.map(p => (
                          <option key={p} value={p}>
                            {p.split(/[\\\/]/).filter(Boolean).pop() || p} — {p}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {/* 드라이브 루트 — 탐색 시작점 */}
                    <optgroup label="💾 드라이브">
                      {drives.map(drive => <option key={drive} value={drive}>{drive}</option>)}
                    </optgroup>
                  </select>
                  <button
                    onClick={() => setTreeMode(v => !v)}
                    className={`p-1.5 rounded border text-[10px] font-bold transition-all shrink-0 ${treeMode ? 'bg-primary/20 border-primary/40 text-primary' : 'bg-[#3c3c3c] border-white/10 text-[#858585] hover:text-white'}`}
                    title={treeMode ? '플랫 뷰로 전환' : '트리 뷰로 전환'}
                  >
                    {treeMode ? '≡' : '⊞'}
                  </button>
                </div>

                {/* 파일 목록 컨테이너 — overflow-auto로 상하/좌우 스크롤 모두 허용 */}
                <div className="flex-1 overflow-auto custom-scrollbar border-t border-white/5 pt-2">
                  {/* min-w-max 래퍼: 파일명이 긴 경우 가로로 확장되어 스크롤 가능하게 함 */}
                  <div className="min-w-max space-y-0.5">
                  <button onClick={goUp} className="w-full flex items-center gap-2 px-2 py-1 hover:bg-[#2a2d2e] rounded text-xs transition-colors group">
                    <ChevronLeft className="w-4 h-4 text-[#3794ef] group-hover:-translate-x-1 transition-transform" /> ..
                  </button>

                  {treeMode ? (
                    /* 트리 뷰 */
                    items.map(item => (
                      <FileTreeNode
                        key={item.path}
                        item={item}
                        depth={0}
                        expanded={treeExpanded}
                        treeChildren={treeChildren}
                        onToggle={handleTreeToggle}
                        onFileOpen={handleFileClick}
                        onContextMenu={(e, it) => {
                          setContextMenu({
                            x: e.clientX,
                            y: e.clientY,
                            path: it.path,
                            isDir: it.isDir
                          });
                        }}
                        onRename={renameFile}
                        onDelete={deleteFile}
                        onCreateFile={createFile}
                        onCreateFolder={createFolder}
                        editingPath={editingPath}
                        setEditingPath={setEditingPath}
                        editValue={editValue}
                        setEditValue={setEditValue}
                      />
                    ))
                  ) : (
                    /* 플랫 뷰 (기존) */
                    items.map(item => (
                      <div key={item.path} className={`group flex items-center gap-0 px-2 py-0.5 rounded text-xs transition-colors relative ${selectedPath === item.path ? 'bg-primary/20 border-l-2 border-primary' : 'hover:bg-[#2a2d2e]'}`}>
                        <button
                          onClick={() => handleFileClick(item)}
                          onContextMenu={(e) => {
                            e.preventDefault();
                            setContextMenu({ x: e.clientX, y: e.clientY, path: item.path, isDir: item.isDir });
                          }}
                          className={`flex items-center gap-2 py-1 ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] font-medium'}`}
                        >
                          {item.isDir ? <VscFolder className="w-4 h-4 text-[#dcb67a] shrink-0" /> : getFileIcon(item.name)}
                          {editingPath === item.path ? (
                            <input
                              autoFocus
                              value={editValue}
                              onChange={e => setEditValue(e.target.value)}
                              onKeyDown={async e => {
                                if (e.key === 'Enter') {
                                  if (editValue && editValue !== item.name) {
                                    const parentPath = item.path.split(/[\\\/]/).slice(0, -1).join('/');
                                    const dest = parentPath ? `${parentPath}/${editValue}` : editValue;
                                    await renameFile(item.path, dest);
                                  }
                                  setEditingPath(null);
                                }
                                if (e.key === 'Escape') setEditingPath(null);
                              }}
                              onBlur={async () => {
                                if (editValue && editValue !== item.name) {
                                  const parentPath = item.path.split(/[\\\/]/).slice(0, -1).join('/');
                                  const dest = parentPath ? `${parentPath}/${editValue}` : editValue;
                                  await renameFile(item.path, dest);
                                }
                                setEditingPath(null);
                              }}
                              onClick={e => e.stopPropagation()}
                              className="flex-1 bg-[#1e1e1e] border border-primary outline-none px-1 text-xs text-white rounded"
                            />
                          ) : (
                            <span className="whitespace-nowrap">{item.name}</span>
                          )}
                        </button>
                        
                        {editingPath !== item.path && (
                          <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 ml-auto shrink-0 pr-1 transition-all">
                            {item.isDir && (
                              <>
                                <button onClick={(e) => { e.stopPropagation(); createFile(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 파일"><Plus className="w-3 h-3" /></button>
                                <button onClick={(e) => { e.stopPropagation(); createFolder(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 폴더"><VscNewFolder className="w-3 h-3" /></button>
                              </>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(item.path)}`)
                                  .then(res => res.json())
                                  .then(data => {
                                    if (data.status === 'success') {
                                      const btn = e.currentTarget;
                                      const originalHtml = btn.innerHTML;
                                      btn.innerHTML = '<span class="text-[8px] text-green-400">Copied!</span>';
                                      setTimeout(() => btn.innerHTML = originalHtml, 1500);
                                    }
                                  });
                              }}
                              className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all"
                              title="경로 복사"
                            >
                              <ClipboardList className="w-3 h-3" />
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); setEditingPath(item.path); setEditValue(item.name); }}
                              className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all"
                              title="이름 변경"
                            >
                              <Edit3 className="w-3 h-3" />
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteFile(item.path, item.isDir); }}
                              className="p-1 hover:bg-red-500/20 rounded text-[#858585] hover:text-red-400 transition-all"
                              title="삭제"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                  </div>{/* end min-w-max wrapper */}
                </div>
              </>
            )}

            {/* ── 사이드바 하단 메시지 입력창 (상시 고정) ── */}
            <div className="mt-auto pt-3 border-t border-white/5 flex flex-col gap-2 shrink-0">
              <div className="flex gap-1">
                <select value={msgFrom} onChange={e => setMsgFrom(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white">
                  <option value="user">User</option>
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                  <option value="system">System</option>
                </select>
                <span className="text-white/30 text-[10px] px-0.5 leading-7">→</span>
                <select value={msgTo} onChange={e => setMsgTo(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white">
                  <option value="all">All</option>
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                </select>
              </div>
              <select value={msgType} onChange={e => setMsgType(e.target.value)} className="w-full bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white">
                <option value="info">ℹ️ 정보 공유</option>
                <option value="handoff">🤝 핸드오프 (작업 위임)</option>
                <option value="request">📋 작업 요청</option>
                <option value="task_complete">✅ 완료 알림</option>
                <option value="warning">⚠️ 경고</option>
              </select>
              <div className="relative">
                <textarea
                  value={msgContent}
                  onChange={e => setMsgContent(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      if (!e.nativeEvent.isComposing && msgContent.trim()) {
                        sendMessage();
                        setTimeout(() => setMsgContent(''), 0);
                      }
                    }
                  }}
                  placeholder="메시지 입력... (Enter: 전송)"
                  rows={2}
                  className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors resize-none pr-8"
                />
                <button
                  onClick={sendMessage}
                  disabled={!msgContent.trim()}
                  className="absolute right-1.5 bottom-1.5 p-1 bg-primary hover:bg-primary/80 disabled:opacity-30 text-white rounded transition-colors"
                  title="전송 (Enter)"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* 사이드바 좌우 드래그 리사이즈 핸들 — 이 선을 좌우로 드래그하여 너비 조절 */}
        {isSidebarOpen && (
          <div
            onMouseDown={handleSidebarResizeMouseDown}
            className="w-1 h-full cursor-col-resize shrink-0 hover:bg-primary/60 transition-colors bg-black/20 z-20 group"
            title="드래그하여 탐색기 너비 조절"
          >
            {/* 시각적 드래그 인디케이터 (호버 시 강조) */}
            <div className="w-full h-full group-hover:bg-primary/40 transition-colors" />
          </div>
        )}

        {/* 컨텍스트 메뉴 UI */}
        {contextMenu && (
          <div 
            className="fixed z-[9999] bg-[#252526] border border-white/10 rounded shadow-2xl py-1 min-w-[150px] animate-in fade-in zoom-in duration-100"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            {contextMenu.isDir && (
              <>
                <button onClick={() => { createFile(contextMenu.path); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2">
                  <VscFile className="w-3.5 h-3.5" /> 새 파일...
                </button>
                <button onClick={() => { createFolder(contextMenu.path); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2">
                  <VscFolder className="w-3.5 h-3.5" /> 새 폴더...
                </button>
                <div className="h-[1px] bg-white/5 my-1" />
              </>
            )}
            <button 
              onClick={() => { 
                fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(contextMenu.path)}`);
                setContextMenu(null); 
              }} 
              className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2"
            >
              <ClipboardList className="w-3.5 h-3.5" /> 경로 복사
            </button>
            <button 
              onClick={() => { 
                setEditingPath(contextMenu.path); 
                setEditValue(contextMenu.path.split(/[\\\/]/).pop() || "");
                setContextMenu(null); 
              }} 
              className="w-full text-left px-3 py-1.5 text-xs text-[#cccccc] hover:bg-primary hover:text-white transition-colors flex items-center gap-2"
            >
              <Edit3 className="w-3.5 h-3.5" /> 이름 변경...
            </button>
            <div className="h-[1px] bg-white/5 my-1" />
            <button onClick={() => { deleteFile(contextMenu.path, contextMenu.isDir); setContextMenu(null); }} className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/20 transition-colors flex items-center gap-2">
              <VscTrash className="w-3.5 h-3.5" /> 삭제
            </button>

            <button onClick={() => setContextMenu(null)} className="w-full text-left px-3 py-1.5 text-xs text-[#858585] hover:bg-white/5 transition-colors">
              취소
            </button>
          </div>
        )}

        {/* Main Area */}
        <div className="flex-1 flex flex-col min-w-0" onClick={() => setContextMenu(null)}>
          
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

          {/* Terminals Area — overflow-y-auto로 세로 스크롤 허용 */}
          <main className="flex-1 p-2 overflow-y-auto custom-scrollbar bg-[#1e1e1e]">
            {/* 터미널 그리드: 1→1열, 2→2열, 3→3열, 4→가로4열, 2x2→2×2격자, 6→3×2격자, 8→4×2격자 */}
            <div className={`min-h-full w-full gap-2 grid ${
              layoutMode === '1' ? 'grid-cols-1' :
              layoutMode === '2' ? 'grid-cols-2' :
              layoutMode === '3' ? 'grid-cols-3' :
              layoutMode === '4' ? 'grid-cols-4' :
              layoutMode === '2x2' ? 'grid-cols-2 grid-rows-2' :
              layoutMode === '6' ? 'grid-cols-3 grid-rows-2' :
              'grid-cols-4 grid-rows-2'
            }`}>
              {/* tasks는 TasksPanel로 이동됨 — TerminalSlot에는 빈 배열 전달 */}
              {slots.map(slotId => (
                <TerminalSlot key={slotId} slotId={slotId} logs={logs} currentPath={currentPath} terminalCount={terminalCount} locks={locks} messages={messages} tasks={[]} geminiUsage={geminiUsage} />
              ))}            </div>
          </main>
        </div>
      </div>

      {/* Quick View Floating Panels */}
      {openFiles.map((file, idx) => (
        <FloatingWindow key={file.id} file={file} idx={idx} bringToFront={bringToFront} closeFile={closeFile} updateFileContent={updateFileContent} handleSaveFile={handleSaveFile} />
      ))}
    </div>
  )
}

export default App;
