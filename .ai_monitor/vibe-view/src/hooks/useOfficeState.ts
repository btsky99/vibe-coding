/**
 * ------------------------------------------------------------------------
 * FILE: useOfficeState.ts
 * DESCRIPTION: 메타버스 오피스 전용 파생 상태 계산 훅.
 *              기존 useVibeData()가 수집한 에이전트/메시지/메모리/로그를 바탕으로
 *              에이전트 위치, 존 상태, 이벤트 카드, 포커스 대상을 계산한다.
 * REVISION HISTORY:
 * - 2026-04-06 Codex: 초기 작성 — Phase 1 메타버스 오피스 공간 상태 모델 도입
 * ------------------------------------------------------------------------
 */

import { useMemo } from 'react';
import type { AgentMessage, LogRecord, MemoryEntry } from '../types';

export type OfficeZone =
  | 'desk'
  | 'meeting'
  | 'review'
  | 'memory'
  | 'git'
  | 'lounge'
  | 'recovery'
  | 'user';

export interface OfficeAgentPresence {
  terminalId: string;
  slotId: number;
  agent: string;
  status: string;
  pipelineStage: string;
  liveTask: string;
  zone: OfficeZone;
  anchorId: string;
  badges: string[];
  colorKey: string;
}

export interface OfficeZoneState {
  id: OfficeZone;
  label: string;
  occupancy: number;
  warningCount: number;
  primaryTerminalIds: string[];
}

export interface OfficeEventCard {
  id: string;
  zone: OfficeZone;
  title: string;
  subtitle: string;
  severity: 'info' | 'success' | 'warning' | 'error';
  terminalIds: string[];
}

interface UseOfficeStateArgs {
  agentTerminals: Record<string, any>;
  messages: AgentMessage[];
  memory: MemoryEntry[];
  logs: LogRecord[];
  hiveHealth: any;
}

const ZONE_LABELS: Record<OfficeZone, string> = {
  desk: 'Desk',
  meeting: 'Meeting',
  review: 'Review',
  memory: 'Memory',
  git: 'Git',
  lounge: 'Lounge',
  recovery: 'Recovery',
  user: 'User',
};

function deriveZone(data: any, hiveHealth: any): OfficeZone {
  const status = String(data?.status || 'idle').toLowerCase();
  const stage = String(data?.pipeline_stage || 'idle').toLowerCase();
  const task = String(data?.live_task || '').toLowerCase();

  if (status.includes('error') || status.includes('failed') || task.includes('hang')) {
    return 'recovery';
  }
  if (hiveHealth?.status === 'healing' && status !== 'idle') {
    return 'recovery';
  }
  if (task.includes('debate') || task.includes('meeting') || task.includes('discussion') || task.includes('review with')) {
    return 'meeting';
  }
  if (stage === 'verifying' || task.includes('test') || task.includes('verify') || task.includes('lint')) {
    return 'review';
  }
  if (task.includes('memory') || task.includes('zettel') || task.includes('docs') || task.includes('note')) {
    return 'memory';
  }
  if (task.includes('commit') || task.includes('git') || task.includes('merge') || task.includes('release')) {
    return 'git';
  }
  if (status === 'running' || status === 'started' || stage === 'modifying' || stage === 'analyzing') {
    return 'desk';
  }
  return 'lounge';
}

function makeBadges(data: any, zone: OfficeZone): string[] {
  const badges: string[] = [];
  const stage = String(data?.pipeline_stage || '').toLowerCase();

  if (zone === 'meeting') badges.push('sync');
  if (zone === 'review') badges.push('qa');
  if (zone === 'memory') badges.push('notes');
  if (zone === 'git') badges.push('git');
  if (zone === 'recovery') badges.push('alert');
  if (stage === 'modifying') badges.push('write');
  if (stage === 'analyzing') badges.push('analyze');
  if (stage === 'verifying') badges.push('verify');

  return badges.slice(0, 3);
}

