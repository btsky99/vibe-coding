/**
 * ------------------------------------------------------------------------
 * FILE: OfficeApp.tsx
 * DESCRIPTION: 메타버스 오피스 Phase 1 메인 컴포넌트.
 *              기존 Office 모드를 확장하여 존 기반 월드, 운영 HUD,
 *              선택 에이전트 인스펙터, 이벤트 레일을 함께 제공한다.
 * REVISION HISTORY:
 * - 2026-04-06 Codex: 메타버스 오피스 Phase 1 구조로 재작성
 * - 2026-04-03 Claude: 초기 생성 — 2D 오피스 월드 + HUD 레이아웃
 * ------------------------------------------------------------------------
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ClipboardList,
  Database,
  GitBranch,
  LayoutGrid,
  MessageSquare,
  Monitor,
  Radar,
} from 'lucide-react';
import { useVibeData } from '../../hooks/useVibeData';
import { type OfficeZone, useOfficeState } from '../../hooks/useOfficeState';
import OfficeWorld from './OfficeWorld';
import TerminalSlot from '../TerminalSlot';
import MessagesPanel from '../panels/MessagesPanel';
import TasksPanel from '../panels/TasksPanel';
import MemoryPanel from '../panels/MemoryPanel';
import GitPanel from '../panels/GitPanel';

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

interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number;
}

const ZONE_PANEL_MAP: Record<OfficeZone, HudTab> = {
  desk: 'terminal',
  meeting: 'messages',
  review: 'tasks',
  memory: 'memory',
  git: 'git',
  lounge: 'terminal',
  recovery: 'terminal',
  user: 'terminal',
};

const ZONE_ACTION_HINT: Record<OfficeZone, string> = {
  desk: '실시간 실행 및 페어 작업',
  meeting: '토론, 동기화, 프롬프트 라우팅',
  review: '검증, 린트, QA 패스',
  memory: '공유 노트, 메모리, 문서',
  git: '브랜치, 커밋, 릴리즈 흐름',
  lounge: '디스패치 대기 중인 유휴 에이전트',
  recovery: '차단되거나 실패한 에이전트 — 개입 필요',
  user: '운영자 포커스 및 수동 제어',
};

export default function OfficeApp({ onSwitchToClassic }: OfficeAppProps) {
  const vibe = useVibeData();
  const office = useOfficeState({
    agentTerminals: vibe.agentTerminals,
    messages: vibe.messages,
    memory: vibe.memory,
    logs: vibe.logs,
    hiveHealth: vibe.hiveHealth,
  });

  const [hudTab, setHudTab] = useState<HudTab>('terminal');
  const [selectedDesk, setSelectedDesk] = useState(office.selectedDefaultSlot);
  const [selectedZone, setSelectedZone] = useState<OfficeZone>('desk');
  const [speechBubbles, setSpeechBubbles] = useState<SpeechBubble[]>([]);
  const prevStatuses = useRef<Record<string, string>>({});

  useEffect(() => {
    setSelectedDesk((prev) => (prev > 7 ? office.selectedDefaultSlot : prev));
  }, [office.selectedDefaultSlot]);

  useEffect(() => {
    const nextBubbles: SpeechBubble[] = [];
    const now = Date.now();

    for (const presence of office.presences) {
      const prev = prevStatuses.current[presence.terminalId] || 'idle';
      const curr = presence.status;
      if (prev !== curr && (curr === 'running' || curr === 'started')) {
        nextBubbles.push({
          deskId: presence.slotId,
          text: presence.zone === 'meeting' ? '회의 동기화' : '작업 시작',
          createdAt: now,
          duration: 3500,
        });
      }
      if ((prev === 'running' || prev === 'started') && curr !== 'running' && curr !== 'started') {
        nextBubbles.push({
          deskId: presence.slotId,
          text: '작업 완료',
          createdAt: now,
          duration: 4200,
        });
      }
      prevStatuses.current[presence.terminalId] = curr;
    }

    if (nextBubbles.length > 0) {
      setSpeechBubbles((prev) => [...prev, ...nextBubbles].slice(-10));
    }
  }, [office.presences]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setSpeechBubbles((prev) => prev.filter((bubble) => now - bubble.createdAt < bubble.duration));
    }, 1500);
    return () => window.clearInterval(timer);
  }, []);

  const selectedPresence = useMemo(
    () => office.presences.find((presence) => presence.slotId === selectedDesk) ?? null,
    [office.presences, selectedDesk],
  );
  const zoneSummary = office.zones.filter((zone) => zone.id !== 'user');
  const projectName = vibe.currentPath.split(/[/\\]/).filter(Boolean).pop();
  const selectedZoneState = useMemo(
    () => office.zones.find((zone) => zone.id === selectedZone) ?? office.zones[0],
    [office.zones, selectedZone],
  );
  const selectedZoneMembers = useMemo(
    () => office.presences.filter((presence) => presence.zone === selectedZone).slice(0, 4),
    [office.presences, selectedZone],
  );

  const routeZoneToPanel = (zone: OfficeZone) => {
    setHudTab(ZONE_PANEL_MAP[zone]);
  };

  const handleZoneClick = (zone: OfficeZone) => {
    setSelectedZone(zone);
    routeZoneToPanel(zone);
  };

  const handleDeskSelect = (slotId: number) => {
    setSelectedDesk(slotId);
    const presence = office.presences.find((item) => item.slotId === slotId);
    if (presence) {
      setSelectedZone(presence.zone);
      routeZoneToPanel(presence.zone);
    } else {
      setSelectedZone('desk');
      setHudTab('terminal');
    }
  };

  const handleEventFocus = (event: (typeof office.events)[number]) => {
    setSelectedZone(event.zone);
    routeZoneToPanel(event.zone);
    const targetTerminalId = event.terminalIds[0];
    if (!targetTerminalId) return;
    const targetPresence = office.presences.find((presence) => presence.terminalId === targetTerminalId);
    if (targetPresence) {
      setSelectedDesk(targetPresence.slotId);
    }
  };

  const summonMeeting = () => {
    setSelectedZone('meeting');
    setHudTab('messages');
    setSpeechBubbles((prev) => [
      ...prev,
      ...office.presences.slice(0, 3).map((presence) => ({
        deskId: presence.slotId,
        text: '회의실 이동',
        createdAt: Date.now(),
        duration: 3000,
      })),
    ].slice(-12));
  };

  const requestReview = () => {
    setSelectedZone('review');
    setHudTab('tasks');
    if (selectedPresence) {
      setSpeechBubbles((prev) => [
        ...prev,
        {
          deskId: selectedPresence.slotId,
          text: '리뷰 요청됨',
          createdAt: Date.now(),
          duration: 3200,
        },
      ].slice(-12));
    }
  };

  const openStandaloneOfficePage = () => {
    const url = new URL(window.location.href);
    url.searchParams.set('page', 'office');
    window.open(url.toString(), '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-[#081019] text-[#e5eef8]">
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-white/5 bg-[#0b1320] px-4">
        <div className="flex items-center gap-3">
          <span className="bg-gradient-to-r from-cyan-300 via-sky-400 to-fuchsia-400 bg-clip-text text-sm font-black tracking-[0.35em] text-transparent">
            바이브 오피스
          </span>
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-mono text-white/45">
            v{vibe.appVersion}
          </span>
          <span className="text-[10px] text-white/30">
            활성 {office.summary.activeAgents} · 차단 {office.summary.blockedAgents}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-white/10 bg-black/15 px-1 py-0.5">
            {onSwitchToClassic && (
              <button
                type="button"
                onClick={onSwitchToClassic}
                className="rounded px-2 py-0.5 text-[10px] font-semibold text-white/75 transition hover:bg-white/10 hover:text-white"
              >
                클래식
              </button>
            )}
            <button
              type="button"
              className="rounded bg-cyan-400/12 px-2 py-0.5 text-[10px] font-semibold text-cyan-200"
            >
              오피스
            </button>
            <button
              type="button"
              onClick={openStandaloneOfficePage}
              className="rounded px-2 py-0.5 text-[10px] font-semibold text-sky-200 transition hover:bg-white/10"
            >
              오피스 페이지
            </button>
          </div>
          <button
            type="button"
            onClick={summonMeeting}
            className="rounded border border-cyan-400/20 bg-cyan-400/10 px-2.5 py-1 text-[10px] font-semibold text-cyan-200 transition hover:bg-cyan-400/15"
          >
            회의 소집
          </button>
          <button
            type="button"
            onClick={requestReview}
            className="rounded border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200 transition hover:bg-emerald-400/15"
          >
            리뷰 요청
          </button>
          {onSwitchToClassic && (
            <button
              onClick={onSwitchToClassic}
              className="flex items-center gap-1.5 rounded border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-semibold text-white/55 transition hover:bg-white/10 hover:text-white/80"
            >
              <LayoutGrid className="h-3 w-3" />
              클래식
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="relative min-w-0 flex-1 overflow-hidden">
          <OfficeWorld
            presences={office.presences}
            zones={office.zones}
            events={office.events}
            selectedDesk={selectedDesk}
            onDeskClick={handleDeskSelect}
            onZoneClick={handleZoneClick}
            speechBubbles={speechBubbles}
          />

          <div className="absolute left-4 top-4 flex max-w-[70%] flex-wrap gap-2">
            {zoneSummary.map((zone) => (
              <button
                key={zone.id}
                type="button"
                onClick={() => handleZoneClick(zone.id)}
                className={`rounded-full border px-3 py-1 text-[10px] backdrop-blur ${
                  selectedZone === zone.id
                    ? 'border-cyan-300/35 bg-cyan-300/12'
                    : 'border-white/10 bg-black/35 hover:bg-black/50'
                }`}
              >
                <span className="font-semibold text-white/75">{zone.label}</span>
                <span className="ml-2 text-white/35">{zone.occupancy}</span>
              </button>
            ))}
          </div>

          <div className="absolute bottom-4 left-4 w-[320px] rounded-xl border border-white/10 bg-[#08111ccc] p-3 backdrop-blur">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-white/80">
              <Radar className="h-3.5 w-3.5 text-cyan-300" />
              이벤트 레일
            </div>
            <div className="space-y-2">
              {office.events.slice(0, 4).map((event) => (
                <button
                  key={event.id}
                  type="button"
                  onClick={() => handleEventFocus(event)}
                  className="block w-full rounded-lg border border-white/6 bg-white/[0.03] px-2.5 py-2 text-left transition hover:border-cyan-300/20 hover:bg-cyan-300/[0.05]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-[10px] font-semibold text-white/78">{event.title}</div>
                    <span className="text-[9px] uppercase tracking-[0.18em] text-white/28">{event.zone}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-white/42">{event.subtitle}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <aside className="flex w-[430px] shrink-0 flex-col border-l border-white/5 bg-[#0c1522]/95 backdrop-blur">
          <div className="border-b border-white/5 px-3 py-3">
            <div className="mb-3 rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="mb-1 text-[10px] uppercase tracking-[0.2em] text-white/35">포커스 에이전트</div>
              {selectedPresence ? (
                <>
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-bold text-white/85">
                      T{selectedPresence.slotId + 1} · {selectedPresence.agent || 'unknown'}
                    </div>
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/45">
                      {selectedPresence.zone}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={summonMeeting}
                      className="rounded border border-cyan-400/20 bg-cyan-400/10 px-2 py-1 text-[10px] text-cyan-200 transition hover:bg-cyan-400/15"
                    >
                      회의
                    </button>
                    <button
                      type="button"
                      onClick={requestReview}
                      className="rounded border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[10px] text-emerald-200 transition hover:bg-emerald-400/15"
                    >
                      리뷰
                    </button>
                  </div>
                  <div className="mt-2 text-[11px] text-white/48">
                    {selectedPresence.liveTask || '진행 중인 작업 없음'}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {selectedPresence.badges.map((badge) => (
                      <span key={badge} className="rounded-full bg-cyan-400/10 px-2 py-0.5 text-[10px] text-cyan-200">
                        {badge}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <div className="text-[11px] text-white/40">에이전트를 확인하려면 데스크를 선택하세요.</div>
              )}
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-white/28">활성 존</div>
                <div className="mt-1 text-lg font-bold text-white/82">{office.summary.busyZones}</div>
              </div>
              <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-white/28">태스크</div>
                <div className="mt-1 text-lg font-bold text-white/82">{vibe.activeTaskCount}</div>
              </div>
              <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-white/28">읽지 않음</div>
                <div className="mt-1 text-lg font-bold text-white/82">{vibe.unreadMsgCount}</div>
              </div>
            </div>

            <div className="mt-3 rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.2em] text-white/35">존 제어</div>
                  <div className="mt-1 text-sm font-bold text-white/82">{selectedZoneState?.label ?? 'Desk'}</div>
                </div>
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/45">
                  {selectedZoneState?.occupancy ?? 0} 활성
                </span>
              </div>
              <div className="mt-2 text-[11px] text-white/46">
                {ZONE_ACTION_HINT[selectedZone]}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {selectedZoneMembers.length > 0 ? (
                  selectedZoneMembers.map((presence) => (
                    <button
                      key={presence.terminalId}
                      type="button"
                      onClick={() => handleDeskSelect(presence.slotId)}
                      className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-white/68 transition hover:border-cyan-300/25 hover:bg-cyan-300/[0.08]"
                    >
                      T{presence.slotId + 1} {presence.agent}
                    </button>
                  ))
                ) : (
                  <span className="text-[10px] text-white/32">현재 이 존에 배정된 에이전트가 없습니다.</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex h-10 shrink-0 items-center gap-1 border-b border-white/5 bg-[#09111c] px-2">
            {HUD_TABS.map((tab) => {
              const Icon = tab.icon;
              const active = hudTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setHudTab(tab.id)}
                  className={`flex items-center gap-1 rounded px-2.5 py-1 text-[10px] font-semibold transition ${
                    active
                      ? 'border border-cyan-400/25 bg-cyan-400/12 text-cyan-200'
                      : 'border border-transparent text-white/40 hover:bg-white/5 hover:text-white/70'
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="flex-1 overflow-hidden p-2">
            {hudTab === 'terminal' ? (
              <div className="h-full min-h-0">
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
              <MemoryPanel currentProjectName={projectName} />
            ) : (
              <GitPanel
                currentPath={vibe.currentPath}
                onChangesCount={(count, conflictCount) => {
                  vibe.setTotalGitChanges(count);
                  vibe.setConflictCount(conflictCount);
                }}
              />
            )}
          </div>

          <footer className="flex h-7 shrink-0 items-center justify-between border-t border-white/5 px-3 text-[9px] text-white/28">
            <div className="flex items-center gap-3">
              <span>{office.summary.activeAgents} 에이전트 활성</span>
              <span>{office.summary.blockedAgents} 복구 중</span>
            </div>
            <div className="flex items-center gap-1">
              <Activity className="h-3 w-3" />
              office-phase1
            </div>
          </footer>
        </aside>
      </div>
    </div>
  );
}
