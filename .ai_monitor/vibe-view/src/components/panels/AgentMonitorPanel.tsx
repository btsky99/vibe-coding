/**
 * ------------------------------------------------------------------------
 * 파일명: AgentMonitorPanel.tsx
 * 설명: Paperclip 스타일 에이전트 하트비트 모니터.
 *       각 에이전트의 실시간 상태(working/idle/offline), 현재 태스크,
 *       하트비트 횟수를 카드 형태로 표시. 수동 트리거 버튼 포함.
 *
 * REVISION HISTORY:
 * - 2026-03-30 Claude: 최초 작성 — Paperclip 오케스트레이션 전환
 * ------------------------------------------------------------------------
 */

import { useState, useEffect } from 'react';
import { Activity, Zap, Power, PowerOff, Loader2, RefreshCw } from 'lucide-react';
import { API_BASE } from '../../constants';

// 에이전트 하트비트 데이터 타입
interface AgentBeat {
  agent_id: string;
  status: string;     // working | idle | offline
  last_beat: string;  // ISO timestamp
  current_task: string | null;
  beat_count: number;
  config?: string;
}

// 상태별 스타일 매핑
const STATUS_STYLES: Record<string, { icon: string; bg: string; text: string; border: string }> = {
  working: {
    icon: '🟢',
    bg: 'bg-green-500/10',
    text: 'text-green-400',
    border: 'border-green-500/30',
  },
  idle: {
    icon: '💤',
    bg: 'bg-yellow-500/5',
    text: 'text-yellow-400/70',
    border: 'border-yellow-500/20',
  },
  offline: {
    icon: '🔴',
    bg: 'bg-white/[0.02]',
    text: 'text-white/30',
    border: 'border-white/10',
  },
};

// 에이전트 이름 → 표시 라벨
const AGENT_LABELS: Record<string, string> = {
  'claude-T1': 'Claude (T1)',
  'gemini-T2': 'Gemini (T2)',
  'codex-T3': 'Codex (T3)',
  claude: 'Claude',
  gemini: 'Gemini',
  codex: 'Codex',
};

function relativeTime(iso?: string): string {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return '방금';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

export default function AgentMonitorPanel() {
  const [agents, setAgents] = useState<AgentBeat[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);

  // 에이전트 상태 폴링 (5초)
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agents/status`);
        if (res.ok && active) {
          const data = await res.json();
          setAgents(Array.isArray(data) ? data : []);
        }
      } catch {
        // 연결 실패 시 무시
      } finally {
        if (active) setLoading(false);
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // 수동 하트비트 트리거
  const handleTrigger = async (agentId: string) => {
    setTriggeringId(agentId);
    try {
      await fetch(`${API_BASE}/api/agents/${agentId}/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch {
      // 무시
    } finally {
      setTimeout(() => setTriggeringId(null), 1500);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-white/30">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
        <span className="text-xs">에이전트 상태 로딩...</span>
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="p-4 text-center">
        <PowerOff className="w-8 h-8 mx-auto text-white/20 mb-2" />
        <p className="text-xs text-white/40">등록된 에이전트 없음</p>
        <p className="text-[10px] text-white/25 mt-1">
          하트비트 러너를 시작하세요:<br />
          <code className="text-primary/60">python scripts/hive_heartbeat.py --agent claude-T1</code>
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-2">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5">
          <Activity className="w-3.5 h-3.5 text-primary" />
          <span className="text-[11px] font-bold text-white/80">에이전트 하트비트</span>
        </div>
        <span className="text-[10px] text-white/30">
          {agents.filter(a => a.status === 'working').length}개 활성
        </span>
      </div>

      {/* 에이전트 카드 */}
      {agents.map((agent) => {
        const style = STATUS_STYLES[agent.status] ?? STATUS_STYLES.offline;
        const label = AGENT_LABELS[agent.agent_id] ?? agent.agent_id;
        const isTriggering = triggeringId === agent.agent_id;

        return (
          <div
            key={agent.agent_id}
            className={`rounded-lg border ${style.border} ${style.bg} p-3 transition-colors`}
          >
            {/* 상단: 이름 + 상태 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm">{style.icon}</span>
                <span className="text-[12px] font-bold text-white/90">{label}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] font-semibold uppercase ${style.text}`}>
                  {agent.status}
                </span>
                {/* 트리거 버튼 */}
                <button
                  onClick={() => handleTrigger(agent.agent_id)}
                  disabled={isTriggering}
                  className="rounded p-1 hover:bg-white/10 transition-colors disabled:opacity-30"
                  title="하트비트 트리거"
                >
                  {isTriggering ? (
                    <Loader2 className="w-3 h-3 animate-spin text-primary" />
                  ) : (
                    <Zap className="w-3 h-3 text-white/40 hover:text-primary" />
                  )}
                </button>
              </div>
            </div>

            {/* 현재 태스크 */}
            {agent.current_task && (
              <p className="mt-1.5 text-[10px] text-white/50 line-clamp-1">
                <Power className="w-2.5 h-2.5 inline mr-1" />
                {agent.current_task}
              </p>
            )}

            {/* 하단: 마지막 하트비트 + 카운트 */}
            <div className="flex items-center justify-between mt-2">
              <span className="text-[9px] text-white/25">
                <RefreshCw className="w-2.5 h-2.5 inline mr-0.5" />
                {relativeTime(agent.last_beat)}
              </span>
              <span className="text-[9px] text-white/25">
                {agent.beat_count ?? 0}회 하트비트
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
