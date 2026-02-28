/**
 * ------------------------------------------------------------------------
 * 📄 파일명: App.tsx
 * 📂 메인 문서 링크: docs/README.md
 * 🔗 개별 상세 문서: docs/App.tsx.md
 * 📝 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트로, 파일 탐색기, 다중 윈도우 퀵 뷰, 
 *          터미널 분할 화면 및 활성 파일 뷰어를 관리하는 메인 파일입니다.
 *          (2026-02-24: 한글 IME 엔터 키 즉시 전송 로직 최종 개선 및 재빌드 완료)
 * [2026-02-26] Claude: Superpowers 카드 repo·commands 하드코딩 → info?.repo / info?.commands 사용으로 수정
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Menu, Terminal, RotateCw,
  ChevronLeft, X, Zap, Search, Settings, ScrollText,
  Files, Cpu, Info, ChevronRight, ChevronDown,
  Trash2, LayoutDashboard, MessageSquare, ClipboardList, Plus, Brain,
  GitBranch, AlertTriangle, GitCommit as GitCommitIcon, ArrowUp, ArrowDown,
  Bot, Play, CircleDot, Package, CheckCircle2, Circle, Pin,
  Maximize2, Minimize2, FilePlus, FolderPlus, Edit2, Copy, ExternalLink
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
import { LogRecord, AgentMessage, Task, MemoryEntry, GitStatus, GitCommit, OrchestratorStatus, McpEntry, SmitheryServer, HiveHealth, HiveLog } from './types';

// 현재 접속 포트 기반으로 API/WS 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// Claude Code 세션별 컨텍스트 창 사용량 데이터 구조
interface ContextSession {
  session_id: string;
  slug: string;         // 세션 닉네임 (예: peppy-crafting-owl)
  model: string;        // 모델명 (예: claude-sonnet-4-6)
  input_tokens: number; // 현재 컨텍스트 창 입력 토큰 수
  output_tokens: number;// 누적 출력 토큰 수
  cache_read: number;   // 캐시 읽기 (Cache~)
  cache_write: number;  // 캐시 쓰기/생성 (Cache+)
  last_ts: string;      // 마지막 활동 ISO 타임스탬프
  cwd: string;          // 작업 디렉터리
}
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
interface SlashCommand { cmd: string; desc: string; category: string; injectSkill?: string; }

// 한글 스킬 커맨드 — 모든 에이전트 공통
const SKILL_SLASH_CMDS: SlashCommand[] = [
  { cmd: '/마스터',       desc: '중앙 컨트롤 타워 — 요청 분석 → 워크플로우 자동 라우팅', category: '스킬', injectSkill: 'master' },
  { cmd: '/브레인스토밍', desc: '소크라테스식 요구사항 정제 → 알고리즘 주입', category: '스킬', injectSkill: 'brainstorm' },
  { cmd: '/계획작성',     desc: '마이크로태스크 단위 계획 작성 → 알고리즘 주입', category: '스킬', injectSkill: 'write-plan' },
  { cmd: '/계획실행',     desc: '병렬 서브에이전트 실행 → 알고리즘 주입',     category: '스킬', injectSkill: 'execute-plan' },
  { cmd: '/TDD',          desc: 'RED→GREEN→REFACTOR 사이클 → 알고리즘 주입', category: '스킬', injectSkill: 'tdd' },
  { cmd: '/디버그',       desc: '4단계 근본원인 분석 → 알고리즘 주입',        category: '스킬', injectSkill: 'debug' },
  { cmd: '/코드리뷰',     desc: 'OWASP 보안 + 품질 자동 검증 → 알고리즘 주입', category: '스킬', injectSkill: 'code-review' },
];

const SLASH_COMMANDS: Record<string, SlashCommand[]> = {
  claude: [
    ...SKILL_SLASH_CMDS,
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
    ...SKILL_SLASH_CMDS,
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

// ── 활성 터미널 슬롯 추적 (전역) ──────────────────────────────────────────
// 마지막으로 포커스된 터미널 슬롯 ID — vibe:activeSlot 이벤트로 업데이트
let _vibeActiveSlot = 0;
window.addEventListener('vibe:activeSlot', (e: Event) => {
  _vibeActiveSlot = (e as CustomEvent<{ slotId: number }>).detail.slotId;
});

// ── 바이브 스킬 알고리즘 (MCP 없이 직접 주입) ──────────────────────────
export interface VibeSkill {
  name: string;
  desc: string;
  claudeCmd: string;   // MCP 설치 시 사용할 슬래시 커맨드
  geminiCmd: string;
  algo: string;        // MCP 미설치 시 주입할 알고리즘 (단일 메시지)
}

export const VIBE_SKILLS: VibeSkill[] = [
  {
    name: 'master',
    desc: '중앙 컨트롤 타워 — 요청 분석 → 하위 워크플로우 자동 라우팅',
    claudeCmd: '/vibe-master',
    geminiCmd: '/master',
    algo: '🌐 [마스터 컨트롤 프로토콜 가동] .gemini/skills/master/SKILL.md를 읽고 PROJECT_MAP.md를 기반으로 상황을 조율하세요. 어떤 작업을 도와드릴까요?',
  },
  {
    name: 'brainstorm',
    desc: '소크라테스식 요구사항 정제',
    claudeCmd: '/vibe-brainstorm',
    geminiCmd: '/brainstorming',
    algo: '🧠 [브레인스토밍 6단계 절차 가동] .gemini/skills/brainstorming/SKILL.md를 읽고 사용자 의도를 분석하여 승인된 계획을 수립하세요. 지금 무엇을 만들고 싶으신가요?',
  },
  {
    name: 'write-plan',
    desc: '마이크로태스크 단위 계획 작성',
    claudeCmd: '/vibe-write-plan',
    geminiCmd: '/write-plan',
    algo: '📝 [구현 계획 작성 모드] .gemini/skills/write-plan/SKILL.md를 참고하여 TDD 기반의 상세 계획을 수립하세요. 어떤 기능의 계획을 짤까요?',
  },
  {
    name: 'execute-plan',
    desc: '계획 순서대로 실행',
    claudeCmd: '/vibe-execute-plan',
    geminiCmd: '/execute-plan',
    algo: '🚀 [계획 실행 모드] .gemini/skills/execute-plan/SKILL.md를 참고하여 승인된 계획대로 구현을 시작하세요. 어떤 계획 파일을 읽을까요?',
  },
  {
    name: 'tdd',
    desc: 'RED → GREEN → REFACTOR 사이클',
    claudeCmd: '/vibe-tdd',
    geminiCmd: '/tdd',
    algo: '🧪 [TDD 모드 가동] .gemini/skills/tdd/SKILL.md를 참고하여 실패하는 테스트부터 작성하는 RED-GREEN-REFACTOR 사이클을 시작합니다. 어떤 기능을 구현할까요?',
  },
  {
    name: 'debug',
    desc: '4단계 근본원인 분석',
    claudeCmd: '/vibe-debug',
    geminiCmd: '/systematic-debugging',
    algo: '🔍 [지능형 디버깅 가동] .gemini/skills/systematic-debugging/SKILL.md를 참고하여 원인 분석 후 수정을 시작하세요. 어떤 버그를 추적할까요?',
  },
  {
    name: 'code-review',
    desc: 'OWASP 보안 + 품질 자동 검증',
    claudeCmd: '/vibe-code-review',
    geminiCmd: '/code-review',
    algo: '🧐 [코드 리뷰 모드] .gemini/skills/code-review/SKILL.md를 참고하여 품질/보안을 검증하세요. 무엇을 리뷰할까요?',
  },
];

function App() {
  const [isInitializing, setIsInitializing] = useState(true);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(300);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);
  const [activeTab, setActiveTab] = useState('explorer');
  // 레이아웃 모드: 1, 2, 3, 4(가로4열), 2x2(2×2격자), 6(3×2격자), 8(4×2격자)
  const [layoutMode, setLayoutMode] = useState<'1' | '2' | '3' | '4' | '2x2' | '6' | '8'>('2');
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

  // 🔮 컨텍스트 메뉴 상태 (파일/폴더 및 작업 항목 지원)
  const [contextMenu, setContextMenu] = useState<{ 
    x: number, y: number, 
    type: 'file' | 'task', 
    path?: string, isDir?: boolean,
    taskId?: string, taskTitle?: string
  } | null>(null);
  const [isRenaming, setIsRenaming] = useState<string | null>(null); // 이름 변경 중인 파일 경로
  const [newNameDraft, setNewNameDraft] = useState(''); // 새 이름 입력값
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');
  // 메시지 채널용 한글 입력 상태 Ref
  const isMsgComposingRef = useRef(false);

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
  const [memShowAll, setMemShowAll] = useState(false);   // 전체 프로젝트 보기 토글
  const [currentProjectName, setCurrentProjectName] = useState('');
  const [currentProjectRoot, setCurrentProjectRoot] = useState(''); // 서버 PROJECT_ROOT 전체 경로
  const [appVersion, setAppVersion] = useState('');

  // 현재 프로젝트 정보 + 서버 버전 조회 (1회)
  // localStorage에 경로가 없으면 서버 PROJECT_ROOT를 currentPath 초기값으로 사용
  useEffect(() => {
    fetch(`${API_BASE}/api/project-info`)
      .then(res => res.json())
      .then(data => {
        setCurrentProjectName(data.project_name || '');
        const root = (data.project_root || '').replace(/\\/g, '/');
        setCurrentProjectRoot(root);
        // 최초 실행(localStorage 없음)이면 서버 PROJECT_ROOT를 현재 경로로 사용
        if (!localStorage.getItem('hive_last_path') && root) {
          setCurrentPath(root);
          setGitPath(root);
        }
        if (data.version) setAppVersion(data.version);
      })
      .catch(() => {})
      .finally(() => setIsInitializing(false));
  }, []);

  // 검색어가 있으면 서버 검색, 없으면 전체 목록 사용
  const fetchMemory = (q = '', showAll = memShowAll) => {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (showAll) params.set('all', 'true');
    const url = `${API_BASE}/api/memory${params.toString() ? '?' + params.toString() : ''}`;
    fetch(url)
      .then(res => res.json())
      .then(data => setMemory(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 공유 메모리 폴링 (5초 간격 — 자주 바뀌지 않으므로 느리게)
  useEffect(() => {
    fetchMemory(memSearch, memShowAll);
    const interval = setInterval(() => fetchMemory(memSearch, memShowAll), 5000);
    return () => clearInterval(interval);
  }, [memSearch, memShowAll]);

  // 검색어 변경 시 즉시 검색
  useEffect(() => { fetchMemory(memSearch, memShowAll); }, [memSearch, memShowAll]);

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

  // Git 변경사항 롤백 (Undo)
  const rollbackFile = (filePath: string) => {
    if (!confirm(`[위험] '${filePath}'의 모든 변경사항을 취소하고 마지막 커밋 상태로 되돌리시겠습니까?`)) return;
    fetch(`${API_BASE}/api/git/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file: filePath, path: gitPath }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') refreshItems();
        else alert(`롤백 실패: ${data.message}`);
      })
      .catch(err => alert(`에러 발생: ${err}`));
  };

  // ─── Git 실시간 감시 상태 ─────────────────────────────────────────────
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [gitLog, setGitLog] = useState<GitCommit[]>([]);
  // 초기값은 빈 문자열 — project-info useEffect에서 서버 PROJECT_ROOT로 동기화
  const [gitPath, setGitPath] = useState(localStorage.getItem('hive_last_path') || '');

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

  // ─── Superpowers 관리자 상태 ─────────────────────────────────────────────
  interface SpStatus { installed: boolean; version: string | null; skills: string[]; commands: string[]; repo: string; }
  const [spStatus, setSpStatus] = useState<{ claude: SpStatus; gemini: SpStatus } | null>(null);
  const [spLoading, setSpLoading] = useState<Record<string, boolean>>({});
  const [spMsg, setSpMsg] = useState('');
  const [hiveHealth, setHiveHealth] = useState<HiveHealth | null>(null);
  const [hiveLogs, setHiveLogs] = useState<HiveLog[]>([]); // 하이브 통합 로그
  const [logFilter, setLogFilter] = useState(''); // 로그 검색어
  const [skillProposals, setSkillProposals] = useState<{ keyword: string; count: number; suggested_skill_name: string; description: string }[]>([]);

  const fetchHiveHealth = () => {
    fetch(`${API_BASE}/api/hive/health`)
      .then(res => res.json())
      .then(data => setHiveHealth(data))
      .catch(() => {});
  };

  const fetchSkillAnalysis = () => {
    fetch(`${API_BASE}/api/hive/skill-analysis`)
      .then(res => res.json())
      .then(data => setSkillProposals(data.proposals || []))
      .catch(() => {});
  };

  const approveSkill = (proposal: { keyword: string; suggested_skill_name: string }) => {
    fetch(`${API_BASE}/api/hive/approve-skill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_name: proposal.suggested_skill_name, keyword: proposal.keyword })
    })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        setSpMsg(`새로운 스킬 [${proposal.suggested_skill_name}]이(가) 등록되었습니다.`);
        fetchSkillAnalysis();
        fetchHiveHealth();
      }
    });
  };

  const fetchSpStatus = () => {
    fetch(`${API_BASE}/api/superpowers/status`)
      .then(res => res.json())
      .then(data => setSpStatus(data))
      .catch(() => {});
  };
  const fetchHiveLogs = () => {
    fetch(`${API_BASE}/api/hive/logs`)
      .then(res => res.json())
      .then(data => setHiveLogs(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  useEffect(() => { 
    fetchSpStatus(); 
    fetchHiveHealth(); 
    fetchSkillAnalysis(); 
    fetchHiveLogs();
    const interval = setInterval(fetchHiveLogs, 5000);
    return () => clearInterval(interval);
  }, []);

  const spInstall = (tool: 'claude' | 'gemini') => {
    setSpLoading(p => ({ ...p, [tool]: true }));
    setSpMsg('');
    fetch(`${API_BASE}/api/superpowers/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool }),
    })
      .then(res => res.json())
      .then(data => { setSpMsg(data.message || '완료'); fetchSpStatus(); })
      .catch(e => setSpMsg(String(e)))
      .finally(() => setSpLoading(p => ({ ...p, [tool]: false })));
  };

  const spUninstall = (tool: 'claude' | 'gemini') => {
    setSpLoading(p => ({ ...p, [tool]: true }));
    setSpMsg('');
    fetch(`${API_BASE}/api/superpowers/uninstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool }),
    })
      .then(res => res.json())
      .then(data => { setSpMsg(data.message || '완료'); fetchSpStatus(); })
      .catch(e => setSpMsg(String(e)))
      .finally(() => setSpLoading(p => ({ ...p, [tool]: false })));
  };

  // ─── MCP 관리자 상태 ─────────────────────────────────────────────────────
  const [mcpCatalog, setMcpCatalog] = useState<McpEntry[]>([]);
  const [mcpInstalled, setMcpInstalled] = useState<string[]>([]);
  const [mcpTool, setMcpTool] = useState<'claude' | 'gemini'>('claude');
  const [mcpScope, setMcpScope] = useState<'global' | 'project'>('global');
  const [mcpLoading, setMcpLoading] = useState<Record<string, boolean>>({}); // 이름 → 로딩 여부
  const [mcpMsg, setMcpMsg] = useState(''); // 마지막 작업 결과 메시지
  const [mcpNeedsRestart, setMcpNeedsRestart] = useState(false); // 재시작 안내 플래그
  // Smithery 검색
  const [mcpView, setMcpView] = useState<'catalog' | 'search'>('catalog');
  const [mcpSearchQuery, setMcpSearchQuery] = useState('');
  const [mcpSearchResults, setMcpSearchResults] = useState<SmitheryServer[]>([]);
  const [mcpSearchLoading, setMcpSearchLoading] = useState(false);
  const [mcpSearchPage, setMcpSearchPage] = useState(1);
  const [mcpSearchTotal, setMcpSearchTotal] = useState(0);
  const [mcpSearchTotalPages, setMcpSearchTotalPages] = useState(0);
  const [mcpSearchError, setMcpSearchError] = useState('');
  const [mcpHasKey, setMcpHasKey] = useState(false);
  const [mcpKeyMasked, setMcpKeyMasked] = useState('');
  const [mcpKeyDraft, setMcpKeyDraft] = useState('');
  const [mcpKeySaving, setMcpKeySaving] = useState(false);
  const [mcpShowKeyInput, setMcpShowKeyInput] = useState(false);

  // 카탈로그는 최초 1회만 불러옴
  useEffect(() => {
    fetch(`${API_BASE}/api/mcp/catalog`)
      .then(res => res.json())
      .then((data: McpEntry[]) => setMcpCatalog(Array.isArray(data) ? data : []))
      .catch(() => {});
    // Smithery API 키 상태 조회
    fetch(`${API_BASE}/api/mcp/apikey`)
      .then(res => res.json())
      .then(data => { setMcpHasKey(data.has_key ?? false); setMcpKeyMasked(data.masked ?? ''); })
      .catch(() => {});
  }, []);

  // Smithery API 키 저장
  const saveMcpApiKey = () => {
    if (!mcpKeyDraft.trim()) return;
    setMcpKeySaving(true);
    fetch(`${API_BASE}/api/mcp/apikey`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: mcpKeyDraft.trim() }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setMcpHasKey(true);
          setMcpKeyMasked(mcpKeyDraft.slice(0, 6) + '…');
          setMcpKeyDraft('');
          setMcpShowKeyInput(false);
        }
      })
      .catch(() => {})
      .finally(() => setMcpKeySaving(false));
  };

  // Smithery 검색 실행
  const searchSmithery = (page = 1) => {
    if (!mcpSearchQuery.trim()) return;
    setMcpSearchLoading(true);
    setMcpSearchError('');
    fetch(`${API_BASE}/api/mcp/search?q=${encodeURIComponent(mcpSearchQuery)}&page=${page}&pageSize=10`)
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          setMcpSearchError(data.message ?? data.error);
          setMcpSearchResults([]);
        } else {
          setMcpSearchResults(data.servers ?? []);
          setMcpSearchPage(data.pagination?.currentPage ?? page);
          setMcpSearchTotal(data.pagination?.totalCount ?? 0);
          setMcpSearchTotalPages(data.pagination?.totalPages ?? 0);
        }
      })
      .catch(() => setMcpSearchError('네트워크 오류'))
      .finally(() => setMcpSearchLoading(false));
  };

  // Smithery 검색 결과에서 설치 (qualifiedName을 package로 사용)
  const installFromSearch = (server: SmitheryServer) => {
    const slug = server.qualifiedName.split('/').pop() ?? server.qualifiedName;
    setMcpLoading(prev => ({ ...prev, [server.qualifiedName]: true }));
    fetch(`${API_BASE}/api/mcp/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: mcpTool, scope: mcpScope,
        name: slug, package: server.qualifiedName,
        requiresEnv: [],
      }),
    })
      .then(res => res.json())
      .then(data => {
        setMcpMsg(data.message ?? '');
        if (data.status === 'success') { setMcpNeedsRestart(true); fetchMcpInstalled(); }
      })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [server.qualifiedName]: false })));
  };

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
      .then(data => {
        setMcpMsg(data.message ?? '');
        if (data.status === 'success') setMcpNeedsRestart(true);
        fetchMcpInstalled();
      })
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
      .then(data => {
        setMcpMsg(data.message ?? '');
        if (data.status === 'success') setMcpNeedsRestart(true);
        fetchMcpInstalled();
      })
      .catch(() => {})
      .finally(() => setMcpLoading(prev => ({ ...prev, [name]: false })));
  };

  // 메시지 전송
  const sendMessage = () => {
    if (!msgContent.trim()) return;
    
    // 명령어 모드('>')인 경우 엔터(\n)를 유지하여 터미널에서 즉시 실행되도록 합니다.
    const isCommand = msgContent.trim().startsWith('>');
    const cleanContent = isCommand ? msgContent : msgContent.replace(/[\r\n]+$/, '');
    
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
  const [updateReady, setUpdateReady] = useState<{ version?: string; ready: boolean; downloading: boolean; checking?: boolean } | null>(null);
  const [updateApplying, setUpdateApplying] = useState(false);

  // Claude Code 세션별 컨텍스트 사용량 — TerminalSlot에 slotId 순서대로 전달
  const [contextSessions, setContextSessions] = useState<ContextSession[]>([]);
  // Gemini CLI 세션별 컨텍스트 사용량 — Claude와 동일한 ContextSession 인터페이스 재사용
  // [2026-02-27] Claude: Gemini 컨텍스트 사용량 표시 기능 추가
  const [geminiContextSessions, setGeminiContextSessions] = useState<ContextSession[]>([]);

  // 30초마다 Claude/Gemini 컨텍스트 사용량 동시 갱신
  useEffect(() => {
    const doFetch = () => {
      fetch(`${API_BASE}/api/context-usage`)
        .then(res => res.json())
        .then(data => setContextSessions(data.sessions || []))
        .catch(() => {});
      // Gemini 세션도 같은 주기로 갱신 (로컬 JSON 파일 읽기 — API 호출 아님)
      fetch(`${API_BASE}/api/gemini-context-usage`)
        .then(res => res.json())
        .then(data => setGeminiContextSessions(data.sessions || []))
        .catch(() => {});
    };
    doFetch();
    const iv = setInterval(doFetch, 30000);
    return () => clearInterval(iv);
  }, []);

  // 30초마다 업데이트 준비 여부 확인 (다운로드/확인 중이면 5초마다)
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const check = () => {
      fetch(`${API_BASE}/api/check-update-ready`)
        .then(res => res.json())
        .then(data => {
          if (data?.version || data?.checking) {
            const next = { 
              version: data.version, 
              ready: !!data.ready, 
              downloading: !!data.downloading,
              checking: !!data.checking
            };
            // 다운로드 완료 전환 감지 → 토스트 알림
            setUpdateReady(prev => {
              if (prev?.downloading && next.ready) {
                showToast(`🎉 ${next.version} 다운로드 완료! 우측 상단 [업데이트] 버튼을 눌러주세요.`, 'ok', 6000);
              }
              return next;
            });
          } else {
            setUpdateReady(null);
          }
        })
        .catch(() => {});
    };
    check();
    // 다운로드 중이거나 확인 중이면 5초, 아니면 30초 폴링
    const scheduleNext = () => {
      const delay = (updateReady?.downloading || updateReady?.checking) ? 5000 : 30000;
      interval = setTimeout(() => { check(); scheduleNext(); }, delay);
    };
    scheduleNext();
    return () => clearTimeout(interval);
  }, [updateReady?.downloading, updateReady?.checking]);

  // 토스트 알림 상태 — 업데이트 확인 결과, 설치 완료 등 간단한 피드백용
  const [toast, setToast] = useState<{ msg: string; type: 'info' | 'ok' | 'warn' } | null>(null);
  const showToast = (msg: string, type: 'info' | 'ok' | 'warn' = 'info', ms = 3500) => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), ms);
  };

  const [updateChecking, setUpdateChecking] = useState(false);
  const triggerUpdateCheck = () => {
    if (updateChecking) return;
    setUpdateChecking(true);
    showToast('업데이트 확인 중...', 'info', 8000);
    fetch(`${API_BASE}/api/trigger-update-check`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (!data.started) {
          showToast('업데이트 확인 불가 (개발 빌드)', 'warn');
        } else {
          // 10초 뒤 update_ready 상태 체크 — 새 버전 없으면 "최신 버전" 메시지
          setTimeout(() => {
            fetch(`${API_BASE}/api/check-update-ready`)
              .then(r => r.json())
              .then(d => {
                if (!d.ready && !d.downloading) showToast('✓ 최신 버전입니다', 'ok');
              });
          }, 10000);
        }
      })
      .catch(() => showToast('서버 연결 오류', 'warn'))
      .finally(() => setUpdateChecking(false));
  };

  const applyUpdate = () => {
    setUpdateApplying(true);
    // 업데이트 적용 후 재시작되므로, 재시작 시 스킬 재설치 안내를 띄우기 위해 플래그 저장
    localStorage.setItem('hive_needs_skill_reinstall', 'true');
    fetch(`${API_BASE}/api/apply-update`, { method: 'POST' })
      .then(res => res.json())
      .then(() => setUpdateReady(null))
      .catch(() => {})
      .finally(() => setUpdateApplying(false));
  };

  // 업데이트 후 재시작 감지 — localStorage 플래그로 스킬 재설치 안내 표시
  const [needsSkillReinstall, setNeedsSkillReinstall] = useState<boolean>(
    () => localStorage.getItem('hive_needs_skill_reinstall') === 'true'
  );

  // ─── 컨텍스트 메뉴 핸들러 ───────────────────────────────────────────────────
  const handleContextMenu = (e: React.MouseEvent, path: string, isDir: boolean) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, type: 'file', path, isDir });
  };

  const handleTaskContextMenu = (e: React.MouseEvent, taskId: string, taskTitle: string) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, type: 'task', taskId, taskTitle });
  };

  const closeContextMenu = () => setContextMenu(null);

  const handleFileRename = (oldPath: string, newName: string) => {
    const parent = oldPath.substring(0, oldPath.lastIndexOf('/'));
    const newPath = `${parent}/${newName}`;
    fetch(`${API_BASE}/api/file-rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src: oldPath, dest: newPath }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          showToast('이름 변경 완료', 'ok');
          refreshItems(); // 파일 목록 새로고침
          // 트리 모드 대응을 위해 부모 폴더도 갱신 필요할 수 있음
          if (treeExpanded[parent]) {
            fetch(`${API_BASE}/api/files?path=${encodeURIComponent(parent)}`)
              .then(res => res.json())
              .then(data => { if (Array.isArray(data)) setTreeChildren(prev => ({ ...prev, [parent]: data })); });
          }
        } else {
          showToast(`오류: ${data.message}`, 'warn');
        }
      })
      .finally(() => { setIsRenaming(null); closeContextMenu(); });
  };

  const handleFileDelete = (path: string, isDir: boolean) => {
    if (!confirm(`${isDir ? '폴더' : '파일'}을(를) 정말 삭제하시겠습니까?\n${path}`)) return;
    fetch(`${API_BASE}/api/file-op`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op: 'delete', src: path }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          showToast('삭제 완료', 'ok');
          refreshItems();
          const parent = path.substring(0, path.lastIndexOf('/'));
          if (treeExpanded[parent]) {
            fetch(`${API_BASE}/api/files?path=${encodeURIComponent(parent)}`)
              .then(res => res.json())
              .then(data => { if (Array.isArray(data)) setTreeChildren(prev => ({ ...prev, [parent]: data })); });
          }
        } else {
          showToast(`오류: ${data.message}`, 'warn');
        }
      })
      .finally(() => closeContextMenu());
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    showToast('클립보드에 복사됨', 'ok');
    closeContextMenu();
  };

  const revealInExplorer = (path: string) => {
    // 서버측 API 호출 필요 (이미 구현된 /api/file-op 확장 또는 신규)
    // 여기서는 간단히 경로 복사로 대체하거나 신규 엔드포인트 제안
    fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(path)}`)
      .then(() => showToast('경로 복사 및 탐색기 준비', 'info'))
      .finally(() => closeContextMenu());
  };

  useEffect(() => {
    const handleClick = () => closeContextMenu();
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, []);

  const doReinstallSkills = () => {
    // Claude + Gemini 스킬 순차 재설치
    Promise.all(['claude', 'gemini'].map(tool =>
      fetch(`${API_BASE}/api/superpowers/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool }),
      }).then(r => r.json())
    ))
      .then(() => {
        localStorage.removeItem('hive_needs_skill_reinstall');
        setNeedsSkillReinstall(false);
        fetchSpStatus();
      })
      .catch(() => {});
  };

  // 파일 시스템 탐색 상태
  const [drives, setDrives] = useState<string[]>([]);
  const [projects, setProjects] = useState<string[]>([]);
  // 마지막 선택 경로를 localStorage에서 복원 — 앱 재시작 시 이전 프로젝트 유지
  // 최초 실행 시 빈 문자열 → 서버의 PROJECT_ROOT 로 초기화됨 (useEffect에서 동기화)
  const [currentPath, setCurrentPath] = useState<string>(
    () => localStorage.getItem('hive_last_path') || ''
  );

  // 최근 프로젝트 목록 가져오기
  const fetchProjects = () => {
    fetch(`${API_BASE}/api/projects`)
      .then(res => res.json())
      .then(data => setProjects(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 새 프로젝트 폴더 열기 (브라우저 다이얼로그 호출)
  const openProjectFolder = () => {
    fetch(`${API_BASE}/api/browse-folder`)
      .then(res => res.json())
      .then(data => {
        if (data.path) {
          setCurrentPath(data.path);
          // 서버 목록에도 추가
          fetch(`${API_BASE}/api/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: data.path })
          }).then(() => fetchProjects());
        }
      })
      .catch(err => alert("폴더 선택 오류: " + err));
    setActiveMenu(null);
  };

  useEffect(() => {
    fetchProjects();
  }, []);
  const [items, setItems] = useState<{ name: string, path: string, isDir: boolean }[]>([]);
  const [treeMode, setTreeMode] = useState(true);
  const [treeExpanded, setTreeExpanded] = useState<Record<string, boolean>>({});
  const [treeChildren, setTreeChildren] = useState<Record<string, { name: string; path: string; isDir: boolean }[]>>({});

  // currentPath 변경 시 Git 감시 경로도 동기화 + 트리 초기화 + localStorage 저장
  useEffect(() => { setGitPath(currentPath); }, [currentPath]);
  useEffect(() => { setTreeExpanded({}); setTreeChildren({}); }, [currentPath]);
  // 경로가 바뀔 때마다 localStorage에 저장 — 다음 세션에서 복원용
  useEffect(() => { localStorage.setItem('hive_last_path', currentPath); }, [currentPath]);

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
  // SSE 핸들러 내 stale closure 방지용 ref
  // (fsSse는 마운트 1회만 생성 → ref로 항상 최신 함수 참조)
  const refreshItemsRef = useRef(refreshItems);
  useEffect(() => { refreshItemsRef.current = refreshItems; });

  // currentPath 변경 시 파일 목록 자동 갱신
  useEffect(() => { refreshItems(); }, [currentPath]);

  const createFile = () => {
    const name = prompt("새 파일 이름을 입력하세요:");
    if (!name) return;
    const path = `${currentPath}/${name}`;
    fetch(`${API_BASE}/api/file-op`, {
      method: 'POST',
      body: JSON.stringify({ op: 'create_file', path })
    }).then(() => refreshItems());
  };

  const createDir = () => {
    const name = prompt("새 폴더 이름을 입력하세요:");
    if (!name) return;
    const path = `${currentPath}/${name}`;
    fetch(`${API_BASE}/api/file-op`, {
      method: 'POST',
      body: JSON.stringify({ op: 'create_dir', path })
    }).then(() => refreshItems());
  };

  const deleteItem = (itemPath: string, name: string) => {
    if (!confirm(`'${name}'을(를) 삭제하시겠습니까?`)) return;
    fetch(`${API_BASE}/api/file-op`, {
      method: 'POST',
      body: JSON.stringify({ op: 'delete', src: itemPath })
    }).then(() => {
      refreshItems();
      setOpenFiles(prev => prev.filter(f => f.path !== itemPath));
    });
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
      if (treeMode) {
        handleTreeToggle(item.path);
      } else {
        setCurrentPath(item.path);
      }
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
    setActiveMenu(null);
    setActiveTab('superpowers');
    setIsSidebarOpen(true);
    setSpMsg('설치 중...');
    fetch(`${API_BASE}/api/install-skills?path=${encodeURIComponent(currentPath)}`)
      .then(res => res.json())
      .then(data => { setSpMsg(data.message || '하이브 스킬 설치 완료 ✓'); fetchSpStatus(); refreshItems(); })
      .catch(err => setSpMsg('설치 실패: ' + err));
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
    // 1) 메인 로그 스트림
    const sse = new EventSource(`${API_BASE}/stream`);
    sse.onmessage = (e) => {
      try {
        const data: LogRecord = JSON.parse(e.data);
        setLogs(prev => [...prev.slice(-199), data]);
      } catch (err) { }
    };

    // 2) 파일 시스템 이벤트 → 탐색기 갱신
    // ref를 통해 호출 → stale closure 방지 (currentPath 최신값 항상 반영)
    const fsSse = new EventSource(`${API_BASE}/api/events/fs`);
    fsSse.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'fs_change') refreshItemsRef.current();
      } catch (err) { }
    };

    return () => {
      sse.close();
      fsSse.close();
    };
  }, []);

  const slots = Array.from({ length: terminalCount }, (_, i) => i);

  // ─── 사이드바 리사이징 로직 ─────────────────────────────────────────────
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizingSidebar) return;
      // Activity Bar 너비(48px)를 제외한 위치 계산
      const newWidth = e.clientX - 48;
      if (newWidth > 150 && newWidth < 800) {
        setSidebarWidth(newWidth);
      }
    };
    const handleMouseUp = () => setIsResizingSidebar(false);

    if (isResizingSidebar) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
    } else {
      document.body.style.cursor = 'default';
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizingSidebar]);

  if (isInitializing) return null;

  return (
    <div className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden select-none font-sans flex-col" onClick={() => setActiveMenu(null)}>
      
      {/* 업데이트 알림 배너 */}
      {updateReady && (
        <div className="flex items-center justify-between px-3 py-1 bg-primary/20 border-b border-primary/40 shrink-0 z-50">
          <span className="text-[10px] text-primary font-bold">
            {updateReady.checking
              ? <>GitHub에서 새로운 버전을 찾는 중...</>
              : updateReady.downloading
                ? <>새 버전 <span className="font-mono">{updateReady.version}</span> 다운로드 중...</>
                : <>새 버전 <span className="font-mono">{updateReady.version}</span> 업데이트 준비 완료</>
            }
          </span>
          <div className="flex items-center gap-2">
            {!updateReady.downloading && !updateReady.checking && (
              <button
                onClick={applyUpdate}
                disabled={updateApplying}
                className="text-[9px] font-bold px-2 py-0.5 rounded bg-primary text-white hover:bg-primary/80 disabled:opacity-50 transition-colors"
              >
                {updateApplying ? '적용 중...' : '지금 업데이트'}
              </button>
            )}
            {(updateReady.downloading || updateReady.checking) && (
              <span className="text-[9px] text-primary/60 animate-pulse">
                {updateReady.checking ? '조회 중...' : '준비 중...'}
              </span>
            )}
            <button
              onClick={() => setUpdateReady(null)}
              className="text-[9px] text-white/40 hover:text-white/70 transition-colors"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 업데이트 후 스킬 재설치 안내 배너 */}
      {needsSkillReinstall && (
        <div className="flex items-center justify-between px-3 py-1 bg-yellow-500/20 border-b border-yellow-500/40 shrink-0 z-50">
          <span className="text-[10px] text-yellow-300 font-bold">
            ⚡ 업데이트 완료! 스킬을 다시 설치해 주세요.
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={doReinstallSkills}
              className="text-[9px] font-bold px-2 py-0.5 rounded bg-yellow-500 text-black hover:bg-yellow-400 transition-colors"
            >
              스킬 재설치
            </button>
            <button
              onClick={() => { localStorage.removeItem('hive_needs_skill_reinstall'); setNeedsSkillReinstall(false); }}
              className="text-[9px] text-white/40 hover:text-white/70 transition-colors"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 토스트 알림 — 우측 상단 고정 */}
      {toast && (
        <div className={`fixed top-3 right-4 z-[9999] px-3 py-2 rounded shadow-lg text-[11px] font-bold flex items-center gap-2 transition-all pointer-events-none
          ${toast.type === 'ok' ? 'bg-green-600/90 text-white' : toast.type === 'warn' ? 'bg-yellow-500/90 text-black' : 'bg-[#007acc]/90 text-white'}`}>
          {toast.type === 'info' && <span className="animate-spin inline-block w-3 h-3 border-2 border-white/40 border-t-white rounded-full" />}
          {toast.msg}
        </div>
      )}

      {/* 🔮 파일 탐색기 및 작업 항목 컨텍스트 메뉴 (다크 네온 스타일) */}
      {contextMenu && (
        <div 
          className="fixed z-[9999] min-w-[170px] bg-[#252526]/95 backdrop-blur-md border border-white/10 rounded shadow-2xl py-1 overflow-hidden animate-in fade-in zoom-in-95 duration-100"
          style={{ 
            left: Math.min(contextMenu.x, window.innerWidth - 180), 
            top: Math.min(contextMenu.y, window.innerHeight - (contextMenu.type === 'file' ? 240 : 150)) 
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {contextMenu.type === 'file' && contextMenu.path && (
            <>
              {/* 메뉴 항목: 이름 변경 */}
              <button 
                onClick={() => { setIsRenaming(contextMenu.path!); setNewNameDraft(contextMenu.path!.split('/').pop() || ''); closeContextMenu(); }}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-primary/20 hover:text-white transition-colors"
              >
                <Edit2 className="w-3.5 h-3.5" /> 이름 변경
              </button>

              {/* 메뉴 항목: 삭제 (아이콘 Trash2로 통일) */}
              <button 
                onClick={() => handleFileDelete(contextMenu.path!, !!contextMenu.isDir)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-red-500/20 hover:text-red-400 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" /> 삭제
              </button>

              <div className="h-px bg-white/5 my-1" />

              {/* 메뉴 항목: 경로 복사 */}
              <button 
                onClick={() => copyToClipboard(contextMenu.path!)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-white/5 hover:text-white transition-colors"
              >
                <Copy className="w-3.5 h-3.5" /> 경로 복사
              </button>

              {/* 메뉴 항목: 탐색기에서 보기 */}
              <button 
                onClick={() => revealInExplorer(contextMenu.path!)}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-white/5 hover:text-white transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" /> 탐색기에서 보기
              </button>

              <div className="h-px bg-white/5 my-1" />

              {/* 하이브 마인드 특화 기능 */}
              <button 
                onClick={() => {
                  window.dispatchEvent(new CustomEvent(`vibe:fillInput:${_vibeActiveSlot}`, { 
                    detail: { text: `[파일 분석 요청] ${contextMenu.path} 이 파일의 역할과 내용을 설명해줘.` } 
                  }));
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-primary hover:bg-primary/10 transition-colors font-bold"
              >
                <Brain className="w-3.5 h-3.5" /> 에이전트에게 분석 요청
              </button>
            </>
          )}

          {contextMenu.type === 'task' && contextMenu.taskId && (
            <>
              <div className="px-3 py-1 text-[9px] text-textMuted font-bold uppercase tracking-wider opacity-60">작업 관리</div>
              <button 
                onClick={() => { updateTask(contextMenu.taskId!, { status: 'in_progress' }); closeContextMenu(); }}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-primary/20 hover:text-white transition-colors"
              >
                <Play className="w-3.5 h-3.5" /> 작업 시작
              </button>
              <button 
                onClick={() => { updateTask(contextMenu.taskId!, { status: 'done' }); closeContextMenu(); }}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-[#cccccc] hover:bg-green-500/20 hover:text-green-400 transition-colors"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> 완료 처리
              </button>
              <div className="h-px bg-white/5 my-1" />
              <button 
                onClick={() => { deleteTask(contextMenu.taskId!); closeContextMenu(); }}
                className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] text-red-400 hover:bg-red-500/20 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" /> 작업 삭제
              </button>
            </>
          )}
        </div>
      )}

      {/* 🟢 Top Menu Bar (IDE Style - 최상단 고정) */}
      <div className="h-7 bg-[#323233] flex items-center px-2 gap-0.5 text-[12px] border-b border-black/30 shrink-0 z-50 shadow-lg">
        <img src="/vibe_icon.png" alt="vibe" className="w-4 h-4 mx-1 object-contain" />
        <span className="text-[10px] font-bold text-white/90 mr-1 tracking-tight">바이브 코딩</span>
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
                  onClick={openProjectFolder}
                  className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2"
                >
                  <VscFolderOpened className="w-3.5 h-3.5 text-[#dcb67a]" /> 폴더 열기...
                </button>
                <div className="h-px bg-white/5 my-1 mx-2"></div>
                <button
                  onClick={() => {
                    alert("이 시스템은 24시간 상시 가동 모드로 설정되어 있습니다.\n시스템을 종료하려면 관리자에게 문의하거나 프로세스를 수동으로 중단해야 합니다.");
                    setActiveMenu(null);
                  }}
                  className="w-full text-left px-4 py-1.5 hover:bg-white/5 text-gray-500 flex items-center gap-2 cursor-not-allowed"
                >
                  <X className="w-3.5 h-3.5" /> 시스템 종료 (상시 가동 중)
                </button>              </div>
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
                <button onClick={() => { alert("바이브 코딩(Vibe Coding) v1.0.0\n하이브 마인드 중앙 지휘소"); setActiveMenu(null); }} className="w-full text-left px-4 py-1.5 hover:bg-white/10 flex items-center gap-2">
                  <Info className="w-3.5 h-3.5 text-[#3794ef]" /> 버전 정보
                </button>
              </div>
            )}
          </div>
        ))}
        <div className="ml-auto flex items-center gap-3 text-[11px] text-[#969696] px-4 font-mono overflow-hidden">
           {/* 🟢 실시간 에이전트 모니터 (Real-time Agent HUD) */}
           {orchStatus?.agent_status && Object.entries(orchStatus.agent_status).map(([agent, st]) => {
             if (st.state !== 'active') return null;
             return (
               <div key={agent} className="flex items-center gap-1 bg-green-500/10 border border-green-500/30 px-1.5 py-0.5 rounded text-[9px] text-green-400 animate-pulse shadow-[0_0_8px_rgba(74,222,128,0.2)]" title="에이전트 작업 중">
                 <Bot className="w-3 h-3" />
                 <span className="font-bold uppercase tracking-wider">{agent}</span>
                 <span className="opacity-80">활성</span>
               </div>
             );
           })}
           <span className="truncate opacity-50 border-l border-white/10 pl-3">{currentPath}</span>

           {/* 버전 + 업데이트 버튼 — 오른쪽 끝 고정 */}
           <button
             onClick={triggerUpdateCheck}
             disabled={updateChecking}
             title="업데이트 확인"
             className={`flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-bold shrink-0 transition-all disabled:opacity-60
               ${updateReady && !updateReady.downloading
                 ? 'bg-red-500/20 border-red-500/60 text-red-400 animate-pulse hover:bg-red-500/30'
                 : updateReady?.downloading
                 ? 'bg-yellow-500/20 border-yellow-500/40 text-yellow-300'
                 : 'bg-white/5 border-white/10 text-white/50 hover:text-white/80 hover:border-white/30'
               }`}
           >
             <span className="font-mono">{appVersion ? `v${appVersion}` : 'v3.4.1'}</span>
             {updateChecking
               ? <span className="animate-spin inline-block w-3 h-3 border-2 border-current/30 border-t-current rounded-full" />
               : updateReady && !updateReady.downloading
               ? <span>🔴 업데이트</span>
               : updateReady?.downloading
               ? <span>⬇ 다운로드 중</span>
               : <span className="opacity-60">↑ 업데이트 확인</span>
             }
           </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Activity Bar (VS Code Style) */}
        <div className="w-12 h-full bg-[#333333] border-r border-black/40 flex flex-col items-center py-4 gap-4 shrink-0">
          <button onClick={() => { setActiveTab('explorer'); setIsSidebarOpen(true); }} className={`p-2 transition-colors ${activeTab === 'explorer' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="파일 탐색기">
            <Files className="w-6 h-6" />
          </button>
          <button onClick={() => { setActiveTab('search'); setIsSidebarOpen(true); }} className={`p-2 transition-colors ${activeTab === 'search' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="검색">
            <Search className="w-6 h-6" />
          </button>
          {/* 하이브 오케스트레이터 탭 — 경고 수 배지 */}
          <button onClick={() => { setActiveTab('hive'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'hive' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="하이브 마인드">
            <Zap className="w-6 h-6" />
            {orchWarningCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-orange-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {orchWarningCount > 9 ? '9+' : orchWarningCount}
              </span>
            )}
          </button>
          {/* 하이브 로그 익스플로러 탭 */}
          <button onClick={() => { setActiveTab('logs'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'logs' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="하이브 통합 로그">
            <ScrollText className="w-6 h-6" />
            {hiveLogs.length > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-blue-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {hiveLogs.length > 99 ? '99+' : hiveLogs.length}
              </span>
            )}
          </button>
          {/* 메시지 채널 탭 — 읽지 않은 메시지 수 배지 표시 */}
          <button onClick={() => { setActiveTab('messages'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'messages' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="메시지 채널">
            <MessageSquare className="w-6 h-6" />
            {unreadMsgCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {unreadMsgCount > 9 ? '9+' : unreadMsgCount}
              </span>
            )}
          </button>
          {/* 태스크 보드 탭 — 활성 작업 수 배지 표시 */}
          <button onClick={() => { setActiveTab('tasks'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'tasks' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="태스크 보드">
            <ClipboardList className="w-6 h-6" />
            {activeTaskCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-yellow-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {activeTaskCount > 9 ? '9+' : activeTaskCount}
              </span>
            )}
          </button>
          {/* 공유 메모리 탭 */}
          <button onClick={() => { setActiveTab('memory'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'memory' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="공유 메모리">
            <Brain className="w-6 h-6" />
            {memory.length > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-cyan-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {memory.length > 9 ? '9+' : memory.length}
              </span>
            )}
          </button>
          {/* Git 감시 탭 — 충돌 파일 수 배지 표시 */}
          <button onClick={() => { setActiveTab('git'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'git' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="Git 감시">
            <GitBranch className="w-6 h-6" />
            {conflictCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none animate-pulse">
                {conflictCount > 9 ? '9+' : conflictCount}
              </span>
            )}
          </button>
          {/* MCP 관리자 탭 — 설치된 MCP 수 배지 */}
          <button onClick={() => { setActiveTab('mcp'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'mcp' ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`} title="MCP 관리자">
            <Package className="w-6 h-6" />
            {mcpInstalled.length > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-purple-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
                {mcpInstalled.length > 9 ? '9+' : mcpInstalled.length}
              </span>
            )}
          </button>
          {/* 바이브 스킬 관리자 탭 — 설치 수 배지 */}
          <button onClick={() => { setActiveTab('superpowers'); setIsSidebarOpen(true); }} className={`p-2 transition-colors relative ${activeTab === 'superpowers' ? 'text-white border-l-2 border-yellow-400 bg-white/5' : 'text-[#858585] hover:text-white'}`} title="바이브 스킬 관리자">
            <Zap className="w-6 h-6" />
            {spStatus && (
              <span className={`absolute top-1 right-1 w-4 h-4 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none ${
                (spStatus.claude.installed ? 1 : 0) + (spStatus.gemini.installed ? 1 : 0) > 0 ? 'bg-yellow-500' : 'bg-white/20'
              }`}>
                {(spStatus.claude.installed ? 1 : 0) + (spStatus.gemini.installed ? 1 : 0)}
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
          animate={{ width: isSidebarOpen ? sidebarWidth : 0, opacity: isSidebarOpen ? 1 : 0 }}
          className="h-full bg-[#252526] border-r border-black/40 flex flex-col overflow-x-auto overflow-y-hidden custom-scrollbar relative"
        >
          {/* Sidebar Resize Handle */}
          {isSidebarOpen && (
            <div
              onMouseDown={(e) => { e.stopPropagation(); setIsResizingSidebar(true); }}
              className={`absolute right-0 top-0 w-1 h-full cursor-col-resize hover:bg-primary/50 transition-colors z-50 ${isResizingSidebar ? 'bg-primary/50' : ''}`}
            />
          )}
          <div className="h-12 px-5 flex items-center justify-between text-[16px] font-bold uppercase tracking-wider text-[#bbbbbb] shrink-0 border-b border-black/10 min-w-[200px]">
            <span className="flex items-center gap-2.5"><ChevronDown className="w-5 h-5" />{activeTab === 'explorer' ? '파일 탐색기' : activeTab === 'search' ? '검색' : activeTab === 'messages' ? '메시지 채널' : activeTab === 'tasks' ? '태스크 보드' : activeTab === 'memory' ? '공유 메모리' : activeTab === 'git' ? 'Git 감시' : activeTab === 'mcp' ? 'MCP 관리자' : activeTab === 'superpowers' ? '⚡ 바이브 스킬' : activeTab === 'logs' ? '하이브 로그' : '하이브 마인드'}</span>
            <button onClick={() => setIsSidebarOpen(false)} className="hover:bg-white/10 p-1.5 rounded transition-colors"><X className="w-6 h-6" /></button>
          </div>

          <div className="p-5 flex-1 overflow-y-auto overflow-x-auto custom-scrollbar flex flex-col min-w-[200px]">
            {activeTab === 'logs' ? (
              /* ── 하이브 통합 로그 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-3">
                <div className="relative shrink-0">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[#858585]" />
                  <input
                    type="text"
                    value={logFilter}
                    onChange={e => setLogFilter(e.target.value)}
                    placeholder="로그 내용 / 에이전트 검색..."
                    className="w-full bg-[#1e1e1e] border border-white/10 rounded pl-6 pr-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors"
                  />
                </div>
                
                <div className="flex-1 overflow-y-auto space-y-2 custom-scrollbar">
                  {hiveLogs
                    .filter(l => !logFilter || l.agent.toLowerCase().includes(logFilter.toLowerCase()) || (l.trigger_msg && l.trigger_msg.toLowerCase().includes(logFilter.toLowerCase())) || (l.project && l.project.toLowerCase().includes(logFilter.toLowerCase())))
                    .map(log => (
                    <div key={log.id} className="p-2.5 rounded-lg border border-white/10 bg-white/2 text-[11px] hover:border-white/20 transition-colors shadow-sm">
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                            log.agent.toLowerCase().includes('claude') ? 'bg-green-500/20 text-green-400' :
                            log.agent.toLowerCase().includes('gemini') ? 'bg-blue-500/20 text-blue-400' :
                            'bg-white/10 text-white/50'
                          }`}>{log.agent}</span>
                          <span className="text-[9px] text-white/30 font-mono">{log.terminal_id}</span>
                        </div>
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                          log.status === 'success' ? 'bg-green-500/10 text-green-500' :
                          log.status === 'failed' ? 'bg-red-500/10 text-red-500' :
                          'bg-yellow-500/10 text-yellow-500'
                        }`}>{log.status}</span>
                      </div>
                      
                      <p className="text-[#cccccc] leading-snug mb-1.5 break-words font-medium">{log.trigger_msg}</p>
                      
                      {log.files_changed && (
                        <div className="flex items-center gap-1 text-[9px] text-[#858585] mb-1.5 bg-black/20 p-1 rounded overflow-hidden">
                          <Files className="w-2.5 h-2.5 shrink-0" />
                          <span className="truncate">{log.files_changed}</span>
                        </div>
                      )}
                      
                      <div className="flex items-center justify-between text-[9px] font-mono text-[#666666]">
                        <span>{log.project}</span>
                        <span>{log.ts_start.replace('T', ' ').slice(5, 16)}</span>
                      </div>
                    </div>
                  ))}
                  {hiveLogs.length === 0 && (
                    <div className="text-center text-[#858585] text-xs py-10 italic flex flex-col items-center gap-2">
                      <ScrollText className="w-8 h-8 opacity-20" />
                      기록된 로그가 없습니다.
                    </div>
                  )}
                </div>
              </div>
            ) : activeTab === 'messages' ? (
              /* ── 메시지 채널 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-3">
                {/* 메시지 목록 (최신순 — 역순 표시) */}
                <div className="flex-1 overflow-y-auto space-y-3 custom-scrollbar">
                  {messages.length === 0 ? (
                    <div className="text-center text-[#858585] text-sm py-12 flex flex-col items-center gap-3 italic">
                      <MessageSquare className="w-9 h-9 opacity-20" />
                      아직 메시지가 없습니다
                    </div>
                  ) : (
                    [...messages].reverse().map(msg => (
                      <div key={msg.id} className="p-3 rounded-lg border border-white/10 bg-white/2 text-[12px] hover:border-white/20 transition-colors">
                        {/* 발신자 → 수신자 + 타입 배지 */}
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-1.5 font-mono font-bold">
                            <span className="text-success">{msg.from}</span>
                            <span className="text-white/30 font-normal">→</span>
                            <span className="text-accent">{msg.to}</span>
                          </div>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            msg.type === 'handoff'       ? 'bg-yellow-500/20 text-yellow-400' :
                            msg.type === 'request'       ? 'bg-blue-500/20 text-blue-400' :
                            msg.type === 'task_complete' ? 'bg-green-500/20 text-green-400' :
                            msg.type === 'warning'       ? 'bg-red-500/20 text-red-400' :
                            'bg-white/10 text-white/50'
                          }`}>{msg.type}</span>
                        </div>
                        {/* 메시지 본문 */}
                        <p className="text-[#cccccc] leading-relaxed break-words whitespace-pre-wrap text-[12.5px]">{msg.content}</p>
                        {/* 타임스탬프 */}
                        <div className="text-[#858585] mt-2 text-[10px] font-mono">{msg.timestamp.replace('T', ' ')}</div>
                      </div>
                    ))
                  )}
                </div>

                {/* 메시지 작성 폼 */}
                <div className="border-t border-white/5 pt-3 flex flex-col gap-2 shrink-0">
                  {/* 발신자 → 수신자 선택 */}
                  <div className="flex gap-2 items-center">
                    <select value={msgFrom} onChange={e => setMsgFrom(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-2 py-2 text-[12px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
                      <option value="claude">Claude</option>
                      <option value="gemini">Gemini</option>
                      <option value="system">System</option>
                    </select>
                    <span className="text-white/30 text-[12px] px-1">→</span>
                    <select value={msgTo} onChange={e => setMsgTo(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-2 py-2 text-[12px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
                      <option value="all">All</option>
                      <option value="claude">Claude</option>
                      <option value="gemini">Gemini</option>
                    </select>
                  </div>
                  {/* 메시지 유형 선택 */}
                  <select value={msgType} onChange={e => setMsgType(e.target.value)} className="w-full bg-[#3c3c3c] border border-white/5 rounded px-2 py-2 text-[12px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors">
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
                    onCompositionStart={() => { isMsgComposingRef.current = true; }}
                    onCompositionEnd={() => { isMsgComposingRef.current = false; }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        // 엔터 키 입력 시 기본 줄바꿈 동작을 즉시 차단합니다.
                        e.preventDefault();

                        // 한글 조합 중(isComposing)에 엔터가 눌린 경우, 
                        // 브라우저에 따라 KeyDown이 두 번 발생할 수 있으므로 
                        // 이미 메시지가 비워졌다면(전송 완료) 추가 전송을 방지합니다.
                        if (msgContent.trim()) {
                          sendMessage();
                        }
                      }
                    }}
                    placeholder="메시지 입력... (Enter: 전송, Shift+Enter: 줄바꿈, >명령어: 터미널 실행)"
                    rows={4}
                    className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-[13px] focus:outline-none focus:border-primary text-white transition-colors resize-none"
                  />
                  <button
                    onClick={sendMessage}
                    disabled={!msgContent.trim()}
                    className="w-full py-2.5 bg-primary/80 hover:bg-primary disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg text-[13px] font-bold transition-colors shadow-lg"
                  >
                    전송 (Enter)
                  </button>
                </div>
              </div>
            ) : activeTab === 'tasks' ? (
              /* ── 태스크 보드 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-3">
                {/* 상태 필터 탭 */}
                <div className="flex gap-1.5 shrink-0">
                  {(['all', 'pending', 'in_progress', 'done'] as const).map(s => {
                    const label = s === 'all' ? '전체' : s === 'pending' ? '할 일' : s === 'in_progress' ? '진행' : '완료';
                    const count = s === 'all' ? tasks.length : tasks.filter(t => t.status === s).length;
                    return (
                      <button key={s} onClick={() => setTaskFilter(s)} className={`flex-1 py-2 rounded-lg text-[11px] font-bold transition-all ${taskFilter === s ? 'bg-primary text-white shadow-md' : 'bg-white/5 text-[#858585] hover:text-white'}`}>
                        {label}{count > 0 && ` (${count})`}
                      </button>
                    );
                  })}
                </div>

                {/* 작업 목록 */}
                <div className="flex-1 overflow-y-auto space-y-2.5 custom-scrollbar">
                  {tasks.filter(t => taskFilter === 'all' || t.status === taskFilter).length === 0 ? (
                    <div className="text-center text-[#858585] text-sm py-12 flex flex-col items-center gap-3 italic">
                      <ClipboardList className="w-9 h-9 opacity-20" />
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
                          <div 
                            key={task.id} 
                            onContextMenu={(e) => handleTaskContextMenu(e, task.id, task.title)}
                            className={`p-3 rounded-lg border text-[12px] transition-all shadow-sm ${task.status === 'done' ? 'border-white/5 opacity-50 bg-black/10' : 'border-white/10 bg-white/2 hover:border-white/20'}`}
                          >
                            {/* 제목 + 우선순위 */}
                            <div className="flex items-start gap-2 mb-2">
                              <span className="text-[13px] shrink-0">{priorityDot}</span>
                              <span className={`font-bold flex-1 break-words leading-snug text-[13px] ${task.status === 'done' ? 'line-through text-[#858585]' : 'text-[#cccccc]'}`}>{task.title}</span>
                            </div>
                            {/* 설명 (있을 경우) */}
                            {task.description && (
                              <p className="text-[#858585] text-[11px] mb-2.5 leading-relaxed pl-5">{task.description}</p>
                            )}
                            {/* 담당자 + 상태 */}
                            <div className="flex items-center justify-between pl-5 mb-2.5">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
                                task.assigned_to === 'claude'  ? 'bg-green-500/15 text-green-400' :
                                task.assigned_to === 'gemini' ? 'bg-blue-500/15 text-blue-400' :
                                'bg-white/10 text-white/50'
                              }`}>{task.assigned_to}</span>
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                                task.status === 'pending'     ? 'bg-white/10 text-[#858585]' :
                                task.status === 'in_progress' ? 'bg-primary/20 text-primary' :
                                'bg-green-500/20 text-green-400'
                              }`}>{statusLabel}</span>
                            </div>
                            {/* 액션 버튼 */}
                            <div className="flex gap-1.5 pl-5">
                              {task.status === 'pending' && (
                                <button onClick={() => updateTask(task.id, { status: 'in_progress' })} className="flex-1 py-1.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[11px] font-bold transition-colors">▶ 시작</button>
                              )}
                              {task.status === 'in_progress' && (
                                <>
                                  <button onClick={() => updateTask(task.id, { status: 'done' })} className="flex-1 py-1.5 bg-green-500/20 hover:bg-green-500/40 text-green-400 rounded text-[11px] font-bold transition-colors">✅ 완료</button>
                                  <button onClick={() => updateTask(task.id, { status: 'pending' })} className="px-2 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[11px] transition-colors">↩</button>
                                </>
                              )}
                              {task.status === 'done' && (
                                <button onClick={() => updateTask(task.id, { status: 'pending' })} className="flex-1 py-1.5 bg-white/5 hover:bg-white/10 text-[#858585] rounded text-[11px] transition-colors">↩ 다시</button>
                              )}
                              <button onClick={() => deleteTask(task.id)} className="px-2 py-1.5 bg-red-500/10 hover:bg-red-500/25 text-red-400 rounded text-[11px] transition-colors" title="삭제">🗑️</button>
                            </div>
                          </div>
                        );
                      })
                  )}
                </div>

                {/* 새 작업 추가 */}
                {showTaskForm ? (
                  <div className="border-t border-white/5 pt-3 flex flex-col gap-2 shrink-0">
                    <div className="text-[11px] text-[#858585] font-bold uppercase tracking-wider">새 작업 작성</div>
                    <input
                      type="text"
                      value={newTaskTitle}
                      onChange={e => setNewTaskTitle(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') createTask(); if (e.key === 'Escape') setShowTaskForm(false); }}
                      placeholder="작업 제목 (필수)"
                      autoFocus
                      className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-[12px] focus:outline-none focus:border-primary text-white transition-colors"
                    />
                    <input
                      type="text"
                      value={newTaskDesc}
                      onChange={e => setNewTaskDesc(e.target.value)}
                      placeholder="상세 설명 (선택)"
                      className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-3 py-2 text-[12px] focus:outline-none focus:border-primary text-white transition-colors"
                    />
                    <div className="flex gap-2">
                      <select value={newTaskAssignee} onChange={e => setNewTaskAssignee(e.target.value)} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-2 py-2 text-[12px] focus:outline-none cursor-pointer">
                        <option value="all">All</option>
                        <option value="claude">Claude</option>
                        <option value="gemini">Gemini</option>
                      </select>
                      <select value={newTaskPriority} onChange={e => setNewTaskPriority(e.target.value as 'high' | 'medium' | 'low')} className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-2 py-2 text-[12px] focus:outline-none cursor-pointer">
                        <option value="high">🔴 높음</option>
                        <option value="medium">🟡 보통</option>
                        <option value="low">🟢 낮음</option>
                      </select>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={createTask} disabled={!newTaskTitle.trim()} className="flex-1 py-2 bg-primary/80 hover:bg-primary disabled:opacity-30 text-white rounded-lg text-[13px] font-bold transition-colors">추가</button>
                      <button onClick={() => setShowTaskForm(false)} className="px-4 py-2 bg-white/5 hover:bg-white/10 text-[#858585] rounded-lg text-[13px] transition-colors">취소</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setShowTaskForm(true)} className="shrink-0 w-full py-2.5 border border-dashed border-white/15 hover:border-primary/40 hover:bg-primary/5 rounded-lg text-[12px] text-[#858585] hover:text-primary transition-colors flex items-center justify-center gap-2">
                    <Plus className="w-4 h-4" /> 새 작업 추가
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
                {/* 항목 수 요약 + 프로젝트 필터 토글 */}
                <div className="flex items-center justify-between shrink-0 px-0.5">
                  <span className="text-[9px] text-[#858585]">
                    총 {memory.length}개 항목{memSearch && ` (검색: "${memSearch}")`}
                    {currentProjectName && !memShowAll && (
                      <span className="ml-1 text-cyan-600">— {currentProjectName}</span>
                    )}
                  </span>
                  <button
                    onClick={() => setMemShowAll(v => !v)}
                    className={`px-1.5 py-0.5 rounded text-[8px] font-bold transition-colors ${memShowAll ? 'bg-amber-500/20 text-amber-400' : 'bg-white/5 text-[#858585] hover:text-white'}`}
                    title={memShowAll ? '현재 프로젝트만 보기' : '전체 프로젝트 보기'}
                  >
                    {memShowAll ? '전체' : '현재'}
                  </button>
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
                        {/* 전체 모드일 때 출처 프로젝트 배지 */}
                        {memShowAll && entry.project && (
                          <span className="inline-block px-1.5 py-0.5 bg-amber-500/10 text-amber-400 rounded text-[8px] font-mono mb-0.5">{entry.project}</span>
                        )}
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
                              <span className="text-[#858585]">대:{taskDist.pending}</span>
                              <span className="text-primary">진:{taskDist.in_progress}</span>
                              <span className="text-green-400">완:{taskDist.done}</span>
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

                {/* 하이브 시스템 진단 위젯 — 오케스트레이터 대시보드 하단 배치
                    변경 이력: 2026-02-28 Claude — superpowers 탭에서 hive 탭으로 이동
                    이유: 하이브 헬스 진단은 오케스트레이터(Hive Mind) 탭과 의미적으로 일치함 */}
                <div className="shrink-0 p-2 rounded border border-white/10 bg-black/20 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="text-[10px] font-bold text-[#969696] flex items-center gap-1.5 uppercase tracking-tighter">
                      <Cpu className="w-3.5 h-3.5" /> 하이브 시스템 진단
                    </div>
                    <button onClick={fetchHiveHealth} className="p-1 hover:bg-white/10 rounded transition-colors text-[#858585]">
                      <RotateCw className="w-2.5 h-2.5" />
                    </button>
                  </div>

                  {!hiveHealth ? (
                    <div className="text-[9px] text-[#555] italic">진단 데이터 로드 중...</div>
                  ) : (
                    <div className="flex flex-col gap-2">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                        {/* 코어 지침 */}
                        <div className="flex flex-col gap-0.5">
                          <div className="text-[8px] text-[#666] mb-0.5">📜 코어 지침</div>
                          <div className="flex items-center justify-between text-[9px]">
                            <span className="text-[#aaa]">RULES.md</span>
                            {hiveHealth.constitution?.rules_md ? <CheckCircle2 className="w-2.5 h-2.5 text-green-400" /> : <AlertTriangle className="w-2.5 h-2.5 text-red-500" />}
                          </div>
                          <div className="flex items-center justify-between text-[9px]">
                            <span className="text-[#aaa]">CLAUDE.md</span>
                            {hiveHealth.constitution?.claude_md ? <CheckCircle2 className="w-2.5 h-2.5 text-green-400" /> : <AlertTriangle className="w-2.5 h-2.5 text-red-500" />}
                          </div>
                        </div>
                        {/* 하이브 스킬 */}
                        <div className="flex flex-col gap-0.5">
                          <div className="text-[8px] text-[#666] mb-0.5">🧠 핵심 스킬</div>
                          <div className="flex items-center justify-between text-[9px]">
                            <span className="text-[#aaa]">Master Skill</span>
                            {hiveHealth.skills?.master ? <CheckCircle2 className="w-2.5 h-2.5 text-green-400" /> : <AlertTriangle className="w-2.5 h-2.5 text-red-500" />}
                          </div>
                          <div className="flex items-center justify-between text-[9px]">
                            <span className="text-[#aaa]">Memory Script</span>
                            {hiveHealth.skills?.memory_script ? <CheckCircle2 className="w-2.5 h-2.5 text-green-400" /> : <AlertTriangle className="w-2.5 h-2.5 text-red-500" />}
                          </div>
                        </div>
                      </div>

                      {/* 자가 치유 엔진 상태 */}
                      <div className="pt-1 border-t border-white/5 flex flex-col gap-1">
                        <div className="text-[8px] text-[#666] flex items-center justify-between">
                          <span>🛡️ 자가 치유 엔진</span>
                          <span className="text-primary/50">v4.0</span>
                        </div>
                        <div className="flex items-center justify-between text-[9px]">
                          <span className="text-[#aaa]">DB 연결성</span>
                          <span className={hiveHealth.db_ok ? "text-green-400" : "text-red-500"}>{hiveHealth.db_ok ? "정상" : "오류"}</span>
                        </div>
                        <div className="flex items-center justify-between text-[9px]">
                          <span className="text-[#aaa]">에이전트 활동</span>
                          <span className={hiveHealth.agent_active ? "text-green-400" : "text-yellow-500"}>{hiveHealth.agent_active ? "활발" : "유휴"}</span>
                        </div>
                        <div className="flex items-center justify-between text-[9px]">
                          <span className="text-[#aaa]">누적 복구 횟수</span>
                          <span className="text-primary">{hiveHealth.repair_count ?? 0}회</span>
                        </div>
                        {hiveHealth.last_check && (
                          <div className="text-[7px] text-[#444] text-right italic">
                            최근 점검: {new Date(hiveHealth.last_check).toLocaleTimeString()}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {/* 통합 복구 버튼 */}
                  <div className="flex gap-1">
                    <button
                      onClick={() => {
                        if(confirm("모든 누락된 하이브 지침과 스킬을 현재 프로젝트에 자동 복구하시겠습니까?")) {
                          const projectRoot = currentProjectRoot || currentPath || gitPath;
                          fetch(`${API_BASE}/api/install-skills?path=${encodeURIComponent(projectRoot)}`)
                            .then(res => res.json())
                            .then(data => {
                              setSpMsg(data.message);
                              fetchHiveHealth();
                            });
                        }
                      }}
                      className="flex-1 py-1 bg-primary/10 hover:bg-primary/20 text-primary text-[9px] font-bold rounded border border-primary/20 transition-all flex items-center justify-center gap-1"
                    >
                      <Zap className="w-2.5 h-2.5" /> 스킬 복구
                    </button>
                    <button
                      onClick={() => {
                        fetch(`${API_BASE}/api/hive/health/repair`)
                          .then(res => res.json())
                          .then(() => {
                            setSpMsg("하이브 엔진 정밀 진단 및 자가 치유 완료");
                            fetchHiveHealth();
                          });
                      }}
                      className="px-2 py-1 bg-green-500/10 hover:bg-green-500/20 text-green-400 text-[9px] font-bold rounded border border-green-500/20 transition-all flex items-center justify-center gap-1"
                      title="하이브 엔진 정밀 점검"
                    >
                      <Cpu className="w-2.5 h-2.5" /> 자가 치유
                    </button>
                  </div>
                </div>
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
                        <span className="text-green-400">스:{gitStatus.staged.length}</span>
                        <span className="text-yellow-400">수:{gitStatus.unstaged.length}</span>
                        <span className="text-[#858585]">?:{gitStatus.untracked.length}</span>
                        {gitStatus.conflicts.length > 0 && (
                          <span className="text-red-400 font-black animate-pulse">⚠ 충:{gitStatus.conflicts.length}</span>
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
                        {gitStatus.unstaged.slice(0, 15).map(f => (
                          <div key={f} className="group flex items-center justify-between gap-1.5 py-0.5 hover:bg-white/5 rounded px-1 transition-colors">
                            <span className="text-[9px] font-mono text-yellow-300/70 truncate flex-1" title={f}>~{f}</span>
                            <button
                              onClick={() => rollbackFile(f)}
                              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded text-red-400 transition-all shrink-0"
                              title="변경사항 취소 (git checkout)"
                            >
                              <RotateCw className="w-3 h-3 rotate-180" />
                            </button>
                          </div>
                        ))}
                        {gitStatus.unstaged.length > 15 && <div className="text-[8px] text-yellow-400/50 pl-2">... +{gitStatus.unstaged.length - 15}개 더</div>}
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

                {/* 카탈로그 / 검색 뷰 전환 */}
                <div className="flex gap-1 shrink-0 border border-white/10 rounded p-0.5">
                  <button
                    onClick={() => setMcpView('catalog')}
                    className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors ${mcpView === 'catalog' ? 'bg-white/15 text-white' : 'text-[#858585] hover:text-white'}`}
                  >내장 카탈로그</button>
                  <button
                    onClick={() => setMcpView('search')}
                    className={`flex-1 py-1 text-[10px] font-bold rounded transition-colors flex items-center justify-center gap-1 ${mcpView === 'search' ? 'bg-purple-500/30 text-purple-300' : 'text-[#858585] hover:text-white'}`}
                  >
                    <Search className="w-3 h-3" />Smithery 검색
                  </button>
                </div>

                {/* 재시작 필요 안내 배너 */}
                {mcpNeedsRestart && (
                  <div className="flex items-center gap-2 text-[9px] text-yellow-300 bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1 shrink-0">
                    <span>⚠️</span>
                    <span className="flex-1 font-bold">Claude Code · Gemini 재시작해야 MCP가 적용됩니다</span>
                    <button
                      onClick={() => setMcpNeedsRestart(false)}
                      className="text-yellow-400 hover:text-yellow-200 font-bold leading-none"
                      title="닫기"
                    >✕</button>
                  </div>
                )}

                {/* 마지막 작업 결과 메시지 */}
                {mcpMsg && (
                  <div className="text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1 font-mono truncate shrink-0" title={mcpMsg}>
                    {mcpMsg}
                  </div>
                )}

                {mcpView === 'catalog' ? (
                  /* ── 내장 카탈로그 목록 ── */
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
                            <p className="text-[9px] text-[#858585] pl-5 mb-1.5 leading-tight">{entry.description}</p>
                            {entry.requiresEnv && entry.requiresEnv.length > 0 && (
                              <p className="text-[8px] text-yellow-400/70 pl-5 mb-1.5 font-mono">
                                ENV: {entry.requiresEnv.join(', ')}
                              </p>
                            )}
                            <div className="pl-5">
                              {isInstalled ? (
                                <button onClick={() => uninstallMcp(entry.name)} disabled={isLoading}
                                  className="text-[9px] font-bold px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 transition-colors">
                                  {isLoading ? '처리 중...' : '제거'}
                                </button>
                              ) : (
                                <button onClick={() => installMcp(entry)} disabled={isLoading}
                                  className="text-[9px] font-bold px-2 py-0.5 rounded bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors">
                                  {isLoading ? '처리 중...' : '설치'}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                ) : (
                  /* ── Smithery 검색 패널 ── */
                  <div className="flex-1 flex flex-col overflow-hidden gap-2">
                    {/* API 키 설정 영역 */}
                    <div className="shrink-0">
                      {mcpHasKey && !mcpShowKeyInput ? (
                        <div className="flex items-center gap-1.5 text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1">
                          <CheckCircle2 className="w-3 h-3 shrink-0" />
                          <span className="flex-1 font-mono truncate">API Key: {mcpKeyMasked}</span>
                          <button onClick={() => setMcpShowKeyInput(true)}
                            className="text-[#858585] hover:text-white font-bold text-[9px] transition-colors">변경</button>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <p className="text-[9px] text-[#858585]">
                            Smithery API 키 필요 →{' '}
                            <a href="https://smithery.ai/account/api-keys" target="_blank" rel="noreferrer"
                              className="text-purple-400 hover:text-purple-300 underline">smithery.ai/account/api-keys</a>
                          </p>
                          <div className="flex gap-1">
                            <input
                              type="password"
                              value={mcpKeyDraft}
                              onChange={e => setMcpKeyDraft(e.target.value)}
                              onKeyDown={e => e.key === 'Enter' && saveMcpApiKey()}
                              placeholder="sk-..."
                              className="flex-1 bg-white/5 border border-white/15 rounded px-2 py-1 text-[10px] text-white placeholder-[#555] focus:outline-none focus:border-purple-500/50"
                            />
                            <button onClick={saveMcpApiKey} disabled={mcpKeySaving || !mcpKeyDraft.trim()}
                              className="text-[9px] font-bold px-2 py-1 rounded bg-purple-500/30 text-purple-300 hover:bg-purple-500/50 disabled:opacity-40 transition-colors shrink-0">
                              {mcpKeySaving ? '저장 중' : '저장'}
                            </button>
                            {mcpHasKey && (
                              <button onClick={() => { setMcpShowKeyInput(false); setMcpKeyDraft(''); }}
                                className="text-[9px] px-1.5 py-1 rounded bg-white/5 text-[#858585] hover:text-white transition-colors shrink-0">✕</button>
                            )}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 검색 입력 */}
                    <div className="flex gap-1 shrink-0">
                      <input
                        type="text"
                        value={mcpSearchQuery}
                        onChange={e => setMcpSearchQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && searchSmithery(1)}
                        placeholder="검색어 입력 (예: database, browser...)"
                        disabled={!mcpHasKey}
                        className="flex-1 bg-white/5 border border-white/15 rounded px-2 py-1 text-[10px] text-white placeholder-[#555] focus:outline-none focus:border-purple-500/50 disabled:opacity-40"
                      />
                      <button
                        onClick={() => searchSmithery(1)}
                        disabled={!mcpHasKey || mcpSearchLoading || !mcpSearchQuery.trim()}
                        className="text-[9px] font-bold px-2 py-1 rounded bg-purple-500/30 text-purple-300 hover:bg-purple-500/50 disabled:opacity-40 transition-colors shrink-0 flex items-center gap-1"
                      >
                        {mcpSearchLoading ? <RotateCw className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                      </button>
                    </div>

                    {/* 오류 메시지 */}
                    {mcpSearchError && (
                      <div className="text-[9px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1 shrink-0">
                        {mcpSearchError}
                      </div>
                    )}

                    {/* 검색 결과 */}
                    <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
                      {mcpSearchLoading ? (
                        <div className="text-center text-[#858585] text-xs py-8 flex flex-col items-center gap-2">
                          <RotateCw className="w-5 h-5 animate-spin opacity-40" />
                          검색 중...
                        </div>
                      ) : mcpSearchResults.length === 0 && !mcpSearchError ? (
                        <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
                          <Search className="w-7 h-7 opacity-20" />
                          {mcpHasKey ? '검색어를 입력하세요' : 'API 키를 먼저 설정하세요'}
                        </div>
                      ) : (
                        mcpSearchResults.map(server => {
                          const slug = server.qualifiedName.split('/').pop() ?? server.qualifiedName;
                          const isInstalled = mcpInstalled.includes(slug);
                          const isLoading = mcpLoading[server.qualifiedName] ?? false;
                          return (
                            <div key={server.qualifiedName} className={`p-2 rounded border transition-colors ${isInstalled ? 'border-green-500/30 bg-green-500/5' : 'border-white/10 bg-white/2 hover:border-white/20'}`}>
                              <div className="flex items-center gap-1.5 mb-0.5">
                                {isInstalled
                                  ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0" />
                                  : <Circle className="w-3.5 h-3.5 text-[#555] shrink-0" />
                                }
                                <span className="text-[11px] font-bold text-white flex-1 truncate">{server.displayName}</span>
                                {server.verified && (
                                  <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-blue-500/20 text-blue-300">✓ 인증</span>
                                )}
                              </div>
                              <p className="text-[9px] text-[#858585] pl-5 mb-1 leading-tight line-clamp-2">{server.description}</p>
                              <div className="flex items-center gap-1.5 pl-5">
                                <span className="text-[8px] text-[#555] font-mono truncate flex-1">{server.qualifiedName}</span>
                                {server.useCount > 0 && (
                                  <span className="text-[8px] text-[#555]">{server.useCount.toLocaleString()} 사용</span>
                                )}
                                {isInstalled ? (
                                  <button onClick={() => uninstallMcp(slug)} disabled={isLoading}
                                    className="text-[9px] font-bold px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 transition-colors shrink-0">
                                    {isLoading ? '처리 중...' : '제거'}
                                  </button>
                                ) : (
                                  <button onClick={() => installFromSearch(server)} disabled={isLoading}
                                    className="text-[9px] font-bold px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 disabled:opacity-50 transition-colors shrink-0">
                                    {isLoading ? '처리 중...' : '설치'}
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>

                    {/* 페이지네이션 */}
                    {mcpSearchTotalPages > 1 && (
                      <div className="flex items-center justify-between shrink-0 pt-1 border-t border-white/10">
                        <button
                          onClick={() => searchSmithery(mcpSearchPage - 1)}
                          disabled={mcpSearchPage <= 1 || mcpSearchLoading}
                          className="text-[9px] font-bold px-2 py-1 rounded bg-white/5 text-[#858585] hover:text-white disabled:opacity-30 transition-colors"
                        >← 이전</button>
                        <span className="text-[9px] text-[#858585]">
                          {mcpSearchPage} / {mcpSearchTotalPages} ({mcpSearchTotal.toLocaleString()}개)
                        </span>
                        <button
                          onClick={() => searchSmithery(mcpSearchPage + 1)}
                          disabled={mcpSearchPage >= mcpSearchTotalPages || mcpSearchLoading}
                          className="text-[9px] font-bold px-2 py-1 rounded bg-white/5 text-[#858585] hover:text-white disabled:opacity-30 transition-colors"
                        >다음 →</button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : activeTab === 'superpowers' ? (
              /* ── 바이브 스킬 관리자 패널 ── */
              <div className="flex-1 flex flex-col overflow-hidden gap-2">
                {/* 지능형 스킬 제안 */}
                {skillProposals.length > 0 && (
                  <div className="shrink-0 p-2 rounded border border-primary/20 bg-primary/5 flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <div className="text-[10px] font-bold text-primary flex items-center gap-1.5 uppercase tracking-tighter">
                        <Brain className="w-3.5 h-3.5" /> 지능형 스킬 제안
                      </div>
                      <button onClick={fetchSkillAnalysis} className="p-1 hover:bg-white/10 rounded transition-colors text-primary/60">
                        <RotateCw className="w-2.5 h-2.5" />
                      </button>
                    </div>
                    
                    <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto custom-scrollbar pr-1">
                      {skillProposals.map((p, i) => (
                        <div key={i} className="p-1.5 rounded bg-black/30 border border-white/5 flex flex-col gap-1">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-bold text-yellow-300">#{p.keyword}</span>
                            <span className="text-[8px] text-[#666]">{p.count}회 감지</span>
                          </div>
                          <p className="text-[8px] text-[#aaa] leading-tight">{p.description}</p>
                          <button 
                            onClick={() => approveSkill(p)}
                            className="mt-1 py-0.5 bg-primary/20 hover:bg-primary/30 text-primary text-[8px] font-bold rounded transition-all"
                          >
                            스킬 초안 생성
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 상단 설명 */}
                <div className="shrink-0 flex items-center gap-2 px-1 py-1 bg-yellow-500/10 border border-yellow-500/20 rounded text-[9px] text-yellow-300">
                  <Zap className="w-3.5 h-3.5 shrink-0" />
                  <span>AI 에이전트 스킬 프레임워크 — 체계적 개발 워크플로 주입</span>
                </div>

                {/* 메시지 */}
                {spMsg && (
                  <div className="text-[9px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1 font-mono truncate shrink-0" title={spMsg}>
                    {spMsg}
                  </div>
                )}

                {/* Claude Code 카드 */}
                {(['claude', 'gemini'] as const).map(tool => {
                  const info = spStatus?.[tool];
                  const isLoading = spLoading[tool] ?? false;
                  const toolLabel = tool === 'claude' ? 'Claude Code' : 'Gemini CLI';
                  const toolColor = tool === 'claude' ? 'border-[#3794ef]/30 bg-[#3794ef]/5' : 'border-blue-400/30 bg-blue-400/5';
                  const toolBadge = tool === 'claude' ? 'bg-[#3794ef]/20 text-[#3794ef]' : 'bg-blue-400/20 text-blue-300';
                  const repo = info?.repo ?? (tool === 'claude' ? 'btsky99/vibe-coding (내장)' : 'btsky99/vibe-coding (내장)');
                  const commands = info?.commands ?? [];
                  return (
                    <div key={tool} className={`rounded border p-2.5 flex flex-col gap-2 ${info?.installed ? (tool === 'claude' ? 'border-[#3794ef]/40 bg-[#3794ef]/8' : 'border-blue-400/40 bg-blue-400/8') : 'border-white/10 bg-white/2'}`}>
                      {/* 헤더 */}
                      <div className="flex items-center gap-2">
                        {info?.installed
                          ? <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
                          : <Circle className="w-4 h-4 text-[#555] shrink-0" />}
                        <span className="text-[12px] font-bold text-white flex-1">{toolLabel}</span>
                        <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded ${toolBadge}`}>
                          {info?.installed ? `v${info.version ?? 'latest'}` : '미설치'}
                        </span>
                      </div>
                      {/* 리포 링크 */}
                      <p className="text-[9px] text-[#666] pl-6 font-mono">{repo}</p>
                      {/* 스킬 목록 */}
                      {info?.installed && info.skills.length > 0 && (
                        <div className="pl-6 flex flex-wrap gap-1">
                          {info.skills.map(s => (
                            <span key={s} className={`text-[7px] px-1 py-0.5 rounded font-mono ${toolColor}`}>{s}</span>
                          ))}
                        </div>
                      )}
                      {/* 커맨드 목록 */}
                      {info?.installed && (
                        <div className="pl-6 flex flex-col gap-0.5">
                          {commands.map(c => (
                            <span key={c} className="text-[8px] text-yellow-300/70 font-mono">{c}</span>
                          ))}
                        </div>
                      )}
                      {/* 설치 / 제거 버튼 */}
                      <div className="flex gap-1.5 pt-1">
                        {info?.installed ? (
                          <button
                            onClick={() => spUninstall(tool)}
                            disabled={isLoading}
                            className="flex-1 py-1 text-[10px] font-bold rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50"
                          >
                            {isLoading ? '처리 중…' : '제거'}
                          </button>
                        ) : (
                          <button
                            onClick={() => spInstall(tool)}
                            disabled={isLoading}
                            className="flex-1 py-1 text-[10px] font-bold rounded bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 transition-colors disabled:opacity-50"
                          >
                            {isLoading ? '설치 중…' : '설치'}
                          </button>
                        )}
                        <button
                          onClick={fetchSpStatus}
                          className="px-2 py-1 text-[10px] rounded bg-white/5 text-[#858585] hover:text-white transition-colors"
                          title="상태 새로고침"
                        >
                          <RotateCw className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  );
                })}

                {/* 스킬 주입 패널 */}
                <div className="shrink-0 mt-1 flex flex-col gap-0.5">
                  <p className="text-[9px] font-bold text-[#858585] uppercase tracking-wider mb-1">핵심 스킬 — 클릭으로 터미널 주입</p>
                  {VIBE_SKILLS.map(sk => {
                    const claudeInstalled = spStatus?.claude?.installed ?? false;
                    const geminiInstalled = spStatus?.gemini?.installed ?? false;
                    const injectText = claudeInstalled
                      ? sk.claudeCmd
                      : geminiInstalled
                      ? sk.geminiCmd
                      : sk.algo;
                    const isMcp = claudeInstalled || geminiInstalled;
                    return (
                      <div key={sk.name} className="flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-white/5 border border-transparent hover:border-white/10 transition-all group">
                        <Zap className="w-2.5 h-2.5 text-yellow-400/60 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <span className="text-[9px] font-bold text-white/80 font-mono">{sk.name}</span>
                          <span className="text-[8px] text-[#555] ml-1.5">{sk.desc}</span>
                        </div>
                        <button
                          onClick={() => {
                            // 🛑 안전장치 팝업 (Approval Gate)
                            if (sk.name === 'master' || sk.name === 'brainstorm') {
                              if (!confirm(`[안전장치 가동]\n\n강력한 스킬('${sk.name}')을 실행하려고 합니다.\n작업을 시작하기 전, 브레인스토밍 6단계 절차에 따라 계획을 먼저 수립하고 승인을 받겠습니다.\n\n진행할까요?`)) {
                                return; // 사용자가 취소하면 스킬 주입 중단
                              }
                            }
                            // 마지막으로 포커스된 터미널(_vibeActiveSlot)에만 주입
                            window.dispatchEvent(new CustomEvent(`vibe:inject:${_vibeActiveSlot}`, { detail: { text: injectText } }));
                          }}
                          className="shrink-0 opacity-0 group-hover:opacity-100 flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[8px] font-bold transition-all bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30"
                          title={isMcp ? `MCP: ${injectText}` : '알고리즘 직접 주입'}
                        >
                          <Play className="w-2 h-2" />
                          {isMcp ? 'MCP' : '주입'}
                        </button>
                      </div>
                    );
                  })}
                  <p className="text-[8px] text-[#444] mt-1 px-1">
                    {(spStatus?.claude?.installed || spStatus?.gemini?.installed)
                      ? '✓ MCP 연결됨 — 슬래시 커맨드로 실행'
                      : '⚡ MCP 미설치 — 알고리즘 직접 주입'}
                  </p>
                </div>
              </div>
            ) : (
              /* ── 파일 탐색기 ── */
              <>
                {/* 프로젝트 및 드라이브 선택기 */}
                <div className="flex flex-col gap-2.5 mb-4 shrink-0">
                  <div className="flex items-center justify-between px-1 mb-1.5">
                    <span className="text-[12px] font-bold text-[#858585] uppercase tracking-widest">Workspace</span>
                    <button 
                      onClick={openProjectFolder}
                      className="p-1.5 hover:bg-white/10 rounded text-primary transition-colors"
                      title="새 폴더 열기"
                    >
                      <Plus className="w-5 h-5" />
                    </button>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <select
                      value={projects.includes(currentPath) ? currentPath : ""}
                      onChange={(e) => {
                        if (e.target.value === "browse") {
                          openProjectFolder();
                        } else if (e.target.value) {
                          setCurrentPath(e.target.value);
                        }
                      }}
                      className="flex-1 bg-[#3c3c3c] border border-white/5 hover:border-white/20 rounded px-3 py-2 text-[13px] focus:outline-none transition-all cursor-pointer text-white font-medium shadow-sm"
                    >
                      <option value="" disabled>프로젝트 선택...</option>
                      {projects.map(p => (
                        <option key={p} value={p}>{p.split('/').pop() || p}</option>
                      ))}
                      <option value="divider" disabled>──────────</option>
                      <option value="browse">📂 폴더 찾아보기...</option>
                    </select>
                    <button
                      onClick={() => setTreeMode(v => !v)}
                      className={`p-2 rounded-lg border text-[12px] font-bold transition-all shrink-0 ${treeMode ? 'bg-primary/20 border-primary/40 text-primary' : 'bg-[#3c3c3c] border-white/10 text-[#858585] hover:text-white'}`}
                      title={treeMode ? '플랫 뷰로 전환' : '트리 뷰로 전환'}
                    >
                      {treeMode ? '≡' : '⊞'}
                    </button>
                  </div>

                  {/* 드라이브 선택 (보조) */}
                  <select
                    value={drives.find(d => currentPath.startsWith(d)) || ""}
                    onChange={(e) => setCurrentPath(e.target.value)}
                    className="w-full bg-white/5 border border-transparent hover:border-white/10 rounded px-2.5 py-1.5 text-[11px] focus:outline-none transition-all cursor-pointer text-[#858585]"
                  >
                    <option value="" disabled>드라이브 이동...</option>
                    {drives.map(drive => <option key={drive} value={drive}>{drive}</option>)}
                  </select>
                </div>

                <div 
                  className="flex-1 overflow-y-auto space-y-1 custom-scrollbar border-t border-white/5 pt-3"
                  onContextMenu={(e) => e.preventDefault()} // 브라우저 기본 메뉴 방지
                >
                  <div className="flex items-center gap-1 px-3 mb-2">
                    <button 
                      onClick={createFile}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-white/5 hover:bg-white/10 rounded text-[11px] text-[#cccccc] transition-colors"
                      title="새 파일 생성"
                    >
                      <FilePlus className="w-3.5 h-3.5" /> 파일
                    </button>
                    <button 
                      onClick={createDir}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-white/5 hover:bg-white/10 rounded text-[11px] text-[#cccccc] transition-colors"
                      title="새 폴더 생성"
                    >
                      <FolderPlus className="w-3.5 h-3.5" /> 폴더
                    </button>
                    <button 
                      onClick={refreshItems}
                      className="p-1.5 bg-white/5 hover:bg-white/10 rounded text-[#858585] hover:text-white transition-colors"
                      title="새로고침"
                    >
                      <RotateCw className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <button onClick={goUp} className="w-full flex items-center gap-2.5 px-3 py-1.5 hover:bg-[#2a2d2e] rounded text-[13px] transition-colors group">
                    <ChevronLeft className="w-5 h-5 text-[#3794ef] group-hover:-translate-x-1 transition-transform" /> ..
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
                        onDelete={deleteItem}
                        onContextMenu={handleContextMenu}
                        isRenaming={isRenaming}
                        newNameDraft={newNameDraft}
                        setNewNameDraft={setNewNameDraft}
                        onRenameSubmit={handleFileRename}
                        setIsRenaming={setIsRenaming}
                      />
                    ))
                  ) : (
                    /* 플랫 뷰 (기존) */
                    items.map(item => (
                      <div 
                        key={item.path} 
                        className={`group flex items-center gap-0 px-3 py-1 rounded text-[13px] transition-colors relative ${selectedPath === item.path ? 'bg-primary/20 border-l-2 border-primary' : 'hover:bg-[#2a2d2e]'}`}
                        onContextMenu={(e) => handleContextMenu(e, item.path, item.isDir)}
                      >
                        <button
                          onClick={() => handleFileClick(item)}
                          className={`flex-1 flex items-center gap-2.5 py-1 overflow-hidden ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] font-medium'}`}
                        >
                          {item.isDir ? <VscFolder className="w-5 h-5 text-[#dcb67a] shrink-0" /> : getFileIcon(item.name)}
                          {isRenaming === item.path ? (
                            <input
                              autoFocus
                              value={newNameDraft}
                              onChange={e => setNewNameDraft(e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter') handleFileRename(item.path, newNameDraft);
                                if (e.key === 'Escape') setIsRenaming(null);
                              }}
                              onBlur={() => setIsRenaming(null)}
                              className="bg-[#1e1e1e] border border-primary rounded px-1 py-0.5 text-xs text-white outline-none w-full"
                              onClick={e => e.stopPropagation()}
                            />
                          ) : (
                            <span className="truncate">{item.name}</span>
                          )}
                        </button>
                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-all">
                          {!item.isDir && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                window.dispatchEvent(new CustomEvent(`vibe:fillInput:${_vibeActiveSlot}`, { detail: { text: item.path } }));
                              }}
                              className="p-1 hover:bg-white/10 rounded text-primary transition-all shrink-0"
                              title="터미널 입력창으로 경로 보내기"
                            >
                              <Pin className="w-3 h-3" />
                            </button>
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
                            className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary transition-all shrink-0"
                            title="경로 복사"
                          >
                            <ClipboardList className="w-3 h-3" />
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); deleteItem(item.path, item.name); }}
                            className="p-1 hover:bg-red-500/20 text-[#858585] hover:text-red-500 rounded transition-all shrink-0"
                            title="삭제"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
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
              <button onClick={refreshItems} className="p-1.5 hover:bg-white/10 rounded text-primary hover:text-white transition-all hover:rotate-180 duration-500" title="파일 새로고침">
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
                <TerminalSlot key={slotId} slotId={slotId} logs={logs} currentPath={currentPath} terminalCount={terminalCount} locks={locks} messages={messages} tasks={tasks} claudeSpInstalled={spStatus?.claude?.installed ?? false} geminiSpInstalled={spStatus?.gemini?.installed ?? false} contextSessions={contextSessions} geminiContextSessions={geminiContextSessions} />
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
function FileTreeNode({ item, depth, expanded, treeChildren, onToggle, onFileOpen, onDelete, onContextMenu, isRenaming, newNameDraft, setNewNameDraft, onRenameSubmit, setIsRenaming }: {
  item: TreeItem; depth: number;
  expanded: Record<string, boolean>;
  treeChildren: Record<string, TreeItem[]>;
  onToggle: (path: string) => void;
  onFileOpen: (item: TreeItem) => void;
  onDelete: (path: string, name: string) => void;
  onContextMenu: (e: React.MouseEvent, path: string, isDir: boolean) => void;
  isRenaming: string | null;
  newNameDraft: string;
  setNewNameDraft: (val: string) => void;
  onRenameSubmit: (oldPath: string, newName: string) => void;
  setIsRenaming: (val: string | null) => void;
}) {
  const isOpen = expanded[item.path] || false;
  const kids = treeChildren[item.path] || [];
  const indent = depth * 12;
  const isTargetRenaming = isRenaming === item.path;

  if (item.isDir) {
    return (
      <div className="group/node">
        <div
          className="flex items-center hover:bg-[#2a2d2e] rounded transition-colors pr-2"
          onContextMenu={(e) => onContextMenu(e, item.path, true)}
        >
          {/* 화살표: 펼치기/접기 전용 (2026-02-27) */}
          <button
            onClick={(e) => { e.stopPropagation(); onToggle(item.path); }}
            style={{ paddingLeft: `${indent + 6}px` }}
            className="flex items-center py-1 px-1 text-[#858585] hover:text-white shrink-0"
          >
            {isOpen
              ? <ChevronDown className="w-3.5 h-3.5" />
              : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
          {/* 폴더 아이콘 + 이름: 클릭 시 트리 토글 및 선택 (2026-02-28 개선) */}
          <button
            onClick={() => onFileOpen(item)}
            className="flex-1 flex items-center gap-1.5 py-1 text-[13px] text-[#cccccc] overflow-hidden"
          >
            {isOpen
              ? <VscFolderOpened className="w-5 h-5 text-[#dcb67a] shrink-0" />
              : <VscFolder className="w-5 h-5 text-[#dcb67a] shrink-0" />}
            {isTargetRenaming ? (
              <input
                autoFocus
                value={newNameDraft}
                onChange={e => setNewNameDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') onRenameSubmit(item.path, newNameDraft);
                  if (e.key === 'Escape') setIsRenaming(null);
                }}
                onBlur={() => setIsRenaming(null)}
                className="bg-[#1e1e1e] border border-primary rounded px-1 py-0.5 text-xs text-white outline-none w-full"
                onClick={e => e.stopPropagation()}
              />
            ) : (
              <span className="truncate">{item.name}</span>
            )}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(item.path, item.name); }}
            className="opacity-0 group-hover/node:opacity-100 p-1 hover:bg-red-500/20 text-[#858585] hover:text-red-500 rounded transition-all"
            title="폴더 삭제"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
        {isOpen && kids.length === 0 && (
          <div style={{ paddingLeft: `${indent + 32}px` }} className="py-1 text-[11px] text-[#858585] italic">비어 있음</div>
        )}
        {isOpen && kids.map(child => (
          <FileTreeNode key={child.path} item={child} depth={depth + 1}
            expanded={expanded} treeChildren={treeChildren}
            onToggle={onToggle} onFileOpen={onFileOpen} onDelete={onDelete} 
            onContextMenu={onContextMenu} isRenaming={isRenaming} newNameDraft={newNameDraft} 
            setNewNameDraft={setNewNameDraft} onRenameSubmit={onRenameSubmit} setIsRenaming={setIsRenaming} />
        ))}
      </div>
    );
  }
  return (
    <div 
      className="group/node flex items-center hover:bg-primary/20 rounded transition-colors pr-2"
      onContextMenu={(e) => onContextMenu(e, item.path, false)}
    >
      <button
        onClick={() => onFileOpen(item)}
        style={{ paddingLeft: `${indent + 24}px` }}
        className="flex-1 flex items-center gap-2.5 py-1 text-[13px] text-white overflow-hidden"
      >
        {getFileIcon(item.name)}
        {isTargetRenaming ? (
          <input
            autoFocus
            value={newNameDraft}
            onChange={e => setNewNameDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') onRenameSubmit(item.path, newNameDraft);
              if (e.key === 'Escape') setIsRenaming(null);
            }}
            onBlur={() => setIsRenaming(null)}
            className="bg-[#1e1e1e] border border-primary rounded px-1 py-0.5 text-xs text-white outline-none w-full"
            onClick={e => e.stopPropagation()}
          />
        ) : (
          <span className="truncate font-medium text-left">{item.name}</span>
        )}
      </button>
      <div className="flex items-center gap-0.5 opacity-0 group-hover/node:opacity-100 transition-all">
        <button
          onClick={(e) => {
            e.stopPropagation();
            window.dispatchEvent(new CustomEvent(`vibe:fillInput:${_vibeActiveSlot}`, { detail: { text: item.path } }));
          }}
          className="p-1 hover:bg-white/20 rounded text-primary transition-all shrink-0"
          title="터미널 입력창으로 경로 보내기"
        >
          <Pin className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(item.path, item.name); }}
          className="p-1 hover:bg-red-500/20 text-[#858585] hover:text-red-500 rounded transition-all shrink-0"
          title="파일 삭제"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// Git Diff 시각화 컴포넌트
function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n');
  return (
    <div className="font-mono text-[11px] leading-relaxed">
      {lines.map((line, i) => {
        let bgColor = '';
        let textColor = 'text-[#cccccc]';
        if (line.startsWith('+') && !line.startsWith('+++')) {
          bgColor = 'bg-green-500/20';
          textColor = 'text-green-400';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          bgColor = 'bg-red-500/20';
          textColor = 'text-red-400';
        } else if (line.startsWith('@@')) {
          textColor = 'text-primary opacity-70';
          bgColor = 'bg-primary/5';
        }
        return (
          <div key={i} className={`${bgColor} ${textColor} px-2 whitespace-pre-wrap`}>
            {line}
          </div>
        );
      })}
    </div>
  );
}

function FloatingWindow({ file, idx, bringToFront, closeFile }: { file: OpenFile, idx: number, bringToFront: (id: string) => void, closeFile: (id: string) => void }) {
  const [position, setPosition] = useState({ x: 100 + (idx * 30), y: 100 + (idx * 30) });
  const [isMaximized, setIsMaximized] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartPos = useRef({ x: 0, y: 0 });

  const handlePointerDown = (e: React.PointerEvent) => {
    if (isMaximized) return; // 최대화 상태에서는 드래그 금지
    setIsDragging(true);
    bringToFront(file.id);
    dragStartPos.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (isDragging && !isMaximized) {
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

  const toggleMaximize = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsMaximized(!isMaximized);
    bringToFront(file.id);
  };

  return (
    <div 
      onPointerDown={() => bringToFront(file.id)}
      style={{ 
        zIndex: file.zIndex, 
        left: isMaximized ? 0 : position.x, 
        top: isMaximized ? 0 : position.y,
        width: isMaximized ? '100%' : undefined,
        height: isMaximized ? '100%' : undefined,
        resize: isMaximized ? 'none' : 'both', 
        overflow: 'hidden',
        borderRadius: isMaximized ? 0 : '12px',
        transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)'
      }}
      className={`absolute ${isMaximized ? 'w-full h-full' : 'w-[550px] h-[500px]'} min-w-[300px] min-h-[200px] bg-[#1e1e1e]/95 backdrop-blur-xl border border-white/20 shadow-2xl flex flex-col`}
    >
      <div 
        className={`h-10 bg-[#2d2d2d]/90 border-b border-white/10 flex items-center justify-between px-4 shrink-0 ${isMaximized ? 'cursor-default' : 'cursor-move'} select-none`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div className="flex items-center gap-2 text-[#cccccc] font-mono text-sm truncate pointer-events-none">
          {getFileIcon(file.name)}
          {file.name}
        </div>
        <div className="flex items-center gap-1">
          <button 
            onClick={toggleMaximize}
            onPointerDownCapture={e => e.stopPropagation()}
            className="p-1 hover:bg-white/10 rounded text-[#cccccc] transition-colors cursor-pointer"
            title={isMaximized ? "Restore" : "Maximize"}
          >
            {isMaximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          <button 
            onClick={(e) => { e.stopPropagation(); closeFile(file.id); }} 
            onPointerDownCapture={e => e.stopPropagation()}
            className="p-1 hover:bg-white/10 rounded text-[#cccccc] transition-colors cursor-pointer"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
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

function TerminalSlot({ slotId, logs, currentPath, terminalCount, locks, messages, tasks, claudeSpInstalled, geminiSpInstalled, contextSessions, geminiContextSessions }: { slotId: number, logs: LogRecord[], currentPath: string, terminalCount: number, locks: Record<string, string>, messages: AgentMessage[], tasks: Task[], claudeSpInstalled: boolean, geminiSpInstalled: boolean, contextSessions: ContextSession[], geminiContextSessions: ContextSession[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const inputTextareaRef = useRef<HTMLTextAreaElement>(null);
  // FitAddon 참조 보관 (파일 뷰어 토글 시 재조정용)
  const fitAddonRef = useRef<FitAddon | null>(null);
  // ResizeObserver 참조: 터미널 컨테이너 크기 변화 자동 감지용
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [isTerminalMode, setIsTerminalMode] = useState(false);
  const [fileViewerHeight, setFileViewerHeight] = useState(33);
  const [isResizingFileViewer, setIsResizingFileViewer] = useState(false);
  const [activeAgent, setActiveAgent] = useState('');

  // ─── 터미널 파일 뷰어 리사이징 로직 ───────────────────────────────────────
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizingFileViewer) return;
      // 터미널 슬롯 컨테이너 찾기
      const container = xtermRef.current?.closest('.h-full.bg-\\[\\#252526\\]');
      if (container) {
        const rect = container.getBoundingClientRect();
        const newHeight = ((e.clientY - rect.top) / rect.height) * 100;
        if (newHeight > 10 && newHeight < 85) {
          setFileViewerHeight(newHeight);
        }
      }
    };
    const handleMouseUp = () => setIsResizingFileViewer(false);

    if (isResizingFileViewer) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'row-resize';
    } else {
      document.body.style.cursor = 'default';
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizingFileViewer]);
  const [inputValue, setInputValue] = useState('');
  // 한글 입력(IME) 상태 추적용 Ref
  const isComposingRef = useRef(false);
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
  const [showDiff, setShowDiff] = useState(false);
  const [diffContent, setDiffContent] = useState<string>('');

  // 최근 변경 파일 목록 — FS 이벤트에서 누적 (최대 8개)
  interface FileChange { path: string; eventType: string; ts: number; added: number; removed: number; hunks: string[] }
  const [recentChanges, setRecentChanges] = useState<FileChange[]>([]);

  // 컨텍스트 상세 정보 토글 (클릭 시 In/Out/Cache 2행 표시)
  const [showCtxDetail, setShowCtxDetail] = useState(false);
  // showContextPanel 제거됨 — 항상 표시 방식으로 변경 (2026-02-27)
  // activeAgent에 따라 Claude/Gemini 세션 선택 — slotId 번째 세션 사용
  // [2026-02-27] Claude: Gemini 컨텍스트 분기 추가
  const isGeminiAgent = activeAgent === 'gemini';
  const ctxSession = isGeminiAgent
    ? (geminiContextSessions[slotId] ?? null)
    : (contextSessions[slotId] ?? null);
  // 컨텍스트 창 최대 토큰: Claude=200k, Gemini=1M
  const CTX_MAX = isGeminiAgent ? 1000000 : 200000;
  const ctxPct = ctxSession ? Math.round((ctxSession.input_tokens / CTX_MAX) * 100) : 0;
  // ISO 타임스탬프 → 상대 시간 문자열 (예: "3분 전")
  const ctxRelTime = (() => {
    if (!ctxSession?.last_ts) return '';
    const diff = Math.floor((Date.now() - new Date(ctxSession.last_ts).getTime()) / 1000);
    if (diff < 60) return `${diff}초 전`;
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    return `${Math.floor(diff / 86400)}일 전`;
  })();

  // ─── 파일 시스템 이벤트 → 변경 파일 목록 추적 + slot0 자동 뷰어 ───
  useEffect(() => {
    const fsSse = new EventSource(`${API_BASE}/api/events/fs`);
    fsSse.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type !== 'fs_change') return;
        const filePath: string = data.path;
        const evType: string = data.event || 'modified';

        // 모든 슬롯: 최근 변경 파일 목록 누적 (동일 파일은 덮어씀, 최대 8개)
        setRecentChanges(prev => {
          const filtered = prev.filter(c => c.path !== filePath);
          const entry: FileChange = { path: filePath, eventType: evType, ts: Date.now(), added: 0, removed: 0, hunks: [] };
          return [entry, ...filtered].slice(0, 8);
        });

        // 백그라운드: git diff로 +N/-N 줄 수 및 hunk 헤더 파싱
        if (evType !== 'deleted') {
          fetch(`${API_BASE}/api/git/diff?path=${encodeURIComponent(filePath)}&git_path=${encodeURIComponent(currentPath)}`)
            .then(r => r.json())
            .then(d => {
              if (!d.diff) return;
              let added = 0, removed = 0;
              const hunks: string[] = [];
              d.diff.split('\n').forEach((line: string) => {
                if (line.startsWith('+') && !line.startsWith('+++')) added++;
                else if (line.startsWith('-') && !line.startsWith('---')) removed++;
                else if (line.startsWith('@@')) {
                  // "@@ -84,5 +84,8 @@" 에서 줄 번호 추출
                  const m = line.match(/@@ [+-]\d+(?:,\d+)? [+-](\d+)/);
                  if (m) hunks.push(`L${m[1]}`);
                }
              });
              setRecentChanges(prev => prev.map(c =>
                c.path === filePath ? { ...c, added, removed, hunks } : c
              ));
            })
            .catch(() => {});
        }

        // slot0 만 파일 뷰어 자동 열기 (사용자 요청으로 자동 열기 제거)
        if (slotId === 0) {
          setActiveFilePath(filePath);
          // setShowActiveFile(true); // 자동 열기 방지
        }
      } catch (err) { }
    };
    return () => fsSse.close();
  }, [slotId, currentPath]);

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

      // [추가] 터미널 크기 변경 시 백엔드 PTY에 알림 (글자 깨짐 및 중복 방지)
      term.onResize(({ cols, rows }) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
      });

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
      // 창 크기 변경 시 터미널 재조정
      const handleResize = () => fitAddon.fit();
      window.addEventListener('resize', handleResize);
      
      // cleanup을 위해 xtermRef에 이벤트 리스너 제거 함수 보관 (간이 방식)
      (xtermRef.current as any)._handleResize = handleResize;

      return () => {
        // 이 리턴은 setTimeout 내부라 효과가 없지만, 명시적으로 둡니다.
        window.removeEventListener('resize', handleResize);
      };
    }, 50);
  };

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const isImage = activeFilePath ? /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(activeFilePath) : false;
    
    if (activeFilePath && !isImage) {
      const fetchData = () => {
        const targetPath = activeFilePath.includes(':') || activeFilePath.startsWith('/') 
          ? activeFilePath 
          : `${currentPath}/${activeFilePath}`;

        if (showDiff) {
          // Diff 데이터 가져오기
          fetch(`${API_BASE}/api/git/diff?path=${encodeURIComponent(activeFilePath)}&git_path=${encodeURIComponent(currentPath)}`)
            .then(res => res.json())
            .then(data => { if (data.diff !== undefined) setDiffContent(data.diff); })
            .catch(() => {});
        }

        if (showActiveFile) {
          // 일반 파일 내용 가져오기
          setIsActiveFileLoading(true);
          fetch(`${API_BASE}/api/read-file?path=${encodeURIComponent(targetPath)}`)
            .then(res => res.json())
            .then(data => { if (!data.error) setActiveFileContent(data.content); })
            .catch(() => {})
            .finally(() => setIsActiveFileLoading(false));
        }
      };
      
      fetchData();
      interval = setInterval(fetchData, 3000);
    }
    return () => clearInterval(interval);
  }, [showActiveFile, showDiff, activeFilePath, currentPath]);

  // 파일 뷰어 토글 시 xterm 터미널 크기 재조정
  // ResizeObserver가 주 역할이며, 이 타이머는 폴백으로 이중 호출해 안정성 확보
  useEffect(() => {
    if (!fitAddonRef.current) return;
    const t1 = setTimeout(() => fitAddonRef.current?.fit(), 100);
    const t2 = setTimeout(() => fitAddonRef.current?.fit(), 350);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [showActiveFile, fileViewerHeight]);

  const closeTerminal = () => {
    setIsTerminalMode(false);
    setShowActiveFile(false);
    fitAddonRef.current = null;

    // ResizeObserver 및 리사이즈 이벤트 리스너 해제
    if (xtermRef.current) {
      const anyRef = xtermRef.current as any;
      if (anyRef._handleResize) {
        window.removeEventListener('resize', anyRef._handleResize);
        delete anyRef._handleResize;
      }
    }

    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (wsRef.current) wsRef.current.close();
    if (termRef.current) termRef.current.dispose();
  };

  const handleSend = (text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const cleanText = text.replace(/[\r\n]+$/, '');
    if (!cleanText) return;

    // 텍스트와 Enter(\r)를 별도 WebSocket 메시지로 분리 전송.
    // winpty는 멀티캐릭터 문자열 끝에 붙은 \r을 Enter로 처리하지 않는 경우가 있음.
    // xterm.js 키보드 Enter가 \r 단독 메시지로 오는 것과 동일하게 맞춤.
    wsRef.current.send(cleanText.replace(/\n/g, '\r'));
    wsRef.current.send('\r');

    setInputValue('');
    // 전송 후 xterm 터미널로 포커스 이동 — 실행 결과를 보며 바로 터미널 입력 가능
    setTimeout(() => termRef.current?.focus(), 10);
  };

  // Superpowers 스킬 주입 — 이 터미널을 전역 주입 대상으로 등록
  // 마지막으로 포커스된 터미널(또는 유일한 터미널)이 주입을 처리함
  useEffect(() => {
    const handler = (e: Event) => {
      const { text } = (e as CustomEvent<{ text: string }>).detail;
      handleSend(text);
    };
    // 터미널 포커스 시 이 슬롯을 주입 대상으로 등록
    const markActive = () => window.dispatchEvent(new CustomEvent('vibe:activeSlot', { detail: { slotId } }));
    xtermRef.current?.addEventListener('click', markActive);
    // 단일 슬롯이면 자동 등록, 포커스 받으면 재등록
    window.addEventListener(`vibe:inject:${slotId}`, handler);
    // 📌 경로 주입(Fill Input) 이벤트 리스너 추가
    const fillHandler = (e: Event) => {
      const { text } = (e as CustomEvent<{ text: string }>).detail;
      setInputValue(prev => prev ? `${prev} "${text}"` : text);
      setTimeout(() => inputTextareaRef.current?.focus(), 10);
    };
    window.addEventListener(`vibe:fillInput:${slotId}`, fillHandler);

    return () => {
      window.removeEventListener(`vibe:inject:${slotId}`, handler);
      window.removeEventListener(`vibe:fillInput:${slotId}`, fillHandler);
      xtermRef.current?.removeEventListener('click', markActive);
    };
  }, [slotId]);


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
        <div className="flex items-center gap-1.5">
          {!isTerminalMode ? (
            <span className="text-[9px] text-[#858585] font-bold mr-1">에이전트 선택 대기 중...</span>
          ) : (
            <>
              <button
                onClick={() => {
                  if (!showActiveFile) setShowActiveFile(true);
                  setShowDiff(!showDiff);
                }}
                className={`px-2 py-0.5 rounded text-[9px] border transition-all font-bold ${showDiff ? 'bg-accent/40 border-accent text-white' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
                title="Git 변경사항(Diff) 보기"
              >
                ± Diff
              </button>
              <button
                onClick={() => setShowActiveFile(!showActiveFile)}
                className={`px-2 py-0.5 rounded text-[9px] border transition-all font-bold ${showActiveFile ? 'bg-primary/40 border-primary text-white' : 'bg-[#3c3c3c] border-white/5 text-[#cccccc] hover:bg-white/10'}`}
                title="현재 에이전트가 수정중인 파일 보기"
              >
                👀 파일 뷰어
              </button>
              <button onClick={closeTerminal} className="p-0.5 hover:bg-red-500/20 rounded text-red-400 transition-colors"><X className="w-3.5 h-3.5" /></button>
            </>
          )}
        </div>
      </div>

      {/* ── 컨텍스트 컬러 블록 바 — 클릭 시 /context 스타일 상세 팝업 (2026-02-27) ── */}
      {(() => {
        const cacheRead  = ctxSession?.cache_read  ?? 0;
        const cacheWrite = ctxSession?.cache_write ?? 0;
        const inputTok   = ctxSession?.input_tokens ?? 0;
        const outputTok  = ctxSession?.output_tokens ?? 0;
        const freeTok    = Math.max(0, CTX_MAX - inputTok);

        // 각 토큰 타입의 컨텍스트 점유 % (입력 기준)
        const cacheReadPct  = Math.min(100, (cacheRead  / CTX_MAX) * 100);
        const cacheWritePct = Math.min(100, (cacheWrite / CTX_MAX) * 100);
        const inputOnlyPct  = Math.max(0, ctxPct - cacheReadPct - cacheWritePct);
        const freePct       = Math.max(0, 100 - ctxPct);

        // 배경 & 경고 색
        const dangerBg   = ctxPct >= 80 ? 'bg-red-950/30 border-red-500/15'
                         : ctxPct >= 60 ? 'bg-yellow-950/30 border-yellow-500/15'
                         : 'bg-[#0d1117] border-white/5';
        const modelColor = ctxPct >= 80 ? '#f87171' : ctxPct >= 60 ? '#facc15' : '#a3e635';

        // 모델명 단축
        const modelShort = ctxSession
          ? ctxSession.model
              .replace(/^claude-/, '').replace(/^gemini-/, 'Gemini ')
              .replace(/-(\d)/, ' $1').replace(/-latest$/, '').replace(/-\d{8}$/, '')
              .replace(/\b\w/g, c => c.toUpperCase())
          : (isGeminiAgent ? 'Gemini' : 'Claude');

        // 토큰 표시 레이블
        const maxLabel  = CTX_MAX >= 1_000_000 ? `${CTX_MAX/1_000_000}M` : `${CTX_MAX/1000}k`;
        const usedLabel = `${Math.round(inputTok / 1000)}k`;

        // 블록 그리드 색상 결정 (100개 블록, 각 1%)
        const getBlockColor = (idx: number) => {
          const p = idx + 1;
          if (p <= cacheReadPct)                         return '#22d3ee'; // cyan  — 캐시 읽기
          if (p <= cacheReadPct + cacheWritePct)         return '#4ade80'; // green — 캐시 쓰기
          if (p <= cacheReadPct + cacheWritePct + inputOnlyPct) return '#fbbf24'; // amber — 순수 입력
          return '#1e2130'; // 빈 공간
        };

        // 카테고리 목록 (레이블, 토큰 수, %, 색상)
        const pureInput = Math.max(0, inputTok - cacheRead - cacheWrite);
        const categories = [
          { label: '입력 토큰', tok: pureInput,   pct: inputOnlyPct,  color: '#fbbf24' },
          ...(cacheWrite > 0 ? [{ label: '캐시 쓰기', tok: cacheWrite, pct: cacheWritePct, color: '#4ade80' }] : []),
          ...(cacheRead  > 0 ? [{ label: '캐시 읽기', tok: cacheRead,  pct: cacheReadPct,  color: '#22d3ee' }] : []),
          { label: '출력 누적', tok: outputTok,   pct: Math.round((outputTok / CTX_MAX) * 100), color: '#888' },
          { label: '여유 공간', tok: freeTok,     pct: freePct,       color: '#2a2d3a', dim: true },
        ];

        const fmtTok = (t: number) => t >= 1000 ? `${(t/1000).toFixed(1)}k` : `${t}`;

        return (
          <div className="relative shrink-0">
            {/* ── 단일 행 바 (항상 표시) ── */}
            <div
              className={`border-b px-3 py-[3px] flex items-center gap-2 font-mono text-[10px] overflow-hidden cursor-pointer select-none transition-colors hover:brightness-110 ${dangerBg}`}
              onClick={() => setShowCtxDetail(p => !p)}
              title="클릭하여 컨텍스트 상세 보기"
            >
              {/* 컬러 블록 바: 20개 █, 각 5% */}
              <div className="flex shrink-0 leading-none">
                {Array.from({ length: 20 }, (_, idx) => {
                  const p = (idx + 1) * 5;
                  const color = p <= cacheReadPct                              ? '#22d3ee'
                              : p <= cacheReadPct + cacheWritePct              ? '#4ade80'
                              : p <= ctxPct                                    ? '#fbbf24'
                              : '#2a2d3a';
                  return <span key={idx} style={{ color, fontSize: 11, letterSpacing: '-0.5px' }}>█</span>;
                })}
              </div>
              {/* 텍스트: 모델명 · 사용량 */}
              <div className="flex items-center gap-0 whitespace-nowrap flex-1 min-w-0">
                <span className="font-semibold" style={{ color: modelColor }}>{modelShort}</span>
                <span className="text-[#444] mx-1.5">·</span>
                <span className="text-[#ccc]">{usedLabel}/{maxLabel} 토큰 ({ctxPct}%)</span>
                {ctxSession && ctxRelTime && (
                  <span className="text-[#333] ml-2 text-[9px]">{ctxRelTime}</span>
                )}
                <span className="ml-auto text-[#333] text-[8px]">{showCtxDetail ? '▲' : '▼'}</span>
              </div>
              {/* 세션 없을 때 */}
              {!ctxSession && (
                <span className="text-[9px] text-[#333] italic">
                  {isGeminiAgent ? 'Gemini CLI' : 'Claude Code'} 세션 대기 중...
                </span>
              )}
            </div>

            {/* ── 상세 팝업: /context 스타일 블록 그리드 + 카테고리 (클릭 토글) ── */}
            {showCtxDetail && ctxSession && (
              <div className="absolute top-full left-0 right-0 z-50 bg-[#0d1117] border-b border-x border-white/10 shadow-2xl font-mono text-[10px] px-3 pt-2 pb-3 space-y-2">
                {/* 제목 */}
                <div className="text-[#ccc] font-bold text-[11px]">컨텍스트 사용량</div>

                {/* 블록 그리드 10×10 (100블록, 각 1%) */}
                <div className="flex flex-col gap-[2px]">
                  {Array.from({ length: 10 }, (_, row) => (
                    <div key={row} className="flex gap-[2px]">
                      {Array.from({ length: 10 }, (_, col) => (
                        <span key={col} style={{ color: getBlockColor(row * 10 + col), fontSize: 11, lineHeight: 1 }}>█</span>
                      ))}
                    </div>
                  ))}
                </div>

                {/* 카테고리별 사용량 */}
                <div className="pt-1 space-y-[3px]">
                  <div className="text-[#444] text-[9px] mb-1">카테고리별 사용량</div>
                  {categories.map(cat => (
                    <div key={cat.label} className="flex items-center gap-1">
                      <span style={{ color: cat.color }}>■</span>
                      <span style={{ color: cat.dim ? '#444' : '#666' }}>{cat.label}:</span>
                      <span style={{ color: cat.dim ? '#333' : '#bbb' }} className="ml-auto">
                        {fmtTok(cat.tok)}
                      </span>
                      <span className="text-[#444] w-9 text-right">({Math.round(cat.pct)}%)</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })()}
      {isTerminalMode ? (
        <div className="flex-1 flex flex-col min-h-0 bg-[#1e1e1e]">

          {/* ── 최근 변경 파일 목록 패널 (2026-02-27) ── */}
          {recentChanges.length > 0 && (
            <div className="shrink-0 border-b border-white/5 bg-[#161616] px-2 py-1 flex flex-col gap-[2px] max-h-[75px] overflow-y-auto custom-scrollbar">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[8px] text-[#444] uppercase tracking-widest font-bold">변경 파일</span>
                <button
                  onClick={() => setRecentChanges([])}
                  className="text-[8px] text-[#333] hover:text-[#666] transition-colors"
                  title="목록 초기화"
                >✕</button>
              </div>
              {recentChanges.map(ch => {
                // 파일명만 추출 (경로 마지막 부분)
                const fname = ch.path.split('/').pop() || ch.path;
                // 변경 타입 아이콘 + 색상
                const typeLabel = ch.eventType === 'created' ? '+' : ch.eventType === 'deleted' ? 'D' : 'M';
                const typeColor = ch.eventType === 'created' ? 'text-emerald-400' : ch.eventType === 'deleted' ? 'text-red-400' : 'text-yellow-400';
                // 상대 시간
                const sec = Math.floor((Date.now() - ch.ts) / 1000);
                const relT = sec < 60 ? `${sec}s` : sec < 3600 ? `${Math.floor(sec/60)}m` : `${Math.floor(sec/3600)}h`;
                return (
                  <button
                    key={ch.path}
                    onClick={() => { setActiveFilePath(ch.path); setShowActiveFile(true); setShowDiff(ch.eventType !== 'created'); }}
                    className="flex items-center gap-1.5 text-left hover:bg-white/5 rounded px-1 py-[1px] group transition-colors w-full min-w-0"
                    title={ch.path}
                  >
                    {/* 타입 배지 */}
                    <span className={`text-[9px] font-bold w-3 shrink-0 ${typeColor}`}>{typeLabel}</span>
                    {/* 파일명 */}
                    <span className="text-[10px] text-[#ccc] font-mono truncate flex-1 group-hover:text-white">{fname}</span>
                    {/* hunk 줄 번호 (최대 2개) */}
                    {ch.hunks.length > 0 && (
                      <span className="text-[8px] text-[#555] shrink-0 font-mono">
                        {ch.hunks.slice(0, 2).join(' ')}
                        {ch.hunks.length > 2 ? ` +${ch.hunks.length - 2}` : ''}
                      </span>
                    )}
                    {/* +N -N */}
                    {(ch.added > 0 || ch.removed > 0) && (
                      <span className="text-[8px] shrink-0 font-mono">
                        {ch.added > 0 && <span className="text-emerald-500">+{ch.added}</span>}
                        {ch.removed > 0 && <span className="text-red-500 ml-0.5">-{ch.removed}</span>}
                      </span>
                    )}
                    {/* 시간 */}
                    <span className="text-[8px] text-[#333] shrink-0">{relT}</span>
                  </button>
                );
              })}
            </div>
          )}

          {showActiveFile && (
            <div 
              className="border-b border-black/40 bg-[#1a1a1a] flex flex-col shrink-0 relative"
              style={{ height: `${fileViewerHeight}%`, minHeight: '100px', maxHeight: '85%', overflow: 'hidden' }}
            >
              <div className="h-6 bg-[#2d2d2d] px-2 flex items-center justify-between text-[10px] text-[#cccccc] shrink-0 border-b border-white/5 pointer-events-none">
                <span className="truncate flex items-center gap-1 opacity-80 pointer-events-auto">
                  {getFileIcon(activeFilePath || '')} 
                  {activeFilePath ? activeFilePath : "감지된 파일 없음..."}
                </span>
                {isActiveFileLoading && <span className="text-[#3794ef] animate-pulse pointer-events-auto">●</span>}
              </div>
              <div className="flex-1 overflow-auto p-2 custom-scrollbar flex items-center justify-center">
                {/* 이미지 파일이면 img 태그로, 아니면 코드 뷰어/Diff 뷰어로 */}
                {activeFilePath && /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(activeFilePath)
                  ? <img
                      src={`${API_BASE}/api/image-file?path=${encodeURIComponent(activeFilePath.includes(':') || activeFilePath.startsWith('/') ? activeFilePath : `${currentPath}/${activeFilePath}`)}`}
                      alt={activeFilePath}
                      className="max-w-full max-h-full object-contain"
                      style={{ imageRendering: 'auto' }}
                    />
                  : showDiff
                    ? (diffContent ? <DiffViewer diff={diffContent} /> : <span className="text-[10px] text-[#858585] italic">변경된 내용이 없습니다 (Clean)</span>)
                    : (activeFileContent
                        ? <CodeWithLineNumbers content={activeFileContent} fontSize="11px" />
                        : <span className="font-mono text-[11px] text-[#cccccc] italic opacity-40">에이전트가 파일을 수정하거나 경로를 출력할 때까지 대기 중...</span>
                      )
                }
              </div>
              {/* Terminal Panel Resize Handle */}
              <div
                onMouseDown={(e) => { e.stopPropagation(); setIsResizingFileViewer(true); }}
                className={`absolute bottom-0 left-0 w-full h-1 cursor-row-resize hover:bg-primary/50 transition-colors z-20 ${isResizingFileViewer ? 'bg-primary/50' : ''}`}
              />
            </div>
          )}
          {/* overflow-hidden: fit() 재조정 전 xterm이 컨테이너를 넘치는 시각적 오버플로우 차단 */}
          <div className="flex-1 relative min-h-0 overflow-hidden"><div ref={xtermRef} className="absolute inset-0 p-2" /></div>
          
          {/* 터미널 한글 입력 및 단축어 바 */}
          <div className="p-2 border-t border-black/40 bg-[#252526] shrink-0 flex flex-col gap-2 z-10">
            <div className="flex gap-1.5 overflow-x-auto custom-scrollbar pb-0.5 opacity-80 hover:opacity-100 transition-opacity items-center">
               {shortcuts.map((sc, i) => (
                 <button key={i} onClick={() => handleSend(sc.cmd)} className="px-2 py-0.5 bg-[#3c3c3c] hover:bg-white/10 rounded text-[10px] whitespace-nowrap border border-white/5 transition-colors" title={sc.cmd}>
                   {sc.label}
                 </button>
               ))}
               <button onClick={() => setShowShortcutEditor(true)} className="px-2 py-0.5 bg-primary/20 hover:bg-primary/40 text-primary rounded text-[10px] whitespace-nowrap border border-primary/30 font-bold transition-colors">✏️ 편집</button>
            </div>
            <div className="flex gap-2 items-end relative">
              <textarea
                ref={inputTextareaRef}
                value={inputValue}
                onChange={e => {
                  const val = e.target.value;
                  setInputValue(val);
                  // '/'로 시작하면 슬래시 메뉴 자동 팝업
                  if (val.startsWith('/') && val.length >= 1) setShowSlashMenu(true);
                  else if (!val.startsWith('/')) setShowSlashMenu(false);
                }}
                onCompositionStart={() => { isComposingRef.current = true; }}
                onCompositionEnd={() => { isComposingRef.current = false; }}
                onKeyDown={e => {
                  if ((e.key === 'Enter' || e.keyCode === 13) && !e.shiftKey) {
                    // 엔터 키 입력 시 기본 동작(줄바꿈) 차단
                    e.preventDefault();

                    // 한글 조합 중(isComposing)에 엔터가 눌린 경우, 
                    // 브라우저에 따라 KeyDown이 두 번 발생할 수 있으므로 
                    // 이미 입력값이 비워졌다면(전송 완료) 추가 전송을 방지합니다.
                    if (inputValue.trim()) {
                      handleSend(inputValue);
                    }
                  }
                }}
                placeholder="터미널 명령어 전송 (엔터:전송, 쉬프트+엔터:줄바꿈)..."
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
                  <div className="absolute bottom-full right-0 mb-1 w-80 bg-[#252526] border border-white/15 rounded-md shadow-2xl z-50 overflow-hidden">
                    <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center px-3 gap-1.5">
                      <span className="text-primary font-bold text-[11px]">/</span>
                      <span className="text-[11px] font-bold text-[#cccccc] uppercase tracking-wider">
                        {inputValue.startsWith('/') && inputValue.length > 1 ? `"${inputValue}" 검색 중…` : `${activeAgent.toUpperCase()} 커맨드`}
                      </span>
                    </div>
                    <div className="max-h-72 overflow-y-auto custom-scrollbar py-1">
                      {(() => {
                        const allCmds = SLASH_COMMANDS[activeAgent] ?? SLASH_COMMANDS['claude'];
                        // 타이핑 중이면 필터링, 아니면 전체 카테고리별 표시
                        const filter = inputValue.startsWith('/') && inputValue.length > 1 ? inputValue.toLowerCase() : '';
                        const filtered = filter ? allCmds.filter(c => c.cmd.toLowerCase().includes(filter) || c.desc.includes(filter)) : null;

                        const handleCmdClick = (sc: SlashCommand) => {
                          if (sc.injectSkill) {
                            // 바이브 스킬 설치 여부에 따라 올바른 커맨드 선택
                            // 설치됨 → claudeCmd / geminiCmd (실제 슬래시 커맨드)
                            // 미설치  → algo (스킬 내용을 AI에게 텍스트로 주입)
                            const sk = VIBE_SKILLS.find(s => s.name === sc.injectSkill);
                            if (sk) {
                              const claudeInstalled = claudeSpInstalled;
                              const geminiInstalled = geminiSpInstalled;
                              let injectText: string;
                              if (activeAgent === 'claude' && claudeInstalled) {
                                injectText = sk.claudeCmd;
                              } else if (activeAgent === 'gemini' && geminiInstalled) {
                                injectText = sk.geminiCmd;
                              } else {
                                injectText = sk.algo;
                              }
                              handleSend(injectText); // 터미널에 즉시 전송
                            }
                          } else {
                            // 일반 커맨드도 즉시 전송
                            handleSend(sc.cmd);
                          }
                          setShowSlashMenu(false);
                        };

                        if (filtered) {
                          // 필터링 결과 평면 표시
                          if (!filtered.length) return <p className="text-[10px] text-[#555] text-center py-4">일치하는 커맨드 없음</p>;
                          return filtered.map(sc => (
                            <button key={sc.cmd} onClick={() => handleCmdClick(sc)}
                              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-primary/20 text-left group transition-colors">
                              <span className={`font-mono text-[11px] font-bold w-28 shrink-0 transition-colors ${sc.injectSkill ? 'text-yellow-400 group-hover:text-yellow-200' : 'text-primary group-hover:text-white'}`}>{sc.cmd}</span>
                              <span className="text-[#969696] text-[10px] group-hover:text-[#cccccc] transition-colors leading-tight flex-1">{sc.desc}</span>
                              {sc.injectSkill && <span className="text-[7px] bg-yellow-500/20 text-yellow-400 px-1 py-0.5 rounded font-bold shrink-0">⚡주입</span>}
                            </button>
                          ));
                        }

                        // 카테고리별 전체 표시
                        return ['스킬', '설정', '작업', '도움말'].map(cat => {
                          const cmds = allCmds.filter(c => c.category === cat);
                          if (!cmds.length) return null;
                          return (
                            <div key={cat}>
                              <div className={`px-3 py-0.5 text-[9px] font-bold uppercase tracking-widest ${cat === '스킬' ? 'text-yellow-400/60' : 'text-white/25'}`}>{cat}</div>
                              {cmds.map(sc => (
                                <button key={sc.cmd} onClick={() => handleCmdClick(sc)}
                                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-primary/20 text-left group transition-colors">
                                  <span className={`font-mono text-[11px] font-bold w-28 shrink-0 transition-colors ${sc.injectSkill ? 'text-yellow-400 group-hover:text-yellow-200' : 'text-primary group-hover:text-white'}`}>{sc.cmd}</span>
                                  <span className="text-[#969696] text-[10px] group-hover:text-[#cccccc] transition-colors leading-tight flex-1">{sc.desc}</span>
                                  {sc.injectSkill && <span className="text-[7px] bg-yellow-500/20 text-yellow-400 px-1 py-0.5 rounded font-bold shrink-0">⚡주입</span>}
                                </button>
                              ))}
                            </div>
                          );
                        });
                      })()}
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
