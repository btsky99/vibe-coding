/**
 * FILE: OrchestratorPanel.tsx
 * DESCRIPTION: AI 오케스트레이터 패널 — 스킬 체인 실행 흐름 모니터링 및 수동 실행 UI.
 *              App.tsx에서 분리된 독립 컴포넌트로, 오케스트레이터 상태와 스킬 체인을
 *              자체 폴링하여 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 * - 2026-03-01 Claude: [버그수정] terminal_agents / agent_status 미렌더링 버그 수정
 *                      — 터미널별 에이전트 현황 그리드 추가 (T1~T8 슬롯 시각화)
 *                      — 근본원인: orchStatus 수신 후 recent_actions만 표시하고
 *                        terminal_agents / agent_status 렌더링 코드가 누락되어 있었음
 */

import { useState, useEffect } from 'react';
import { Play, Network } from 'lucide-react';
import { OrchestratorStatus } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정 (App.tsx와 동일한 패턴)
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ── OrchestratorPanel Props ─────────────────────────────────────────────────
// onWarningCount: 부모(App.tsx)에 경고 수를 전달하여 Hive 탭 배지 업데이트에 사용
interface OrchestratorPanelProps {
  onWarningCount: (count: number) => void;
}

// ── 스킬 체인 상태 타입 ──────────────────────────────────────────────────────
// vibe-orchestrate 스킬이 기록하는 skill_chain.json 구조에 대응
interface SkillChainState {
  status: string;
  request?: string;
  plan?: string[];
  current_step?: number;
  results?: { skill: string; status: string; summary: string }[];
  started_at?: string;
  updated_at?: string;
}

/**
 * OrchestratorPanel
 *
 * 역할: AI 오케스트레이터 상태를 실시간으로 폴링하고,
 *       스킬 체인 실행 흐름을 시각화하는 패널 컴포넌트.
 *
 * 폴링 주기:
 *   - /api/orchestrator/status    : 3초 (에이전트 상태 + 경고 + 최근 액션)
 *   - /api/orchestrator/skill-chain: 3초 (실행 중인 스킬 체인 현황)
 */
