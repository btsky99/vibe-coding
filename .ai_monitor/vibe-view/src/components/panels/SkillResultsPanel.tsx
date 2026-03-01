/**
 * FILE: SkillResultsPanel.tsx
 * DESCRIPTION: AI 오케스트레이터 스킬 실행 결과 패널.
 *              skill_orchestrator.py가 skill_results.jsonl에 저장한 세션별 결과를
 *              30초마다 폴링하여 대시보드에 표시한다.
 *              각 세션 카드에 요청 내용, 실행된 스킬 체인, 완료 시간을 표시한다.
 *
 * REVISION HISTORY:
 * - 2026-03-01 Claude: Task 3 신규 구현 — skill_results.jsonl → 대시보드 표시
 */

import { useState, useEffect } from 'react';
import { Zap, CheckCircle2, SkipForward, AlertCircle, Clock } from 'lucide-react';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// 스킬 실행 결과 타입
interface SkillResultEntry {
  skill: string;    // 스킬 이름 (예: vibe-debug)
  status: string;   // done | skipped | error
  summary: string;  // 실행 요약
}

interface SkillSessionResult {
  session_id: string;         // 세션 ID (날짜시간 기반)
  request: string;            // 사용자 요청 원문
  results: SkillResultEntry[]; // 실행된 스킬 체인 결과
  completed_at: string;       // 완료 시각 (ISO)
}

export default function SkillResultsPanel() {
  const [sessions, setSessions] = useState<SkillSessionResult[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // 스킬 결과 폴링 (30초 간격 — 실행이 잦지 않으므로 느린 주기)
  useEffect(() => {
    const fetchResults = () => {
      fetch(`${API_BASE}/api/skill-results`)
        .then(res => res.json())
        .then(data => setSessions(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    fetchResults();
    const interval = setInterval(fetchResults, 30000);
    return () => clearInterval(interval);
  }, []);

  // 스킬 상태별 아이콘 + 색상
  const statusIcon = (status: string) => {
    switch (status) {
      case 'done':
        return <CheckCircle2 className="w-3 h-3 text-green-400 shrink-0" />;
      case 'skipped':
        return <SkipForward className="w-3 h-3 text-[#858585] shrink-0" />;
      case 'error':
        return <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />;
      default:
        return <Clock className="w-3 h-3 text-yellow-400 shrink-0" />;
    }
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case 'done':    return 'bg-green-500/20 text-green-400';
      case 'skipped': return 'bg-white/10 text-[#858585]';
      case 'error':   return 'bg-red-500/20 text-red-400';
      default:        return 'bg-yellow-500/20 text-yellow-400';
    }
  };

  // 완료 시각 포맷 (ISO → 사람이 읽기 쉬운 형식)
  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 헤더 */}
      <div className="flex items-center gap-2 shrink-0">
        <Zap className="w-4 h-4 text-yellow-400" />
        <span className="text-[11px] font-bold text-white">스킬 실행 결과</span>
        <span className="ml-auto text-[9px] text-[#858585]">{sessions.length}건</span>
      </div>

      {/* 결과 목록 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2">
        {sessions.length === 0 ? (
          <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
            <Zap className="w-7 h-7 opacity-20" />
            아직 스킬 실행 기록이 없습니다
          </div>
        ) : (
          sessions.map(session => {
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
                  {/* 요청 내용 + 완료 시각 */}
                  <div className="flex items-start gap-1.5">
                    <Zap className="w-3 h-3 text-yellow-400 shrink-0 mt-0.5" />
                    <span className="text-[10px] text-white flex-1 leading-tight line-clamp-2">{session.request}</span>
                  </div>

                  {/* 스킬 체인 요약 + 진행률 배지 */}
                  <div className="flex items-center gap-1.5 pl-4">
                    {/* 스킬 이름 태그들 */}
                    <div className="flex gap-1 flex-1 flex-wrap">
                      {session.results.map((r, i) => (
                        <span
                          key={i}
                          className={`text-[8px] font-bold px-1 py-0.5 rounded ${statusBadge(r.status)}`}
                        >
                          {r.skill.replace('vibe-', '')}
                        </span>
                      ))}
                    </div>
                    {/* 완료율 */}
                    <span className="text-[9px] text-[#858585] shrink-0">
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
                            <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${statusBadge(r.status)}`}>
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
                    {/* 세션 ID */}
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
    </div>
  );
}
