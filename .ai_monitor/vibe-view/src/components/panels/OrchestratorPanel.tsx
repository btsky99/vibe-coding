/**
 * FILE: OrchestratorPanel.tsx
 * DESCRIPTION: AI 오케스트레이터 패널 — 스킬 레지스트리(①~⑦) + 터미널별(T1~T8)
 *              스킬 체인 실행 흐름을 N-M 표기로 모니터링합니다.
 *              App.tsx에서 분리된 독립 컴포넌트로, skill_chain.db 기반 API를
 *              자체 폴링하여 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: [리팩터링] skill_chain.json → skill_chain.db 전환에 맞춰 UI 전면 개편
 *                      - 상단 스킬 레지스트리 위젯: ①debug ~ ⑦release 배지 표시
 *                      - 터미널별 체인 섹션: N-M 표기 (T1이 debug→tdd 쓰면 1-1→1-2)
 *                      - 기존 단일 체인 위젯 제거 (DB 전환으로 불필요)
 * - 2026-03-01 Claude: [버그수정] terminal_agents 미렌더링 수정 — 터미널별 에이전트 현황 그리드 추가
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import { Play, Network } from 'lucide-react';
import { OrchestratorStatus } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// 원형 숫자 유니코드 ①②③… (1~7)
const CIRCLE_NUMS = ['', '①', '②', '③', '④', '⑤', '⑥', '⑦'];

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
 * 역할: skill_chain.db 기반 API를 폴링하여
 *       1) 스킬 레지스트리 (①~⑦ 번호 목록)
 *       2) 터미널별 스킬 체인 실행 현황 (N-M 표기)
 *       을 실시간 시각화하는 패널 컴포넌트.
 *
 * 폴링 주기:
 *   - /api/orchestrator/status    : 3초 (에이전트 상태 + 경고 + 최근 액션)
 *   - /api/orchestrator/skill-chain: 3초 (스킬 레지스트리 + 터미널별 체인)
 */
