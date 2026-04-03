import { memo } from 'react';
import {
  Activity,
  Bot,
  Brain,
  ClipboardList,
  Files,
  GitBranch,
  LayoutDashboard,
  MessageSquare,
  Search,
  Settings,
  Smartphone,
  Target,
  Zap,
} from 'lucide-react';

interface ActivityBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  onOpenSettings: () => void;
  skillChainStatus: string;
  orchWarningCount: number;
  unreadMsgCount: number;
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
  unreadMsgCount,
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

      <button onClick={() => onTabChange('messages')} className={tabCls('messages')} title="Messages">
        <MessageSquare className="w-5 h-5" />
        {unreadMsgCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-red-500 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('tasks')} className={tabCls('tasks')} title="Tasks">
        <ClipboardList className="w-5 h-5" />
        {activeTaskCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-yellow-400 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('kanban')} className={tabCls('kanban')} title="Task Board">
        <LayoutDashboard className="w-5 h-5" />
        {activeTaskCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-blue-400 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('memory')} className={tabCls('memory')} title="Shared Memory">
        <Brain className={`w-5 h-5 ${isThinking ? 'text-cyan-400 animate-pulse' : ''}`} />
        {memoryCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-cyan-500 rounded-full" />}
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

      <button onClick={() => onTabChange('agent')} className={tabCls('agent')} title="Agent">
        <Bot className="w-5 h-5" />
        {(isAgentRunning || skillChainStatus === 'running') && (
          <span
            className={`absolute top-0.5 right-0.5 w-2 h-2 rounded-full animate-pulse ${
              isAgentRunning ? 'bg-yellow-400' : 'bg-primary'
            }`}
          />
        )}
      </button>

      <button onClick={() => onTabChange('dispatcher')} className={tabCls('dispatcher')} title="Dispatcher">
        <Target className="w-5 h-5" />
      </button>

      <button onClick={() => onTabChange('hive')} className={tabCls('hive')} title="Hive">
        <Activity className="w-5 h-5" />
        {orchWarningCount > 0 && <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-orange-500 rounded-full" />}
      </button>

      <button onClick={() => onTabChange('telegram')} className={tabCls('telegram')} title="Telegram Bridge">
        <Smartphone className="w-5 h-5" />
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
