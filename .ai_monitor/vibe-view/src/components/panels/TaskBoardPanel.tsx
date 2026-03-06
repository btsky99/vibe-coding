/**
 * ------------------------------------------------------------------------
 * 파일명: TaskBoardPanel.tsx
 * 설명: 스킬 실행 결과 + 오케스트레이션 칸반을 통합한 태스크보드 패널.
 *       [섹션1] Live 파이프라인 — 현재 실행 중인 터미널별 스킬체인 수평 레인 뷰
 *       [섹션2] 터미널 탭 + 칸반 컬럼 (분석 중→수정 중→검증 중→완료)
 *       [섹션3] 완료 기록 — 이전 세션 스킬 파이프라인 히스토리
 *
 *       SkillResultsPanel + KanbanPanel의 중복 데이터 폴링 제거.
 *       두 패널이 같은 /api/orchestrator/skill-chain을 폴링했던 문제 해결.
 *
 * REVISION HISTORY:
 * - 2026-03-06 Claude: 최초 구현 — SkillResultsPanel + KanbanPanel 통합
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useMemo } from 'react';
import {
  Monitor, Cpu, CheckCircle, Clock, AlertCircle, Loader,
  Zap, CheckCircle2, SkipForward, BarChart3, Radio
} from 'lucide-react';
import { API_BASE } from '../../constants';

// ─── 공유 타입 ────────────────────────────────────────────────────────────────

interface LiveStep {
  skill_name: string;
  status: string; // pending | running | done | failed
}

interface LiveChain {
  request: string;
  steps: LiveStep[];
  terminal_id?: number;
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

interface RunRecord {
  run_id: string;
  task: string;
  cli: string;
  status: 'running' | 'done' | 'error';
  ts: string;
  output_preview: string[];
}

interface SkillResultEntry {
  skill: string;
  status: string; // done | skipped | error | running
  summary: string;
}

interface SkillSessionResult {
  session_id: string;
  terminal_id?: number;
  request: string;
  results: SkillResultEntry[];
  completed_at: string;
}

// ─── 스킬명 한글 매핑 ────────────────────────────────────────────────────────
const SKILL_LABELS: Record<string, string> = {
  'debug':        '🔍 디버그',
  'tdd':          '🧪 테스트',
  'brainstorm':   '💡 아이디어',
  'write-plan':   '📝 계획작성',
  'execute-plan': '⚡ 계획실행',
  'execute':      '⚡ 계획실행',
  'code-review':  '🔎 코드리뷰',
  'release':      '🚀 릴리스',
  'orchestrate':  '🤖 오케스트',
};

// 칸반 컬럼 정의
const STAGES = [
  { id: 'analyzing' as const, label: '분석 중',  headerColor: 'bg-blue-700',   cardBorder: 'bg-blue-500/10 border-blue-500/30',   dotColor: 'bg-blue-400',   textColor: 'text-blue-300'   },
  { id: 'modifying' as const, label: '수정 중',  headerColor: 'bg-amber-600',  cardBorder: 'bg-amber-500/10 border-amber-500/30', dotColor: 'bg-amber-400',  textColor: 'text-amber-300'  },
  { id: 'verifying' as const, label: '검증 중',  headerColor: 'bg-purple-700', cardBorder: 'bg-purple-500/10 border-purple-500/30',dotColor: 'bg-purple-400', textColor: 'text-purple-300' },
  { id: 'done'      as const, label: '완료',     headerColor: 'bg-green-700',  cardBorder: 'bg-green-500/10 border-green-500/30',  dotColor: 'bg-green-400',  textColor: 'text-green-300'  },
] as const;

type StageId = typeof STAGES[number]['id'];

// 터미널 배지 색상
const TERMINAL_COLORS: Record<number, string> = {
  1: 'bg-blue-500/30 text-blue-300 border-blue-500/40',
  2: 'bg-green-500/30 text-green-300 border-green-500/40',
  3: 'bg-yellow-500/30 text-yellow-300 border-yellow-500/40',
  4: 'bg-purple-500/30 text-purple-300 border-purple-500/40',
  5: 'bg-pink-500/30 text-pink-300 border-pink-500/40',
  6: 'bg-orange-500/30 text-orange-300 border-orange-500/40',
  7: 'bg-cyan-500/30 text-cyan-300 border-cyan-500/40',
  8: 'bg-red-500/30 text-red-300 border-red-500/40',
};

// ─── 헬퍼 함수 ────────────────────────────────────────────────────────────────

function relativeTime(iso: string | undefined): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return '';
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ko-KR', {
      month: 'numeric', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

// run의 칸반 단계 추론 (running→modifying, done/error→done, pending→analyzing)
function inferRunStage(run: RunRecord, terminalStage?: string): StageId {
  if (run.status === 'done' || run.status === 'error') return 'done';
  if (terminalStage) {
    if (terminalStage === 'analyzing') return 'analyzing';
    if (terminalStage === 'modifying') return 'modifying';
    if (terminalStage === 'verifying') return 'verifying';
    if (terminalStage === 'done')      return 'done';
  }
  return 'analyzing';
}

// LiveStep 상태 → 칸반 단계 매핑
function stepToStage(status: string): StageId {
  if (status === 'done' || status === 'failed') return 'done';
  if (status === 'running')                     return 'modifying';
  return 'analyzing'; // pending
}

const statusIcon = (status: string) => {
  switch (status) {
    case 'done':    return <CheckCircle2 className="w-3 h-3 text-green-400 shrink-0" />;
    case 'skipped': return <SkipForward  className="w-3 h-3 text-[#858585] shrink-0" />;
    case 'error':   return <AlertCircle  className="w-3 h-3 text-red-400 shrink-0" />;
    default:        return <Clock        className="w-3 h-3 text-yellow-400 shrink-0" />;
  }
};

const statusBadgeCls = (status: string) => {
  switch (status) {
    case 'done':    return 'bg-green-500/20 text-green-400';
    case 'skipped': return 'bg-white/10 text-[#858585]';
    case 'error':   return 'bg-red-500/20 text-red-400';
    default:        return 'bg-yellow-500/20 text-yellow-400';
  }
};

const STATUS_KR: Record<string, string> = {
  'done': '완료', 'error': '오류', 'skipped': '건너뜀', 'running': '실행중',
};

// ─── 섹션1: Live 파이프라인 레인 뷰 ──────────────────────────────────────────
/**
 * LivePipelineSection
 * 현재 실행 중인 터미널별로 수평 파이프라인 레인을 표시합니다.
 * [오케스트레이션] → [스킬1] → [스킬2] 순서로 단계별 진행 상태를 시각화합니다.
 */
