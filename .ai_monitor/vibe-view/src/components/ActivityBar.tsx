/**
 * ------------------------------------------------------------------------
 * 📄 파일명: ActivityBar.tsx
 * 📝 설명: VS Code 스타일의 좌측 아이콘 액티비티 바 컴포넌트.
 *          각종 패널(탐색기, 검색, 오케스트레이터, 하이브, 메시지, 태스크,
 *          메모리, Git, MCP, 스킬결과)로 전환하는 버튼들과
 *          미읽음/활성 건수를 보여주는 배지를 포함합니다.
 *          App.tsx에서 분리되어 독립 파일로 관리됩니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리.
 * - 2026-03-04 Gemini: Mission Control (AI Brain) 버튼 추가 및 isThinking 상태 반영.
 * ------------------------------------------------------------------------
 */

import {
  Search, Settings,
  Files, Info, Zap,
  MessageSquare, ClipboardList, Brain,
  GitBranch, Package, Network, Cpu
} from 'lucide-react';

interface ActivityBarProps {
  // 현재 활성 탭 + 탭 전환 콜백
  activeTab: string;
  onTabChange: (tab: string) => void;
  // 각 배지에 필요한 카운트들
  skillChainStatus: string;    // 'running'이면 오케스트레이터 펄스 표시
  orchWarningCount: number;    // 하이브 진단 경고 배지
  unreadMsgCount: number;      // 메시지 채널 미읽음 배지
  activeTaskCount: number;     // 태스크보드 진행 중 배지
  memoryCount: number;         // 공유 메모리 항목 수 배지
  conflictCount: number;       // Git 충돌 배지 (충돌 우선)
  totalGitChanges: number;     // Git 변경 파일 수 배지
  mcpCount: number;            // 설치된 MCP 수 배지
  isThinking?: boolean;        // AI가 생각 중인지 여부
}

export default function ActivityBar({
  activeTab, onTabChange,
  skillChainStatus, orchWarningCount,
  unreadMsgCount, activeTaskCount,
  memoryCount, conflictCount, totalGitChanges, mcpCount,
  isThinking = false,
}: ActivityBarProps) {

  // 탭 버튼 공통 스타일 계산 (활성 시 왼쪽 보더 + 배경 강조)
  const tabCls = (tab: string) =>
    `p-2 transition-colors relative ${activeTab === tab ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'}`;

  // 탭 클릭 시 사이드바 열기 + 탭 전환
  const handleTab = (tab: string) => onTabChange(tab);

  return (
    <div className="w-12 h-full bg-[#333333] border-r border-black/40 flex flex-col items-center py-4 gap-4 shrink-0">

      {/* 📂 파일 탐색기 */}
      <button onClick={() => handleTab('explorer')} className={tabCls('explorer')} title="탐색기">     
        <Files className="w-6 h-6" />
      </button>

      {/* 🔍 파일 검색 */}
      <button onClick={() => handleTab('search')} className={tabCls('search')} title="검색">
        <Search className="w-6 h-6" />
      </button>

      {/* 🧠 Mission Control (AI 생각 과정) */}
      <button onClick={() => handleTab('mission-control')} className={tabCls('mission-control')} title="Mission Control (AI Brain)">
        <Cpu className={`w-6 h-6 ${isThinking ? 'text-primary animate-pulse' : ''}`} />
        {isThinking && (
          <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-primary rounded-full animate-ping" />
        )}
      </button>

      {/* 🛰️ AI 오케스트레이터 (실행 중이면 펄스 배지) */}
      <button onClick={() => handleTab('orchestrate')} className={tabCls('orchestrate')} title="AI 오케스트레이터">
        <Network className="w-6 h-6" />
        {skillChainStatus === 'running' && (
          <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-primary rounded-full animate-pulse" /> 
        )}
      </button>

      {/* ⚡ 하이브 진단 (경고 시 배지) */}
      <button onClick={() => handleTab('hive')} className={tabCls('hive')} title="하이브 진단">      
        <Zap className="w-6 h-6" />
        {orchWarningCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-orange-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
            {orchWarningCount > 9 ? '9+' : orchWarningCount}
          </span>
        )}
      </button>

      {/* 💬 메시지 채널 (미읽음 발생 시 배지) */}
      <button onClick={() => handleTab('messages')} className={tabCls('messages')} title="메시지 채널">
        <MessageSquare className="w-6 h-6" />
        {unreadMsgCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
            {unreadMsgCount > 9 ? '9+' : unreadMsgCount}
          </span>
        )}
      </button>

      {/* 📋 태스크보드 (진행 중 태스크 배지) */}
      <button onClick={() => handleTab('tasks')} className={tabCls('tasks')} title="태스크보드">     
        <ClipboardList className="w-6 h-6" />
        {activeTaskCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-yellow-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
            {activeTaskCount > 9 ? '9+' : activeTaskCount}
          </span>
        )}
      </button>

      {/* 🧠 공유 메모리 (항목 수 배지) */}
      <button onClick={() => handleTab('memory')} className={tabCls('memory')} title="공유 메모리"> 
        <Brain className="w-6 h-6" />
        {memoryCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-cyan-500 text-black text-[8px] font-black rounded-full flex items-center justify-center leading-none">
            {memoryCount > 99 ? '99+' : memoryCount}
          </span>
        )}
      </button>

      {/* 🌿 Git 감시 (충돌(빨간색) 또는 변경파일) 배지 */}
      <button onClick={() => handleTab('git')} className={tabCls('git')} title="Git 감시">
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

      {/* 📦 MCP 관리자 (설치된 수 배지) */}
      <button onClick={() => handleTab('mcp')} className={tabCls('mcp')} title="MCP 관리자">
        <Package className="w-6 h-6" />
        {mcpCount > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-purple-500 text-white text-[8px] font-black rounded-full flex items-center justify-center leading-none">
            {mcpCount > 9 ? '9+' : mcpCount}
          </span>
        )}
      </button>

      {/* ⚡ 스킬 실행 결과 */}
      <button onClick={() => handleTab('skills')} className={tabCls('skills')} title="스킬 실행 결과">
        <Zap className="w-5 h-5" />
      </button>

      {/* ⚙️ 하단 고정 버튼 (설정 / 정보) */}
      <div className="mt-auto flex flex-col gap-4">
        <button className="p-2 text-[#858585] hover:text-white transition-colors" title="정보">        
          <Info className="w-6 h-6" />
        </button>
        <button className="p-2 text-[#858585] hover:text-white transition-colors" title="설정">        
          <Settings className="w-6 h-6" />
        </button>
      </div>

    </div>
  );
}
