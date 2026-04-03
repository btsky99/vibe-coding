/**
 * ------------------------------------------------------------------------
 * 📄 파일명: OfficeWorld.tsx
 * 📝 설명: DeskRPG-Lite 2D 오피스 월드 렌더링.
 *          Canvas 2D로 야간 오피스 배경 + T1~T8 책상 + 에이전트 아바타를 그립니다.
 *          agentTerminals 데이터를 기반으로 에이전트 상태를 시각적으로 표현합니다.
 * REVISION HISTORY:
 * - 2026-04-03 Claude: 초기 생성 — Canvas 2D 오피스 + 에이전트 아바타
 * ------------------------------------------------------------------------
 */

import { useRef, useEffect, useCallback } from 'react';

// 에이전트 타입별 색상 매핑
const AGENT_COLORS: Record<string, { main: string; glow: string; label: string }> = {
  claude:  { main: '#8b5cf6', glow: 'rgba(139,92,246,0.3)', label: 'Claude' },
  gemini:  { main: '#10b981', glow: 'rgba(16,185,129,0.3)', label: 'Gemini' },
  codex:   { main: '#06b6d4', glow: 'rgba(6,182,212,0.3)',  label: 'Codex' },
};

// 책상 배치: 2행 4열 오피스 레이아웃 (비율 기반 좌표)
const DESK_LAYOUT = [
  { id: 0, label: 'T1', rx: 0.12, ry: 0.28 },
  { id: 1, label: 'T2', rx: 0.30, ry: 0.28 },
  { id: 2, label: 'T3', rx: 0.48, ry: 0.28 },
  { id: 3, label: 'T4', rx: 0.66, ry: 0.28 },
  { id: 4, label: 'T5', rx: 0.12, ry: 0.62 },
  { id: 5, label: 'T6', rx: 0.30, ry: 0.62 },
  { id: 6, label: 'T7', rx: 0.48, ry: 0.62 },
  { id: 7, label: 'T8', rx: 0.66, ry: 0.62 },
];

// 특수 오브젝트: 유저 책상, 회의실, 휴게실
const SPECIAL_OBJECTS = [
  { id: 'user', label: '내 책상', rx: 0.40, ry: 0.88, color: '#f59e0b', emoji: '👤' },
  { id: 'meeting', label: '회의실', rx: 0.82, ry: 0.28, color: '#ef4444', emoji: '🗓' },
  { id: 'lounge', label: '휴게실', rx: 0.82, ry: 0.62, color: '#6366f1', emoji: '☕' },
];

interface OfficeWorldProps {
  agentTerminals: Record<string, any>;
  selectedDesk: number;
  onDeskClick: (slotId: number) => void;
}

