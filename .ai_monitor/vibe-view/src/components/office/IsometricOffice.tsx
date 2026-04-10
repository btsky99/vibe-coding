/**
 * ------------------------------------------------------------------------
 * FILE: IsometricOffice.tsx
 * DESCRIPTION: 2D 탑다운 오피스 맵. 평면도 스타일.
 *              방 / 복도 / 책상 / 에이전트 캐릭터 (SVG 플랫 2D).
 * REVISION HISTORY:
 * - 2026-04-10 Claude: v3 — 아이소메트릭 포기, 2D 탑다운 평면도로 전환
 * ------------------------------------------------------------------------
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import type { OfficeAgentPresence, OfficeZoneState, OfficeEventCard } from '../../hooks/useOfficeState';
import type { AgentStatus } from './IsoAgent';
import { detectAgentType } from './IsoAgent';
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

/* ── 에이전트 색상 ── */
const AGENT_COLORS: Record<string, { bg: string; border: string; label: string }> = {
  claude:  { bg: '#2d1f4a', border: '#a78bfa', label: 'C' },
  gemini:  { bg: '#0f2e22', border: '#34d399', label: 'G' },
  codex:   { bg: '#0f2535', border: '#22d3ee', label: '</>' },
  ceo:     { bg: '#1e3a5f', border: '#f59e0b', label: '★' },
  unknown: { bg: '#1a2435', border: '#64748b', label: '?' },
};

const STATUS_COLORS: Record<string, string> = {
  idle:    '#3b82f6',
  working: '#22c55e',
  meeting: '#f97316',
  error:   '#ef4444',
};

function toAgentStatus(status: string): AgentStatus {
  const s = status.toLowerCase();
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('meet') || s.includes('discuss')) return 'meeting';
  if (s.includes('work') || s.includes('run') || s.includes('busy') || s.includes('modif') || s.includes('analyz')) return 'working';
  return 'idle';
}

/* ── 오피스 레이아웃 상수 (px) ── */
const W = 900;   /* 전체 SVG 너비 */
const H = 680;   /* 전체 SVG 높이 */
const WALL = 10; /* 벽 두께 */
const CORRIDOR = 36; /* 복도 너비 */

/* 방 좌표 정의 */
const ROOMS = {
  ceo: {
    x: WALL, y: WALL,
    w: 200, h: 260,
    label: 'CEO 집무실',
    color: '#0d1a2a',
    border: '#1e3a5f',
  },
  corridor_v: {
    x: WALL + 200, y: WALL,
    w: CORRIDOR, h: H - WALL * 2,
    label: '',
    color: '#0a1520',
    border: 'none',
  },
  dept_a: {
    x: WALL + 200 + CORRIDOR, y: WALL,
    w: 240, h: 260,
    label: '개발부서 A',
    color: '#0e1d2e',
    border: '#1e3a5f',
  },
  corridor_h2: {
    x: WALL + 200 + CORRIDOR, y: WALL + 260,
    w: W - (WALL + 200 + CORRIDOR) - WALL, h: CORRIDOR,
    label: '',
    color: '#0a1520',
    border: 'none',
  },
  dept_b: {
    x: WALL + 200 + CORRIDOR + 240 + WALL, y: WALL,
    w: W - (WALL + 200 + CORRIDOR + 240 + WALL) - WALL, h: 260,
    label: '개발부서 B',
    color: '#0e1d2e',
    border: '#1e3a5f',
  },
  corridor_h: {
    x: WALL, y: WALL + 260,
    w: 200, h: CORRIDOR,
    label: '',
    color: '#0a1520',
    border: 'none',
  },
  meeting: {
    x: WALL, y: WALL + 260 + CORRIDOR,
    w: 200, h: H - (WALL + 260 + CORRIDOR) - WALL,
    label: '회의실',
    color: '#0c1828',
    border: '#1e3a5f',
  },
  workspace: {
    x: WALL + 200 + CORRIDOR, y: WALL + 260 + CORRIDOR,
    w: W - (WALL + 200 + CORRIDOR) - WALL, h: H - (WALL + 260 + CORRIDOR) - WALL,
    label: '작업 공간',
    color: '#0e1d2e',
    border: '#1e3a5f',
  },
};

