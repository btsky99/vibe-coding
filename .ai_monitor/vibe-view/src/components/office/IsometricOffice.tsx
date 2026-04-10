/**
 * ------------------------------------------------------------------------
 * FILE: IsometricOffice.tsx
 * DESCRIPTION: 아이소메트릭 오피스 — 타일맵 기반 진짜 아이소메트릭 렌더러.
 *              벽면 / 복도 / 방 구분, SVG polygon 좌표 계산으로 구현.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: v2 — 타일맵 + SVG 좌표 기반으로 전면 재작성
 * ------------------------------------------------------------------------
 */

import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import type { OfficeAgentPresence, OfficeZoneState, OfficeEventCard } from '../../hooks/useOfficeState';
import type { AgentStatus } from './IsoAgent';
import {
  TW, TH, WALL_H,
  isoToScreen,
  FloorTile, CorridorTile, WallTile, PartitionTile,
  DeskObject, MonitorObject, SofaObject, TableObject, PotObject,
} from './IsoRoom';
import IsoAgent, { detectAgentType } from './IsoAgent';
import './isometric.css';

/* ── props ── */
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

/* ── 타일 타입 정의 ──
   0=빈공간  1=바닥(방)  2=복도  3=벽(외벽)  4=파티션
*/
type Cell = 0 | 1 | 2 | 3 | 4;

/* ── 오피스 맵 레이아웃 (24×20 그리드) ──
   CEO실(좌상), 개발부서실(우상+하), 회의실(하좌)
   복도가 방들을 연결
*/
const MAP_COLS = 24;
const MAP_ROWS = 20;

function buildMap(deptCount: number): Cell[][] {
  const M = Array.from({ length: MAP_ROWS }, () => Array(MAP_COLS).fill(0) as Cell[]);

  /* ── 외벽 그리기 헬퍼 ── */
  const wall = (r: number, c: number) => { M[r][c] = 3; };
  const floor = (r: number, c: number) => { M[r][c] = 1; };
  const corridor = (r: number, c: number) => { M[r][c] = 2; };
  const partition = (r: number, c: number) => { M[r][c] = 4; };

  /* ── CEO실 (col 1~7, row 1~8) ── */
  for (let r = 1; r <= 8; r++) for (let c = 1; c <= 7; c++) {
    if (r === 1 || r === 8 || c === 1 || c === 7) wall(r, c);
    else floor(r, c);
  }

  /* ── 복도 (col 8, row 1~18 | row 9, col 1~23) ── */
  for (let r = 1; r <= 18; r++) corridor(r, 8);
  for (let c = 1; c <= 23; c++) corridor(9, c);

  /* ── 개발부서실 A (col 9~15, row 1~8) ── */
  for (let r = 1; r <= 8; r++) for (let c = 9; c <= 15; c++) {
    if (r === 1 || r === 8 || c === 9 || c === 15) wall(r, c);
    else floor(r, c);
  }

  /* ── 파티션 (개발부서 내부) ── */
  for (let r = 3; r <= 6; r++) partition(r, 12);

  /* ── 개발부서실 B (col 16~23, row 1~8) ── */
  if (deptCount >= 2) {
    for (let r = 1; r <= 8; r++) for (let c = 16; c <= 23; c++) {
      if (r === 1 || r === 8 || c === 16 || c === 23) wall(r, c);
      else floor(r, c);
    }
    for (let r = 3; r <= 6; r++) partition(r, 19);
  }

  /* ── 회의실 (col 1~7, row 10~18) ── */
  for (let r = 10; r <= 18; r++) for (let c = 1; c <= 7; c++) {
    if (r === 10 || r === 18 || c === 1 || c === 7) wall(r, c);
    else floor(r, c);
  }

  /* ── 추가 개발 공간 (col 9~23, row 10~18) ── */
  for (let r = 10; r <= 18; r++) for (let c = 9; c <= 23; c++) {
    if (r === 10 || r === 18 || c === 9 || c === 23) wall(r, c);
    else floor(r, c);
  }
  /* 파티션 (추가 공간) */
  for (let r = 12; r <= 16; r++) partition(r, 15);

  return M;
}

