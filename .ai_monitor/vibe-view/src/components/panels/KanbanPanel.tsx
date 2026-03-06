/**
 * ------------------------------------------------------------------------
 * 파일명: KanbanPanel.tsx
 * 설명: 오케스트레이션 현황판.
 *       1번 컬럼: 전체 스킬 카탈로그 (영어+한글 설명 나열)
 *       2번~ 컬럼: 지시받아 실행 중인 각 스킬 (어떤 파일 수정, 변경 내용)
 *       데이터: /api/orchestrator/skill-chain (3초 폴링 — 라이브)
 *              /api/skill-results (10초 폴링 — 완료된 세션 요약)
 *
 * REVISION HISTORY:
 * - 2026-03-06 Claude: 최초 구현
 * - 2026-03-06 Claude: v6 — 스킬 카탈로그 + 실행 스킬 컬럼 통합 뷰
 *                           1번=전체스킬목록, 2번~=실행스킬(파일/변경내용)
 * ------------------------------------------------------------------------
 */

import { useState, useEffect } from 'react';
import { Monitor, Cpu, CheckCircle, Clock, AlertCircle, Loader, BookOpen, Radio } from 'lucide-react';
import { API_BASE } from '../../constants';

// ─── 타입 ─────────────────────────────────────────────────────────────────────

interface LiveStep {
  skill_name: string;
  status: string; // pending | running | done | failed
}

interface LiveChain {
  request: string;
  steps: LiveStep[];
}

interface SkillResult {
  skill: string;
  status: string;
  summary: string;
}

interface SkillSession {
  session_id: string;
  terminal_id?: number;
  request: string;
  results: SkillResult[];
  completed_at: string;
}

// ─── 전체 스킬 카탈로그 ────────────────────────────────────────────────────────
// 오케스트레이션이 사용할 수 있는 모든 스킬 목록 (영어명 + 한글명 + 설명)
const SKILL_CATALOG = [
  { name: 'vibe-orchestrate',  en: 'Orchestrate',   label: '오케스트레이터', desc: '요청 분석 → 필요한 스킬 자동 선택·실행', color: 'text-primary',    dot: 'bg-primary',    isMain: true  },
  { name: 'vibe-brainstorm',   en: 'Brainstorm',    label: '브레인스토밍',   desc: '기능 구현 전 요구사항 정제 및 설계 승인', color: 'text-yellow-400', dot: 'bg-yellow-400', isMain: false },
  { name: 'vibe-write-plan',   en: 'Write Plan',    label: '계획 작성',      desc: '승인된 설계를 마이크로태스크로 분해 저장', color: 'text-orange-400', dot: 'bg-orange-400', isMain: false },
  { name: 'vibe-execute-plan', en: 'Execute Plan',  label: '계획 실행',      desc: 'ai_monitor_plan.md 태스크 순서대로 실행', color: 'text-blue-400',   dot: 'bg-blue-400',   isMain: false },
  { name: 'vibe-debug',        en: 'Debug',         label: '디버그 분석',    desc: '버그/에러 근본 원인 4단계 분석 및 수정',  color: 'text-red-400',    dot: 'bg-red-400',    isMain: false },
  { name: 'vibe-tdd',          en: 'TDD',           label: '테스트 주도',    desc: 'RED-GREEN-REFACTOR 사이클 테스트 개발',   color: 'text-green-400',  dot: 'bg-green-400',  isMain: false },
  { name: 'vibe-code-review',  en: 'Code Review',   label: '코드 리뷰',      desc: '품질·보안(OWASP)·성능 4가지 관점 검토',  color: 'text-cyan-400',   dot: 'bg-cyan-400',   isMain: false },
  { name: 'vibe-release',      en: 'Release',       label: '릴리스',         desc: '버전증가 → 커밋 → 푸시 → GitHub Actions', color: 'text-purple-400', dot: 'bg-purple-400', isMain: false },
  { name: 'vibe-heal',         en: 'Self-Heal',     label: '자기 치유',      desc: '반복 오류 패턴 감지 및 근본 원인 자동 수정', color: 'text-pink-400', dot: 'bg-pink-400',   isMain: false },
];

// 스킬명 → 카탈로그 항목 빠른 조회
const SKILL_CATALOG_MAP: Record<string, typeof SKILL_CATALOG[number]> = Object.fromEntries(
  SKILL_CATALOG.map(s => [s.name, s])
);
function findSkill(name: string) {
  return SKILL_CATALOG_MAP[name] ?? SKILL_CATALOG_MAP['vibe-' + name] ?? null;
}