/* ── 책상 배치 ── */
const DESKS = {
  ceo: [
    { x: 80, y: 80, w: 90, h: 50, monitor: true },
  ],
  dept_a: [
    { x: 30, y: 50,  w: 70, h: 40, monitor: true },
    { x: 140, y: 50,  w: 70, h: 40, monitor: true },
    { x: 30, y: 120, w: 70, h: 40, monitor: true },
    { x: 140, y: 120, w: 70, h: 40, monitor: true },
    { x: 30, y: 190, w: 70, h: 40, monitor: true },
    { x: 140, y: 190, w: 70, h: 40, monitor: true },
  ],
  dept_b: [
    { x: 20, y: 50,  w: 70, h: 40, monitor: true },
    { x: 110, y: 50,  w: 70, h: 40, monitor: true },
    { x: 20, y: 120, w: 70, h: 40, monitor: true },
    { x: 110, y: 120, w: 70, h: 40, monitor: true },
    { x: 20, y: 190, w: 70, h: 40, monitor: true },
    { x: 110, y: 190, w: 70, h: 40, monitor: true },
  ],
  workspace: [
    { x: 30,  y: 40,  w: 70, h: 40, monitor: true },
    { x: 140, y: 40,  w: 70, h: 40, monitor: true },
    { x: 260, y: 40,  w: 70, h: 40, monitor: true },
    { x: 370, y: 40,  w: 70, h: 40, monitor: true },
    { x: 30,  y: 130, w: 70, h: 40, monitor: true },
    { x: 140, y: 130, w: 70, h: 40, monitor: true },
    { x: 260, y: 130, w: 70, h: 40, monitor: true },
    { x: 370, y: 130, w: 70, h: 40, monitor: true },
  ],
};

/* ── 에이전트 위치 (방 내부 기준 상대좌표) ── */
const AGENT_SPOTS = {
  ceo:       [{ x: 115, y: 115 }],
  dept_a:    [
    { x: 65,  y: 72  }, { x: 175, y: 72  },
    { x: 65,  y: 142 }, { x: 175, y: 142 },
    { x: 65,  y: 212 }, { x: 175, y: 212 },
  ],
  dept_b:    [
    { x: 55,  y: 72  }, { x: 145, y: 72  },
    { x: 55,  y: 142 }, { x: 145, y: 142 },
    { x: 55,  y: 212 }, { x: 145, y: 212 },
  ],
  workspace: [
    { x: 65,  y: 62  }, { x: 175, y: 62  }, { x: 295, y: 62  }, { x: 405, y: 62  },
    { x: 65,  y: 152 }, { x: 175, y: 152 }, { x: 295, y: 152 }, { x: 405, y: 152 },
  ],
  meeting:   [
    { x: 50,  y: 80  }, { x: 140, y: 80  },
    { x: 50,  y: 150 }, { x: 140, y: 150 },
    { x: 100, y: 220 },
  ],
};

/* ── 단일 에이전트 동그라미 ── */
function AgentDot({
  cx, cy, name, agentType, status, selected,
  onClick,
}: {
  cx: number; cy: number; name: string;
  agentType: string; status: AgentStatus;
  selected?: boolean; onClick?: () => void;
}) {
  const cfg = AGENT_COLORS[agentType] ?? AGENT_COLORS.unknown;
  const ledColor = STATUS_COLORS[status] ?? STATUS_COLORS.idle;
  const R = 16;

  return (
    <g onClick={onClick} style={{ cursor: 'pointer' }}>
      {/* 그림자 */}
      <ellipse cx={cx} cy={cy + R + 2} rx={R} ry={4} fill="rgba(0,0,0,0.3)" />

      {/* 선택 링 */}
      {selected && (
        <circle cx={cx} cy={cy} r={R + 5} fill="none" stroke="#fff" strokeWidth="2" opacity="0.4" strokeDasharray="4 3" />
      )}

      {/* 본체 원 */}
      <circle cx={cx} cy={cy} r={R} fill={cfg.bg} stroke={cfg.border} strokeWidth="2" />

      {/* 라벨 */}
      <text
        x={cx} y={cy + 4}
        textAnchor="middle"
        fontSize={agentType === 'codex' ? "6" : "9"}
        fontWeight="700"
        fill={cfg.border}
        fontFamily="monospace"
      >
        {cfg.label}
      </text>

      {/* LED 상태 점 */}
      <circle cx={cx + R - 4} cy={cy - R + 4} r={4} fill={ledColor} stroke="#060a0f" strokeWidth="1.5">
        <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
      </circle>

      {/* 이름 태그 (호버) */}
      <title>{name} [{status}]</title>
    </g>
  );
}