function LivePipelineSection({ chains }: { chains: Record<string, LiveChain> }) {
  const list = Object.entries(chains).sort(([a], [b]) => a.localeCompare(b));
  if (list.length === 0) return null;

  return (
    <div className="shrink-0 rounded border border-green-500/30 bg-green-500/5 p-2 flex flex-col gap-2">
      {/* 섹션 헤더 */}
      <div className="flex items-center gap-1.5">
        <Radio className="w-3 h-3 text-green-400 animate-pulse" />
        <span className="text-[10px] font-bold text-green-400 uppercase tracking-wider">실행 중</span>
        <span className="text-[9px] text-green-400/50">{list.length}개 터미널</span>
      </div>

      {/* 터미널별 파이프라인 레인 */}
      {list.map(([tid, chain]) => (
        <div key={tid} className="flex items-stretch gap-0 overflow-x-auto custom-scrollbar pb-1">
          {/* 오케스트레이션 레인 */}
          <div className="shrink-0 w-[90px] flex flex-col gap-1 rounded-l border border-blue-500/40 bg-blue-500/8 p-1.5">
            <span className="text-[8px] font-black text-blue-400 uppercase tracking-wide leading-tight">오케스트레이션</span>
            <span className="text-[7px] font-bold text-blue-300/50">T{tid}</span>
            {chain.request && (
              <span className="text-[8px] text-white/45 leading-tight line-clamp-3 break-all">{chain.request}</span>
            )}
            {/* 스킬 목록 미리보기 */}
            <div className="flex flex-col gap-0.5 mt-auto pt-1">
              {chain.steps.map((step, i) => {
                const label = SKILL_LABELS[step.skill_name.replace(/^vibe-/, '')] ?? step.skill_name.replace(/^vibe-/, '');
                return (
                  <span key={i} className="text-[7px] text-blue-300/60 font-mono flex items-center gap-0.5">
                    <span className="text-blue-400/40">→</span> {label}
                  </span>
                );
              })}
            </div>
          </div>

          {/* 각 스킬 레인 */}
          {chain.steps.map((step, i) => {
            const label = SKILL_LABELS[step.skill_name.replace(/^vibe-/, '')] ?? step.skill_name.replace(/^vibe-/, '');
            const s = step.status;
            const isRunning = s === 'running';
            const isDone    = s === 'done';
            const isFailed  = s === 'failed';
            const isLast    = i === chain.steps.length - 1;

            const borderCls = isRunning ? 'border-yellow-400/60 bg-yellow-400/8'
                            : isDone    ? 'border-green-500/40 bg-green-500/8'
                            : isFailed  ? 'border-red-500/40 bg-red-500/8'
                            :             'border-white/8 bg-white/3';
            const labelCls  = isRunning ? 'text-yellow-300 animate-pulse'
                            : isDone    ? 'text-green-400'
                            : isFailed  ? 'text-red-400'
                            :             'text-white/20';
            const arrowCls  = isRunning ? 'bg-yellow-400/40 border-l-yellow-400/40'
                            : isDone    ? 'bg-green-500/35 border-l-green-500/35'
                            :             'bg-white/10 border-l-white/10';
            const icon = isRunning ? '●' : isDone ? '✓' : isFailed ? '✗' : '○';

            return (
              <div key={i} className="flex items-stretch">
                {/* 화살표 */}
                <div className="flex items-center shrink-0 px-0.5">
                  <div className={`w-2.5 h-px ${arrowCls}`} />
                  <div className={`w-0 h-0 border-t-[3px] border-t-transparent border-b-[3px] border-b-transparent border-l-[4px] ${arrowCls}`} />
                </div>
                {/* 스킬 카드 */}
                <div className={`shrink-0 w-[82px] flex flex-col gap-1 border ${borderCls} p-1.5 ${isLast ? 'rounded-r' : ''}`}>
                  <span className={`text-[8px] font-black leading-tight ${labelCls}`}>{icon} {label}</span>
                  <span className="text-[7px] text-white/18 font-mono leading-tight break-all">{step.skill_name}</span>
                  {!isRunning && !isDone && !isFailed && (
                    <span className="text-[6px] text-white/15 italic">대기 중</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ─── 섹션2: 칸반 보드 ────────────────────────────────────────────────────────
/**
 * KanbanSection
 * T1~T8 터미널 탭 + 4컬럼 칸반 보드.
 * liveChains 우선 사용 (스킬체인 데이터), 없으면 liveRuns 폴백 사용.
 */
interface KanbanSectionProps {
  terminals: Record<string, TerminalStatus>;
  liveRuns: Record<string, RunRecord[]>;
  liveChains: Record<string, LiveChain>;
}

function KanbanSection({ terminals, liveRuns, liveChains }: KanbanSectionProps) {
  const [selectedTab, setSelectedTab] = useState<string>('T2');

  // 실행 중인 터미널이 생기면 자동으로 해당 탭 선택
  useEffect(() => {
    const runningTid = Object.entries(terminals).find(([, s]) => s.status === 'running')?.[0];
    if (runningTid) {
      setSelectedTab(prev => {
        const prevStatus = terminals[prev];
        if (!prevStatus || prevStatus.status === 'idle' || prevStatus.status === 'done') {
          return runningTid;
        }
        return prev;
      });
    }
  }, [terminals]);

  const currentTerminal = terminals[selectedTab];
  const currentRuns = liveRuns[selectedTab] ?? [];
  const totalRunning = Object.values(terminals).filter(t => t.status === 'running').length;

  // 칸반 컬럼별 데이터 분류
  // liveChains 있으면 스킬 단계 카드, 없으면 RunRecord 카드
  const useLiveChains = Object.keys(liveChains).length > 0;
  const runsByStage: Record<StageId, RunRecord[]> = { analyzing: [], modifying: [], verifying: [], done: [] };
  if (!useLiveChains) {
    for (const run of currentRuns) {
      const stage = inferRunStage(run, currentTerminal?.pipeline_stage);
      runsByStage[stage].push(run);
    }
  }

  const activeRunId = currentTerminal?.run_id;

  return (
    <div className="flex flex-col gap-2 flex-1 min-h-0">
      {/* 터미널 탭 바 + 통계 */}
      <div className="flex items-center gap-2 shrink-0">
        <Monitor className="w-3.5 h-3.5 text-primary shrink-0" />
        <div className="flex gap-1 flex-wrap flex-1">
          {(['T1','T2','T3','T4','T5','T6','T7','T8'] as const).map(tid => {
            const tStatus = terminals[tid];
            const isRunning = tStatus?.status === 'running';
            const runCount = liveRuns[tid]?.length ?? 0;
            return (
              <button
                key={tid}
                onClick={() => setSelectedTab(tid)}
                className={`relative flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${
                  selectedTab === tid
                    ? 'bg-primary text-white'
                    : isRunning
                    ? 'bg-amber-500/20 text-amber-300 hover:bg-amber-500/30'
                    : 'bg-white/5 text-[#666] hover:text-[#aaa] hover:bg-white/8'
                }`}
              >
                {isRunning && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />}
                <span>{tid}</span>
                {tStatus?.cli && (
                  <span className={`text-[7px] opacity-70 ${tStatus.cli === 'gemini' ? 'text-blue-300' : 'text-green-300'}`}>
                    {tStatus.cli === 'gemini' ? 'G' : 'C'}
                  </span>
                )}
                {runCount > 0 && !isRunning && (
                  <span className="text-[7px] bg-white/10 px-1 rounded">{runCount}</span>
                )}
              </button>
            );
          })}
        </div>
        {/* 전체 통계 */}
        <span className="text-[9px] text-[#777] shrink-0">
          활성 <span className={`font-bold ${totalRunning > 0 ? 'text-amber-400' : 'text-[#555]'}`}>{totalRunning}</span>
        </span>
      </div>

      {/* 선택된 터미널 현재 작업 배너 */}
      <div className={`shrink-0 rounded px-2.5 py-1.5 flex items-center gap-2 ${
        currentTerminal?.status === 'running' ? 'bg-amber-500/10 border border-amber-500/30'
        : currentTerminal?.status === 'error'  ? 'bg-red-500/10 border border-red-500/30'
        :                                        'bg-white/5 border border-white/8'
      }`}>
        {currentTerminal?.status === 'running' ? (
          <Loader className="w-3 h-3 text-amber-400 animate-spin shrink-0" />
        ) : currentTerminal?.status === 'done' ? (
          <CheckCircle className="w-3 h-3 text-green-400 shrink-0" />
        ) : currentTerminal?.status === 'error' ? (
          <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />
        ) : (
          <Clock className="w-3 h-3 text-[#555] shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <p className={`text-[9px] font-bold ${
            currentTerminal?.status === 'running' ? 'text-amber-300'
            : currentTerminal?.status === 'error' ? 'text-red-300'
            : currentTerminal?.status === 'done'  ? 'text-green-300' : 'text-[#555]'
          }`}>
            {currentTerminal?.status === 'running' ? '실행 중'
             : currentTerminal?.status === 'done'  ? '완료'
             : currentTerminal?.status === 'error' ? '오류' : `${selectedTab} 대기 중`}
            {currentTerminal?.cli && (
              <span className={`ml-1.5 text-[7px] font-bold px-1 py-0.5 rounded ${
                currentTerminal.cli === 'gemini' ? 'bg-blue-500/20 text-blue-400' : 'bg-green-500/20 text-green-400'
              }`}>{currentTerminal.cli}</span>
            )}
          </p>
          {currentTerminal?.task && (
            <p className="text-[8px] text-[#aaa] leading-tight line-clamp-1 mt-0.5">{currentTerminal.task}</p>
          )}
          {currentTerminal?.last_line && currentTerminal.status === 'running' && (
            <p className="text-[7px] text-[#666] font-mono leading-tight line-clamp-1 mt-0.5">{currentTerminal.last_line}</p>
          )}
        </div>
        {currentTerminal?.ts && (
          <span className="text-[8px] text-[#555] shrink-0">{relativeTime(currentTerminal.ts)}</span>
        )}
      </div>

      {/* 칸반 컬럼 (가로 스크롤 허용) */}
      <div className="flex-1 overflow-x-auto overflow-y-hidden min-h-[140px]">
        <div className="flex gap-2 h-full px-0.5 pb-1" style={{ minWidth: 'max-content' }}>
          {STAGES.map(stage => {
            // liveChains 있으면 스킬 카드 수집
            const skillCards: Array<{ tid: string; step: LiveStep; request: string }> = [];
            if (useLiveChains) {
              for (const [tid, chain] of Object.entries(liveChains)) {
                for (const step of chain.steps) {
                  if (stepToStage(step.status) === stage.id) {
                    skillCards.push({ tid, step, request: chain.request });
                  }
                }
              }
            }
            const colRuns = useLiveChains ? [] : runsByStage[stage.id];
            const totalCount = skillCards.length + colRuns.length;
            const isCurrentStage = currentTerminal?.status === 'running' && currentTerminal.pipeline_stage === stage.id;

            return (
              <div
                key={stage.id}
                className={`flex flex-col w-56 shrink-0 rounded overflow-hidden border ${isCurrentStage ? 'border-white/25' : 'border-white/8'}`}
              >
                {/* 컬럼 헤더 */}
                <div className={`${stage.headerColor} px-2.5 py-1.5 flex items-center justify-between shrink-0`}>
                  <div className="flex items-center gap-1.5">
                    {isCurrentStage && <span className={`w-1.5 h-1.5 rounded-full ${stage.dotColor} animate-pulse`} />}
                    <span className="text-[10px] font-bold text-white">{stage.label}</span>
                  </div>
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-white/25 text-white">{totalCount}</span>
                </div>

                {/* 컬럼 바디 */}
                <div className="flex-1 overflow-y-auto bg-[#161616] p-1.5 custom-scrollbar">
                  {/* 스킬체인 카드 (liveChains 모드) */}
                  {skillCards.map(({ tid, step, request }, i) => {
                    const rawKey = step.skill_name.replace(/^vibe-/, '');
                    const label = SKILL_LABELS[rawKey] ?? rawKey;
                    const isRunning = step.status === 'running';
                    const isFailed  = step.status === 'failed';
                    const cardCls = isRunning ? 'bg-amber-500/10 border-amber-500/30'
                                  : isFailed  ? 'bg-red-500/10 border-red-500/30'
                                  : stage.id === 'done' ? 'bg-green-500/8 border-green-500/25'
                                  :                       'bg-blue-500/8 border-blue-500/20';
                    return (
                      <div key={i} className={`rounded border p-1.5 mb-1.5 ${cardCls}`}>
                        <div className="flex items-center justify-between gap-1 mb-1">
                          <span className={`text-[9px] font-bold leading-tight ${
                            isRunning ? 'text-amber-300 animate-pulse'
                            : isFailed ? 'text-red-300'
                            : stage.id === 'done' ? 'text-green-300' : 'text-blue-300'
                          }`}>{label}</span>
                          {isRunning ? <Loader className="w-2.5 h-2.5 text-amber-400 animate-spin shrink-0" />
                          : isFailed  ? <AlertCircle className="w-2.5 h-2.5 text-red-400 shrink-0" />
                          : stage.id === 'done' ? <CheckCircle className="w-2.5 h-2.5 text-green-400 shrink-0" />
                          : <Clock className="w-2.5 h-2.5 text-[#555] shrink-0" />}
                        </div>
                        <p className="text-[7px] text-white/25 font-mono">{step.skill_name}</p>
                        {request && (
                          <p className="text-[7px] text-white/20 leading-tight mt-0.5 line-clamp-2">{request}</p>
                        )}
                        <div className="mt-1">
                          <span className="text-[7px] font-bold bg-white/8 text-white/40 px-1 py-0.5 rounded">T{tid}</span>
                        </div>
                      </div>
                    );
                  })}

                  {/* RunRecord 카드 (폴백 모드) */}
                  {colRuns.map(run => {
                    const isActive = run.run_id === activeRunId || run.status === 'running';
                    const stageInfo = STAGES.find(s => s.id === stage.id);
                    return (
                      <div key={run.run_id} className={`rounded border p-1.5 mb-1.5 transition-all ${
                        isActive ? `${stageInfo?.cardBorder ?? 'bg-white/5 border-white/10'} shadow-sm`
                                 : 'bg-[#1a1a1a] border-white/8 opacity-65'
                      }`}>
                        <p className={`text-[9px] leading-tight mb-1 font-medium line-clamp-2 ${run.status === 'error' ? 'text-red-300' : 'text-[#ccc]'}`}>
                          {run.task || '(내용 없음)'}
                        </p>
                        {isActive && run.output_preview?.length > 0 && (
                          <p className="text-[8px] text-[#777] font-mono leading-tight mb-1 line-clamp-1 bg-black/20 px-1 py-0.5 rounded">
                            {run.output_preview[run.output_preview.length - 1]}
                          </p>
                        )}
                        <div className="flex items-center justify-between gap-1">
                          <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${
                            run.cli === 'claude' ? 'bg-green-500/15 text-green-400'
                            : run.cli === 'gemini' ? 'bg-blue-500/15 text-blue-400'
                            : 'bg-white/8 text-[#777]'
                          }`}>{run.cli || 'AI'}</span>
                          <span className="text-[8px] text-[#555]">{relativeTime(run.ts)}</span>
                          {run.status === 'running' && <Loader className="w-2.5 h-2.5 text-amber-400 animate-spin shrink-0" />}
                          {run.status === 'done' && <CheckCircle className="w-2.5 h-2.5 text-green-400 shrink-0" />}
                          {run.status === 'error' && <AlertCircle className="w-2.5 h-2.5 text-red-400 shrink-0" />}
                        </div>
                      </div>
                    );
                  })}

                  {totalCount === 0 && (
                    <div className="text-center text-[#333] text-[9px] py-4 italic">없음</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── 섹션3: 완료 기록 ────────────────────────────────────────────────────────
/**
 * HistorySection
 * 완료된 스킬 세션 목록. 터미널 필터 탭 + 파이프라인 미니뷰 + 클릭으로 상세 토글.
 */
function HistorySection({ sessions }: { sessions: SkillSessionResult[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterTerminal, setFilterTerminal] = useState<string>('all');
  const [isCollapsed, setIsCollapsed] = useState(false);

  const terminalIds = useMemo(() => {
    const ids = new Set<number>();
    sessions.forEach(s => { if (s.terminal_id) ids.add(s.terminal_id); });
    return Array.from(ids).sort();
  }, [sessions]);

  const filteredSessions = useMemo(() => {
    if (filterTerminal === 'all') return sessions;
    const tid = parseInt(filterTerminal, 10);
    return sessions.filter(s => s.terminal_id === tid || (!s.terminal_id && tid === 0));
  }, [sessions, filterTerminal]);

  const stats = useMemo(() => {
    let done = 0, total = 0, error = 0;
    sessions.forEach(s => s.results.forEach(r => {
      total++;
      if (r.status === 'done') done++;
      if (r.status === 'error') error++;
    }));
    return { done, total, error, sessions: sessions.length };
  }, [sessions]);

  const terminalBadgeCls = (id?: number) =>
    id ? (TERMINAL_COLORS[id] ?? 'bg-white/10 text-white/60 border-white/20')
       : 'bg-white/5 text-white/30 border-white/10';

  return (
    <div className="flex flex-col border-t border-white/8 pt-2 gap-2 shrink-0" style={{ maxHeight: isCollapsed ? undefined : '45%' }}>
      {/* 섹션 헤더 (클릭으로 접기/펼치기) */}
      <div
        className="flex items-center gap-2 cursor-pointer select-none shrink-0"
        onClick={() => setIsCollapsed(c => !c)}
      >
        <Zap className="w-3.5 h-3.5 text-yellow-400" />
        <span className="text-[10px] font-bold text-white/60">완료 기록</span>
        <span className="text-[8px] text-[#555]">{isCollapsed ? '▶' : '▼'}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {stats.total > 0 && (
            <span className="flex items-center gap-1 text-[9px] text-[#858585]">
              <BarChart3 className="w-3 h-3" />
              <span className="text-green-400 font-bold">{stats.done}</span>
              <span>/</span><span>{stats.total}</span>
              {stats.error > 0 && <span className="text-red-400 font-bold ml-0.5">({stats.error}오류)</span>}
            </span>
          )}
          <span className="text-[9px] text-[#858585]">{stats.sessions}건</span>
        </div>
      </div>

      {!isCollapsed && (
        <>
          {/* 터미널 필터 탭 */}
          {terminalIds.length > 1 && (
            <div className="flex gap-1 flex-wrap shrink-0">
              <button
                onClick={() => setFilterTerminal('all')}
                className={`text-[9px] font-bold px-2 py-0.5 rounded border transition-colors ${
                  filterTerminal === 'all'
                    ? 'bg-primary/30 text-primary border-primary/50'
                    : 'bg-white/5 text-[#858585] border-white/10 hover:border-white/20'
                }`}
              >전체</button>
              {terminalIds.map(tid => (
                <button
                  key={tid}
                  onClick={() => setFilterTerminal(String(tid))}
                  className={`text-[9px] font-bold px-2 py-0.5 rounded border transition-colors ${
                    filterTerminal === String(tid)
                      ? `${TERMINAL_COLORS[tid] ?? ''} border-opacity-60`
                      : 'bg-white/5 text-[#858585] border-white/10 hover:border-white/20'
                  }`}
                >T{tid}</button>
              ))}
            </div>
          )}

          {/* 세션 목록 */}
          <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
            {filteredSessions.length === 0 ? (
              <div className="text-center text-[#858585] text-xs py-6 flex flex-col items-center gap-2 italic">
                <Zap className="w-6 h-6 opacity-20" />
                {sessions.length === 0 ? '아직 스킬 실행 기록이 없습니다' : '선택한 터미널에 결과가 없습니다'}
              </div>
            ) : (
              filteredSessions.map(session => {
                const isExpanded = expandedId === session.session_id;
                const doneCount = session.results.filter(r => r.status === 'done').length;
                const totalCount = session.results.length;

                return (
                  <div key={session.session_id} className="rounded border border-white/10 bg-white/2 hover:border-white/20 transition-colors overflow-hidden">
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : session.session_id)}
                      className="w-full p-2 text-left flex flex-col gap-1"
                    >
                      {/* 요약 헤더 */}
                      <div className="flex items-start gap-1.5">
                        {session.terminal_id ? (
                          <span className={`text-[8px] font-black px-1 py-0.5 rounded border shrink-0 mt-0.5 ${terminalBadgeCls(session.terminal_id)}`}>
                            T{session.terminal_id}
                          </span>
                        ) : (
                          <Zap className="w-3 h-3 text-yellow-400 shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1 min-w-0">
                          {/* 마지막 summary 우선, 없으면 request */}
                          <span className="text-[10px] text-white leading-tight line-clamp-1 block">
                            {(() => {
                              const summaries = session.results.map(r => r.summary).filter(s => s?.trim());
                              return summaries.length > 0 ? summaries[summaries.length - 1] : session.request;
                            })()}
                          </span>
                          <span className="text-[8px] text-[#555] leading-tight line-clamp-1 block mt-0.5">
                            지시: {session.request}
                          </span>
                        </div>
                        <span className="text-[8px] text-[#555] font-mono shrink-0">{formatTime(session.completed_at)}</span>
                      </div>

                      {/* 파이프라인 미니뷰 (가로 레인) */}
                      <div className="flex items-stretch gap-0 overflow-x-auto custom-scrollbar">
                        {/* 오케스트레이션 레인 */}
                        <div className="shrink-0 w-[52px] flex flex-col gap-0.5 rounded-l border border-blue-500/30 bg-blue-500/6 px-1 py-1">
                          <span className="text-[6px] font-black text-blue-400/80 uppercase">오케스트</span>
                          <span className="text-[6px] text-white/30 leading-tight line-clamp-2">{session.request}</span>
                        </div>
                        {session.results.map((r, i) => {
                          const label = SKILL_LABELS[r.skill.replace('vibe-', '')] ?? r.skill.replace('vibe-', '');
                          const isLast = i === session.results.length - 1;
                          const arrowCls = r.status === 'done'    ? 'bg-green-500/30 border-l-green-500/30'
                                         : r.status === 'error'   ? 'bg-red-500/30 border-l-red-500/30'
                                         : r.status === 'running' ? 'bg-yellow-400/30 border-l-yellow-400/30'
                                         :                          'bg-white/8 border-l-white/8';
                          return (
                            <div key={i} className="flex items-stretch">
                              <div className="flex items-center shrink-0">
                                <div className={`w-2 h-px ${arrowCls}`} />
                                <div className={`w-0 h-0 border-t-[2px] border-t-transparent border-b-[2px] border-b-transparent border-l-[3px] ${arrowCls}`} />
                              </div>
                              <div className={`shrink-0 w-[62px] flex flex-col gap-0.5 border border-current/30 px-1 py-1 ${statusBadgeCls(r.status)} ${isLast ? 'rounded-r' : ''}`}>
                                <div className="flex items-center gap-0.5">
                                  {statusIcon(r.status)}
                                  <span className="text-[7px] font-bold leading-tight truncate">{label}</span>
                                </div>
                                {r.summary ? (
                                  <span className="text-[6px] text-[#aaa] leading-tight line-clamp-1">{r.summary}</span>
                                ) : (
                                  <span className="text-[6px] text-[#444] italic">{STATUS_KR[r.status] ?? r.status}</span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      {/* 완료율 */}
                      <div className="flex items-center gap-2 pl-1">
                        <span className={`text-[9px] font-bold ${doneCount === totalCount ? 'text-green-400' : 'text-[#858585]'}`}>
                          {doneCount}/{totalCount} 완료
                        </span>
                      </div>
                    </button>

                    {/* 상세 토글 */}
                    {isExpanded && (
                      <div className="border-t border-white/5 px-2 pb-2 pt-1.5 space-y-1.5">
                        {session.results.map((r, i) => (
                          <div key={i} className="flex items-start gap-1.5">
                            {statusIcon(r.status)}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1 flex-wrap">
                                <span className="text-[10px] font-bold text-white">
                                  {SKILL_LABELS[r.skill.replace('vibe-', '')] ?? r.skill.replace('vibe-', '')}
                                </span>
                                <span className="text-[8px] text-white/25 font-mono">({r.skill})</span>
                                <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${statusBadgeCls(r.status)}`}>
                                  {STATUS_KR[r.status] ?? r.status}
                                </span>
                              </div>
                              {r.summary && (
                                <p className="text-[9px] text-[#aaa] leading-tight mt-0.5 break-words whitespace-pre-wrap">{r.summary}</p>
                              )}
                            </div>
                          </div>
                        ))}
                        <div className="text-[8px] text-[#333] font-mono pt-1 border-t border-white/5">
                          #{session.session_id}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── 메인 컴포넌트 ────────────────────────────────────────────────────────────
/**
 * TaskBoardPanel — 스킬 실행 결과 + 오케스트레이션 칸반 통합 뷰
 *
 * [섹션1] Live 파이프라인 레인 — 현재 실행 중인 스킬체인 수평 시각화
 * [섹션2] 터미널 탭 + 칸반 보드 — 단계별(분석→수정→검증→완료) 카드 뷰
 * [섹션3] 완료 기록 — 이전 세션 히스토리 + 미니 파이프라인
 *
 * 데이터 소스:
 * - /api/orchestrator/skill-chain : 3초 — 라이브 스킬체인 (중앙화, 중복 제거)
 * - /api/agent/terminals          : 3초 — 터미널별 실행 상태
 * - /api/agent/live-runs          : 10초 — 터미널별 실행 히스토리
 * - /api/skill-results            : 10초 — 완료된 세션 결과
 */
export default function TaskBoardPanel() {
  // ── 데이터 상태 ──────────────────────────────────────────────────────────
  // 현재 실행 중인 스킬체인 (터미널별) — 3초 폴링
  const [liveChains, setLiveChains] = useState<Record<string, LiveChain>>({});
  // 터미널별 실행 상태 — 3초 폴링
  const [terminals, setTerminals] = useState<Record<string, TerminalStatus>>({});
  // 터미널별 실행 히스토리 — 10초 폴링
  const [liveRuns, setLiveRuns] = useState<Record<string, RunRecord[]>>({});
  // 완료된 스킬 세션 — 10초 폴링
  const [sessions, setSessions] = useState<SkillSessionResult[]>([]);

  // ── /api/orchestrator/skill-chain 폴링 (3초) ─────────────────────────────
  // SkillResultsPanel: running/pending만 추출 / KanbanPanel: 모든 steps 추출
  // 여기서는 running/pending 있는 체인만 → liveChains (섹션1+2 공유)
  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(r => r.json())
        .then(data => {
          const active: Record<string, LiveChain> = {};
          const tmap: Record<string, any> = data?.terminals ?? {};
          for (const [tid, chain] of Object.entries(tmap)) {
            const steps: LiveStep[] = (chain as any)?.steps ?? [];
            // running/pending 스텝이 있으면 섹션1(Live)에 표시
            const hasActive = steps.some(s => s.status === 'running' || s.status === 'pending');
            if (hasActive) {
              active[tid] = {
                request: (chain as any)?.request ?? '',
                steps,
                terminal_id: parseInt(tid, 10) || undefined,
              };
            }
          }
          setLiveChains(active);
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  // ── /api/agent/terminals 폴링 (3초) ──────────────────────────────────────
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/agent/terminals`)
        .then(r => r.json())
        .then(data => { if (data && typeof data === 'object') setTerminals(data); })
        .catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  // ── /api/agent/live-runs 폴링 (10초) ────────────────────────────────────
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/agent/live-runs`)
        .then(r => r.json())
        .then(data => { if (data && typeof data === 'object') setLiveRuns(data); })
        .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  // ── /api/skill-results 폴링 (10초) ──────────────────────────────────────
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/skill-results`)
        .then(r => r.json())
        .then(data => setSessions(Array.isArray(data) ? data : []))
        .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  // 전체 실행 중 터미널 수 (헤더 배지)
  const totalRunning = Object.values(terminals).filter(t => t.status === 'running').length;
  const isLive = Object.keys(liveChains).length > 0 || totalRunning > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden gap-3">

      {/* ── 헤더 ── */}
      <div className="flex items-center gap-2 shrink-0">
        <Cpu className="w-4 h-4 text-primary shrink-0" />
        <span className="text-[11px] font-bold text-white">오케스트레이션 태스크보드</span>
        {isLive && (
          <span className="flex items-center gap-1 text-[8px] text-green-400">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />Live
          </span>
        )}
        <div className="ml-auto flex items-center gap-2 text-[9px] text-[#777]">
          <span>활성 <span className={`font-bold ${totalRunning > 0 ? 'text-amber-400' : 'text-[#555]'}`}>{totalRunning}</span></span>
          <span>완료 <span className="font-bold text-green-400">{sessions.length}</span></span>
        </div>
      </div>

      {/* ── 섹션1: Live 파이프라인 레인 (실행 중일 때만 표시) ── */}
      <LivePipelineSection chains={liveChains} />

      {/* ── 섹션2: 칸반 보드 ── */}
      <KanbanSection
        terminals={terminals}
        liveRuns={liveRuns}
        liveChains={liveChains}
      />

      {/* ── 섹션3: 완료 기록 ── */}
      <HistorySection sessions={sessions} />

      {/* 완전 빈 상태 */}
      {Object.keys(liveChains).length === 0 && sessions.length === 0 && totalRunning === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <Cpu className="w-10 h-10 text-[#2a2a2a] mb-3" />
          <p className="text-[11px] text-[#3a3a3a]">오케스트레이션 대기 중</p>
          <p className="text-[9px] text-[#2a2a2a] mt-1">스킬이 실행되면 여기에 표시됩니다</p>
        </div>
      )}
    </div>
  );
}