export function useOfficeState({
  agentTerminals,
  messages,
  memory,
  logs,
  hiveHealth,
}: UseOfficeStateArgs) {
  return useMemo(() => {
    const presences: OfficeAgentPresence[] = Object.entries(agentTerminals)
      .map(([terminalId, data]) => {
        const slotId = Math.max(0, Number(String(terminalId).replace('terminal_', '')) - 1);
        const agent = String(data?.cli || 'unknown').toLowerCase();
        const zone = deriveZone(data, hiveHealth);

        return {
          terminalId,
          slotId,
          agent,
          status: String(data?.status || 'idle'),
          pipelineStage: String(data?.pipeline_stage || 'idle'),
          liveTask: String(data?.live_task || ''),
          zone,
          anchorId: zone === 'desk' ? `desk-${slotId}` : zone,
          badges: makeBadges(data, zone),
          colorKey: ['claude', 'gemini', 'codex'].includes(agent) ? agent : 'unknown',
        };
      })
      .sort((a, b) => a.slotId - b.slotId);

    const zones = (Object.keys(ZONE_LABELS) as OfficeZone[]).map((id) => {
      const members = presences.filter((p) => p.zone === id);
      const warningCount = members.filter((p) => p.zone === 'recovery').length;
      return {
        id,
        label: ZONE_LABELS[id],
        occupancy: members.length,
        warningCount,
        primaryTerminalIds: members.map((p) => p.terminalId),
      } satisfies OfficeZoneState;
    });

    const recentFailures = logs
      .filter((log) => log.status === 'failed')
      .slice(-2)
      .map((log, index) => ({
        id: `log-${index}-${log.session_id}`,
        zone: 'recovery' as OfficeZone,
        title: `${log.agent} failed`,
        subtitle: log.trigger || 'Execution failed',
        severity: 'error' as const,
        terminalIds: [log.terminal_id],
      }));

    const recentMessages = messages.slice(-3).map((msg, index) => ({
      id: `msg-${index}-${msg.id}`,
      zone: msg.type === 'warning' ? 'recovery' as OfficeZone : 'meeting' as OfficeZone,
      title: `${msg.from} -> ${msg.to}`,
      subtitle: msg.content.slice(0, 56),
      severity: msg.type === 'warning' ? 'warning' as const : 'info' as const,
      terminalIds: [],
    }));

    const recentMemory = memory
      .slice()
      .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
      .slice(0, 2)
      .map((note, index) => ({
        id: `memory-${index}-${note.id}`,
        zone: 'memory' as OfficeZone,
        title: note.title || note.key,
        subtitle: `${note.author} updated shared memory`,
        severity: 'success' as const,
        terminalIds: [],
      }));

    const activeTasks = presences
      .filter((p) => p.liveTask)
      .slice(0, 4)
      .map((presence, index) => ({
        id: `task-${index}-${presence.terminalId}`,
        zone: presence.zone,
        title: `${presence.agent.toUpperCase()} · T${presence.slotId + 1}`,
        subtitle: presence.liveTask.slice(0, 56),
        severity: presence.zone === 'recovery' ? 'warning' as const : 'info' as const,
        terminalIds: [presence.terminalId],
      }));

    const events: OfficeEventCard[] = [
      ...recentFailures,
      ...activeTasks,
      ...recentMessages,
      ...recentMemory,
    ].slice(0, 10);

    const selectedDefaultSlot = presences.find((p) => p.zone === 'desk')?.slotId ?? presences[0]?.slotId ?? 0;

    return {
      presences,
      zones,
      events,
      selectedDefaultSlot,
      summary: {
        activeAgents: presences.filter((p) => p.status === 'running' || p.status === 'started').length,
        blockedAgents: presences.filter((p) => p.zone === 'recovery').length,
        busyZones: zones.filter((z) => z.occupancy > 0 && z.id !== 'lounge' && z.id !== 'user').length,
      },
    };
  }, [agentTerminals, hiveHealth, logs, memory, messages]);
}
