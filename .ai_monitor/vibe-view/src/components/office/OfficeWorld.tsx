/**
 * ------------------------------------------------------------------------
 * 📄 파일명: OfficeWorld.tsx
 * 📝 설명: DeskRPG-Lite 2D 오피스 월드 렌더링.
 *          Canvas 2D로 야간 오피스 배경 + T1~T8 책상 + 픽셀아트 에이전트 아바타를 그립니다.
 *          에이전트 상태에 따라 idle/working 애니메이션, 말풍선, 호버 하이라이트를 표현합니다.
 * REVISION HISTORY:
 * - 2026-04-03 Claude: Phase 2 — 픽셀아트 아바타, 말풍선, 호버, 인월드 이벤트 애니메이션
 * - 2026-04-03 Claude: 초기 생성 — Canvas 2D 오피스 + 에이전트 아바타
 * ------------------------------------------------------------------------
 */

import { useRef, useEffect, useCallback, useState } from 'react';

// 에이전트 타입별 색상 + 픽셀 아바타 색상 매핑
const AGENT_COLORS: Record<string, { main: string; glow: string; label: string; body: string; hair: string }> = {
  claude:  { main: '#8b5cf6', glow: 'rgba(139,92,246,0.3)', label: 'Claude', body: '#7c3aed', hair: '#c4b5fd' },
  gemini:  { main: '#10b981', glow: 'rgba(16,185,129,0.3)', label: 'Gemini', body: '#059669', hair: '#6ee7b7' },
  codex:   { main: '#06b6d4', glow: 'rgba(6,182,212,0.3)',  label: 'Codex',  body: '#0891b2', hair: '#67e8f9' },
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

// 말풍선 데이터 타입
interface SpeechBubble {
  deskId: number;
  text: string;
  createdAt: number;
  duration: number; // ms
}

interface OfficeWorldProps {
  agentTerminals: Record<string, any>;
  selectedDesk: number;
  onDeskClick: (slotId: number) => void;
  // 인월드 이벤트용 — 외부에서 말풍선 주입
  speechBubbles?: SpeechBubble[];
}

// ── 픽셀아트 캐릭터 그리기 함수 (8x12 픽셀 스케일) ──
function drawPixelCharacter(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  bodyColor: string, hairColor: string,
  isWorking: boolean, t: number, scale: number = 2.5
) {
  const s = scale; // 픽셀 크기
  const ox = x - 4 * s; // 중심 정렬 (8px 너비의 절반)
  const oy = y - 12 * s; // 발 기준 → 머리 위로

  // 타이핑 애니메이션: 상체 미세 흔들림
  const bobY = isWorking ? Math.sin(t * 6) * 1.2 : 0;
  // 팔 각도 (타이핑 중 팔이 움직임)
  const armPhase = isWorking ? Math.floor(t * 4) % 2 : 0;

  ctx.save();

  // ── 머리카락 (상단) ──
  ctx.fillStyle = hairColor;
  ctx.fillRect(ox + 1*s, oy + bobY, 6*s, 2*s); // 머리카락 (위)
  ctx.fillRect(ox + 0*s, oy + 1*s + bobY, 8*s, 1*s); // 머리카락 (옆)

  // ── 얼굴 ──
  ctx.fillStyle = '#fcd9b6'; // 살색
  ctx.fillRect(ox + 1*s, oy + 2*s + bobY, 6*s, 3*s); // 얼굴
  // 눈
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(ox + 2*s, oy + 3*s + bobY, 1*s, 1*s); // 왼쪽 눈
  ctx.fillRect(ox + 5*s, oy + 3*s + bobY, 1*s, 1*s); // 오른쪽 눈

  // ── 몸통 ──
  ctx.fillStyle = bodyColor;
  ctx.fillRect(ox + 1*s, oy + 5*s + bobY, 6*s, 4*s); // 상체

  // ── 팔 (타이핑 애니메이션) ──
  ctx.fillStyle = bodyColor;
  if (isWorking) {
    // 왼팔 — 타이핑
    ctx.fillRect(ox - 1*s, oy + 5*s + bobY + (armPhase === 0 ? 0 : s), 2*s, 3*s);
    // 오른팔 — 타이핑 (반대 위상)
    ctx.fillRect(ox + 7*s, oy + 5*s + bobY + (armPhase === 1 ? 0 : s), 2*s, 3*s);
    // 손
    ctx.fillStyle = '#fcd9b6';
    ctx.fillRect(ox - 1*s, oy + 8*s + bobY + (armPhase === 0 ? 0 : s), 2*s, 1*s);
    ctx.fillRect(ox + 7*s, oy + 8*s + bobY + (armPhase === 1 ? 0 : s), 2*s, 1*s);
  } else {
    // idle — 팔 내림
    ctx.fillRect(ox - 1*s, oy + 5*s, 2*s, 4*s);
    ctx.fillRect(ox + 7*s, oy + 5*s, 2*s, 4*s);
    ctx.fillStyle = '#fcd9b6';
    ctx.fillRect(ox - 1*s, oy + 9*s, 2*s, 1*s);
    ctx.fillRect(ox + 7*s, oy + 9*s, 2*s, 1*s);
  }

  // ── 다리 ──
  ctx.fillStyle = '#334155'; // 바지색
  ctx.fillRect(ox + 1*s, oy + 9*s, 2.5*s, 3*s); // 왼다리
  ctx.fillRect(ox + 4.5*s, oy + 9*s, 2.5*s, 3*s); // 오른다리

  ctx.restore();
}

// ── 말풍선 그리기 ──
function drawSpeechBubble(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  text: string, opacity: number
) {
  ctx.save();
  ctx.globalAlpha = opacity;

  const maxWidth = 120;
  ctx.font = '10px "Inter", system-ui, sans-serif';
  const metrics = ctx.measureText(text);
  const textW = Math.min(metrics.width + 16, maxWidth);
  const textH = 22;
  const bx = x - textW / 2;
  const by = y - textH;

  // 말풍선 배경
  ctx.fillStyle = 'rgba(255,255,255,0.95)';
  ctx.beginPath();
  ctx.roundRect(bx, by, textW, textH, 6);
  ctx.fill();

  // 말풍선 꼬리
  ctx.beginPath();
  ctx.moveTo(x - 4, y);
  ctx.lineTo(x, y + 6);
  ctx.lineTo(x + 4, y);
  ctx.closePath();
  ctx.fill();

  // 텍스트
  ctx.fillStyle = '#1a1a2e';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text.length > 16 ? text.substring(0, 15) + '…' : text, x, by + textH / 2);

  ctx.restore();
}

