/**
 * ------------------------------------------------------------------------
 * FILE: OfficeWorld.tsx
 * DESCRIPTION: 메타버스 오피스 Phase 2: Glassmorphism Spatial UI.
 *              Canvas 배경(그리드, 라인) + React DOM(유리 질감 오브젝트) 하이브리드 렌더러.
 * REVISION HISTORY:
 * - 2026-04-09 Claude: 동적 zone 레이아웃 — 부서 개수만큼 desk 영역을 자동 분할.
 *                      기존에는 하드코딩된 4개 zone만 지원해 모든 부서가 'desk'로
 *                      폴백되며 시각적으로 겹치는 버그가 있었음.
 * - 2026-04-08 Gemini: 전면 재설계 — 하이테크 홀로그램 & 유리 질감 UI 도입
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { OfficeAgentPresence, OfficeEventCard, OfficeZone, OfficeZoneState } from '../../hooks/useOfficeState';

interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number;
}

interface OfficeWorldProps {
  presences: OfficeAgentPresence[];
  zones: OfficeZoneState[];
  events: OfficeEventCard[];
  selectedDesk: number;
  onDeskClick: (slotId: number) => void;
  onZoneClick?: (zone: OfficeZone) => void;
  speechBubbles?: SpeechBubble[];
  slotNames?: string[];
}

type Rect = { x: number; y: number; w: number; h: number };

const AGENT_THEMES: Record<string, { main: string; glow: string; secondary: string }> = {
  claude: { main: '#a78bfa', glow: 'rgba(167, 139, 250, 0.4)', secondary: '#7c3aed' },
  gemini: { main: '#34d399', glow: 'rgba(52, 211, 153, 0.4)', secondary: '#059669' },
  codex: { main: '#22d3ee', glow: 'rgba(34, 211, 238, 0.4)', secondary: '#0891b2' },
  user: { main: '#fbbf24', glow: 'rgba(251, 191, 36, 0.4)', secondary: '#d97706' },
  unknown: { main: '#94a3b8', glow: 'rgba(148, 163, 184, 0.3)', secondary: '#475569' },
};

// 공용 존 (항상 같은 위치)
// - user: 대표실 (CEO 전용) — 좌상단 확대
// - meeting: 회의실
// - recovery: 복구 영역
// 그 외 zone ID는 동적 부서 zone으로 간주되어 desk 영역(중앙 하단)을 분할한다.
const COMMON_ZONE_LAYOUT: Record<string, Rect> = {
  user:     { x: 0.04, y: 0.04, w: 0.22, h: 0.14 },
  meeting:  { x: 0.66, y: 0.08, w: 0.30, h: 0.30 },
  recovery: { x: 0.66, y: 0.42, w: 0.30, h: 0.20 },
};

// 부서 zone이 배치될 기본 영역 — 공용 존을 제외한 중앙~좌하단
const DEPT_CANVAS: Rect = { x: 0.04, y: 0.20, w: 0.58, h: 0.72 };

type ZoneLayout = Record<string, Rect>;

/**
 * 전체 zone 레이아웃 계산.
 * 공용 존은 고정 위치, 동적 부서 zone은 DEPT_CANVAS를 개수에 맞춰 균등 분할한다.
 *
 * 분할 규칙:
 *  - 1개: 전체
 *  - 2개: 좌우 2분할
 *  - 3개: 상단 1개 + 하단 2개
 *  - 4개 이상: 2xN 그리드
 */
