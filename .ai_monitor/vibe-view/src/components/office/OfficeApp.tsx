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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  FolderOpen,
  LayoutGrid,
  Pencil,
  Plus,
  Radar,
  RefreshCw,
  Settings2,
  Trash2,
  X,
} from 'lucide-react';
import { useVibeData } from '../../hooks/useVibeData';
import { type OfficeZone, useOfficeState } from '../../hooks/useOfficeState';
import { type AgentCli, useWorkspaceProfiles, MAX_SLOTS } from '../../hooks/useWorkspaceProfiles';
import { useCliModels, getDefaultModel } from '../../hooks/useCliModels';
import IsometricOffice from './IsometricOffice';
import OfficeChatPanel from './OfficeChatPanel';
import { useOfficeChat } from '../../hooks/useOfficeChat';

// HUD 탭 제거됨 — 오피스 우측은 채팅 전용

interface OfficeAppProps {
  onSwitchToClassic?: () => void;
}

interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number;
}

export interface AgentStats {
  agent_id: string;
  total_xp: number;
  level: number;
  task_count: number;
  skill_map: Record<string, number>;
  streak_days: number;
}

// ZONE_PANEL_MAP 제거 — 채팅 전용 모드

// ZONE_ACTION_HINT 제거 — 채팅 전용 모드에서 미사용

