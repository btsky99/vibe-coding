/**
 * ------------------------------------------------------------------------
 * FILE: IsoFurniture.tsx
 * DESCRIPTION: 아이소메트릭 오피스 가구 SVG 컴포넌트.
 *              책상, 모니터, 파티션, 소파, 테이블, 바닥 타일.
 * REVISION HISTORY:
 * - 2026-04-10 Claude: 최초 생성 — 아이소메트릭 오피스 재설계
 * ------------------------------------------------------------------------
 */

import type { ReactNode } from 'react';

/* ── 아이소메트릭 책상 ── */
export function IsoDesk({ x = 0, y = 0 }: { x?: number; y?: number }) {
  return (
    <svg
      width="72"
      height="56"
      viewBox="0 0 72 56"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 상판 (윗면) */}
      <polygon points="36,4 68,20 36,36 4,20" fill="#5c3d1e" stroke="#3d2810" strokeWidth="1" />
      {/* 상판 하이라이트 */}
      <polygon points="36,4 68,20 36,36 4,20" fill="url(#deskTop)" stroke="none" />
      {/* 왼쪽 다리면 */}
      <polygon points="4,20 36,36 36,52 4,36" fill="#3d2810" stroke="#2a1c08" strokeWidth="1" />
      {/* 오른쪽 다리면 */}
      <polygon points="68,20 36,36 36,52 68,36" fill="#4a2e12" stroke="#2a1c08" strokeWidth="1" />
      {/* 다리 */}
      <line x1="8" y1="34" x2="8" y2="50" stroke="#2a1c08" strokeWidth="2" />
      <line x1="64" y1="34" x2="64" y2="50" stroke="#2a1c08" strokeWidth="2" />
      <line x1="36" y1="50" x2="36" y2="54" stroke="#2a1c08" strokeWidth="2" />
      <defs>
        <linearGradient id="deskTop" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="white" stopOpacity="0.08" />
          <stop offset="100%" stopColor="black" stopOpacity="0.05" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/* ── 아이소메트릭 모니터 ── */
export function IsoMonitor({ x = 0, y = 0 }: { x?: number; y?: number }) {
  return (
    <svg
      width="48"
      height="52"
      viewBox="0 0 48 52"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 스탠드 */}
      <rect x="20" y="38" width="8" height="8" fill="#1a2a3a" />
      <rect x="16" y="45" width="16" height="4" rx="1" fill="#1a2a3a" />
      {/* 베젤 (윗면) */}
      <polygon points="24,2 44,12 24,22 4,12" fill="#0d1826" stroke="#1e3048" strokeWidth="1" />
      {/* 베젤 (왼면) */}
      <polygon points="4,12 24,22 24,38 4,28" fill="#0a1520" stroke="#1e3048" strokeWidth="1" />
      {/* 베젤 (오른면) */}
      <polygon points="44,12 24,22 24,38 44,28" fill="#0c1a28" stroke="#1e3048" strokeWidth="1" />
      {/* 화면 */}
      <polygon points="24,5 41,14 24,23 7,14" fill="#0a2040" />
      {/* 코드 라인 효과 */}
      <line x1="12" y1="12" x2="22" y2="12" stroke="#22d3ee" strokeWidth="1" opacity="0.7" />
      <line x1="12" y1="15" x2="28" y2="15" stroke="#a78bfa" strokeWidth="1" opacity="0.5" />
      <line x1="12" y1="18" x2="20" y2="18" stroke="#34d399" strokeWidth="1" opacity="0.6" />
      {/* 화면 글로우 */}
      <polygon points="24,5 41,14 24,23 7,14" fill="#22d3ee" opacity="0.03" />
    </svg>
  );
}

/* ── 아이소메트릭 파티션 ── */
export function IsoPartition({ x = 0, y = 0, height = 48 }: { x?: number; y?: number; height?: number }) {
  return (
    <svg
      width="64"
      height={height + 20}
      viewBox={`0 0 64 ${height + 20}`}
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 상단 프레임 */}
      <polygon points={`32,4 60,18 32,32 4,18`} fill="#1e3048" stroke="#2a4060" strokeWidth="1" />
      {/* 왼쪽 패널 (반투명 유리) */}
      <polygon
        points={`4,18 32,32 32,${height} 4,${height - 14}`}
        fill="rgba(147,197,253,0.06)"
        stroke="rgba(147,197,253,0.15)"
        strokeWidth="1"
      />
      {/* 오른쪽 패널 */}
      <polygon
        points={`60,18 32,32 32,${height} 60,${height - 14}`}
        fill="rgba(147,197,253,0.04)"
        stroke="rgba(147,197,253,0.12)"
        strokeWidth="1"
      />
      {/* 프레임 세로선 */}
      <line x1="4" y1="18" x2="4" y2={height - 14} stroke="#2a4060" strokeWidth="2" />
      <line x1="60" y1="18" x2="60" y2={height - 14} stroke="#2a4060" strokeWidth="2" />
      <line x1="32" y1="32" x2="32" y2={height} stroke="#2a4060" strokeWidth="2" />
    </svg>
  );
}

