import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  Code2,
  Globe,
  Home,
  Loader2,
  PowerOff,
  Radio,
  ServerCrash,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import { API_BASE } from '../../constants';

// ── 에이전트 조직도 관련 타입/상수 ──

interface AgentBeat {
  agent_id: string;
  status: string;
  last_beat: string;
  current_task: string | null;
  beat_count: number;
  config?: string;
}

const AGENT_ROLES: Record<string, {
  label: string;
  title: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
}> = {
  'claude-T1': { label: 'Claude', title: 'Engineer', description: 'Founding Full-Stack Engineer', Icon: Code2 },
  'gemini-T2': { label: 'Gemini', title: 'Architect', description: 'Design & Orchestration', Icon: Globe },
  'codex-T3': { label: 'Codex', title: 'QA Engineer', description: 'Sandbox & Validation', Icon: Wrench },
  claude: { label: 'Claude', title: 'Engineer', description: 'Precision Logic', Icon: Code2 },
  gemini: { label: 'Gemini', title: 'Architect', description: 'Research & Design', Icon: Globe },
  codex: { label: 'Codex', title: 'QA Engineer', description: 'Execution & Verify', Icon: Wrench },
};

const STATUS_COLORS: Record<string, { dot: string; glow: string; border: string }> = {
  working: { dot: '#22c55e', glow: '0 0 8px rgba(34, 197, 94, 0.6)', border: 'rgba(34, 197, 94, 0.3)' },
  idle: { dot: '#eab308', glow: '0 0 6px rgba(234, 179, 8, 0.4)', border: 'rgba(234, 179, 8, 0.2)' },
  offline: { dot: '#6b7280', glow: 'none', border: 'rgba(255, 255, 255, 0.06)' },
};

function agentRelativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return 'now';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

// ── 조직도 카드 컴포넌트들 ──

function OrgAgentCard({ agent, onTrigger, isTriggering }: {
  agent: AgentBeat; onTrigger: (id: string) => void; isTriggering: boolean;
}) {
  const role = AGENT_ROLES[agent.agent_id] ?? { label: agent.agent_id, title: 'Agent', description: '', Icon: Wrench };
  const colors = STATUS_COLORS[agent.status] ?? STATUS_COLORS.offline;
  const { Icon } = role;
  return (
    <div
      className="org-card"
      style={{
        background: 'rgba(255,255,255,0.04)', border: `1px solid ${colors.border}`,
        borderRadius: 12, padding: '14px 16px 12px', minWidth: 160, maxWidth: 190,
        cursor: 'pointer', transition: 'border-color 0.3s, box-shadow 0.3s', position: 'relative',
      }}
      onClick={() => onTrigger(agent.agent_id)}
      title={`클릭하여 하트비트 트리거 (${agent.agent_id})`}
    >
      {isTriggering && (
        <div style={{ position: 'absolute', inset: 0, borderRadius: 12, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2 }}>
          <Loader2 className="w-4 h-4 animate-spin text-white/60" />
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
        <Icon className="w-3.5 h-3.5 text-white/50" />
        <span style={{ fontSize: 13, fontWeight: 700, color: 'white' }}>{role.title}</span>
      </div>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 5, lineHeight: 1.3 }}>{role.description}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%', background: colors.dot,
          boxShadow: colors.glow, display: 'inline-block', flexShrink: 0,
          animation: agent.status === 'working' ? 'pulse-dot 2s ease-in-out infinite' : 'none',
        }} />
        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.45)' }}>{role.label}</span>
        {agent.last_beat && (
          <span style={{
            fontSize: 10, marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 3,
            color: (() => {
              const age = (Date.now() - new Date(agent.last_beat).getTime()) / 1000;
              if (age > 300) return '#ef4444';  // 5분 초과: 빨강
              if (age > 60) return '#eab308';   // 1분 초과: 노랑
              return 'rgba(255,255,255,0.4)';   // 정상: 흰색
            })(),
          }}>
            <Clock3 className="w-3 h-3" style={{ opacity: 0.6 }} />
            {agentRelativeTime(agent.last_beat)}
          </span>
        )}
      </div>
      {agent.current_task && (
        <div style={{
          marginTop: 6, padding: '3px 6px', borderRadius: 5, background: 'rgba(255,255,255,0.04)',
          fontSize: 9, color: 'rgba(255,255,255,0.3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {agent.current_task}
        </div>
      )}
    </div>
  );
}