/* ── 책상 SVG ── */
function Desk({ x, y, w, h, monitor }: { x: number; y: number; w: number; h: number; monitor?: boolean }) {
  return (
    <g>
      {/* 책상 */}
      <rect x={x} y={y} width={w} height={h} rx={3} fill="#1e2e40" stroke="#2a4060" strokeWidth="1" />
      {/* 책상 상판 하이라이트 */}
      <rect x={x + 2} y={y + 2} width={w - 4} height={6} rx={1} fill="rgba(255,255,255,0.04)" />
      {/* 모니터 */}
      {monitor && (
        <g>
          <rect x={x + w * 0.2} y={y + 4} width={w * 0.6} height={h * 0.55} rx={2} fill="#0a1a2e" stroke="#1e3a5f" strokeWidth="1" />
          {/* 화면 */}
          <rect x={x + w * 0.22} y={y + 6} width={w * 0.56} height={h * 0.42} rx={1} fill="#040d1a" />
          {/* 코드 라인 */}
          <line x1={x + w * 0.25} y1={y + 10} x2={x + w * 0.55} y2={y + 10} stroke="#22d3ee" strokeWidth="1" opacity="0.6" />
          <line x1={x + w * 0.25} y1={y + 14} x2={x + w * 0.68} y2={y + 14} stroke="#a78bfa" strokeWidth="1" opacity="0.5" />
          <line x1={x + w * 0.25} y1={y + 18} x2={x + w * 0.48} y2={y + 18} stroke="#34d399" strokeWidth="1" opacity="0.6" />
          {/* 스탠드 */}
          <line x1={x + w * 0.5} y1={y + h * 0.55 + 4} x2={x + w * 0.5} y2={y + h - 4} stroke="#2a4060" strokeWidth="3" />
          <rect x={x + w * 0.35} y={y + h - 6} width={w * 0.3} height={4} rx={1} fill="#2a4060" />
        </g>
      )}
    </g>
  );
}

/* ── 소파 ── */
function Sofa({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <rect x={x} y={y} width={120} height={50} rx={8} fill="#1e3a5f" stroke="#2952a0" strokeWidth="1.5" />
      <rect x={x + 5} y={y + 5} width={110} height={40} rx={5} fill="#253f6a" />
      <rect x={x + 5} y={y} width={15} height={50} rx={4} fill="#2952a0" />
      <rect x={x + 100} y={y} width={15} height={50} rx={4} fill="#2952a0" />
    </g>
  );
}

/* ── 회의 테이블 ── */
function MeetingTable({ cx, cy }: { cx: number; cy: number }) {
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx={60} ry={35} fill="#1e2e1a" stroke="#2d4a2a" strokeWidth="1.5" />
      <ellipse cx={cx} cy={cy} rx={52} ry={27} fill="#253825" />
      <ellipse cx={cx - 10} cy={cy - 8} rx={20} ry={8} fill="rgba(255,255,255,0.03)" />
    </g>
  );
}

