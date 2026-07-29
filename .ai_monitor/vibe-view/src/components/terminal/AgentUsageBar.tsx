/**
 * FILE: components/terminal/AgentUsageBar.tsx
 * DESCRIPTION: 터미널 하단의 에이전트별 플랜·컨텍스트 사용량 바와 상세 팝업.
 *
 * REVISION HISTORY:
 * - 2026-07-26 Codex: Claude/Codex/Antigravity 공통 하단 사용량 UI 최초 작성.
 */
import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import type { AgentQuotaInfo } from './QuotaBadge';
import type { ClaudeUsage } from './ClaudeContextBar';

type AntigravityUsage = {
  total_tokens: number;
  context_window: number;
  percentage: number;
  model?: string;
  error?: string;
};

const colorFor = (value: number) =>
  value >= 95 ? '#ef4444' : value >= 80 ? '#f97316' : value >= 60 ? '#facc15' : '#22c55e';

const durationLabel = (seconds?: number, fallback = '5h') => {
  if (!seconds) return fallback;
  if (seconds >= 172800) return `${Math.round(seconds / 86400)}d`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 60)}m`;
};

const resetLabel = (iso?: string) => {
  if (!iso) return '리셋 정보 없음';
  const remain = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
  if (remain <= 0) return '리셋됨';
  const d = Math.floor(remain / 86400);
  const h = Math.floor((remain % 86400) / 3600);
  const m = Math.floor((remain % 3600) / 60);
  return d > 0 ? `${d}일 ${h}시간 후` : h > 0 ? `${h}시간 ${m}분 후` : `${m}분 후`;
};

const quotaLabel = (key: string) => {
  const model = key.replace(/^seven_day_/, '').replace(/^weekly_/, '');
  return model.split('_').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
};

export default function AgentUsageBar({
  agentType,
  quota,
  claudeUsage,
  antigravityUsage,
  onRefresh,
}: {
  agentType: string;
  quota?: AgentQuotaInfo | null;
  claudeUsage?: ClaudeUsage | null;
  antigravityUsage?: AntigravityUsage | null;
  onRefresh?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => tick(value => value + 1), 30000);
    return () => clearInterval(timer);
  }, [open]);

  const data = useMemo(() => {
    if (agentType === 'antigravity') {
      const pct = Number(antigravityUsage?.percentage || 0);
      const available = Boolean(antigravityUsage && antigravityUsage.total_tokens > 0);
      return {
        name: 'ANTIGRAVITY',
        available,
        percent: pct,
        remaining: Math.max(0, 100 - pct),
        window: 'context',
        resetAt: '',
        detail: available
          ? `${antigravityUsage?.total_tokens.toLocaleString()} / ${antigravityUsage?.context_window.toLocaleString()} tokens`
          : '현재 세션 사용량을 집계할 수 없습니다',
      };
    }
    const primary = quota?.five_hour;
    const pct = Number(primary?.utilization || 0);
    return {
      name: agentType === 'codex' ? 'CODEX' : 'CLAUDE',
      available: Boolean(quota?.available && primary),
      percent: pct,
      remaining: Math.max(0, 100 - pct),
      window: durationLabel(primary?.window_seconds, '5h'),
      resetAt: primary?.resets_at || '',
      detail: claudeUsage && agentType === 'claude'
        ? `컨텍스트 ${Math.round(claudeUsage.percentage || 0)}% · ${claudeUsage.model || ''}`
        : quota?.plan || '',
    };
  }, [agentType, quota, claudeUsage, antigravityUsage]);

  const filled = data.available ? Math.ceil(Math.min(100, data.percent) / 10) : 0;
  const color = colorFor(data.percent);
  const claudeWeekly = agentType === 'claude'
    ? [
        ...(quota?.seven_day ? [['모든 모델', quota.seven_day] as const] : []),
        ...(quota?.seven_day_opus ? [['Opus', quota.seven_day_opus] as const] : []),
        ...(quota?.seven_day_sonnet ? [['Sonnet', quota.seven_day_sonnet] as const] : []),
        ...Object.entries(quota?.model_windows || {}).map(
          ([key, value]) => [quotaLabel(key), value] as const,
        ),
      ]
    : [];

  return (
    <div className="relative shrink-0 border-t border-white/5 bg-[#151515] px-2 py-1">
      <div className="flex items-center gap-2 font-mono text-[9px] min-w-0">
        <div className="flex gap-[2px]" aria-label={`${Math.round(data.percent)}% 사용`}>
          {Array.from({ length: 10 }, (_, index) => (
            <span
              key={index}
              className="w-2 h-2 rounded-[2px] border border-white/5"
              style={{ backgroundColor: index < filled ? color : '#303030' }}
            />
          ))}
        </div>
        <span className="font-black" style={{ color }}>{data.name}</span>
        {data.available ? (
          <>
            <span className="text-white/65">{data.window} {Math.round(data.percent)}% 사용</span>
            <span className="text-white/35">·</span>
            <span className="text-white/55">{Math.round(data.remaining)}% 남음</span>
            {data.resetAt && <span className="text-white/35">· {resetLabel(data.resetAt)} 리셋</span>}
          </>
        ) : (
          <span className="text-white/35">사용량 조회 불가</span>
        )}
        <button
          type="button"
          onClick={() => setOpen(value => !value)}
          className="ml-auto px-2 py-0.5 rounded border border-white/10 bg-white/5 text-white/65 hover:text-white hover:bg-white/10"
        >
          사용량
        </button>
      </div>

      {open && (
        <div className="absolute right-2 bottom-7 z-50 w-72 rounded-lg border border-white/10 bg-[#202020] shadow-2xl p-3 text-[10px]">
          <div className="flex items-center justify-between mb-3">
            <strong className="text-white/90">{data.name} 사용량 상세</strong>
            <button onClick={() => setOpen(false)} className="text-white/40 hover:text-white"><X className="w-3.5 h-3.5" /></button>
          </div>
          <div className="h-2 rounded-full overflow-hidden bg-black/40 mb-2">
            <div className="h-full transition-all" style={{ width: `${Math.min(100, data.percent)}%`, backgroundColor: color }} />
          </div>
          <div className="grid grid-cols-2 gap-y-2 text-white/55">
            <span>사용</span><span className="text-right text-white/85">{data.available ? `${Math.round(data.percent)}%` : '조회 불가'}</span>
            <span>남음</span><span className="text-right text-white/85">{data.available ? `${Math.round(data.remaining)}%` : '-'}</span>
            <span>기준 창</span><span className="text-right text-white/85">{data.window}</span>
            <span>리셋</span><span className="text-right text-white/85">{data.resetAt ? resetLabel(data.resetAt) : '제공되지 않음'}</span>
            {agentType !== 'claude' && quota?.seven_day && (
              <><span>{durationLabel(quota.seven_day.window_seconds, '7d')}</span><span className="text-right text-white/85">{Math.round(quota.seven_day.utilization)}%</span></>
            )}
            {claudeWeekly.map(([label, window]) => (
              <span key={label} className="contents">
                <span>{label} 주간</span>
                <span className="text-right text-white/85">
                  {Math.round(window.utilization)}% 사용 · {Math.max(0, 100 - Math.round(window.utilization))}% 남음
                </span>
              </span>
            ))}
          </div>
          {data.detail && <div className="mt-3 pt-2 border-t border-white/5 text-white/40">{data.detail}</div>}
          <button
            onClick={onRefresh}
            className="mt-3 w-full flex items-center justify-center gap-1 py-1 rounded bg-white/5 hover:bg-white/10 text-white/60"
          >
            <RefreshCw className="w-3 h-3" /> 새로고침
          </button>
        </div>
      )}
    </div>
  );
}
