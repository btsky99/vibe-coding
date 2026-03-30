/**
 * ------------------------------------------------------------------------
 * 파일명: AgentMonitorPanel.tsx
 * 설명: Paperclip 스타일 에이전트 오케스트레이션 조직도 뷰.
 *       Dispatcher(사용자)를 루트로 각 에이전트가 트리 구조로 연결되며,
 *       실시간 상태(working/idle/offline), 현재 태스크, 하트비트를 표시.
 *       SVG 연결선으로 계층 관계를 시각화.
 *
 * REVISION HISTORY:
 * - 2026-03-31 Claude: Paperclip 스타일 조직도(org chart) UI로 전면 리디자인
 *   - 카드 나열 → SVG 연결선 + 트리 계층 구조로 변경
 *   - Dispatcher 루트 노드 + 에이전트 자식 노드 레이아웃
 *   - 상태별 글로우 효과 + 애니메이션 펄스 추가
 * - 2026-03-30 Claude: 최초 작성 — Paperclip 오케스트레이션 전환
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Zap, Loader2, PowerOff } from 'lucide-react';
import { API_BASE } from '../../constants';

// 에이전트 하트비트 데이터 타입
interface AgentBeat {
  agent_id: string;
  status: string;     // working | idle | offline
  last_beat: string;  // ISO timestamp
  current_task: string | null;
  beat_count: number;
  config?: string;
}

// 에이전트 역할 정의 — Paperclip 스타일 조직도 노드에 표시
const AGENT_ROLES: Record<string, { label: string; role: string; icon: string }> = {
  'claude-T1': { label: 'Claude', role: '정밀 로직 · 프론트엔드', icon: '⚡' },
  'gemini-T2': { label: 'Gemini', role: '설계 · 오케스트레이션', icon: '🌐' },
  'codex-T3':  { label: 'Codex',  role: '샌드박스 · 테스트',     icon: '🔧' },
  claude:      { label: 'Claude', role: '정밀 로직',             icon: '⚡' },
  gemini:      { label: 'Gemini', role: '설계 · 연구',           icon: '🌐' },
  codex:       { label: 'Codex',  role: '실행 · 검증',           icon: '🔧' },
};

// 상태별 색상
const STATUS_COLORS: Record<string, { dot: string; glow: string; border: string; text: string }> = {
  working: {
    dot: '#22c55e',
    glow: 'rgba(34, 197, 94, 0.4)',
    border: 'rgba(34, 197, 94, 0.35)',
    text: '#4ade80',
  },
  idle: {
    dot: '#eab308',
    glow: 'rgba(234, 179, 8, 0.25)',
    border: 'rgba(234, 179, 8, 0.25)',
    text: '#facc15',
  },
  offline: {
    dot: '#ef4444',
    glow: 'rgba(239, 68, 68, 0.15)',
    border: 'rgba(255, 255, 255, 0.08)',
    text: '#f87171',
  },
};

function relativeTime(iso?: string): string {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return '방금';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

// 터미널 ID 추출 (claude-T1 → T1)
function terminalId(agentId: string): string {
  const m = agentId.match(/T(\d+)/i);
  return m ? `T${m[1]}` : '';
}

export default function AgentMonitorPanel() {
  const [agents, setAgents] = useState<AgentBeat[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // 컨테이너 너비 감지 — 반응형 레이아웃
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // 에이전트 상태 폴링 (5초)
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agents/status`);
        if (res.ok && active) {
          const data = await res.json();
          setAgents(Array.isArray(data) ? data : []);
        }
      } catch {
        // 연결 실패 시 무시
      } finally {
        if (active) setLoading(false);
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // 수동 하트비트 트리거
  const handleTrigger = useCallback(async (agentId: string) => {
    setTriggeringId(agentId);
    try {
      await fetch(`${API_BASE}/api/agents/${agentId}/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch {
      // 무시
    } finally {
      setTimeout(() => setTriggeringId(null), 1500);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-white/30">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
        <span className="text-xs">에이전트 상태 로딩...</span>
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="p-4 text-center">
        <PowerOff className="w-8 h-8 mx-auto text-white/20 mb-2" />
        <p className="text-xs text-white/40">등록된 에이전트 없음</p>
        <p className="text-[10px] text-white/25 mt-1">
          하트비트 러너를 시작하세요:<br />
          <code className="text-primary/60">python scripts/hive_heartbeat.py --agent claude-T1</code>
        </p>
      </div>
    );
  }

  const workingCount = agents.filter(a => a.status === 'working').length;

  // ── 레이아웃 계산 ──
  // 사이드바 폭이 좁으면(< 350px) 세로 레이아웃으로 전환
  const isNarrow = containerWidth > 0 && containerWidth < 350;

  // 루트(Dispatcher) 노드 위치
  const rootW = 140, rootH = 56;
  // 자식 노드 크기
  const nodeW = 150, nodeH = 90;
  // 간격
  const gapX = 16;
  const totalChildrenWidth = agents.length * nodeW + (agents.length - 1) * gapX;
  const svgWidth = Math.max(totalChildrenWidth + 40, rootW + 40);
  // 좁은 모드에서는 세로 배치
  const svgHeight = isNarrow
    ? 80 + agents.length * (nodeH + 50) + 20
    : 80 + nodeH + 40;

  // 루트 노드 중앙
  const rootX = svgWidth / 2 - rootW / 2;
  const rootY = 10;
  const rootCenterX = rootX + rootW / 2;
  const rootBottomY = rootY + rootH;

  // 자식 노드 좌표 계산
  const childStartX = svgWidth / 2 - totalChildrenWidth / 2;
  const childY = isNarrow ? 0 : rootBottomY + 50;

  return (
    <div ref={containerRef} className="flex flex-col gap-2 p-2 overflow-auto">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[11px] font-bold text-white/80">에이전트 오케스트레이션</span>
        <span className="text-[10px] text-white/30">
          {workingCount}/{agents.length} 활성
        </span>
      </div>

      {/* 조직도 SVG */}
      <div className="flex justify-center overflow-x-auto">
        <svg
          width={isNarrow ? '100%' : svgWidth}
          height={svgHeight}
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="flex-shrink-0"
        >
          {/* 그라디언트 정의 */}
          <defs>
            <filter id="glow-green">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="glow-yellow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* ── 루트 노드: Dispatcher ── */}
          <g>
            <rect
              x={rootX} y={rootY}
              width={rootW} height={rootH}
              rx={10}
              fill="rgba(255,255,255,0.06)"
              stroke="rgba(255,255,255,0.15)"
              strokeWidth={1.5}
            />
            {/* 아이콘 */}
            <text
              x={rootCenterX - 28} y={rootY + 33}
              fontSize={16}
              textAnchor="middle"
            >🏠</text>
            {/* 타이틀 */}
            <text
              x={rootCenterX} y={rootY + 24}
              textAnchor="middle"
              fill="white"
              fontSize={12}
              fontWeight="bold"
            >Dispatcher</text>
            <text
              x={rootCenterX} y={rootY + 42}
              textAnchor="middle"
              fill="rgba(255,255,255,0.4)"
              fontSize={9}
            >태스크 분배 · 관제</text>
          </g>

          {/* ── 연결선 + 자식 노드 ── */}
          {agents.map((agent, i) => {
            const role = AGENT_ROLES[agent.agent_id] ?? { label: agent.agent_id, role: '', icon: '🤖' };
            const colors = STATUS_COLORS[agent.status] ?? STATUS_COLORS.offline;
            const tid = terminalId(agent.agent_id);
            const isTriggering = triggeringId === agent.agent_id;

            // 좁은 모드: 세로 배치
            const cx = isNarrow
              ? svgWidth / 2 - nodeW / 2
              : childStartX + i * (nodeW + gapX);
            const cy = isNarrow
              ? rootBottomY + 50 + i * (nodeH + 50)
              : childY;
            const nodeCenterX = cx + nodeW / 2;
            const nodeTopY = cy;

            return (
              <g key={agent.agent_id}>
                {/* 연결선: 루트 → 자식 */}
                <path
                  d={isNarrow
                    ? `M ${rootCenterX} ${rootBottomY}
                       L ${rootCenterX} ${rootBottomY + 20}
                       L ${nodeCenterX} ${rootBottomY + 20}
                       L ${nodeCenterX} ${nodeTopY}`
                    : `M ${rootCenterX} ${rootBottomY}
                       L ${rootCenterX} ${rootBottomY + 25}
                       L ${nodeCenterX} ${rootBottomY + 25}
                       L ${nodeCenterX} ${nodeTopY}`
                  }
                  fill="none"
                  stroke={colors.border}
                  strokeWidth={1.5}
                  strokeDasharray={agent.status === 'offline' ? '4 3' : 'none'}
                />

                {/* 에이전트 카드 배경 */}
                <rect
                  x={cx} y={cy}
                  width={nodeW} height={nodeH}
                  rx={10}
                  fill="rgba(255,255,255,0.04)"
                  stroke={colors.border}
                  strokeWidth={1.5}
                  className="cursor-pointer"
                />
                {/* 상태 글로우 상단 바 */}
                <rect
                  x={cx} y={cy}
                  width={nodeW} height={3}
                  rx={1}
                  fill={colors.dot}
                  opacity={agent.status === 'working' ? 0.8 : 0.3}
                />

                {/* 터미널 ID 배지 */}
                {tid && (
                  <>
                    <rect
                      x={cx + 6} y={cy + 10}
                      width={22} height={14}
                      rx={3}
                      fill="rgba(255,255,255,0.08)"
                    />
                    <text
                      x={cx + 17} y={cy + 20}
                      textAnchor="middle"
                      fill="rgba(255,255,255,0.5)"
                      fontSize={8}
                      fontWeight="bold"
                    >{tid}</text>
                  </>
                )}

                {/* 아이콘 */}
                <text
                  x={cx + nodeW - 20} y={cy + 22}
                  fontSize={14}
                  textAnchor="middle"
                >{role.icon}</text>

                {/* 에이전트 이름 */}
                <text
                  x={cx + nodeW / 2} y={cy + 38}
                  textAnchor="middle"
                  fill="white"
                  fontSize={12}
                  fontWeight="bold"
                >{role.label}</text>

                {/* 역할 */}
                <text
                  x={cx + nodeW / 2} y={cy + 52}
                  textAnchor="middle"
                  fill="rgba(255,255,255,0.35)"
                  fontSize={8}
                >{role.role}</text>

                {/* 상태 표시등 + 텍스트 */}
                <circle
                  cx={cx + 14} cy={cy + 68}
                  r={3.5}
                  fill={colors.dot}
                  filter={agent.status === 'working' ? 'url(#glow-green)' : undefined}
                >
                  {agent.status === 'working' && (
                    <animate
                      attributeName="opacity"
                      values="1;0.4;1"
                      dur="2s"
                      repeatCount="indefinite"
                    />
                  )}
                </circle>
                <text
                  x={cx + 22} y={cy + 71}
                  fill={colors.text}
                  fontSize={8}
                  fontWeight="600"
                >{agent.status.toUpperCase()}</text>

                {/* 마지막 하트비트 시간 */}
                <text
                  x={cx + nodeW - 8} y={cy + 71}
                  textAnchor="end"
                  fill="rgba(255,255,255,0.2)"
                  fontSize={7}
                >{relativeTime(agent.last_beat)}</text>

                {/* 현재 태스크 — 카드 아래에 작게 표시 */}
                {agent.current_task && (
                  <text
                    x={cx + nodeW / 2} y={cy + nodeH + 12}
                    textAnchor="middle"
                    fill="rgba(255,255,255,0.3)"
                    fontSize={7}
                  >
                    {agent.current_task.length > 25
                      ? agent.current_task.slice(0, 25) + '…'
                      : agent.current_task}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* 하단: 카드 리스트 (상세 정보 + 트리거 버튼) */}
      <div className="flex flex-col gap-1.5 mt-1">
        {agents.map((agent) => {
          const role = AGENT_ROLES[agent.agent_id] ?? { label: agent.agent_id, role: '', icon: '🤖' };
          const colors = STATUS_COLORS[agent.status] ?? STATUS_COLORS.offline;
          const isTriggering = triggeringId === agent.agent_id;
          const tid = terminalId(agent.agent_id);

          return (
            <div
              key={agent.agent_id}
              className="flex items-center justify-between rounded-md px-2.5 py-1.5 transition-colors"
              style={{
                background: 'rgba(255,255,255,0.03)',
                borderLeft: `3px solid ${colors.dot}`,
              }}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs">{role.icon}</span>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-bold text-white/85">{role.label}</span>
                    {tid && (
                      <span className="text-[8px] text-white/30 bg-white/5 px-1 rounded">{tid}</span>
                    )}
                    <span className="text-[9px] font-semibold" style={{ color: colors.text }}>
                      {agent.status.toUpperCase()}
                    </span>
                  </div>
                  {agent.current_task && (
                    <p className="text-[9px] text-white/35 truncate max-w-[180px]">
                      {agent.current_task}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-[8px] text-white/20">{relativeTime(agent.last_beat)}</span>
                <button
                  onClick={() => handleTrigger(agent.agent_id)}
                  disabled={isTriggering}
                  className="rounded p-1 hover:bg-white/10 transition-colors disabled:opacity-30"
                  title="하트비트 트리거"
                >
                  {isTriggering ? (
                    <Loader2 className="w-3 h-3 animate-spin text-primary" />
                  ) : (
                    <Zap className="w-3 h-3 text-white/40 hover:text-primary" />
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
