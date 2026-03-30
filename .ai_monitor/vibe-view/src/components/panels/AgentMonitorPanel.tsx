/**
 * ------------------------------------------------------------------------
 * 파일명: AgentMonitorPanel.tsx
 * 설명: Paperclip 스타일 에이전트 오케스트레이션 조직도 뷰.
 *       Dispatcher(사용자)를 루트로 각 에이전트가 트리 구조로 연결되며,
 *       실시간 상태(working/idle/offline), 현재 태스크, 하트비트를 표시.
 *       HTML/CSS 기반 카드형 조직도로 Paperclip UI를 충실히 재현.
 *
 * REVISION HISTORY:
 * - 2026-03-31 Claude: Paperclip 정식 UI 모방 — HTML/CSS 카드형 조직도로 전면 재작성
 *   - SVG 기반 → HTML div + CSS tree connector로 전환
 *   - 카드 디자인: 아이콘 + 역할명 + 설명 + 상태 dot + 에이전트명 (Paperclip 동일)
 *   - 계층 연결선: CSS ::before/::after 수직/수평선
 * - 2026-03-31 Claude: Paperclip 스타일 조직도(org chart) UI로 전면 리디자인
 * - 2026-03-30 Claude: 최초 작성 — Paperclip 오케스트레이션 전환
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useCallback } from 'react';
import { Zap, Loader2, PowerOff, Code2, Globe, Wrench, Home } from 'lucide-react';
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
const AGENT_ROLES: Record<string, {
  label: string;
  title: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
}> = {
  'claude-T1': {
    label: 'Claude',
    title: 'Engineer',
    description: 'Founding Full-Stack Engineer',
    Icon: Code2,
  },
  'gemini-T2': {
    label: 'Gemini',
    title: 'Architect',
    description: 'Design & Orchestration',
    Icon: Globe,
  },
  'codex-T3': {
    label: 'Codex',
    title: 'QA Engineer',
    description: 'Sandbox & Validation',
    Icon: Wrench,
  },
  claude: {
    label: 'Claude',
    title: 'Engineer',
    description: 'Precision Logic',
    Icon: Code2,
  },
  gemini: {
    label: 'Gemini',
    title: 'Architect',
    description: 'Research & Design',
    Icon: Globe,
  },
  codex: {
    label: 'Codex',
    title: 'QA Engineer',
    description: 'Execution & Verify',
    Icon: Wrench,
  },
};

// 상태별 색상 — Paperclip 스타일 (노란 dot이 기본)
const STATUS_COLORS: Record<string, { dot: string; glow: string; border: string }> = {
  working: {
    dot: '#22c55e',
    glow: '0 0 8px rgba(34, 197, 94, 0.6)',
    border: 'rgba(34, 197, 94, 0.3)',
  },
  idle: {
    dot: '#eab308',
    glow: '0 0 6px rgba(234, 179, 8, 0.4)',
    border: 'rgba(234, 179, 8, 0.2)',
  },
  offline: {
    dot: '#6b7280',
    glow: 'none',
    border: 'rgba(255, 255, 255, 0.06)',
  },
};

function relativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return 'now';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

// ── Paperclip 스타일 개별 에이전트 카드 ──
function AgentCard({
  agent,
  onTrigger,
  isTriggering,
}: {
  agent: AgentBeat;
  onTrigger: (id: string) => void;
  isTriggering: boolean;
}) {
  const role = AGENT_ROLES[agent.agent_id] ?? {
    label: agent.agent_id,
    title: 'Agent',
    description: '',
    Icon: Wrench,
  };
  const colors = STATUS_COLORS[agent.status] ?? STATUS_COLORS.offline;
  const { Icon } = role;

  return (
    <div
      className="org-card"
      style={{
        background: 'rgba(255, 255, 255, 0.04)',
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: '16px 18px 14px',
        minWidth: 180,
        maxWidth: 210,
        cursor: 'pointer',
        transition: 'border-color 0.3s, box-shadow 0.3s',
        position: 'relative',
      }}
      onClick={() => onTrigger(agent.agent_id)}
      title={`클릭하여 하트비트 트리거 (${agent.agent_id})`}
    >
      {/* 트리거 로딩 오버레이 */}
      {isTriggering && (
        <div style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 12,
          background: 'rgba(0,0,0,0.4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2,
        }}>
          <Loader2 className="w-5 h-5 animate-spin text-white/60" />
        </div>
      )}

      {/* 아이콘 + 역할명 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Icon className="w-4 h-4" style={{ color: 'rgba(255,255,255,0.5)' }} />
        <span style={{
          fontSize: 15,
          fontWeight: 700,
          color: 'white',
          letterSpacing: '-0.01em',
        }}>
          {role.title}
        </span>
      </div>

      {/* 설명 */}
      <div style={{
        fontSize: 11,
        color: 'rgba(255,255,255,0.35)',
        marginBottom: 6,
        lineHeight: 1.3,
      }}>
        {role.description}
      </div>

      {/* 상태 dot + 에이전트명 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: colors.dot,
            boxShadow: colors.glow,
            display: 'inline-block',
            flexShrink: 0,
            animation: agent.status === 'working' ? 'pulse-dot 2s ease-in-out infinite' : 'none',
          }}
        />
        <span style={{
          fontSize: 11,
          color: 'rgba(255,255,255,0.45)',
        }}>
          {role.label}
        </span>
        {agent.last_beat && (
          <span style={{
            fontSize: 9,
            color: 'rgba(255,255,255,0.2)',
            marginLeft: 'auto',
          }}>
            {relativeTime(agent.last_beat)}
          </span>
        )}
      </div>

      {/* 현재 태스크 표시 */}
      {agent.current_task && (
        <div style={{
          marginTop: 8,
          padding: '4px 8px',
          borderRadius: 6,
          background: 'rgba(255,255,255,0.04)',
          fontSize: 9,
          color: 'rgba(255,255,255,0.3)',
          lineHeight: 1.4,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {agent.current_task}
        </div>
      )}
    </div>
  );
}

