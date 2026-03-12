import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  Loader2,
  Radio,
  ServerCrash,
  TerminalSquare,
} from 'lucide-react';
import { API_BASE } from '../../constants';

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
    .flatMap((chain) => chain.steps)
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
                const currentStep = chain?.steps.find((step) => step.status === 'running') ?? null;
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