function OrgDispatcherCard() {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 12, padding: '12px 18px 10px', display: 'inline-block',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
        <Home className="w-3.5 h-3.5 text-white/50" />
        <span style={{ fontSize: 13, fontWeight: 700, color: 'white' }}>Dispatcher</span>
      </div>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 3 }}>Task Orchestrator</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 6px rgba(34,197,94,0.5)', display: 'inline-block' }} />
        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.45)' }}>User</span>
      </div>
    </div>
  );
}

interface LiveStep {
  skill_name: string;
  status: string;
  summary?: string;
}

interface LiveChain {
  request: string;
  steps: LiveStep[];
  terminal_id?: number;
  // true = running/pending 단계가 존재 (라이브), false = 완료된 체인 (흐리게 표시)
  isLive: boolean;
  updatedAt?: string;
}

interface TerminalStatus {
  status: 'running' | 'idle' | 'done' | 'error';
  task: string;
  cli: string;
  run_id?: string;
  ts?: string;
  last_line?: string;
  pipeline_stage?: 'analyzing' | 'modifying' | 'verifying' | 'done' | 'idle';
  external?: boolean;
}

interface SkillResultEntry {
  skill: string;
  status: string;
  summary: string;
}

interface SkillSessionResult {
  session_id: string;
  terminal_id?: number;
  request: string;
  results: SkillResultEntry[];
  completed_at: string;
}

const SKILL_LABELS: Record<string, string> = {
  debug: '디버그',
  tdd: 'TDD',
  brainstorm: '브레인스토밍',
  'write-plan': '계획 작성',
  'execute-plan': '계획 실행',
  execute: '계획 실행',
  'code-review': '코드 리뷰',
  release: '릴리스',
  orchestrate: '오케스트레이션',
};

function relativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff)) return '';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