// ─── 상태 아이콘 ───────────────────────────────────────────────────────────────
function StatusIcon({ status, size = 'sm' }: { status: string; size?: 'sm' | 'md' }) {
  const cls = size === 'md' ? 'w-4 h-4' : 'w-3 h-3';
  if (status === 'running') return <Loader className={`${cls} text-amber-400 animate-spin shrink-0`} />;
  if (status === 'done')    return <CheckCircle className={`${cls} text-green-400 shrink-0`} />;
  if (status === 'failed')  return <AlertCircle className={`${cls} text-red-400 shrink-0`} />;
  return <Clock className={`${cls} text-[#555] shrink-0`} />;
}

// ─── 메인 컴포넌트 ─────────────────────────────────────────────────────────────
export default function KanbanPanel() {
  // 터미널별 라이브 체인
  const [liveChains, setLiveChains] = useState<Record<string, LiveChain>>({});
  // 최근 완료 세션 (요약 데이터)
  const [sessions, setSessions] = useState<SkillSession[]>([]);
  // 터미널 필터
  const [filter, setFilter] = useState<string>('all');

  // ── /api/orchestrator/skill-chain 폴링 (3초) ─────────────────────────────
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(r => r.json())
        .then(data => {
          const result: Record<string, LiveChain> = {};
          for (const [tid, chain] of Object.entries(data?.terminals ?? {})) {
            const steps: LiveStep[] = (chain as any)?.steps ?? [];
            // running 상태인 스텝이 하나라도 있어야만 표시
            // — pending만 있거나 전부 done/failed인 과거 체인은 표시 안 함
            const hasActive = steps.some(s => s.status === 'running');
            if (hasActive)
              result[tid] = { request: (chain as any)?.request ?? '', steps };
          }
          setLiveChains(result);
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  // ── /api/skill-results 폴링 (10초) — 완료 세션 요약 ─────────────────────
  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/skill-results`)
        .then(r => r.json())
        .then(data => setSessions(Array.isArray(data) ? data.slice(-5) : []))
        .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  // ── 필터 적용 체인 ────────────────────────────────────────────────────────
  const chainEntries = Object.entries(liveChains)
    .sort(([a], [b]) => a.localeCompare(b))
    .filter(([tid]) => filter === 'all' || tid === filter);

  // ── 통계 ─────────────────────────────────────────────────────────────────
  const runningCount = Object.values(liveChains)
    .flatMap(c => c.steps).filter(s => s.status === 'running').length;
  const hasLive = chainEntries.length > 0;

  // ── 완료 세션에서 스킬별 요약 찾기 헬퍼 ──────────────────────────────────
  function findSummary(skillName: string): string | null {
    for (const session of [...sessions].reverse()) {
      const r = session.results.find(r => r.skill === skillName || r.skill === skillName.replace(/^vibe-/, ''));
      if (r?.summary) return r.summary;
    }
    return null;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── 헤더 ─────────────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-white/8 bg-[#111]">
        <Monitor className="w-4 h-4 text-primary shrink-0" />
        <span className="text-[12px] font-bold text-white">오케스트레이션 현황판</span>
        {hasLive && (
          <span className="flex items-center gap-1 text-[8px] text-green-400">
            <Radio className="w-2.5 h-2.5 animate-pulse" />
            Live
          </span>
        )}

        {/* 터미널 필터 탭 */}
        <div className="flex gap-1 ml-3 flex-wrap">
          <button
            onClick={() => setFilter('all')}
            className={`text-[9px] font-bold px-2 py-0.5 rounded transition-colors ${
              filter === 'all' ? 'bg-primary text-white' : 'bg-white/5 text-[#777] hover:bg-white/10 hover:text-white'
            }`}
          >
            전체
          </button>
          {Object.keys(liveChains).sort().map(tid => (
            <button key={tid} onClick={() => setFilter(tid)}
              className={`text-[9px] font-bold px-2 py-0.5 rounded transition-colors ${
                filter === tid ? 'bg-primary text-white' : 'bg-white/5 text-[#777] hover:bg-white/10 hover:text-white'
              }`}
            >
              T{tid}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-3 text-[9px] text-[#555]">
          <span>실행 중 <span className={`font-bold ${runningCount > 0 ? 'text-amber-400' : 'text-[#444]'}`}>{runningCount}</span></span>
        </div>
      </div>

      {/* ── 컬럼 영역 ────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex gap-3 h-full px-4 py-3 min-w-max">

          {/* ════ 1번 컬럼: 오케스트레이션 스킬 카탈로그 ════════════════════ */}
          <div className="flex flex-col w-[230px] shrink-0 rounded-lg overflow-hidden border border-white/10 bg-[#0d0d0d]">
            {/* 컬럼 헤더 */}
            <div className="px-3 py-2.5 flex items-center gap-2 shrink-0 border-b border-white/8 bg-[#111]">
              <BookOpen className="w-3.5 h-3.5 text-primary shrink-0" />
              <span className="text-[11px] font-bold text-white">스킬 목록</span>
              <span className="ml-auto text-[8px] text-[#444]">Skill Catalog</span>
            </div>
            {/* 스킬 목록 — 영어명 + 한글명 + 설명 */}
            <div className="flex-1 overflow-y-auto bg-[#0d0d0d] p-2 custom-scrollbar space-y-1">
              {SKILL_CATALOG.map(skill => (
                <div key={skill.name}
                  className={`rounded-lg border px-2.5 py-2 transition-colors ${
                    skill.isMain
                      ? 'border-primary/25 bg-primary/5'
                      : 'border-white/6 bg-white/2 hover:border-white/10'
                  }`}
                >
                  {/* 영어명 + 주요 배지 */}
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${skill.dot} opacity-70`} />
                    <span className={`text-[11px] font-bold font-mono ${skill.color}`}>{skill.en}</span>
                    {skill.isMain && (
                      <span className="ml-auto text-[7px] bg-primary/20 text-primary px-1 py-0.5 rounded font-bold">MAIN</span>
                    )}
                  </div>
                  {/* 한글명 */}
                  <p className="text-[9px] font-semibold text-white/60 leading-tight mb-0.5 pl-3">{skill.label}</p>
                  {/* 한글 설명 */}
                  <p className="text-[7.5px] text-white/25 leading-snug pl-3">{skill.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {/* ════ 2번~: 실행 중인 스킬 컬럼들 ══════════════════════════════ */}
          {hasLive ? (
            chainEntries.flatMap(([tid, chain]) =>
              chain.steps.map((step, stepIdx) => {
                const s = step.status;
                const isRunning = s === 'running';
                const isDone    = s === 'done';
                const isFailed  = s === 'failed';
                const isPending = !isRunning && !isDone && !isFailed;

                // 컬럼 색상 테마
                const theme = isRunning
                  ? { border: 'border-amber-500/40', header: 'bg-amber-700', card: 'bg-amber-500/8', text: 'text-amber-200' }
                  : isDone
                  ? { border: 'border-green-500/30', header: 'bg-green-800', card: 'bg-green-500/6', text: 'text-green-300' }
                  : isFailed
                  ? { border: 'border-red-500/30', header: 'bg-red-900', card: 'bg-red-500/6', text: 'text-red-300' }
                  : { border: 'border-white/8', header: 'bg-[#1a1a1a]', card: 'bg-white/2', text: 'text-white/30' };

                // 이 스킬의 완료 요약 (skill-results에서 조회)
                const summary = findSummary(step.skill_name);
                // 카탈로그 항목으로 영어명/색상 조회
                const cat = findSkill(step.skill_name);

                return (
                  <div
                    key={`${tid}-${stepIdx}`}
                    className={`flex flex-col w-[240px] shrink-0 rounded-lg overflow-hidden border ${theme.border} transition-all ${
                      isRunning ? 'shadow-lg shadow-amber-500/10' : ''
                    }`}
                  >
                    {/* 컬럼 헤더 — 순서 번호 + 영어명 + 한글명 */}
                    <div className={`${theme.header} px-3 py-2.5 shrink-0`}>
                      <div className="flex items-center justify-between mb-0.5">
                        <div className="flex items-center gap-1.5">
                          <StatusIcon status={s} size="md" />
                          {/* 영어명 (mono) */}
                          <span className={`text-[11px] font-bold font-mono ${cat ? cat.color : theme.text} ${isRunning ? 'animate-pulse' : ''}`}>
                            {cat?.en ?? step.skill_name}
                          </span>
                        </div>
                        {/* 단계 번호 */}
                        <span className="text-[8px] font-bold bg-white/15 text-white/60 px-1.5 py-0.5 rounded font-mono shrink-0">
                          STEP {stepIdx + 1}
                        </span>
                      </div>
                      {/* 한글명 */}
                      <p className={`text-[9px] font-semibold pl-6 ${theme.text}`}>
                        {cat?.label ?? ''}
                      </p>
                    </div>

                    {/* 컬럼 바디 */}
                    <div className="flex-1 overflow-y-auto bg-[#141414] p-3 custom-scrollbar space-y-2.5">

                      {/* 상태 배지 + 터미널 */}
                      <div className="flex items-center justify-between">
                        <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${
                          isRunning ? 'bg-amber-500/15 text-amber-400'
                          : isDone   ? 'bg-green-500/15 text-green-400'
                          : isFailed ? 'bg-red-500/15 text-red-400'
                          : 'bg-white/5 text-[#555]'
                        }`}>
                          {isRunning ? '실행 중' : isDone ? '완료' : isFailed ? '실패' : '대기 중'}
                        </span>
                        <span className="text-[8px] font-bold bg-white/8 text-white/35 px-1.5 py-0.5 rounded font-mono">T{tid}</span>
                      </div>

                      {/* 지시 내용 (첫 번째 스텝에만) */}
                      {stepIdx === 0 && chain.request && (
                        <div className="rounded bg-white/3 border border-white/5 px-2 py-1.5">
                          <p className="text-[7px] text-[#444] font-bold uppercase tracking-wider mb-0.5">지시 내용</p>
                          <p className="text-[9px] text-white/40 leading-relaxed line-clamp-3">{chain.request}</p>
                        </div>
                      )}

                      {/* 실행 중: 진행 표시 */}
                      {isRunning && (
                        <div className="rounded bg-amber-500/8 border border-amber-500/20 px-2 py-2">
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <Loader className="w-2.5 h-2.5 text-amber-400 animate-spin" />
                            <span className="text-[8px] text-amber-400 font-bold">처리 중...</span>
                          </div>
                          <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                            <div className="h-full bg-amber-400/60 rounded-full animate-pulse" style={{ width: '60%' }} />
                          </div>
                        </div>
                      )}

                      {/* 완료: 변경 내용 요약 */}
                      {isDone && summary && (
                        <div className="rounded bg-green-500/8 border border-green-500/20 px-2 py-2">
                          <p className="text-[7px] text-green-400/60 font-bold uppercase tracking-wider mb-1">변경 내용</p>
                          <p className="text-[9px] text-green-200/70 leading-relaxed">{summary}</p>
                        </div>
                      )}
                      {isDone && !summary && (
                        <div className="rounded bg-green-500/5 border border-green-500/10 px-2 py-1.5">
                          <p className="text-[8px] text-green-400/40 italic">완료 — 요약 없음</p>
                        </div>
                      )}

                      {/* 대기 중 */}
                      {isPending && (
                        <div className="rounded bg-white/3 border border-white/5 px-2 py-2 text-center">
                          <p className="text-[8px] text-[#333] italic">앞 단계 완료 후 시작</p>
                        </div>
                      )}

                      {/* 실패 */}
                      {isFailed && (
                        <div className="rounded bg-red-500/8 border border-red-500/20 px-2 py-2">
                          <p className="text-[8px] text-red-400 font-bold">실행 실패</p>
                          {summary && <p className="text-[8px] text-red-300/60 mt-1">{summary}</p>}
                        </div>
                      )}

                      {/* 스킬명 (하단 참조용) */}
                      <p className="text-[7px] text-[#2a2a2a] font-mono pt-1 border-t border-white/4">{step.skill_name}</p>
                    </div>
                  </div>
                );
              })
            )
          ) : (
            /* ── 대기 상태: 빈 슬롯 안내 ── */
            <div className="flex items-center justify-center flex-1 min-w-[400px]">
              <div className="flex flex-col items-center gap-3 text-center">
                <Cpu className="w-10 h-10 text-[#1e1e1e]" />
                <p className="text-[12px] text-[#333] font-bold">오케스트레이션 대기 중</p>
                <p className="text-[9px] text-[#222] leading-relaxed">
                  지시를 내리면 오케스트레이션이 분석하여<br />
                  실행할 스킬 컬럼이 순서대로 나타납니다
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