/* ── 렌더링 우선순위 (row+col 합산 기준 painter's algorithm) ── */

/* ── 에이전트 상태 변환 ── */
function toAgentStatus(status: string): AgentStatus {
  const s = status.toLowerCase();
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('meet') || s.includes('discuss')) return 'meeting';
  if (s.includes('work') || s.includes('run') || s.includes('busy') || s.includes('modif') || s.includes('analyz')) return 'working';
  return 'idle';
}

/* ── 방 레이블 위치 ── */
const ROOM_LABELS = [
  { label: 'CEO 집무실',  col: 4,  row: 4  },
  { label: '개발부서 A',  col: 12, row: 4  },
  { label: '개발부서 B',  col: 19, row: 4  },
  { label: '회의실',      col: 4,  row: 14 },
  { label: '작업 공간',   col: 16, row: 14 },
];

export default function IsometricOffice({
  presences,
  zones: _zones,
  events: _events,
  selectedDesk: _selectedDesk,
  onDeskClick: _onDeskClick,
  onZoneClick: _onZoneClick,
  speechBubbles: _speechBubbles,
  slotNames,
  slotRoles,
}: IsometricOfficeProps) {
  /* ── 패닝 / 줌 ── */
  const [transform, setTransform] = useState({ x: 120, y: 40, scale: 0.85 });
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });
  const sceneRef = useRef<HTMLDivElement>(null);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    lastPos.current = { x: e.clientX, y: e.clientY };
  }, []);
  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return;
    const dx = e.clientX - lastPos.current.x;
    const dy = e.clientY - lastPos.current.y;
    lastPos.current = { x: e.clientX, y: e.clientY };
    setTransform(t => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, []);
  const onMouseUp = useCallback(() => { dragging.current = false; }, []);

  const onWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    setTransform(t => ({
      ...t,
      scale: Math.max(0.4, Math.min(2.5, t.scale * (e.deltaY > 0 ? 0.92 : 1.08))),
    }));
  }, []);

  useEffect(() => {
    const el = sceneRef.current;
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  /* ── 데이터 파생 ── */
  const ceoIdx = slotRoles.findIndex(r => r.toLowerCase() === 'ceo');
  const ceoName = ceoIdx >= 0 ? (slotNames[ceoIdx] ?? 'CEO') : 'CEO';
  const ceoPresence = presences.find(p => p.zone === 'user' || slotRoles[p.slotId]?.toLowerCase() === 'ceo');

  const meetingAgents = presences.filter(p => p.zone === 'meeting');
  const deskAgents = presences.filter(p => p.zone !== 'user' && p.zone !== 'meeting' && p.zone !== 'recovery');

  /* ── 타일맵 생성 ── */
  const deptCount = useMemo(() => {
    const zones = new Set(presences.map(p => p.zone).filter(z => z !== 'user' && z !== 'meeting' && z !== 'recovery'));
    return Math.max(1, zones.size);
  }, [presences]);

  const map = useMemo(() => buildMap(deptCount), [deptCount]);

  /* ── SVG 전체 크기 계산 ── */
  const svgW = (MAP_COLS + MAP_ROWS) * (TW / 2) + TW;
  const svgH = (MAP_COLS + MAP_ROWS) * (TH / 2) + WALL_H + TH * 2;

  /* ── 오프셋: SVG 내 시작점 ── */
  const originX = MAP_ROWS * (TW / 2);
  const originY = WALL_H + TH;

  /* ── 에이전트 배치 좌표 ── */
  /* CEO실 내부 */
  const CEO_DESK_COL = 5; const CEO_DESK_ROW = 5;
  /* 개발부서 책상들 (그리드) */
  const DESK_POSITIONS_A = [
    { col: 11, row: 3 }, { col: 13, row: 3 },
    { col: 11, row: 5 }, { col: 13, row: 5 },
    { col: 11, row: 7 }, { col: 13, row: 7 },
  ];
  const DESK_POSITIONS_B = [
    { col: 17, row: 3 }, { col: 20, row: 3 },
    { col: 17, row: 5 }, { col: 20, row: 5 },
    { col: 17, row: 7 }, { col: 20, row: 7 },
  ];
  /* 회의실 테이블 주변 */
  const MEETING_POSITIONS = [
    { col: 3, row: 12 }, { col: 5, row: 12 },
    { col: 3, row: 15 }, { col: 5, row: 15 },
  ];
  /* 추가 작업 공간 */
  const DESK_POSITIONS_C = [
    { col: 11, row: 12 }, { col: 13, row: 12 },
    { col: 17, row: 12 }, { col: 20, row: 12 },
    { col: 11, row: 15 }, { col: 13, row: 15 },
    { col: 17, row: 15 }, { col: 20, row: 15 },
  ];

  /* 에이전트를 책상 포지션에 배정 */
  const allDeskPositions = [...DESK_POSITIONS_A, ...DESK_POSITIONS_B, ...DESK_POSITIONS_C];

  /* 화면 좌표 변환 (originX, originY 오프셋 포함) */
  const toSVG = (col: number, row: number) => {
    const s = isoToScreen(col, row);
    return { x: s.x + originX, y: s.y + originY };
  };

  return (
    <div
      ref={sceneRef}
      className="iso-scene"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <div
        style={{
          position: 'absolute',
          transformOrigin: '0 0',
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
        }}
      >
        <svg
          width={svgW}
          height={svgH}
          viewBox={`0 0 ${svgW} ${svgH}`}
          style={{ display: 'block', overflow: 'visible' }}
        >
          <g transform={`translate(${originX}, ${originY})`}>
            {/* ── 1pass: 바닥 + 복도 타일 (painter's algorithm: row+col 오름차순) ── */}
            {Array.from({ length: MAP_ROWS }, (_, r) =>
              Array.from({ length: MAP_COLS }, (_, c) => {
                const cell = map[r][c];
                const key = `f-${r}-${c}`;
                if (cell === 1) {
                  const isLight = (r + c) % 2 === 0;
                  return <FloorTile key={key} col={c} row={r} color={isLight ? '#1a2435' : '#162030'} />;
                }
                if (cell === 2) return <CorridorTile key={key} col={c} row={r} />;
                if (cell === 0) return null;
                return null;
              })
            )}

            {/* ── 2pass: 가구 오브젝트 (책상+모니터) ── */}
            {/* CEO 책상 + 소파 */}
            <DeskObject col={CEO_DESK_COL} row={CEO_DESK_ROW} />
            <MonitorObject col={CEO_DESK_COL} row={CEO_DESK_ROW} />
            <SofaObject col={3} row={3} />
            <PotObject col={6} row={2} />
            <PotObject col={2} row={7} />

            {/* 개발부서 A 책상들 */}
            {DESK_POSITIONS_A.map((p, i) => (
              <g key={`da-${i}`}>
                <DeskObject col={p.col} row={p.row} />
                <MonitorObject col={p.col} row={p.row} />
              </g>
            ))}

            {/* 개발부서 B 책상들 */}
            {DESK_POSITIONS_B.map((p, i) => (
              <g key={`db-${i}`}>
                <DeskObject col={p.col} row={p.row} />
                <MonitorObject col={p.col} row={p.row} />
              </g>
            ))}

            {/* 회의실 테이블 */}
            <TableObject col={4} row={13} />

            {/* 추가 공간 책상들 */}
            {DESK_POSITIONS_C.map((p, i) => (
              <g key={`dc-${i}`}>
                <DeskObject col={p.col} row={p.row} />
                <MonitorObject col={p.col} row={p.row} />
              </g>
            ))}

            {/* ── 3pass: 벽 + 파티션 (타일 위에 솟아오름) ── */}
            {Array.from({ length: MAP_ROWS }, (_, r) =>
              Array.from({ length: MAP_COLS }, (_, c) => {
                const cell = map[r][c];
                const key = `w-${r}-${c}`;
                if (cell === 3) return <WallTile key={key} col={c} row={r} />;
                if (cell === 4) return <PartitionTile key={key} col={c} row={r} />;
                return null;
              })
            )}

            {/* ── 4pass: 에이전트 캐릭터 (SVG foreignObject로 HTML 캐릭터 오버레이) ── */}
            {/* CEO */}
            {(() => {
              const pos = toSVG(CEO_DESK_COL, CEO_DESK_ROW - 1);
              return (
                <foreignObject key="ceo" x={pos.x - 20} y={pos.y - 55} width={40} height={70} overflow="visible">
                  <IsoAgent
                    agentType="ceo"
                    name={ceoName}
                    status={ceoPresence ? toAgentStatus(ceoPresence.status) : 'idle'}
                    onClick={() => {}}
                  />
                </foreignObject>
              );
            })()}

            {/* 책상 에이전트들 */}
            {deskAgents.slice(0, allDeskPositions.length).map((p, i) => {
              const deskPos = allDeskPositions[i];
              if (!deskPos) return null;
              const pos = toSVG(deskPos.col, deskPos.row - 1);
              return (
                <foreignObject key={p.terminalId} x={pos.x - 20} y={pos.y - 55} width={40} height={70} overflow="visible">
                  <IsoAgent
                    agentType={detectAgentType(p.agent || p.terminalId)}
                    name={p.agent || p.terminalId}
                    status={toAgentStatus(p.status)}
                    onClick={() => {}}
                  />
                </foreignObject>
              );
            })}

            {/* 회의실 에이전트들 */}
            {meetingAgents.slice(0, MEETING_POSITIONS.length).map((p, i) => {
              const mPos = MEETING_POSITIONS[i];
              if (!mPos) return null;
              const pos = toSVG(mPos.col, mPos.row - 1);
              return (
                <foreignObject key={`m-${p.terminalId}`} x={pos.x - 20} y={pos.y - 55} width={40} height={70} overflow="visible">
                  <IsoAgent
                    agentType={detectAgentType(p.agent || p.terminalId)}
                    name={p.agent || p.terminalId}
                    status="meeting"
                    onClick={() => {}}
                  />
                </foreignObject>
              );
            })}

            {/* ── 방 레이블 ── */}
            {ROOM_LABELS.map(({ label, col, row }) => {
              const pos = isoToScreen(col, row);
              return (
                <text
                  key={label}
                  x={pos.x}
                  y={pos.y - WALL_H - 8}
                  textAnchor="middle"
                  fontSize="9"
                  fontWeight="700"
                  letterSpacing="1.5"
                  fill="rgba(255,255,255,0.25)"
                  fontFamily="monospace"
                  style={{ textTransform: 'uppercase', pointerEvents: 'none' }}
                >
                  {label}
                </text>
              );
            })}
          </g>
        </svg>
      </div>

      {/* ── HUD: 줌 컨트롤 ── */}
      <div style={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 4, zIndex: 50 }}>
        {[
          { label: '+', fn: () => setTransform(t => ({ ...t, scale: Math.min(2.5, t.scale * 1.2) })) },
          { label: '−', fn: () => setTransform(t => ({ ...t, scale: Math.max(0.4, t.scale * 0.8) })) },
          { label: '↺', fn: () => setTransform({ x: 120, y: 40, scale: 0.85 }) },
        ].map(({ label, fn }) => (
          <button key={label} onClick={fn} style={btnStyle}>{label}</button>
        ))}
      </div>

      {/* ── HUD: 범례 ── */}
      <div style={{
        position: 'absolute', top: 12, left: 12, zIndex: 50,
        background: 'rgba(6,10,15,0.8)', border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 8, padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 4,
      }}>
        {[
          { label: '대기', color: '#3b82f6' },
          { label: '작업 중', color: '#22c55e' },
          { label: '회의', color: '#f97316' },
          { label: '오류', color: '#ef4444' },
        ].map(({ label, color }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}` }} />
            {label}
          </div>
        ))}
      </div>

      {/* ── HUD: 에이전트 수 ── */}
      <div style={{ position: 'absolute', top: 12, right: 16, zIndex: 50, fontSize: 11, color: 'rgba(255,255,255,0.3)' }}>
        에이전트 {presences.length}명 재직 중
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  width: 28, height: 28, borderRadius: 6,
  background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
  color: 'rgba(255,255,255,0.7)', fontSize: 16, cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: '1',
};
