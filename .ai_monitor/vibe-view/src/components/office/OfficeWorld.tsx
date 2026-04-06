/**
 * ------------------------------------------------------------------------
 * FILE: OfficeWorld.tsx
 * DESCRIPTION: 메타버스 오피스 Phase 1 월드 렌더러.
 *              존 기반 2D 캔버스 오피스를 렌더링하고 에이전트를 각 공간으로 배치한다.
 * REVISION HISTORY:
 * - 2026-04-06 Codex: 존 기반 메타버스 오피스 월드로 재작성
 * - 2026-04-03 Claude: 초기 생성 — DeskRPG-Lite 캔버스 월드
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from 'react';
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
}

type Rect = { x: number; y: number; w: number; h: number };

const AGENT_COLORS: Record<string, { main: string; glow: string; body: string; hair: string }> = {
  claude: { main: '#8b5cf6', glow: 'rgba(139,92,246,0.28)', body: '#6d28d9', hair: '#c4b5fd' },
  gemini: { main: '#10b981', glow: 'rgba(16,185,129,0.26)', body: '#059669', hair: '#86efac' },
  codex: { main: '#06b6d4', glow: 'rgba(6,182,212,0.28)', body: '#0891b2', hair: '#a5f3fc' },
  unknown: { main: '#94a3b8', glow: 'rgba(148,163,184,0.24)', body: '#64748b', hair: '#e2e8f0' },
};

const ZONE_LAYOUT: Record<OfficeZone, Rect> = {
  desk: { x: 0.05, y: 0.16, w: 0.56, h: 0.58 },
  meeting: { x: 0.66, y: 0.11, w: 0.27, h: 0.22 },
  review: { x: 0.66, y: 0.37, w: 0.27, h: 0.19 },
  memory: { x: 0.66, y: 0.60, w: 0.27, h: 0.16 },
  git: { x: 0.05, y: 0.80, w: 0.24, h: 0.12 },
  lounge: { x: 0.32, y: 0.80, w: 0.29, h: 0.12 },
  recovery: { x: 0.66, y: 0.80, w: 0.27, h: 0.12 },
  user: { x: 0.05, y: 0.04, w: 0.20, h: 0.08 },
};

const DESK_SLOTS = [
  { id: 0, col: 0, row: 0 },
  { id: 1, col: 1, row: 0 },
  { id: 2, col: 2, row: 0 },
  { id: 3, col: 3, row: 0 },
  { id: 4, col: 0, row: 1 },
  { id: 5, col: 1, row: 1 },
  { id: 6, col: 2, row: 1 },
  { id: 7, col: 3, row: 1 },
];

function getDeskAnchor(slotId: number, width: number, height: number) {
  const rect = ZONE_LAYOUT.desk;
  const px = rect.x * width;
  const py = rect.y * height;
  const pw = rect.w * width;
  const ph = rect.h * height;
  const slot = DESK_SLOTS.find((item) => item.id === slotId) ?? DESK_SLOTS[0];
  const gapX = pw / 4.7;
  const gapY = ph / 2.5;
  return {
    x: px + 90 + slot.col * gapX,
    y: py + 95 + slot.row * gapY,
  };
}

function getZonePoints(zone: OfficeZone, width: number, height: number, count: number) {
  const rect = ZONE_LAYOUT[zone];
  const px = rect.x * width;
  const py = rect.y * height;
  const pw = rect.w * width;
  const ph = rect.h * height;
  const points: Array<{ x: number; y: number }> = [];

  const cols = Math.max(1, Math.ceil(Math.sqrt(count || 1)));
  const rows = Math.max(1, Math.ceil((count || 1) / cols));
  const stepX = pw / (cols + 1);
  const stepY = ph / (rows + 1);

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      points.push({
        x: px + stepX * (col + 1),
        y: py + stepY * (row + 1),
      });
    }
  }

  return points;
}

function drawAgent(
  ctx: CanvasRenderingContext2D,
  presence: OfficeAgentPresence,
  x: number,
  y: number,
  selected: boolean,
  t: number,
) {
  const colors = AGENT_COLORS[presence.colorKey] ?? AGENT_COLORS.unknown;
  const busy = presence.status === 'running' || presence.status === 'started';
  const bobY = busy ? Math.sin(t * 5 + presence.slotId) * 2 : 0;

  ctx.save();

  ctx.shadowColor = colors.main;
  ctx.shadowBlur = selected ? 24 : busy ? 12 : 0;
  ctx.fillStyle = selected ? `${colors.main}55` : colors.glow;
  ctx.beginPath();
  ctx.ellipse(x, y + 20, selected ? 22 : 18, 7, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;

  ctx.fillStyle = colors.hair;
  ctx.fillRect(x - 9, y - 22 + bobY, 18, 7);
  ctx.fillStyle = '#fde3c1';
  ctx.fillRect(x - 8, y - 15 + bobY, 16, 11);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(x - 5, y - 11 + bobY, 2, 2);
  ctx.fillRect(x + 3, y - 11 + bobY, 2, 2);
  ctx.fillStyle = colors.body;
  ctx.fillRect(x - 10, y - 2 + bobY, 20, 18);
  ctx.fillStyle = '#334155';
  ctx.fillRect(x - 8, y + 16 + bobY, 5, 12);
  ctx.fillRect(x + 3, y + 16 + bobY, 5, 12);

  ctx.fillStyle = colors.main;
  ctx.font = 'bold 10px ui-sans-serif, system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(`T${presence.slotId + 1}`, x, y - 30);

  const badge = presence.liveTask
    ? presence.liveTask.slice(0, 16)
    : presence.zone === 'lounge'
      ? 'idle'
      : presence.pipelineStage || presence.zone;
  const badgeWidth = Math.max(34, ctx.measureText(badge).width + 12);
  ctx.fillStyle = 'rgba(8,15,28,0.86)';
  ctx.strokeStyle = `${colors.main}66`;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(x - badgeWidth / 2, y - 47, badgeWidth, 16, 8);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = '#e2e8f0';
  ctx.font = '9px ui-sans-serif, system-ui, sans-serif';
  ctx.fillText(badge, x, y - 35.5);

  ctx.restore();
}

export default function OfficeWorld({
  presences,
  zones,
  events,
  selectedDesk,
  onDeskClick,
  onZoneClick,
  speechBubbles = [],
}: OfficeWorldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const positionsRef = useRef<Record<string, { x: number; y: number; tx: number; ty: number; zone: OfficeZone }>>({});
  const [hoveredDesk, setHoveredDesk] = useState<number | null>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const t = Date.now() / 1000;
    const now = Date.now();

    ctx.fillStyle = '#071019';
    ctx.fillRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, width, height);
    bg.addColorStop(0, 'rgba(8,145,178,0.10)');
    bg.addColorStop(0.6, 'rgba(139,92,246,0.06)');
    bg.addColorStop(1, 'rgba(14,165,233,0.02)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(255,255,255,0.03)';
    for (let gx = 0; gx <= width; gx += 42) {
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, height);
      ctx.stroke();
    }
    for (let gy = 0; gy <= height; gy += 42) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(width, gy);
      ctx.stroke();
    }

    (Object.keys(ZONE_LAYOUT) as OfficeZone[]).forEach((zoneId) => {
      const zoneRect = ZONE_LAYOUT[zoneId];
      const zone = zones.find((item) => item.id === zoneId);
      const x = zoneRect.x * width;
      const y = zoneRect.y * height;
      const w = zoneRect.w * width;
      const h = zoneRect.h * height;
      const occupied = zone?.occupancy ?? 0;
      const warningCount = zone?.warningCount ?? 0;
      const congestion = Math.min(occupied / 4, 1);
      const highlight = zoneId === 'recovery'
        ? 'rgba(248,113,113,0.12)'
        : zoneId === 'meeting'
          ? 'rgba(34,197,94,0.10)'
          : zoneId === 'memory'
            ? 'rgba(250,204,21,0.08)'
            : 'rgba(255,255,255,0.03)';

      ctx.fillStyle = highlight;
      ctx.strokeStyle = occupied > 0 ? 'rgba(148,163,184,0.24)' : 'rgba(255,255,255,0.08)';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 18);
      ctx.fill();
      ctx.stroke();

      if (congestion > 0 || warningCount > 0) {
        const heatColor = zoneId === 'recovery'
          ? `rgba(248,113,113,${0.12 + warningCount * 0.08})`
          : `rgba(34,211,238,${0.04 + congestion * 0.10})`;
        ctx.fillStyle = heatColor;
        ctx.beginPath();
        ctx.roundRect(x + 8, y + 8, w - 16, h - 16, 14);
        ctx.fill();
      }

      ctx.fillStyle = '#f8fafc';
      ctx.font = 'bold 12px ui-sans-serif, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(zone?.label ?? zoneId, x + 14, y + 22);
      ctx.fillStyle = 'rgba(255,255,255,0.45)';
      ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
      ctx.fillText(`${occupied} agents`, x + 14, y + 38);
      if (warningCount > 0) {
        ctx.fillStyle = 'rgba(252,165,165,0.92)';
        ctx.fillText(`${warningCount} alerts`, x + 14, y + 52);
      } else if (occupied >= 3) {
        ctx.fillStyle = 'rgba(125,211,252,0.86)';
        ctx.fillText('high traffic', x + 14, y + 52);
      }
    });

    DESK_SLOTS.forEach((desk) => {
      const anchor = getDeskAnchor(desk.id, width, height);
      const selected = selectedDesk === desk.id;
      const hovered = hoveredDesk === desk.id;
      ctx.fillStyle = selected ? 'rgba(34,211,238,0.18)' : hovered ? 'rgba(255,255,255,0.08)' : 'rgba(15,23,42,0.6)';
      ctx.strokeStyle = selected ? 'rgba(34,211,238,0.55)' : 'rgba(255,255,255,0.08)';
      ctx.beginPath();
      ctx.roundRect(anchor.x - 44, anchor.y - 28, 88, 56, 10);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(anchor.x - 13, anchor.y - 20, 26, 15);
      ctx.fillStyle = selected ? '#67e8f9' : 'rgba(255,255,255,0.30)';
      ctx.font = 'bold 10px ui-sans-serif, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(`T${desk.id + 1}`, anchor.x, anchor.y + 39);
    });

    const grouped = new Map<OfficeZone, OfficeAgentPresence[]>();
    presences.forEach((presence) => {
      const list = grouped.get(presence.zone) ?? [];
      list.push(presence);
      grouped.set(presence.zone, list);
    });

    presences.forEach((presence) => {
      const selected = selectedDesk === presence.slotId;
      let target = getDeskAnchor(presence.slotId, width, height);

      if (presence.zone !== 'desk') {
        const members = grouped.get(presence.zone) ?? [];
        const points = getZonePoints(presence.zone, width, height, members.length);
        const memberIndex = members.findIndex((member) => member.terminalId === presence.terminalId);
        target = points[Math.max(0, memberIndex)] ?? target;
      }

      const prev = positionsRef.current[presence.terminalId];
      if (!prev) {
        positionsRef.current[presence.terminalId] = {
          x: target.x,
          y: target.y,
          tx: target.x,
          ty: target.y,
          zone: presence.zone,
        };
      } else {
        prev.tx = target.x;
        prev.ty = target.y;
        prev.zone = presence.zone;
        prev.x += (prev.tx - prev.x) * 0.14;
        prev.y += (prev.ty - prev.y) * 0.14;
      }

      const point = positionsRef.current[presence.terminalId];
      const moving = Math.abs(point.tx - point.x) + Math.abs(point.ty - point.y) > 2.5;

      if (moving) {
        ctx.strokeStyle = presence.zone === 'recovery' ? 'rgba(248,113,113,0.30)' : 'rgba(125,211,252,0.20)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(point.x, point.y + 10);
        ctx.lineTo(point.tx, point.ty + 10);
        ctx.stroke();
      }

      drawAgent(ctx, presence, point.x, point.y, selected, t);

      if (moving) {
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = '9px ui-sans-serif, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('moving', point.x, point.y + 38);
      }
    });

    speechBubbles.forEach((bubble) => {
      if (now - bubble.createdAt > bubble.duration) return;
      const point = getDeskAnchor(bubble.deskId, width, height);
      const fadeFrom = bubble.duration * 0.65;
      const elapsed = now - bubble.createdAt;
      const opacity = elapsed > fadeFrom ? 1 - (elapsed - fadeFrom) / (bubble.duration - fadeFrom) : 1;
      const text = bubble.text.slice(0, 18);
      const tw = Math.max(56, ctx.measureText(text).width + 18);

      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.fillStyle = 'rgba(255,255,255,0.94)';
      ctx.beginPath();
      ctx.roundRect(point.x - tw / 2, point.y - 76, tw, 22, 8);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(point.x - 4, point.y - 54);
      ctx.lineTo(point.x, point.y - 46);
      ctx.lineTo(point.x + 4, point.y - 54);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = '#0f172a';
      ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(text, point.x, point.y - 61);
      ctx.restore();
    });

    events.slice(0, 3).forEach((event, index) => {
      const x = width - 270;
      const y = 28 + index * 48;
      ctx.fillStyle = 'rgba(8,15,28,0.84)';
      ctx.strokeStyle = 'rgba(255,255,255,0.08)';
      ctx.beginPath();
      ctx.roundRect(x, y, 240, 38, 10);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#f8fafc';
      ctx.font = 'bold 10px ui-sans-serif, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(event.title, x + 12, y + 15);
      ctx.fillStyle = 'rgba(255,255,255,0.45)';
      ctx.font = '9px ui-sans-serif, system-ui, sans-serif';
      ctx.fillText(event.subtitle.slice(0, 42), x + 12, y + 29);
    });

    rafRef.current = window.requestAnimationFrame(render);
  }, [events, hoveredDesk, onDeskClick, presences, selectedDesk, speechBubbles, zones]);

  useEffect(() => {
    rafRef.current = window.requestAnimationFrame(render);
    return () => window.cancelAnimationFrame(rafRef.current);
  }, [render]);

  const findDeskAtPoint = useCallback((mx: number, my: number, width: number, height: number) => {
    for (const desk of DESK_SLOTS) {
      const anchor = getDeskAnchor(desk.id, width, height);
      if (mx >= anchor.x - 48 && mx <= anchor.x + 48 && my >= anchor.y - 34 && my <= anchor.y + 34) {
        return desk.id;
      }
    }
    return null;
  }, []);

  const findZoneAtPoint = useCallback((mx: number, my: number, width: number, height: number) => {
    const ordered: OfficeZone[] = ['meeting', 'review', 'memory', 'git', 'lounge', 'recovery', 'user', 'desk'];
    for (const zone of ordered) {
      const rect = ZONE_LAYOUT[zone];
      const x = rect.x * width;
      const y = rect.y * height;
      const w = rect.w * width;
      const h = rect.h * height;
      if (mx >= x && mx <= x + w && my >= y && my <= y + h) {
        return zone;
      }
    }
    return null;
  }, []);

  const handleMouseMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const deskId = findDeskAtPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    setHoveredDesk(deskId);
  };

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const deskId = findDeskAtPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    if (deskId !== null) {
      onDeskClick(deskId);
      return;
    }

    const zone = findZoneAtPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    if (zone && onZoneClick) {
      onZoneClick(zone);
    }
  };

  return (
    <div ref={containerRef} className="h-full w-full">
      <canvas
        ref={canvasRef}
        className={`h-full w-full ${hoveredDesk !== null ? 'cursor-pointer' : 'cursor-default'}`}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredDesk(null)}
        onClick={handleClick}
      />
    </div>
  );
}
