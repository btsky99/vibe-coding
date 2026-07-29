/**
 * ------------------------------------------------------------------------
 * 📄 파일명: QuotaBadge.tsx
 * 📝 설명: 터미널 헤더 플랜 쿼터 배지 — Claude/Codex 5h 게이지+% · 7d %.
 *          데이터는 App.tsx의 /api/agent-quota 폴링에서 내려옴.
 * REVISION HISTORY:
 * - 2026-07-15 Claude: TerminalSlot.tsx 1500줄 상한 도달로 분리 (로직 무변경 이동)
 * - 2026-07-04 Claude: (TerminalSlot 내) 헤더 플랜 쿼터 배지 신설 — 세션 데이터 없어도 상시 표시
 * ------------------------------------------------------------------------
 */

// [WHY] 타입을 여기서 export — TerminalSlot이 props 타입으로 재사용 (import type이라 순환 없음).
// window_seconds: 창 길이(초). Codex free는 30일 창이라 "5h" 고정 라벨이 오표기 —
// 있으면 라벨을 동적 계산(5h/7d/30d), 없으면(Claude·구 스키마) 기존 5h/7d 유지.
export interface AgentQuotaInfo {
  available: boolean; reason?: string; plan?: string; stale?: boolean; observed_at?: string;
  five_hour?: { utilization: number; resets_at: string; window_seconds?: number } | null;
  seven_day?: { utilization: number; resets_at: string; window_seconds?: number } | null;
  seven_day_opus?: { utilization: number; resets_at: string; window_seconds?: number } | null;
  seven_day_sonnet?: { utilization: number; resets_at: string; window_seconds?: number } | null;
  model_windows?: Record<string, { utilization: number; resets_at: string; window_seconds?: number }>;
}

/**
 * [2026-07-04] 플랜 쿼터 배지 — Claude/Codex 슬롯 헤더 상시 표시.
 * 세션 JSONL 데이터(ctx) 유무와 무관하게 뜸 — "쿼터는 정상인데 안 보임" 원천 차단.
 * stale=Codex 토큰 만료로 세션 파일 마지막 관측값 폴백 → 흐리게 + ⏱ 표시
 */
export default function QuotaBadge({ agentType, quota }: {
  agentType: string;
  quota: AgentQuotaInfo | null | undefined;
}) {
  const q = quota;
  if (!q?.available || !q.five_hour) return null;
  const col = (u: number) => u >= 80 ? '#f87171' : u >= 60 ? '#facc15' : '#a3e635';
  const reset = (iso?: string) => {
    if (!iso) return '';
    const remain = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
    if (remain <= 0) return '리셋됨';
    const d = Math.floor(remain / 86400), h = Math.floor((remain % 86400) / 3600), m = Math.floor((remain % 3600) / 60);
    return d > 0 ? `${d}d ${h}h 후` : h > 0 ? `${h}h ${m}m 후` : `${m}m 후`;
  };
  const u5 = q.five_hour.utilization;
  // 창 길이 라벨 — window_seconds가 오면 동적(30d 등), 없으면 관례상 5h/7d
  const winLabel = (sec: number | undefined, fallback: string) => {
    if (!sec) return fallback;
    if (sec >= 2 * 86400) return `${Math.round(sec / 86400)}d`;
    if (sec >= 3600) return `${Math.round(sec / 3600)}h`;
    return `${Math.round(sec / 60)}m`;
  };
  const l5 = winLabel(q.five_hour.window_seconds, '5h');
  const l7 = winLabel(q.seven_day?.window_seconds, '7d');
  const tip = [
    `${agentType === 'claude' ? 'Claude' : 'Codex'} 플랜 사용률${q.plan ? ` (${q.plan})` : ''}`,
    `${l5} ${Math.round(u5)}% — 리셋 ${reset(q.five_hour.resets_at)}`,
    q.seven_day ? `${l7} ${Math.round(q.seven_day.utilization)}% — 리셋 ${reset(q.seven_day.resets_at)}` : '',
    q.stale ? `⚠ ${q.observed_at ? new Date(q.observed_at).toLocaleString() : ''} 마지막 관측값 — 일시 조회 실패, 자동 재시도 중` : '',
  ].filter(Boolean).join('\n');
  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-[9px] font-mono shrink-0 ${q.stale ? 'opacity-50 bg-white/5 border-white/10 text-[#999]' : 'bg-[#16210f]/80 border-lime-500/20 text-[#ccc]'}`}
      title={tip}
    >
      <span className="opacity-60 font-bold">{l5}</span>
      <div className="w-10 h-1.5 bg-black/40 rounded-full overflow-hidden border border-white/5">
        <div className="h-full transition-all duration-1000" style={{ width: `${Math.min(100, u5)}%`, backgroundColor: col(u5) }} />
      </div>
      <span className="font-black" style={{ color: col(u5) }}>{Math.round(u5)}%</span>
      {q.seven_day && (
        <>
          <span className="opacity-30">|</span>
          <span className="opacity-60 font-bold">{l7}</span>
          <span className="font-black" style={{ color: col(q.seven_day.utilization) }}>{Math.round(q.seven_day.utilization)}%</span>
        </>
      )}
      {q.stale && <span className="opacity-70">⏱</span>}
    </div>
  );
}