export default function OrchestratorPanel({ onWarningCount }: OrchestratorPanelProps) {
  // 오케스트레이터 전체 상태 (에이전트별 상태, 태스크 분배, 경고 등)
  const [orchStatus, setOrchStatus] = useState<OrchestratorStatus | null>(null);
  // 수동 실행 중 여부
  const [orchRunning, setOrchRunning] = useState(false);
  // 마지막 수동 실행 시각
  const [orchLastRun, setOrchLastRun] = useState<string | null>(null);
  // 스킬 레지스트리 + 터미널별 체인 데이터
  const [chainData, setChainData] = useState<SkillChainResponse>({
    skill_registry: [],
    terminals: {},
  });

  // ── 오케스트레이터 상태 폴링 (3초 간격) ──────────────────────────────────
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

  // ── 스킬 체인 폴링 (3초 간격) — DB 기반 응답 ────────────────────────────
  useEffect(() => {
    const fetchChain = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then((data: SkillChainResponse) => {
          // 새 응답 구조(skill_registry + terminals) 처리
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

  // ── 오케스트레이터 수동 실행 핸들러 ──────────────────────────────────────
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

  // ── 활성 터미널 목록 (steps가 있는 터미널만) ───────────────────────────
  const activeTerminals = Object.entries(chainData.terminals ?? {})
    .filter(([, chain]) => chain.steps && chain.steps.length > 0)
    .sort(([a], [b]) => Number(a) - Number(b));

  // ── 스텝 상태별 아이콘/색상 ────────────────────────────────────────────
  const stepIcon = (status: string) =>
    status === 'done'    ? '✅' :
    status === 'running' ? '🔄' :
    status === 'failed'  ? '❌' :
    status === 'skipped' ? '⏭️' : '⏳';

  const stepColor = (status: string) =>
    status === 'done'    ? 'border-green-500/40 bg-green-500/10 text-green-400' :
    status === 'running' ? 'border-primary/50 bg-primary/10 text-primary animate-pulse' :
    status === 'failed'  ? 'border-red-500/40 bg-red-500/10 text-red-400' :
    status === 'skipped' ? 'border-white/10 bg-white/5 text-[#555]' :
                           'border-white/10 bg-white/5 text-[#666]';

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* 헤더: 실행 버튼 + 마지막 실행 시각 */}
      <div className="flex items-center justify-between shrink-0">
        <div className="text-[9px] text-[#858585] font-mono">
          {orchLastRun ? `마지막 실행: ${orchLastRun}` : '자동 조율 엔진'}
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

      {/* ── ① 스킬 레지스트리 위젯 ──────────────────────────────────────── */}
      {/* 전역 스킬 번호 ①~⑦을 배지로 표시. 각 터미널 체인의 N-M 표기 기준표 역할 */}
      {chainData.skill_registry.length > 0 && (
        <div className="shrink-0 p-2 rounded border border-white/10">
          <div className="text-[9px] font-bold text-[#969696] mb-1.5 uppercase tracking-wider">
            스킬 레지스트리
          </div>
          <div className="flex flex-wrap gap-1">
            {chainData.skill_registry.map(sk => (
              <div
                key={sk.num}
                className="flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-white/10 bg-white/3 text-[8px] font-mono"
                title={sk.name}
              >
                <span className="text-primary font-bold">{CIRCLE_NUMS[sk.num] ?? sk.num}</span>
                <span className="text-[#888]">{sk.short}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── ② 터미널별 스킬 체인 현황 ───────────────────────────────────── */}
      {/* 활성 터미널만 표시. 각 스텝은 "T번호-스킬번호" 형태로 레이블 표시 */}
      {activeTerminals.length > 0 ? (
        <div className="shrink-0 flex flex-col gap-1.5">
          <div className="text-[9px] font-bold text-[#969696] uppercase tracking-wider px-1">
            터미널별 실행 현황
          </div>
          {activeTerminals.map(([termId, chain]) => {
            // 터미널에 실제로 실행 중인 에이전트 이름 (PTY 기반)
            const agentName = (orchStatus?.terminal_agents ?? {})[termId] || '';
            // 체인 전체 상태 색상
            const chainBorder =
              chain.status === 'running' ? 'border-primary/30 bg-primary/5' :
              chain.status === 'done'    ? 'border-green-500/20 bg-green-500/5' :
                                          'border-white/10';
            return (
              <div key={termId} className={`p-2 rounded border ${chainBorder}`}>
                {/* 터미널 헤더: T번호 + 에이전트명 + 요청 내용 + 시각 */}
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] font-bold text-[#bbbbbb] font-mono">
                      T{termId}
                    </span>
                    {agentName && (
                      <span className={`px-1 py-0.5 rounded text-[7px] font-bold ${
                        agentName === 'claude' ? 'bg-green-500/20 text-green-400' :
                        agentName === 'gemini' ? 'bg-blue-500/20 text-blue-400' :
                                                  'bg-yellow-500/20 text-yellow-400'
                      }`}>
                        {agentName}
                      </span>
                    )}
                    {chain.request && (
                      <span
                        className="text-[7px] text-[#777] truncate max-w-[80px]"
                        title={chain.request}
                      >
                        {chain.request}
                      </span>
                    )}
                  </div>
                  {chain.updated_at && (
                    <span className="text-[7px] text-[#555] font-mono shrink-0">
                      {new Date(chain.updated_at).toLocaleTimeString()}
                    </span>
                  )}
                </div>

                {/* 스킬 체인 흐름: 1-① → 1-③ → 1-⑤ */}
                <div className="flex items-center gap-1 flex-wrap">
                  {chain.steps.map((step, i) => {
                    // N-M 레이블에서 M이 스킬 번호 → 원형 숫자로 변환
                    const circleNum = CIRCLE_NUMS[step.skill_num] ?? step.skill_num;
                    return (
                      <div key={i} className="flex items-center gap-1">
                        {i > 0 && <span className="text-[#444] text-[8px]">→</span>}
                        <div
                          className={`px-1.5 py-0.5 rounded border text-[8px] font-mono font-bold ${stepColor(step.status)}`}
                          title={step.summary || step.skill_name}
                        >
                          {stepIcon(step.status)}{' '}
                          {/* 표기: T번호-스킬원형번호 (예: 1-③) */}
                          <span className="opacity-60">{termId}-</span>{circleNum}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* 현재 실행 중인 스킬 요약 */}
                {chain.status === 'running' && (() => {
                  const running = chain.steps.find(s => s.status === 'running');
                  const lastDone = [...chain.steps].reverse().find(s => s.status === 'done');
                  if (running) return (
                    <div className="mt-1 text-[7px] text-[#888] truncate">
                      ⚡ {running.skill_name} 실행 중...
                    </div>
                  );
                  if (lastDone?.summary) return (
                    <div className="mt-1 text-[7px] text-[#777] truncate">
                      ✅ {lastDone.summary}
                    </div>
                  );
                  return null;
                })()}
              </div>
            );
          })}
        </div>
      ) : (
        /* 활성 체인 없을 때 안내 */
        <div className="text-center text-[#858585] text-xs py-6 flex flex-col items-center gap-2 italic shrink-0">
          <Network className="w-7 h-7 opacity-20" />
          <span>실행 중인 스킬 체인 없음</span>
          <span className="text-[9px]">
            /vibe-orchestrate --terminal N 으로 실행
          </span>
        </div>
      )}

      {/* ── ③ 터미널별 에이전트 현황 그리드 (T1~T8) ──────────────────────── */}
      {orchStatus && Object.keys(orchStatus.terminal_agents ?? {}).length > 0 && (
        <div className="shrink-0 p-2 rounded border border-white/10">
          <div className="text-[9px] font-bold text-[#969696] mb-1.5 uppercase tracking-wider">
            터미널별 에이전트
          </div>
          <div className="grid grid-cols-4 gap-1">
            {Array.from({ length: 8 }, (_, i) => {
              const slot = String(i + 1);
              const agent = (orchStatus.terminal_agents ?? {})[slot] || '';
              const st = agent ? (orchStatus.agent_status ?? {})[agent] : null;
              const color = !agent
                ? 'border-white/5 bg-white/3 text-[#555]'
                : agent === 'claude'
                  ? 'border-green-500/40 bg-green-500/10 text-green-400'
                  : agent === 'gemini'
                    ? 'border-blue-500/40 bg-blue-500/10 text-blue-400'
                    : 'border-yellow-500/40 bg-yellow-500/10 text-yellow-400';
              const dotColor = !st ? '' : st.state === 'active' ? 'bg-green-400' : st.state === 'idle' ? 'bg-yellow-400' : 'bg-gray-500';
              return (
                <div key={slot} className={`flex flex-col items-center gap-0.5 p-1 rounded border text-[8px] font-mono ${color}`}>
                  <span className="text-[7px] text-[#555] font-bold">T{slot}</span>
                  {agent ? (
                    <div className="flex items-center gap-0.5">
                      {dotColor && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />}
                      <span className="truncate font-bold" style={{ maxWidth: 36 }}>{agent}</span>
                    </div>
                  ) : (
                    <span className="opacity-30">—</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── ④ 최근 오케스트레이터 자동 액션 로그 ───────────────────────────── */}
      {orchStatus?.recent_actions && orchStatus.recent_actions.length > 0 ? (
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          <div className="p-2 rounded border border-white/10">
            <div className="text-[9px] font-bold text-[#969696] mb-1.5">최근 자동 액션</div>
            {orchStatus.recent_actions.slice(0, 8).map((act, i) => {
              const actionColor =
                act.action === 'auto_assign'   ? 'text-green-400' :
                act.action === 'idle_agent'     ? 'text-yellow-400' :
                act.action.includes('overload') ? 'text-red-400' :
                                                  'text-[#858585]';
              return (
                <div key={i} className="flex items-start gap-1.5 py-0.5 hover:bg-white/3 rounded px-1">
                  <span className={`text-[8px] font-mono shrink-0 mt-0.5 ${actionColor}`}>{act.action}</span>
                  <span className="text-[9px] text-[#cccccc] flex-1 break-words leading-tight">{act.detail}</span>
                  <span className="text-[8px] text-[#858585] shrink-0 font-mono">{act.timestamp?.slice(11, 16)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="p-2 rounded border border-white/5 text-center text-[9px] text-[#858585] italic">
          자동 액션 기록 없음
        </div>
      )}
    </div>
  );
}