function computeZoneLayout(zoneIds: string[]): ZoneLayout {
  const layout: ZoneLayout = { ...COMMON_ZONE_LAYOUT };
  const deptZones = zoneIds.filter((z) => !COMMON_ZONE_LAYOUT[z] && z !== 'desk');

  if (deptZones.length === 0) {
    layout.desk = DEPT_CANVAS;
    return layout;
  }

  const n = deptZones.length;
  const { x, y, w, h } = DEPT_CANVAS;

  if (n === 1) {
    layout[deptZones[0]] = { x, y, w, h };
  } else if (n === 2) {
    const half = w / 2;
    const gap = 0.012;
    layout[deptZones[0]] = { x, y, w: half - gap, h };
    layout[deptZones[1]] = { x: x + half + gap, y, w: half - gap, h };
  } else if (n === 3) {
    const halfH = h / 2;
    const halfW = w / 2;
    const gap = 0.012;
    layout[deptZones[0]] = { x, y, w, h: halfH - gap };
    layout[deptZones[1]] = { x, y: y + halfH + gap, w: halfW - gap, h: halfH - gap };
    layout[deptZones[2]] = { x: x + halfW + gap, y: y + halfH + gap, w: halfW - gap, h: halfH - gap };
  } else {
    // 2열 그리드
    const cols = 2;
    const rows = Math.ceil(n / cols);
    const cellW = w / cols;
    const cellH = h / rows;
    const gap = 0.008;
    deptZones.forEach((id, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      layout[id] = {
        x: x + col * cellW + gap,
        y: y + row * cellH + gap,
        w: cellW - gap * 2,
        h: cellH - gap * 2,
      };
    });
  }

  // desk는 폴백용 — 아직 분류 안 된 에이전트가 오면 첫 번째 부서 자리로
  layout.desk = layout[deptZones[0]] || DEPT_CANVAS;
  return layout;
}

function getZoneRect(zone: string, layout: ZoneLayout): Rect {
  return layout[zone] || layout.desk || DEPT_CANVAS;
}

function getZonePoints(zone: string, width: number, height: number, count: number, layout: ZoneLayout) {
  const rect = getZoneRect(zone, layout);
  const px = rect.x * width;
  const py = rect.y * height;
  const pw = rect.w * width;
  const ph = rect.h * height;
  const points: Array<{ x: number; y: number }> = [];

  const cols = Math.max(1, Math.ceil(Math.sqrt(count || 1)));
  const rows = Math.max(1, Math.ceil((count || 1) / cols));
  // 상단 라벨 공간 확보 — y 방향 여백을 두고 시작
  const topPad = 36; // px, 부서 이름 라벨 영역
  const stepX = pw / (cols + 1);
  const availH = Math.max(ph - topPad, ph * 0.6);
  const stepY = availH / (rows + 1);

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      points.push({
        x: px + stepX * (col + 1),
        y: py + topPad + stepY * (row + 1),
      });
    }
  }
  return points;
}

