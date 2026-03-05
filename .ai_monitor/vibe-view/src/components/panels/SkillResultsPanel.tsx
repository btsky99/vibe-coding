/**
 * ------------------------------------------------------------------------
 * 📄 파일명: SkillResultsPanel.tsx
 * 📝 설명: AI 오케스트레이터 스킬 실행 결과 패널.
 *          [현재 실행 중] 섹션: /api/orchestrator/skill-chain 3초 폴링 → 라이브 체인 표시
 *          [완료 기록] 섹션: skill_results.jsonl 10초 폴링 → 이전 세션 히스토리
 * REVISION HISTORY:
 * - 2026-03-05 Claude: 현재 실행 중 섹션 추가 — skill-chain 라이브 폴링으로 과거/현재 분리
 * - 2026-03-02 Claude: terminal_id 배지, 터미널 필터 탭, 통계 헤더, 폴링 30→10s 강화
 * - 2026-03-01 Claude: Task 3 신규 구현 — skill_results.jsonl → 대시보드 표시
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useMemo } from 'react';
import { Zap, CheckCircle2, SkipForward, AlertCircle, Clock, BarChart3, Radio } from 'lucide-react';
import { API_BASE } from '../../constants';

// ─── 현재 실행 중 체인 타입 ────────────────────────────────────────────────

interface LiveStep {
  skill_name: string;
  status: string;  // pending | running | done | failed
}

interface LiveChain {
  request: string;
  steps: LiveStep[];
  terminal_id?: number;
}

// ─── 타입 정의 ────────────────────────────────────────────────────────────

interface SkillResultEntry {
  skill: string;    // 스킬 이름 (예: vibe-debug)
  status: string;   // done | skipped | error | running
  summary: string;  // 실행 요약
}

interface SkillSessionResult {
  session_id: string;           // 세션 ID (날짜시간 기반)
  terminal_id?: number;         // 실행 터미널 번호 (0=미지정, 1~8=터미널N)
  request: string;              // 사용자 요청 원문
  results: SkillResultEntry[];  // 실행된 스킬 체인 결과
  completed_at: string;         // 완료 시각 (ISO)
}

// ─── 스킬명 한글 표시 매핑 ───────────────────────────────────────────
const SKILL_LABELS: Record<string, string> = {
  'debug':        '🔍 디버그',
  'tdd':          '🧪 테스트',
  'brainstorm':   '💡 아이디어',
  'write-plan':   '📝 계획작성',
  'execute-plan': '⚡ 계획실행',
  'execute':      '⚡ 계획실행',
  'code-review':  '🔎 코드리뷰',
  'release':      '🚀 릴리스',
  'orchestrate':  '🤖 오케스트레이터',
  'master':       '🎯 마스터',
};

// 상태 한글 변환
const STATUS_KR: Record<string, string> = {
  'done':    '완료',
  'error':   '오류',
  'skipped': '건너뜀',
  'running': '실행중',
};

// ─── 상수 ────────────────────────────────────────────────────────────────

// 터미널 번호 → 색상 배지 (7가지 구분색)
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

export default function SkillResultsPanel() {
  const [sessions, setSessions] = useState<SkillSessionResult[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // 'all' 또는 터미널 번호 문자열 ('1', '2', ...)
  const [filterTerminal, setFilterTerminal] = useState<string>('all');
  // 현재 실행 중인 스킬 체인 (터미널별)
  const [liveChains, setLiveChains] = useState<Record<string, LiveChain>>({});

  // [라이브] 현재 실행 중 스킬 체인 — 3초마다 빠르게 폴링
  useEffect(() => {
    const fetchLive = () => {
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then(data => {
          // terminals 맵에서 running/pending 스텝이 있는 것만 추출
          const active: Record<string, LiveChain> = {};
          const terminals: Record<string, any> = data?.terminals ?? {};
          for (const [tid, chain] of Object.entries(terminals)) {
            const steps: LiveStep[] = chain?.steps ?? [];
            const isActive = steps.some((s: LiveStep) => s.status === 'running' || s.status === 'pending');
            if (isActive) {
              active[tid] = {
                request: chain?.request ?? '',
                steps,
                terminal_id: parseInt(tid, 10) || undefined,
              };
            }
          }
          setLiveChains(active);
        })
        .catch(() => {});
    };
    fetchLive();
    const interval = setInterval(fetchLive, 3000);
    return () => clearInterval(interval);
  }, []);

  // [히스토리] 완료된 스킬 결과 폴링 (10초 간격)
  useEffect(() => {
    const fetchResults = () => {
      fetch(`${API_BASE}/api/skill-results`)
        .then(res => res.json())
        .then(data => setSessions(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchResults();
    const interval = setInterval(fetchResults, 10000);
    return () => clearInterval(interval);
  }, []);

  // ─── 파생 데이터 ────────────────────────────────────────────────────────

  // 터미널 번호 목록 (데이터에 등장하는 것만)
  const terminalIds = useMemo(() => {
    const ids = new Set<number>();
    sessions.forEach(s => { if (s.terminal_id) ids.add(s.terminal_id); });
    return Array.from(ids).sort();
  }, [sessions]);

  // 필터 적용된 세션 목록
  const filteredSessions = useMemo(() => {
    if (filterTerminal === 'all') return sessions;
    const tid = parseInt(filterTerminal, 10);
    return sessions.filter(s => s.terminal_id === tid || (!s.terminal_id && tid === 0));
  }, [sessions, filterTerminal]);

  // 전체 완료 통계
  const stats = useMemo(() => {
    let done = 0, total = 0, error = 0;
    sessions.forEach(s => s.results.forEach(r => {
      total++;
      if (r.status === 'done') done++;
      if (r.status === 'error') error++;
    }));
    return { done, total, error, sessions: sessions.length };
  }, [sessions]);

  // ─── 렌더링 헬퍼 ────────────────────────────────────────────────────────

  const statusIcon = (status: string) => {
    switch (status) {
      case 'done':    return <CheckCircle2 className="w-3 h-3 text-green-400 shrink-0" />;
      case 'skipped': return <SkipForward className="w-3 h-3 text-[#858585] shrink-0" />;
      case 'error':   return <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />;
      default:        return <Clock className="w-3 h-3 text-yellow-400 shrink-0" />;
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

  // 터미널 배지 CSS — 번호 없는 세션은 회색
  const terminalBadgeCls = (id?: number) =>
    id ? (TERMINAL_COLORS[id] ?? 'bg-white/10 text-white/60 border-white/20')
       : 'bg-white/5 text-white/30 border-white/10';

  // 완료 시각 포맷 (ISO → M/D HH:MM)
  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString('ko-KR', {
        month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    } catch { return iso; }
  };

  // 현재 실행 중 체인 목록 (터미널 순 정렬)
  const liveChainList = Object.entries(liveChains).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* ── 현재 실행 중 섹션 (라이브 데이터) ── */}
      {liveChainList.length > 0 && (
        <div className="shrink-0 rounded border border-green-500/30 bg-green-500/5 p-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-green-400 animate-pulse" />
            <span className="text-[10px] font-bold text-green-400 uppercase tracking-wider">현재 실행 중</span>
          </div>
          {liveChainList.map(([tid, chain]) => (
            <div key={tid} className="flex flex-col gap-1">
              {/* 요청 원문 */}
              {chain.request && (
                <span className="text-[9px] text-white/40 font-mono line-clamp-1">
                  T{tid}: {chain.request}
                </span>
              )}
              {/* 스텝 배지 */}
              <div className="flex flex-wrap gap-1">
                {chain.steps.map((step, i) => {
                  const rawKey = step.skill_name.replace(/^vibe-/, '');
                  const label = SKILL_LABELS[rawKey] ?? rawKey;
                  const s = step.status;
                  const colorCls = s === 'running'  ? 'border-yellow-400/60 text-yellow-300 bg-yellow-400/10 animate-pulse'
                                 : s === 'done'     ? 'border-green-500/50 text-green-400 bg-green-500/10'
                                 : s === 'failed'   ? 'border-red-500/50 text-red-400 bg-red-500/10'
                                 :                   'border-white/10 text-white/30 bg-white/5';
                  const icon = s === 'running' ? '●' : s === 'done' ? '✓' : s === 'failed' ? '✗' : '○';
                  return (
                    <span key={i} className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${colorCls}`}>
                      {icon} {label}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 헤더: 완료 기록 제목 + 통계 ── */}
      <div className="flex items-center gap-2 shrink-0">
        <Zap className="w-4 h-4 text-yellow-400" />
        <span className="text-[11px] font-bold text-white/60">완료 기록</span>
        <div className="ml-auto flex items-center gap-1.5">
          {/* 완료 통계 배지 */}
          {stats.total > 0 && (
            <span className="flex items-center gap-1 text-[9px] text-[#858585]">
              <BarChart3 className="w-3 h-3" />
              <span className="text-green-400 font-bold">{stats.done}</span>
              <span>/</span>
              <span>{stats.total}</span>
              {stats.error > 0 && (
                <span className="text-red-400 font-bold ml-0.5">({stats.error}오류)</span>
              )}
            </span>
          )}
          <span className="text-[9px] text-[#858585]">{stats.sessions}건</span>
        </div>
      </div>

      {/* ── 터미널 필터 탭 (2개 이상 터미널일 때만 표시) ── */}
      {terminalIds.length > 1 && (
        <div className="flex gap-1 flex-wrap shrink-0">
          <button
            onClick={() => setFilterTerminal('all')}
            className={`text-[9px] font-bold px-2 py-0.5 rounded border transition-colors ${filterTerminal === 'all' ? 'bg-primary/30 text-primary border-primary/50' : 'bg-white/5 text-[#858585] border-white/10 hover:border-white/20'}`}
          >
            전체
          </button>
          {terminalIds.map(tid => (
            <button
              key={tid}
              onClick={() => setFilterTerminal(String(tid))}
              className={`text-[9px] font-bold px-2 py-0.5 rounded border transition-colors ${filterTerminal === String(tid) ? `${TERMINAL_COLORS[tid] ?? ''} border-opacity-60` : 'bg-white/5 text-[#858585] border-white/10 hover:border-white/20'}`}
            >
              T{tid}
            </button>
          ))}
        </div>
      )}

      {/* ── 결과 목록 ── */}
      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2">
        {filteredSessions.length === 0 ? (
          <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
            <Zap className="w-7 h-7 opacity-20" />
            {sessions.length === 0
              ? '아직 스킬 실행 기록이 없습니다'
              : '선택한 터미널에 결과가 없습니다'}
          </div>
        ) : (
          filteredSessions.map(session => {
            const isExpanded = expandedId === session.session_id;
            const doneCount = session.results.filter(r => r.status === 'done').length;
            const totalCount = session.results.length;

            return (
              <div
                key={session.session_id}
                className="rounded border border-white/10 bg-white/2 hover:border-white/20 transition-colors overflow-hidden"
              >
                {/* 세션 카드 헤더 — 클릭 시 상세 토글 */}
                <button
                  onClick={() => setExpandedId(isExpanded ? null : session.session_id)}
                  className="w-full p-2 text-left flex flex-col gap-1"
                >
                  {/* 분석 결과(summary) 헤더 표시 — 터미널 배지 + 분석 내용 */}
                  <div className="flex items-start gap-1.5">
                    {/* 터미널 번호 배지 */}
                    {session.terminal_id ? (
                      <span className={`text-[8px] font-black px-1 py-0.5 rounded border shrink-0 mt-0.5 ${terminalBadgeCls(session.terminal_id)}`}>
                        T{session.terminal_id}
                      </span>
                    ) : (
                      <Zap className="w-3 h-3 text-yellow-400 shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      {/* 분석 결과 요약 — 마지막 비어있지 않은 summary 우선, 없으면 request */}
                      {(() => {
                        const summaries = session.results
                          .map(r => r.summary)
                          .filter(s => s && s.trim());
                        const mainText = summaries.length > 0
                          ? summaries[summaries.length - 1]
                          : session.request;
                        return (
                          <span className="text-[10px] text-white leading-tight line-clamp-2 block">
                            {mainText}
                          </span>
                        );
                      })()}
                      {/* 지시 원문 — 작게 보조 표시 */}
                      <span className="text-[8px] text-[#555] leading-tight line-clamp-1 block mt-0.5">
                        지시: {session.request}
                      </span>
                    </div>
                  </div>

                  {/* 스킬별 실행 결과 내러티브 — 각 스킬이 실제로 무엇을 했는지 한 줄씩 표시 */}
                  <div className="pl-4 flex flex-col gap-0.5">
                    {session.results.map((r, i) => {
                      const shortName = r.skill.replace('vibe-', '');
                      const label = SKILL_LABELS[shortName] ?? shortName;
                      return (
                        <div key={i} className="flex items-start gap-1">
                          {/* 스킬 배지 */}
                          <span
                            className={`text-[8px] font-bold px-1 py-0.5 rounded flex items-center gap-0.5 shrink-0 ${statusBadgeCls(r.status)}`}
                          >
                            {statusIcon(r.status)}
                            {label}
                          </span>
                          {/* 스킬이 생성한 분석/결과 요약 */}
                          {r.summary ? (
                            <span className="text-[9px] text-[#aaa] leading-tight pt-0.5 line-clamp-1">
                              {r.summary}
                            </span>
                          ) : (
                            <span className="text-[9px] text-[#444] leading-tight pt-0.5 italic">
                              {STATUS_KR[r.status] ?? r.status}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {/* 완료율 */}
                  <div className="pl-4">
                    <span className={`text-[9px] font-bold ${doneCount === totalCount ? 'text-green-400' : 'text-[#858585]'}`}>
                      {doneCount}/{totalCount} 완료
                    </span>
                  </div>

                  {/* 완료 시각 */}
                  <div className="pl-4 text-[8px] text-[#555] font-mono">
                    {formatTime(session.completed_at)}
                  </div>
                </button>

                {/* 상세 결과 (토글) */}
                {isExpanded && (
                  <div className="border-t border-white/5 px-2 pb-2 pt-1.5 space-y-1.5">
                    {session.results.map((r, i) => (
                      <div key={i} className="flex items-start gap-1.5">
                        {statusIcon(r.status)}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1 flex-wrap">
                            {/* 스킬 한글명 + 원본명 */}
                            <span className="text-[10px] font-bold text-white">
                              {SKILL_LABELS[r.skill.replace('vibe-', '')] ?? r.skill.replace('vibe-', '')}
                            </span>
                            <span className="text-[8px] text-white/25 font-mono">({r.skill})</span>
                            <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${statusBadgeCls(r.status)}`}>
                              {STATUS_KR[r.status] ?? r.status}
                            </span>
                          </div>
                          {r.summary && (
                            <p className="text-[9px] text-[#aaaaaa] leading-tight mt-0.5 break-words whitespace-pre-wrap">
                              {r.summary}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                    {/* 세션 메타 */}
                    <div className="text-[8px] text-[#333] font-mono pt-1 border-t border-white/5 flex items-center gap-2">
                      <span>#{session.session_id}</span>
                      {session.terminal_id && (
                        <span className={`px-1 py-0.5 rounded border text-[7px] font-bold ${terminalBadgeCls(session.terminal_id)}`}>
                          T{session.terminal_id}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