// ── 진행률 바 그리기 ──
function drawProgressBar(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  progress: number, // 0~1
  color: string
) {
  const w = 40;
  const h = 4;
  const bx = x - w / 2;

  // 배경
  ctx.fillStyle = 'rgba(0,0,0,0.5)';
  ctx.beginPath();
  ctx.roundRect(bx, y, w, h, 2);
  ctx.fill();

  // 진행
  if (progress > 0) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(bx, y, w * Math.min(progress, 1), h, 2);
    ctx.fill();
  }
}

export default function OfficeWorld({ agentTerminals, selectedDesk, onDeskClick, speechBubbles = [] }: OfficeWorldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef(0);
  const [hoveredDesk, setHoveredDesk] = useState<number | null>(null);

  // 에이전트 상태 조회 헬퍼
  const getAgentInfo = useCallback((slotId: number) => {
    const termId = `terminal_${slotId + 1}`;
    const data = agentTerminals[termId];
    if (!data) return { cli: '', status: 'offline', pipeline: 'idle', liveTask: '' };
    return {
      cli: (data.cli || '').toLowerCase(),
      status: data.status || 'idle',
      pipeline: data.pipeline_stage || 'idle',
      liveTask: data.live_task || '',
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
    const t = Date.now() / 1000;
    const now = Date.now();

    // ── 배경: 야간 오피스 ──
    ctx.fillStyle = '#0a0a12';
    ctx.fillRect(0, 0, W, H);

    // 바닥 그리드 (미세한 타일 패턴)
    ctx.strokeStyle = 'rgba(255,255,255,0.02)';
    ctx.lineWidth = 1;
    const gridSize = 40;
    for (let gx = 0; gx < W; gx += gridSize) {
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
    }
    for (let gy = 0; gy < H; gy += gridSize) {
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke();
    }

    // 바닥 앰비언트 — 중앙 약간 밝은 원형 비네팅
    const grad = ctx.createRadialGradient(W * 0.4, H * 0.5, 0, W * 0.4, H * 0.5, W * 0.6);
    grad.addColorStop(0, 'rgba(59,130,246,0.03)');
    grad.addColorStop(1, 'transparent');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // 천장 네온 라인들
    const neonY = H * 0.08;
    ctx.shadowColor = '#3b82f6';
    ctx.shadowBlur = 15;
    ctx.strokeStyle = 'rgba(59,130,246,0.4)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(W * 0.05, neonY); ctx.lineTo(W * 0.55, neonY); ctx.stroke();
    // 두 번째 네온 라인 (보라)
    ctx.shadowColor = '#8b5cf6';
    ctx.strokeStyle = 'rgba(139,92,246,0.3)';
    ctx.beginPath(); ctx.moveTo(W * 0.60, neonY); ctx.lineTo(W * 0.90, neonY); ctx.stroke();
    ctx.shadowBlur = 0;

    // "VIBE OFFICE" 네온 사인 텍스트
    ctx.font = 'bold 14px "Inter", system-ui, sans-serif';
    ctx.fillStyle = `rgba(59,130,246,${0.5 + 0.2 * Math.sin(t * 2)})`;
    ctx.shadowColor = '#3b82f6';
    ctx.shadowBlur = 20;
    ctx.textAlign = 'left';
    ctx.fillText('VIBE OFFICE', W * 0.05, neonY - 8);
    ctx.shadowBlur = 0;

    // ── 책상 + 에이전트 렌더링 ──
    const deskW = 80;
    const deskH = 50;

    for (const desk of DESK_LAYOUT) {
      const x = desk.rx * W;
      const y = desk.ry * H;
      const agent = getAgentInfo(desk.id);
      const colors = AGENT_COLORS[agent.cli] || { main: '#555', glow: 'rgba(85,85,85,0.2)', label: '', body: '#555', hair: '#888' };
      const isActive = agent.status === 'running' || agent.status === 'started';
      const isSelected = selectedDesk === desk.id;
      const isHovered = hoveredDesk === desk.id;

      // 호버/선택 글로우
      if (isSelected || isHovered) {
        ctx.shadowColor = colors.main || '#3b82f6';
        ctx.shadowBlur = isSelected ? 25 : 15;
        ctx.fillStyle = isSelected
          ? (colors.glow || 'rgba(59,130,246,0.15)')
          : 'rgba(255,255,255,0.05)';
        ctx.fillRect(x - deskW/2 - 8, y - deskH/2 - 8, deskW + 16, deskH + 16);
        ctx.shadowBlur = 0;
      }

      // 책상 본체 — 모니터 + 키보드 디테일
      ctx.fillStyle = isSelected ? '#1e293b' : '#151520';
      ctx.strokeStyle = isActive ? colors.main : (isHovered ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.08)');
      ctx.lineWidth = isSelected ? 2 : 1;
      ctx.beginPath();
      ctx.roundRect(x - deskW/2, y - deskH/2, deskW, deskH, 6);
      ctx.fill();
      ctx.stroke();

      // 책상 위 모니터 (작은 사각형)
      ctx.fillStyle = isActive ? `${colors.main}44` : 'rgba(255,255,255,0.04)';
      ctx.fillRect(x - 12, y - deskH/2 + 6, 24, 16);
      ctx.strokeStyle = isActive ? colors.main : 'rgba(255,255,255,0.1)';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(x - 12, y - deskH/2 + 6, 24, 16);

      // 모니터 스크린 라인 (작업 중이면 깜빡임)
      if (isActive) {
        const lineCount = 3;
        for (let i = 0; i < lineCount; i++) {
          const ly = y - deskH/2 + 9 + i * 4;
          const lw = 8 + ((i + Math.floor(t * 3)) % 3) * 4;
          ctx.fillStyle = `${colors.main}88`;
          ctx.fillRect(x - 10, ly, lw, 1.5);
        }
      }

      // 키보드 (작은 직사각형)
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(x - 8, y + deskH/2 - 10, 16, 5);

      // 터미널 번호 라벨
      ctx.font = 'bold 10px "Inter", system-ui, sans-serif';
      ctx.fillStyle = isSelected ? colors.main : 'rgba(255,255,255,0.3)';
      ctx.textAlign = 'center';
      ctx.fillText(desk.label, x, y + deskH/2 + 14);

      // ── 픽셀아트 에이전트 아바타 ──
      if (agent.cli) {
        const avatarX = x;
        const avatarY = y - deskH/2 - 2; // 책상 위

        // 활성 상태 글로우 (아바타 아래 바닥)
        if (isActive) {
          ctx.shadowColor = colors.main;
          ctx.shadowBlur = 8 + 3 * Math.sin(t * 3);
          ctx.fillStyle = `${colors.glow}`;
          ctx.beginPath();
          ctx.ellipse(avatarX, avatarY + 2, 12, 4, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        }

        // 픽셀 캐릭터 그리기
        drawPixelCharacter(ctx, avatarX, avatarY, colors.body, colors.hair, isActive, t);

        // 에이전트 이름 (머리 위)
        ctx.font = 'bold 9px "Inter", system-ui, sans-serif';
        ctx.fillStyle = colors.main;
        ctx.textAlign = 'center';
        ctx.fillText(colors.label, avatarX, avatarY - 12 * 2.5 - 8);

        // 상태 버블 배지
        const pipelineText = agent.pipeline === 'modifying' ? '✏️ 수정중' :
                             agent.pipeline === 'analyzing' ? '🔍 분석중' :
                             agent.pipeline === 'verifying' ? '✅ 검증중' :
                             isActive ? '⚡ 작업중' : '💤 대기';

        // 상태 배지 (이름 아래)
        ctx.font = '8px "Inter", system-ui, sans-serif';
        const badgeW = ctx.measureText(pipelineText).width + 10;
        const badgeX = avatarX - badgeW / 2;
        const badgeY = avatarY - 12 * 2.5 - 4;
        ctx.fillStyle = isActive ? `${colors.main}33` : 'rgba(255,255,255,0.05)';
        ctx.beginPath();
        ctx.roundRect(badgeX, badgeY, badgeW, 13, 3);
        ctx.fill();
        ctx.fillStyle = isActive ? colors.main : 'rgba(255,255,255,0.4)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(pipelineText, avatarX, badgeY + 6.5);
        ctx.textBaseline = 'alphabetic';

        // 진행률 바 (working 상태일 때)
        if (isActive) {
          // 의사 진행률: 시간 기반 순환 (실제 진행률 API 없으면 시각적 효과용)
          const fakeProgress = (t * 0.05) % 1;
          drawProgressBar(ctx, avatarX, avatarY + 4, fakeProgress, colors.main);
        }
      } else {
        // 빈 책상 — 모니터 꺼짐 아이콘
        ctx.font = '16px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('🖥️', x, y - 2);
        ctx.font = '8px "Inter", system-ui, sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.15)';
        ctx.fillText('빈 자리', x, y + 12);
      }
    }

    // ── 특수 오브젝트 렌더링 ──
    for (const obj of SPECIAL_OBJECTS) {
      const ox = obj.rx * W;
      const oy = obj.ry * H;
      const objW = 70;
      const objH = 40;

      ctx.fillStyle = 'rgba(255,255,255,0.03)';
      ctx.strokeStyle = `${obj.color}33`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(ox - objW/2, oy - objH/2, objW, objH, 8);
      ctx.fill();
      ctx.stroke();

      ctx.font = '18px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(obj.emoji, ox, oy + 2);
      ctx.font = '9px "Inter", system-ui, sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.fillText(obj.label, ox, oy + objH/2 + 12);
    }

    // ── 말풍선 렌더링 ──
    for (const bubble of speechBubbles) {
      const desk = DESK_LAYOUT[bubble.deskId];
      if (!desk) continue;
      const elapsed = now - bubble.createdAt;
      if (elapsed > bubble.duration) continue;
      // 페이드 아웃
      const fadeStart = bubble.duration * 0.7;
      const opacity = elapsed > fadeStart
        ? 1 - (elapsed - fadeStart) / (bubble.duration - fadeStart)
        : 1;
      const bx = desk.rx * W;
      const by = desk.ry * H - deskH/2 - 12 * 2.5 - 24; // 아바타 머리 위
      drawSpeechBubble(ctx, bx, by, bubble.text, opacity);
    }

    // 다음 프레임
    animFrameRef.current = requestAnimationFrame(render);
  }, [agentTerminals, selectedDesk, hoveredDesk, getAgentInfo, speechBubbles]);

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

  // 마우스 이동 — 호버 감지
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = rect.width;
    const H = rect.height;
    const deskW = 80;
    const deskH = 50;

    let found: number | null = null;
    for (const desk of DESK_LAYOUT) {
      const dx = desk.rx * W;
      const dy = desk.ry * H;
      if (mx >= dx - deskW/2 - 10 && mx <= dx + deskW/2 + 10 &&
          my >= dy - deskH/2 - 40 && my <= dy + deskH/2 + 10) {
        found = desk.id;
        break;
      }
    }
    setHoveredDesk(found);
  };

  // 클릭 처리
  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = rect.width;
    const H = rect.height;
    const deskW = 80;
    const deskH = 50;

    for (const desk of DESK_LAYOUT) {
      const dx = desk.rx * W;
      const dy = desk.ry * H;
      if (mx >= dx - deskW/2 - 10 && mx <= dx + deskW/2 + 10 &&
          my >= dy - deskH/2 - 40 && my <= dy + deskH/2 + 10) {
        onDeskClick(desk.id);
        return;
      }
    }
  };

  return (
    <div ref={containerRef} className="w-full h-full relative">
      <canvas
        ref={canvasRef}
        className={`w-full h-full ${hoveredDesk !== null ? 'cursor-pointer' : 'cursor-default'}`}
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredDesk(null)}
      />
    </div>
  );
}