// ── Paperclip 스타일 Dispatcher (루트) 카드 ──
function DispatcherCard() {
  return (
    <div
      style={{
        background: 'rgba(255, 255, 255, 0.05)',
        border: '1px solid rgba(255, 255, 255, 0.1)',
        borderRadius: 12,
        padding: '14px 20px 12px',
        minWidth: 160,
        display: 'inline-block',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <Home className="w-4 h-4" style={{ color: 'rgba(255,255,255,0.5)' }} />
        <span style={{
          fontSize: 15,
          fontWeight: 700,
          color: 'white',
          letterSpacing: '-0.01em',
        }}>
          Dispatcher
        </span>
      </div>
      <div style={{
        fontSize: 11,
        color: 'rgba(255,255,255,0.35)',
        marginBottom: 4,
      }}>
        Task Orchestrator
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: '#22c55e',
          boxShadow: '0 0 6px rgba(34, 197, 94, 0.5)',
          display: 'inline-block',
        }} />
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)' }}>
          User
        </span>
      </div>
    </div>
  );
}

// ── 메인 컴포넌트: Paperclip 스타일 조직도 ──
export default function AgentMonitorPanel() {
  const [agents, setAgents] = useState<AgentBeat[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);

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

  return (
    <div className="flex flex-col gap-3 p-3 overflow-auto">
      {/* 글로벌 스타일 — 펄스 애니메이션 + 트리 연결선 */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        .org-card:hover {
          border-color: rgba(255, 255, 255, 0.2) !important;
          box-shadow: 0 0 20px rgba(255, 255, 255, 0.03);
        }
        /* Paperclip 스타일 트리 연결선 */
        .org-tree {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
        }
        /* 루트 → 중간 수직선 */
        .org-tree-trunk {
          width: 1px;
          height: 32px;
          background: rgba(255, 255, 255, 0.1);
        }
        /* 자식 노드 행 — 수평 연결 */
        .org-children {
          display: flex;
          justify-content: center;
          gap: 16px;
          position: relative;
          padding-top: 32px;
        }
        /* 수평 연결 바 (자식 노드들 위) */
        .org-children::before {
          content: '';
          position: absolute;
          top: 0;
          left: 50%;
          transform: translateX(-50%);
          height: 1px;
          background: rgba(255, 255, 255, 0.1);
          /* 너비는 JS로 계산 */
        }
        /* 각 자식에서 위로 올라가는 수직선 */
        .org-child-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .org-child-stem {
          width: 1px;
          height: 32px;
          background: rgba(255, 255, 255, 0.1);
        }
      `}</style>

      {/* 헤더 */}
      <div className="flex items-center justify-between px-1">
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: 'rgba(255, 255, 255, 0.7)',
          letterSpacing: '0.02em',
        }}>
          Agent Orchestration
        </span>
        <span style={{
          fontSize: 10,
          color: 'rgba(255, 255, 255, 0.25)',
        }}>
          {workingCount}/{agents.length} active
        </span>
      </div>

      {/* 조직도 트리 */}
      <div className="org-tree">
        {/* 루트: Dispatcher */}
        <DispatcherCard />

        {/* 수직 줄기 */}
        <div className="org-tree-trunk" />

        {/* 자식 에이전트들 — 수평 배치 + 연결선 */}
        <div style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
          {/* 수평 연결 바 */}
          {agents.length > 1 && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: '50%',
              transform: 'translateX(-50%)',
              height: 1,
              background: 'rgba(255, 255, 255, 0.1)',
              // 첫 자식 중앙 ~ 마지막 자식 중앙까지
              width: `calc(100% - 180px)`,
            }} />
          )}

          <div style={{
            display: 'flex',
            gap: 16,
            justifyContent: 'center',
            flexWrap: 'wrap',
          }}>
            {agents.map((agent) => (
              <div key={agent.agent_id} className="org-child-wrapper">
                {/* 수직 줄기: 수평 바 → 카드 */}
                <div className="org-child-stem" />
                <AgentCard
                  agent={agent}
                  onTrigger={handleTrigger}
                  isTriggering={triggeringId === agent.agent_id}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 하단: 현재 태스크 요약 (working 에이전트만) */}
      {agents.some(a => a.status === 'working' && a.current_task) && (
        <div style={{
          marginTop: 4,
          padding: '8px 10px',
          borderRadius: 8,
          background: 'rgba(34, 197, 94, 0.06)',
          border: '1px solid rgba(34, 197, 94, 0.1)',
        }}>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginBottom: 4 }}>
            ACTIVE TASKS
          </div>
          {agents
            .filter(a => a.status === 'working' && a.current_task)
            .map(a => {
              const role = AGENT_ROLES[a.agent_id];
              return (
                <div key={a.agent_id} style={{
                  fontSize: 10,
                  color: 'rgba(255,255,255,0.5)',
                  display: 'flex',
                  gap: 6,
                  alignItems: 'baseline',
                  marginBottom: 2,
                }}>
                  <span style={{ color: '#4ade80', fontWeight: 600 }}>
                    {role?.label ?? a.agent_id}
                  </span>
                  <span style={{ color: 'rgba(255,255,255,0.3)' }}>
                    {a.current_task && a.current_task.length > 40
                      ? a.current_task.slice(0, 40) + '…'
                      : a.current_task}
                  </span>
                </div>
              );
            })
          }
        </div>
      )}
    </div>
  );
}
