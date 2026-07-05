/**
 * FILE: components/panels/HealPanel.tsx
 * DESCRIPTION: 자가치유 계측 패널 (읽기 전용). GET /api/heal/metrics를 불러 4장치
 *   (회상/사고/체크포인트/교훈)의 성과+커버리지를 verdict 뱃지와 바로 표시.
 *   계산 로직 없음 — 서버 heal_metrics 단일 소스가 낸 값을 그리기만.
 *
 * REVISION HISTORY:
 * - 2026-07-05 Claude: 신규 — 자가치유 계측 Task 4. 진입 시 1회 fetch(폴링 없음).
 */
import { useState, useEffect, useCallback } from 'react';
import { HeartPulse, RotateCw } from 'lucide-react';
import { API_BASE } from '../../constants';

interface HealMetrics {
  generated_at: string;
  project_id: string;
  recall: {
    tables: Record<string, { total: number; embed_pct: number; referenced: number }>;
    total_knowledge: number; embed_coverage_pct: number; referenced_pct: number;
    ref_sum: number; verdict: string; note: string;
  };
  incidents: {
    total: number; recurred: number; recurrence_rate_pct: number;
    sample_ok: boolean; min_sample: number; verdict: string; note: string;
  };
  checkpoints: { total: number; recent_7d: number; distinct_agents: number; verdict: string; note: string };
  lessons: { approved: number; verdict: string; note: string };
}

// 커버리지/비율 바 — verdict 색을 따라감
function Bar({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="h-1.5 w-full bg-white/10 rounded overflow-hidden">
      <div className={`h-full ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}

function Card({ title, verdict, subtitle, children }:
  { title: string; verdict: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-2.5 flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-[#dddddd]">{verdict} {title}</span>
      </div>
      <span className="text-[9px] text-[#888888]">{subtitle}</span>
      {children}
    </div>
  );
}

export default function HealPanel() {
  const [m, setM] = useState<HealMetrics | null>(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setErr('');
    fetch(`${API_BASE}/api/heal/metrics`)
      .then(r => r.json())
      .then(d => { if (d.error) setErr(d.error); else setM(d); })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="flex flex-col gap-2 overflow-y-auto text-[11px]">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 font-bold text-[#cccccc]">
          <HeartPulse className="w-4 h-4 text-rose-400" /> 자가치유 계측
        </span>
        <button onClick={load} disabled={loading}
          className="p-1 hover:bg-white/10 rounded text-[#888888] disabled:opacity-40" title="새로고침">
          <RotateCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {err && <div className="text-[10px] text-red-400 bg-red-500/10 rounded p-2">계측 오류: {err}</div>}
      {!m && !err && <div className="text-[10px] text-[#888888]">불러오는 중…</div>}

      {m && (
        <>
          <span className="text-[9px] text-[#666666]">{m.generated_at} · 범위 {m.project_id} · 성과+기록성실도 이중계측</span>

          <Card title="회상 v2" verdict={m.recall.verdict} subtitle="지식이 실제로 회상되나">
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-[#999999] w-14 shrink-0">임베딩 {m.recall.embed_coverage_pct}%</span>
              <Bar pct={m.recall.embed_coverage_pct} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-[#999999] w-14 shrink-0">참조율 {m.recall.referenced_pct}%</span>
              <Bar pct={m.recall.referenced_pct} />
            </div>
            <span className="text-[9px] text-[#777777]">
              전체 {m.recall.total_knowledge}건 · 참조합 {m.recall.ref_sum} · {m.recall.note}
            </span>
          </Card>

          <Card title="사고 장부 (북극성)" verdict={m.incidents.verdict} subtitle="같은 버그 재발 방지">
            <span className="text-[10px] text-[#bbbbbb]">
              총 {m.incidents.total}건 / 재발 {m.incidents.recurred}건 → 재발률 {m.incidents.recurrence_rate_pct}%
            </span>
            {!m.incidents.sample_ok && (
              <span className="text-[9px] text-yellow-400 bg-yellow-500/10 rounded px-1.5 py-0.5">
                🟡 표본 부족 (&lt;{m.incidents.min_sample}) — 재발률 0%가 성공 아님, 미측정
              </span>
            )}
            <span className="text-[9px] text-[#777777]">{m.incidents.note}</span>
          </Card>

          <Card title="체크포인트" verdict={m.checkpoints.verdict} subtitle="세션 튕김 후 이어받기">
            <span className="text-[10px] text-[#bbbbbb]">
              총 {m.checkpoints.total}건 · 최근 7일 {m.checkpoints.recent_7d}건 · 에이전트 {m.checkpoints.distinct_agents}명
            </span>
            <span className="text-[9px] text-[#777777]">{m.checkpoints.note}</span>
          </Card>

          <Card title="교훈 증류" verdict={m.lessons.verdict} subtitle="프로젝트 특화 학습">
            <span className="text-[10px] text-[#bbbbbb]">승인 교훈 {m.lessons.approved}건</span>
            <span className="text-[9px] text-[#777777]">{m.lessons.note}</span>
          </Card>
        </>
      )}
    </div>
  );
}
