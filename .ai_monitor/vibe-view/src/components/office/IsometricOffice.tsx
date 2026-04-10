/**
 * ------------------------------------------------------------------------
 * FILE: IsometricOffice.tsx
 * DESCRIPTION: 아이소메트릭 오피스 메인 컨테이너.
 *              CEO실 / 부서실 / 회의실 방 분리형 레이아웃.
 *              Phaser.js 없이 React + CSS만으로 구현.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: 최초 생성 — 아이소메트릭 오피스 재설계
 * ------------------------------------------------------------------------
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import type { OfficeAgentPresence, OfficeZoneState, OfficeEventCard } from '../../hooks/useOfficeState';
import type { AgentStatus } from './IsoAgent';
import { RoomCeo, RoomDept, RoomMeeting } from './IsoRoom';
import type { DeptAgent } from './IsoRoom';
import './isometric.css';

interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number;
}

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

/* ── 에이전트 상태 변환 ── */
function toAgentStatus(status: string): AgentStatus {
  const s = status.toLowerCase();
  if (s.includes('error') || s.includes('fail')) return 'error';
  if (s.includes('meet') || s.includes('discuss')) return 'meeting';
  if (s.includes('work') || s.includes('run') || s.includes('busy') || s.includes('modif') || s.includes('analyz')) return 'working';
  return 'idle';
}

/* ── 부서별 에이전트 그루핑 ── */
function groupByDept(presences: OfficeAgentPresence[]): Map<string, DeptAgent[]> {
  const map = new Map<string, DeptAgent[]>();
  for (const p of presences) {
    if (p.zone === 'user' || p.zone === 'meeting' || p.zone === 'recovery') continue;
    const dept = p.zone || 'desk';
    if (!map.has(dept)) map.set(dept, []);
    map.get(dept)!.push({ name: p.agent || p.terminalId, status: toAgentStatus(p.status) });
  }
  return map;
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
  /* ── 패닝 / 줌 상태 ── */
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const dragging = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });
  const sceneRef = useRef<HTMLDivElement>(null);

  /* ── 드래그 패닝 ── */
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

  /* ── 휠 줌 ── */
  const onWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform(t => ({
      ...t,
      scale: Math.max(0.4, Math.min(2.5, t.scale * delta)),
    }));
  }, []);

  useEffect(() => {
    const el = sceneRef.current;
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  /* ── 데이터 파생 ── */
  /* CEO 찾기 */
  const ceoIdx = slotRoles.findIndex(r => r.toLowerCase() === 'ceo');
  const ceoName = ceoIdx >= 0 ? (slotNames[ceoIdx] ?? 'CEO') : 'CEO';
  const ceoPresence = presences.find(p => p.zone === 'user' || slotRoles[p.slotId]?.toLowerCase() === 'ceo');
  const ceoStatus: AgentStatus = ceoPresence ? toAgentStatus(ceoPresence.status) : 'idle';

  /* 회의실 에이전트 */
  const meetingAgents: DeptAgent[] = presences
    .filter(p => p.zone === 'meeting')
    .map(p => ({ name: p.agent || p.terminalId, status: 'meeting' as AgentStatus }));

  /* 부서별 그루핑 */
  const deptMap = groupByDept(presences);
  /* 부서가 없으면 존 이름 기반으로 폴백 */
  if (deptMap.size === 0) {
    const workingAgents = presences.filter(
      p => p.zone !== 'user' && p.zone !== 'meeting' && p.zone !== 'recovery'
    );
    if (workingAgents.length > 0) {
      deptMap.set('개발부서', workingAgents.map(p => ({
        name: p.agent || p.terminalId,
        status: toAgentStatus(p.status),
      })));
    }
  }

  const deptEntries = Array.from(deptMap.entries());

  /* ── 레이아웃 상수 ── */
  const GAP = 24;
  const CEO_W = 280;
  const MEETING_W = 260;

  /* 초기 중앙 정렬 */
  const [initialized, setInitialized] = useState(false);
  useEffect(() => {
    if (initialized || !sceneRef.current) return;
    const rect = sceneRef.current.getBoundingClientRect();
    setTransform({ x: rect.width / 2 - 400, y: 60, scale: 1 });
    setInitialized(true);
  }, [initialized]);

  return (
    <div
      ref={sceneRef}
      className="iso-scene"
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      {/* 줌/패닝 월드 */}
      <div
        className="iso-world"
        style={{
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
          transformOrigin: '0 0',
        }}
      >
        {/* ── 상단 행: CEO실 + 부서실들 ── */}
        <div style={{ display: 'flex', gap: GAP, alignItems: 'flex-start' }}>

          {/* CEO실 */}
          <RoomCeo
            ceoName={ceoName}
            ceoStatus={ceoStatus}
            style={{ flexShrink: 0, width: CEO_W }}
          />

          {/* 부서실들 */}
          <div style={{ display: 'flex', gap: GAP, flexWrap: 'wrap' }}>
            {deptEntries.map(([deptId, agents]) => {
              const zone = _zones.find(z => z.id === deptId);
              const label = zone?.label ?? deptId;
              return (
                <RoomDept
                  key={deptId}
                  deptName={label}
                  agents={agents}
                  style={{ cursor: 'pointer' }}
                />
              );
            })}

            {/* 부서 없을 때 기본 빈 부서 */}
            {deptEntries.length === 0 && (
              <RoomDept deptName="개발부서" agents={[]} />
            )}
          </div>
        </div>

        {/* ── 하단 행: 회의실 ── */}
        <div style={{ marginTop: GAP }}>
          <RoomMeeting agents={meetingAgents} />
        </div>
      </div>

      {/* ── HUD: 줌 컨트롤 ── */}
      <div
        style={{
          position: 'absolute',
          bottom: 16,
          right: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          zIndex: 50,
        }}
      >
        <button
          onClick={() => setTransform(t => ({ ...t, scale: Math.min(2.5, t.scale * 1.2) }))}
          style={btnStyle}
          title="확대"
        >+</button>
        <button
          onClick={() => setTransform(t => ({ ...t, scale: Math.max(0.4, t.scale * 0.8) }))}
          style={btnStyle}
          title="축소"
        >−</button>
        <button
          onClick={() => setTransform({ x: 0, y: 60, scale: 1 })}
          style={{ ...btnStyle, fontSize: 10 }}
          title="초기화"
        >↺</button>
      </div>

      {/* ── HUD: 범례 ── */}
      <div
        style={{
          position: 'absolute',
          top: 12,
          left: 12,
          zIndex: 50,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          background: 'rgba(6,10,15,0.75)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 8,
          padding: '8px 12px',
        }}
      >
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

      {/* ── HUD: 총 에이전트 수 ── */}
      <div
        style={{
          position: 'absolute',
          top: 12,
          right: 16,
          zIndex: 50,
          fontSize: 11,
          color: 'rgba(255,255,255,0.3)',
        }}
      >
        에이전트 {presences.length}명 재직 중
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 6,
  background: 'rgba(255,255,255,0.06)',
  border: '1px solid rgba(255,255,255,0.1)',
  color: 'rgba(255,255,255,0.7)',
  fontSize: 16,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  lineHeight: 1,
};
