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
import { Menu, ChevronRight, ChevronDown, RotateCw, X } from 'lucide-react';
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
import LanPanel from './components/panels/LanPanel';
import MemoryPanel from './components/panels/MemoryPanel';
import ZettelkastenPanel from './components/panels/ZettelkastenPanel';
import HivePanel from './components/panels/HivePanel';
import GitPanel from './components/panels/GitPanel';
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
    updateProgress, setUpdateProgress,
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

  // ─── 슬롯별 프로젝트 (터미널마다 다른 프로젝트 실행) ───────────────────────
  // [WHY] currentPath 전역 하나로는 모든 슬롯이 같은 프로젝트로 뜬다. 슬롯별 오버라이드를 둬서
  //   각 터미널이 다른 프로젝트 cwd로 뜨고, '활성 슬롯'의 프로젝트가 사이드 패널 전체를 지배한다
  //   (활성화는 명시적 버튼 — 암묵적 포커스는 Phase 2-5.2 race window 재발 위험이라 배제).
  //   미지정 슬롯은 currentPath 상속(하위호환). 영속은 localStorage(WebView2 storage_path).
  const [slotProjects, setSlotProjects] = useState<Record<number, string>>(() => {
    try {
      const saved = localStorage.getItem('hive_slot_projects');
      const parsed = saved ? JSON.parse(saved) : {};
      // [코드리뷰 2026-07-24] 파싱 결과는 cwd/PTY spawn으로 직결 — shape 검증 필수.
      //   외부/구버전 변형된 localStorage 값이 문자열 아닌 걸 흘려보내지 않도록 string 값만 채택.
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
      const clean: Record<number, string> = {};
      for (const [k, v] of Object.entries(parsed)) {
        if (typeof v === 'string' && v) clean[Number(k)] = v;
      }
      return clean;
    } catch { return {}; }
  });
  const [activeProjectSlot, setActiveProjectSlot] = useState<number | null>(null);
  useEffect(() => {
    try { localStorage.setItem('hive_slot_projects', JSON.stringify(slotProjects)); } catch { /* WebView 저장 실패 무시 */ }
  }, [slotProjects]);
  const setSlotProject = (slotId: number, path: string) => {
    setSlotProjects(prev => ({ ...prev, [slotId]: path }));
  };
  // [불변식] 활성화 = 그 슬롯 프로젝트를 currentPath로 승격 → 기존 패널들이 currentPath를 읽어
  //   자동 재조회. 미지정 슬롯이면 currentPath 유지(전역 프로젝트 그대로).
  const activateSlotProject = (slotId: number) => {
    const proj = slotProjects[slotId];
    if (proj) setCurrentPath(proj);
    setActiveProjectSlot(slotId);
  };

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

  // [2026-07-17] 자율 heartbeat 헤더 토글 칩 — 관제 패널이 아닌 런처급 스위치
  // (관제 신규 개발 중단 원칙 준수 — 상세 이력은 pg_logs/hive_tasks 열람으로)
  // active_here: 이 인스턴스가 9019 싱글턴 락을 쥔 auto 실행 주체인지. enabled는 dev+설치본이
  //   DB로 공유하는 값이라 양쪽 다 ON으로 보이지만 실제로 도는 건 한쪽뿐 — active_here=false면
  //   '다른 인스턴스에서 실행 중, 나는 대기'라 초록 ON이 아니라 대기 배지를 띄운다.
  const [heartbeat, setHeartbeat] = useState<{ enabled: boolean; daily_count: number; daily_limit: number; pending: number; stale?: boolean; loop_beat_at?: string; active_here?: boolean; last_result?: string; consecutive_fails?: number; current_task?: string; model?: string; recent?: { title: string; status: string; at: string }[] } | null>(null);
  // [읽기전용] 자율 클로드 상태 드로어 열림 여부 — 배지 클릭 시 토글(관제 아님, 열람용).
  const [autoPanel, setAutoPanel] = useState(false);
  const fetchHeartbeat = () => {
    fetch(`${API_BASE}/api/heartbeat/status`)
      .then(r => r.json())
      .then(d => { if (!d.error) setHeartbeat(d); })
      .catch(() => { /* 서버 미실행 시 무시 */ });
  };
  useEffect(() => {
    fetchHeartbeat();
    const t = setInterval(fetchHeartbeat, 30000);
    return () => clearInterval(t);
  }, []);
  const toggleHeartbeat = () => {
    if (!heartbeat) return;
    fetch(`${API_BASE}/api/heartbeat/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !heartbeat.enabled }),
    }).then(() => fetchHeartbeat()).catch(() => {});
  };

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
                setUpdateProgress(null);
                clearInterval(poll);
                setUpdateChecking(false);
              } else if (data?.downloading) {
                // 다운로드 진행 중 — 진행바 갱신하고 완료까지 폴링 유지(횟수 리셋)
                setUpdateProgress({
                  percent: typeof data.percent === 'number' ? data.percent : -1,
                  downloaded_mb: data.downloaded_mb || 0,
                  total_mb: data.total_mb || 0,
                });
                tries = 0;
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

  // 프로젝트 라이브 전환 — 선택한 폴더로 서버 프로젝트(DB/컨텍스트/배너)를 재시작 없이 전환.
  // [WHY] 예전엔 setCurrentPath만 해 last_path만 저장되고 서버는 옛 프로젝트를 계속 봐서
  //   패널이 비고 배너가 안 사라졌다(2026-07-19). switch-project를 await한 뒤 setCurrentPath해야
  //   config 재조회(projectUnresolved effect)가 전환된 상태를 읽어 배너가 정확히 갱신된다.
  const activateProject = async (path: string) => {
    const clean = path.trim().replace(/\\/g, '/');
    try {
      await fetch(`${API_BASE}/api/switch-project`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: clean }),
      });
    } catch {
      // 전환 API 실패해도 경로 표시는 갱신(다음 폴링/재시작에 반영).
    }
    setCurrentPath(clean);
  };

  // 폴더 열기 — TopMenuBar "파일 → 폴더 열기" 전용 (FileExplorer 자체 버튼과 별개)
  const openFolder = async () => {
    try {
      if ((window as any).pywebview?.api?.select_folder) {
        const data = await (window as any).pywebview.api.select_folder();
        if (data.status === 'success' && data.path) await activateProject(data.path);
        return;
      }
      const res = await fetch(`${API_BASE}/api/select-folder`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success' && data.path) await activateProject(data.path);
    } catch {
      // 다이얼로그 실패 시 prompt 폴백
      const path = prompt('프로젝트 폴더 경로를 입력하세요:', currentPath);
      if (path) await activateProject(path);
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
    lan: 'LAN 공유',
  }[activeTab] ?? activeTab;

  return (
    <div
      className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden font-sans flex-col"
      onClick={() => setActiveMenu(null)}
    >
      {/* ── 업데이트 다운로드 진행바 (다운로드 중 & 아직 준비 전) ── */}
      {updateProgress && !updateReady && (
        <div className="px-3 py-1 bg-primary/10 border-b border-primary/30 shrink-0 z-50">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] text-primary font-bold">
              새 버전 다운로드 중{updateProgress.percent >= 0 ? ` ${updateProgress.percent}%` : '...'}
              {updateProgress.total_mb > 0 && (
                <span className="font-mono text-primary/70 ml-1">
                  ({updateProgress.downloaded_mb}/{updateProgress.total_mb}MB)
                </span>
              )}
            </span>
          </div>
          {/* percent -1(총 크기 미상)이면 확정 진행바 대신 좌우 왕복 인디케이터 */}
          <div className="h-1 w-full bg-primary/15 rounded overflow-hidden">
            {updateProgress.percent >= 0 ? (
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${updateProgress.percent}%` }}
              />
            ) : (
              <div className="h-full w-1/3 bg-primary/60 animate-pulse" />
            )}
          </div>
        </div>
      )}

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
            ) : activeTab === 'lan' ? (
              /* LAN 브리지 패널 — 자동발견·페어링·파일전송 (Phase 1) */
              <LanPanel />
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
              {/* 자율 heartbeat 토글 — 클릭 한 번으로 on/off (scripts/auto.py·텔레그램 /auto와 동일 스위치) */}
              {/* hbWaiting: enabled인데 이 인스턴스가 9019 락을 못 쥠 = 다른 인스턴스가 실행 주체(대기).
                  [과거사고 2026-07-22] 다른 프로젝트 설치본 2개 동시 실행 시, 대기 인스턴스는 자기
                  PG DB(프로젝트별 분리)의 loop_beat_at을 갱신 못 해 항상 stale → '멈춤(hang)'으로 오표시.
                  [불변식] '멈춤'은 내가 실행 주체(active_here=true)일 때만. 대기(active_here=false)는
                  stale이어도 '대기'로 표시. 우선순위: 멈춤(주체+stale) > 대기 > ON > OFF. */}
              {(() => {
              const hbWaiting = !!(heartbeat && heartbeat.enabled && heartbeat.active_here === false);
              // [과거사고 2026-07-23] hbStale을 !hbWaiting으로 막았더니, hbWaiting이 enabled=true를
              //   요구해서 '비주체 + enabled=false + stale' 조합(설치본이 자기 DB의 이틀 묵은
              //   loop_beat_at을 읽는 상황)이 그대로 '멈춤'으로 샜다 = 위 불변식 위반.
              //   락을 못 쥔 인스턴스의 stale은 hang 근거가 못 된다(박동 주체가 남이라 당연히 늙음).
              //   → 게이트를 active_here로 직접 건다. undefined(구버전 서버)는 기존대로 통과.
              const hbStale = !!(heartbeat?.stale && heartbeat?.active_here !== false);
              const hbStatus = hbStale ? '멈춤' : hbWaiting ? '대기' : heartbeat?.enabled ? 'ON' : 'OFF';
              return (
              <div className="relative">
              <button
                onClick={() => setAutoPanel(v => !v)}
                className={`flex items-center gap-1 px-2 h-6 rounded-full text-[10px] font-bold border transition-all ${
                  hbStale
                    ? 'bg-red-500/20 border-red-400/50 text-red-300 shadow-[0_0_8px_rgba(248,113,113,0.3)]'
                    : hbWaiting
                    ? 'bg-amber-500/15 border-amber-400/40 text-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.25)]'
                    : heartbeat?.enabled
                    ? 'bg-emerald-500/15 border-emerald-400/40 text-emerald-300 shadow-[0_0_8px_rgba(52,211,153,0.25)]'
                    : 'bg-black/30 border-white/10 text-[#858585] hover:text-white hover:border-white/25'
                }`}
                title="자율 클로드 상태 보기 (클릭)"
              >
                <span className={hbStale || hbWaiting ? '' : heartbeat?.enabled ? 'animate-pulse' : ''}>
                  {hbStale ? '⚠️' : hbWaiting ? '⏸️' : '🫀'}
                </span>
                <span>{hbStale ? 'AUTO 멈춤' : hbWaiting ? 'AUTO 대기' : heartbeat?.enabled ? 'AUTO ON' : 'AUTO'}</span>
                {heartbeat && heartbeat.pending > 0 && (
                  <span className="px-1 rounded-full bg-amber-500/20 text-amber-300">{heartbeat.pending}</span>
                )}
              </button>
              {autoPanel && heartbeat && (
                <div className="absolute right-0 mt-2 w-72 bg-[#14171c] border border-white/10 rounded-xl shadow-2xl p-3 z-[60] text-[11px] text-[#c9cfd8]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-[12px]">🫀 자율 클로드</span>
                    <span className={`px-2 py-0.5 rounded-full font-bold ${hbStale ? 'bg-red-500/20 text-red-300' : hbWaiting ? 'bg-amber-500/20 text-amber-300' : heartbeat.enabled ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/10 text-[#858585]'}`}>{hbStatus}</span>
                  </div>
                  <div className="space-y-1">
                    <div><span className="text-[#858585]">현재 작업</span> · {heartbeat.current_task || '없음 (대기)'}</div>
                    <div><span className="text-[#858585]">모델</span> · {heartbeat.model || '—'}</div>
                    <div><span className="text-[#858585]">오늘</span> · {heartbeat.daily_count}/{heartbeat.daily_limit}건 · 연속실패 {heartbeat.consecutive_fails ?? 0}</div>
                    <div><span className="text-[#858585]">실행 주체</span> · {heartbeat.active_here === false ? '다른 인스턴스' : '이 인스턴스'}{hbStale ? ' · hang 의심(재시작 권장)' : ''}</div>
                  </div>
                  {heartbeat.recent && heartbeat.recent.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-white/10">
                      <div className="text-[#858585] mb-1">최근 결과</div>
                      {heartbeat.recent.map((t, i) => (
                        <div key={i} className="flex items-center gap-1">
                          <span>{t.status === 'done' ? '✅' : '⛔'}</span>
                          <span className="truncate flex-1">{t.title}</span>
                          <span className="text-[#6b7280] shrink-0">{t.at}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <button
                    onClick={toggleHeartbeat}
                    className={`w-full mt-2 py-1.5 rounded-lg font-bold transition-all ${heartbeat.enabled ? 'bg-white/10 text-[#858585] hover:text-white' : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'}`}
                  >{heartbeat.enabled ? '자율 클로드 끄기' : '자율 클로드 켜기'}</button>
                </div>
              )}
              </div>
              ); })()}
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
                  slotProject={slotProjects[slotId]}
                  isActiveProject={activeProjectSlot === slotId}
                  onActivateProject={() => activateSlotProject(slotId)}
                  onPickProject={(p: string) => setSlotProject(slotId, p)}
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

      {/* [9차 정리 2026-07-16] 오케스트레이션 보드(칸반 플로팅 창) 은퇴 — 관제 시대 유물.
          체인 기록(PG hive_skill_chains)과 슬롯 인라인 MonitorView는 유지. */}

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

// ─── 루트 진입점 — URL 파라미터로 렌더링 모드 분기 ─────────────────────────
// ?page=dashboard(독립 대시보드 창) / ?page=office(오피스 창) 쿼리 파라미터로 분기.
// [9차 정리 2026-07-16] ?kanban=1(KanbanOnlyApp) 경로 은퇴 — 오케스트레이션 보드 소멸.
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


