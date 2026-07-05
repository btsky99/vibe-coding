/**
 * ------------------------------------------------------------------------
 * 📄 파일명: App.tsx
 * 📂 메인 문서 링크: docs/README.md
 * 📝 설명: 하이브 마인드의 바이브 코딩(Vibe Coding) 프론트엔드 최상위 컴포넌트.
 *          레이아웃 상태, 데이터 폴링, 플로팅 윈도우, 업데이트 관리를 담당하며,
 *          각 기능 영역은 독립 컴포넌트(TopMenuBar, ActivityBar, FileExplorer,
 *          각 패널)로 분리되어 있습니다.
 * REVISION HISTORY:
 * - 2026-04-18 Claude: MessageComposer / MessagesPanel 제거 — 레거시 직접 메시징 UI.
 *                      Phase B 원칙(에이전트끼리 직접 통신 X, 메모리 공유 중심)에 맞춰 정리.
 * - 2026-03-22 Codex: 기본 터미널 레이아웃을 2분할에서 3분할로 변경.
 * - 2026-03-07 Claude: ActivityBar HiveEngineStatus 통합 — globalEngineStage 계산 + hive_health 폴링 추가.
 *                      agentTerminals에서 최고 우선순위 파이프라인 단계를 추출, ActivityBar LED 링에 연동.
 * - 2026-03-02 Claude: TopMenuBar, ActivityBar, FileExplorer, MessageComposer 분리.
 *                      App.tsx 1303→~430줄로 감소. 상태/로직을 책임 영역별 컴포넌트로 이동.
 * - 2026-03-01 Claude: FileTreeNode, FloatingWindow, TerminalSlot을 독립 컴포넌트 파일로 분리.
 *                      공유 상수(API_BASE, getFileIcon 등)는 constants.ts로 이동.
 *                      App.tsx 2200→~1360줄로 감소.
 * - 2026-03-01 Claude: 각 패널 JSX를 독립 컴포넌트(MessagesPanel, TasksPanel, MemoryPanel,
 *                      OrchestratorPanel, HivePanel, GitPanel, SkillResultsPanel)로 교체.
 *                      배지 카운트는 콜백(onUnreadCount, onActiveCount 등)으로 수신하는 방식으로 전환.
 *                      skills 탭 및 Activity Bar 버튼 추가. App.tsx 3289→2197줄으로 대폭 감소.
 * - 2026-03-01 Claude: 파일 탐색기 가로 스크롤 추가 (overflow-auto + min-w-max 래퍼),
 *                      파일명 truncate→whitespace-nowrap 변경, 버튼 overflow-hidden 제거
 * - 2026-03-01 Claude: 사이드바 좌우 드래그 리사이즈 핸들 추가 (sidebarWidth 동적 상태, 150~600px),
 *                      오른쪽 터미널 영역 overflow-y-auto 스크롤 적용, 그리드 min-h-full로 변경
 * - 2026-03-01 Antigravity CLI: 사이드바 VS Code 스타일 UI 복원 (인라인 편집, 호버 버튼 그룹)
 * - 2026-03-01 Antigravity-2: 터미널 초기 레이아웃 2분할로 변경 및 뷰어 창 수동 리사이즈 핸들 도입
 * - 2026-02-24: 한글 입력 엔터 키 처리 로직 개선 반영
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef, useMemo, lazy, Suspense } from 'react';
import { motion } from 'framer-motion';
import { Menu, ChevronRight, ChevronDown, RotateCw, X, Minimize2, Maximize2, ExternalLink } from 'lucide-react';
/* ── 공유 상수/타입 ── */
import { API_BASE, OpenFile, TreeItem } from './constants';
/* ── 데이터 폴링 커스텀 훅 — ClassicApp/OfficeApp 공유 ── */
import { useVibeData } from './hooks/useVibeData';
/* ── 레이아웃 컴포넌트 — App.tsx 2차 분리에서 추출 ── */
import TopMenuBar from './components/TopMenuBar';
import ActivityBar from './components/ActivityBar';
import FileExplorer from './components/FileExplorer';
/* ── 유틸리티 컴포넌트 ── */
// [v3.7.62] FloatingWindow(Monaco Editor ~800kB) → React.lazy() 동적 import
// 파일을 열 때만 로드되므로 초기 번들에서 제외 → 첫 화면 렌더링 대폭 단축
const FloatingWindow = lazy(() => import('./components/FloatingWindow'));
import TerminalSlot from './components/TerminalSlot';
/* ── 오피스 모드 컴포넌트 ── */
const OfficeApp = lazy(() => import('./components/office/OfficeApp'));
/* ── 패널 컴포넌트 (사이드바 직접 렌더링용) ── */
import TasksPanel from './components/panels/TasksPanel';
import MemoryPanel from './components/panels/MemoryPanel';
import ZettelkastenPanel from './components/panels/ZettelkastenPanel';
import HivePanel from './components/panels/HivePanel';
import GitPanel from './components/panels/GitPanel';
import TaskBoardPanel from './components/panels/TaskBoardPanel';
import TelegramPanel from './components/panels/TelegramPanel';
import ToolsPanel from './components/panels/ToolsPanel';
import HealPanel from './components/panels/HealPanel';
import SetupBanner from './components/SetupBanner';

