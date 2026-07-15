/**
 * ------------------------------------------------------------------------
 * 📄 파일명: ClaudeContextBar.tsx
 * 📝 설명: Claude 컨텍스트 컬러 블록 바 + 클릭 상세 팝업(/context 스타일 블록 그리드,
 *          플랜 쿼터 사용률, 카테고리별 사용량). 데이터는 App.tsx의 세션 JSONL 폴링.
 * REVISION HISTORY:
 * - 2026-07-15 Claude: TerminalSlot.tsx 1500줄 상한 도달로 분리 (로직 무변경 이동,
 *                      showCtxDetail 상태는 이 컴포넌트 전용이라 함께 이동)
 * - 2026-04-21 Claude: (TerminalSlot 내) context_used = input + cache_read + cache_write
 * - 2026-03-26 Claude: (TerminalSlot 내) 리팩토링 복원 — 클릭 시 상세 팝업
 * ------------------------------------------------------------------------
 */
import { useState } from 'react';

// [WHY] 타입을 여기서 export — TerminalSlot props가 재사용 (import type이라 순환 없음).
export interface ClaudeUsage {
  input_tokens: number; output_tokens: number; cache_read: number; cache_write: number;
  context_used?: number;  // [2026-04-21] input + cache_read + cache_write (캐시 포함 실제 점유)
  model: string; context_window: number; percentage: number; last_ts: string;
  // [2026-04-21] 5시간 sliding window 집계 (JSONL 절대값 — quota 실패 시 폴백 표시용)
  last_5h_tokens?: number;
  last_5h_messages?: number;
  last_5h_oldest_ts?: string;
  // [2026-07-03] OAuth 쿼터 사용률 — 5h/7d 한도 대비 % + 리셋 시각 (CodexBar 방식)
  quota?: {
    available: boolean; reason?: string; plan?: string;
    five_hour?: { utilization: number; resets_at: string } | null;
    seven_day?: { utilization: number; resets_at: string } | null;
    seven_day_opus?: { utilization: number; resets_at: string } | null;
    seven_day_sonnet?: { utilization: number; resets_at: string } | null;
  } | null;
}