export default function OfficeApp({ onSwitchToClassic }: OfficeAppProps) {
  const vibe = useVibeData();

  // ── 워크스페이스 프로필 (office 전에 초기화 — profileSlots를 전달하기 위해) ──
  const wp = useWorkspaceProfiles();
  const cliModels = useCliModels();

  const office = useOfficeState({
    agentTerminals: vibe.agentTerminals,
    messages: vibe.messages,
    memory: vibe.memory,
    logs: vibe.logs,
    hiveHealth: vibe.hiveHealth,
    profileSlots: wp.activeProfile.slots.map(s => ({ name: s.name, cli: s.cli, model: s.model, role: s.role })),
    departments: wp.activeProfile.departments.map(d => ({ id: d.id, name: d.name, color: d.color, agentCount: d.agents.length })),
  });
  const [showAddSlot, setShowAddSlot] = useState(false);
  const [showProfileMgr, setShowProfileMgr] = useState(false);
  const [newSlotName, setNewSlotName] = useState('');
  const [newSlotCli, setNewSlotCli] = useState<AgentCli>('claude');
  const [newSlotModel, setNewSlotModel] = useState('claude-sonnet-4-6');
  const [newSlotYolo, setNewSlotYolo] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  // 슬롯 편집 모달
  const [editSlotId, setEditSlotId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editCli, setEditCli] = useState<AgentCli>('claude');
  const [editModel, setEditModel] = useState('');
  const [editYolo, setEditYolo] = useState(false);

  // ── 프로젝트 폴더 선택 ──
  const [projectPath, setProjectPath] = useState('');
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => { if (data.last_path) setProjectPath(data.last_path); })
      .catch(() => {});
  }, []);

  const handleChangeProject = useCallback(async () => {
    let selectedPath: string | null = null;
    try {
      const pywebview = (window as any).pywebview;
      if (pywebview?.api?.select_folder) {
        const data = await pywebview.api.select_folder();
        if (data.status === 'success' && data.path) selectedPath = data.path;
      } else {
        const res = await fetch('/api/select-folder', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success' && data.path) selectedPath = data.path;
      }
    } catch {
      selectedPath = prompt('프로젝트 폴더 경로:', projectPath);
    }
    if (selectedPath) {
      setProjectPath(selectedPath);
      fetch('/api/config/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ last_path: selectedPath }),
      }).catch(() => {});
    }
  }, [projectPath]);

  // ── 에이전트 경험/성장 데이터 폴링 ──
  const [agentStats, setAgentStats] = useState<AgentStats[]>([]);
  const fetchStats = useCallback(() => {
    fetch('/api/experience/stats')
      .then(r => r.json())
      .then(data => { if (data.stats) setAgentStats(data.stats); })
      .catch(err => console.warn('[OfficeApp] 에이전트 스탯 조회 실패:', err));
  }, []);
  useEffect(() => {
    fetchStats();
    const timer = window.setInterval(fetchStats, 30_000); // 30초마다 폴링
    return () => window.clearInterval(timer);
  }, [fetchStats]);

  // ── agent/chat API 기반 채팅 ──
  // selectedDesk(슬롯 인덱스) → 터미널 ID 매핑
  const [selectedDesk, setSelectedDesk] = useState(office.selectedDefaultSlot);
  const [selectedZone, setSelectedZone] = useState<OfficeZone>('desk');
  const [speechBubbles, setSpeechBubbles] = useState<SpeechBubble[]>([]);
  const prevStatuses = useRef<Record<string, string>>({});

  const activeSlots = wp.activeProfile.slots;
  const slotCount = activeSlots.length;

  // ── 오피스 채팅 (agent/chat SSE 기반) ──
  // 선택된 슬롯의 CLI에 해당하는 오피스 터미널 ID를 생성한다.
  // PTY spawn 대신 agent_api.py의 /api/agent/chat을 사용.

  // 선택된 슬롯의 CLI
  const selectedCli = useMemo(() => {
    if (selectedDesk === -1) {
      return activeSlots.find(s => (s.role || '').toLowerCase() === 'ceo')?.cli || 'claude';
    }
    return activeSlots[selectedDesk]?.cli || 'claude';
  }, [selectedDesk, activeSlots]);

  // 선택된 슬롯의 YOLO 모드
  const selectedYolo = useMemo(() => {
    if (selectedDesk === -1) {
      return activeSlots.find(s => (s.role || '').toLowerCase() === 'ceo')?.yolo || false;
    }
    return activeSlots[selectedDesk]?.yolo || false;
  }, [selectedDesk, activeSlots]);

  // 오피스 터미널 ID: 슬롯 인덱스 기반 (O1, O2, ...)
  const terminalId = useMemo(() => {
    if (selectedDesk === -1) return 'O-CEO';
    return `O${selectedDesk + 1}`;
  }, [selectedDesk]);

  const chatHook = useOfficeChat(terminalId, selectedCli, selectedYolo);

  useEffect(() => {
    setSelectedDesk((prev) => (prev >= slotCount ? 0 : prev));
  }, [slotCount]);

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
  // 'user' zone(대표실)은 사이드바 zone 요약에서 제외 — 대표실은 월드에 별도로 표시됨
  const zoneSummary = office.zones.filter((zone) => zone.id !== 'user');
  // 'desk'는 폴백 별칭이라 사이드바에서 숨김
  const visibleZones = zoneSummary.filter((zone) => zone.id !== 'desk');
  void visibleZones;
  const projectName = vibe.currentPath.split(/[/\\]/).filter(Boolean).pop();
  // selectedZoneState/selectedZoneMembers 제거 — 채팅 모드에서 미사용

  const handleZoneClick = (zone: OfficeZone) => {
    setSelectedZone(zone);
  };

  const handleDeskSelect = (slotId: number) => {
    setSelectedDesk(slotId);
    if (slotId === -1) {
      /* CEO 특수값 */
      setSelectedZone('user');
      return;
    }
    const presence = office.presences.find((item) => item.slotId === slotId);
    if (presence) {
      setSelectedZone(presence.zone);
    } else {
      setSelectedZone('desk');
    }
  };

  const handleEventFocus = (event: (typeof office.events)[number]) => {
    setSelectedZone(event.zone);
    const targetTerminalId = event.terminalIds[0];
    if (!targetTerminalId) return;
    const targetPresence = office.presences.find((presence) => presence.terminalId === targetTerminalId);
    if (targetPresence) {
      setSelectedDesk(targetPresence.slotId);
    }
  };

  const summonMeeting = () => {
    setSelectedZone('meeting');
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
    <div className="flex h-screen w-full flex-col overflow-hidden bg-[#060a0f] text-[#e5eef8]" onContextMenu={e => e.preventDefault()}>
      {/* ═══ 헤더 ═══ */}
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-white/[0.06] bg-[#080e18]/90 px-4 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <span className="bg-gradient-to-r from-cyan-300 via-sky-400 to-fuchsia-400 bg-clip-text text-xs font-black tracking-[0.3em] text-transparent">
            VIBE OFFICE
          </span>
          <div className="h-3 w-px bg-white/10" />
          <select
            value={wp.activeProfileId}
            onChange={e => wp.setActiveProfile(e.target.value)}
            className="rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-white/60 outline-none backdrop-blur"
          >
            {wp.profiles.map(p => (
              <option key={p.id} value={p.id} className="bg-[#0b1320]">{p.name} ({p.slots.length})</option>
            ))}
          </select>
          <div className="h-3 w-px bg-white/10" />
          <button
            onClick={handleChangeProject}
            className="flex items-center gap-1 rounded border border-white/8 bg-white/[0.03] px-1.5 py-0.5 text-[9px] text-white/40 hover:text-white/70"
            title={projectPath || '프로젝트 선택'}
          >
            <FolderOpen className="h-2.5 w-2.5" />
            <span className="max-w-[120px] truncate">{projectPath ? projectPath.split(/[/\\]/).pop() : '프로젝트'}</span>
          </button>
          <button onClick={() => setShowAddSlot(true)} className="rounded border border-cyan-500/20 bg-cyan-500/8 p-1 text-cyan-300 hover:bg-cyan-500/15" title="터미널 추가">
            <Plus className="h-3 w-3" />
          </button>
          <button onClick={() => setShowProfileMgr(true)} className="rounded border border-white/8 bg-white/[0.03] p-1 text-white/35 hover:text-white/60" title="프로필 관리">
            <Settings2 className="h-3 w-3" />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-white/25">{office.summary.activeAgents} 활성 · {office.summary.blockedAgents} 차단</span>
          <button onClick={summonMeeting} className="rounded border border-cyan-500/20 bg-cyan-500/8 px-2 py-0.5 text-[9px] font-bold text-cyan-300 hover:bg-cyan-500/15">회의</button>
          <button onClick={requestReview} className="rounded border border-emerald-500/20 bg-emerald-500/8 px-2 py-0.5 text-[9px] font-bold text-emerald-300 hover:bg-emerald-500/15">리뷰</button>
          <button onClick={() => {
            chatHook.clearChat();
            window.location.href = window.location.href;
          }} className="rounded border border-white/8 bg-white/[0.03] p-1 text-white/30 hover:text-white/60" title="새로고침">
            <RefreshCw className="h-2.5 w-2.5" />
          </button>
          {onSwitchToClassic && (
            <button onClick={onSwitchToClassic} className="rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[9px] font-bold text-white/50 hover:text-white/80">
              <LayoutGrid className="mr-1 inline h-2.5 w-2.5" />클래식
            </button>
          )}
        </div>
      </header>

      {/* ═══ 3-Column 본문 ═══ */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── 왼쪽: 부서별 에이전트 사이드바 ── */}
        <aside className="flex w-[190px] shrink-0 flex-col overflow-y-auto border-r border-white/[0.04] bg-[#080d15]">
          {/* 조직 헤더 — 하드코딩된 "대표" 아이콘 제거 (CEO는 월드 대표실에 렌더링됨) */}
          <div className="flex items-center justify-between border-b border-white/[0.04] px-3 py-3">
            <div className="text-[9px] font-black uppercase tracking-[0.2em] text-white/40">조직도</div>
            <span className="text-[8px] text-white/25">{activeSlots.length}명</span>
          </div>
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-2">
            {wp.activeProfile.departments.map(dept => {
              // 이 부서의 에이전트들의 flat index 시작점
              let flatStartIdx = 0;
              for (const d of wp.activeProfile.departments) {
                if (d.id === dept.id) break;
                flatStartIdx += d.agents.length;
              }
              return (
                <div key={dept.id}>
                  {/* 부서 헤더 */}
                  <div className="flex items-center gap-1.5 px-1 py-1">
                    <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: dept.color }} />
                    <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: `${dept.color}cc` }}>
                      {dept.name}
                    </span>
                    <span className="text-[8px] text-white/15">{dept.agents.length}</span>
                  </div>
                  {/* 에이전트 목록 */}
                  <div className="space-y-0.5">
                    {dept.agents.map((agent, agentIdx) => {
                      const flatIdx = flatStartIdx + agentIdx;
                      const presence = office.presences.find(p => p.slotId === flatIdx);
                      const isActive = selectedDesk === flatIdx;
                      const cliColor = agent.cli === 'claude' ? '#a78bfa' : agent.cli === 'gemini' ? '#34d399' : '#22d3ee';
                      const busy = presence?.status === 'running' || presence?.status === 'started';
                      const isCeoAgent = (agent.role || '').toLowerCase() === 'ceo';
                      const isActiveFinal = isCeoAgent ? selectedDesk === -1 : isActive;
                      return (
                        <button
                          key={agent.id}
                          onClick={() => handleDeskSelect(isCeoAgent ? -1 : flatIdx)}
                          className={`group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-all ${
                            isActiveFinal
                              ? 'bg-white/[0.06] border border-cyan-500/25'
                              : 'border border-transparent hover:bg-white/[0.03]'
                          }`}
                        >
                          <div className="relative shrink-0">
                            <div
                              className={`h-6 w-6 rounded-full flex items-center justify-center text-[8px] font-black text-white/90 ${busy ? 'animate-pulse' : ''}`}
                              style={{ backgroundColor: `${cliColor}25`, border: `1.5px solid ${cliColor}${isActive ? 'aa' : '33'}` }}
                            >
                              {agent.cli[0].toUpperCase()}
                            </div>
                            {busy && (
                              <div className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-green-400" style={{ boxShadow: '0 0 4px rgba(74,222,128,0.6)' }} />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className={`truncate text-[9px] font-bold ${isActiveFinal ? 'text-white/85' : 'text-white/50'}`}>
                              {agent.name}
                            </div>
                            <div className="truncate text-[7px] text-white/20">
                              {agent.model.replace('claude-', '').replace('gemini-', '').replace('gpt-', '')}
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditSlotId(agent.id);
                              setEditName(agent.name);
                              setEditCli(agent.cli);
                              setEditModel(agent.model);
                              setEditYolo(agent.yolo);
                            }}
                            className="shrink-0 rounded p-0.5 text-white/0 group-hover:text-white/25 hover:!text-white/60 transition-all"
                          >
                            <Pencil className="h-2.5 w-2.5" />
                          </button>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          {/* 하단 존 목록 */}
          <div className="border-t border-white/[0.04] px-2 py-2 space-y-0.5">
            {zoneSummary.slice(0, 5).map(zone => (
              <button
                key={zone.id}
                onClick={() => handleZoneClick(zone.id)}
                className={`flex w-full items-center justify-between rounded px-2 py-1 text-[9px] transition ${
                  selectedZone === zone.id ? 'bg-cyan-500/10 text-cyan-300' : 'text-white/30 hover:text-white/50'
                }`}
              >
                <span>{zone.label}</span>
                {zone.occupancy > 0 && <span className="rounded-full bg-white/[0.06] px-1.5 text-[8px]">{zone.occupancy}</span>}
              </button>
            ))}
          </div>

          {/* ── 선택된 에이전트 스킬 패널 ── */}
          {(() => {
            const selCli = selectedDesk === -1
              ? (activeSlots.find(s => (s.role || '').toLowerCase() === 'ceo')?.cli || 'claude')
              : activeSlots[selectedDesk]?.cli || '';
            const selStats = agentStats.find(s => s.agent_id === selCli.toLowerCase());
            if (!selStats) return null;
            const skillEntries = Object.entries(selStats.skill_map || {}).sort((a, b) => b[1] - a[1]);
            const maxSkillXp = skillEntries.length > 0 ? skillEntries[0][1] : 1;
            const DOMAIN_LABEL: Record<string, string> = {
              frontend: '프론트엔드', backend: '백엔드', db: 'DB', infra: '인프라',
              docs: '문서', config: '설정', general: '일반', build: '빌드',
            };
            const DOMAIN_COLOR: Record<string, string> = {
              frontend: '#22d3ee', backend: '#a78bfa', db: '#f97316', infra: '#ef4444',
              docs: '#94a3b8', config: '#64748b', general: '#6b7280', build: '#fbbf24',
            };
            return (
              <div className="border-t border-white/[0.04] px-3 py-2">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[8px] uppercase tracking-widest text-white/25">스킬 맵</span>
                  <span className="text-[9px] font-bold" style={{ color: selStats.level >= 7 ? '#a78bfa' : '#94a3b8' }}>
                    Lv.{selStats.level} · {selStats.total_xp} XP
                  </span>
                </div>
                <div className="space-y-1">
                  {skillEntries.slice(0, 6).map(([domain, xp]) => (
                    <div key={domain} className="flex items-center gap-2">
                      <span className="w-16 truncate text-[8px] text-white/40">{DOMAIN_LABEL[domain] || domain}</span>
                      <div className="relative h-2 flex-1 rounded-full bg-white/[0.06]">
                        <div
                          className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                          style={{ width: `${(xp / maxSkillXp) * 100}%`, backgroundColor: DOMAIN_COLOR[domain] || '#6b7280' }}
                        />
                      </div>
                      <span className="w-8 text-right text-[7px] text-white/30">{xp}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[7px] text-white/20">
                  <span>{selStats.task_count}개 작업 완료</span>
                  {selStats.streak_days > 0 && <span>{selStats.streak_days}일 연속</span>}
                </div>
              </div>
            );
          })()}
        </aside>

        {/* ── 가운데: 오피스 월드 ── */}
        <div className="relative min-w-0 flex-1 overflow-hidden">
          <IsometricOffice
            presences={office.presences}
            zones={office.zones}
            events={office.events}
            selectedDesk={selectedDesk}
            onDeskClick={handleDeskSelect}
            onZoneClick={handleZoneClick}
            speechBubbles={speechBubbles}
            slotNames={activeSlots.map(s => s.name)}
            slotRoles={activeSlots.map(s => s.role || 'unknown')}
            agentStats={agentStats}
            slotClis={activeSlots.map(s => s.cli)}
          />

          {/* 이벤트 레일 (월드 위 오버레이) */}
          <div className="absolute bottom-3 left-3 right-3 flex items-end gap-2 pointer-events-none">
            {office.events.slice(0, 3).map((event) => (
              <button
                key={event.id}
                onClick={() => handleEventFocus(event)}
                className="pointer-events-auto rounded-lg border border-white/[0.06] bg-[#0a1018ee] px-3 py-1.5 text-left backdrop-blur-xl transition hover:border-cyan-500/20"
              >
                <div className="text-[9px] font-bold text-white/60 truncate">{event.title}</div>
                <div className="text-[8px] text-white/25 truncate">{event.subtitle}</div>
              </button>
            ))}
          </div>

          {/* 상태 요약 (월드 위 오버레이) */}
          <div className="absolute top-3 right-3 flex gap-2 pointer-events-none">
            <div className="rounded-lg border border-white/[0.06] bg-[#0a1018dd] px-2.5 py-1.5 backdrop-blur-xl">
              <div className="text-[8px] uppercase tracking-widest text-white/25">존</div>
              <div className="text-sm font-bold text-white/70">{office.summary.busyZones}</div>
            </div>
            <div className="rounded-lg border border-white/[0.06] bg-[#0a1018dd] px-2.5 py-1.5 backdrop-blur-xl">
              <div className="text-[8px] uppercase tracking-widest text-white/25">태스크</div>
              <div className="text-sm font-bold text-white/70">{vibe.activeTaskCount}</div>
            </div>
          </div>
        </div>

        {/* ── 오른쪽: agent/chat API 채팅 패널 ── */}
        <aside className="flex w-[380px] shrink-0 flex-col border-l border-white/[0.04] bg-[#0a0f18]">
          <OfficeChatPanel
            chatMessages={chatHook.messages}
            selectedAgent={selectedDesk === -1 ? 'ceo' : (activeSlots[selectedDesk]?.cli || 'claude')}
            selectedSlotName={selectedDesk === -1
              ? (activeSlots.find(s => s.role?.toLowerCase() === 'ceo')?.name ?? 'CEO')
              : (activeSlots[selectedDesk]?.name || `터미널 ${selectedDesk + 1}`)}
            terminalId={terminalId}
            isStreaming={chatHook.isStreaming}
            sendError={chatHook.sendError}
            onSendMessage={chatHook.sendMessage}
            onStopStreaming={chatHook.stopStreaming}
            onClearChat={chatHook.clearChat}
          />
        </aside>
      </div>

      {/* ── 슬롯 편집 모달 ── */}
      {editSlotId && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-[340px] rounded-xl border border-white/15 bg-[#0c1522] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white/85">슬롯 편집</h3>
              <button onClick={() => setEditSlotId(null)} className="text-white/30 hover:text-white/70"><X className="h-4 w-4" /></button>
            </div>
            <label className="mb-2 block">
              <span className="text-[10px] text-white/50">이름</span>
              <input
                value={editName}
                onChange={e => setEditName(e.target.value)}
                className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none focus:border-cyan-400/40"
              />
            </label>
            <label className="mb-2 block">
              <span className="text-[10px] text-white/50">CLI</span>
              <select
                value={editCli}
                onChange={e => {
                  const cli = e.target.value as AgentCli;
                  setEditCli(cli);
                  setEditModel(getDefaultModel(cli));
                }}
                className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none"
              >
                <option value="claude" className="bg-[#0c1522]">Claude</option>
                <option value="gemini" className="bg-[#0c1522]">Gemini</option>
                <option value="codex" className="bg-[#0c1522]">Codex</option>
              </select>
            </label>
            <label className="mb-2 block">
              <span className="text-[10px] text-white/50">모델</span>
              <select
                value={editModel}
                onChange={e => setEditModel(e.target.value)}
                className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none"
              >
                {(cliModels[editCli] || []).map(m => (
                  <option key={m.id} value={m.id} className="bg-[#0c1522]">{m.label}</option>
                ))}
              </select>
            </label>
            <label className="mb-4 flex items-center gap-2">
              <input type="checkbox" checked={editYolo} onChange={e => setEditYolo(e.target.checked)} className="accent-cyan-400" />
              <span className="text-[10px] text-white/60">자율 실행 (YOLO)</span>
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  wp.updateSlot(wp.activeProfileId, editSlotId, {
                    name: editName,
                    cli: editCli,
                    model: editModel,
                    yolo: editYolo,
                  });
                  setEditSlotId(null);
                }}
                className="flex-1 rounded bg-cyan-500/20 py-2 text-xs font-bold text-cyan-200 transition hover:bg-cyan-500/30"
              >
                저장
              </button>
              <button
                onClick={() => {
                  wp.removeSlot(wp.activeProfileId, editSlotId);
                  setEditSlotId(null);
                }}
                className="rounded bg-red-500/15 px-3 py-2 text-xs font-bold text-red-300 transition hover:bg-red-500/25"
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 터미널 추가 모달 ── */}
      {showAddSlot && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-[340px] rounded-xl border border-white/15 bg-[#0c1522] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white/85">터미널 추가</h3>
              <button onClick={() => setShowAddSlot(false)} className="text-white/30 hover:text-white/70"><X className="h-4 w-4" /></button>
            </div>
            {slotCount >= MAX_SLOTS ? (
              <div className="text-[11px] text-red-300">최대 {MAX_SLOTS}개까지만 추가할 수 있습니다.</div>
            ) : (
              <>
                <label className="mb-2 block">
                  <span className="text-[10px] text-white/50">이름</span>
                  <input
                    value={newSlotName}
                    onChange={e => setNewSlotName(e.target.value)}
                    placeholder={`터미널 ${slotCount + 1}`}
                    className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none focus:border-cyan-400/40"
                  />
                </label>
                <label className="mb-2 block">
                  <span className="text-[10px] text-white/50">CLI</span>
                  <select
                    value={newSlotCli}
                    onChange={e => {
                      const cli = e.target.value as AgentCli;
                      setNewSlotCli(cli);
                      setNewSlotModel(getDefaultModel(cli));
                    }}
                    className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none"
                  >
                    <option value="claude" className="bg-[#0c1522]">Claude</option>
                    <option value="gemini" className="bg-[#0c1522]">Gemini</option>
                    <option value="codex" className="bg-[#0c1522]">Codex</option>
                  </select>
                </label>
                <label className="mb-2 block">
                  <span className="text-[10px] text-white/50">모델</span>
                  <select
                    value={newSlotModel}
                    onChange={e => setNewSlotModel(e.target.value)}
                    className="mt-1 block w-full rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none"
                  >
                    {(cliModels[newSlotCli] || []).map(m => (
                      <option key={m.id} value={m.id} className="bg-[#0c1522]">{m.label}</option>
                    ))}
                  </select>
                </label>
                <label className="mb-4 flex items-center gap-2">
                  <input type="checkbox" checked={newSlotYolo} onChange={e => setNewSlotYolo(e.target.checked)} className="accent-cyan-400" />
                  <span className="text-[10px] text-white/60">자율 실행 (YOLO)</span>
                </label>
                <button
                  onClick={() => {
                    wp.addSlot(wp.activeProfileId, {
                      name: newSlotName || `터미널 ${slotCount + 1}`,
                      role: 'fullstack',
                      cli: newSlotCli,
                      model: newSlotModel,
                      skills: ['code'],
                      avatar: 'layers',
                      yolo: newSlotYolo,
                    });
                    setNewSlotName('');
                    setShowAddSlot(false);
                  }}
                  className="w-full rounded bg-cyan-500/20 py-2 text-xs font-bold text-cyan-200 transition hover:bg-cyan-500/30"
                >
                  추가
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── 프로필 관리 모달 ── */}
      {showProfileMgr && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="max-h-[80vh] w-[420px] overflow-y-auto rounded-xl border border-white/15 bg-[#0c1522] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white/85">프로필 관리</h3>
              <button onClick={() => setShowProfileMgr(false)} className="text-white/30 hover:text-white/70"><X className="h-4 w-4" /></button>
            </div>

            {/* 새 프로필 만들기 */}
            <div className="mb-4 flex gap-2">
              <input
                value={newProfileName}
                onChange={e => setNewProfileName(e.target.value)}
                placeholder="새 프로필 이름"
                className="flex-1 rounded border border-white/15 bg-white/5 px-2 py-1.5 text-xs text-white/80 outline-none"
              />
              <button
                onClick={() => {
                  if (newProfileName.trim()) {
                    const id = wp.addProfile(newProfileName.trim());
                    wp.setActiveProfile(id);
                    setNewProfileName('');
                  }
                }}
                className="rounded bg-cyan-500/20 px-3 py-1.5 text-xs font-bold text-cyan-200 hover:bg-cyan-500/30"
              >
                생성
              </button>
            </div>

            {/* 프로필 목록 */}
            {wp.profiles.map(profile => (
              <div key={profile.id} className={`mb-3 rounded-lg border p-3 ${
                profile.id === wp.activeProfileId ? 'border-cyan-400/30 bg-cyan-400/5' : 'border-white/8 bg-white/[0.02]'
              }`}>
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => wp.setActiveProfile(profile.id)}
                    className="text-xs font-bold text-white/80 hover:text-cyan-200"
                  >
                    {profile.name} ({profile.slots.length}개)
                  </button>
                  {!profile.isDefault && (
                    <button onClick={() => wp.deleteProfile(profile.id)} className="text-white/25 hover:text-red-300">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
                <div className="mt-2 space-y-1">
                  {profile.slots.map(slot => (
                    <div key={slot.id} className="flex items-center justify-between rounded bg-white/[0.03] px-2 py-1">
                      <span className="text-[10px] text-white/60">{slot.name}</span>
                      <span className="text-[10px] text-white/35">{slot.cli} · {slot.model}</span>
                      {profile.id === wp.activeProfileId && (
                        <button
                          onClick={() => wp.removeSlot(profile.id, slot.id)}
                          className="text-white/20 hover:text-red-300"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
