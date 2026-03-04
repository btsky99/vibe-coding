/**
 * ------------------------------------------------------------------------
 * 📄 파일명: DashboardPage.tsx
 * 📝 설명: 대시보드 전용 페이지 — 메인 터미널 페이지와 완전히 분리된 독립 페이지.
 *          모든 패널(메시지, 태스크, 메모리, Git, 하이브, 오케스트레이터, MCP,
 *          스킬, 에이전트, 디스코드)을 카드 그리드 레이아웃으로 표시합니다.
 * REVISION HISTORY:
 * - 2026-03-05 Claude: 최초 생성 — 사이드바 내장 방식에서 독립 페이지로 분리
 * ------------------------------------------------------------------------
 */

import { useState } from 'react';
import { ArrowLeft, MessageSquare, CheckSquare, Brain, GitBranch, Activity, Bot, Puzzle, Zap, Cpu, MessageCircle } from 'lucide-react';
import MessagesPanel from '../components/panels/MessagesPanel';
import TasksPanel from '../components/panels/TasksPanel';
import MemoryPanel from '../components/panels/MemoryPanel';
import OrchestratorPanel from '../components/panels/OrchestratorPanel';
import HivePanel from '../components/panels/HivePanel';
import GitPanel from '../components/panels/GitPanel';
import McpPanel from '../components/panels/McpPanel';
import SkillResultsPanel from '../components/panels/SkillResultsPanel';
import AgentPanel from '../components/panels/AgentPanel';
import DiscordConfigPanel from '../components/panels/DiscordConfigPanel';

// 대시보드 패널 탭 정의 — 아이콘 + 레이블 + 컴포넌트 매핑
const DASHBOARD_TABS = [
  { id: 'messages',    label: '메시지',     icon: MessageSquare },
  { id: 'tasks',       label: '태스크',     icon: CheckSquare },
  { id: 'memory',      label: '메모리',     icon: Brain },
  { id: 'git',         label: 'Git',        icon: GitBranch },
  { id: 'hive',        label: '하이브',     icon: Activity },
  { id: 'orchestrate', label: '오케스트레이터', icon: Cpu },
  { id: 'mcp',         label: 'MCP',        icon: Puzzle },
  { id: 'skills',      label: '스킬',       icon: Zap },
  { id: 'agent',       label: '에이전트',   icon: Bot },
  { id: 'discord',     label: '디스코드',   icon: MessageCircle },
] as const;

type DashboardTab = typeof DASHBOARD_TABS[number]['id'];

interface DashboardPageProps {
  onBack: () => void;                    // 메인 터미널 페이지로 돌아가기
  currentPath: string;                   // FileExplorer 현재 경로 (GitPanel 공유)
  onSetIsAgentRunning: (v: boolean) => void;
}

export default function DashboardPage({ onBack, currentPath, onSetIsAgentRunning }: DashboardPageProps) {
  // 팝업 창 여부 확인 (window.opener가 있으면 별도 창으로 간주)
  const isPopup = window.opener && window.opener !== window;

  // 현재 활성 탭 — URL 파라미터(tab)가 있으면 해당 탭을 기본값으로 사용
  const [activeTab, setActiveTab] = useState<DashboardTab>(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab') as DashboardTab;
    return (tab && DASHBOARD_TABS.some(t => t.id === tab)) ? tab : 'messages';
  });

  // ... (생략된 중간 코드 생략하지 않고 전체 로직 유지)

  // 뒤로가기 또는 창 닫기 핸들러
  const handleBack = () => {
    if (isPopup) {
      window.close();
    } else {
      onBack();
    }
  };

  // 패널 배지 카운트 (각 패널 콜백으로 수신)
  const [unreadMsgCount, setUnreadMsgCount] = useState(0);
  const [activeTaskCount, setActiveTaskCount] = useState(0);
  const [totalGitChanges, setTotalGitChanges] = useState(0);
  const [conflictCount, setConflictCount] = useState(0);

  // 현재 활성 탭에 맞는 패널 렌더링
  const renderPanel = () => {
    switch (activeTab) {
      case 'messages':    return <MessagesPanel onUnreadCount={setUnreadMsgCount} />;
      case 'tasks':       return <TasksPanel onActiveCount={setActiveTaskCount} />;
      case 'memory':      return <MemoryPanel currentProjectName={currentPath.split(/[/\\]/).filter(Boolean).pop()} />;
      case 'git':         return <GitPanel currentPath={currentPath} onChangesCount={(c, conf) => { setTotalGitChanges(c); setConflictCount(conf); }} />;
      case 'hive':        return <HivePanel />;
      case 'orchestrate': return <OrchestratorPanel onWarningCount={() => {}} />;
      case 'mcp':         return <McpPanel />;
      case 'skills':      return <SkillResultsPanel />;
      case 'agent':       return <AgentPanel onStatusChange={onSetIsAgentRunning} />;
      case 'discord':     return <DiscordConfigPanel />;
      default:            return null;
    }
  };

  // 탭별 배지 카운트 반환
  const getBadge = (tabId: DashboardTab): number | null => {
    if (tabId === 'messages' && unreadMsgCount > 0) return unreadMsgCount;
    if (tabId === 'tasks' && activeTaskCount > 0) return activeTaskCount;
    if (tabId === 'git' && totalGitChanges > 0) return totalGitChanges + conflictCount;
    return null;
  };

  return (
    <div className="flex h-screen w-full bg-[#1e1e1e] text-[#cccccc] overflow-hidden flex-col font-sans">

      {/* ── 대시보드 헤더 ── */}
      <header className="h-11 bg-[#2d2d2d] border-b border-black/40 flex items-center gap-4 px-4 shrink-0">
        {/* 메인으로 돌아가기 또는 창 닫기 버튼 */}
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-[11px] text-[#969696] hover:text-white transition-colors px-2 py-1 rounded hover:bg-white/10"
        >
          <ArrowLeft className="w-4 h-4" />
          {isPopup ? '대시보드 닫기' : '터미널로'}
        </button>

        <div className="w-px h-5 bg-white/10" />

        {/* 대시보드 제목 */}
        <span className="text-[12px] font-bold text-primary tracking-wide">
          🎛️ Vibe Coding Dashboard
        </span>
      </header>

      {/* ── 탭 바 ── */}
      <div className="flex items-center gap-0.5 px-3 py-1.5 bg-[#252526] border-b border-black/30 shrink-0 overflow-x-auto">
        {DASHBOARD_TABS.map(({ id, label, icon: Icon }) => {
          const badge = getBadge(id);
          const isActive = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium transition-all whitespace-nowrap ${
                isActive
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'text-[#969696] hover:text-white hover:bg-white/5'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
              {/* 배지 */}
              {badge !== null && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] font-bold rounded-full min-w-[14px] h-3.5 flex items-center justify-center px-0.5">
                  {badge > 99 ? '99+' : badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ── 패널 컨텐츠 영역 ── */}
      <main className="flex-1 overflow-hidden p-4">
        <div className="h-full bg-[#252526] rounded-lg border border-white/5 overflow-hidden p-3">
          {renderPanel()}
        </div>
      </main>
    </div>
  );
}
