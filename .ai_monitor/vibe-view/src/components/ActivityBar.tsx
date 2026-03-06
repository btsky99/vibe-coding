/**
 * ------------------------------------------------------------------------
 * 📄 파일명: ActivityBar.tsx
 * 📝 설명: VS Code 스타일의 좌측 아이콘 액티비티 바 컴포넌트.
 *          파일 탐색기/검색 탭 전환 + 대시보드 페이지 진입 버튼 포함.
 *          기존에 사이드바 내부에 있던 패널들(메시지, 태스크, 메모리 등)은
 *          대시보드 페이지(/dashboard)로 분리되어 여기서는 아이콘 버튼만 남깁니다.
 * REVISION HISTORY:
 * - 2026-03-05 Claude: 패널 탭을 대시보드 페이지로 분리. ActivityBar는 파일 탐색기/검색/대시보드 진입만 담당.
 * - 2026-03-04 Gemini: Mission Control (AI Brain) 버튼 추가 및 isThinking 상태 반영.
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리.
 * ------------------------------------------------------------------------
 */

import {
  Search, Settings, Files,
  MessageSquare, ClipboardList, Brain, GitBranch, Package, Bot, Zap,
  ExternalLink, LayoutDashboard
} from 'lucide-react';

interface ActivityBarProps {
  // 파일 탐색기 탭 관련 — 사이드바 탭 전환
  activeTab: string;
  onTabChange: (tab: string) => void;
  // 설정 팝업 오픈 콜백
  onOpenSettings: () => void;
  // 디스코드 새 창 열기 콜백 (분리된 기능)
  onOpenDiscordNewWindow: () => void;
  // 배지 카운트들 — 대시보드 버튼에 통합 배지 표시용
  skillChainStatus: string;
  orchWarningCount: number;
  unreadMsgCount: number;
  activeTaskCount: number;
  memoryCount: number;
  conflictCount: number;
  totalGitChanges: number;
  mcpCount: number;
  isThinking?: boolean;
  isAgentRunning?: boolean;
}

export default function ActivityBar({
  activeTab, onTabChange,
  onOpenSettings,
  onOpenDiscordNewWindow,
  skillChainStatus, orchWarningCount,
  unreadMsgCount, activeTaskCount,
  memoryCount, conflictCount, totalGitChanges, mcpCount,
  isThinking = false,
  isAgentRunning = false,
}: ActivityBarProps) {

  // 탭 버튼 공통 스타일 (활성 시 왼쪽 보더 + 배경 강조)
  const tabCls = (tab: string) =>
    `p-2 transition-colors relative ${activeTab === tab ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`;

  return (
    <div className="w-12 h-full bg-[#333333] border-r border-black/40 flex flex-col items-center py-4 gap-4 shrink-0">

      {/* 📂 파일 탐색기 — 사이드바 탐색기 전환 */}
      <button onClick={() => onTabChange('explorer')} className={tabCls('explorer')} title="파일 탐색기">
        <Files className="w-6 h-6" />
      </button>

      {/* 🔍 파일 검색 — 사이드바 검색 전환 */}
      <button onClick={() => onTabChange('search')} className={tabCls('search')} title="파일 검색">
        <Search className="w-6 h-6" />
      </button>

      {/* ── 구분선 ── */}
      <div className="w-6 h-px bg-white/10" />

      {/* ── 빠른 접근 아이콘 (사이드바 탭 전환) ── */}
      <button onClick={() => onTabChange('messages')} className={tabCls('messages')} title="메시지 채널">
        <MessageSquare className="w-5 h-5" />
        {unreadMsgCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-red-500 rounded-full" />
        )}
      </button>

      <button onClick={() => onTabChange('tasks')} className={tabCls('tasks')} title="태스크보드 (리스트)">
        <ClipboardList className="w-5 h-5" />
        {activeTaskCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-yellow-400 rounded-full" />
        )}
      </button>

      {/* 태스크보드 — 스킬 실행결과 + 칸반 통합 팝업 */}
      <button onClick={() => onTabChange('kanban')} className={tabCls('kanban')} title="태스크보드 (스킬결과 + 칸반 통합)">
        <LayoutDashboard className="w-5 h-5" />
        {activeTaskCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-blue-400 rounded-full" />
        )}
      </button>

      <button onClick={() => onTabChange('memory')} className={tabCls('memory')} title="공유 메모리">
        <Brain className={`w-5 h-5 ${isThinking ? 'text-cyan-400 animate-pulse' : ''}`} />
        {memoryCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-cyan-500 rounded-full" />
        )}
      </button>

      <button onClick={() => onTabChange('git')} className={tabCls('git')} title="Git 감시">
        <GitBranch className="w-5 h-5" />
        {(conflictCount > 0 || totalGitChanges > 0) && (
          <span className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full ${conflictCount > 0 ? 'bg-red-500 animate-pulse' : 'bg-cyan-400'}`} />
        )}
      </button>

      <button onClick={() => onTabChange('agent')} className={tabCls('agent')} title="자율 에이전트 / 스킬체인">
        <Bot className="w-5 h-5" />
        {/* 에이전트 실행 중: 노랑 / 스킬체인 실행 중: primary 펄스 */}
        {(isAgentRunning || skillChainStatus === 'running') && (
          <span className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full animate-pulse ${
            isAgentRunning ? 'bg-yellow-400' : 'bg-primary'
          }`} />
        )}
      </button>

      <button onClick={() => onTabChange('mcp')} className={tabCls('mcp')} title="MCP 관리자">
        <Package className="w-5 h-5" />
        {mcpCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-purple-500 rounded-full" />
        )}
      </button>

      <button onClick={() => onTabChange('hive')} className={tabCls('hive')} title="하이브 진단 / 스킬">
        <Zap className="w-5 h-5" />
        {orchWarningCount > 0 && (
          <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-orange-500 rounded-full" />
        )}
      </button>

      {/* ⚙️ 하단 고정 버튼 */}
      <div className="mt-auto flex flex-col gap-4">
        <button
          onClick={onOpenDiscordNewWindow}
          className="p-2 text-indigo-400 hover:text-indigo-300 transition-colors group"
          title="디스코드 설정 (전체 화면 새 창)"
        >
          <ExternalLink className="w-6 h-6 group-hover:scale-110 transition-transform" />
        </button>
        <button
          onClick={onOpenSettings}
          className="p-2 text-[#858585] hover:text-white transition-colors group"
          title="설정 (팝업)"
        >
          <Settings className="w-6 h-6 group-hover:rotate-90 transition-transform duration-500" />
        </button>
      </div>

    </div>
  );
}