// 레이아웃 모드 타입 정의 — TopMenuBar와 공유 (9분할 추가)
type LayoutMode = '1' | '2' | '3' | '4' | '2x2' | '6' | '8' | '9';

function App() {

  // ─── 공유 데이터 훅 — 모든 폴링/SSE/상태를 useVibeData로 통합 ──────
  const vibe = useVibeData();
  const {
    logs, setLogs, messages, memory, locks,
    agentTerminals, globalPipelineStage, skillChain,
    antigravityUsage, claudeUsage, agentQuota,
    hiveHealth, hiveActivity, isHealingActive,
    appVersion, updateReady, setUpdateReady, updateApplying, setUpdateApplying,
    updateChecking, setUpdateChecking,
    activeTaskCount, setActiveTaskCount,
    totalGitChanges, setTotalGitChanges,
    conflictCount, setConflictCount,
    isAgentRunning, setIsAgentRunning,
    currentPath, setCurrentPath,
  } = vibe;

  // ─── 경량 소스 업데이트 채널(boot.py A안) ──────────────────────────────
  // EXE 풀빌드(updateReady)와 독립된 빠른 .py 갱신 채널. 둘이 동시에 뜨면 풀빌드 우선.
  const [softUpdate, setSoftUpdate] = useState<{ ready: boolean; remote_sha?: string; reason?: string } | null>(null);
  const [softApplying, setSoftApplying] = useState(false);

  // ─── 레이아웃 상태 ────────────────────────────────────────────────────
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState('explorer');
  // activeMenu: 상단 메뉴 드롭다운 활성 상태 — 루트 div 클릭으로 닫기 위해 App에서 관리
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  // 칸반 보드 팝아웃 모드 — 드래그 가능한 플로팅 윈도우로 표시
  const [isKanbanExpanded, setIsKanbanExpanded] = useState(false);
  // 칸반 팝업 위치/크기 — 열릴 때마다 화면 중앙에서 시작, 드래그로 자유롭게 이동 가능
  const initKanbanSize = { width: Math.min(window.innerWidth * 0.85, 1300), height: Math.min(window.innerHeight * 0.82, 820) };
  const [kanbanPos, setKanbanPos] = useState({
    x: Math.round((window.innerWidth  - initKanbanSize.width)  / 2),
    y: Math.round((window.innerHeight - initKanbanSize.height) / 2),
  });
  const [kanbanSize, setKanbanSize] = useState(initKanbanSize);
  const kanbanDragStart = useRef({ x: 0, y: 0 });
  const kanbanResizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });
  const [isKanbanDragging, setIsKanbanDragging] = useState(false);
  const [isKanbanResizing, setIsKanbanResizing] = useState(false);
  // 칸반 전체화면 토글 — 플로팅 창 뷰포트 전체 점유 모드
  const [isKanbanMaximized, setIsKanbanMaximized] = useState(false);
  // 사이드바 너비 — 드래그 리사이즈로 동적 조절 (최소 150px, 최대 600px)
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const isResizingSidebar = useRef(false);
  const sidebarResizeStartX = useRef(0);
  const sidebarResizeStartWidth = useRef(260);
  // 터미널 레이아웃 모드 — '2x2'는 parseInt 불가, 직접 매핑
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('3');
  const terminalCountMap: Record<string, number> = { '1':1, '2':2, '3':3, '4':4, '2x2':4, '6':6, '8':8, '9':9 };
  const terminalCount = terminalCountMap[layoutMode] ?? 3;
  const orchWarningCount = 0; // OrchestratorPanel 통합 후 미사용

  // ─── 플로팅 윈도우 상태 (파일 퀵 뷰) ─────────────────────────────────
  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [_maxZIndex, setMaxZIndex] = useState(100);

  // ─── 설정 팝업 상태 (메인 창 내부 팝업용) ──────────────────────────────
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsZIndex, setSettingsZIndex] = useState(1000);

  // ─── 파일 목록 강제 새로고침 트리거 (헤더 새로고침 버튼 → FileExplorer) ──
  const [fileRefreshKey, setFileRefreshKey] = useState(0);

  // [2026-06-21] 설치본 빈-패널 사고 대응 — 백엔드가 활성 프로젝트를 못 잡으면(project_unresolved)
  // 하이브/제텔/태스크가 phantom project_id로 0건 조회된다. 그 상태를 배너로 노출해 폴더 선택을 유도.
  const [projectUnresolved, setProjectUnresolved] = useState(false);
  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then(r => r.json())
      .then(cfg => setProjectUnresolved(!!cfg?.project_unresolved))
      .catch(() => { /* 서버 미실행 시 무시 */ });
  }, [currentPath]);

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

  // 업데이트 적용 — 에러 발생 시 사용자에게 알림 메시지 표시
  const applyUpdate = () => {
    setUpdateApplying(true);
    fetch(`${API_BASE}/api/apply-update`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setUpdateReady(null);
        } else {
          alert(`업데이트 적용 실패: ${data.error || '알 수 없는 오류'}\n경로: ${data.path || '(없음)'}`);
        }
      })
      .catch((err) => alert(`업데이트 요청 실패: ${err}`))
      .finally(() => setUpdateApplying(false));
  };

  // 경량 소스 업데이트 폴링 — 60초 주기로 main 커밋 SHA 갱신 여부 확인.
  // 서버가 백그라운드로 원격 SHA를 갱신하고, 여기서는 캐시된 ready 상태만 읽는다.
  useEffect(() => {
    const checkSoft = () => {
      fetch(`${API_BASE}/api/soft-update/check`)
        .then(res => res.json())
        .then(data => setSoftUpdate(data?.ready ? data : null))
        .catch(() => {});
    };
    checkSoft();
    const id = setInterval(checkSoft, 60000);
    return () => clearInterval(id);
  }, []);

  // 경량 소스 업데이트 적용 — git reset --hard origin/main + EXE 재시작(boot.py 재진입)
  const applySoftUpdate = () => {
    setSoftApplying(true);
    fetch(`${API_BASE}/api/soft-update/apply`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (data.success) setSoftUpdate(null);
        else alert(`소스 업데이트 실패: ${data.error || '알 수 없는 오류'}`);
      })
      .catch((err) => alert(`소스 업데이트 요청 실패: ${err}`))
      .finally(() => setSoftApplying(false));
  };

  // 폴더 열기 — TopMenuBar "파일 → 폴더 열기" 전용 (FileExplorer 자체 버튼과 별개)
  const openFolder = async () => {
    try {
      if ((window as any).pywebview?.api?.select_folder) {
        const data = await (window as any).pywebview.api.select_folder();
        if (data.status === 'success' && data.path) setCurrentPath(data.path);
        return;
      }
      const res = await fetch(`${API_BASE}/api/select-folder`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success' && data.path) setCurrentPath(data.path);
    } catch {
      // 다이얼로그 실패 시 prompt 폴백
      const path = prompt('프로젝트 폴더 경로를 입력하세요:', currentPath);
      if (path) setCurrentPath(path.trim().replace(/\\/g, '/'));
    }
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


  // 도움말 문서 — 플로팅 윈도우로 열기 (이미 열린 경우 앞으로 가져오기)
  // setMaxZIndex 함수형 업데이트로 stale closure 방지 (bringToFront와 동일 패턴)
  const openHelpDoc = (topic: string, title: string) => {
    const existing = openFiles.find(f => f.path === `help:${topic}`);
    if (existing) { bringToFront(existing.id); return; }
    const newId = Date.now().toString();
    setMaxZIndex(prev => {
      const newZIndex = prev + 1;
      setOpenFiles(files => [...files, {
        id: newId, name: title, path: `help:${topic}`,
        content: 'Loading...', isLoading: true, zIndex: newZIndex
      }]);
      return newZIndex;
    });
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
  // setMaxZIndex 콜백 안에서 setOpenFiles를 호출해 stale closure 방지
  const bringToFront = (id: string) => {
    setMaxZIndex(prev => {
      const newZ = prev + 1;
      setOpenFiles(files => files.map(f => f.id === id ? { ...f, zIndex: newZ } : f));
      return newZ;
    });
  };

  const bringSettingsToFront = () => {
    setMaxZIndex(prev => {
      const newZ = prev + 1;
      setSettingsZIndex(newZ);
      return newZ;
    });
    setIsSettingsOpen(true);
  };

  const closeFile = (id: string) => setOpenFiles(prev => prev.filter(f => f.id !== id));

  const updateFileContent = (id: string, newContent: string) =>
    setOpenFiles(prev => prev.map(f => f.id === id ? { ...f, content: newContent } : f));

  const normalizePreviewPath = (rawPath: string) => {
    const trimmed = rawPath.trim().replace(/^[("'`[{<]+/, '').replace(/[),\].!?'"`}>]+$/, '');
    if (!trimmed) return '';

    const withoutHashLine = trimmed.replace(/#L\d+(?:C\d+)?$/i, '');
    const lineSuffixMatch = withoutHashLine.match(/:(\d+)(?::\d+)?$/);
    if (!lineSuffixMatch) return withoutHashLine;

    const colonIndex = lineSuffixMatch.index ?? -1;
    const lastSlashIndex = Math.max(withoutHashLine.lastIndexOf('/'), withoutHashLine.lastIndexOf('\\'));
    return colonIndex > lastSlashIndex ? withoutHashLine.slice(0, colonIndex) : withoutHashLine;
  };

  const openFileWindow = (targetPath: string, fileName?: string) => {
    const existing = openFiles.find(f => f.path === targetPath);
    if (existing) { bringToFront(existing.id); return; }

    const newId = Date.now().toString();
    const displayName = fileName || targetPath.split(/[\\/]/).pop() || targetPath;
    const isImg = /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(displayName);

    setMaxZIndex(prev => {
      const newZIndex = prev + 1;
      setOpenFiles(files => [...files, {
        id: newId,
        name: displayName,
        path: targetPath,
        content: isImg ? '' : 'Loading...',
        isLoading: !isImg,
        zIndex: newZIndex
      }]);
      return newZIndex;
    });

    if (!isImg) {
      fetch(`${API_BASE}/api/read-file?path=${encodeURIComponent(targetPath)}`)
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
  // setMaxZIndex 함수형 업데이트로 stale closure 방지 (bringToFront와 동일 패턴)
  const handleOpenFile = (item: TreeItem) => {
    openFileWindow(item.path, item.name);
  };

  // 터미널 슬롯 인덱스 배열 — terminalCount가 변경될 때만 배열 재생성 (useMemo로 최적화)
  const slots = useMemo(() => Array.from({ length: terminalCount }, (_, i) => i), [terminalCount]);

  // 사이드바 탭 제목 매핑
  const sidebarTitle = {
    explorer: '파일 탐색기',
    search: '파일 검색',
    messages: '메시지 채널',
    tasks: '태스크보드',
    memory: '공유 메모리',
    hive: '하이브 진단 / 스킬',
    git: 'Git 감시',
    heal: '자가치유 계측',
  }[activeTab] ?? activeTab;

  return (
    <div
      className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden font-sans flex-col"
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

      {/* ── 소스 업데이트(빠름) 배너 — boot.py 경량 채널. 초록으로 풀빌드(파랑)와 구분 ── */}
      {/* 풀빌드 업데이트가 동시에 떠 있으면 그쪽을 우선 표시(중복 배너 방지) */}
      {softUpdate?.ready && !updateReady && (
        <div className="flex items-center justify-between px-3 py-1 bg-emerald-500/20 border-b border-emerald-500/40 shrink-0 z-50">
          <span className="text-[10px] text-emerald-400 font-bold">
            소스 업데이트(빠름) 준비됨 <span className="font-mono">{softUpdate.remote_sha?.slice(0, 7)}</span> — 풀빌드 없이 즉시 반영
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={applySoftUpdate}
              disabled={softApplying}
              className="text-[9px] font-bold px-2 py-0.5 rounded bg-emerald-500 text-white hover:bg-emerald-500/80 disabled:opacity-50 transition-colors"
            >
              {softApplying ? '적용 중...' : '소스 업데이트'}
            </button>
            <button
              onClick={() => setSoftUpdate(null)}
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
        onOpenHelpDoc={openHelpDoc}
        onClearLogs={() => setLogs([])}
        currentPath={currentPath}
        onSwitchProject={(path) => setCurrentPath(path)}
        ptySessionsSummary={vibe.ptySessionsSummary}
      />

      {/* ── 프로젝트 미해석 배너 — 설치본이 활성 프로젝트를 못 잡았을 때 폴더 선택 유도 ── */}
      {projectUnresolved && (
        <div className="flex items-center gap-3 px-4 py-2 text-[12px] bg-amber-900/40 border-b border-amber-700/50 text-amber-200">
          <span>⚠️ 활성 프로젝트가 설정되지 않아 하이브/제텔/태스크가 비어 보입니다.</span>
          <button
            onClick={openFolder}
            className="px-2 py-0.5 rounded bg-amber-700/60 hover:bg-amber-600 text-amber-50"
          >
            프로젝트 폴더 선택
          </button>
        </div>
      )}

      {/* ── Setup Doctor 배너 — 미완료 설정 항목이 있을 때만 표시 ── */}
      <SetupBanner onNavigate={(tab) => setActiveTab(tab)} />

      <div className="flex flex-1 overflow-hidden">
        {/* ── 좌측 액티비티 바 컴포넌트 ── */}
        <ActivityBar
          activeTab={activeTab}
          onTabChange={(tab) => {
            // 칸반 보드 + 스킬 결과는 팝업으로 열기 — 좁은 사이드바로는 내용을 보기 어려움
            if (tab === 'kanban' || tab === 'skills') {
              setIsKanbanExpanded(true);
              return;
            }
            setActiveTab(tab);
            setIsSidebarOpen(true);
          }}
          onOpenSettings={bringSettingsToFront}
          skillChainStatus={skillChain.status}
          orchWarningCount={orchWarningCount}
          activeTaskCount={activeTaskCount}
          memoryCount={memory.length}
          conflictCount={conflictCount}
          totalGitChanges={totalGitChanges}
          isAgentRunning={isAgentRunning}
          globalPipelineStage={globalPipelineStage}
          hiveHealth={hiveHealth}
          isHealingActive={isHealingActive}
        />

        {/* ── 사이드바 — 탭 패널 + 메시지 작성창 ── */}
        <motion.div
          animate={{ width: isSidebarOpen ? sidebarWidth : 0, opacity: isSidebarOpen ? 1 : 0 }}
          className="h-full bg-[#252526] border-r border-black/40 flex flex-col overflow-hidden"
          style={{ minWidth: isSidebarOpen ? 150 : 0 }}
        >
          {/* 사이드바 헤더 — 현재 탭 제목 + (칸반 탭 시 팝아웃 버튼) + 닫기 버튼 */}
          <div className="h-9 px-4 flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb] shrink-0 border-b border-black/10">
            <span className="flex items-center gap-1.5">
              <ChevronDown className="w-3.5 h-3.5" />{sidebarTitle}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setIsSidebarOpen(false)}
                className="hover:bg-white/10 p-0.5 rounded transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* 패널 컨텐츠 */}
          <div className="p-3 flex-1 overflow-hidden flex flex-col">
            {activeTab === 'tasks' ? (
              /* 태스크 보드 패널 (리스트 뷰) */
              <TasksPanel onActiveCount={setActiveTaskCount} />
            ) : activeTab === 'memory' ? (
              /* 공유 메모리 패널 */
              <MemoryPanel currentProjectName={currentPath.split(/[/\\]/).filter(Boolean).pop()} />
            ) : activeTab === 'zettel' ? (
              /* 제텔카스텐 패널 — 카파시+루만 융합 메모 시스템 */
              <ZettelkastenPanel />
            ) : activeTab === 'hive' ? (
              /* 하이브 진단 패널 */
              <HivePanel />
            ) : activeTab === 'git' ? (
              /* Git 감시 패널 */
              <GitPanel
                currentPath={currentPath}
                onChangesCount={(c, conf) => { setTotalGitChanges(c); setConflictCount(conf); }}
              />
            ) : activeTab === 'telegram' ? (
              /* 텔레그램 브릿지 설정 패널 — 봇 토큰 + T1~T8 채팅 ID 관리 */
              <TelegramPanel />
            ) : activeTab === 'tools' ? (
              /* 개발 도구 설치 관리 패널 — TOOL_REGISTRY 연동 */
              <ToolsPanel />
            ) : activeTab === 'heal' ? (
              /* 자가치유 계측 패널 — 4장치 성과+커버리지 진단 */
              <HealPanel />
            ) : null}
            {/* [성능 최적화] 파일 탐색기는 항상 마운트 유지 — 탭 전환 시 재마운트로 인한
                API 재호출(drives, projects, config, files) 지연을 방지.
                다른 탭 활성 시 display:none으로 숨김 처리하여 DOM 유지 + 상태 보존 */}
            <div className={`flex-1 overflow-hidden flex flex-col ${activeTab === 'explorer' ? '' : 'hidden'}`}>
              <FileExplorer
                currentPath={currentPath}
                onPathChange={setCurrentPath}
                onOpenFile={handleOpenFile}
                refreshKey={fileRefreshKey}
              />
            </div>

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
                {currentPath.split(/[/\\]/).filter(Boolean).map((p, i) => (
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
                {(['1', '2', '3', '4', '2x2', '6', '8', '9'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setLayoutMode(mode)}
                    className={`px-1.5 h-5 rounded text-[10px] font-bold transition-all ${layoutMode === mode ? 'bg-primary text-white' : 'hover:bg-white/5 text-[#858585]'}`}
                    title={mode === '4' ? '4 분할 (가로 4열)' : mode === '2x2' ? '4 분할 (2×2 격자)' : mode === '6' ? '6 분할 (3×2 격자)' : mode === '8' ? '8 분할 (4×2 격자)' : mode === '9' ? '9 분할 (3×3 격자)' : `${mode} 분할`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
          </header>

          {/* 터미널 그리드 — layoutMode에 따른 열/행 분할 */}
          <main className="flex-1 min-w-0 min-h-0 p-2 bg-[#1e1e1e] overflow-x-auto overflow-y-hidden">
            <div className={`h-full min-w-0 min-h-0 w-full gap-2 grid ${
              layoutMode === '1' ? 'grid-cols-1' :
              layoutMode === '2' ? 'grid-cols-2' :
              layoutMode === '3' ? 'grid-cols-3' :
              layoutMode === '4' ? 'grid-cols-4' :
              layoutMode === '2x2' ? 'grid-cols-2 grid-rows-2' :
              layoutMode === '6' ? 'grid-cols-3 grid-rows-2' :
              layoutMode === '8' ? 'grid-cols-4 grid-rows-2' :
              'grid-cols-3 grid-rows-3'
            }`} style={{ gridAutoRows: '1fr' }}>
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
                  antigravityUsage={antigravityUsage}
                  claudeUsage={claudeUsage}
                  agentQuota={agentQuota}
                  agentTerminals={agentTerminals}
                  orchestratorData={skillChain}
                  hiveActivity={hiveActivity}
                />
              ))}
            </div>
          </main>
        </div>
      </div>

      {/* ── 칸반 보드 드래그 가능 플로팅 윈도우 — 다른 모니터로도 이동 가능 ── */}
      {isKanbanExpanded && (
        <div
          className={`fixed z-[9999] bg-[#1e1e1e] flex flex-col overflow-hidden shadow-2xl transition-none ${
            isKanbanMaximized
              ? 'border-0 rounded-none'
              : 'border border-white/15 rounded-lg'
          }`}
          style={isKanbanMaximized ? {
            // 전체화면: pywebview 네이티브 창 전체를 점유 (인터넷 브라우저 창 없음)
            left: 0, top: 0, width: '100vw', height: '100vh',
            cursor: 'default',
          } : {
            left: kanbanPos.x,
            top: kanbanPos.y,
            width: kanbanSize.width,
            height: kanbanSize.height,
            minWidth: 600,
            minHeight: 300,
            cursor: isKanbanDragging ? 'grabbing' : 'default',
          }}
          onPointerMove={e => {
            if (isKanbanDragging) {
              // 드래그 중 — 윈도우 위치 업데이트
              setKanbanPos({
                x: e.clientX - kanbanDragStart.current.x,
                y: e.clientY - kanbanDragStart.current.y,
              });
            } else if (isKanbanResizing) {
              // 리사이즈 중 — 윈도우 크기 업데이트 (최소 크기 제한)
              const dw = e.clientX - kanbanResizeStart.current.x;
              const dh = e.clientY - kanbanResizeStart.current.y;
              setKanbanSize({
                width:  Math.max(600, kanbanResizeStart.current.w + dw),
                height: Math.max(300, kanbanResizeStart.current.h + dh),
              });
            }
          }}
          onPointerUp={() => { setIsKanbanDragging(false); setIsKanbanResizing(false); }}
        >
          {/* 팝아웃 헤더 — grab 커서로 드래그 가능 */}
          <div
            className="h-10 px-4 flex items-center justify-between bg-[#252526] border-b border-black/40 shrink-0 select-none"
            style={{ cursor: isKanbanMaximized ? 'default' : (isKanbanDragging ? 'grabbing' : 'grab') }}
            onPointerDown={e => {
              // 전체화면 모드에서는 드래그 비활성화
              if (isKanbanMaximized) return;
              setIsKanbanDragging(true);
              kanbanDragStart.current = {
                x: e.clientX - kanbanPos.x,
                y: e.clientY - kanbanPos.y,
              };
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            }}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb]">
                오케스트레이션 보드
              </span>
              {/* 전체화면이 아닐 때만 드래그 힌트 표시 */}
              {!isKanbanMaximized && (
                <span className="text-[9px] text-[#555] select-none">⠿ 드래그로 이동</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              {/* 네이티브 창으로 열기 — PySide6 OS 네이티브 데스크톱 창 실행 (브라우저 창 X) */}
              <button
                onPointerDown={e => e.stopPropagation()}
                onClick={() => {
                  // window.open() 대신 백엔드 API로 PySide6 kanban_board.py 실행
                  // — window.open은 인터넷 브라우저 창으로 열리는 문제 해결
                  fetch(`${API_BASE}/api/kanban/launch`, { method: 'POST' }).catch((err) => console.error('[App] fetch error:', err));
                }}
                className="hover:bg-white/10 p-1 rounded transition-colors"
                title="네이티브 창으로 열기"
              >
                <ExternalLink className="w-4 h-4 text-[#aaa]" />
              </button>
              {/* 전체화면 토글 — pywebview 네이티브 창 안에서 최대화 (브라우저 창 X) */}
              <button
                onPointerDown={e => e.stopPropagation()}
                onClick={() => setIsKanbanMaximized(v => !v)}
                className="hover:bg-white/10 p-1 rounded transition-colors"
                title={isKanbanMaximized ? '창 크기 복원' : '전체화면으로 확장'}
              >
                {isKanbanMaximized
                  ? <Minimize2 className="w-4 h-4 text-[#aaa]" />
                  : <Maximize2 className="w-4 h-4 text-[#aaa]" />
                }
              </button>
              <button
                onPointerDown={e => e.stopPropagation()}
                onClick={() => { setIsKanbanMaximized(false); setIsKanbanExpanded(false); }}
                className="hover:bg-white/10 p-1 rounded transition-colors"
                title="닫기"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* 태스크보드 패널 — 플로팅 윈도우 내부 (스킬결과 + 칸반 통합) */}
          <div className="flex-1 overflow-hidden p-3">
            <TaskBoardPanel />
          </div>

          {/* 우하단 리사이즈 핸들 */}
          <div
            className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
            style={{ background: 'linear-gradient(135deg, transparent 50%, rgba(255,255,255,0.15) 50%)' }}
            onPointerDown={e => {
              e.stopPropagation();
              setIsKanbanResizing(true);
              kanbanResizeStart.current = {
                x: e.clientX,
                y: e.clientY,
                w: kanbanSize.width,
                h: kanbanSize.height,
              };
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
            }}
          />
        </div>
      )}

      {/* ── 파일 퀵 뷰 플로팅 윈도우들 — lazy load (Monaco 포함) ── */}
      <Suspense fallback={null}>
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
      </Suspense>

    </div>
  );
}

// ─── 칸반 전용 팝아웃 창 컴포넌트 ─────────────────────────────────────────────
// window.open('?kanban=1')으로 열릴 때 렌더링되는 독립 컴포넌트.
// 브라우저 네이티브 창으로 열리므로 다른 모니터로 드래그 이동 가능.
function KanbanOnlyApp() {
  return (
    <div className="w-screen h-screen bg-[#1e1e1e] text-[#cccccc] font-sans flex flex-col overflow-hidden">
      {/* 최소 타이틀바 — 창 이동 구분용 */}
      <div className="h-8 bg-[#252526] border-b border-black/40 flex items-center px-3 shrink-0 select-none">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb]">오케스트레이션 보드</span>
        <span className="text-[9px] text-[#555] ml-2">— 이 창을 다른 모니터로 드래그하세요</span>
      </div>
      {/* 태스크보드 패널 전체 화면 표시 — 네이티브 앱 플로팅과 동일한 컴포넌트 */}
      <div className="flex-1 overflow-hidden p-3">
        <TaskBoardPanel />
      </div>
    </div>
  );
}

// ─── 루트 진입점 — URL 파라미터로 렌더링 모드 분기 ─────────────────────────
// ?kanban=1 / ?graph=1 쿼리 파라미터에 따라 전용 창 렌더링
function DashboardOnlyApp() {
  const params = new URLSearchParams(window.location.search);
  const rawTab = (params.get('tab') || 'hive').toLowerCase();
  const tab = rawTab;

  const titleMap: Record<string, string> = {
    tasks: 'Tasks',
    memory: 'Shared Memory',
    git: 'Git',
    hive: 'Hive',
    telegram: 'Telegram Bridge',
  };

  const renderPanel = () => {
    switch (tab) {
      case 'tasks':
        return <TasksPanel onActiveCount={() => {}} />;
      case 'memory':
        return <MemoryPanel />;
      case 'git':
        return <GitPanel currentPath="" onChangesCount={() => {}} />;
      case 'telegram':
        return <TelegramPanel />;
      case 'hive':
      default:
        return <HivePanel />;
    }
  };

  return (
    <div className="w-screen h-screen bg-[#1e1e1e] text-[#cccccc] font-sans flex flex-col overflow-hidden">
      <div className="h-8 bg-[#252526] border-b border-black/40 flex items-center px-3 shrink-0 select-none">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#bbbbbb]">
          {titleMap[tab] ?? titleMap.agent}
        </span>
        <span className="text-[9px] text-[#555] ml-2">standalone dashboard</span>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden p-3 flex flex-col">
        {renderPanel()}
      </div>
    </div>
  );
}

function Root() {
  const params = new URLSearchParams(window.location.search);
  if (params.has('kanban')) return <KanbanOnlyApp />;
  if (params.get('page') === 'dashboard') return <DashboardOnlyApp />;
  if (params.get('page') === 'office') return (
    <Suspense fallback={<div className="w-screen h-screen bg-[#0a0a0f] flex items-center justify-center text-white">Loading Office...</div>}>
      <OfficeApp />
    </Suspense>
  );
  // viewMode: localStorage로 마지막 선택 모드 복원
  return <AppWithModeToggle />;
}

// 클래식 모드 고정 — 오피스는 보기 메뉴에서 ?page=office 로 전환
function AppWithModeToggle() {
  return <App />;
}

export default Root;


