/**
 * ------------------------------------------------------------------------
 * 📄 파일명: AgentTerminalCard.tsx
 * 📝 설명: 자율 에이전트 터미널 카드 컴포넌트.
 *          T1~T8 각 터미널의 상태를 카드 형태로 표시합니다.
 *          파이프라인 단계(분석→수정→검증→완료), CLI 배지, 실행 상태를 시각화.
 *          AgentPanel.tsx에서 분리하여 독립 컴포넌트로 관리합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-22 Claude: AgentPanel.tsx에서 분리 — TerminalCard 독립 컴포넌트화
 * - 2026-03-08 Claude: [UI] 각 TerminalCard가 개별 파이프라인 표시하도록 개선
 * - 2026-03-06 Claude: [Phase6] 모델 라우팅 근거 뱃지 표시
 * - 2026-03-05 Claude: [리디자인] 1열 확장 모니터링 패널 목록으로 교체
 * ------------------------------------------------------------------------
 */

import React from 'react';
import {
  Clock, Search, Pencil, ShieldCheck, CheckCircle2,
} from 'lucide-react';
import { TerminalState, detectStage, summarizeOutputText } from './agentPanelTypes';

export default function TerminalCard({
  id, state, selected, onClick,
}: {
  id: string;
  state: TerminalState;
  selected: boolean;
  onClick: () => void;
}) {
  const { status, task, cli, ts, last_line, pipeline_stage } = state;
  const previewLine = summarizeOutputText(last_line);

  // 카드 테두리: 선택 > running > 기본
  const cardBorder = selected
    ? 'border-primary/60 bg-primary/5'
    : status === 'running'
      ? 'border-yellow-400/30 bg-yellow-400/5'
      : status === 'done'
        ? 'border-green-600/20 bg-green-900/5'
        : status === 'error'
          ? 'border-red-500/20 bg-red-900/5'
          : 'border-white/8 bg-black/20 hover:border-white/15';

  // 상태 도트 색상 + 애니메이션
  const dotColor =
    status === 'running' ? 'bg-yellow-400 animate-pulse' :
    status === 'done'    ? 'bg-green-500' :
    status === 'error'   ? 'bg-red-500' :
                           'bg-white/15';

  // CLI 배지 색상
  const cliBadge =
    cli === 'claude' ? 'bg-orange-500/20 text-orange-300 border-orange-500/20' :
    cli === 'gemini' ? 'bg-blue-500/20 text-blue-300 border-blue-500/20' :
    cli === 'codex'  ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/20' :
                       'bg-white/5 text-white/20 border-white/5';

  // 시간 포맷: 오늘 → HH:MM, 이전 날짜 → MM/DD
  const timeStr = (() => {
    if (!ts) return '';
    const today = new Date().toISOString().slice(0, 10);
    const itemDate = ts.slice(0, 10);
    if (itemDate === today) return ts.slice(11, 16);
    return `${ts.slice(5, 7)}/${ts.slice(8, 10)}`;
  })();

  // 파이프라인 단계: 서버 pipeline_stage가 정확한 소스 (hive_hook.py가 도구 이벤트 기반으로 전송)
  // last_line 키워드 fallback은 훅이 없는 외부 CLI(Gemini 등)에서만 동작
  const serverStage = pipeline_stage && pipeline_stage !== 'idle' ? pipeline_stage : null;
  const detectedStage = serverStage ?? (previewLine ? detectStage(previewLine) : null);

  // 파이프라인 단계 목록 — 각 단계별 고유 아이콘/색상으로 한눈에 구분
  const PIPELINE = [
    {
      id: 'analyzing', label: '분석',
      icon: <Search className="w-3 h-3" />,
      activeBorder: 'border-cyan-400 bg-cyan-400/20 shadow-[0_0_6px_rgba(34,211,238,0.4)] animate-pulse',
      activeText: 'text-cyan-400', activeIcon: 'text-cyan-400',
      idleIcon: 'text-cyan-400/25', idleBorder: 'border-cyan-400/20 bg-cyan-400/5',
    },
    {
      id: 'modifying', label: '수정',
      icon: <Pencil className="w-3 h-3" />,
      activeBorder: 'border-yellow-400 bg-yellow-400/20 shadow-[0_0_6px_rgba(250,204,21,0.4)] animate-pulse',
      activeText: 'text-yellow-400', activeIcon: 'text-yellow-400',
      idleIcon: 'text-yellow-400/25', idleBorder: 'border-yellow-400/20 bg-yellow-400/5',
    },
    {
      id: 'verifying', label: '검증',
      icon: <ShieldCheck className="w-3 h-3" />,
      activeBorder: 'border-purple-400 bg-purple-400/20 shadow-[0_0_6px_rgba(168,85,247,0.4)] animate-pulse',
      activeText: 'text-purple-400', activeIcon: 'text-purple-400',
      idleIcon: 'text-purple-400/25', idleBorder: 'border-purple-400/20 bg-purple-400/5',
    },
    {
      id: 'done', label: '완료',
      icon: <CheckCircle2 className="w-3 h-3" />,
      activeBorder: 'border-green-400 bg-green-400/20 shadow-[0_0_6px_rgba(74,222,128,0.4)] animate-pulse',
      activeText: 'text-green-400', activeIcon: 'text-green-400',
      idleIcon: 'text-green-400/25', idleBorder: 'border-green-400/20 bg-green-400/5',
    },
  ] as const;
  const stageOrder: Record<string, number> = { analyzing: 0, modifying: 1, verifying: 2, done: 3 };
  // running 중 단계 미감지 시 → 분석(0)을 디폴트 활성으로 표시 (시작 단계임을 명시)
  const currentIdx = detectedStage
    ? (stageOrder[detectedStage] ?? -1)
    : status === 'done' ? 3
    : status === 'running' ? 0   // 감지 전이면 분석 단계 활성
    : -1;

  // idle 터미널은 최소 높이 유지 (헤더+상태만 표시)
  const isActive = status !== 'idle';

  return (
    <button
      onClick={onClick}
      className={`flex flex-col gap-0 rounded border transition-all duration-200 text-left w-full overflow-hidden ${cardBorder}`}
    >
      {/* ── 실행 중 상태: 상단 애니메이션 진행 바 ────────────────────────────── */}
      {status === 'running' && (
        <div className="h-0.5 w-full overflow-hidden shrink-0 bg-yellow-400/15">
          <div style={{
            height: '100%',
            background: 'rgba(250,204,21,0.7)',
            animation: 'termCardLive 1.6s ease-in-out infinite',
          }} />
          <style>{`
            @keyframes termCardLive {
              0%   { width:0%;  margin-left:0%; }
              50%  { width:55%; margin-left:22%; }
              100% { width:0%;  margin-left:100%; }
            }
          `}</style>
        </div>
      )}

      {/* ── 모니터링 헤더: ID + 배지 + 상태 + 시간 ─────────────────────────── */}
      <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-white/5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* 터미널 ID — 실행 중이면 노란색 강조 */}
          <span className={`font-bold text-[11px] font-mono tracking-wider ${
            status === 'running' ? 'text-yellow-300' : 'text-white/80'
          }`}>{id}</span>

          {/* 실행 중 LIVE 배지 */}
          {status === 'running' && (
            <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-yellow-400/15 border border-yellow-400/35 text-yellow-400 text-[8px] font-bold animate-pulse">
              <span className="w-1 h-1 rounded-full bg-yellow-400 inline-block" />
              LIVE
            </span>
          )}

          {/* 실행 대상(선택됨) 배지 */}
          {selected && (
            <span className="px-1.5 py-0.5 rounded bg-primary/20 border border-primary/40 text-primary text-[8px] font-bold">
              실행 대상
            </span>
          )}

          {/* CLI 배지 */}
          {cli && (
            <span className={`text-[8px] px-1.5 py-0.5 rounded border font-bold ${cliBadge}`}>
              {cli === 'claude' ? '⚡' : '✨'} {cli}
            </span>
          )}
          {/* 모델 자동 선택 근거 뱃지 — 실행 중일 때만 표시 */}
          {state.routing_reason && status === 'running' && (
            <span className="text-[7px] text-white/30 font-mono truncate max-w-[80px]" title={state.routing_reason}>
              {state.routing_reason}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {/* 상태 도트 + 텍스트 */}
          <div className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
            <span className={`text-[9px] font-semibold ${
              status === 'running' ? 'text-yellow-400' :
              status === 'done'    ? 'text-green-400' :
              status === 'error'   ? 'text-red-400' :
                                     'text-white/20'
            }`}>
              {status === 'idle' ? '대기' : status === 'running' ? '실행 중' : status === 'done' ? '완료' : '오류'}
            </span>
          </div>
          <span className="text-[8px] text-white/20 font-mono">{timeStr}</span>
        </div>
      </div>

      {/* ── 파이프라인 단계 (실행 이력이 있는 터미널만 표시) ────────────────── */}
      {isActive && (
        <div className="flex items-center justify-center gap-0 px-3 py-2 border-b border-white/5">
          {PIPELINE.map((step, idx) => {
            const isStepActive = step.id === detectedStage && status === 'running';
            const isPast       = currentIdx > idx;
            return (
              <React.Fragment key={step.id}>
                {/* 단계 간 연결선 */}
                {idx > 0 && (
                  <div className={`flex-1 h-px mx-0.5 transition-all ${
                    isPast || isStepActive ? 'bg-green-600/40' : 'bg-white/8'
                  }`} />
                )}
                {/* 단계 원형 + 레이블 — 단계별 고유 색상으로 현재 위치 즉시 파악 */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center border transition-all duration-300 ${
                    isStepActive ? step.activeBorder :
                    isPast       ? 'border-green-600/50 bg-green-900/20' :
                                   step.idleBorder
                  }`}>
                    <span className={`transition-all ${
                      isStepActive ? step.activeIcon :
                      isPast       ? 'text-green-500/70' :
                                     step.idleIcon
                    }`}>{step.icon}</span>
                  </div>
                  <span className={`text-[8px] font-bold transition-all ${
                    isStepActive ? step.activeText :
                    isPast       ? 'text-green-600/50' :
                                   'text-white/20'
                  }`}>
                    {step.label}
                  </span>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      )}

      {/* ── 현재 작업 텍스트 ────────────────────────────────────────────────── */}
      <div className="flex items-start gap-1.5 px-2.5 py-1.5">
        <Clock className={`w-3 h-3 shrink-0 mt-0.5 ${
          status === 'running' ? 'text-yellow-400/60' : 'text-white/15'
        }`} />
        <span className={`text-[9px] truncate leading-tight ${
          status === 'running' ? 'text-yellow-200/70' :
          status === 'done'    ? 'text-green-200/40 line-through' :
                                 'text-white/25'
        }`}>
          {task || '—'}
        </span>
      </div>

      {/* ── 마지막 출력 줄 (running 중에만 표시) ────────────────────────────── */}
      {previewLine && status === 'running' && (
        <div className="px-2.5 pb-1.5">
          <div className="text-[8px] text-white/25 font-mono truncate bg-black/30 rounded px-1.5 py-0.5 border border-white/5">
            {previewLine}
          </div>
        </div>
      )}
    </button>
  );
}
