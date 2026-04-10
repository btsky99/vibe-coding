/**
 * ------------------------------------------------------------------------
 * FILE: IsoRoom.tsx
 * DESCRIPTION: 아이소메트릭 맵 타일 렌더러.
 *              순수 SVG 좌표 계산 기반 진짜 아이소메트릭.
 *              타일맵(2D 배열) → SVG polygon 변환.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: v2 — CSS 가짜 아이소 → SVG 좌표 기반 진짜 아이소로 전면 재작성
 * ------------------------------------------------------------------------
 */

/* ── 아이소메트릭 좌표 변환 ──
   월드 그리드 (col, row) → SVG 화면 (sx, sy)
   sx = (col - row) * TW/2
   sy = (col + row) * TH/2
*/
export const TW = 80;   /* 타일 너비 (화면 픽셀) */
export const TH = 40;   /* 타일 높이 (TW/2)      */
export const WALL_H = 56; /* 벽 높이 픽셀 */

export function isoToScreen(col: number, row: number): { x: number; y: number } {
  return {
    x: (col - row) * (TW / 2),
    y: (col + row) * (TH / 2),
  };
}

/* ── 타일 타입 ── */
export type TileType =
  | 'floor'        /* 방 바닥 */
  | 'corridor'     /* 복도 */
  | 'wall_n'       /* 북쪽 벽 (좌상단 방향) */
  | 'wall_w'       /* 서쪽 벽 */
  | 'empty';       /* 빈 공간 */

/* ── 바닥 타일 polygon (다이아몬드) ── */
export function FloorTile({
  col, row,
  color = '#1a2435',
  stroke = 'rgba(255,255,255,0.06)',
}: {
  col: number; row: number;
  color?: string; stroke?: string;
}) {
  const c = isoToScreen(col, row);
  const points = [
    `${c.x},${c.y}`,
    `${c.x + TW / 2},${c.y + TH / 2}`,
    `${c.x},${c.y + TH}`,
    `${c.x - TW / 2},${c.y + TH / 2}`,
  ].join(' ');
  return <polygon points={points} fill={color} stroke={stroke} strokeWidth="1" />;
}

/* ── 복도 타일 ── */
export function CorridorTile({ col, row }: { col: number; row: number }) {
  return <FloorTile col={col} row={row} color="#111d2b" stroke="rgba(255,255,255,0.04)" />;
}

/* ── 북쪽 벽 (타일 상단에 솟아오르는 2면 벽) ──
   왼쪽 면(어두움) + 오른쪽 면(밝음) + 상단 면(가장 밝음)
*/
export function WallTile({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const h = WALL_H;

  /* 바닥 다이아몬드 4개 꼭짓점 */
  const top    = { x: c.x,            y: c.y };
  const right  = { x: c.x + TW / 2,  y: c.y + TH / 2 };
  const bottom = { x: c.x,            y: c.y + TH };
  const left   = { x: c.x - TW / 2,  y: c.y + TH / 2 };

  /* 위로 올린 꼭짓점 */
  const topUp    = { x: top.x,    y: top.y    - h };
  const rightUp  = { x: right.x,  y: right.y  - h };
  const leftUp   = { x: left.x,   y: left.y   - h };

  const toStr = (...pts: {x:number;y:number}[]) => pts.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <g>
      {/* 상단면 (밝음) */}
      <polygon
        points={toStr(topUp, rightUp, top, leftUp)}
        fill="#253545"
        stroke="rgba(255,255,255,0.1)"
        strokeWidth="1"
      />
      {/* 왼쪽면 (어두움) */}
      <polygon
        points={toStr(leftUp, top, bottom, left)}
        fill="#0f1923"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth="1"
      />
      {/* 오른쪽면 (중간) */}
      <polygon
        points={toStr(topUp, rightUp, right, top)}
        fill="#1a2d40"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth="1"
      />
    </g>
  );
}

