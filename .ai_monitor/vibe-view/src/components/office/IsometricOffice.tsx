/**
 * ------------------------------------------------------------------------
 * FILE: IsometricOffice.tsx
 * DESCRIPTION: 2.5D 아이소메트릭 메타버스 오피스.
 *              SVG 기반 True Isometric 좌표계 사용.
 *              대표실, 작업실, 회의실, 탕비실, 복도 구현.
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: v5 — 컴포넌트 호출 규격 수정 (Build Fix)
 * ------------------------------------------------------------------------
 */

import { useMemo } from 'react';
import type { OfficeAgentPresence, OfficeZoneState, OfficeEventCard } from '../../hooks/useOfficeState';
import { IsoAgent, type AgentStatus, detectAgentType } from './IsoAgent';
import { FloorTile, isoToScreen, getZoneAt } from './IsoRoom';
import { IsoDesk, IsoMonitor, IsoPartition, IsoSofa, IsoTable } from './IsoFurniture';
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
}

function toAgentStatus(status: string): AgentStatus {
  const s = status.toLowerCase();
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('meet') || s.includes('discuss')) return 'meeting';
  if (s.includes('work') || s.includes('run') || s.includes('busy') || s.includes('modif') || s.includes('analyz')) return 'working';
  return 'idle';
}

const GRID_SIZE = 16;

/* ── 가구 배치 정보 ── */
const DESKS = [
  { col: 8, row: 1, deskId: 0 }, { col: 11, row: 1, deskId: 1 },
  { col: 8, row: 4, deskId: 2 }, { col: 11, row: 4, deskId: 3 },
  { col: 8, row: 7, deskId: 4 }, { col: 11, row: 7, deskId: 5 },
];

export default function IsometricOffice({
  presences,
  onDeskClick,
  speechBubbles,
  slotNames,
}: IsometricOfficeProps) {

  const agents = useMemo(() => {
    return presences.map((p, idx) => {
      const status = toAgentStatus(p.status);
      const name = slotNames[idx] || p.agent;
      const type = detectAgentType(name) || (p.agent as any);
      
      let targetCol = 2, targetRow = 12;

      if (type === 'ceo') {
        targetCol = 2; targetRow = 2;
      } else if (status === 'working') {
        const d = DESKS[idx % DESKS.length];
        targetCol = d.col; targetRow = d.row;
      } else if (status === 'meeting') {
        targetCol = 10 + (idx % 4); targetRow = 11 + Math.floor(idx / 4);
      }

      const screenPos = isoToScreen(targetCol, targetRow);
      return { ...p, col: targetCol, row: targetRow, sx: screenPos.x, sy: screenPos.y, status, type, name, originalIdx: idx };
    });
  }, [presences, slotNames]);

  return (
    <div className="iso-office-container">
      <svg width="100%" height="100%" viewBox="-400 -50 1200 900" preserveAspectRatio="xMidYMid meet" className="iso-svg">
        <g className="iso-layer-floor">
          {Array.from({ length: GRID_SIZE }).map((_, r) => (
            Array.from({ length: GRID_SIZE }).map((_, c) => (
              <FloorTile key={`tile-${c}-${r}`} col={c} row={r} zone={getZoneAt(c, r) || undefined} />
            ))
          ))}
        </g>

        <g className="iso-layer-objects">
          <IsoSofa col={1} row={1} />
          
          {DESKS.map((d) => (
            <g key={`furniture-desk-${d.deskId}`} onClick={() => onDeskClick(d.deskId)} style={{ cursor: 'pointer' }}>
              <IsoPartition col={d.col} row={d.row} />
              <IsoDesk col={d.col} row={d.row} />
              <IsoMonitor col={d.col} row={d.row} />
            </g>
          ))}

          <IsoTable col={12} row={12} />

          {agents.sort((a, b) => (a.col + a.row) - (b.col + b.row)).map((agent) => (
            <g key={agent.terminalId} style={{ transition: 'all 0.8s ease-in-out' }}>
              <IsoAgent
                agentType={agent.type}
                name={agent.name}
                status={agent.status}
                x={agent.sx - 20}
                y={agent.sy - 45}
              />
              {speechBubbles.find(b => b.deskId === agent.originalIdx) && (
                <g transform={`translate(${agent.sx}, ${agent.sy - 75})`}>
                  <rect x="-60" y="-30" width="120" height="30" rx="15" fill="white" fillOpacity="0.9" stroke="#ddd" strokeWidth="1" />
                  <text x="0" y="-12" textAnchor="middle" fontSize="10" fontWeight="bold" fill="#333">
                    {speechBubbles.find(b => b.deskId === agent.originalIdx)?.text.substring(0, 15)}...
                  </text>
                  <path d="M-5,0 L0,5 L5,0 Z" fill="white" fillOpacity="0.9" stroke="#ddd" strokeWidth="1" />
                </g>
              )}
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