export default function ClaudeContextBar({ ctx }: { ctx: ClaudeUsage | null }) {
  // Claude 컨텍스트 바 상세 토글 (클릭 시 In/Out/Cache 2행 표시)
  const [showCtxDetail, setShowCtxDetail] = useState(false);

  const CTX_MAX = ctx?.context_window ?? 200000;
  const inputTok = ctx?.input_tokens ?? 0;
  const outputTok = ctx?.output_tokens ?? 0;
  const cacheRead = ctx?.cache_read ?? 0;
  const cacheWrite = ctx?.cache_write ?? 0;
  // [2026-04-21] 실제 컨텍스트 점유 = 현재 턴 input + 캐시 히트 + 캐시 생성.
  // Claude Code CLI `/context` 와 동일. 서버가 context_used를 주면 그대로 쓰고
  // 없으면(구 응답) 프론트에서 합산한다.
  const usedTok = ctx?.context_used ?? (inputTok + cacheRead + cacheWrite);
  const ctxPct = ctx ? Math.round((usedTok / CTX_MAX) * 100) : 0;
  const freeTok = Math.max(0, CTX_MAX - usedTok);

  // 각 토큰 타입의 컨텍스트 점유 %
  const cacheReadPct = Math.min(100, (cacheRead / CTX_MAX) * 100);
  const cacheWritePct = Math.min(100, (cacheWrite / CTX_MAX) * 100);
  const inputOnlyPct = Math.max(0, ctxPct - cacheReadPct - cacheWritePct);
  const freePct = Math.max(0, 100 - ctxPct);

  // 배경 & 경고 색
  const dangerBg = ctxPct >= 80 ? 'bg-red-950/30 border-red-500/15'
    : ctxPct >= 60 ? 'bg-yellow-950/30 border-yellow-500/15'
    : 'bg-[#0d1117] border-white/5';
  const modelColor = ctxPct >= 80 ? '#f87171' : ctxPct >= 60 ? '#facc15' : '#a3e635';

  // 모델명 단축
  const modelShort = ctx?.model
    ? ctx.model.replace(/^claude-/, '').replace(/-(\d)/, ' $1').replace(/-latest$/, '').replace(/-\d{8}$/, '').replace(/\b\w/g, c => c.toUpperCase())
    : 'Claude';
  const maxLabel = CTX_MAX >= 1_000_000 ? `${CTX_MAX / 1_000_000}M` : `${CTX_MAX / 1000}k`;
  const usedLabel = `${Math.round(usedTok / 1000)}k`;

  // 상대 시간
  const ctxRelTime = (() => {
    if (!ctx?.last_ts) return '';
    const diff = Math.floor((Date.now() - new Date(ctx.last_ts).getTime()) / 1000);
    if (diff < 60) return `${diff}초 전`;
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    return `${Math.floor(diff / 86400)}일 전`;
  })();

  // 카테고리 목록
  const pureInput = Math.max(0, inputTok - cacheRead - cacheWrite);
  const categories = [
    { label: '입력 토큰', tok: pureInput, pct: inputOnlyPct, color: '#fbbf24' },
    ...(cacheWrite > 0 ? [{ label: '캐시 쓰기', tok: cacheWrite, pct: cacheWritePct, color: '#4ade80' }] : []),
    ...(cacheRead > 0 ? [{ label: '캐시 읽기', tok: cacheRead, pct: cacheReadPct, color: '#22d3ee' }] : []),
    { label: '출력 누적', tok: outputTok, pct: Math.round((outputTok / CTX_MAX) * 100), color: '#888' },
    { label: '여유 공간', tok: freeTok, pct: freePct, color: '#2a2d3a' },
  ];
  const fmtTok = (t: number) => t >= 1000 ? `${(t / 1000).toFixed(1)}k` : `${t}`;

  // OAuth 쿼터 표시 헬퍼 — resets_at(ISO) → 남은 시간, 사용률 → 경고색
  const quota = ctx?.quota?.available ? ctx.quota : null;
  const fmtReset = (iso: string) => {
    const remain = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
    if (remain <= 0) return '곧 리셋';
    const d = Math.floor(remain / 86400);
    const h = Math.floor((remain % 86400) / 3600);
    const m = Math.floor((remain % 3600) / 60);
    if (d > 0) return `${d}d ${h}h 후`;
    return h > 0 ? `${h}h ${m}m 후` : `${m}m 후`;
  };
  const quotaColor = (u: number) => u >= 80 ? '#f87171' : u >= 60 ? '#facc15' : '#a3e635';

  return (
    <div className="relative shrink-0">
      {/* 단일 행 바 (항상 표시) */}
      <div
        className={`border-b px-3 py-[3px] flex items-center gap-2 font-mono text-[10px] overflow-hidden cursor-pointer select-none transition-colors hover:brightness-110 ${dangerBg}`}
        onClick={() => setShowCtxDetail(p => !p)}
        title="클릭하여 컨텍스트 상세 보기"
      >
        {/* 컬러 블록 바: 20개 █, 각 5% */}
        <div className="flex shrink-0 leading-none">
          {Array.from({ length: 20 }, (_, idx) => {
            const p = (idx + 1) * 5;
            const color = p <= cacheReadPct ? '#22d3ee'
              : p <= cacheReadPct + cacheWritePct ? '#4ade80'
              : p <= ctxPct ? '#fbbf24'
              : '#2a2d3a';
            return <span key={idx} style={{ color, fontSize: 11, letterSpacing: '-0.5px' }}>█</span>;
          })}
        </div>
        {/* 텍스트: 모델명 (컨텍스트 크기) · 사용량 */}
        <div className="flex items-center gap-0 whitespace-nowrap flex-1 min-w-0">
          <span className="font-semibold" style={{ color: modelColor }}>{modelShort}</span>
          <span className="text-[#555] ml-1 text-[9px]">({maxLabel} context)</span>
          <span className="text-[#444] mx-1.5">·</span>
          <span className="text-[#ccc]">{usedLabel}/{maxLabel} tokens ({ctxPct}%)</span>
          {ctx && ctxRelTime && <span className="text-[#333] ml-2 text-[9px]">{ctxRelTime}</span>}
          <span className="ml-auto text-[#333] text-[8px]">{showCtxDetail ? '▲' : '▼'}</span>
        </div>
        {!ctx && <span className="text-[9px] text-[#333] italic">Claude Code 세션 대기 중...</span>}
      </div>
      {/* 데이터 없을 때 2행: No usage data yet */}
      {!ctx && (
        <div className="border-b border-white/5 bg-[#0d1117] px-3 py-[2px] font-mono text-[9px] text-[#444] italic">
          No usage data yet
        </div>
      )}
      {/* 데이터 있을 때 2행: In / Out / Cache+ / Cache~ · 5h 누적 */}
      {ctx && (
        <div className="border-b border-white/5 bg-[#0d1117] px-3 py-[2px] font-mono text-[9px] text-[#888] flex items-center gap-3 flex-wrap">
          <span>In: <span className="text-[#fbbf24]">{fmtTok(inputTok)}</span></span>
          <span>Out: <span className="text-[#ccc]">{fmtTok(outputTok)}</span></span>
          {cacheWrite > 0 && <span>Cache+: <span className="text-[#4ade80]">{fmtTok(cacheWrite)}</span></span>}
          {cacheRead > 0 && <span>Cache~: <span className="text-[#22d3ee]">{fmtTok(cacheRead)}</span></span>}
          {quota?.five_hour ? (
            // 쿼터 사용률 우선 표시 — 플랜 한도 대비 실제 % + 리셋 카운트다운
            <span
              className="ml-auto text-[#666]"
              title={`플랜 한도 대비 사용률${quota.plan ? ` (${quota.plan})` : ''} — 로컬 5h ${fmtTok(ctx.last_5h_tokens ?? 0)} tokens · ${ctx.last_5h_messages ?? 0}회`}
            >
              5h <span style={{ color: quotaColor(quota.five_hour.utilization) }}>{Math.round(quota.five_hour.utilization)}%</span>
              {quota.five_hour.resets_at && (
                <span className="text-[#444] ml-1">({fmtReset(quota.five_hour.resets_at)})</span>
              )}
              {quota.seven_day && (
                <>
                  <span className="text-[#444] mx-1">·</span>
                  7d <span style={{ color: quotaColor(quota.seven_day.utilization) }}>{Math.round(quota.seven_day.utilization)}%</span>
                </>
              )}
            </span>
          ) : (ctx.last_5h_tokens ?? 0) > 0 ? (
            // 폴백: 쿼터 API 실패/미가용 시 기존 JSONL 절대값
            <span className="ml-auto text-[#666]" title="지난 5시간 누적 (cwd 일치 세션)">
              5h: <span className="text-[#a3e635]">{fmtTok(ctx.last_5h_tokens ?? 0)}</span>
              <span className="text-[#444] ml-1">· {ctx.last_5h_messages ?? 0}회</span>
            </span>
          ) : null}
        </div>
      )}

      {/* 상세 팝업: /context 스타일 블록 그리드 + 카테고리 + 5h sliding (클릭 토글) */}
      {showCtxDetail && ctx && (() => {
        // 5시간 집계 리셋 시각 계산: oldest_ts + 5h
        const oldestMs = ctx.last_5h_oldest_ts ? new Date(ctx.last_5h_oldest_ts).getTime() : 0;
        const resetLabel = oldestMs
          ? (() => {
              const remainSec = Math.max(0, Math.floor((oldestMs + 5 * 3600 * 1000 - Date.now()) / 1000));
              if (remainSec <= 0) return '곧 초기화';
              const h = Math.floor(remainSec / 3600);
              const m = Math.floor((remainSec % 3600) / 60);
              return h > 0 ? `${h}h ${m}m 후` : `${m}m 후`;
            })()
          : '';
        return (
          <div className="absolute top-full left-0 right-0 z-50 bg-[#0d1117] border-b border-x border-white/10 shadow-2xl font-mono text-[10px] px-3 pt-2 pb-3 space-y-3">
            {/* ── 상단 프로그레스 바 — CLI /context 스타일 ── */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[#ccc] font-bold text-[11px]">컨텍스트 창</span>
                <span className="text-[#ccc] text-[10px]">
                  {usedLabel}/{maxLabel} ({ctxPct}%)
                </span>
              </div>
              <div className="h-2 bg-[#1a1a2e] rounded-full overflow-hidden flex">
                {/* 캐시 읽기 · 쓰기 · 입력 순서로 쌓인 스택형 프로그레스 */}
                <div style={{ width: `${cacheReadPct}%`, backgroundColor: '#22d3ee' }} />
                <div style={{ width: `${cacheWritePct}%`, backgroundColor: '#4ade80' }} />
                <div style={{ width: `${inputOnlyPct}%`, backgroundColor: '#fbbf24' }} />
              </div>
            </div>

            {/* ── 플랜 쿼터 사용률 (OAuth /api/oauth/usage) — 실패 시 절대값 폴백 ── */}
            {quota ? (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[#ccc] font-bold text-[11px]">플랜 쿼터 사용률</span>
                  {quota.plan && <span className="text-[#555] text-[9px] uppercase">{quota.plan}</span>}
                </div>
                <div className="space-y-[5px]">
                  {([
                    { label: '5시간', win: quota.five_hour },
                    { label: '7일', win: quota.seven_day },
                    { label: '7일 Opus', win: quota.seven_day_opus },
                    { label: '7일 Sonnet', win: quota.seven_day_sonnet },
                  ] as const).filter(r => r.win).map(r => (
                    <div key={r.label} className="flex items-center gap-2">
                      <span className="text-[#999] w-14 shrink-0">{r.label}</span>
                      <div className="flex-1 h-1.5 bg-[#1a1a2e] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${Math.min(100, r.win!.utilization)}%`, backgroundColor: quotaColor(r.win!.utilization) }}
                        />
                      </div>
                      <span className="w-9 text-right" style={{ color: quotaColor(r.win!.utilization) }}>
                        {Math.round(r.win!.utilization)}%
                      </span>
                      <span className="text-[#555] w-16 text-right text-[9px]">
                        {r.win!.resets_at ? fmtReset(r.win!.resets_at) : ''}
                      </span>
                    </div>
                  ))}
                </div>
                {(ctx.last_5h_tokens ?? 0) > 0 && (
                  <div className="text-[9px] text-[#555] leading-tight mt-1">
                    로컬 5h 집계: {fmtTok(ctx.last_5h_tokens ?? 0)} tokens · {ctx.last_5h_messages ?? 0}회
                    {resetLabel && <span> · {resetLabel} 롤오프</span>}
                  </div>
                )}
              </div>
            ) : (ctx.last_5h_tokens ?? 0) > 0 ? (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[#ccc] font-bold text-[11px]">5시간 누적 사용량</span>
                  <span className="text-[#888] text-[10px]">
                    {fmtTok(ctx.last_5h_tokens ?? 0)} tokens · {ctx.last_5h_messages ?? 0}회
                    {resetLabel && <span className="text-[#555] ml-2">· {resetLabel} 롤오프</span>}
                  </span>
                </div>
                <div className="text-[9px] text-[#555] leading-tight">
                  cwd 일치 세션의 지난 5h assistant usage 합계. (쿼터 API 미가용 — 절대값 폴백)
                </div>
              </div>
            ) : null}

            {/* ── 카테고리별 사용량 ── */}
            <div className="pt-1 space-y-[3px]">
              <div className="text-[#444] text-[9px] mb-1">카테고리별 사용량</div>
              {categories.map(cat => (
                <div key={cat.label} className="flex items-center gap-1">
                  <span style={{ color: cat.color, fontSize: 9 }}>█</span>
                  <span className="text-[#999] w-14">{cat.label}</span>
                  <span className="text-[#ccc] w-10 text-right">{fmtTok(cat.tok)}</span>
                  <div className="flex-1 h-1 bg-[#1a1a2e] rounded-full overflow-hidden ml-1">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, cat.pct)}%`, backgroundColor: cat.color }} />
                  </div>
                  <span className="text-[#555] w-8 text-right">{Math.round(cat.pct)}%</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