function formatTime(iso?: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function skillLabel(skillName: string): string {
  const raw = skillName.replace(/^vibe-/, '');
  return SKILL_LABELS[raw] ?? raw;
}

function StepPill({ step }: { step: LiveStep }) {
  const isRunning = step.status === 'running';
  const isDone = step.status === 'done';
  const isFailed = step.status === 'failed';
  const tone = isRunning
    ? 'border-amber-400/40 bg-amber-500/10 text-amber-200'
    : isDone
    ? 'border-green-500/30 bg-green-500/10 text-green-300'
    : isFailed
    ? 'border-red-500/30 bg-red-500/10 text-red-300'
    : 'border-white/10 bg-white/[0.04] text-white/45';

  return (
    <div className={`rounded-md border px-2 py-1 ${tone}`}>
      <div className="flex items-center gap-1.5">
        {isRunning ? (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
        ) : isDone ? (
          <CheckCircle2 className="h-3 w-3 shrink-0" />
        ) : isFailed ? (
          <AlertCircle className="h-3 w-3 shrink-0" />
        ) : (
          <Clock3 className="h-3 w-3 shrink-0" />
        )}
        <span className="text-[11px] font-semibold leading-none">{skillLabel(step.skill_name)}</span>
      </div>
      {step.summary && (
        <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-white/35">{step.summary}</p>
      )}
    </div>
  );
}

function SessionRow({ session }: { session: SkillSessionResult }) {
  const doneCount = session.results.filter((result) => result.status === 'done').length;
  const totalCount = session.results.length;
  const terminalLabel = session.terminal_id ? `T${session.terminal_id}` : '공용';

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-bold text-white/65">
              {terminalLabel}
            </span>
            <span className="text-[10px] text-white/35">{formatTime(session.completed_at)}</span>
          </div>
          <p className="mt-1 line-clamp-2 text-[12px] font-medium leading-snug text-white/90">
            {session.request || '요청 없음'}
          </p>
        </div>
        <span className="shrink-0 text-[11px] font-bold text-green-400">
          {doneCount}/{totalCount}
        </span>
      </div>

      {session.results.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {session.results.map((result, index) => {
            const tone =
              result.status === 'done'
                ? 'bg-green-500/10 text-green-300'
                : result.status === 'error'
                ? 'bg-red-500/10 text-red-300'
                : result.status === 'skipped'
                ? 'bg-white/10 text-white/35'
                : 'bg-amber-500/10 text-amber-300';

            return (
              <span key={`${session.session_id}-${index}`} className={`rounded px-1.5 py-1 text-[10px] font-semibold ${tone}`}>
                {skillLabel(result.skill)}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TaskBoardPanel() {
  const [liveChains, setLiveChains] = useState<Record<string, LiveChain>>({});
  const [terminals, setTerminals] = useState<Record<string, TerminalStatus>>({});
  const [sessions, setSessions] = useState<SkillSessionResult[]>([]);
  const [hasApiSignal, setHasApiSignal] = useState(false);
  const [fetchFailures, setFetchFailures] = useState(0);

  // ── 에이전트 조직도 상태 ──
  const [agents, setAgents] = useState<AgentBeat[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
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
      } catch { /* 연결 실패 시 무시 */ }
      finally { if (active) setAgentsLoading(false); }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // 오프라인 에이전트 목록 (5분 이상 heartbeat 없음) — 렌더 내 중복 계산 방지
  const offlineAgentIds = useMemo(() => {
    return agents.filter(a => {
      if (!a.last_beat) return true;
      return (Date.now() - new Date(a.last_beat).getTime()) / 1000 > 300;
    }).map(a => a.agent_id);
  }, [agents]);

  const handleAgentTrigger = useCallback(async (agentId: string) => {
    setTriggeringId(agentId);
    try {
      await fetch(`${API_BASE}/api/agents/${agentId}/trigger`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
    } catch { /* 무시 */ }
    finally { setTimeout(() => setTriggeringId(null), 1500); }
  }, []);

  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then((response) => response.json())
        .then((data) => {
          const next: Record<string, LiveChain> = {};
          const terminalMap: Record<string, any> = data?.terminals ?? {};
          for (const [terminalId, chain] of Object.entries(terminalMap)) {
            const steps: LiveStep[] = (chain as any)?.steps ?? [];
            // 실제 작업이 있는 체인만 포함 (done/running/failed 중 하나라도 있어야 함)
            const hasRealWork = steps.some(
              (step) => step.status === 'running' || step.status === 'pending' || step.status === 'done' || step.status === 'failed',
            );
            if (!hasRealWork) continue;
            const isLive = steps.some((step) => step.status === 'running' || step.status === 'pending');
            next[terminalId] = {
              request: (chain as any)?.request ?? '',
              steps,
              terminal_id: Number.parseInt(terminalId, 10) || undefined,
              isLive,
              updatedAt: (chain as any)?.updated_at ?? undefined,
            };
          }
          setLiveChains(next);
          setHasApiSignal(true);
        })
        .catch(() => setFetchFailures((prev) => prev + 1));
    };

    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/agent/terminals`)
        .then((response) => response.json())
        .then((data) => {
          if (data && typeof data === 'object') {
            setTerminals(data);
            setHasApiSignal(true);
          }
        })
        .catch(() => setFetchFailures((prev) => prev + 1));
    };

    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/skill-results`)
        .then((response) => response.json())
        .then((data) => {
          setSessions(Array.isArray(data) ? data : []);
          setHasApiSignal(true);
        })
        .catch(() => setFetchFailures((prev) => prev + 1));
    };

    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  const activeTerminals = useMemo(() => {
    const ids = new Set<string>();
    // 체인이 있는 터미널 모두 포함 (라이브 + 완료 포함)
    Object.keys(liveChains).forEach((id) => ids.add(id));
    // agent_live.jsonl 기반 터미널도 포함
    Object.entries(terminals).forEach(([id, status]) => {
      if (status.external) return;
      if (status.status === 'running' || status.status === 'error' || status.status === 'done') {
        ids.add(id.replace(/^T/i, ''));
      }
    });

    return Array.from(ids)
      .map((rawId) => {
        const terminalId = rawId.startsWith('T') ? rawId : `T${rawId}`;
        const terminal = terminals[terminalId];
        const chain = liveChains[rawId] ?? liveChains[terminalId.replace(/^T/i, '')] ?? null;
        return {
          rawId,
          terminalId,
          terminal,
          chain,
        };
      })
      .sort((a, b) => {
        // 라이브(running/pending) → agent running → 완료 순
        const aLive = a.chain?.isLive || a.terminal?.status === 'running';
        const bLive = b.chain?.isLive || b.terminal?.status === 'running';
        if (aLive !== bLive) return aLive ? -1 : 1;
        return a.terminalId.localeCompare(b.terminalId);
      });
  }, [liveChains, terminals]);

  const recentSessions = useMemo(
    () =>
      [...sessions]
        .sort((a, b) => String(b.completed_at ?? '').localeCompare(String(a.completed_at ?? '')))
        .slice(0, 8),
    [sessions],
  );

  const runningTerminalCount = activeTerminals.filter(
    (entry) => entry.terminal?.status === 'running' || entry.chain?.isLive,
  ).length;
  const runningStepCount = Object.values(liveChains)
    .flatMap((chain) => chain.steps ?? [])
    .filter((step) => step.status === 'running').length;
  const serverOffline = !hasApiSignal && fetchFailures > 0;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      <div className="rounded-2xl border border-white/10 bg-[#111315] p-4">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-bold text-white">오케스트레이션 모니터</h2>
          {runningTerminalCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-1 text-[10px] font-bold text-green-400">
              <Radio className="h-3 w-3 animate-pulse" />
              Live
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-white/45">중복 단계 보드는 제거하고, 지금 실행 중인 터미널과 최근 완료만 보여줍니다.</p>

        <div className="mt-4 grid grid-cols-3 gap-2">
          <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-white/35">활성 터미널</div>
            <div className="mt-1 text-lg font-bold text-white">{runningTerminalCount}</div>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-white/35">실행 중 단계</div>
            <div className="mt-1 text-lg font-bold text-amber-300">{runningStepCount}</div>
          </div>
          <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-white/35">최근 완료</div>
            <div className="mt-1 text-lg font-bold text-green-400">{recentSessions.length}</div>
          </div>
        </div>

        {serverOffline && (
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            <ServerCrash className="h-4 w-4 shrink-0" />
            서버에 연결되지 않았습니다. 현재 팝업은 빈 화면처럼 보일 수 있습니다.
          </div>
        )}
      </div>

      {/* ── 에이전트 조직도 (Paperclip 스타일) ── */}
      {!agentsLoading && agents.length > 0 && (
        <div className="rounded-2xl border border-white/10 bg-[#111315] p-4">
          <style>{`
            @keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
            .org-card:hover { border-color: rgba(255,255,255,0.2) !important; box-shadow: 0 0 20px rgba(255,255,255,0.03); }
          `}</style>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Wrench className="h-4 w-4 text-amber-300" />
              <h3 className="text-sm font-bold text-white">에이전트 조직도</h3>
            </div>
            <span className="text-[10px] text-white/25">
              {agents.filter(a => a.status === 'working').length}/{agents.length} active
            </span>
          </div>

          {/* 오프라인 에이전트 경고 */}
          {offlineAgentIds.length > 0 && (
            <div className="mb-3 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-3 py-2">
              <PowerOff className="h-3.5 w-3.5 shrink-0 text-red-400" />
              <span className="text-[10px] text-red-300">
                오프라인 에이전트 감지 — {offlineAgentIds.join(', ')} (카드 클릭으로 재시도)
              </span>
            </div>
          )}

          {/* 트리 구조: Dispatcher → 에이전트들 */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0 }}>
            <OrgDispatcherCard />
            {/* 수직 줄기 */}
            <div style={{ width: 1, height: 24, background: 'rgba(255,255,255,0.1)' }} />
            {/* 자식 에이전트들 */}
            <div style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
              {agents.length > 1 && (
                <div style={{
                  position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)',
                  height: 1, background: 'rgba(255,255,255,0.1)', width: 'calc(100% - 160px)',
                }} />
              )}
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
                {agents.map((agent) => (
                  <div key={agent.agent_id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    <div style={{ width: 1, height: 24, background: 'rgba(255,255,255,0.1)' }} />
                    <OrgAgentCard agent={agent} onTrigger={handleAgentTrigger} isTriggering={triggeringId === agent.agent_id} />
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 현재 작업 중인 에이전트 태스크 요약 */}
          {agents.some(a => a.status === 'working' && a.current_task) && (
            <div style={{
              marginTop: 10, padding: '6px 10px', borderRadius: 8,
              background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.1)',
            }}>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginBottom: 3 }}>ACTIVE TASKS</div>
              {agents.filter(a => a.status === 'working' && a.current_task).map(a => {
                const role = AGENT_ROLES[a.agent_id];
                return (
                  <div key={a.agent_id} style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', display: 'flex', gap: 6, alignItems: 'baseline', marginBottom: 2 }}>
                    <span style={{ color: '#4ade80', fontWeight: 600 }}>{role?.label ?? a.agent_id}</span>
                    <span style={{ color: 'rgba(255,255,255,0.3)' }}>
                      {a.current_task && a.current_task.length > 60 ? a.current_task.slice(0, 60) + '…' : a.current_task}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-h-0 overflow-hidden rounded-2xl border border-white/10 bg-[#111315]">
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <div className="flex items-center gap-2">
              <TerminalSquare className="h-4 w-4 text-sky-300" />
              <h3 className="text-sm font-bold text-white">활성 터미널</h3>
            </div>
            <span className="text-[11px] text-white/35">{activeTerminals.length}개 슬롯</span>
          </div>

          <div className="grid max-h-full gap-3 overflow-y-auto p-4 custom-scrollbar md:grid-cols-2">
            {activeTerminals.length === 0 ? (
              <div className="col-span-full flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 text-center">
                <Clock3 className="mb-3 h-8 w-8 text-white/15" />
                <p className="text-sm text-white/45">최근 8시간 내 오케스트레이션 기록이 없습니다.</p>
                <p className="mt-1 text-xs text-white/25">새 체인이 시작되면 여기서 터미널별 상태가 표시됩니다.</p>
              </div>
            ) : (
              activeTerminals.map(({ rawId, terminalId, terminal, chain }) => {
                const request = chain?.request || terminal?.task || '작업 설명 없음';
                const currentStep = chain?.steps?.find((step) => step.status === 'running') ?? null;
                const isChainDone = chain && !chain.isLive;  // 체인 있지만 완료 상태
                const statusTone =
                  terminal?.status === 'error'
                    ? 'border-red-500/25 bg-red-500/[0.05]'
                    : (terminal?.status === 'done' || isChainDone)
                    ? 'border-green-500/15 bg-green-500/[0.03] opacity-75'
                    : 'border-sky-500/20 bg-sky-500/[0.04]';

                return (
                  <div key={rawId} className={`rounded-2xl border p-4 ${statusTone}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="rounded-md bg-white/10 px-2 py-1 text-[11px] font-bold text-white">
                            {terminalId}
                          </span>
                          {terminal?.cli && (
                            <span
                              className={`rounded-md px-1.5 py-1 text-[10px] font-bold ${
                                terminal.cli === 'gemini'
                                  ? 'bg-blue-500/15 text-blue-300'
                                  : 'bg-green-500/15 text-green-300'
                              }`}
                            >
                              {terminal.cli}
                            </span>
                          )}
                          {/* 완료된 체인: "완료" 배지 표시 */}
                          {isChainDone && !terminal?.cli && (
                            <span className="rounded-md bg-white/8 px-1.5 py-1 text-[10px] font-bold text-white/35">
                              완료
                            </span>
                          )}
                        </div>
                        <p className="mt-2 line-clamp-2 text-sm font-medium leading-snug text-white/90">{request}</p>
                      </div>

                      <div className="shrink-0 text-right">
                        <div className="text-[10px] uppercase tracking-wider text-white/30">
                          {terminal?.status ?? (chain ? 'running' : 'idle')}
                        </div>
                        <div className="mt-1 text-[11px] text-white/40">{relativeTime(terminal?.ts)}</div>
                      </div>
                    </div>

                    {currentStep && (
                      <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2">
                        <div className="flex items-center gap-2 text-[11px] font-semibold text-amber-200">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          현재 단계: {skillLabel(currentStep.skill_name)}
                        </div>
                      </div>
                    )}

                    {terminal?.last_line && terminal.status === 'running' && (
                      <p className="mt-3 line-clamp-2 rounded-lg bg-black/20 px-3 py-2 font-mono text-[11px] leading-snug text-white/45">
                        {terminal.last_line}
                      </p>
                    )}

                    {chain?.steps?.length ? (
                      <div className="mt-3 grid gap-2">
                        {chain.steps.map((step, index) => (
                          <StepPill key={`${terminalId}-${index}-${step.skill_name}`} step={step} />
                        ))}
                      </div>
                    ) : (
                      <div className="mt-3 rounded-lg border border-dashed border-white/10 px-3 py-4 text-center text-[11px] text-white/30">
                        현재 체인 정보가 아직 기록되지 않았습니다.
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="min-h-0 overflow-hidden rounded-2xl border border-white/10 bg-[#111315]">
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-400" />
              <h3 className="text-sm font-bold text-white">최근 완료</h3>
            </div>
            <span className="text-[11px] text-white/35">최대 8건</span>
          </div>

          <div className="flex max-h-full min-h-0 flex-col gap-3 overflow-y-auto p-4 custom-scrollbar">
            {recentSessions.length === 0 ? (
              <div className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 text-center">
                <CheckCircle2 className="mb-3 h-8 w-8 text-white/15" />
                <p className="text-sm text-white/45">표시할 완료 기록이 없습니다.</p>
              </div>
            ) : (
              recentSessions.map((session) => <SessionRow key={session.session_id} session={session} />)
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
