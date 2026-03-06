/**
 * FILE: OrchestratorPanel.tsx
 * DESCRIPTION: AI 오케스트레이터 패널 — 스킬 레지스트리(①~⑦) 세로 나열 +
 *              각 스킬에 어떤 터미널이 사용 중인지 배지로 표시.
 *              하단에 터미널별 스킬 사용 순서(N-M 표기)를 보여줍니다.
 *              App.tsx에서 분리된 독립 컴포넌트로, skill_chain.db 기반 API를
 *              자체 폴링하여 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: [UI 전면 개편] 사용자 요청 — 스킬 세로 나열 + 터미널별 사용 순서
 *                      - 상단: 스킬 ①~⑦ 세로 목록, 각 스킬 옆에 사용 중인 터미널 배지
 *                      - 하단: 터미널별 체인 순서 (T1: 1-① → 1-③)
 *                      - 데이터 없어도 기본 7개 스킬은 항상 표시
 * - 2026-03-01 Claude: [리팩터링] skill_chain.json → skill_chain.db 전환에 맞춰 UI 개편
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import { Play } from 'lucide-react';
import { OrchestratorStatus } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// 원형 숫자 유니코드 ①②③… (1~7)
const CIRCLE_NUMS = ['', '①', '②', '③', '④', '⑤', '⑥', '⑦'];

// 기본 스킬 레지스트리 — API 데이터 없어도 항상 표시되는 고정 목록
const DEFAULT_SKILLS: SkillRegistry[] = [
  { num: 1, name: 'vibe-debug',        short: 'debug' },
  { num: 2, name: 'vibe-tdd',          short: 'tdd' },
  { num: 3, name: 'vibe-brainstorm',   short: 'brainstorm' },
  { num: 4, name: 'vibe-write-plan',   short: 'write-plan' },
  { num: 5, name: 'vibe-execute-plan', short: 'execute' },
  { num: 6, name: 'vibe-code-review',  short: 'review' },
  { num: 7, name: 'vibe-release',      short: 'release' },
];

// ── 스킬 레지스트리 타입 ──────────────────────────────────────────────────────
interface SkillRegistry {
  num: number;    // 전역 번호 (1~7)
  name: string;   // vibe-debug 등
  short: string;  // debug 등 약칭
}

// ── 터미널 체인 스텝 타입 ─────────────────────────────────────────────────────
interface TerminalStep {
  label: string;      // "1-3" (터미널1, 스킬③)
  skill_num: number;
  skill_name: string;
  step_order: number;
  status: string;     // pending | running | done | failed | skipped
  summary: string;
}

// ── 터미널 체인 타입 ──────────────────────────────────────────────────────────
interface TerminalChain {
  session_id: string;
  request: string;
  status: string;   // running | done
  updated_at: string;
  agent?: string;   // DB에 저장된 에이전트 이름 (PTY 세션 종료 후에도 유지)
  steps: TerminalStep[];
}

// ── API 응답 전체 타입 ────────────────────────────────────────────────────────
interface SkillChainResponse {
  skill_registry: SkillRegistry[];
  terminals: Record<string, TerminalChain>;
}

// ── OrchestratorPanel Props ───────────────────────────────────────────────────
interface OrchestratorPanelProps {
  onWarningCount: (count: number) => void;
}

/**
 * OrchestratorPanel
 *
 * 역할:
 *   상단 — 스킬 ①~⑦ 세로 목록. 각 스킬 오른쪽에 그 스킬을 실행 중인 터미널 배지 표시.
 *   하단 — 터미널별 스킬 사용 순서 (T1: 1-① → 1-③ → 1-⑤).
 *
 * 폴링 주기:
 *   - /api/orchestrator/status    : 3초
 *   - /api/orchestrator/skill-chain: 3초
 */
