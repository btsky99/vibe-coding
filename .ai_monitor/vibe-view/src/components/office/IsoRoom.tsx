/**
 * ------------------------------------------------------------------------
 * FILE: IsoRoom.tsx
 * DESCRIPTION: 아이소메트릭 방 컴포넌트.
 *              CEO실 / 부서실 / 회의실 세 가지 방 타입 제공.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: 최초 생성 — 아이소메트릭 오피스 재설계
 * ------------------------------------------------------------------------
 */

import type { ReactNode } from 'react';
import { IsoFloorGrid, IsoDesk, IsoMonitor, IsoSofa, IsoTable, IsoChair, IsoPartition, IsoPot } from './IsoFurniture';
import IsoAgent, { detectAgentType } from './IsoAgent';
import type { AgentStatus } from './IsoAgent';

/* ── 공통 방 래퍼 ── */
interface IsoRoomProps {
  label: string;
  width: number;   /* px */
  height: number;  /* px */
  wallColor?: string;
  children?: ReactNode;
  style?: React.CSSProperties;
  onClick?: () => void;
}

export function IsoRoom({ label, width, height, wallColor = '#0f1923', children, style, onClick }: IsoRoomProps) {
  const wallH = 72;

  return (
    <div
      style={{
        position: 'relative',
        width,
        height: height + wallH,
        ...style,
      }}
      onClick={onClick}
    >
      {/* 방 레이블 */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 20,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.3)',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
        }}
      >
        {label}
      </div>

      {/* 뒷벽 */}
      <div
        style={{
          position: 'absolute',
          top: 14,
          left: 0,
          width,
          height: wallH * 0.6,
          background: wallColor,
          borderTop: '2px solid rgba(255,255,255,0.08)',
          borderLeft: '1px solid rgba(255,255,255,0.05)',
          borderRight: '1px solid rgba(255,255,255,0.05)',
        }}
      />

      {/* 바닥 */}
      <div style={{ position: 'absolute', top: wallH * 0.5, left: 0, right: 0 }}>
        <IsoFloorGrid cols={Math.ceil(width / 64)} rows={2} tileW={64} tileH={32} />
      </div>

      {/* 왼쪽 벽 */}
      <div
        style={{
          position: 'absolute',
          top: wallH * 0.5,
          left: 0,
          width: 6,
          height: height,
          background: 'rgba(0,0,0,0.25)',
          borderLeft: '2px solid rgba(255,255,255,0.06)',
        }}
      />

      {/* 오른쪽 벽 */}
      <div
        style={{
          position: 'absolute',
          top: wallH * 0.5,
          right: 0,
          width: 6,
          height: height,
          background: 'rgba(0,0,0,0.15)',
          borderRight: '2px solid rgba(255,255,255,0.06)',
        }}
      />

      {/* 콘텐츠 */}
      <div style={{ position: 'absolute', top: wallH, left: 0, right: 0, bottom: 0 }}>
        {children}
      </div>

      {/* 방 테두리 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          border: '1px solid rgba(42,63,90,0.6)',
          borderRadius: 4,
          pointerEvents: 'none',
          zIndex: 15,
        }}
      />
    </div>
  );
}

/* ── CEO실 ── */
interface RoomCeoProps {
  ceoName: string;
  ceoStatus: AgentStatus;
  style?: React.CSSProperties;
}

export function RoomCeo({ ceoName, ceoStatus, style }: RoomCeoProps) {
  return (
    <IsoRoom label="CEO 집무실" width={260} height={200} wallColor="#0a1520" style={style}>
      {/* 소파 (좌측) */}
      <IsoSofa x={8} y={20} />

      {/* 책상 */}
      <IsoDesk x={120} y={30} />

      {/* 모니터 */}
      <IsoMonitor x={128} y={2} />

      {/* 화분 */}
      <IsoPot x={210} y={10} />

      {/* CEO 캐릭터 */}
      <IsoAgent
        agentType="ceo"
        name={ceoName}
        status={ceoStatus}
        x={140}
        y={60}
      />

      {/* 바닥 카펫 */}
      <div
        style={{
          position: 'absolute',
          left: 20,
          top: 80,
          width: 160,
          height: 90,
          background: 'rgba(30,58,95,0.2)',
          border: '2px solid rgba(30,58,95,0.4)',
          borderRadius: 4,
        }}
      />
    </IsoRoom>
  );
}

/* ── 부서실 ── */
export interface DeptAgent {
  name: string;
  status: AgentStatus;
}

interface RoomDeptProps {
  deptName: string;
  agents: DeptAgent[];
  style?: React.CSSProperties;
}

export function RoomDept({ deptName, agents, style }: RoomDeptProps) {
  /* 에이전트 수에 따른 책상 그리드 계산 */
  const cols = Math.min(3, Math.ceil(Math.sqrt(agents.length || 1)));
  const rows = Math.ceil((agents.length || 1) / cols);
  const roomW = Math.max(280, cols * 100 + 40);
  const roomH = Math.max(200, rows * 110 + 40);

  return (
    <IsoRoom label={deptName} width={roomW} height={roomH} wallColor="#0e1d2e" style={style}>
      {agents.map((agent, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const deskX = col * 100 + 20;
        const deskY = row * 110 + 10;

        return (
          <div key={agent.name} style={{ position: 'absolute', left: deskX, top: deskY }}>
            {/* 파티션 */}
            {col < cols - 1 && (
              <IsoPartition x={78} y={-10} height={60} />
            )}
            {/* 책상 */}
            <IsoDesk x={0} y={20} />
            {/* 모니터 */}
            <IsoMonitor x={8} y={-2} />
            {/* 캐릭터 */}
            <IsoAgent
              agentType={detectAgentType(agent.name)}
              name={agent.name}
              status={agent.status}
              x={20}
              y={50}
            />
          </div>
        );
      })}

      {/* 에이전트 없을 때 빈 표시 */}
      {agents.length === 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'rgba(255,255,255,0.15)',
            fontSize: 12,
          }}
        >
          대기 중
        </div>
      )}
    </IsoRoom>
  );
}