export default function OfficeWorld({ agentTerminals, selectedDesk, onDeskClick }: OfficeWorldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef(0);

  // 에이전트 상태 조회 헬퍼
  const getAgentInfo = useCallback((slotId: number) => {
    const termId = `terminal_${slotId + 1}`;
    const data = agentTerminals[termId];
    if (!data) return { cli: '', status: 'offline', pipeline: 'idle' };
    return {
      cli: (data.cli || '').toLowerCase(),
      status: data.status || 'idle',
      pipeline: data.pipeline_stage || 'idle',
    };
  }, [agentTerminals]);

  // 렌더 루프
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;
    const t = Date.now() / 1000; // 애니메이션 시간

    // ── 배경: 야간 오피스 ──
    // 바닥
    ctx.fillStyle = '#0a0a12';
    ctx.fillRect(0, 0, W, H);

    // 바닥 그리드 (미세한 타일 패턴)
    ctx.strokeStyle = 'rgba(255,255,255,0.02)';
    ctx.lineWidth = 1;
    const gridSize = 40;
    for (let x = 0; x < W; x += gridSize) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += gridSize) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    // 천장 네온 라인 (위쪽)
    const neonY = H * 0.08;
    ctx.shadowColor = '#3b82f6';
    ctx.shadowBlur = 15;
    ctx.strokeStyle = 'rgba(59,130,246,0.4)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(W * 0.05, neonY); ctx.lineTo(W * 0.75, neonY); ctx.stroke();
    ctx.shadowBlur = 0;

    // "VIBE OFFICE" 네온 사인 텍스트
    ctx.font = 'bold 14px "Inter", system-ui, sans-serif';
    ctx.fillStyle = `rgba(59,130,246,${0.5 + 0.2 * Math.sin(t * 2)})`;
    ctx.shadowColor = '#3b82f6';
    ctx.shadowBlur = 20;
    ctx.fillText('VIBE OFFICE', W * 0.05, neonY - 8);
    ctx.shadowBlur = 0;

    // ── 책상 렌더링 ──
    const deskW = 80;
    const deskH = 50;

    for (const desk of DESK_LAYOUT) {
      const x = desk.rx * W;
      const y = desk.ry * H;
      const agent = getAgentInfo(desk.id);
      const colors = AGENT_COLORS[agent.cli] || { main: '#555', glow: 'rgba(85,85,85,0.2)', label: '' };
      const isActive = agent.status === 'running' || agent.status === 'started';
      const isSelected = selectedDesk === desk.id;

      // 선택 글로우
      if (isSelected) {
        ctx.shadowColor = colors.main || '#3b82f6';
        ctx.shadowBlur = 25;
        ctx.fillStyle = `${colors.glow || 'rgba(59,130,246,0.15)'}`;
        ctx.fillRect(x - deskW/2 - 8, y - deskH/2 - 8, deskW + 16, deskH + 16);
        ctx.shadowBlur = 0;
      }

      // 책상 본체
      ctx.fillStyle = isSelected ? '#1e293b' : '#151520';
      ctx.strokeStyle = isActive ? colors.main : 'rgba(255,255,255,0.08)';
      ctx.lineWidth = isSelected ? 2 : 1;
      // 라운드 사각형
      const r = 6;
      ctx.beginPath();
      ctx.moveTo(x - deskW/2 + r, y - deskH/2);
      ctx.lineTo(x + deskW/2 - r, y - deskH/2);
      ctx.quadraticCurveTo(x + deskW/2, y - deskH/2, x + deskW/2, y - deskH/2 + r);
      ctx.lineTo(x + deskW/2, y + deskH/2 - r);
      ctx.quadraticCurveTo(x + deskW/2, y + deskH/2, x + deskW/2 - r, y + deskH/2);
      ctx.lineTo(x - deskW/2 + r, y + deskH/2);
      ctx.quadraticCurveTo(x - deskW/2, y + deskH/2, x - deskW/2, y + deskH/2 - r);
      ctx.lineTo(x - deskW/2, y - deskH/2 + r);
      ctx.quadraticCurveTo(x - deskW/2, y - deskH/2, x - deskW/2 + r, y - deskH/2);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      // 터미널 번호 라벨
      ctx.font = 'bold 10px "Inter", system-ui, sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.textAlign = 'center';
      ctx.fillText(desk.label, x, y + deskH/2 + 14);

      // ── 에이전트 아바타 ──
      if (agent.cli) {
        // 아바타 원형 (책상 위)
        const avatarY = y - 6;
        const avatarR = 14;

        // 활성 상태 글로우
        if (isActive) {
          ctx.shadowColor = colors.main;
          ctx.shadowBlur = 12 + 4 * Math.sin(t * 3);
        }

        // 아바타 원
        ctx.beginPath();
        ctx.arc(x, avatarY, avatarR, 0, Math.PI * 2);
        ctx.fillStyle = colors.main;
        ctx.fill();
        ctx.shadowBlur = 0;

        // 아바타 내부 이니셜
        ctx.font = 'bold 12px "Inter", system-ui, sans-serif';
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(colors.label[0] || '?', x, avatarY);
        ctx.textBaseline = 'alphabetic';

        // 에이전트 이름
        ctx.font = '9px "Inter", system-ui, sans-serif';
        ctx.fillStyle = colors.main;
        ctx.fillText(colors.label, x, avatarY - avatarR - 4);

        // 상태 버블
        const statusEmoji = agent.pipeline === 'modifying' ? '✏️' :
                           agent.pipeline === 'analyzing' ? '🔍' :
                           agent.pipeline === 'verifying' ? '✅' :
                           isActive ? '⚡' : '💤';

        ctx.font = '12px sans-serif';
        ctx.fillText(statusEmoji, x + avatarR + 4, avatarY - 2);

        // Working 상태일 때 타이핑 도트 애니메이션
        if (isActive) {
          const dots = '.'.repeat(1 + Math.floor(t * 2) % 3);
          ctx.font = '10px monospace';
          ctx.fillStyle = 'rgba(255,255,255,0.4)';
          ctx.fillText(dots, x + avatarR + 16, avatarY - 2);
        }
      } else {
        // 에이전트 없음 — 빈 책상 아이콘
        ctx.font = '16px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('🖥️', x, y);
      }
    }

    // ── 특수 오브젝트 렌더링 ──
    for (const obj of SPECIAL_OBJECTS) {
      const x = obj.rx * W;
      const y = obj.ry * H;
      const objW = 70;
      const objH = 40;

      // 배경
      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      ctx.strokeStyle = `${obj.color}33`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x - objW/2, y - objH/2, objW, objH, 8);
      ctx.fill();
      ctx.stroke();

      // 이모지 + 라벨
      ctx.font = '18px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(obj.emoji, x, y + 2);
      ctx.font = '9px "Inter", system-ui, sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.fillText(obj.label, x, y + objH/2 + 12);
    }

    // 다음 프레임
    animFrameRef.current = requestAnimationFrame(render);
  }, [agentTerminals, selectedDesk, getAgentInfo]);

  // Canvas 초기화 + 애니메이션 루프
  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [render]);

  // 리사이즈 대응
  useEffect(() => {
    const handleResize = () => {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = requestAnimationFrame(render);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [render]);

  // 클릭 처리 — 어느 책상을 클릭했는지 판별
  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const rect = container.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = rect.width;
    const H = rect.height;
    const deskW = 80;
    const deskH = 50;

    for (const desk of DESK_LAYOUT) {
      const x = desk.rx * W;
      const y = desk.ry * H;
      if (mx >= x - deskW/2 - 10 && mx <= x + deskW/2 + 10 &&
          my >= y - deskH/2 - 10 && my <= y + deskH/2 + 10) {
        onDeskClick(desk.id);
        return;
      }
    }
  };

  return (
    <div ref={containerRef} className="w-full h-full relative">
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-pointer"
        onClick={handleClick}
      />
    </div>
  );
}
