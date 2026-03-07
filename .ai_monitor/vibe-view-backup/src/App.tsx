/**
 * ------------------------------------------------------------------------
 * 📄 파일명: App.tsx
 * 📂 메인 문서 링크: docs/README.md
 * 🔗 개별 상세 문서: docs/App.tsx.md
 * 📝 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트로, 파일 탐색기, 다중 윈도우 퀵 뷰, 
 *          터미널 분할 화면 및 활성 파일 뷰어를 관리하는 메인 파일입니다.
 *          (2026-02-24: 한글 입력 엔터 키 처리 로직 개선 반영)
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Activity, Menu, Terminal, RotateCw,
  ChevronLeft, X, Zap, Search, Settings,
  Files, Cpu, Info, ChevronRight, ChevronDown,
  Trash2, LayoutDashboard, MessageSquare, ClipboardList, Plus, Brain,
  GitBranch, AlertTriangle, GitCommit as GitCommitIcon, ArrowUp, ArrowDown,
  Bot, Play, CircleDot, Package, CheckCircle2, Circle
} from 'lucide-react';
import { 
  SiPython, SiJavascript, SiTypescript, SiMarkdown, 
  SiGit, SiCss3, SiHtml5 
} from 'react-icons/si';
import { FaWindows } from 'react-icons/fa';
import { VscJson, VscFileMedia, VscArchive, VscFile, VscFolder, VscFolderOpened } from 'react-icons/vsc';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { LogRecord, AgentMessage, Task, MemoryEntry, GitStatus, GitCommit, OrchestratorStatus, McpEntry } from './types';

// 현재 접속 포트 기반으로 API/WS 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;
const WS_PORT = parseInt(window.location.port) + 1;

export interface Shortcut { label: string; cmd: string; }
const defaultShortcuts: Shortcut[] = [
  { label: '마스터 호출', cmd: 'gemini --skill master' },
  { label: '🧹 화면 지우기', cmd: '/clear' },
  { label: '깃 커밋', cmd: 'git add . && git commit -m "update"' },
  { label: '깃 푸시', cmd: 'git push' },
  { label: '문서 업데이트', cmd: 'gemini "현재까지 진행 상황 문서 업데이트"' },
];

// 에이전트별 슬래시 커맨드 목록 (한글 설명 포함)
interface SlashCommand { cmd: string; desc: string; category: string; }
const SLASH_COMMANDS: Record<string, SlashCommand[]> = {
  claude: [
    { cmd: '/model',       desc: '모델 변경 (opus / sonnet / haiku)',    category: '설정' },
    { cmd: '/clear',       desc: '대화 기록 초기화',                      category: '설정' },
    { cmd: '/compact',     desc: '대화 압축 — 컨텍스트 절약',             category: '설정' },
    { cmd: '/memory',      desc: '메모리(CLAUDE.md) 파일 편집',           category: '설정' },
    { cmd: '/vim',         desc: 'Vim 키 바인딩 모드 토글',               category: '설정' },
    { cmd: '/help',        desc: '전체 도움말 보기',                       category: '도움말' },
    { cmd: '/doctor',      desc: '개발 환경 진단',                         category: '도움말' },
    { cmd: '/status',      desc: '현재 상태 및 컨텍스트 확인',            category: '도움말' },
    { cmd: '/bug',         desc: '버그 리포트 Anthropic에 전송',           category: '도움말' },
    { cmd: '/review',      desc: '현재 코드 리뷰 요청',                   category: '작업' },
    { cmd: '/commit',      desc: 'Git 커밋 메시지 자동 생성',             category: '작업' },
    { cmd: '/init',        desc: 'CLAUDE.md 프로젝트 가이드 생성',        category: '작업' },
    { cmd: '/pr_comments', desc: 'GitHub PR 댓글 가져오기',               category: '작업' },
    { cmd: '/terminal',    desc: '터미널 명령 실행 모드',                  category: '작업' },
  ],
  gemini: [
    { cmd: '/help',        desc: '전체 도움말 보기',                       category: '도움말' },
    { cmd: '/clear',       desc: '대화 초기화',                            category: '설정' },
    { cmd: '/chat',        desc: '대화형 채팅 모드 전환',                  category: '설정' },
    { cmd: '/tools',       desc: '사용 가능한 툴 목록 보기',              category: '도움말' },
  ],
};

export const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'py': return <SiPython className="w-4 h-4 text-[#3776ab] shrink-0" />;
    case 'js': case 'jsx': case 'mjs': case 'cjs': return <SiJavascript className="w-4 h-4 text-[#F7DF1E] shrink-0" />;
    case 'ts': case 'tsx': return <SiTypescript className="w-4 h-4 text-[#3178C6] shrink-0" />;
    case 'json': return <VscJson className="w-4 h-4 text-[#cbcb41] shrink-0" />;
    case 'md': return <SiMarkdown className="w-4 h-4 text-[#083fa1] shrink-0" />;
    case 'html': case 'htm': return <SiHtml5 className="w-4 h-4 text-[#E34F26] shrink-0" />;
    case 'css': case 'scss': case 'less': return <SiCss3 className="w-4 h-4 text-[#1572B6] shrink-0" />;
    case 'png': case 'jpg': case 'jpeg': case 'gif': case 'svg': case 'ico': return <VscFileMedia className="w-4 h-4 text-[#a074c4] shrink-0" />;
    case 'zip': case 'tar': case 'gz': case 'rar': case '7z': return <VscArchive className="w-4 h-4 text-[#d19a66] shrink-0" />;
    case 'bat': case 'cmd': case 'exe': return <FaWindows className="w-4 h-4 text-[#0078D4] shrink-0" />;
    case 'gitignore': return <SiGit className="w-4 h-4 text-[#F05032] shrink-0" />;
    default: return <VscFile className="w-4 h-4 text-[#cccccc] shrink-0" />;
  }
};

export interface OpenFile {
  id: string;
  name: string;
  path: string;
  content: string;
  isLoading: boolean;
  zIndex: number;
}

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('explorer');
  // 레이아웃 모드: 1, 2, 3, 4(가로4열), 2x2(2×2격자), 6(3×2격자), 8(4×2격자)
  const [layoutMode, setLayoutMode] = useState<'1' | '2' | '3' | '4' | '2x2' | '6' | '8'>('1');
  // '2x2'는 parseInt 불가 → 직접 매핑
  const terminalCountMap: Record<string, number> = { '1':1, '2':2, '3':3, '4':4, '2x2':4, '6':6, '8':8 };
  const terminalCount = terminalCountMap[layoutMode] ?? 2;
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [locks, setLocks] = useState<Record<string, string>>({});
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

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

  // ─── 에이전트 간 메시지 채널 상태 ───────────────────────────────────
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [lastSeenMsgCount, setLastSeenMsgCount] = useState(0);
  const [msgFrom, setMsgFrom] = useState('claude');
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');

  // 읽지 않은 메시지 수 — 메시지 탭을 열면 0으로 초기화
  const unreadMsgCount = activeTab === 'messages' ? 0 : Math.max(0, messages.length - lastSeenMsgCount);

  // 메시지 탭 진입 시 읽음 처리
  useEffect(() => {
    if (activeTab === 'messages') setLastSeenMsgCount(messages.length);
  }, [activeTab, messages.length]);

  // 메시지 채널 폴링 (3초 간격)
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

  // ─── 태스크 보드 상태 ─────────────────────────────────────────────
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskFilter, setTaskFilter] = useState<'all' | 'pending' | 'in_progress' | 'done'>('all');
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskAssignee, setNewTaskAssignee] = useState('all');
  const [newTaskPriority, setNewTaskPriority] = useState<'high' | 'medium' | 'low'>('medium');

  // 활성 작업 수 배지 (pending + in_progress)
  const activeTaskCount = tasks.filter(t => t.status !== 'done').length;

  // 태스크 폴링 (4초 간격)
  useEffect(() => {
    const fetchTasks = () => {
      fetch(`${API_BASE}/api/tasks`)
        .then(res => res.json())
        .then(data => setTasks(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchTasks();
    const interval = setInterval(fetchTasks, 4000);
    return () => clearInterval(interval);
  }, []);

  // 새 작업 생성
  const createTask = () => {
    if (!newTaskTitle.trim()) return;
    fetch(`${API_BASE}/api/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: newTaskTitle,
        description: newTaskDesc,
        assigned_to: newTaskAssignee,
        priority: newTaskPriority,
        created_by: 'user',
      }),
    })
      .then(res => res.json())
      .then(() => {
        setNewTaskTitle('');
        setNewTaskDesc('');
        setShowTaskForm(false);
        return fetch(`${API_BASE}/api/tasks`);
      })
      .then(res => res.json())
      .then(data => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 작업 상태/필드 업데이트
  const updateTask = (id: string, fields: Partial<Task>) => {
    fetch(`${API_BASE}/api/tasks/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, ...fields }),
    })
      .then(res => res.json())
      .then(() => fetch(`${API_BASE}/api/tasks`))
      .then(res => res.json())
      .then(data => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 작업 삭제
  const deleteTask = (id: string) => {
    fetch(`${API_BASE}/api/tasks/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    })
      .then(res => res.json())
      .then(() => fetch(`${API_BASE}/api/tasks`))
      .then(res => res.json())
      .then(data => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // ─── 공유 메모리(SQLite) 상태 ────────────────────────────────────────────
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memSearch, setMemSearch] = useState('');
  const [showMemForm, setShowMemForm] = useState(false);
  const [editingMemKey, setEditingMemKey] = useState<string | null>(null);
  const [memKey, setMemKey] = useState('');
  const [memTitle, setMemTitle] = useState('');
  const [memContent, setMemContent] = useState('');
  const [memTags, setMemTags] = useState('');
  const [memAuthor, setMemAuthor] = useState('claude');

  // 검색어가 있으면 서버 검색, 없으면 전체 목록 사용
  const fetchMemory = (q = '') => {
    const url = q ? `${API_BASE}/api/memory?q=${encodeURIComponent(q)}` : `${API_BASE}/api/memory`;
    fetch(url)
      .then(res => res.json())
      .then(data => setMemory(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 공유 메모리 폴링 (5초 간격 — 자주 바뀌지 않으므로 느리게)
  useEffect(() => {
    fetchMemory();
    const interval = setInterval(() => fetchMemory(memSearch), 5000);
    return () => clearInterval(interval);
  }, [memSearch]);

  // 검색어 변경 시 즉시 검색
  useEffect(() => { fetchMemory(memSearch); }, [memSearch]);

  // 메모리 저장 (신규 또는 수정 — key 기준 UPSERT)
  const saveMemory = () => {
    if (!memKey.trim() || !memContent.trim()) return;
    fetch(`${API_BASE}/api/memory/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key:     memKey.trim(),
        title:   memTitle.trim() || memKey.trim(),
        content: memContent.trim(),
        tags:    memTags.split(',').map(t => t.trim()).filter(Boolean),
        author:  memAuthor,
      }),
    })
      .then(() => {
        setMemKey(''); setMemTitle(''); setMemContent('');
        setMemTags(''); setShowMemForm(false); setEditingMemKey(null);
        fetchMemory(memSearch);
      })
      .catch(() => {});
  };

  // 메모리 항목 삭제
  const deleteMemory = (key: string) => {
    fetch(`${API_BASE}/api/memory/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }).then(() => fetchMemory(memSearch)).catch(() => {});
  };

  // 수정 폼 열기 (기존 항목 데이터 주입)
  const startEditMemory = (entry: MemoryEntry) => {
    setMemKey(entry.key);
    setMemTitle(entry.title);
    setMemContent(entry.content);
    setMemTags(entry.tags.join(', '));
    setMemAuthor(entry.author);
    setEditingMemKey(entry.key);
    setShowMemForm(true);
  };

  // ─── Git 실시간 감시 상태 ─────────────────────────────────────────────
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [gitLog, setGitLog] = useState<GitCommit[]>([]);
  // 초기값은 하드코딩 — currentPath 선언 이후 useEffect로 동기화
  const [gitPath, setGitPath] = useState("D:/vibe-coding");

  // Git 상태 폴링 (5초 간격)
  useEffect(() => {
    const fetchGit = () => {
      const encodedPath = encodeURIComponent(gitPath);
      fetch(`${API_BASE}/api/git/status?path=${encodedPath}`)
        .then(res => res.json())
        .then((data: GitStatus) => setGitStatus(data))
        .catch(() => {});
      fetch(`${API_BASE}/api/git/log?path=${encodedPath}&n=15`)
        .then(res => res.json())
        .then((data: GitCommit[]) => setGitLog(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchGit();
    const interval = setInterval(fetchGit, 5000);
    return () => clearInterval(interval);
  }, [gitPath]);

  // 충돌 파일 수 (Activity Bar 배지용)
  const conflictCount = gitStatus?.conflicts?.length ?? 0;

  // ─── 오케스트레이터 상태 ──────────────────────────────────────────────
  const [orchStatus, setOrchStatus] = useState<OrchestratorStatus | null>(null);
  const [orchRunning, setOrchRunning] = useState(false);
  const [orchLastRun, setOrchLastRun] = useState<string | null>(null);

  // 오케스트레이터 상태 폴링 (10초 간격)
  useEffect(() => {
    const fetchOrch = () => {
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then((data: OrchestratorStatus) => setOrchStatus(data))
        .catch(() => {});
    };
    fetchOrch();
    const interval = setInterval(fetchOrch, 10000);
    return () => clearInterval(interval);
  }, []);

  // 오케스트레이터 수동 실행
  const runOrchestrator = () => {
    setOrchRunning(true);
    fetch(`${API_BASE}/api/orchestrator/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then(res => res.json())
      .then(() => {
        setOrchLastRun(new Date().toLocaleTimeString());
        return fetch(`${API_BASE}/api/orchestrator/status`);
      })
      .then(res => res.json())
      .then((data: OrchestratorStatus) => setOrchStatus(data))
      .catch(() => {})
      .finally(() => setOrchRunning(false));
  };

  // 오케스트레이터 경고 수 (Hive 탭 배지용)
  const orchWarningCount = orchStatus?.warnings?.length ?? 0;

  // ─── MCP 관리자 상태 ─────────────────────────────────────────────────────
  const [mcpCatalog, setMcpCatalog] = useState<McpEntry[]>([]);
  const [mcpInstalled, setMcpInstalled] = useState<string[]>([]);
  const [mcpTool, setMcpTool] = useState<'claude' | 'gemini'>('claude');
  const [mcpScope, setMcpScope] = useState<'global' | 'project'>('global');
  const [mcpLoading, setMcpLoading] = useState<Record<string, boolean>>({}); // 이름 → 로딩 여부
  const [mcpMsg, setMcpMsg] = useState(''); // 마지막 작업 결과 메시지

  // 카탈로그는 최초 1회만 불러옴
  useEffect(() => {
    fetch(`${API_BASE}/api/mcp/catalog`)
      .then(res => res.json())
      .then((data: McpEntry[]) => setMcpCatalog(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  // 설치 현황 폴링 (5초 간격 — 도구·범위 변경 시 즉시 재조회)
  const fetchMcpInstalled = () => {
    fetch(`${API_BASE}/api/mcp/installed?tool=${mcpTool}&scope=${mcpScope}`)
      .then(res => res.json())
      .then(data => setMcpInstalled(data.installed ?? []))
      .catch(() => {});
  };
  useEffect(() => {
    fetchMcpInstalled();
    const interval = setInterval(fetchMcpInstalled, 5000);
    return () => clearInterval(interval);
  }, [mcpTool, mcpScope]);

  // MCP 설치 핸들러
  const installMcp = (entry: McpEntry) => {
    setMcpLoading(prev => ({ ...prev, [entry.name]: true }));
    fetch(`${API_BASE}/api/mcp/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: mcpTool, scope: mcpScope,
        name: entry.name, package: entry.package,
        requiresEnv: entry.requiresEnv ?? [],
      }),
    })
      .then(res => res.json())
      .then(data => { setMcpMsg(data.message ?? ''); fetchMcpInstalled(); })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [entry.name]: false })));
  };

  // MCP 제거 핸들러
  const uninstallMcp = (name: string) => {
    setMcpLoading(prev => ({ ...prev, [name]: true }));
    fetch(`${API_BASE}/api/mcp/uninstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: mcpTool, scope: mcpScope, name }),
    })
      .then(res => res.json())
      .then(data => { setMcpMsg(data.message ?? ''); fetchMcpInstalled(); })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [name]: false })));
  };

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
  const [currentPath, setCurrentPath] = useState("D:/vibe-coding");
  const [initialConfigLoaded, setInitialConfigLoaded] = useState(false);
  const [items, setItems] = useState<{ name: string, path: string, isDir: boolean }[]>([]);

  // 초기 설정 로드 (마지막 경로 기억)
  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then(res => res.json())
      .then(data => {
        if (data.last_path) {
          setCurrentPath(data.last_path);
        }
        setInitialConfigLoaded(true);
      })
      .catch(() => setInitialConfigLoaded(true));
  }, []);

  // 경로 변경 시 서버에 저장
  useEffect(() => {
    if (initialConfigLoaded && currentPath) {
      fetch(`${API_BASE}/api/config/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ last_path: currentPath })
      }).catch(() => {});
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

  // currentPath 변경 시 Git 감시 경로도 동기화 + 트리 초기화
  useEffect(() => { setGitPath(currentPath); }, [currentPath]);
  useEffect(() => { setTreeExpanded({}); setTreeChildren({}); }, [currentPath]);

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
    const urlMap: Record<string, string> = {
      gemini: `${API_BASE}/api/install-gemini-cli`,
      claude: `${API_BASE}/api/install-claude-code`,
      codex:  `${API_BASE}/api/install-codex-cli`,
    };
    const url = urlMap[tool] ?? `${API_BASE}/api/install-claude-code`;
    fetch(url).then(res => res.json()).then(data => alert(data.message)).catch(err => alert(err));
    setActiveMenu(null);
  };

  // Vibe Coding Codex를 Gemini CLI / Claude Desktop MCP 서버로 등록합니다.
  const registerCodexToAI = () => {
    setActiveMenu(null);
    fetch(`${API_BASE}/api/register-codex-to-ai`)
      .then(res => res.json())
      .then(data => alert(data.message))
      .catch(err => alert('등록 실패: ' + err));
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
        <Activity className="w-3.5 h-3.5 text-primary mx-1" />
        <span className="text-[10px] font-bold text-white/90 mr-1 tracking-tight">바이브 코딩</span>
        <span className="text-[9px] bg-primary/20 text-primary px-1 py-0 rounded border border-primary/30 mr-2 font-mono">v3.3.0</span>
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
                <button onClick={() => installTool('codex')} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-[#f39c12]" />
                  <span>Codex CLI 설치 (npm -g)</span>
                </button>
                <button onClick={() => registerCodexToAI()} className="w-full text-left px-4 py-1.5 hover:bg-primary/20 flex items-center justify-between group">
                  <div className="flex items-center gap-2">
                    <Package className="w-3.5 h-3.5 text-[#f39c12]" />
                    <span>Codex → AI 도구에 등록 (MCP)</span>
                  </div>
                  <span className="text-[9px] text-white/30 group-hover:text-white/60 font-mono">Gemini·Claude</span>
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
                <button onClick={() => { alert("바이브 코딩(Vibe Coding) v1.0.0\n하이브 마인드 중앙 지휘소"); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
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
          {/* 하이브 오케스트레이터 탭 — 경고 수 배지 */}
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
                {memory.length > 9 ? '9+' : memory.length}
              </span>
            )}
          </button>
          {/* Git 감시 탭 — 충돌 파일 수 배지 표시 */}
          <button onClick={() => { setActiveTab('git'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'git' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`}>
            <GitBranch className="w-6 h-6" />
            {conflictCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none animate-pulse">
                {conflictCount > 9 ? '9+' : conflictCount}
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
            <span className="flex items-center gap-1.5"><ChevronDown className="w-3.5 h-3.5" />{activeTab === 'explorer' ? 'Explorer' : activeTab === 'search' ? 'Search' : activeTab === 'messages' ? '메시지 채널' : activeTab === 'tasks' ? '태스크 보드' : activeTab === 'memory' ? '공유 메모리' : activeTab === 'git' ? 'Git 감시' : activeTab === 'mcp' ? 'MCP 관리자' : 'Hive Mind'}</span>
            <button onClick={() => setIsSidebarOpen(false)} className="hover:bg-white/10 p-0.5 rounded transition-colors"><X className="w-4 h-4" /></button>
          </div>

          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            {activeTab === 'messages' ? (
              /* ── 메시지 채널 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 메시지 목록 (최신순 — 역순 표시) */}
                <div className="flex-1 overflow-y-auto space-y-2 custom-scrollbar">
                  {messages.length === 0 ? (
                    <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                      <MessageSquare className="w-7 h-7 opacity-20" />
                      아직 메시지가 없습니다
                    </div>
                  ) : (
                    [...messages].reverse().map(msg => (
                      <div key={msg.id} className="p-2 rounded border border-white/10 bg-white/2 text-[10px] hover:border-white/20 transition-colors">
                        {/* 발신자 → 수신자 + 타입 배지 */}
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-1 font-mono font-bold">
                            <span className="text-success">{msg.from}</span>
                            <span className="text-white/30 font-normal">→</span>
                            <span className="text-accent">{msg.to}</span>
                          </div>
                          <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                            msg.type === 'handoff'       ? 'bg-yellow-500/20 text-yellow-400' :
                            msg.type === 'request'       ? 'bg-blue-500/20 text-blue-400' :
                            msg.type === 'task_complete' ? 'bg-green-500/20 text-green-400' :
                            msg.type === 'warning'       ? 'bg-red-500/20 text-red-400' :
                            'bg-white/10 text-white/50'
                          }`}>{msg.type}</span>
                        </div>
                        {/* 메시지 본문 */}
                        <p className="text-[#cccccc] leading-relaxed break-words whitespace-pre-wrap">{msg.content}</p>
                        {/* 타임스탬프 */}
                        <div className="text-[#858585] mt-1 text-[9px] font-mono">{msg.timestamp.replace('T', ' ')}</div>
                      </div>
                    ))
                  )}
                </div>

                {/* 메시지 작성 폼 */}
                <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
                  {/* 발신자 → 수신자 선택 */}
                  <div className="flex gap-1 items-center">
                    <select value={msgFrom} onChange={e => setMsgFrom(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
                      <option value="claude">Claude</option>
                      <option value="gemini">Gemini</option>
                      <option value="system">System</option>
                    </select>
                    <span className="text-white/30 text-[10px] px-0.5">→</span>
                    <select value={msgTo} onChange={e => setMsgTo(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
                      <option value="all">All</option>
                      <option value="claude">Claude</option>
                      <option value="gemini">Gemini</option>
                    </select>
                  </div>
                  {/* 메시지 유형 선택 */}
                  <select value={msgType} onChange={e => setMsgType(e.target.value)} className="w-full bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
                    <option value="info">ℹ️ 정보 공유</option>
                    <option value="handoff">🤝 핸드오프 (작업 위임)</option>
                    <option value="request">📋 작업 요청</option>
                    <option value="task_complete">✅ 완료 알림</option>
                    <option value="warning">⚠️ 경고</option>
                  </select>
                  {/* 메시지 본문 입력 */}
                  <textarea
                    value={msgContent}
                    onChange={e => setMsgContent(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        // 엔터 키 입력 시 즉시 기본 줄바꿈 동작을 차단합니다.
                        e.preventDefault();

                        // 한글 조합 중이 아닐 때만 명령어를 전송합니다.
                        if (!e.nativeEvent.isComposing && msgContent.trim()) {
                          sendMessage();
                          // 전송 후 입력창을 비울 때 레이스 컨디션 방지를 위해 지연 처리
                          setTimeout(() => setMsgContent(''), 0);
                        }
                      }
                    }}
                    placeholder="메시지 입력... (Enter: 전송, Shift+Enter: 줄바꿈)"
                    rows={3}
                    className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors resize-none"
                  />
                  <button
                    onClick={sendMessage}
                    disabled={!msgContent.trim()}
                    className="w-full py-1.5 bg-primary/80 hover:bg-primary disabled:opacity-30 disabled:cursor-not-allowed text-white rounded text-[10px] font-bold transition-colors"
                  >
                    전송 (Enter)
                  </button>
                </div>
              </div>
            ) : activeTab === 'tasks' ? (
              /* ── 태스크 보드 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 상태 필터 탭 */}
                <div className="flex gap-1 shrink-0">
                  {(['all', 'pending', 'in_progress', 'done'] as const).map(s => {
                    const label = s === 'all' ? '전체' : s === 'pending' ? '할 일' : s === 'in_progress' ? '진행' : '완료';
                    const count = s === 'all' ? tasks.length : tasks.filter(t => t.status === s).length;
                    return (
                      <button key={s} onClick={() => setTaskFilter(s)} className={`flex-1 py-1 rounded text-[9px] font-bold transition-colors ${taskFilter === s ? 'bg-primary text-white' : 'bg-white/5 text-[#858585] hover:text-white'}`}>
                        {label}{count > 0 && ` (${count})`}
                      </button>
                    );
                  })}
                </div>

                {/* 작업 목록 */}
                <div className="flex-1 overflow-y-auto space-y-1.5 custom-scrollbar">
                  {tasks.filter(t => taskFilter === 'all' || t.status === taskFilter).length === 0 ? (
                    <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                      <ClipboardList className="w-7 h-7 opacity-20" />
                      작업이 없습니다
                    </div>
                  ) : (
                    tasks
                      .filter(t => taskFilter === 'all' || t.status === taskFilter)
                      .slice().reverse()
                      .map(task => {
                        const priorityDot =
                          task.priority === 'high' ? '🔴' : task.priority === 'medium' ? '🟡' : '🟢';
                        const statusLabel =
                          task.status === 'pending' ? '할 일' : task.status === 'in_progress' ? '진행 중' : '완료';
                        return (
                          <div key={task.id} className={`p-2 rounded border text-[10px] transition-colors ${task.status === 'done' ? 'border-white/5 opacity-50' : 'border-white/10 hover:border-white/20'}`}>
                            {/* 제목 + 우선순위 */}
                            <div className="flex items-start gap-1.5 mb-1">
                              <span className="text-[11px] shrink-0">{priorityDot}</span>
                              <span className={`font-bold flex-1 break-words leading-tight ${task.status === 'done' ? 'line-through text-[#858585]' : 'text-[#cccccc]'}`}>{task.title}</span>
                            </div>
                            {/* 설명 (있을 경우) */}
                            {task.description && (
                              <p className="text-[#858585] text-[9px] mb-1.5 leading-relaxed pl-4">{task.description}</p>
                            )}
                            {/* 담당자 + 상태 */}
                            <div className="flex items-center justify-between pl-4 mb-1.5">
                              <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold font-mono ${
                                task.assigned_to === 'claude'  ? 'bg-green-500/15 text-green-400' :
                                task.assigned_to === 'gemini' ? 'bg-blue-500/15 text-blue-400' :
                                'bg-white/10 text-white/50'
                              }`}>{task.assigned_to}</span>
                              <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${
                                task.status === 'pending'     ? 'bg-white/10 text-[#858585]' :
                                task.status === 'in_progress' ? 'bg-primary/20 text-primary' :
                                'bg-green-500/20 text-green-400'
                              }`}>{statusLabel}</span>
                            </div>
                            {/* 액션 버튼 */}
                            <div className="flex gap-1 pl-4">
                              {task.status === 'pending' && (
                                <button onClick={() => updateTask(task.id, { status: 'in_progress' })} className="flex-1 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[9px] font-bold transition-colors">▶ 시작</button>
                              )}
                              {task.status === 'in_progress' && (
                                <>
                                  <button onClick={() => updateTask(task.id, { status: 'done' })} className="flex-1 py-0.5 bg-green-500/20 hover:bg-green-500/40 text-green-400 rounded text-[9px] font-bold transition-colors">✅ 완료</button>
                                  <button onClick={() => updateTask(task.id, { status: 'pending' })} className="px-1.5 py-0.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[9px] transition-colors">↩</button>
                                </>
                              )}
                              {task.status === 'done' && (
                                <button onClick={() => updateTask(task.id, { status: 'pending' })} className="flex-1 py-0.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[9px] transition-colors">↩ 다시</button>
                              )}
                              <button onClick={() => deleteTask(task.id)} className="px-1.5 py-0.5 bg-red-500/10 hover:bg-red-500/25 text-red-400 rounded text-[9px] transition-colors" title="삭제">🗑️</button>
                            </div>
                          </div>
                        );
                      })
                  )}
                </div>

                {/* 새 작업 추가 */}
                {showTaskForm ? (
                  <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
                    <input
                      type="text"
                      value={newTaskTitle}
                      onChange={e => setNewTaskTitle(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') createTask(); if (e.key === 'Escape') setShowTaskForm(false); }}
                      placeholder="작업 제목 (필수)"
                      autoFocus
                      className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
                    />
                    <input
                      type="text"
                      value={newTaskDesc}
                      onChange={e => setNewTaskDesc(e.target.value)}
                      placeholder="상세 설명 (선택)"
                      className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
                    />
                    <div className="flex gap-1">
                      <select value={newTaskAssignee} onChange={e => setNewTaskAssignee(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer">
                        <option value="all">All</option>
                        <option value="claude">Claude</option>
                        <option value="gemini">Gemini</option>
                      </select>
                      <select value={newTaskPriority} onChange={e => setNewTaskPriority(e.target.value as 'high' | 'medium' | 'low')} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer">
                        <option value="high">🔴 높음</option>
                        <option value="medium">🟡 보통</option>
                        <option value="low">🟢 낮음</option>
                      </select>
                    </div>
                    <div className="flex gap-1">
                      <button onClick={createTask} disabled={!newTaskTitle.trim()} className="flex-1 py-1.5 bg-primary/80 hover:bg-primary disabled:opacity-30 text-white rounded text-[10px] font-bold transition-colors">추가</button>
                      <button onClick={() => setShowTaskForm(false)} className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[10px] transition-colors">취소</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setShowTaskForm(true)} className="shrink-0 w-full py-1.5 border border-dashed border-white/15 hover:border-primary/40 hover:bg-primary/5 rounded text-[10px] text-[#858585] hover:text-primary transition-colors flex items-center justify-center gap-1.5">
                    <Plus className="w-3 h-3" /> 새 작업 추가
                  </button>
                )}
              </div>
            ) : activeTab === 'memory' ? (
              /* ── 공유 메모리 패널 (SQLite 기반) ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 검색 입력 */}
                <div className="relative shrink-0">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#858585]" />
                  <input
                    type="text"
                    value={memSearch}
                    onChange={e => setMemSearch(e.target.value)}
                    placeholder="키 / 내용 / 태그 검색..."
                    className="w-full bg-[#1e1e1e] border border-white/10 rounded pl-6 pr-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
                  />
                </div>
                {/* 항목 수 요약 */}
                <div className="text-[9px] text-[#858585] shrink-0 px-0.5">
                  총 {memory.length}개 항목{memSearch && ` (검색: "${memSearch}")`}
                </div>

                {/* 메모리 항목 목록 */}
                <div className="flex-1 overflow-y-auto space-y-1.5 custom-scrollbar">
                  {memory.length === 0 ? (
                    <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                      <Brain className="w-7 h-7 opacity-20" />
                      {memSearch ? '검색 결과 없음' : '저장된 메모리 없음'}
                    </div>
                  ) : (
                    memory.map(entry => (
                      <div key={entry.key} className="p-2 rounded border border-white/10 bg-white/2 text-[10px] hover:border-white/20 transition-colors group">
                        {/* 키 + 액션 버튼 */}
                        <div className="flex items-start justify-between gap-1 mb-1">
                          <span className="font-mono font-bold text-cyan-400 text-[10px] break-all leading-tight">{entry.key}</span>
                          <div className="flex gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button onClick={() => startEditMemory(entry)} className="px-1.5 py-0.5 bg-white/5 hover:bg-primary/20 rounded text-[9px] text-[#858585] hover:text-primary transition-colors">✏️</button>
                            <button onClick={() => deleteMemory(entry.key)} className="px-1.5 py-0.5 bg-white/5 hover:bg-red-500/20 rounded text-[9px] text-[#858585] hover:text-red-400 transition-colors">🗑️</button>
                          </div>
                        </div>
                        {/* 제목 (키와 다를 경우만) */}
                        {entry.title && entry.title !== entry.key && (
                          <p className="text-[#cccccc] font-semibold text-[10px] mb-0.5">{entry.title}</p>
                        )}
                        {/* 내용 미리보기 */}
                        <p className="text-[#969696] text-[9px] leading-relaxed line-clamp-2 break-words">{entry.content}</p>
                        {/* 태그 + 작성자 + 날짜 */}
                        <div className="flex items-center flex-wrap gap-1 mt-1.5">
                          {entry.tags.map(tag => (
                            <span key={tag} onClick={() => setMemSearch(tag)} className="px-1 py-0.5 bg-cyan-500/10 text-cyan-400 rounded text-[8px] font-mono cursor-pointer hover:bg-cyan-500/20 transition-colors">#{tag}</span>
                          ))}
                          <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ml-auto ${entry.author === 'claude' ? 'bg-green-500/15 text-green-400' : entry.author === 'gemini' ? 'bg-blue-500/15 text-blue-400' : 'bg-white/10 text-white/50'}`}>{entry.author}</span>
                          <span className="text-[#858585] text-[8px] font-mono">{entry.updated_at.slice(5, 16).replace('T', ' ')}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>

                {/* 저장 폼 또는 추가 버튼 */}
                {showMemForm ? (
                  <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
                    <div className="text-[9px] text-[#858585] font-bold uppercase tracking-wider">
                      {editingMemKey ? `✏️ 수정: ${editingMemKey}` : '+ 새 메모리 항목'}
                    </div>
                    <input
                      type="text"
                      value={memKey}
                      onChange={e => setMemKey(e.target.value)}
                      placeholder="키 (예: db_schema, auth_method)"
                      disabled={!!editingMemKey}
                      className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-mono"
                    />
                    <input
                      type="text"
                      value={memTitle}
                      onChange={e => setMemTitle(e.target.value)}
                      placeholder="제목 (선택, 비워두면 키 사용)"
                      className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors"
                    />
                    <textarea
                      value={memContent}
                      onChange={e => setMemContent(e.target.value)}
                      placeholder="내용 (에이전트가 공유할 정보)"
                      rows={4}
                      className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors resize-none"
                    />
                    <div className="flex gap-1">
                      <input
                        type="text"
                        value={memTags}
                        onChange={e => setMemTags(e.target.value)}
                        placeholder="태그 (쉼표 구분)"
                        className="flex-1 bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-cyan-500 text-white transition-colors"
                      />
                      <select value={memAuthor} onChange={e => setMemAuthor(e.target.value)} className="bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer">
                        <option value="claude">Claude</option>
                        <option value="gemini">Gemini</option>
                        <option value="user">User</option>
                      </select>
                    </div>
                    <div className="flex gap-1">
                      <button onClick={saveMemory} disabled={!memKey.trim() || !memContent.trim()} className="flex-1 py-1.5 bg-cyan-500/80 hover:bg-cyan-500 disabled:opacity-30 text-black rounded text-[10px] font-black transition-colors">저장</button>
                      <button onClick={() => { setShowMemForm(false); setEditingMemKey(null); setMemKey(''); setMemTitle(''); setMemContent(''); setMemTags(''); }} className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[10px] transition-colors">취소</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setShowMemForm(true)} className="shrink-0 w-full py-1.5 border border-dashed border-white/15 hover:border-cyan-500/40 hover:bg-cyan-500/5 rounded text-[10px] text-[#858585] hover:text-cyan-400 transition-colors flex items-center justify-center gap-1.5">
                    <Plus className="w-3 h-3" /> 새 메모리 항목 추가
                  </button>
                )}
              </div>
            ) : activeTab === 'hive' ? (
              /* ── 오케스트레이터 대시보드 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 헤더: 실행 버튼 + 마지막 실행 시각 */}
                <div className="flex items-center justify-between shrink-0">
                  <div className="text-[9px] text-[#858585] font-mono">
                    {orchLastRun ? `마지막 실행: ${orchLastRun}` : '자동 조율 엔진'}
                  </div>
                  <button
                    onClick={runOrchestrator}
                    disabled={orchRunning}
                    className="flex items-center gap-1 px-2 py-1 bg-primary/20 hover:bg-primary/40 disabled:opacity-40 text-primary rounded text-[9px] font-bold transition-colors"
                  >
                    <Play className="w-3 h-3" />
                    {orchRunning ? '실행 중...' : '지금 실행'}
                  </button>
                </div>

                {!orchStatus ? (
                  <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                    <Bot className="w-7 h-7 opacity-20" />
                    오케스트레이터 연결 중...
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-3">

                    {/* 경고 배너 */}
                    {orchStatus.warnings && orchStatus.warnings.length > 0 && (
                      <div className="p-2 rounded border border-red-500/40 bg-red-500/5">
                        <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-red-400">
                          <AlertTriangle className="w-3.5 h-3.5" /> 경고 ({orchStatus.warnings.length})
                        </div>
                        {orchStatus.warnings.map((w, i) => (
                          <div key={i} className="text-[9px] text-red-300 pl-3 py-0.5">⚠ {w}</div>
                        ))}
                      </div>
                    )}

                    {/* 에이전트 상태 카드 */}
                    <div className="p-2 rounded border border-white/10">
                      <div className="text-[9px] font-bold text-[#969696] mb-1.5 flex items-center gap-1">
                        <Bot className="w-3 h-3" /> 에이전트 상태
                      </div>
                      {Object.entries(orchStatus.agent_status ?? {}).map(([agent, st]) => {
                        const dotColor = st.state === 'active' ? 'text-green-400' : st.state === 'idle' ? 'text-yellow-400' : 'text-[#858585]';
                        const stateLabel = st.state === 'active' ? '활성' : st.state === 'idle' ? `유휴 ${st.idle_sec ? Math.floor(st.idle_sec / 60) + '분' : ''}` : '미확인';
                        const taskDist = orchStatus.task_distribution?.[agent] ?? { pending: 0, in_progress: 0, done: 0 };
                        return (
                          <div key={agent} className="flex items-center gap-2 py-1 border-b border-white/5 last:border-0">
                            <CircleDot className={`w-3 h-3 shrink-0 ${dotColor}`} />
                            <span className={`font-mono font-bold text-[10px] w-12 shrink-0 ${agent === 'claude' ? 'text-green-400' : 'text-blue-400'}`}>{agent}</span>
                            <span className={`text-[9px] ${dotColor}`}>{stateLabel}</span>
                            <div className="ml-auto flex gap-1.5 text-[8px] font-mono">
                              <span className="text-[#858585]">P:{taskDist.pending}</span>
                              <span className="text-primary">W:{taskDist.in_progress}</span>
                              <span className="text-green-400">D:{taskDist.done}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* 태스크 분배 전체 요약 */}
                    {orchStatus.task_distribution?.all && (
                      <div className="p-2 rounded border border-white/10">
                        <div className="text-[9px] font-bold text-[#969696] mb-1">미할당 태스크 (all)</div>
                        <div className="flex gap-3 text-[9px] font-mono">
                          <span className="text-[#858585]">대기: {orchStatus.task_distribution.all.pending}</span>
                          <span className="text-primary">진행: {orchStatus.task_distribution.all.in_progress}</span>
                          <span className="text-green-400">완료: {orchStatus.task_distribution.all.done}</span>
                        </div>
                      </div>
                    )}

                    {/* 최근 오케스트레이터 액션 로그 */}
                    {orchStatus.recent_actions && orchStatus.recent_actions.length > 0 ? (
                      <div className="p-2 rounded border border-white/10">
                        <div className="text-[9px] font-bold text-[#969696] mb-1.5">최근 자동 액션</div>
                        {orchStatus.recent_actions.slice(0, 8).map((act, i) => {
                          const actionColor = act.action === 'auto_assign' ? 'text-green-400' : act.action === 'idle_agent' ? 'text-yellow-400' : act.action.includes('overload') ? 'text-red-400' : 'text-[#858585]';
                          return (
                            <div key={i} className="flex items-start gap-1.5 py-0.5 hover:bg-white/3 rounded px-1">
                              <span className={`text-[8px] font-mono shrink-0 mt-0.5 ${actionColor}`}>{act.action}</span>
                              <span className="text-[9px] text-[#cccccc] flex-1 break-words leading-tight">{act.detail}</span>
                              <span className="text-[8px] text-[#858585] shrink-0 font-mono">{act.timestamp?.slice(11, 16)}</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="p-2 rounded border border-white/5 text-center text-[9px] text-[#858585] italic">
                        자동 액션 기록 없음 — "지금 실행"으로 첫 조율을 시작하세요
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : activeTab === 'git' ? (
              /* ── Git 실시간 감시 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 경로 입력 (모니터링 대상 변경) */}
                <input
                  type="text"
                  value={gitPath}
                  onChange={e => setGitPath(e.target.value)}
                  onBlur={() => setGitPath(gitPath.trim() || currentPath)}
                  placeholder="Git 저장소 경로..."
                  className="w-full bg-[#1e1e1e] border border-white/10 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors font-mono shrink-0"
                />

                {!gitStatus || !gitStatus.is_git_repo ? (
                  <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                    <GitBranch className="w-7 h-7 opacity-20" />
                    {gitStatus?.error ? gitStatus.error : 'Git 저장소가 아닙니다'}
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-3">
                    {/* 브랜치 + ahead/behind */}
                    <div className="p-2 rounded border border-white/10 bg-white/2">
                      <div className="flex items-center gap-2 mb-1.5">
                        <GitBranch className="w-3.5 h-3.5 text-primary shrink-0" />
                        <span className="text-[11px] font-bold text-primary font-mono">{gitStatus.branch}</span>
                        {gitStatus.ahead > 0 && (
                          <span className="flex items-center gap-0.5 text-[9px] text-green-400 font-bold ml-auto">
                            <ArrowUp className="w-3 h-3" />{gitStatus.ahead}
                          </span>
                        )}
                        {gitStatus.behind > 0 && (
                          <span className="flex items-center gap-0.5 text-[9px] text-orange-400 font-bold ml-auto">
                            <ArrowDown className="w-3 h-3" />{gitStatus.behind}
                          </span>
                        )}
                      </div>
                      {/* 요약 통계 행 */}
                      <div className="flex gap-2 text-[9px] font-mono">
                        <span className="text-green-400">S:{gitStatus.staged.length}</span>
                        <span className="text-yellow-400">M:{gitStatus.unstaged.length}</span>
                        <span className="text-[#858585]">?:{gitStatus.untracked.length}</span>
                        {gitStatus.conflicts.length > 0 && (
                          <span className="text-red-400 font-black animate-pulse">⚠ C:{gitStatus.conflicts.length}</span>
                        )}
                      </div>
                    </div>

                    {/* 충돌 파일 (최우선 경고) */}
                    {gitStatus.conflicts.length > 0 && (
                      <div className="p-2 rounded border border-red-500/40 bg-red-500/5">
                        <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-red-400">
                          <AlertTriangle className="w-3.5 h-3.5" /> 충돌 파일 ({gitStatus.conflicts.length})
                        </div>
                        {gitStatus.conflicts.map(f => (
                          <div key={f} className="text-[9px] font-mono text-red-300 pl-4 py-0.5 truncate">{f}</div>
                        ))}
                      </div>
                    )}

                    {/* 스테이징된 파일 */}
                    {gitStatus.staged.length > 0 && (
                      <div className="p-2 rounded border border-green-500/20 bg-green-500/3">
                        <div className="text-[9px] font-bold text-green-400 mb-1">스테이징됨 ({gitStatus.staged.length})</div>
                        {gitStatus.staged.slice(0, 8).map(f => (
                          <div key={f} className="text-[9px] font-mono text-green-300/70 pl-2 py-0.5 truncate">+{f}</div>
                        ))}
                        {gitStatus.staged.length > 8 && <div className="text-[8px] text-green-400/50 pl-2">... +{gitStatus.staged.length - 8}개 더</div>}
                      </div>
                    )}

                    {/* 수정됨 (unstaged) */}
                    {gitStatus.unstaged.length > 0 && (
                      <div className="p-2 rounded border border-yellow-500/20 bg-yellow-500/3">
                        <div className="text-[9px] font-bold text-yellow-400 mb-1">수정됨 (unstaged) ({gitStatus.unstaged.length})</div>
                        {gitStatus.unstaged.slice(0, 8).map(f => (
                          <div key={f} className="text-[9px] font-mono text-yellow-300/70 pl-2 py-0.5 truncate">~{f}</div>
                        ))}
                        {gitStatus.unstaged.length > 8 && <div className="text-[8px] text-yellow-400/50 pl-2">... +{gitStatus.unstaged.length - 8}개 더</div>}
                      </div>
                    )}

                    {/* 미추적 파일 */}
                    {gitStatus.untracked.length > 0 && (
                      <div className="p-2 rounded border border-white/10">
                        <div className="text-[9px] font-bold text-[#858585] mb-1">미추적 ({gitStatus.untracked.length})</div>
                        {gitStatus.untracked.slice(0, 5).map(f => (
                          <div key={f} className="text-[9px] font-mono text-[#858585] pl-2 py-0.5 truncate">?{f}</div>
                        ))}
                        {gitStatus.untracked.length > 5 && <div className="text-[8px] text-[#858585]/50 pl-2">... +{gitStatus.untracked.length - 5}개 더</div>}
                      </div>
                    )}

                    {/* 최근 커밋 로그 */}
                    {gitLog.length > 0 && (
                      <div className="p-2 rounded border border-white/10">
                        <div className="flex items-center gap-1.5 mb-1.5 text-[9px] font-bold text-[#969696]">
                          <GitCommitIcon className="w-3 h-3" /> 최근 커밋
                        </div>
                        {gitLog.slice(0, 8).map(commit => (
                          <div key={commit.hash} className="flex items-start gap-1.5 py-0.5 hover:bg-white/3 rounded px-1 transition-colors">
                            <span className="font-mono text-[8px] text-primary shrink-0 mt-0.5">{commit.hash}</span>
                            <span className="text-[9px] text-[#cccccc] flex-1 truncate leading-tight">{commit.message}</span>
                            <span className="text-[8px] text-[#858585] shrink-0 font-mono">{commit.date.replace(' ago', '')}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : activeTab === 'mcp' ? (
              /* ── MCP 관리자 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 도구 탭 선택: Claude Code / Gemini CLI */}
                <div className="flex gap-1 shrink-0">
                  {(['claude', 'gemini'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => setMcpTool(t)}
                      className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors ${mcpTool === t ? 'bg-primary text-white' : 'bg-white/5 text-[#858585] hover:text-white'}`}
                    >
                      {t === 'claude' ? 'Claude Code' : 'Gemini CLI'}
                    </button>
                  ))}
                </div>
                {/* 범위 탭 선택: 전역 / 프로젝트 */}
                <div className="flex gap-1 shrink-0">
                  {(['global', 'project'] as const).map(s => (
                    <button
                      key={s}
                      onClick={() => setMcpScope(s)}
                      className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors ${mcpScope === s ? 'bg-accent/80 text-white' : 'bg-white/5 text-[#858585] hover:text-white'}`}
                    >
                      {s === 'global' ? '전역 (Global)' : '프로젝트'}
                    </button>
                  ))}
                </div>

                {/* 마지막 작업 결과 메시지 */}
                {mcpMsg && (
                  <div className="text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1 font-mono truncate shrink-0" title={mcpMsg}>
                    {mcpMsg}
                  </div>
                )}

                {/* MCP 카드 목록 */}
                <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
                  {mcpCatalog.length === 0 ? (
                    <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                      <Package className="w-7 h-7 opacity-20" />
                      카탈로그 로딩 중...
                    </div>
                  ) : (
                    mcpCatalog.map(entry => {
                      const isInstalled = mcpInstalled.includes(entry.name);
                      const isLoading = mcpLoading[entry.name] ?? false;
                      // 카테고리별 색상
                      const catColor: Record<string, string> = {
                        '문서': 'bg-blue-500/20 text-blue-300',
                        '개발': 'bg-orange-500/20 text-orange-300',
                        '검색': 'bg-yellow-500/20 text-yellow-300',
                        'AI':   'bg-purple-500/20 text-purple-300',
                        '브라우저': 'bg-green-500/20 text-green-300',
                        'DB':   'bg-red-500/20 text-red-300',
                      };
                      return (
                        <div key={entry.name} className={`p-2 rounded border transition-colors ${isInstalled ? 'border-green-500/30 bg-green-500/5' : 'border-white/10 bg-white/2 hover:border-white/20'}`}>
                          {/* 이름 + 카테고리 배지 + 설치 아이콘 */}
                          <div className="flex items-center gap-1.5 mb-0.5">
                            {isInstalled
                              ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />
                              : <Circle className="w-3.5 h-3.5 text-[#555] shrink-0" />
                            }
                            <span className="text-[11px] font-bold text-white flex-1 truncate">{entry.name}</span>
                            <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${catColor[entry.category] ?? 'bg-white/10 text-white/50'}`}>
                              {entry.category}
                            </span>
                          </div>
                          {/* 설명 */}
                          <p className="text-[9px] text-[#858585] pl-5 mb-1.5 leading-tight">{entry.description}</p>
                          {/* 환경변수 안내 */}
                          {entry.requiresEnv && entry.requiresEnv.length > 0 && (
                            <p className="text-[8px] text-yellow-400/70 pl-5 mb-1.5 font-mono">
                              ENV: {entry.requiresEnv.join(', ')}
                            </p>
                          )}
                          {/* 설치 / 제거 버튼 */}
                          <div className="pl-5">
                            {isInstalled ? (
                              <button
                                onClick={() => uninstallMcp(entry.name)}
                                disabled={isLoading}
                                className="text-[9px] font-bold px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 transition-colors"
                              >
                                {isLoading ? '처리 중...' : '제거'}
                              </button>
                            ) : (
                              <button
                                onClick={() => installMcp(entry)}
                                disabled={isLoading}
                                className="text-[9px] font-bold px-2 py-0.5 rounded bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
                              >
                                {isLoading ? '처리 중...' : '설치'}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
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
                    value={drives.find(d => currentPath.startsWith(d)) || currentPath}
                    onChange={(e) => setCurrentPath(e.target.value)}
                    className="flex-1 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded px-2 py-1.5 text-xs focus:outline-none transition-all cursor-pointer"
                  >
                    <option value="D:/vibe-coding">vibe-coding</option>
                    {drives.map(drive => <option key={drive} value={drive}>{drive}</option>)}
                  </select>
                  <button
                    onClick={() => setTreeMode(v => !v)}
                    className={`p-1.5 rounded border text-[10px] font-bold transition-all shrink-0 ${treeMode ? 'bg-primary/20 border-primary/40 text-primary' : 'bg-[#3c3c3c] border-white/10 text-[#858585] hover:text-white'}`}
                    title={treeMode ? '플랫 뷰로 전환' : '트리 뷰로 전환'}
                  >
                    {treeMode ? '≡' : '⊞'}
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto space-y-0.5 custom-scrollbar border-t border-white/5 pt-2">
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
                      />
                    ))
                  ) : (
                    /* 플랫 뷰 (기존) */
                    items.map(item => (
                      <div key={item.path} className={`group flex items-center gap-0 px-2 py-0.5 rounded text-xs transition-colors relative ${selectedPath === item.path ? 'bg-primary/20 border-l-2 border-primary' : 'hover:bg-[#2a2d2e]'}`}>
                        <button
                          onClick={() => handleFileClick(item)}
                          className={`flex-1 flex items-center gap-2 py-1 overflow-hidden ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] font-medium'}`}
                        >
                          {item.isDir ? <VscFolder className="w-4 h-4 text-[#dcb67a] shrink-0" /> : getFileIcon(item.name)}
                          <span className="truncate">{item.name}</span>
                        </button>
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
                          className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all ml-auto shrink-0"
                          title="경로 복사"
                        >
                          <ClipboardList className="w-3 h-3" />
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
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

          {/* Terminals Area */}
          <main className="flex-1 p-2 overflow-hidden bg-[#1e1e1e]">
            {/* 터미널 그리드: 1→1열, 2→2열, 3→3열, 4→가로4열, 2x2→2×2격자, 6→3×2격자, 8→4×2격자 */}
            <div className={`h-full w-full gap-2 grid ${
              layoutMode === '1' ? 'grid-cols-1' :
              layoutMode === '2' ? 'grid-cols-2' :
              layoutMode === '3' ? 'grid-cols-3' :
              layoutMode === '4' ? 'grid-cols-4' :
              layoutMode === '2x2' ? 'grid-cols-2 grid-rows-2' :
              layoutMode === '6' ? 'grid-cols-3 grid-rows-2' :
              'grid-cols-4 grid-rows-2'
            }`}>
              {slots.map(slotId => (
                <TerminalSlot key={slotId} slotId={slotId} logs={logs} currentPath={currentPath} terminalCount={terminalCount} locks={locks} messages={messages} tasks={tasks} />
              ))}
            </div>
          </main>
        </div>
      </div>

      {/* Quick View Floating Panels */}
      {openFiles.map((file, idx) => (
        <FloatingWindow key={file.id} file={file} idx={idx} bringToFront={bringToFront} closeFile={closeFile} />
      ))}
    </div>
  )
}

// VS코드 스타일 줄 번호 뷰어 컴포넌트
// - 우측 정렬 번호 + 세로 구분선 + 호버 시 행 하이라이트
function CodeWithLineNumbers({ content, fontSize = '12px' }: { content: string; fontSize?: string }) {
  const lines = content.split('\n');
  const gutterWidth = String(lines.length).length;
  return (
    <div className="font-mono leading-relaxed" style={{ fontSize }}>
      {lines.map((line, i) => (
        <div key={i} className="flex hover:bg-white/5 group">
          {/* 줄 번호 거터: 우측 정렬, 선택 불가, 구분선 포함 */}
          <span
            className="shrink-0 text-right pr-3 select-none text-[#858585] group-hover:text-[#aaaaaa] border-r border-white/10 mr-3 transition-colors"
            style={{ minWidth: `${gutterWidth + 1}ch` }}
          >
            {i + 1}
          </span>
          {/* 코드 본문 */}
          <span className="flex-1 whitespace-pre text-[#cccccc]">{line}</span>
        </div>
      ))}
    </div>
  );
}

type TreeItem = { name: string; path: string; isDir: boolean };
function FileTreeNode({ item, depth, expanded, treeChildren, onToggle, onFileOpen }: {
  item: TreeItem; depth: number;
  expanded: Record<string, boolean>;
  treeChildren: Record<string, TreeItem[]>;
  onToggle: (path: string) => void;
  onFileOpen: (item: TreeItem) => void;
}) {
  const isOpen = expanded[item.path] || false;
  const kids = treeChildren[item.path] || [];
  const indent = depth * 12;
  if (item.isDir) {
    return (
      <div>
        <button
          onClick={() => onToggle(item.path)}
          style={{ paddingLeft: `${indent + 4}px` }}
          className="w-full flex items-center gap-1 py-0.5 pr-2 hover:bg-[#2a2d2e] rounded text-xs transition-colors text-[#cccccc]"
        >
          {isOpen
            ? <ChevronDown className="w-3 h-3 shrink-0 text-[#858585]" />
            : <ChevronRight className="w-3 h-3 shrink-0 text-[#858585]" />}
          {isOpen
            ? <VscFolderOpened className="w-4 h-4 text-[#dcb67a] shrink-0" />
            : <VscFolder className="w-4 h-4 text-[#dcb67a] shrink-0" />}
          <span className="truncate">{item.name}</span>
        </button>
        {isOpen && kids.length === 0 && (
          <div style={{ paddingLeft: `${indent + 28}px` }} className="py-0.5 text-[10px] text-[#858585] italic">비어 있음</div>
        )}
        {isOpen && kids.map(child => (
          <FileTreeNode key={child.path} item={child} depth={depth + 1}
            expanded={expanded} treeChildren={treeChildren}
            onToggle={onToggle} onFileOpen={onFileOpen} />
        ))}
      </div>
    );
  }
  return (
    <button
      onClick={() => onFileOpen(item)}
      style={{ paddingLeft: `${indent + 20}px` }}
      className="w-full flex items-center gap-2 py-0.5 pr-2 hover:bg-primary/20 rounded text-xs transition-colors text-white"
    >
      {getFileIcon(item.name)}
      <span className="truncate">{item.name}</span>
    </button>
  );
}

function FloatingWindow({ file, idx, bringToFront, closeFile }: { file: OpenFile, idx: number, bringToFront: (id: string) => void, closeFile: (id: string) => void }) {
  const [position, setPosition] = useState({ x: 100 + (idx * 30), y: 100 + (idx * 30) });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef({ x: 0, y: 0 });

  const handlePointerDown = (e: React.PointerEvent) => {
    setIsDragging(true);
    bringToFront(file.id);
    dragStartPos.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStartPos.current.x,
        y: e.clientY - dragStartPos.current.y
      });
    }
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    setIsDragging(false);
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return (
    <div 
      onPointerDown={() => bringToFront(file.id)}
      style={{ 
        zIndex: file.zIndex, 
        left: position.x, 
        top: position.y,
        resize: 'both', 
        overflow: 'hidden' 
      }}
      className="absolute w-[550px] min-w-[300px] h-[500px] min-h-[200px] bg-[#1e1e1e]/95 backdrop-blur-xl border border-white/20 shadow-2xl rounded-xl flex flex-col"
    >
      <div 
        className="h-10 bg-[#2d2d2d]/90 border-b border-white/10 flex items-center justify-between px-4 shrink-0 cursor-move select-none"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div className="flex items-center gap-2 text-[#cccccc] font-mono text-sm truncate pointer-events-none">
          {getFileIcon(file.name)}
          {file.name}
        </div>
        <button 
          onClick={(e) => { e.stopPropagation(); closeFile(file.id); }} 
          onPointerDownCapture={e => e.stopPropagation()}
          className="p-1 hover:bg-white/10 rounded text-[#cccccc] transition-colors cursor-pointer"
          title="Close"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
      <div 
        className="flex-1 overflow-auto bg-transparent relative custom-scrollbar"
        onPointerDownCapture={e => e.stopPropagation()}
      >
        {file.isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-[#858585] animate-pulse">Loading content...</div>
        ) : /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(file.name) ? (
          <div className="absolute inset-0 flex items-center justify-center p-4">
            <img
              src={`${API_BASE}/api/image-file?path=${encodeURIComponent(file.path)}`}
              alt={file.name}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        ) : (
          // VS코드 스타일 줄 번호 포함 파일 내용 표시
          <div className="p-2">
            <CodeWithLineNumbers content={file.content} fontSize="12px" />
          </div>
        )}
      </div>
    </div>
  );
}

function TerminalSlot({ slotId, logs, currentPath, terminalCount, locks, messages, tasks }: { slotId: number, logs: LogRecord[], currentPath: string, terminalCount: number, locks: Record<string, string>, messages: AgentMessage[], tasks: Task[] }) {
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

  // Active File Viewer State
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

    const launchAgent = (agent: string, yolo: boolean = false) => {
      setIsTerminalMode(true);
      setActiveAgent(agent);
  
      setTimeout(() => {      if (!xtermRef.current) return;
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
    // 중간에 포함된 모든 \n도 \r\n으로 변환하여 여러 줄 입력 시 줄바꿈이 깨지지 않게 합니다.
    wsRef.current.send(cleanText.replace(/\n/g, '\r\n') + '\r\n');
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
    // h-full: 그리드 셀 높이를 명시적으로 채워야 flex 자식들이 올바른 높이를 전달받음
    <div className="h-full bg-[#252526] border border-black/40 rounded-md flex flex-col overflow-hidden shadow-inner relative">
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
                    ? <CodeWithLineNumbers content={activeFileContent} fontSize="11px" />
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
          {/* 🔘 중앙 에이전트 선택 카드 UI */}
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

              {/* Codex Card */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                whileHover={{ scale: 1.02, translateY: -5 }}
                className="flex-1 bg-[#252526] border border-white/10 rounded-2xl p-6 shadow-2xl flex flex-col items-center gap-4 transition-all hover:border-[#f39c12]/50 group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                  <Zap className="w-12 h-12 text-[#f39c12]" />
                </div>
                <div className="w-16 h-16 rounded-2xl bg-[#f39c12]/10 flex items-center justify-center mb-2 group-hover:bg-[#f39c12]/20 transition-colors shadow-inner">
                  <Zap className="w-8 h-8 text-[#f39c12]" />
                </div>
                <div className="text-center">
                  <h3 className="text-xl font-black text-white tracking-tighter mb-1">CODEX CLI</h3>
                  <p className="text-[10px] text-[#f39c12] font-bold uppercase tracking-widest opacity-60">Autonomous Code Agent</p>
                </div>
                <p className="text-xs text-[#969696] text-center leading-relaxed h-12 flex items-center">
                  OpenAI 기반 자율 코딩 에이전트.<br/>YOLO 모드로 확인 없이 완전 자율 실행합니다.
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
                    className="w-full py-2.5 bg-[#f39c12]/20 hover:bg-[#f39c12]/40 text-[#f39c12] rounded-xl text-[11px] font-black transition-all border border-[#f39c12]/30 flex items-center justify-center gap-2 shadow-lg shadow-[#f39c12]/10"
                  >
                    <Zap className="w-3.5 h-3.5 fill-current" /> Codex 욜로(YOLO)
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
  )
}

export default App;
