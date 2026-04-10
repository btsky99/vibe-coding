/**
 * ------------------------------------------------------------------------
 * FILE: IsoFurniture.tsx
 * DESCRIPTION: 아이소메트릭 오피스 가구 SVG 컴포넌트.
 *              LEGO 스타일 조립 구조 (Parts-based Composition).
 * REVISION HISTORY:
 * - 2026-04-10 Gemini: 가구 부품화 및 대표님 전용 세트(CEO Set) 추가
 * ------------------------------------------------------------------------
 */

import { isoToScreen, TW, TH } from './IsoRoom';

// ─── LEGO 가구 파츠 (Furniture Parts) ───

/** 책상 상판 파츠 */
function PartDeskTop({ x, y, w, h, depth, color, stroke }: any) {
  const pts = [
    { x: x,         y: y - depth },
    { x: x + w / 2, y: y + h / 2 - depth },
    { x: x,         y: y + h - depth },
    { x: x - w / 2, y: y + h / 2 - depth }
  ];
  const toStr = (p: any[]) => p.map(pt => `${pt.x},${pt.y}`).join(' ');
  
  return (
    <g>
      {/* 두께(옆면) */}
      <polygon points={toStr([pts[2], {x: pts[2].x, y: pts[2].y + depth}, {x: pts[3].x, y: pts[3].y + depth}, pts[3]])} fill={stroke} />
      <polygon points={toStr([pts[1], {x: pts[1].x, y: pts[1].y + depth}, {x: pts[2].x, y: pts[2].y + depth}, pts[2]])} fill={stroke} opacity="0.8" />
      {/* 상판 */}
      <polygon points={toStr(pts)} fill={color} stroke={stroke} strokeWidth="1" />
    </g>
  );
}

/** 모니터 파츠 */
function PartMonitor({ x, y, color = "#0f172a" }: { x: number; y: number; color?: string }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect x="-1" y="8" width="2" height="8" fill="#1e293b" />
      <ellipse cx="0" cy="16" rx="6" ry="2.5" fill="#1e293b" />
      <polygon points="0,0 16,8 0,16 -16,8" fill={color} stroke="#334155" />
      <polygon points="0,2 13,8.5 0,15 -13,8.5" fill="#1e3a8a" opacity="0.4" />
    </g>
  );
}

/** 소품 파츠: 커피/명패 */
function PartProp({ type, x, y }: { type: 'coffee' | 'nameplate'; x: number; y: number }) {
  if (type === 'coffee') {
    return (
      <g transform={`translate(${x}, ${y})`}>
        <rect x="-2" y="-4" width="4" height="6" fill="white" />
        <ellipse cx="0" cy="-4" rx="2" ry="1" fill="#ddd" />
      </g>
    );
  }
  return (
    <g transform={`translate(${x}, ${y})`}>
      <polygon points="-8,0 8,0 6,4 -6,4" fill="#fbbf24" stroke="#d97706" strokeWidth="0.5" />
      <text x="0" y="3" textAnchor="middle" fontSize="3" fill="#92400e" fontWeight="bold">CEO</text>
    </g>
  );
}

// ─── 조립기 (Assemblers) ───

/** [LEGO 세트] 대표님 전용 중역 책상 */
export function CeoDesk({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const ox = c.x;
  const oy = c.y + TH * 0.2;

  return (
    <g>
      {/* 1. 책상 베이스 (원목) */}
      <PartDeskTop x={ox} y={oy} w={TW * 1.2} h={TH * 1.2} depth={14} color="#451a03" stroke="#270e02" />
      {/* 2. 가죽 매트 */}
      <PartDeskTop x={ox} y={oy - 1} w={TW * 0.8} h={TH * 0.8} depth={2} color="#1e293b" stroke="#0f172a" />
      {/* 3. 트리플 모니터 조립 */}
      <PartMonitor x={ox - 22} y={oy - 12} />
      <PartMonitor x={ox} y={oy - 15} />
      <PartMonitor x={ox + 22} y={oy - 12} />
      {/* 4. 소품: 황금 명패 & 커피 */}
      <PartProp type="nameplate" x={ox} y={oy + 10} />
      <PartProp type="coffee" x={ox + 25} y={oy + 5} />
    </g>
  );
}

/** [LEGO 세트] 일반 직원 책상 */
export function IsoDesk({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const ox = c.x;
  const oy = c.y + TH * 0.2;

  return (
    <g>
      <PartDeskTop x={ox} y={oy} w={TW * 0.8} h={TH * 0.8} depth={10} color="#334155" stroke="#1e293b" />
      <PartMonitor x={ox} y={oy - 10} />
      <PartProp type="coffee" x={ox + 15} y={oy + 2} />
    </g>
  );
}

// ... (다른 가구들도 부품화 가능)
export function IsoSofa({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  return (
    <g transform={`translate(${c.x}, ${c.y + 10})`}>
      <rect x="-20" y="-10" width="40" height="20" rx="4" fill="#1e40af" stroke="#1e3a8a" />
      <rect x="-20" y="-20" width="40" height="12" rx="4" fill="#1e3a8a" />
    </g>
  );
}

export function IsoTable({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  return (
    <g transform={`translate(${c.x}, ${c.y + 10})`}>
       <PartDeskTop x={0} y={0} w={TW * 1.2} h={TH * 1.2} depth={6} color="#451a03" stroke="#270e02" />
    </g>
  );
}

export function IsoPot({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  return (
    <g transform={`translate(${c.x}, ${c.y + 12})`}>
      <polygon points="-6,0 6,0 4,10 -4,10" fill="#92400e" />
      <circle cx="0" cy="-4" r="8" fill="#166534" />
      <circle cx="4" cy="-8" r="6" fill="#15803d" />
      <circle cx="-3" cy="-10" r="5" fill="#16a34a" />
    </g>
  );
}

export function IsoPartition({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  return (
    <g transform={`translate(${c.x}, ${c.y})`} opacity="0.6">
      <rect x="-30" y="-40" width="60" height="50" rx="2" fill="#94a3b8" stroke="#64748b" />
    </g>
  );
}
