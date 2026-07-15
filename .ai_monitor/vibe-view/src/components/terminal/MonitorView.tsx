/**
 * ------------------------------------------------------------------------
 * 📄 파일명: MonitorView.tsx
 * 📝 설명: 자율 에이전트 모니터링 뷰 — 상태 뱃지, 오케스트레이터 스킬 체인 배지,
 *          현재 작업, 하이브 저장 상태. 터미널 부착/미부착 양쪽에서 렌더 가능.
 * REVISION HISTORY:
 * - 2026-07-15 Claude: TerminalSlot.tsx에서 분리 — [근본수정] 기존엔 isTerminalMode
 *                      블록 안에만 있어 "실행 감지 시 선택 카드 건너뛰고 모니터링 표시"
 *                      (2026-03-08 약속)가 도달 불가였음. 분리로 미부착 슬롯에서도 표시.
 * ------------------------------------------------------------------------
 */
import { Activity, CheckCircle2, ClipboardList, Clock } from 'lucide-react';
import { Task } from '../../types';

export default function MonitorView({
  activeAgent, agentStatus, statusColor, statusDot,
  chainSteps, chainRequest, liveTask, inProgressTask, myPendingTasks, hiveActivity,
}: {
  activeAgent: string;
  agentStatus: string;
  statusColor: string;
  statusDot: string;
  chainSteps: any[];
  chainRequest: string;
  liveTask: string | null;
  inProgressTask: Task | undefined;
  myPendingTasks: Task[];
  hiveActivity?: Array<{ timestamp: string; agent: string; type: string; task: string }>;
}) {
  return (
    <div className="max-h-[160px] border-b border-black/40 bg-[#1a1a1a] flex flex-col shrink-0 overflow-y-auto custom-scrollbar">

      {/* 모니터링 헤더: 에이전트명 + 상태 뱃지 (슬림화) */}
      <div className="h-5 bg-[#2d2d2d] px-2 flex items-center justify-between shrink-0 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Activity className="w-3 h-3 text-green-400" />
          <span className="text-[10px] font-bold text-[#cccccc] uppercase tracking-wider">
            {activeAgent.toUpperCase()} 모니터링
          </span>
        </div>
        {/* 에이전트 상태 뱃지 */}
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[9px] font-bold ${statusColor}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
          {agentStatus}
        </div>
      </div>

      {/* 오케스트레이터 스킬 체인 (있을 때만 표시) */}
      {chainSteps.length > 0 && (
        <div className="px-2 pb-1 shrink-0 border-b border-white/5">
          {/* 요청 문구 (있을 때만) */}
          {chainRequest && (
            <div className="text-[8px] text-white/25 font-mono truncate mb-1">{chainRequest}</div>
          )}
          {/* 스킬 단계 배지 목록 */}
          <div className="flex flex-wrap gap-1">
            {chainSteps.map((step: any, idx: number) => {
              const s = step.status as string;
              const isRunning = s === 'running';
              const isDone    = s === 'done';
              const isFailed  = s === 'failed';
              const colorCls  = isRunning ? 'border-yellow-400/60 text-yellow-300 bg-yellow-400/10 animate-pulse'
                              : isDone    ? 'border-green-500/50 text-green-400 bg-green-500/10'
                              : isFailed  ? 'border-red-500/50 text-red-400 bg-red-500/10'
                              :             'border-white/10 text-white/30 bg-white/5';
              const icon = isRunning ? '●' : isDone ? '✓' : isFailed ? '✗' : '○';
              // skill_name을 한글 단축어로 변환 ('vibe-debug' → '디버그' 등)
              const SKILL_KO: Record<string, string> = {
                'debug': '디버그', 'tdd': 'TDD', 'brainstorm': '아이디어',
                'write-plan': '계획작성', 'execute-plan': '계획실행',
                'code-review': '코드리뷰', 'release': '릴리스',
              };
              const rawKey = (step.skill_name as string).replace(/^vibe-/, '');
              const label = SKILL_KO[rawKey] ?? rawKey;
              return (
                <div
                  key={idx}
                  className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[9px] font-mono font-bold ${colorCls}`}
                  title={`${step.skill_name} (${s})`}
                >
                  <span>{icon}</span>
                  <span>{label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 모니터링 본문 — 오케스트레이션 + 하이브 저장 상태 중심 */}
      <div className="flex-1 overflow-hidden flex flex-col px-2 pb-2 gap-1.5">

        {/* ── 현재 작업 ── */}
        <div className="flex items-start gap-2 shrink-0 mt-1">
          {liveTask ? (
            <>
              <Clock className="w-3 h-3 text-yellow-400 mt-0.5 shrink-0" />
              <span className="text-[10px] text-yellow-300 font-mono leading-tight truncate">
                {liveTask}
              </span>
            </>
          ) : inProgressTask ? (
            <>
              <Clock className="w-3 h-3 text-yellow-400 mt-0.5 shrink-0" />
              <span className="text-[10px] text-yellow-300 font-mono leading-tight truncate">
                {inProgressTask.title ?? '태스크 진행 중...'}
              </span>
            </>
          ) : myPendingTasks.length > 0 ? (
            <>
              <ClipboardList className="w-3 h-3 text-[#858585] mt-0.5 shrink-0" />
              <span className="text-[10px] text-[#858585] font-mono leading-tight truncate">
                대기: {myPendingTasks[0].title ?? '작업 대기'}
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-3 h-3 text-[#555] mt-0.5 shrink-0" />
              <span className="text-[10px] text-[#555] font-mono">할당된 태스크 없음</span>
            </>
          )}
        </div>

        {/* ── 하이브 저장 상태 — memory_write / orchestrate 최근 이벤트 ── */}
        {(() => {
          const acts = hiveActivity ?? [];
          // memory_write: 가장 최근 메모리 저장 이벤트
          const lastWrite = acts.find(a => a.type === 'memory_write');
          // orchestrate: 가장 최근 오케스트레이션 이벤트
          const lastOrch = acts.find(a => a.type === 'orchestrate');
          // 5분 이내 이벤트는 "방금" 표시
          const fmtTime = (ts: string) => {
            const diffMs = Date.now() - new Date(ts).getTime();
            if (diffMs < 60000) return '방금';
            if (diffMs < 300000) return `${Math.floor(diffMs/60000)}분 전`;
            return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
          };
          return (
            <div className="flex flex-col gap-0.5 border-t border-white/5 pt-1.5 shrink-0">
              <div className="text-[8px] text-white/20 font-bold uppercase tracking-widest mb-0.5">하이브 상태</div>
              {/* 하이브 메모리 저장 상태 */}
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${lastWrite ? 'bg-green-400' : 'bg-[#444]'}`} />
                <span className="text-[9px] text-[#888] font-mono">메모리 저장</span>
                {lastWrite ? (
                  <span className="text-[9px] text-green-400 font-mono ml-auto">{fmtTime(lastWrite.timestamp)}</span>
                ) : (
                  <span className="text-[9px] text-[#444] font-mono ml-auto">없음</span>
                )}
              </div>
              {/* 오케스트레이션 실행 상태 */}
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${chainSteps.length > 0 ? 'bg-yellow-400 animate-pulse' : lastOrch ? 'bg-blue-400' : 'bg-[#444]'}`} />
                <span className="text-[9px] text-[#888] font-mono">오케스트레이션</span>
                {chainSteps.length > 0 ? (
                  <span className="text-[9px] text-yellow-300 font-mono ml-auto animate-pulse">실행 중</span>
                ) : lastOrch ? (
                  <span className="text-[9px] text-blue-400 font-mono ml-auto">{fmtTime(lastOrch.timestamp)}</span>
                ) : (
                  <span className="text-[9px] text-[#444] font-mono ml-auto">없음</span>
                )}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