export default function OfficeWorld({
  presences,
  zones,
  events,
  selectedDesk,
  onDeskClick,
  onZoneClick,
  speechBubbles = [],
  slotNames,
}: OfficeWorldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // 동적 zone 레이아웃 — zones prop이 바뀔 때마다 재계산
  const zoneLayout = useMemo(() => computeZoneLayout(zones.map((z) => z.id)), [zones]);
  // slotNames는 타입 시그니처 유지용(외부 props 호환). 내부에서는 presence.agent 라벨을 사용.
  void slotNames;
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  // 화면 크기 추적 — ResizeObserver로 정확히 크기 변경 시에만 업데이트
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDimensions(prev => (prev.width === Math.round(width) && prev.height === Math.round(height)) ? prev : { width: Math.round(width), height: Math.round(height) });
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // 1. Canvas 배경 렌더링 (그리드, 존 베이스)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = dimensions.width * dpr;
    canvas.height = dimensions.height * dpr;
    ctx.scale(dpr, dpr);

    const { width, height } = dimensions;

    // 배경 채우기
    ctx.fillStyle = '#060a0f';
    ctx.fillRect(0, 0, width, height);

    // 미래지향적 그리드
    ctx.strokeStyle = 'rgba(34, 211, 238, 0.04)';
    ctx.lineWidth = 1;
    for (let x = 0; x < width; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
    }
    for (let y = 0; y < height; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
    }

    // 존 영역 외곽 광채 (Soft Glow)
    Object.keys(zoneLayout).forEach(zId => {
      if (zId === 'desk') return; // desk는 폴백 별칭 — 중복 렌더 방지
      const r = zoneLayout[zId];
      const zx = r.x * width;
      const zy = r.y * height;
      const zw = r.w * width;
      const zh = r.h * height;

      const gradient = ctx.createRadialGradient(zx + zw/2, zy + zh/2, 0, zx + zw/2, zy + zh/2, zw/1.5);
      gradient.addColorStop(0, 'rgba(15, 23, 42, 0.4)');
      gradient.addColorStop(1, 'rgba(6, 10, 15, 0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(zx - 20, zy - 20, zw + 40, zh + 40);

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
      ctx.setLineDash([10, 5]);
      ctx.strokeRect(zx, zy, zw, zh);
      ctx.setLineDash([]);
    });
  }, [dimensions.width, dimensions.height, zoneLayout]);

  // 2. 에이전트 그룹화 (좌표 계산용)
  const groupedPresences = useMemo(() => {
    const map = new Map<string, OfficeAgentPresence[]>();
    presences.forEach(p => {
      const list = map.get(p.zone) || [];
      list.push(p);
      map.set(p.zone, list);
    });
    return map;
  }, [presences]);

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-[#060a0f] font-sans selection:bg-cyan-500/30">
      {/* Layer 1: Canvas Background */}
      <canvas ref={canvasRef} className="absolute inset-0 pointer-events-none" />

      {/* Layer 2: Zone Labels (DOM) — 라벨만 클릭 가능, 영역 전체는 투과 */}
      {zones.map(z => {
        const r = getZoneRect(z.id, zoneLayout);
        return (
        <div
          key={z.id}
          className="absolute pointer-events-none"
          style={{
            left: `${r.x * 100}%`,
            top: `${r.y * 100}%`,
            width: `${r.w * 100}%`,
            height: `${r.h * 100}%`,
          }}
        >
          <button
            type="button"
            onClick={() => onZoneClick?.(z.id)}
            className="pointer-events-auto absolute top-2 left-4 flex flex-col gap-0.5 opacity-40 hover:opacity-100 transition-opacity cursor-pointer bg-transparent border-none p-0"
          >
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-cyan-400/80">
              {z.label}
            </span>
            <div className="h-[1px] w-8 bg-gradient-to-r from-cyan-500/50 to-transparent" />
          </button>
        </div>
        );
      })}

      {/* Layer 3: Agents (Glowing Orbs) — 부서 zone 내부 좌표로 배치 */}
      <div className="absolute inset-0 pointer-events-none">
        <AnimatePresence>
          {presences.map(presence => {
            const isSelected = selectedDesk === presence.slotId;
            const theme = AGENT_THEMES[presence.colorKey] || AGENT_THEMES.unknown;
            const busy = presence.status === 'running' || presence.status === 'started';
            
            // 좌표 계산: zone(부서 또는 공용) 내부에 그리드 배치
            const members = groupedPresences.get(presence.zone) || [];
            const points = getZonePoints(presence.zone, dimensions.width, dimensions.height, Math.max(members.length, 1), zoneLayout);
            const idx = members.findIndex(m => m.terminalId === presence.terminalId);
            const targetPos = points[Math.max(0, idx)] || { x: dimensions.width * 0.14, y: dimensions.height * 0.08 };

            return (
              <motion.div
                key={presence.terminalId}
                initial={false}
                animate={{ x: targetPos.x, y: targetPos.y }}
                transition={{ type: 'spring', damping: 25, stiffness: 120 }}
                className="absolute pointer-events-auto cursor-pointer"
                onClick={() => onDeskClick(presence.slotId)}
                style={{ transform: 'translate(-50%, -50%)', zIndex: isSelected ? 50 : 10 }}
              >
                <div className="relative flex flex-col items-center">
                  {/* Rotating Ring */}
                  <div 
                    className={`absolute rounded-full border border-dashed transition-all duration-700 ${busy ? 'animate-[spin_4s_linear_infinite]' : 'opacity-30'}`}
                    style={{ 
                      width: isSelected ? 54 : 42, 
                      height: isSelected ? 54 : 42, 
                      borderColor: isSelected ? theme.main : `${theme.main}44`,
                      top: '50%', left: '50%', transform: 'translate(-50%, -50%)'
                    }}
                  />
                  
                  {/* Central Orb */}
                  <div 
                    className={`relative rounded-full transition-all duration-500 shadow-2xl flex items-center justify-center`}
                    style={{ 
                      width: isSelected ? 28 : 22, 
                      height: isSelected ? 28 : 22, 
                      backgroundColor: theme.main,
                      boxShadow: `0 0 ${busy ? '30px' : '15px'} ${theme.glow}`,
                    }}
                  >
                    {/* Inner Core */}
                    <div className="w-1/2 h-1/2 rounded-full bg-white/40 blur-[1px] animate-pulse" />
                  </div>

                  {/* Label & Task Badge */}
                  <div className="absolute top-8 flex flex-col items-center gap-1 w-32">
                    <span className={`text-[9px] font-black tracking-tighter uppercase px-1.5 py-0.5 rounded border backdrop-blur-sm transition-colors ${
                      isSelected ? 'text-white border-cyan-500/50 bg-cyan-500/20' : 'text-white/60 border-white/5 bg-black/40'
                    }`}>
                      T{presence.slotId + 1} · {presence.agent}
                    </span>
                    
                    {presence.liveTask && (
                      <motion.div 
                        initial={{ opacity: 0, y: 5 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="max-w-full"
                      >
                        <span className="text-[8px] text-cyan-200/80 bg-cyan-950/40 border border-cyan-500/20 px-2 py-0.5 rounded-full backdrop-blur-sm truncate block">
                          {presence.liveTask.slice(0, 20)}
                        </span>
                      </motion.div>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Layer 5: Speech Bubbles (Floating Glass) */}
      <AnimatePresence>
        {speechBubbles.map((bubble, idx) => {
          // deskId → slotId에 해당하는 presence의 위치를 찾는다
          const bubblePresence = presences.find((p) => p.slotId === bubble.deskId);
          if (!bubblePresence) return null;
          const members = groupedPresences.get(bubblePresence.zone) || [];
          const pts = getZonePoints(bubblePresence.zone, dimensions.width, dimensions.height, Math.max(members.length, 1), zoneLayout);
          const mIdx = members.findIndex((m) => m.terminalId === bubblePresence.terminalId);
          const point = pts[Math.max(0, mIdx)] || { x: dimensions.width * 0.14, y: dimensions.height * 0.3 };
          return (
            <motion.div
              key={`${bubble.deskId}-${bubble.createdAt}-${idx}`}
              initial={{ opacity: 0, scale: 0.8, y: -20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: -10 }}
              className="absolute pointer-events-none"
              style={{ left: point.x, top: point.y - 70, transform: 'translateX(-50%)' }}
            >
              <div className="bg-white/[0.08] backdrop-blur-xl border border-white/10 px-4 py-1.5 rounded-2xl shadow-2xl">
                <span className="text-[11px] font-medium text-white/90 whitespace-nowrap">
                  {bubble.text}
                </span>
                <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-white/10 rotate-45 border-r border-b border-white/10" />
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>

      {/* Layer 6: Events (Minimal HUD Cards) */}
      <div className="absolute top-24 right-6 flex flex-col gap-3 w-64 pointer-events-none">
        {events.slice(0, 3).map((event, i) => (
          <motion.div
            key={event.id}
            initial={{ x: 50, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ delay: i * 0.1 }}
            className={`
              p-3 rounded-xl border backdrop-blur-lg flex flex-col gap-1 transition-all
              ${event.severity === 'error' ? 'bg-red-500/10 border-red-500/20' : 'bg-white/[0.03] border-white/5'}
            `}
          >
            <div className="flex items-center justify-between">
              <span className={`text-[9px] font-black uppercase tracking-widest ${event.severity === 'error' ? 'text-red-400' : 'text-cyan-400/60'}`}>
                {event.zone}
              </span>
              <div className={`h-1 w-1 rounded-full ${event.severity === 'error' ? 'bg-red-500 animate-ping' : 'bg-cyan-500/50'}`} />
            </div>
            <div className="text-[10px] font-bold text-white/80 truncate">{event.title}</div>
            <div className="text-[9px] text-white/40 truncate">{event.subtitle}</div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
