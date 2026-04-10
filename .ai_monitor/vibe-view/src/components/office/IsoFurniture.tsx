/**
 * ------------------------------------------------------------------------
 * FILE: IsoFurniture.tsx
 * DESCRIPTION: 아이소메트릭 오피스 가구 SVG 컴포넌트.
 *              책상, 모니터, 파티션, 소파, 테이블.
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: 컴포넌트 이름 통일 및 빌드 에러 수정
 * ------------------------------------------------------------------------
 */

import { isoToScreen, TW, TH, WALL_H } from './IsoRoom';

/* ── 아이소메트릭 책상 ── */
export function IsoDesk({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const dw = TW * 0.75;
  const dh = TH * 0.75;
  const oh = 12;

  const ox = c.x;
  const oy = c.y + TH * 0.15;

  const top    = { x: ox,          y: oy };
  const right  = { x: ox + dw / 2, y: oy + dh / 2 };
  const bottom = { x: ox,          y: oy + dh };
  const left   = { x: ox - dw / 2, y: oy + dh / 2 };

  const topUp   = { x: top.x,   y: top.y   - oh };
  const rightUp = { x: right.x, y: right.y - oh };
  const leftUp  = { x: left.x,  y: left.y  - oh };

  const toStr = (...pts: {x:number;y:number}[]) => pts.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <g>
      <polygon points={toStr(topUp, rightUp, bottom, leftUp)} fill="#5c3d1e" stroke="#3d2810" strokeWidth="1" />
      <polygon points={toStr(topUp, rightUp, { x: rightUp.x, y: rightUp.y }, top, leftUp)} fill="#6b4826" stroke="#3d2810" strokeWidth="1" />
      <polygon points={toStr(leftUp, bottom, left, { x: leftUp.x, y: leftUp.y + oh })} fill="#3d2810" stroke="#2a1c08" strokeWidth="1" />
      <polygon points={toStr(rightUp, bottom, right, { x: rightUp.x, y: rightUp.y + oh })} fill="#4a2e12" stroke="#2a1c08" strokeWidth="1" />
      <line x1={left.x + 2} y1={left.y} x2={left.x + 2} y2={left.y + 14} stroke="#2a1c08" strokeWidth="2" />
      <line x1={right.x - 2} y1={right.y} x2={right.x - 2} y2={right.y + 14} stroke="#2a1c08" strokeWidth="2" />
    </g>
  );
}

/* ── 아이소메트릭 모니터 ── */
export function IsoMonitor({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const mx = c.x;
  const my = c.y - 18;

  return (
    <g>
      <line x1={mx} y1={my + 22} x2={mx} y2={my + 32} stroke="#0d1826" strokeWidth="3" />
      <ellipse cx={mx} cy={my + 32} rx={6} ry={2.5} fill="#0d1826" />
      <polygon points={`${mx},${my} ${mx + 18},${my + 9} ${mx},${my + 18} ${mx - 18},${my + 9}`} fill="#0d1826" stroke="#1e3048" strokeWidth="1" />
      <polygon points={`${mx},${my + 2} ${mx + 15},${my + 9.5} ${mx},${my + 17} ${mx - 15},${my + 9.5}`} fill="#0a2040" />
    </g>
  );
}

/* ── 아이소메트릭 파티션 ── */
export function IsoPartition({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const h = WALL_H * 0.55;

  const top    = { x: c.x,            y: c.y };
  const right  = { x: c.x + TW / 2,  y: c.y + TH / 2 };
  const bottom = { x: c.x,            y: c.y + TH };
  const left   = { x: c.x - TW / 2,  y: c.y + TH / 2 };

  const topUp   = { x: top.x,   y: top.y   - h };
  const rightUp = { x: right.x, y: right.y - h };
  const leftUp  = { x: left.x,  y: left.y  - h };

  const toStr = (...pts: {x:number;y:number}[]) => pts.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <g opacity="0.85">
      <polygon points={toStr(topUp, rightUp, top, leftUp)} fill="#1e3348" stroke="rgba(147,197,253,0.2)" strokeWidth="1" />
      <polygon points={toStr(leftUp, top, bottom, left)} fill="rgba(147,197,253,0.07)" stroke="rgba(147,197,253,0.15)" strokeWidth="1" />
      <polygon points={toStr(topUp, rightUp, right, top)} fill="rgba(147,197,253,0.05)" stroke="rgba(147,197,253,0.12)" strokeWidth="1" />
    </g>
  );
}

/* ── 아이소메트릭 소파 ── */
export function IsoSofa({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const ox = c.x;
  const oy = c.y + TH * 0.1;

  const sw = TW * 0.85;
  const sh = TH * 0.6;
  const backH = 22;

  const sTop    = { x: ox,          y: oy + sh * 0.2 };
  const sRight  = { x: ox + sw / 2, y: oy + sh * 0.7 };
  const sBottom = { x: ox,          y: oy + sh * 1.2 };
  const sLeft   = { x: ox - sw / 2, y: oy + sh * 0.7 };

  const toStr = (...pts: {x:number;y:number}[]) => pts.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <g>
      <polygon points={toStr(sTop, sRight, sBottom, sLeft)} fill="#2952a0" stroke="#1e3c7a" strokeWidth="1" />
      <line x1={ox} y1={oy + sh * 0.2} x2={ox} y2={oy + sh * 1.2} stroke="rgba(255,255,255,0.07)" strokeWidth="1" />
    </g>
  );
}

/* ── 아이소메트릭 테이블 ── */
export function IsoTable({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const cx = c.x;
  const cy = c.y + TH * 0.5;

  return (
    <g>
      <rect x={cx - 2} y={cy} width={4} height={16} rx={2} fill="#2a1c0e" />
      <ellipse cx={cx} cy={cy - 4} rx={26} ry={12} fill="#3d2810" stroke="#2a1c0e" strokeWidth="1.5" />
    </g>
  );
}

/* ── 화분 ── */
export function IsoPot({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const px = c.x;
  const py = c.y + TH * 0.2;

  return (
    <g>
      <polygon points={`${px - 6},${py + 16} ${px + 6},${py + 16} ${px + 4},${py + 26} ${px - 4},${py + 26}`} fill="#92400e" stroke="#78350f" strokeWidth="1" />
      <ellipse cx={px} cy={py + 16} rx={6} ry={2.5} fill="#a16207" />
    </g>
  );
}
