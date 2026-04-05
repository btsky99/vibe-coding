/**
 * ------------------------------------------------------------------------
 * 파일명: AgentMonitorPanel.tsx
 * 설명: Paperclip 스타일 에이전트 오케스트레이션 조직도 뷰.
 *       Dispatcher(사용자)를 루트로 실제 활성 터미널이 트리 구조로 연결되며,
 *       실시간 상태(running/idle/done/error), 현재 태스크, CLI 정보를 표시.
 *       터미널 API(/api/agent/terminals) 기반으로 동적 렌더링 — 하드코딩 없음.
 *
 * REVISION HISTORY:
 * - 2026-03-31 Claude: 터미널 API 기반 동적 조직도로 전면 재작성
 *   - 하드코딩된 3개 에이전트 → /api/agent/terminals에서 실제 터미널 동적 로드
 *   - 하트비트 API(/api/agents/status)를 보조로 병합 (beat_count, config 표시)
 *   - 터미널 수에 따라 조직도 자동 확장/축소
 * - 2026-03-31 Claude: Paperclip 정식 UI 모방 — HTML/CSS 카드형 조직도로 전면 재작성
 * - 2026-03-31 Claude: Paperclip 스타일 조직도(org chart) UI로 전면 리디자인
 * - 2026-03-30 Claude: 최초 작성 — Paperclip 오케스트레이션 전환
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Zap, Loader2, PowerOff, Code2, Globe, Wrench, Home, Terminal, Cpu } from 'lucide-react';
import { API_BASE } from '../../constants';

// ── 터미널 데이터 타입 (TaskBoardPanel과 동일) ──
interface TerminalStatus {
  status: 'running' | 'idle' | 'done' | 'error';
  task: string;
  cli: string;          // claude | gemini | codex 등
  run_id?: string;
  ts?: string;
  last_line?: string;
  pipeline_stage?: 'analyzing' | 'modifying' | 'verifying' | 'done' | 'idle';
  external?: boolean;
  interactive?: boolean;
}

// 에이전트 하트비트 데이터 타입 (보조 정보용)
interface AgentBeat {
  agent_id: string;
  status: string;
  last_beat: string;
  current_task: string | null;
  beat_count: number;
  config?: string;
}

// CLI별 아이콘/색상 매핑 — 새 CLI가 추가되면 자동으로 기본값 사용
const CLI_META: Record<string, {
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  color: string;
}> = {
  claude: { label: 'Claude', Icon: Code2, color: '#8b5cf6' },
  gemini: { label: 'Gemini', Icon: Globe, color: '#eab308' },
  codex:  { label: 'Codex',  Icon: Wrench, color: '#3b82f6' },
};

// 터미널 상태별 색상
const STATUS_COLORS: Record<string, { dot: string; glow: string; border: string }> = {
  running: {
    dot: '#22c55e',
    glow: '0 0 8px rgba(34, 197, 94, 0.6)',
    border: 'rgba(34, 197, 94, 0.3)',
  },
  idle: {
    dot: '#eab308',
    glow: '0 0 6px rgba(234, 179, 8, 0.4)',
    border: 'rgba(234, 179, 8, 0.2)',
  },
  done: {
    dot: '#6b7280',
    glow: 'none',
    border: 'rgba(255, 255, 255, 0.06)',
  },
  error: {
    dot: '#ef4444',
    glow: '0 0 8px rgba(239, 68, 68, 0.5)',
    border: 'rgba(239, 68, 68, 0.2)',
  },
};

// 파이프라인 스테이지 한글 표시
const STAGE_LABELS: Record<string, string> = {
  analyzing: '분석 중',
  modifying: '수정 중',
  verifying: '검증 중',
  done: '완료',
  idle: '대기',
};

function relativeTime(iso?: string): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!isFinite(diff) || diff < 0) return 'now';
  if (diff < 60) return `${Math.max(1, Math.floor(diff))}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

// ── 터미널 카드 (조직도 노드) ──
function TerminalCard({
  terminalId,
  terminal,
  heartbeat,
  onTrigger,
  isTriggering,
}: {
  terminalId: string;
  terminal: TerminalStatus;
  heartbeat?: AgentBeat;
  onTrigger: (id: string) => void;
  isTriggering: boolean;
}) {
  const cli = terminal.cli?.toLowerCase() ?? 'unknown';
  const meta = CLI_META[cli] ?? { label: cli, Icon: Terminal, color: '#9ca3af' };
  const colors = STATUS_COLORS[terminal.status] ?? STATUS_COLORS.done;
  const { Icon } = meta;

  // 하트비트에서 에이전트 ID 추출 (있으면)
  const agentId = heartbeat?.agent_id ?? `${cli}-${terminalId}`;

  return (
    <div
      className="org-card"
      style={{
        background: 'rgba(255, 255, 255, 0.04)',
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: '14px 16px 12px',
        minWidth: 170,
        maxWidth: 220,
        cursor: 'pointer',
        transition: 'border-color 0.3s, box-shadow 0.3s',
        position: 'relative',
      }}
      onClick={() => onTrigger(agentId)}
      title={`${terminalId} — ${meta.label} (${terminal.status})`}
    >
      {/* 트리거 로딩 오버레이 */}
      {isTriggering && (
        <div style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 12,
          background: 'rgba(0,0,0,0.4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2,
        }}>
          <Loader2 className="w-5 h-5 animate-spin text-white/60" />
        </div>
      )}

      {/* 터미널 ID 배지 + CLI 배지 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: 'white',
          background: 'rgba(255,255,255,0.08)',
          padding: '2px 6px',
          borderRadius: 4,
          letterSpacing: '0.02em',
        }}>
          {terminalId}
        </span>
        <span style={{
          fontSize: 10,
          fontWeight: 600,
          color: meta.color,
          background: `${meta.color}15`,
          padding: '2px 6px',
          borderRadius: 4,
        }}>
          {meta.label}
        </span>
      </div>

      {/* 아이콘 + 역할/태스크 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <Icon className="w-3.5 h-3.5" />
        <span style={{
          fontSize: 13,
          fontWeight: 700,
          color: 'white',
          letterSpacing: '-0.01em',
        }}>
          {terminal.task
            ? (terminal.task.length > 25 ? terminal.task.slice(0, 25) + '…' : terminal.task)
            : `${meta.label} 세션`}
        </span>
      </div>

      {/* 상태 dot + 상태 텍스트 + 시간 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: colors.dot,
            boxShadow: colors.glow,
            display: 'inline-block',
            flexShrink: 0,
            animation: terminal.status === 'running' ? 'pulse-dot 2s ease-in-out infinite' : 'none',
          }}
        />
        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase' }}>
          {terminal.status}
        </span>
        {/* 파이프라인 스테이지 */}
        {terminal.pipeline_stage && terminal.pipeline_stage !== 'idle' && (
          <span style={{
            fontSize: 9,
            color: 'rgba(255,255,255,0.3)',
            background: 'rgba(255,255,255,0.05)',
            padding: '1px 5px',
            borderRadius: 3,
          }}>
            {STAGE_LABELS[terminal.pipeline_stage] ?? terminal.pipeline_stage}
          </span>
        )}
        {terminal.ts && (
          <span style={{
            fontSize: 9,
            color: 'rgba(255,255,255,0.2)',
            marginLeft: 'auto',
          }}>
            {relativeTime(terminal.ts)}
          </span>
        )}
      </div>

      {/* last_line 표시 (있으면) */}
      {terminal.last_line && (
        <div style={{
          marginTop: 6,
          padding: '3px 7px',
          borderRadius: 5,
          background: 'rgba(255,255,255,0.03)',
          fontSize: 9,
          color: 'rgba(255,255,255,0.25)',
          lineHeight: 1.3,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontFamily: 'monospace',
        }}>
          {terminal.last_line.length > 50 ? terminal.last_line.slice(0, 50) + '…' : terminal.last_line}
        </div>
      )}

      {/* 하트비트 정보: last_beat + beat_count */}
      {heartbeat && (
        <div style={{
          marginTop: 6,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 10,
          color: 'rgba(255,255,255,0.4)',
        }}>
          {heartbeat.last_beat && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <Cpu className="w-3 h-3" style={{ opacity: 0.5 }} />
              {relativeTime(heartbeat.last_beat)}
            </span>
          )}
          {heartbeat.beat_count > 0 && (
            <span style={{
              marginLeft: 'auto',
              fontSize: 9,
              color: 'rgba(255,255,255,0.2)',
              display: 'flex',
              alignItems: 'center',
              gap: 2,
            }}>
              <Zap className="w-2.5 h-2.5" />
              {heartbeat.beat_count}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Dispatcher (루트) 카드 ──
function DispatcherCard() {
  return (
    <div
      style={{
        background: 'rgba(255, 255, 255, 0.05)',
        border: '1px solid rgba(255, 255, 255, 0.1)',
        borderRadius: 12,
        padding: '14px 20px 12px',
        minWidth: 160,
        display: 'inline-block',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
        <Home className="w-4 h-4 text-white/50" />
        <span style={{
          fontSize: 15,
          fontWeight: 700,
          color: 'white',
          letterSpacing: '-0.01em',
        }}>
          Dispatcher
        </span>
      </div>
      <div style={{
        fontSize: 11,
        color: 'rgba(255,255,255,0.35)',
        marginBottom: 4,
      }}>
        Task Orchestrator
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: '#22c55e',
          boxShadow: '0 0 6px rgba(34, 197, 94, 0.5)',
          display: 'inline-block',
        }} />
        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.45)' }}>
          User
        </span>
      </div>
    </div>
  );
}

// 활동 로그 항목 타입
interface ActivityLogEntry {
  agent: string;
  task: string;
  status: string;
  ts: string;
  terminal_id?: string;
}

// ── 메인 컴포넌트: 터미널 기반 동적 조직도 ──
export default function AgentMonitorPanel() {
  const [terminals, setTerminals] = useState<Record<string, TerminalStatus>>({});
  const [heartbeats, setHeartbeats] = useState<AgentBeat[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);
  const [activityLogs, setActivityLogs] = useState<ActivityLogEntry[]>([]);

  // 터미널 상태 폴링 (3초) — 주 데이터 소스
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agent/terminals`);
        if (res.ok && active) {
          const data = await res.json();
          if (data && typeof data === 'object') {
            setTerminals(data);
          }
        }
      } catch {
        // 연결 실패 시 무시
      } finally {
        if (active) setLoading(false);
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // 하트비트 보조 폴링 (10초) — beat_count 등 보조 정보
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agents/status`);
        if (res.ok && active) {
          const data = await res.json();
          setHeartbeats(Array.isArray(data) ? data : []);
        }
      } catch {
        // 무시
      }
    };
    poll();
    const id = setInterval(poll, 10000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // pg_logs 활동 로그 폴링 (15초)
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/kanban/pg-activity`);
        if (res.ok && active) {
          const data = await res.json();
          // 전체 터미널의 로그를 합쳐서 시간순 정렬, 최근 10개만
          const all: ActivityLogEntry[] = [];
          for (const entries of Object.values(data)) {
            if (Array.isArray(entries)) {
              for (const e of entries as ActivityLogEntry[]) {
                all.push(e);
              }
            }
          }
          all.sort((a, b) => (b.ts ?? '').localeCompare(a.ts ?? ''));
          setActivityLogs(all.slice(0, 6));
        }
      } catch { /* 무시 */ }
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // 터미널 → 하트비트 매핑 (T1 → claude-T1 등)
  const heartbeatMap = useMemo(() => {
    const map: Record<string, AgentBeat> = {};
    for (const hb of heartbeats) {
      map[hb.agent_id] = hb;
    }
    return map;
  }, [heartbeats]);

  // 하트비트 키에서 터미널 ID에 매칭되는 것 찾기 (claude-T1 → T1)
  const getHeartbeat = useCallback((terminalId: string, cli: string): AgentBeat | undefined => {
    // 정확한 매칭: "claude-T1", "gemini-T2" 등
    const exact = heartbeatMap[`${cli}-${terminalId}`];
    if (exact) return exact;
    // CLI 이름만으로 매칭 (하트비트가 "claude", "gemini" 등으로 등록된 경우)
    return heartbeatMap[cli];
  }, [heartbeatMap]);

  // 활성 터미널만 필터 (external 제외, 실제 세션이 있는 것만)
  const activeTerminals = useMemo(() => {
    return Object.entries(terminals)
      .filter(([_, t]) => !t.external && (t.status === 'running' || t.status === 'idle'))
      .sort(([a], [b]) => a.localeCompare(b));
  }, [terminals]);

  // 오프라인 에이전트 감지 (5분 이상 heartbeat 없음) — 얼리 리턴 전에 선언 (Hooks 규칙)
  const offlineAgents = useMemo(() => {
    return heartbeats.filter(hb => {
      if (!hb.last_beat) return true;
      const age = (Date.now() - new Date(hb.last_beat).getTime()) / 1000;
      return age > 300;
    });
  }, [heartbeats]);

  // 수동 하트비트 트리거
  const handleTrigger = useCallback(async (agentId: string) => {
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
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-white/30">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
        <span className="text-xs">터미널 상태 로딩...</span>
      </div>
    );
  }

  if (activeTerminals.length === 0) {
    return (
      <div className="p-4 text-center">
        <PowerOff className="w-8 h-8 mx-auto text-white/20 mb-2" />
        <p className="text-xs text-white/40">활성 터미널 없음</p>
        <p className="text-[10px] text-white/25 mt-1">
          터미널을 시작하면 조직도에 자동으로 표시됩니다.
        </p>
      </div>
    );
  }

  const runningCount = activeTerminals.filter(([_, t]) => t.status === 'running').length;

  return (
    <div className="flex flex-col gap-3 p-3 overflow-auto">
      {/* 오프라인 에이전트 경고 배너 */}
      {offlineAgents.length > 0 && (
        <div style={{
          padding: '8px 12px',
          borderRadius: 8,
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.2)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <PowerOff className="w-3.5 h-3.5" style={{ color: '#ef4444', flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#fca5a5' }}>
              오프라인 에이전트 {offlineAgents.length}개
            </div>
            <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 1 }}>
              {offlineAgents.map(a => a.agent_id).join(', ')} — 에이전트 카드 클릭으로 재시도
            </div>
          </div>
        </div>
      )}

      {/* 글로벌 스타일 — 펄스 애니메이션 + 트리 연결선 */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        .org-card:hover {
          border-color: rgba(255, 255, 255, 0.2) !important;
          box-shadow: 0 0 20px rgba(255, 255, 255, 0.03);
        }
        .org-tree {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
        }
        .org-tree-trunk {
          width: 1px;
          height: 28px;
          background: rgba(255, 255, 255, 0.1);
        }
        .org-child-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .org-child-stem {
          width: 1px;
          height: 28px;
          background: rgba(255, 255, 255, 0.1);
        }
      `}</style>

      {/* 헤더 */}
      <div className="flex items-center justify-between px-1">
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: 'rgba(255, 255, 255, 0.7)',
          letterSpacing: '0.02em',
        }}>
          Agent Orchestration
        </span>
        <span style={{
          fontSize: 10,
          color: 'rgba(255, 255, 255, 0.25)',
        }}>
          {runningCount}/{activeTerminals.length} active
        </span>
      </div>

      {/* 조직도 트리 */}
      <div className="org-tree">
        {/* 루트: Dispatcher */}
        <DispatcherCard />

        {/* 수직 줄기 */}
        <div className="org-tree-trunk" />

        {/* 자식 터미널들 — 수평 배치 + 연결선 */}
        <div style={{ position: 'relative', display: 'flex', justifyContent: 'center' }}>
          {/* 수평 연결 바 */}
          {activeTerminals.length > 1 && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: '50%',
              transform: 'translateX(-50%)',
              height: 1,
              background: 'rgba(255, 255, 255, 0.1)',
              width: `calc(100% - 170px)`,
            }} />
          )}

          <div style={{
            display: 'flex',
            gap: 14,
            justifyContent: 'center',
            flexWrap: 'wrap',
          }}>
            {activeTerminals.map(([id, terminal]) => {
              const cli = terminal.cli?.toLowerCase() ?? 'unknown';
              const hb = getHeartbeat(id, cli);
              const agentId = hb?.agent_id ?? `${cli}-${id}`;
              return (
                <div key={id} className="org-child-wrapper">
                  <div className="org-child-stem" />
                  <TerminalCard
                    terminalId={id}
                    terminal={terminal}
                    heartbeat={hb}
                    onTrigger={handleTrigger}
                    isTriggering={triggeringId === agentId}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 하단: 최근 에이전트 활동 로그 (pg_logs) */}
      {activityLogs.length > 0 && (
        <div style={{
          marginTop: 4,
          padding: '8px 10px',
          borderRadius: 8,
          background: 'rgba(59, 130, 246, 0.05)',
          border: '1px solid rgba(59, 130, 246, 0.1)',
        }}>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginBottom: 6, letterSpacing: '0.05em' }}>
            RECENT ACTIVITY
          </div>
          {activityLogs.map((log, i) => {
            const cli = log.agent?.toLowerCase() ?? '';
            const meta = CLI_META[cli];
            return (
              <div key={`log-${i}`} style={{
                fontSize: 10,
                color: 'rgba(255,255,255,0.4)',
                display: 'flex',
                gap: 6,
                alignItems: 'center',
                marginBottom: 3,
                lineHeight: 1.4,
              }}>
                <span style={{
                  fontSize: 9,
                  color: 'rgba(255,255,255,0.2)',
                  fontFamily: 'monospace',
                  minWidth: 48,
                  flexShrink: 0,
                }}>
                  {log.ts}
                </span>
                <span style={{
                  fontWeight: 600,
                  color: meta?.color ?? '#9ca3af',
                  minWidth: 48,
                  flexShrink: 0,
                }}>
                  {meta?.label ?? log.agent}
                </span>
                <span style={{
                  color: log.status === 'error' ? '#ef4444' : 'rgba(255,255,255,0.3)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {log.task ? (log.task.length > 35 ? log.task.slice(0, 35) + '…' : log.task) : log.status}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* 하단: running 터미널 태스크 요약 */}
      {activeTerminals.some(([_, t]) => t.status === 'running' && t.task) && (
        <div style={{
          marginTop: 4,
          padding: '8px 10px',
          borderRadius: 8,
          background: 'rgba(34, 197, 94, 0.06)',
          border: '1px solid rgba(34, 197, 94, 0.1)',
        }}>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginBottom: 4 }}>
            ACTIVE TASKS
          </div>
          {activeTerminals
            .filter(([_, t]) => t.status === 'running' && t.task)
            .map(([id, t]) => {
              const cli = t.cli?.toLowerCase() ?? 'unknown';
              const meta = CLI_META[cli];
              return (
                <div key={id} style={{
                  fontSize: 10,
                  color: 'rgba(255,255,255,0.5)',
                  display: 'flex',
                  gap: 6,
                  alignItems: 'baseline',
                  marginBottom: 2,
                }}>
                  <span style={{
                    fontWeight: 700,
                    color: 'white',
                    background: 'rgba(255,255,255,0.08)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    fontSize: 9,
                  }}>
                    {id}
                  </span>
                  <span style={{ color: meta?.color ?? '#9ca3af', fontWeight: 600 }}>
                    {meta?.label ?? cli}
                  </span>
                  <span style={{ color: 'rgba(255,255,255,0.3)' }}>
                    {t.task.length > 40 ? t.task.slice(0, 40) + '…' : t.task}
                  </span>
                </div>
              );
            })
          }
        </div>
      )}
    </div>
  );
}
