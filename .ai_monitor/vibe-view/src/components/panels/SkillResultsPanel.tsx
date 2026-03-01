/**
 * ------------------------------------------------------------------------
 * 📄 파일명: SkillResultsPanel.tsx
 * 📝 설명: AI 오케스트레이터 스킬 실행 결과 패널.
 *          skill_orchestrator.py가 skill_results.jsonl에 저장한 세션별 결과를
 *          10초마다 폴링하여 대시보드에 표시합니다.
 *          터미널별 필터, 완료 통계, terminal_id 배지를 포함합니다.
 * REVISION HISTORY:
 * - 2026-03-02 Claude: terminal_id 배지, 터미널 필터 탭, 통계 헤더, 폴링 30→10s 강화
 * - 2026-03-01 Claude: Task 3 신규 구현 — skill_results.jsonl → 대시보드 표시
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useMemo } from 'react';
import { Zap, CheckCircle2, SkipForward, AlertCircle, Clock, BarChart3 } from 'lucide-react';
import { API_BASE } from '../../constants';

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

  // 스킬 결과 폴링 (10초 간격 — 30s보다 빠른 갱신)
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

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* ── 헤더: 제목 + 통계 ── */}
      <div className="flex items-center gap-2 shrink-0">
        <Zap className="w-4 h-4 text-yellow-400" />
        <span className="text-[11px] font-bold text-white">스킬 실행 결과</span>
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
            All
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
                  {/* 요청 내용 + 터미널 배지 + 완료 시각 */}
                  <div className="flex items-start gap-1.5">
                    {/* 터미널 번호 배지 */}
                    {session.terminal_id ? (
                      <span className={`text-[8px] font-black px-1 py-0.5 rounded border shrink-0 mt-0.5 ${terminalBadgeCls(session.terminal_id)}`}>
                        T{session.terminal_id}
                      </span>
                    ) : (
                      <Zap className="w-3 h-3 text-yellow-400 shrink-0 mt-0.5" />
                    )}
                    <span className="text-[10px] text-white flex-1 leading-tight line-clamp-2">
                      {session.request}
                    </span>
                  </div>

                  {/* 스킬 체인 태그 + 완료율 */}
                  <div className="flex items-center gap-1.5 pl-4">
                    <div className="flex gap-1 flex-1 flex-wrap">
                      {session.results.map((r, i) => (
                        <span
                          key={i}
                          className={`text-[8px] font-bold px-1 py-0.5 rounded flex items-center gap-0.5 ${statusBadgeCls(r.status)}`}
                        >
                          {statusIcon(r.status)}
                          {r.skill.replace('vibe-', '')}
                        </span>
                      ))}
                    </div>
                    {/* 완료율 배지 */}
                    <span className={`text-[9px] font-bold shrink-0 ${doneCount === totalCount ? 'text-green-400' : 'text-[#858585]'}`}>
                      {doneCount}/{totalCount}
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
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] font-bold text-white">{r.skill}</span>
                            <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${statusBadgeCls(r.status)}`}>
                              {r.status}
                            </span>
                          </div>
                          {r.summary && (
                            <p className="text-[9px] text-[#858585] leading-tight mt-0.5 break-words">
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