/* ── 회의실 ── */
interface RoomMeetingProps {
  agents: DeptAgent[];
  style?: React.CSSProperties;
}

export function RoomMeeting({ agents, style }: RoomMeetingProps) {
  /* 원형 테이블 주변 의자 배치 */
  const chairPositions = [
    { x: 30,  y: 40 },   /* 상좌 */
    { x: 110, y: 40 },   /* 상우 */
    { x: 20,  y: 100 },  /* 하좌 */
    { x: 120, y: 100 },  /* 하우 */
    { x: 70,  y: 20 },   /* 상중 */
    { x: 70,  y: 130 },  /* 하중 */
  ];

  return (
    <IsoRoom label="회의실" width={240} height={220} wallColor="#0c1828" style={style}>
      {/* 원형 테이블 */}
      <IsoTable x={72} y={60} />

      {/* 의자 */}
      {chairPositions.slice(0, Math.max(agents.length, 2)).map((pos, i) => (
        <IsoChair key={i} x={pos.x} y={pos.y} color={i < agents.length ? '#1e4080' : '#1a2d48'} />
      ))}

      {/* 에이전트 (회의 참석자) */}
      {agents.slice(0, 6).map((agent, i) => {
        const pos = chairPositions[i] ?? chairPositions[0];
        return (
          <IsoAgent
            key={agent.name}
            agentType={detectAgentType(agent.name)}
            name={agent.name}
            status="meeting"
            x={pos.x - 10}
            y={pos.y - 40}
          />
        );
      })}

      {/* 빈 회의실 */}
      {agents.length === 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: 8,
            left: 0,
            right: 0,
            textAlign: 'center',
            color: 'rgba(255,255,255,0.12)',
            fontSize: 11,
          }}
        >
          예약 없음
        </div>
      )}
    </IsoRoom>
  );
}
