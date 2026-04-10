/**
 * ------------------------------------------------------------------------
 * FILE: IsometricOffice.tsx
 * DESCRIPTION: 2.5D 아이소메트릭 메타버스 오피스.
 *              SVG 기반 True Isometric 좌표계 사용.
 *              대표실, 작업실, 회의실, 탕비실, 복도 구현.
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: CEO 전용 중역 세트(CeoDesk) 및 레드 카펫 적용
 * ------------------------------------------------------------------------
 */

import { useMemo } from 'react';
import type { OfficeAgentPresence, OfficeZoneState, OfficeEventCard } from '../../hooks/useOfficeState';
import type { AgentStats } from './OfficeApp';
import { IsoAgent, type AgentStatus, detectAgentType } from './IsoAgent';
import { FloorTile, isoToScreen, getZoneAt } from './IsoRoom';
import { IsoDesk, IsoPartition, IsoSofa, IsoTable, CeoDesk } from './IsoFurniture';
import './isometric.css';

interface SpeechBubble { deskId: number; text: string; createdAt: number; duration: number; }

interface IsometricOfficeProps {
  presences: OfficeAgentPresence[];
  zones: OfficeZoneState[];
  events: OfficeEventCard[];
  selectedDesk: number | null;
  onDeskClick: (id: number) => void;
  onZoneClick: (zone: string) => void;
  speechBubbles: SpeechBubble[];
  slotNames: string[];
  slotRoles: string[];
  agentStats?: AgentStats[];
  slotClis?: string[];
}

function toAgentStatus(status: string): AgentStatus {
  const s = status.toLowerCase();
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('meet') || s.includes('discuss')) return 'meeting';
  if (s.includes('work') || s.includes('run') || s.includes('busy') || s.includes('modif') || s.includes('analyz')) return 'working';
  return 'idle';
}

const GRID_SIZE = 16;

/* ── 가구 배치 정보 — 9개 책상 (3열×3행) ── */
const DESKS = [
  { col: 7, row: 1, deskId: 0 }, { col: 10, row: 1, deskId: 1 }, { col: 13, row: 1, deskId: 2 },
  { col: 7, row: 4, deskId: 3 }, { col: 10, row: 4, deskId: 4 }, { col: 13, row: 4, deskId: 5 },
  { col: 7, row: 7, deskId: 6 }, { col: 10, row: 7, deskId: 7 }, { col: 13, row: 7, deskId: 8 },
];

export default function IsometricOffice({
  presences,
  onDeskClick,
  speechBubbles,
  slotNames,
  slotRoles = [],
  agentStats = [],
  slotClis = [],
}: IsometricOfficeProps) {

  const agents = useMemo(() => {
    return presences.map((p, idx) => {
      const status = toAgentStatus(p.status);
      const name = slotNames[idx] || p.agent;
      const role = (slotRoles[idx] || '').toLowerCase();
      // CEO 감지: role이 'ceo'이거나 이름에 'ceo'/'대표' 포함
      const isCeo = role === 'ceo' || name.includes('대표') || name.toLowerCase().includes('ceo');
      const cli = (slotClis[idx] || p.agent || '').toLowerCase();
      // CLI 기반으로 에이전트 타입 감지 (이름에 claude/gemini가 없어도 CLI로 판별)
      const type = isCeo ? 'ceo' as const
        : (detectAgentType(cli) !== 'unknown' ? detectAgentType(cli) : detectAgentType(name)) || (p.agent as any);
      
      let targetCol = 2, targetRow = 2; // 기본적으로 대표님 방 근처

      if (isCeo) {
        targetCol = 2; targetRow = 2;
      } else if (status === 'working') {
        const d = DESKS[idx % DESKS.length];
        targetCol = d.col + 1; targetRow = d.row;
      } else if (status === 'meeting') {
        targetCol = 10 + (idx % 4); targetRow = 11 + Math.floor(idx / 4);
      } else {
        // idle — 각자 자기 책상 옆에서 대기 (겹치지 않게)
        const d = DESKS[idx % DESKS.length];
        targetCol = d.col + 2; targetRow = d.row + 1;
      }

      const screenPos = isoToScreen(targetCol, targetRow);
      // 에이전트 CLI 이름으로 stats 매칭 (claude, gemini, codex)
      const stats = agentStats.find(s => s.agent_id === cli);
      return { ...p, col: targetCol, row: targetRow, sx: screenPos.x, sy: screenPos.y, status, type, name, originalIdx: idx, stats };
    });
  }, [presences, slotNames, slotRoles, agentStats, slotClis]);

  return (
    <div className="iso-office-container">
      <svg width="100%" height="100%" viewBox="-400 -50 1200 900" preserveAspectRatio="xMidYMid meet" className="iso-svg">
        {/* 바닥 레이어 (카펫/타일) */}
        <g className="iso-layer-floor">
          {Array.from({ length: GRID_SIZE }).map((_, r) => (
            Array.from({ length: GRID_SIZE }).map((_, c) => (
              <FloorTile key={`tile-${c}-${r}`} col={c} row={r} zone={getZoneAt(c, r) || undefined} />
            ))
          ))}
        </g>

        {/* 오브젝트 레이어 (가구/캐릭터) */}
        <g className="iso-layer-objects">
          <IsoSofa col={1} row={5} />
          
          {/* 대표실 중역 세트 */}
          <CeoDesk col={2} row={2} />
          
          {/* 일반 직원 구역 책상들 */}
          {DESKS.map((d) => (
            <g key={`furniture-desk-${d.deskId}`} onClick={() => onDeskClick(d.deskId)} style={{ cursor: 'pointer' }}>
              <IsoPartition col={d.col} row={d.row} />
              <IsoDesk col={d.col} row={d.row} />
              {/* IsoMonitor는 IsoDesk에 통합됨 */}
            </g>
          ))}

          {/* 회의실 테이블 */}
          <IsoTable col={12} row={12} />

          {/* 에이전트 캐릭터들 (Y좌표 기준 정렬하여 렌더링 - Z-Sorting) */}
          {agents.sort((a, b) => (a.col + a.row) - (b.col + b.row)).map((agent) => (
            <g key={agent.terminalId} style={{ transition: 'all 0.8s ease-in-out' }}>
              <IsoAgent
                agentType={agent.type}
                name={agent.name}
                status={agent.status}
                x={agent.sx - 20}
                y={agent.sy - 45}
                level={agent.stats?.level}
                totalXp={agent.stats?.total_xp}
                taskCount={agent.stats?.task_count}
              />
              {/* 말풍선 */}
              {speechBubbles.find(b => b.deskId === agent.originalIdx) && (
                <g transform={`translate(${agent.sx}, ${agent.sy - 85})`}>
                  <rect x="-60" y="-30" width="120" height="34" rx="10" fill="white" fillOpacity="0.95" stroke="#ddd" strokeWidth="1.5" />
                  <text x="0" y="-12" textAnchor="middle" fontSize="10" fontWeight="bold" fill="#333">
                    {speechBubbles.find(b => b.deskId === agent.originalIdx)?.text.substring(0, 18)}
                  </text>
                  <path d="M-6,0 L0,8 L6,0 Z" fill="white" fillOpacity="0.95" stroke="#ddd" strokeWidth="1.5" />
                </g>
              )}
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