/* ── 반높이 파티션 ── */
export function PartitionTile({ col, row }: { col: number; row: number }) {
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

/* ── 책상 오브젝트 (타일 위에 얹힘) ── */
export function DeskObject({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const dw = TW * 0.75;
  const dh = TH * 0.75;
  const oh = 12; /* 책상 두께 */

  /* 책상을 타일 중앙에 배치 */
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
      {/* 상판 */}
      <polygon points={toStr(topUp, rightUp, bottom, leftUp)} fill="#5c3d1e" stroke="#3d2810" strokeWidth="1" />
      <polygon points={toStr(topUp, rightUp, { x: rightUp.x, y: rightUp.y }, top, leftUp)} fill="#6b4826" stroke="#3d2810" strokeWidth="1" />
      {/* 왼쪽면 */}
      <polygon points={toStr(leftUp, bottom, left, { x: leftUp.x, y: leftUp.y + oh })} fill="#3d2810" stroke="#2a1c08" strokeWidth="1" />
      {/* 오른쪽면 */}
      <polygon points={toStr(rightUp, bottom, right, { x: rightUp.x, y: rightUp.y + oh })} fill="#4a2e12" stroke="#2a1c08" strokeWidth="1" />
      {/* 다리 */}
      <line x1={left.x + 2} y1={left.y} x2={left.x + 2} y2={left.y + 14} stroke="#2a1c08" strokeWidth="2" />
      <line x1={right.x - 2} y1={right.y} x2={right.x - 2} y2={right.y + 14} stroke="#2a1c08" strokeWidth="2" />
    </g>
  );
}

/* ── 모니터 오브젝트 ── */
export function MonitorObject({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const mx = c.x;
  const my = c.y - 18; /* 책상 위 */

  return (
    <g>
      {/* 스탠드 */}
      <line x1={mx} y1={my + 22} x2={mx} y2={my + 32} stroke="#0d1826" strokeWidth="3" />
      <ellipse cx={mx} cy={my + 32} rx={6} ry={2.5} fill="#0d1826" />
      {/* 화면 베젤 */}
      <polygon
        points={`${mx},${my} ${mx + 18},${my + 9} ${mx},${my + 18} ${mx - 18},${my + 9}`}
        fill="#0d1826"
        stroke="#1e3048"
        strokeWidth="1"
      />
      {/* 화면 */}
      <polygon
        points={`${mx},${my + 2} ${mx + 15},${my + 9.5} ${mx},${my + 17} ${mx - 15},${my + 9.5}`}
        fill="#0a2040"
      />
      {/* 코드 라인 */}
      <line x1={mx - 10} y1={my + 8} x2={mx - 2} y2={my + 8} stroke="#22d3ee" strokeWidth="1" opacity="0.8" />
      <line x1={mx - 10} y1={my + 11} x2={mx + 4} y2={my + 11} stroke="#a78bfa" strokeWidth="1" opacity="0.6" />
      <line x1={mx - 10} y1={my + 14} x2={mx - 4} y2={my + 14} stroke="#34d399" strokeWidth="1" opacity="0.7" />
      {/* 화면 글로우 */}
      <polygon
        points={`${mx},${my + 2} ${mx + 15},${my + 9.5} ${mx},${my + 17} ${mx - 15},${my + 9.5}`}
        fill="#22d3ee"
        opacity="0.04"
      />
    </g>
  );
}

/* ── 소파 오브젝트 ── */
export function SofaObject({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const ox = c.x;
  const oy = c.y + TH * 0.1;

  const sw = TW * 0.85;
  const sh = TH * 0.6;
  const sh2 = TH * 0.4;
  const backH = 22;

  /* 좌석 상단면 */
  const sTop    = { x: ox,          y: oy + sh * 0.2 };
  const sRight  = { x: ox + sw / 2, y: oy + sh * 0.7 };
  const sBottom = { x: ox,          y: oy + sh * 1.2 };
  const sLeft   = { x: ox - sw / 2, y: oy + sh * 0.7 };

  /* 등받이 */
  const bTop    = { x: ox,            y: oy - 4 };
  const bRight  = { x: ox + sw * 0.4, y: oy + sh2 * 0.6 };
  const bTopUp  = { x: bTop.x,        y: bTop.y  - backH };
  const bRightUp = { x: bRight.x,     y: bRight.y - backH };
  const bLeftUp  = { x: ox - sw * 0.4, y: oy + sh2 * 0.6 - backH };
  const bLeft    = { x: ox - sw * 0.4, y: oy + sh2 * 0.6 };

  const toStr = (...pts: {x:number;y:number}[]) => pts.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <g>
      {/* 등받이 */}
      <polygon points={toStr(bTopUp, bRightUp, bRight, bTop, bLeft, bLeftUp)} fill="#2952a0" stroke="#1e3c7a" strokeWidth="1" />
      <polygon points={toStr(bLeftUp, bLeft, bTop, bTopUp)} fill="#1e3c7a" stroke="#163060" strokeWidth="1" />
      {/* 좌석 상판 */}
      <polygon points={toStr(sTop, sRight, sBottom, sLeft)} fill="#2952a0" stroke="#1e3c7a" strokeWidth="1" />
      {/* 좌측면 */}
      <polygon points={toStr(sLeft, sBottom, { x: sLeft.x, y: sLeft.y + 10 }, { x: sBottom.x, y: sBottom.y + 10 })} fill="#1e3c7a" />
      {/* 쿠션 구분 */}
      <line x1={ox} y1={oy + sh * 0.2} x2={ox} y2={oy + sh * 1.2} stroke="rgba(255,255,255,0.07)" strokeWidth="1" />
    </g>
  );
}

/* ── 원형 테이블 ── */
export function TableObject({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const cx = c.x;
  const cy = c.y + TH * 0.5;

  return (
    <g>
      {/* 다리 */}
      <rect x={cx - 2} y={cy} width={4} height={16} rx={2} fill="#2a1c0e" />
      <ellipse cx={cx} cy={cy + 16} rx={10} ry={4} fill="#1a0e06" />
      {/* 상판 그림자 */}
      <ellipse cx={cx} cy={cy - 2} rx={28} ry={14} fill="rgba(0,0,0,0.2)" />
      {/* 상판 */}
      <ellipse cx={cx} cy={cy - 4} rx={26} ry={12} fill="#3d2810" stroke="#2a1c0e" strokeWidth="1.5" />
      {/* 상판 하이라이트 */}
      <ellipse cx={cx - 4} cy={cy - 7} rx={10} ry={4} fill="white" opacity="0.05" />
      {/* 나이테 */}
      <ellipse cx={cx} cy={cy - 4} rx={18} ry={8} fill="none" stroke="#4a3218" strokeWidth="0.8" opacity="0.4" />
    </g>
  );
}

/* ── 화분 ── */
export function PotObject({ col, row }: { col: number; row: number }) {
  const c = isoToScreen(col, row);
  const px = c.x;
  const py = c.y + TH * 0.2;

  return (
    <g>
      {/* 화분 */}
      <polygon
        points={`${px - 6},${py + 16} ${px + 6},${py + 16} ${px + 4},${py + 26} ${px - 4},${py + 26}`}
        fill="#92400e"
        stroke="#78350f"
        strokeWidth="1"
      />
      <ellipse cx={px} cy={py + 16} rx={6} ry={2.5} fill="#a16207" />
      {/* 흙 */}
      <ellipse cx={px} cy={py + 16} rx={5} ry={2} fill="#3b1c0a" />
      {/* 줄기 */}
      <line x1={px} y1={py + 14} x2={px - 4} y2={py + 2} stroke="#92400e" strokeWidth="1.5" />
      <line x1={px} y1={py + 14} x2={px + 3} y2={py + 5} stroke="#92400e" strokeWidth="1.5" />
      {/* 잎 */}
      <ellipse cx={px - 7} cy={py - 1} rx={7} ry={4} fill="#166534" transform={`rotate(-30, ${px - 7}, ${py - 1})`} />
      <ellipse cx={px + 6} cy={py + 2} rx={6} ry={3.5} fill="#15803d" transform={`rotate(20, ${px + 6}, ${py + 2})`} />
      <ellipse cx={px} cy={py - 4} rx={5} ry={6} fill="#166534" />
    </g>
  );
}
