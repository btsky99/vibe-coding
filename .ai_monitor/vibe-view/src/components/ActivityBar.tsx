/**
 * ------------------------------------------------------------------------
 * 📄 파일명: ActivityBar.tsx
 * 📝 설명: 좌측 액티비티 바 — 패널 탭 전환 아이콘 + 배지(태스크/메모리/충돌/Git 변경 수,
 *          하이브 헬스, 사고/실행 중 상태). memo로 리렌더 최소화.
 * REVISION HISTORY:
 * - 2026-08-09 Claude: 중앙 대화 탭 추가 (Phase 10 Task 29)
 * - 2026-07-18 Claude: 헤더 누락 보강 (코드 품질 점검 규칙 5 준수)
 */
import { memo } from 'react';
import {
  Activity,
  BookOpen,
  Brain,
  ClipboardList,
  Files,
  Gauge,
  GitBranch,
  HeartPulse,
  Package,
  Radio,
  Search,
  Settings,
  Wifi,
  Zap,
} from 'lucide-react';

interface ActivityBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  onOpenSettings: () => void;
  skillChainStatus: string;
  orchWarningCount: number;
  activeTaskCount: number;
  memoryCount: number;
  conflictCount: number;
  totalGitChanges: number;
  isThinking?: boolean;
  isAgentRunning?: boolean;
  globalPipelineStage?: string;
  hiveHealth?: any;
  isHealingActive?: boolean;
}

const ActivityBar = memo(function ActivityBar({
  activeTab,
  onTabChange,
  onOpenSettings,
  skillChainStatus,
  orchWarningCount,
  activeTaskCount,
  memoryCount,
  conflictCount,
  totalGitChanges,
  isThinking = false,
  isAgentRunning = false,
  globalPipelineStage = 'idle',
  hiveHealth = null,
}: ActivityBarProps) {
  const tabCls = (tab: string) =>
    `p-2 transition-colors relative ${
      activeTab === tab ? 'text-white border-l-2 border-primary bg-white/5' : 'text-[#858585] hover:text-white'
    }`;

  const isHealthy = hiveHealth?.status === 'healthy';
  const isHealing = hiveHealth?.status === 'healing';

  return (
    <div className="w-12 h-full bg-[#333333] border-r border-black/40 flex flex-col items-center py-2 gap-4 shrink-0 overflow-y-auto overflow-x-hidden no-scrollbar">
      <div className="flex flex-col items-center gap-1 py-2 mb-2 relative group cursor-default">
        <div className="relative p-1.5 rounded-xl bg-black/20 border border-white/5 transition-colors">
          <Zap className={`w-6 h-6 ${isAgentRunning ? 'text-primary animate-pulse' : 'text-textMuted'}`} />
          <span
            className={`absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[#333333] ${
              isHealing ? 'bg-yellow-400 animate-pulse' : isHealthy ? 'bg-green-500' : 'bg-red-500'
            }`}
            title={isHealing ? 'Healing' : isHealthy ? 'Healthy' : 'Warning'}
          />
        </div>

        <div className="flex gap-1 mt-1">
          <div
            className={`w-1.5 h-1.5 rounded-full transition-all duration-500 ${
              globalPipelineStage === 'analyzing'
                ? 'bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)] animate-pulse scale-125'
                : 'bg-white/10'
            }`}
            title="Analyzing"
          />
          <div
            className={`w-1.5 h-1.5 rounded-full transition-all duration-500 ${
              globalPipelineStage === 'modifying'
                ? 'bg-yellow-400 shadow-[0_0_8px_rgba(250,204,21,0.8)] animate-pulse scale-125'
                : 'bg-white/10'
            }`}
            title="Modifying"
          />
          <div
            className={`w-1.5 h-1.5 rounded-full transition-all duration-500 ${
              globalPipelineStage === 'verifying'
                ? 'bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.8)] animate-pulse scale-125'
                : 'bg-white/10'
            }`}
            title="Verifying"
          />
        </div>

        <div className="absolute left-14 top-2 px-2 py-1 bg-[#252526] border border-white/10 rounded text-[10px] whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50 shadow-xl">
          <div className="font-bold text-primary mb-1">HIVE CORE ENGINE</div>
          <div className="flex items-center gap-1.5 text-white/70">
            <span className={`w-1.5 h-1.5 rounded-full ${isHealthy ? 'bg-green-500' : 'bg-red-500'}`} />
            Health: {isHealthy ? 'Healthy' : 'Warning'}
          </div>
          <div className="text-[9px] text-white/40 mt-1">Stage: {globalPipelineStage.toUpperCase()}</div>
        </div>
      </div>

      <div className="w-8 h-px bg-white/5" />

      <button onClick={() => onTabChange('explorer')} className={tabCls('explorer')} title="File Explorer">
        <Files className="w-6 h-6" />
      </button>

      <button onClick={() => onTabChange('search')} className={tabCls('search')} title="Search">
        <Search className="w-6 h-6" />
      </button>

      <div className="w-6 h-px bg-white/10" />

      <button onClick={() => onTabChange('tasks')} className={tabCls('tasks')} title="Tasks">
        <ClipboardList className="w-5 h-5" />
        {activeTaskCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-yellow-400 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('memory')} className={tabCls('memory')} title="Shared Memory">
        <Brain className={`w-5 h-5 ${isThinking ? 'text-cyan-400 animate-pulse' : ''}`} />
        {memoryCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-cyan-500 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('zettel')} className={tabCls('zettel')} title="Zettelkasten">
        <BookOpen className="w-5 h-5" />
      </button>

      <button onClick={() => onTabChange('git')} className={tabCls('git')} title="Git">
        <GitBranch className="w-5 h-5" />
        {(conflictCount > 0 || totalGitChanges > 0) && (
          <span
            className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full ${
              conflictCount > 0 ? 'bg-red-500 animate-pulse' : 'bg-cyan-400'
            }`}
          />
        )}
      </button>

      <button onClick={() => onTabChange('hive')} className={tabCls('hive')} title="Hive">
        <Activity className="w-5 h-5" />
        {orchWarningCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-orange-500 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('heal')} className={tabCls('heal')} title="자가치유 계측">
        <HeartPulse className="w-5 h-5" />
      </button>

      <button onClick={() => onTabChange('lan')} className={tabCls('lan')} title="LAN 공유">
        <Wifi className="w-5 h-5" />
      </button>
      <button onClick={() => onTabChange('central')} className={tabCls('central')} title="중앙 대화 (아픽스 서버)">
        <Radio className="w-5 h-5" />
      </button>
      <button onClick={() => onTabChange('tools')} className={tabCls('tools')} title="개발 도구">
        <Package className="w-5 h-5" />
      </button>
      <button onClick={() => onTabChange('daemons')} className={tabCls('daemons')} title="백그라운드 데몬 on/off">
        <Gauge className="w-5 h-5" />
      </button>


      <div className="mt-auto flex flex-col gap-4">
        <button
          onClick={onOpenSettings}
          className="p-2 text-[#858585] hover:text-white transition-colors group"
          title="Settings"
        >
          <Settings className="w-6 h-6 group-hover:rotate-90 transition-transform duration-500" />
        </button>
      </div>
    </div>
  );
});

export default ActivityBar;