export default function OrchestratorPanel({ onWarningCount }: OrchestratorPanelProps) {
  // 오케스트레이터 전체 상태 (에이전트별 상태, 태스크 분배, 경고 등)
  const [orchStatus, setOrchStatus] = useState<OrchestratorStatus | null>(null);
  // 수동 실행 중 여부 — 버튼 비활성화 및 레이블 변경에 사용
  const [orchRunning, setOrchRunning] = useState(false);
  // 마지막 수동 실행 시각 — 헤더 영역에 표시
  const [orchLastRun, setOrchLastRun] = useState<string | null>(null);
  // 스킬 체인 실행 상태 (idle / running / done / failed)
  const [skillChain, setSkillChain] = useState<SkillChainState>({ status: 'idle' });

  // ── 오케스트레이터 상태 폴링 (3초 간격) ──────────────────────────────────
  // 터미널 에이전트 실시간 감지 + 경고 수 부모 전달
  useEffect(() => {
    const fetchOrch = () => {
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then((data: OrchestratorStatus) => {
          setOrchStatus(data);
          // 경고 수를 부모 컴포넌트로 전달 (Hive 탭 배지용)
          onWarningCount(data.warnings?.length ?? 0);
        })
        .catch(() => {});
    };
    fetchOrch();
    const interval = setInterval(fetchOrch, 3000);
    return () => clearInterval(interval);
  }, [onWarningCount]);

  // ── 스킬 체인 폴링 (3초 간격) ────────────────────────────────────────────
  // vibe-orchestrate 스킬이 저장한 skill_chain.json을 주기적으로 조회
  useEffect(() => {
    const fetchChain = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then(data => setSkillChain(data))
        .catch(() => {});
    };
    fetchChain();
    const interval = setInterval(fetchChain, 3000);
    return () => clearInterval(interval);
  }, []);

  // ── 오케스트레이터 수동 실행 핸들러 ──────────────────────────────────────
  // 실행 후 상태를 즉시 갱신하여 UI에 반영
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

  return (
    /* ── AI 오케스트레이터 패널 — 스킬 체인 실행/모니터링 ── */
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

      {/* ── 스킬 체인 실행 흐름 위젯 (AI 오케스트레이터) ── */}
      {skillChain.status !== 'idle' && skillChain.plan && skillChain.plan.length > 0 && (
        <div className={`p-2 rounded border shrink-0 ${
          skillChain.status === 'running'
            ? 'border-primary/40 bg-primary/5 animate-pulse-subtle'
            : skillChain.status === 'done'
              ? 'border-green-500/30 bg-green-500/5'
              : 'border-red-500/30 bg-red-500/5'
        }`}>
          {/* 스킬 체인 상태 헤더 */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-bold text-[#bbbbbb] uppercase tracking-wider">
                🎯 AI 오케스트레이터
              </span>
              <span className={`px-1.5 py-0.5 rounded text-[7px] font-bold ${
                skillChain.status === 'running' ? 'bg-primary/20 text-primary' :
                skillChain.status === 'done'    ? 'bg-green-500/20 text-green-400' :
                                                  'bg-red-500/20 text-red-400'
              }`}>
                {skillChain.status === 'running' ? '실행 중' :
                 skillChain.status === 'done'    ? '완료' : '실패'}
              </span>
            </div>
            {skillChain.updated_at && (
              <span className="text-[7px] text-[#666] font-mono">
                {new Date(skillChain.updated_at).toLocaleTimeString()}
              </span>
            )}
          </div>

          {/* 요청 내용 요약 */}
          {skillChain.request && (
            <div className="text-[8px] text-[#aaa] mb-2 truncate" title={skillChain.request}>
              📋 {skillChain.request}
            </div>
          )}

          {/* 스킬 체인 흐름 시각화: [skill1 ✅] → [skill2 🔄] → [skill3 ⏳] */}
          <div className="flex items-center gap-1 flex-wrap">
            {(skillChain.results ?? []).map((r, i) => {
              // 각 스킬 실행 결과에 따른 아이콘 결정
              const icon = r.status === 'done'    ? '✅' :
                           r.status === 'running' ? '🔄' :
                           r.status === 'failed'  ? '❌' :
                           r.status === 'skipped' ? '⏭️' : '⏳';
              // 상태별 색상 클래스 결정
              const color = r.status === 'done'    ? 'border-green-500/40 bg-green-500/10 text-green-400' :
                            r.status === 'running' ? 'border-primary/50 bg-primary/10 text-primary animate-pulse' :
                            r.status === 'failed'  ? 'border-red-500/40 bg-red-500/10 text-red-400' :
                                                     'border-white/10 bg-white/5 text-[#666]';
              // 스킬명 단축 표시 (vibe- 접두사 제거)
              const skillShort = r.skill.replace('vibe-', '');
              return (
                <div key={i} className="flex items-center gap-1">
                  {i > 0 && <span className="text-[#444] text-[8px]">→</span>}
                  <div
                    className={`px-1.5 py-0.5 rounded border text-[8px] font-mono font-bold ${color}`}
                    title={r.summary || r.skill}
                  >
                    {icon} {skillShort}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 현재 실행 중인 스킬 요약 메시지 */}
          {skillChain.status === 'running' && skillChain.results && (
            <div className="mt-1.5 text-[7px] text-[#888] truncate">
              {(() => {
                const running = skillChain.results.find(r => r.status === 'running');
                const done = skillChain.results.filter(r => r.status === 'done');
                if (running) return `⚡ ${running.skill} 실행 중...`;
                if (done.length > 0) return `✅ ${done[done.length-1].skill}: ${done[done.length-1].summary}`;
                return '준비 중...';
              })()}
            </div>
          )}
        </div>
      )}

      {/* 스킬 체인 대기 상태 — 활성 체인 없을 때 안내 메시지 */}
      {skillChain.status === 'idle' && (
        <div className="text-center text-[#858585] text-xs py-8 flex flex-col items-center gap-2 italic">
          <Network className="w-7 h-7 opacity-20" />
          <span>스킬 체인 대기 중</span>
          <span className="text-[9px]">/vibe-orchestrate 스킬로 체인 실행</span>
        </div>
      )}

      {/* ── 터미널별 에이전트 현황 그리드 ── */}
      {/* terminal_agents 데이터가 있을 때만 표시 — 슬롯별로 어떤 에이전트가 동작 중인지 시각화 */}
      {orchStatus && Object.keys(orchStatus.terminal_agents ?? {}).length > 0 && (
        <div className="shrink-0 p-2 rounded border border-white/10">
          <div className="text-[9px] font-bold text-[#969696] mb-1.5 uppercase tracking-wider">터미널별 에이전트</div>
          <div className="grid grid-cols-4 gap-1">
            {Array.from({ length: 8 }, (_, i) => {
              const slot = String(i + 1);
              const agent = (orchStatus.terminal_agents ?? {})[slot] || '';
              const st = agent ? (orchStatus.agent_status ?? {})[agent] : null;
              // 에이전트별 색상: claude=초록, gemini=파랑, shell=노랑, 비어있음=회색
              const color = !agent
                ? 'border-white/5 bg-white/3 text-[#555]'
                : agent === 'claude'
                  ? 'border-green-500/40 bg-green-500/10 text-green-400'
                  : agent === 'gemini'
                    ? 'border-blue-500/40 bg-blue-500/10 text-blue-400'
                    : 'border-yellow-500/40 bg-yellow-500/10 text-yellow-400';
              // 활성 상태 표시용 점
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

      {/* 최근 오케스트레이터 자동 액션 로그 */}
      {orchStatus?.recent_actions && orchStatus.recent_actions.length > 0 ? (
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          <div className="p-2 rounded border border-white/10">
            <div className="text-[9px] font-bold text-[#969696] mb-1.5">최근 자동 액션</div>
            {orchStatus.recent_actions.slice(0, 8).map((act, i) => {
              // 액션 유형별 색상 구분 (자동 할당 / 유휴 감지 / 과부하 / 기타)
              const actionColor =
                act.action === 'auto_assign'         ? 'text-green-400' :
                act.action === 'idle_agent'           ? 'text-yellow-400' :
                act.action.includes('overload')       ? 'text-red-400' :
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
