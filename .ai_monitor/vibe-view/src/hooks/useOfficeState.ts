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

// 동적 존: 부서 ID가 곧 존. 공용 존(meeting, user, recovery)만 예약.
export type OfficeZone = string;

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

export interface ProfileSlotInfo {
  name: string;
  cli: string;
  model: string;
}

export interface DepartmentInfo {
  id: string;
  name: string;
  color: string;
  agentCount: number;
}

interface UseOfficeStateArgs {
  agentTerminals: Record<string, any>;
  messages: AgentMessage[];
  memory: MemoryEntry[];
  logs: LogRecord[];
  hiveHealth: any;
  profileSlots?: ProfileSlotInfo[];
  /** 부서 목록 — 동적 존 생성용 */
  departments?: DepartmentInfo[];
}

// 공용 존 (항상 존재)
const COMMON_ZONES: Record<string, string> = {
  meeting: '회의실',
  user: '대표실',
  recovery: '복구',
};

function deriveZone(data: any, hiveHealth: any, deptId?: string): OfficeZone {
  if (!data) return deptId || 'desk';

  const status = String(data?.status || 'idle').toLowerCase();
  const task = String(data?.live_task || '').toLowerCase();

  // 에러 → 복구
  if (status.includes('error') || status.includes('failed') || task.includes('hang')) {
    return 'recovery';
  }
  if (hiveHealth?.status === 'healing' && status !== 'idle') {
    return 'recovery';
  }
  // 회의 중
  if (task.includes('debate') || task.includes('meeting') || task.includes('discussion')) {
    return 'meeting';
  }
  // 기본: 자기 부서에 있음
  return deptId || 'desk';
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
  profileSlots,
  departments: deptInfos,
}: UseOfficeStateArgs) {
  return useMemo(() => {
    let presences: OfficeAgentPresence[];

    if (profileSlots && profileSlots.length > 0 && deptInfos && deptInfos.length > 0) {
      // 오피스 모드: 부서 기반 — 클래식과 완전 분리
      presences = [];
      let flatIdx = 0;
      for (const dept of deptInfos) {
        for (let i = 0; i < dept.agentCount; i++) {
          const slot = profileSlots[flatIdx];
          if (!slot) { flatIdx++; continue; }
          const agent = slot.cli.toLowerCase();
          const zone = deriveZone(null, hiveHealth, dept.id);

          presences.push({
            terminalId: `office-${flatIdx}`,
            slotId: flatIdx,
            agent,
            status: 'idle',
            pipelineStage: 'idle',
            liveTask: '',
            zone,
            anchorId: `${dept.id}-${i}`,
            badges: [],
            colorKey: ['claude', 'gemini', 'codex'].includes(agent) ? agent : 'unknown',
          });
          flatIdx++;
        }
      }
    } else {
      // 클래식 모드 호환
      presences = Object.entries(agentTerminals)
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
    }

    // 동적 존 목록: 부서 + 공용 존
    const zoneMap = new Map<string, string>();
    if (deptInfos && deptInfos.length > 0) {
      for (const dept of deptInfos) zoneMap.set(dept.id, dept.name);
    } else {
      zoneMap.set('desk', '데스크');
    }
    for (const [id, label] of Object.entries(COMMON_ZONES)) zoneMap.set(id, label);

    const zones: OfficeZoneState[] = Array.from(zoneMap.entries()).map(([id, label]) => {
      const members = presences.filter(p => p.zone === id);
      return {
        id,
        label,
        occupancy: members.length,
        warningCount: members.filter(p => p.status?.includes('error') || p.status?.includes('failed')).length,
        primaryTerminalIds: members.map(p => p.terminalId),
      };
    });

    const recentFailures = logs
      .filter((log) => log.status === 'failed')
      .slice(-2)
      .map((log, index) => ({
        id: `log-${index}-${log.session_id}`,
        zone: 'recovery' as OfficeZone,
        title: `${log.agent} 실패`,
        subtitle: log.trigger || '실행 실패',
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
        subtitle: `${note.author} 공유 메모리 업데이트`,
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
  }, [agentTerminals, hiveHealth, logs, memory, messages, profileSlots, deptInfos]);
}