export default function OrchestratorPanel({ onWarningCount }: OrchestratorPanelProps) {
  const [orchStatus, setOrchStatus] = useState<OrchestratorStatus | null>(null);
  const [orchRunning, setOrchRunning] = useState(false);
  const [orchLastRun, setOrchLastRun] = useState<string | null>(null);
  const [chainData, setChainData] = useState<SkillChainResponse>({
    skill_registry: [],
    terminals: {},
  });

  // ── 오케스트레이터 상태 폴링 ─────────────────────────────────────────────
  useEffect(() => {
    const fetchOrch = () => {
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then((data: OrchestratorStatus) => {
          setOrchStatus(data);
          onWarningCount(data.warnings?.length ?? 0);
        })
        .catch(() => {});
    };
    fetchOrch();
    const interval = setInterval(fetchOrch, 3000);
    return () => clearInterval(interval);
  }, [onWarningCount]);

  // ── 스킬 체인 폴링 ───────────────────────────────────────────────────────
  useEffect(() => {
    const fetchChain = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then((data: SkillChainResponse) => {
          if (data.skill_registry !== undefined) {
            setChainData(data);
          }
        })
        .catch(() => {});
    };
    fetchChain();
    const interval = setInterval(fetchChain, 3000);
    return () => clearInterval(interval);
  }, []);

  // ── 수동 실행 ────────────────────────────────────────────────────────────
  const runOrchestrator = () => {
    setOrchRunning(true);
    fetch(`${API_BASE}/api/orchestrator/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then(res => res.json())
      .then(() => {
        setOrchLastRun(new Date().toLocaleTimeString());
        return fetch(`${API_BASE}/api/orchestrator/status`);
      })
      .then(res => res.json())
      .then((data: OrchestratorStatus) => {
        setOrchStatus(data);
        onWarningCount(data.warnings?.length ?? 0);
      })
      .catch(() => {})
      .finally(() => setOrchRunning(false));
  };

  // ── 표시할 스킬 목록 (API 데이터 우선, 없으면 기본값) ───────────────────
  const skills = chainData.skill_registry.length > 0
    ? chainData.skill_registry
    : DEFAULT_SKILLS;

  // ── 활성 터미널 목록 (steps가 있는 터미널만, 번호 순 정렬) ──────────────
  const activeTerminals = Object.entries(chainData.terminals ?? {})
    .filter(([, chain]) => chain.steps && chain.steps.length > 0)
    .sort(([a], [b]) => Number(a) - Number(b));

  // ── 스킬 번호 → 해당 스킬을 사용 중인 터미널+스텝 목록 매핑 ────────────
  // 예: skillUsage[3] = [{termId:"1", step:{...}}, {termId:"2", step:{...}}]
  const skillUsage: Record<number, { termId: string; step: TerminalStep }[]> = {};
  activeTerminals.forEach(([termId, chain]) => {
    chain.steps.forEach(step => {
      if (!skillUsage[step.skill_num]) skillUsage[step.skill_num] = [];
      skillUsage[step.skill_num].push({ termId, step });
    });
  });

  // ── 스텝 상태별 색상 ────────────────────────────────────────────────────
  const stepBadgeColor = (status: string) =>
    status === 'done'    ? 'bg-green-500/20 text-green-400 border-green-500/30' :
    status === 'running' ? 'bg-primary/20 text-primary border-primary/40 animate-pulse' :
    status === 'failed'  ? 'bg-red-500/20 text-red-400 border-red-500/30' :
    status === 'skipped' ? 'bg-white/5 text-[#555] border-white/10' :
                           'bg-white/5 text-[#666] border-white/10';

  const stepIcon = (status: string) =>
    status === 'done'    ? '✅' :
    status === 'running' ? '🔄' :
    status === 'failed'  ? '❌' :
    status === 'skipped' ? '⏭️' : '⏳';

  // ── 터미널 체인 전체 상태 색상 ──────────────────────────────────────────
  const chainBorderColor = (status: string) =>
    status === 'running' ? 'border-primary/30 bg-primary/5' :
    status === 'done'    ? 'border-green-500/20 bg-green-500/5' :
                           'border-white/10';

  // ── 에이전트명 색상 ──────────────────────────────────────────────────────
  const agentBadgeColor = (agent: string) =>
    agent === 'claude' ? 'bg-green-500/20 text-green-400' :
    agent === 'gemini' ? 'bg-blue-500/20 text-blue-400' :
                         'bg-yellow-500/20 text-yellow-400';

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* ── 헤더: 실행 버튼 ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between shrink-0">
        <div className="text-[9px] text-[#858585] font-mono">
          {orchLastRun ? `마지막 실행: ${orchLastRun}` : '스킬 체인 모니터'}
        </div>
        <button
          onClick={runOrchestrator}
          disabled={orchRunning}
          className="flex items-center gap-1 px-2 py-1 bg-primary/20 hover:bg-primary/40 disabled:opacity-40 text-primary rounded text-[9px] font-bold transition-colors"
        >
          <Play className="w-3 h-3" />
          {orchRunning ? '실행 중...' : '지금 실행'}
        </button>
      </div>

      {/* ── ① 스킬 목록 (세로) + 각 스킬에 사용 중인 터미널 배지 ──────── */}
      {/* 항상 표시 — 데이터 없어도 기본 7개 스킬은 고정 노출             */}
      <div className="shrink-0 rounded border border-white/10 overflow-hidden">
        <div className="px-2 py-1.5 border-b border-white/10 flex items-center justify-between">
          <span className="text-[9px] font-bold text-[#969696] uppercase tracking-wider">
            스킬 레지스트리
          </span>
          <span className="text-[8px] text-[#555]">사용 중인 터미널 →</span>
        </div>
        <div className="flex flex-col">
          {skills.map((sk, idx) => {
            // 이 스킬을 사용 중인 터미널+스텝 목록
            const usages = skillUsage[sk.num] ?? [];
            const isInUse = usages.length > 0;
            return (
              <div
                key={sk.num}
                className={`flex items-center gap-2 px-2 py-1.5 ${
                  idx < skills.length - 1 ? 'border-b border-white/5' : ''
                } ${isInUse ? 'bg-white/3' : ''}`}
              >
                {/* 스킬 번호 + 이름 */}
                <span className="text-primary font-bold text-[10px] font-mono w-4 shrink-0">
                  {CIRCLE_NUMS[sk.num] ?? sk.num}
                </span>
                <span className={`text-[9px] font-mono w-16 shrink-0 ${isInUse ? 'text-[#cccccc]' : 'text-[#666]'}`}>
                  {sk.short}
                </span>

                {/* 이 스킬을 사용 중인 터미널 배지들 */}
                <div className="flex items-center gap-1 flex-wrap flex-1">
                  {usages.map(({ termId, step }, i) => (
                    <div
                      key={i}
                      className={`flex items-center gap-0.5 px-1 py-0.5 rounded border text-[8px] font-mono font-bold cursor-default ${stepBadgeColor(step.status)}`}
                      title={step.summary || `T${termId} — ${step.status}`}
                    >
                      {stepIcon(step.status)} T{termId}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── ② 오케스트레이션 파이프라인 (수평 흐름) ─────────────────────── */}
      {/* 왼쪽부터: [오케스트레이터] → [스킬1: 뭐하는지] → [스킬2: 뭐하는지] */}
      <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-2">
        {activeTerminals.length > 0 ? (
          activeTerminals.map(([termId, chain]) => {
            const agentName = (orchStatus?.terminal_agents ?? {})[termId] || chain.agent || '';
            return (
              <div key={termId} className={`rounded border ${chainBorderColor(chain.status)} p-2 shrink-0`}>

                {/* 터미널 헤더 */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-bold text-[#dddddd] font-mono">T{termId}</span>
                    {agentName && (
                      <span className={`px-1 py-0.5 rounded text-[7px] font-bold ${agentBadgeColor(agentName)}`}>
                        {agentName}
                      </span>
                    )}
                    {chain.status === 'running' && (
                      <span className="text-[7px] text-primary animate-pulse">● 실행중</span>
                    )}
                    {chain.status === 'done' && (
                      <span className="text-[7px] text-green-400">✓ 완료</span>
                    )}
                  </div>
                  {chain.updated_at && (
                    <span className="text-[7px] text-[#555] font-mono shrink-0">
                      {new Date(chain.updated_at).toLocaleTimeString()}
                    </span>
                  )}
                </div>

                {/* ── 수평 파이프라인: [오케스트레이터] → [스킬1] → [스킬2] ── */}
                <div className="flex items-stretch gap-0 overflow-x-auto custom-scrollbar pb-1">

                  {/* 오케스트레이터 카드 (파이프라인 첫 번째) */}
                  <div className="flex items-center shrink-0">
                    <div className="flex flex-col gap-1 px-2 py-1.5 rounded border border-primary/30 bg-primary/8 min-w-[72px] max-w-[96px]">
                      <div className="flex items-center gap-1">
                        <span className="text-primary text-[9px]">🎯</span>
                        <span className="text-[8px] font-bold text-primary">오케스트</span>
                      </div>
                      {chain.request && (
                        <span
                          className="text-[7px] text-[#888] leading-tight line-clamp-2"
                          title={chain.request}
                        >
                          "{chain.request}"
                        </span>
                      )}
                    </div>
                    {/* 화살표 */}
                    {chain.steps.length > 0 && (
                      <span className="text-[#444] text-[10px] px-1 shrink-0">→</span>
                    )}
                  </div>

                  {/* 스킬 카드들 (파이프라인 2번째 이후) */}
                  {chain.steps.map((step, i) => {
                    const shortName = step.skill_name.replace(/^vibe-/, '');
                    const isRunning = step.status === 'running';
                    const isDone    = step.status === 'done';
                    const isFailed  = step.status === 'failed';
                    const isPending = step.status === 'pending';

                    // 카드 테두리·배경 색상
                    const cardCls = isRunning ? 'border-primary/50 bg-primary/10'
                                  : isDone    ? 'border-green-500/30 bg-green-500/8'
                                  : isFailed  ? 'border-red-500/30 bg-red-500/8'
                                  :             'border-white/8 bg-white/2';

                    // 스킬명 텍스트 색상
                    const nameCls  = isRunning ? 'text-primary'
                                  : isDone    ? 'text-green-400'
                                  : isFailed  ? 'text-red-400'
                                  :             'text-[#555]';

                    return (
                      <div key={i} className="flex items-center shrink-0">
                        {/* 스킬 카드 */}
                        <div
                          className={`flex flex-col gap-1 px-2 py-1.5 rounded border ${cardCls} min-w-[80px] max-w-[110px]`}
                          title={step.summary || step.skill_name}
                        >
                          {/* 상태 아이콘 + 스킬명 */}
                          <div className="flex items-center gap-1">
                            <span className={`text-[9px] ${isRunning ? 'animate-pulse' : ''}`}>
                              {stepIcon(step.status)}
                            </span>
                            <span className={`text-[8px] font-bold font-mono truncate ${nameCls}`}>
                              {shortName}
                            </span>
                          </div>

                          {/* 뭘 하는지 — summary 또는 상태 텍스트 */}
                          {step.summary ? (
                            <span className="text-[7px] text-[#888] leading-tight line-clamp-2">
                              {step.summary}
                            </span>
                          ) : (
                            <span className={`text-[7px] leading-tight italic ${
                              isRunning ? 'text-primary/70' :
                              isPending ? 'text-[#444]' : 'text-[#555]'
                            }`}>
                              {isRunning ? '실행 중...' : isPending ? '대기' : step.status}
                            </span>
                          )}
                        </div>

                        {/* 스킬 사이 화살표 (마지막 카드 제외) */}
                        {i < chain.steps.length - 1 && (
                          <span className="text-[#333] text-[10px] px-1 shrink-0">→</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        ) : (
          <div className="text-center text-[#555] text-[9px] py-4 italic">
            실행 중인 터미널 없음
            <div className="text-[8px] mt-1 text-[#444]">
              /vibe-orchestrate 실행 시 파이프라인이 여기에 표시됩니다
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