/* ── CEO실 소파 ── */
export function IsoSofa({ x = 0, y = 0 }: { x?: number; y?: number }) {
  return (
    <svg
      width="80"
      height="52"
      viewBox="0 0 80 52"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 소파 등받이 (윗면) */}
      <polygon points="40,2 72,18 56,26 24,10" fill="#1e4080" stroke="#163060" strokeWidth="1" />
      {/* 소파 등받이 (앞면) */}
      <polygon points="24,10 56,26 56,38 24,22" fill="#1a3870" stroke="#163060" strokeWidth="1" />
      {/* 소파 쿠션 (윗면) */}
      <polygon points="8,24 72,24 56,38 8,38" fill="#2952a0" stroke="#1e3c7a" strokeWidth="1" />
      {/* 소파 쿠션 (옆면) */}
      <polygon points="8,24 8,44 8,38" fill="#1e3c7a" />
      <polygon points="72,24 72,44 56,38" fill="#1e3c7a" />
      {/* 소파 다리 */}
      <rect x="10" y="38" width="4" height="8" rx="1" fill="#0f1e36" />
      <rect x="66" y="38" width="4" height="8" rx="1" fill="#0f1e36" />
      {/* 쿠션 구분선 */}
      <line x1="40" y1="24" x2="40" y2="38" stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
      {/* 하이라이트 */}
      <polygon points="8,24 72,24 56,38 8,38" fill="url(#sofaGrad)" />
      <defs>
        <linearGradient id="sofaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="white" stopOpacity="0.07" />
          <stop offset="100%" stopColor="black" stopOpacity="0.1" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/* ── 회의실 원형 테이블 ── */
export function IsoTable({ x = 0, y = 0 }: { x?: number; y?: number }) {
  return (
    <svg
      width="96"
      height="64"
      viewBox="0 0 96 64"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 상판 타원형 */}
      <ellipse cx="48" cy="28" rx="44" ry="22" fill="#2a1c0e" stroke="#1a0e06" strokeWidth="1.5" />
      <ellipse cx="48" cy="28" rx="40" ry="18" fill="#3d2810" />
      {/* 나이테 효과 */}
      <ellipse cx="48" cy="28" rx="30" ry="13" fill="none" stroke="#4a3218" strokeWidth="1" opacity="0.5" />
      <ellipse cx="48" cy="28" rx="18" ry="8" fill="none" stroke="#4a3218" strokeWidth="1" opacity="0.4" />
      {/* 하이라이트 */}
      <ellipse cx="42" cy="24" rx="16" ry="6" fill="white" opacity="0.05" />
      {/* 중앙 다리 (측면) */}
      <rect x="44" y="38" width="8" height="12" rx="2" fill="#2a1c0e" />
      {/* 받침대 */}
      <ellipse cx="48" cy="50" rx="16" ry="6" fill="#1a0e06" />
    </svg>
  );
}

/* ── 아이소메트릭 의자 ── */
export function IsoChair({ x = 0, y = 0, color = '#1a3060' }: { x?: number; y?: number; color?: string }) {
  return (
    <svg
      width="40"
      height="44"
      viewBox="0 0 40 44"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 등받이 */}
      <polygon points="20,2 36,10 28,14 12,6" fill={color} stroke="rgba(0,0,0,0.3)" strokeWidth="1" />
      <polygon points="12,6 28,14 28,24 12,16" fill={color} stroke="rgba(0,0,0,0.3)" strokeWidth="1" opacity="0.8" />
      {/* 좌석 */}
      <polygon points="4,20 36,20 28,28 4,28" fill={color} stroke="rgba(0,0,0,0.3)" strokeWidth="1" />
      {/* 다리 */}
      <line x1="6" y1="28" x2="4" y2="40" stroke="rgba(0,0,0,0.4)" strokeWidth="2" />
      <line x1="32" y1="28" x2="34" y2="40" stroke="rgba(0,0,0,0.4)" strokeWidth="2" />
    </svg>
  );
}

/* ── 화분 ── */
export function IsoPot({ x = 0, y = 0 }: { x?: number; y?: number }) {
  return (
    <svg
      width="32"
      height="48"
      viewBox="0 0 32 48"
      style={{ position: 'absolute', left: x, top: y, overflow: 'visible' }}
    >
      {/* 잎 */}
      <ellipse cx="16" cy="10" rx="10" ry="12" fill="#166534" />
      <ellipse cx="8" cy="14" rx="7" ry="9" fill="#15803d" />
      <ellipse cx="24" cy="14" rx="7" ry="9" fill="#15803d" />
      {/* 줄기 */}
      <line x1="16" y1="18" x2="16" y2="30" stroke="#92400e" strokeWidth="2" />
      {/* 화분 */}
      <polygon points="8,30 24,30 20,42 12,42" fill="#92400e" stroke="#78350f" strokeWidth="1" />
      <ellipse cx="16" cy="30" rx="8" ry="3" fill="#a16207" />
    </svg>
  );
}

/* ── 체크무늬 바닥 ── */
export function IsoFloorGrid({
  cols,
  rows,
  tileW = 64,
  tileH = 32,
}: {
  cols: number;
  rows: number;
  tileW?: number;
  tileH?: number;
}) {
  const tiles: ReactNode[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const isLight = (r + c) % 2 === 0;
      /* 아이소메트릭 다이아몬드 배치:
         x = (c - r) * tileW/2
         y = (c + r) * tileH/2
      */
      const x = (c - r) * (tileW / 2);
      const y = (c + r) * (tileH / 2);
      tiles.push(
        <polygon
          key={`${r}-${c}`}
          points={`
            ${x},${y}
            ${x + tileW / 2},${y + tileH / 2}
            ${x},${y + tileH}
            ${x - tileW / 2},${y + tileH / 2}
          `}
          fill={isLight ? '#1a2435' : '#131c2b'}
          stroke="rgba(255,255,255,0.03)"
          strokeWidth="1"
        />
      );
    }
  }

  const totalW = (cols + rows) * (tileW / 2);
  const totalH = (cols + rows) * (tileH / 2);

  return (
    <svg
      width={totalW}
      height={totalH}
      viewBox={`${-tileW / 2} 0 ${totalW} ${totalH}`}
      style={{ display: 'block' }}
    >
      {tiles}
    </svg>
  );
}