/* ── 화분 ── */
function Plant({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <ellipse cx={x} cy={y + 16} rx={10} ry={5} fill="#92400e" />
      <rect x={x - 8} y={y + 8} width={16} height={12} rx={2} fill="#92400e" />
      <circle cx={x} cy={y} r={12} fill="#166534" />
      <circle cx={x - 6} cy={y + 4} r={8} fill="#15803d" />
      <circle cx={x + 6} cy={y + 4} r={8} fill="#15803d" />
    </g>
  );
}

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
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
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
    setTransform(t => ({ ...t, scale: Math.max(0.5, Math.min(2.5, t.scale * (e.deltaY > 0 ? 0.92 : 1.08))) }));
  }, []);

  useEffect(() => {
    const el = sceneRef.current;
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  /* 데이터 파생 */
  const ceoIdx = slotRoles.findIndex(r => r.toLowerCase() === 'ceo');
  const ceoName = ceoIdx >= 0 ? (slotNames[ceoIdx] ?? 'CEO') : 'CEO';
  const ceoPresence = presences.find(p => p.zone === 'user' || slotRoles[p.slotId]?.toLowerCase() === 'ceo');

  const meetingAgents = presences.filter(p => p.zone === 'meeting');
  const deskAgents    = presences.filter(p => p.zone !== 'user' && p.zone !== 'meeting' && p.zone !== 'recovery');

  /* 방 내 절대 좌표 변환 */
  const absA  = (spot: {x:number;y:number}) => ({ cx: ROOMS.dept_a.x + spot.x,    cy: ROOMS.dept_a.y + spot.y });
  const absB  = (spot: {x:number;y:number}) => ({ cx: ROOMS.dept_b.x + spot.x,    cy: ROOMS.dept_b.y + spot.y });
  const absWS = (spot: {x:number;y:number}) => ({ cx: ROOMS.workspace.x + spot.x,  cy: ROOMS.workspace.y + spot.y });
  const absMT = (spot: {x:number;y:number}) => ({ cx: ROOMS.meeting.x + spot.x,    cy: ROOMS.meeting.y + spot.y });

  /* 에이전트를 책상에 배정 */
  const allSpots = [
    ...AGENT_SPOTS.dept_a.map(absA),
    ...AGENT_SPOTS.dept_b.map(absB),
    ...AGENT_SPOTS.workspace.map(absWS),
  ];

  return (
    <div
      ref={sceneRef}
      className="iso-scene"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      <div style={{
        position: 'absolute',
        transformOrigin: '0 0',
        transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
      }}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>

          {/* ── 배경 ── */}
          <rect width={W} height={H} fill="#060a0f" />

          {/* ── 복도 ── */}
          <rect x={ROOMS.corridor_v.x} y={ROOMS.corridor_v.y} width={ROOMS.corridor_v.w} height={ROOMS.corridor_v.h} fill="#0a1520" />
          <rect x={ROOMS.corridor_h.x} y={ROOMS.corridor_h.y} width={ROOMS.corridor_h.w} height={ROOMS.corridor_h.h} fill="#0a1520" />
          <rect x={ROOMS.corridor_h2.x} y={ROOMS.corridor_h2.y} width={ROOMS.corridor_h2.w} height={ROOMS.corridor_h2.h} fill="#0a1520" />

          {/* 복도 중앙선 */}
          <line
            x1={ROOMS.corridor_v.x + ROOMS.corridor_v.w / 2} y1={WALL + 10}
            x2={ROOMS.corridor_v.x + ROOMS.corridor_v.w / 2} y2={H - WALL - 10}
            stroke="rgba(255,255,255,0.04)" strokeWidth="1" strokeDasharray="8 6"
          />
          <line
            x1={WALL + 10} y1={ROOMS.corridor_h.y + ROOMS.corridor_h.h / 2}
            x2={W - WALL - 10} y2={ROOMS.corridor_h.y + ROOMS.corridor_h.h / 2}
            stroke="rgba(255,255,255,0.04)" strokeWidth="1" strokeDasharray="8 6"
          />

          {/* ── CEO실 ── */}
          <rect x={ROOMS.ceo.x} y={ROOMS.ceo.y} width={ROOMS.ceo.w} height={ROOMS.ceo.h} fill={ROOMS.ceo.color} />
          <rect x={ROOMS.ceo.x} y={ROOMS.ceo.y} width={ROOMS.ceo.w} height={ROOMS.ceo.h} fill="none" stroke={ROOMS.ceo.border} strokeWidth={WALL} />
          {/* CEO실 가구 */}
          <Sofa x={ROOMS.ceo.x + 20} y={ROOMS.ceo.y + 160} />
          {DESKS.ceo.map((d, i) => (
            <Desk key={i} x={ROOMS.ceo.x + d.x} y={ROOMS.ceo.y + d.y} w={d.w} h={d.h} monitor={d.monitor} />
          ))}
          <Plant x={ROOMS.ceo.x + 175} y={ROOMS.ceo.y + 20} />
          <Plant x={ROOMS.ceo.x + 20} y={ROOMS.ceo.y + 20} />
          {/* CEO실 레이블 */}
          <text x={ROOMS.ceo.x + ROOMS.ceo.w / 2} y={ROOMS.ceo.y + ROOMS.ceo.h - 14}
            textAnchor="middle" fontSize="9" fontWeight="700" letterSpacing="2"
            fill="rgba(255,255,255,0.2)" fontFamily="monospace">
            CEO 집무실
          </text>

          {/* ── 개발부서 A ── */}
          <rect x={ROOMS.dept_a.x} y={ROOMS.dept_a.y} width={ROOMS.dept_a.w} height={ROOMS.dept_a.h} fill={ROOMS.dept_a.color} />
          <rect x={ROOMS.dept_a.x} y={ROOMS.dept_a.y} width={ROOMS.dept_a.w} height={ROOMS.dept_a.h} fill="none" stroke={ROOMS.dept_a.border} strokeWidth={WALL} />
          {/* 파티션 */}
          <line x1={ROOMS.dept_a.x + ROOMS.dept_a.w / 2} y1={ROOMS.dept_a.y + WALL + 20} x2={ROOMS.dept_a.x + ROOMS.dept_a.w / 2} y2={ROOMS.dept_a.y + ROOMS.dept_a.h - 20}
            stroke="rgba(147,197,253,0.2)" strokeWidth="3" />
          {DESKS.dept_a.map((d, i) => (
            <Desk key={i} x={ROOMS.dept_a.x + d.x} y={ROOMS.dept_a.y + d.y} w={d.w} h={d.h} monitor={d.monitor} />
          ))}
          <text x={ROOMS.dept_a.x + ROOMS.dept_a.w / 2} y={ROOMS.dept_a.y + ROOMS.dept_a.h - 14}
            textAnchor="middle" fontSize="9" fontWeight="700" letterSpacing="2"
            fill="rgba(255,255,255,0.2)" fontFamily="monospace">
            개발부서 A
          </text>

          {/* ── 개발부서 B ── */}
          <rect x={ROOMS.dept_b.x} y={ROOMS.dept_b.y} width={ROOMS.dept_b.w} height={ROOMS.dept_b.h} fill={ROOMS.dept_b.color} />
          <rect x={ROOMS.dept_b.x} y={ROOMS.dept_b.y} width={ROOMS.dept_b.w} height={ROOMS.dept_b.h} fill="none" stroke={ROOMS.dept_b.border} strokeWidth={WALL} />
          <line x1={ROOMS.dept_b.x + ROOMS.dept_b.w / 2} y1={ROOMS.dept_b.y + WALL + 20} x2={ROOMS.dept_b.x + ROOMS.dept_b.w / 2} y2={ROOMS.dept_b.y + ROOMS.dept_b.h - 20}
            stroke="rgba(147,197,253,0.2)" strokeWidth="3" />
          {DESKS.dept_b.map((d, i) => (
            <Desk key={i} x={ROOMS.dept_b.x + d.x} y={ROOMS.dept_b.y + d.y} w={d.w} h={d.h} monitor={d.monitor} />
          ))}
          <text x={ROOMS.dept_b.x + ROOMS.dept_b.w / 2} y={ROOMS.dept_b.y + ROOMS.dept_b.h - 14}
            textAnchor="middle" fontSize="9" fontWeight="700" letterSpacing="2"
            fill="rgba(255,255,255,0.2)" fontFamily="monospace">
            개발부서 B
          </text>

          {/* ── 회의실 ── */}
          <rect x={ROOMS.meeting.x} y={ROOMS.meeting.y} width={ROOMS.meeting.w} height={ROOMS.meeting.h} fill={ROOMS.meeting.color} />
          <rect x={ROOMS.meeting.x} y={ROOMS.meeting.y} width={ROOMS.meeting.w} height={ROOMS.meeting.h} fill="none" stroke={ROOMS.meeting.border} strokeWidth={WALL} />
          <MeetingTable cx={ROOMS.meeting.x + ROOMS.meeting.w / 2} cy={ROOMS.meeting.y + ROOMS.meeting.h / 2 - 10} />
          <text x={ROOMS.meeting.x + ROOMS.meeting.w / 2} y={ROOMS.meeting.y + ROOMS.meeting.h - 14}
            textAnchor="middle" fontSize="9" fontWeight="700" letterSpacing="2"
            fill="rgba(255,255,255,0.2)" fontFamily="monospace">
            회의실
          </text>

          {/* ── 작업 공간 ── */}
          <rect x={ROOMS.workspace.x} y={ROOMS.workspace.y} width={ROOMS.workspace.w} height={ROOMS.workspace.h} fill={ROOMS.workspace.color} />
          <rect x={ROOMS.workspace.x} y={ROOMS.workspace.y} width={ROOMS.workspace.w} height={ROOMS.workspace.h} fill="none" stroke={ROOMS.workspace.border} strokeWidth={WALL} />
          {/* 세로 파티션 */}
          <line x1={ROOMS.workspace.x + ROOMS.workspace.w / 2} y1={ROOMS.workspace.y + WALL + 10} x2={ROOMS.workspace.x + ROOMS.workspace.w / 2} y2={ROOMS.workspace.y + ROOMS.workspace.h - 10}
            stroke="rgba(147,197,253,0.15)" strokeWidth="3" />
          {DESKS.workspace.map((d, i) => (
            <Desk key={i} x={ROOMS.workspace.x + d.x} y={ROOMS.workspace.y + d.y} w={d.w} h={d.h} monitor={d.monitor} />
          ))}
          <text x={ROOMS.workspace.x + ROOMS.workspace.w / 2} y={ROOMS.workspace.y + ROOMS.workspace.h - 14}
            textAnchor="middle" fontSize="9" fontWeight="700" letterSpacing="2"
            fill="rgba(255,255,255,0.2)" fontFamily="monospace">
            작업 공간
          </text>

          {/* ── 문 표시 ── */}
          {/* CEO실 → 복도 문 */}
          <rect x={ROOMS.ceo.x + ROOMS.ceo.w - 2} y={ROOMS.ceo.y + 100} width={WALL} height={40} fill="#0a1520" />
          <line x1={ROOMS.ceo.x + ROOMS.ceo.w - 1} y1={ROOMS.ceo.y + 100} x2={ROOMS.ceo.x + ROOMS.ceo.w - 1} y2={ROOMS.ceo.y + 140}
            stroke="#f59e0b" strokeWidth="2" opacity="0.4" />
          {/* CEO실 → 복도(수평) 문 */}
          <rect x={ROOMS.ceo.x + 80} y={ROOMS.ceo.y + ROOMS.ceo.h - 2} width={40} height={WALL} fill="#0a1520" />
          <line x1={ROOMS.ceo.x + 80} y1={ROOMS.ceo.y + ROOMS.ceo.h - 1} x2={ROOMS.ceo.x + 120} y2={ROOMS.ceo.y + ROOMS.ceo.h - 1}
            stroke="#f59e0b" strokeWidth="2" opacity="0.4" />
          {/* 부서실 문들 */}
          <rect x={ROOMS.dept_a.x} y={ROOMS.dept_a.y + 100} width={WALL} height={40} fill="#0a1520" />
          <rect x={ROOMS.dept_b.x} y={ROOMS.dept_b.y + 100} width={WALL} height={40} fill="#0a1520" />
          <rect x={ROOMS.meeting.x + 80} y={ROOMS.meeting.y} width={40} height={WALL} fill="#0a1520" />
          <rect x={ROOMS.workspace.x + 80} y={ROOMS.workspace.y} width={40} height={WALL} fill="#0a1520" />

          {/* ── 에이전트: CEO ── */}
          {(() => {
            const s = AGENT_SPOTS.ceo[0];
            return (
              <AgentDot
                key="ceo"
                cx={ROOMS.ceo.x + s.x}
                cy={ROOMS.ceo.y + s.y}
                name={ceoName}
                agentType="ceo"
                status={ceoPresence ? toAgentStatus(ceoPresence.status) : 'idle'}
                selected={selectedAgent === 'ceo'}
                onClick={() => setSelectedAgent(a => a === 'ceo' ? null : 'ceo')}
              />
            );
          })()}

          {/* ── 에이전트: 책상 에이전트들 ── */}
          {deskAgents.slice(0, allSpots.length).map((p, i) => {
            const spot = allSpots[i];
            if (!spot) return null;
            return (
              <AgentDot
                key={p.terminalId}
                cx={spot.cx}
                cy={spot.cy}
                name={p.agent || p.terminalId}
                agentType={detectAgentType(p.agent || p.terminalId)}
                status={toAgentStatus(p.status)}
                selected={selectedAgent === p.terminalId}
                onClick={() => setSelectedAgent(a => a === p.terminalId ? null : p.terminalId)}
              />
            );
          })}

          {/* ── 에이전트: 회의실 ── */}
          {meetingAgents.slice(0, AGENT_SPOTS.meeting.length).map((p, i) => {
            const spot = AGENT_SPOTS.meeting[i];
            if (!spot) return null;
            const pos = absMT(spot);
            return (
              <AgentDot
                key={`m-${p.terminalId}`}
                cx={pos.cx}
                cy={pos.cy}
                name={p.agent || p.terminalId}
                agentType={detectAgentType(p.agent || p.terminalId)}
                status="meeting"
                selected={selectedAgent === p.terminalId}
                onClick={() => setSelectedAgent(a => a === p.terminalId ? null : p.terminalId)}
              />
            );
          })}

          {/* ── 선택 인스펙터 (선택된 에이전트 정보) ── */}
          {selectedAgent && (() => {
            const p = presences.find(a => a.terminalId === selectedAgent || selectedAgent === 'ceo');
            if (!p && selectedAgent !== 'ceo') return null;
            const name = selectedAgent === 'ceo' ? ceoName : (p?.agent || selectedAgent);
            const status = selectedAgent === 'ceo' ? (ceoPresence ? toAgentStatus(ceoPresence.status) : 'idle') : toAgentStatus(p?.status ?? '');
            const task = p?.liveTask || '대기 중';
            return (
              <g>
                <rect x={W - 210} y={H - 90} width={200} height={80} rx={8} fill="rgba(13,24,38,0.95)" stroke="rgba(255,255,255,0.1)" strokeWidth="1" />
                <text x={W - 110} y={H - 68} textAnchor="middle" fontSize="12" fontWeight="700" fill="#e5eef8">{name}</text>
                <circle cx={W - 185} cy={H - 50} r={5} fill={STATUS_COLORS[status]} />
                <text x={W - 175} y={H - 46} fontSize="10" fill="rgba(255,255,255,0.5)">{status}</text>
                <text x={W - 110} y={H - 26} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.3)">{task.slice(0, 28)}</text>
              </g>
            );
          })()}

        </svg>
      </div>

      {/* ── 줌 컨트롤 ── */}
      <div style={{ position: 'absolute', bottom: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 4, zIndex: 50 }}>
        {[
          { label: '+', fn: () => setTransform(t => ({ ...t, scale: Math.min(2.5, t.scale * 1.2) })) },
          { label: '−', fn: () => setTransform(t => ({ ...t, scale: Math.max(0.5, t.scale * 0.8) })) },
          { label: '↺', fn: () => setTransform({ x: 0, y: 0, scale: 1 }) },
        ].map(({ label, fn }) => (
          <button key={label} onClick={fn} style={btnStyle}>{label}</button>
        ))}
      </div>

      {/* ── 범례 ── */}
      <div style={{
        position: 'absolute', top: 12, left: 12, zIndex: 50,
        background: 'rgba(6,10,15,0.85)', border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 8, padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 5,
      }}>
        {Object.entries(STATUS_COLORS).map(([s, color]) => (
          <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 5px ${color}` }} />
            {{ idle: '대기', working: '작업 중', meeting: '회의', error: '오류' }[s]}
          </div>
        ))}
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', marginTop: 2, paddingTop: 4, fontSize: 9, color: 'rgba(255,255,255,0.25)' }}>
          클릭: 에이전트 상세
        </div>
      </div>

      {/* ── 에이전트 수 ── */}
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
