/**
 * ------------------------------------------------------------------------
 * 📄 파일명: OfficeApp.tsx
 * 📝 설명: DeskRPG-Lite 가상 오피스 모드 최상위 컴포넌트.
 *          중앙에 2D 오피스 월드, 우측에 HUD 패널(기존 패널 재활용).
 *          useVibeData 훅을 통해 클래식 모드와 동일한 데이터를 공유합니다.
 * REVISION HISTORY:
 * - 2026-04-03 Claude: 초기 생성 — 오피스 월드 + HUD 패널 레이아웃
 * ------------------------------------------------------------------------
 */

import { useState } from 'react';
import { Monitor, LayoutGrid, MessageSquare, ClipboardList, Database, GitBranch } from 'lucide-react';
import { useVibeData } from '../../hooks/useVibeData';
import OfficeWorld from './OfficeWorld';
/* ── 기존 패널 컴포넌트 재활용 ── */
import TerminalSlot from '../TerminalSlot';
import MessagesPanel from '../panels/MessagesPanel';
import TasksPanel from '../panels/TasksPanel';
import MemoryPanel from '../panels/MemoryPanel';
import GitPanel from '../panels/GitPanel';

// HUD 탭 목록 정의
const HUD_TABS = [
  { id: 'terminal', label: '터미널', icon: Monitor },
  { id: 'tasks', label: '태스크', icon: ClipboardList },
  { id: 'messages', label: '메시지', icon: MessageSquare },
  { id: 'memory', label: '메모리', icon: Database },
  { id: 'git', label: 'Git', icon: GitBranch },
] as const;

type HudTab = typeof HUD_TABS[number]['id'];

interface OfficeAppProps {
  onSwitchToClassic?: () => void;
}

export default function OfficeApp({ onSwitchToClassic }: OfficeAppProps) {
  const vibe = useVibeData();
  const [hudTab, setHudTab] = useState<HudTab>('terminal');
  // 오피스에서 선택된 책상(터미널 슬롯) — 클릭 시 HUD에 해당 터미널 표시
  const [selectedDesk, setSelectedDesk] = useState(0);

  // 책상 클릭 핸들러 — 오피스 월드에서 호출
  const handleDeskClick = (slotId: number) => {
    setSelectedDesk(slotId);
    setHudTab('terminal');
  };

  return (
    <div className="flex h-screen w-full bg-[#0a0a0f] text-[#e2e8f0] overflow-hidden font-sans flex-col">
      {/* ── 상단 바 — 로고 + 프로젝트명 + 모드 전환 ── */}
      <header className="h-10 bg-[#0f0f1a] border-b border-white/5 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500">
            VIBE OFFICE
          </span>
          <span className="text-[10px] text-white/30 font-mono">{vibe.appVersion}</span>
        </div>
        <div className="flex items-center gap-3">
          {/* 에이전트 요약 — 활성 에이전트 수 */}
          <div className="flex items-center gap-1.5 text-[10px]">
            {Object.entries(vibe.agentTerminals).map(([tid, data]: [string, any]) => {
              const isActive = data.status === 'running' || data.status === 'started';
              return (
                <div key={tid} className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-400 animate-pulse' : 'bg-white/10'}`}
                  title={`${tid}: ${data.cli || 'idle'} — ${data.status || 'offline'}`}
                />
              );
            })}
          </div>
          {/* 모드 전환 버튼 */}
          {onSwitchToClassic && (
            <button
              onClick={onSwitchToClassic}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] font-bold
                         bg-white/5 hover:bg-white/10 border border-white/10 text-white/50 hover:text-white/80 transition-all"
            >
              <LayoutGrid className="w-3 h-3" />
              클래식 모드
            </button>
          )}
        </div>
      </header>

      {/* ── 메인 영역 — 오피스 월드(좌) + HUD 패널(우) ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── 오피스 월드 (중앙) ── */}
        <div className="flex-1 min-w-0 relative">
          <OfficeWorld
            agentTerminals={vibe.agentTerminals}
            selectedDesk={selectedDesk}
            onDeskClick={handleDeskClick}
          />
        </div>

        {/* ── HUD 패널 (우측) ── */}
        <div className="w-[420px] shrink-0 bg-[#0f0f1a]/90 backdrop-blur-md border-l border-white/5 flex flex-col">
          {/* HUD 탭 바 */}
          <div className="h-9 flex items-center gap-0.5 px-2 bg-[#0a0a12] border-b border-white/5 shrink-0">
            {HUD_TABS.map(tab => {
              const Icon = tab.icon;
              const isActive = hudTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setHudTab(tab.id)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-bold transition-all ${
                    isActive
                      ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                      : 'text-white/40 hover:text-white/60 hover:bg-white/5 border border-transparent'
                  }`}
                >
                  <Icon className="w-3 h-3" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* HUD 컨텐츠 — 기존 패널 컴포넌트 재활용 */}
          <div className="flex-1 overflow-hidden flex flex-col p-2">
            {hudTab === 'terminal' ? (
              <div className="flex-1 min-h-0">
                <TerminalSlot
                  key={selectedDesk}
                  slotId={selectedDesk}
                  logs={vibe.logs}
                  currentPath={vibe.currentPath}
                  terminalCount={8}
                  locks={vibe.locks}
                  messages={vibe.messages}
                  tasks={[]}
                  geminiUsage={vibe.geminiUsage}
                  claudeUsage={vibe.claudeUsage}
                  agentTerminals={vibe.agentTerminals}
                  orchestratorData={vibe.skillChain}
                  hiveActivity={vibe.hiveActivity}
                />
              </div>
            ) : hudTab === 'tasks' ? (
              <TasksPanel onActiveCount={vibe.setActiveTaskCount} />
            ) : hudTab === 'messages' ? (
              <MessagesPanel onUnreadCount={vibe.setUnreadMsgCount} />
            ) : hudTab === 'memory' ? (
              <MemoryPanel currentProjectName={vibe.currentPath.split(/[/\\]/).filter(Boolean).pop()} />
            ) : hudTab === 'git' ? (
              <GitPanel currentPath={vibe.currentPath} onChangesCount={(c, conf) => { vibe.setTotalGitChanges(c); vibe.setConflictCount(conf); }} />
            ) : null}
          </div>
        </div>
      </div>

      {/* ── 하단 상태바 ── */}
      <footer className="h-6 bg-[#0a0a12] border-t border-white/5 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-4 text-[9px] text-white/30">
          <span>에이전트 {Object.values(vibe.agentTerminals).filter((t: any) => t.status === 'running').length}/{Object.keys(vibe.agentTerminals).length} active</span>
          <span>태스크 {vibe.activeTaskCount}개 진행중</span>
          <span>메시지 {vibe.unreadMsgCount}개 미읽음</span>
        </div>
        <div className="text-[9px] text-white/20 font-mono">
          vibe-office v{vibe.appVersion}
        </div>
      </footer>
    </div>
  );
}
