/**
 * FILE: DispatcherPanel.tsx
 * DESCRIPTION: 자율 멀티-LLM 태스크 디스패처 대시보드 패널.
 *   에이전트 역량 레이더 차트, 실시간 태스크 분배 현황, 크로스 검증 히스토리를 시각화합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-17 Claude: 최초 구현 — 역량 프로필 + 분배 현황 + 디스패치 UI
 * - 2026-03-19 Claude: hive_tasks에서 디스패치 히스토리 로드 기능 추가
 *   - 기존: React 상태에만 저장 → 새로고침 시 유실, CLI 디스패치 미표시
 *   - 수정: /api/dispatcher/history에서 DB 기록을 로드 + 세션 내 디스패치도 병합
 *   - 대시보드 "최근 디스패치" 패널이 비어있던 근본 원인 해결
 */

import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../../constants';
import {
  Send, Target, Shield, Zap, CheckCircle,
  RefreshCw, ChevronDown, ChevronUp, Users
} from 'lucide-react';

/* ── 타입 정의 ────────────────────────────────────────────────────────────── */
interface AgentScore {
  [agent: string]: number;
}

interface ScoreResponse {
  task_type: string;
  description: string;
  scores: AgentScore;
  best_agent: string;
  capabilities: { [agent: string]: { [cap: string]: number } };
}

interface DispatchResult {
  task_id: string;
  assigned_to: string;
  task_type: string;
  score: number;
  verifier: string | null;
  status: string;
  scores: AgentScore;
  description?: string;
  dispatched_at?: string;
}

interface DispatcherStatus {
  dispatched: number;
  verified: number;
  pending_verification: number;
  agent_load: { [agent: string]: number };
}

/* ── 에이전트 표시 색상 ───────────────────────────────────────────────────── */
const AGENT_COLORS: { [key: string]: string } = {
  claude: '#60a5fa',   // blue-400
  gemini: '#34d399',   // emerald-400
  codex: '#c084fc',    // purple-400
};

const AGENT_ICONS: { [key: string]: string } = {
  claude: '🤖',
  gemini: '💎',
  codex: '⚡',
};

/* ── 역량 레이더 차트 (SVG) ───────────────────────────────────────────────── */
// 간소화된 바 차트로 구현 (캔버스/D3 불필요)
function CapabilityChart({ capabilities }: { capabilities: { [agent: string]: { [cap: string]: number } } }) {
  const agents = Object.keys(capabilities);
  if (agents.length === 0) return null;

  // 모든 역량 키 수집
  const allCaps = Array.from(
    new Set(agents.flatMap(a => Object.keys(capabilities[a] || {})))
  ).sort();

  // 상위 8개 역량만 표시 (가독성)
  const topCaps = allCaps.slice(0, 8);

  return (
    <div className="space-y-1.5">
      {topCaps.map(cap => (
        <div key={cap} className="flex items-center gap-2 text-xs">
          {/* 역량 이름 */}
          <span className="w-24 text-white/50 truncate text-right">{cap}</span>
          {/* 에이전트별 바 */}
          <div className="flex-1 flex gap-0.5 items-center">
            {agents.map(agent => {
              const val = (capabilities[agent]?.[cap] || 0) * 100;
              return (
                <div key={agent} className="flex-1 h-3 bg-white/5 rounded-sm overflow-hidden" title={`${agent}: ${val.toFixed(0)}%`}>
                  <div
                    className="h-full rounded-sm transition-all duration-500"
                    style={{
                      width: `${val}%`,
                      backgroundColor: AGENT_COLORS[agent] || '#888',
                      opacity: 0.8,
                    }}
                  />
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {/* 범례 */}
      <div className="flex gap-3 justify-center mt-2">
        {agents.map(agent => (
          <span key={agent} className="flex items-center gap-1 text-xs text-white/60">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: AGENT_COLORS[agent] || '#888' }} />
            {agent}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ── 메인 패널 ────────────────────────────────────────────────────────────── */
export default function DispatcherPanel() {
  // 상태
  const [status, setStatus] = useState<DispatcherStatus | null>(null);
  const [scoreResult, setScoreResult] = useState<ScoreResponse | null>(null);
  const [dispatchHistory, setDispatchHistory] = useState<DispatchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showCapabilities, setShowCapabilities] = useState(true);

  // 디스패치 폼
  const [taskDesc, setTaskDesc] = useState('');
  const [taskType, setTaskType] = useState('auto');
  const [targetAgent, setTargetAgent] = useState('auto');
  const [priority, setPriority] = useState('medium');

  const mergeHistory = useCallback((current: DispatchResult[], incoming: DispatchResult[]) => {
    const merged = new Map(current.map(item => [item.task_id, item]));
    incoming.forEach(item => {
      const prev = merged.get(item.task_id);
      merged.set(item.task_id, { ...prev, ...item });
    });
    return Array.from(merged.values())
      .sort((a, b) => (b.dispatched_at || '').localeCompare(a.dispatched_at || ''))
      .slice(0, 30);
  }, []);

  // ── 데이터 로드 ──────────────────────────────────────────────────────────
  const fetchStatus = useCallback(() => {
    fetch(`${API_BASE}/api/dispatcher/status`)
      .then(r => r.json())
      .then(d => setStatus(d))
      .catch(err => console.error('[DispatcherPanel] status fetch:', err));
  }, []);

  // [2026-03-19 추가] hive_tasks에서 디스패치 히스토리 로드
  // DB에 영속 저장된 디스패치 레코드를 가져와서 세션 내 신규 디스패치와 병합합니다.
  const fetchHistory = useCallback(() => {
    fetch(`${API_BASE}/api/dispatcher/history`)
      .then(r => r.json())
      .then((data: DispatchResult[]) => {
        if (Array.isArray(data)) {
          setDispatchHistory(prev => mergeHistory(prev, data));
        }
      })
      .catch(err => console.error('[DispatcherPanel] history fetch:', err));
  }, [mergeHistory]);

  const fetchScore = useCallback((desc: string) => {
    if (!desc.trim()) return;
    const params = new URLSearchParams({ desc });
    if (taskType !== 'auto') params.set('type', taskType);
    fetch(`${API_BASE}/api/dispatcher/score?${params}`)
      .then(r => r.json())
      .then(d => setScoreResult(d))
      .catch(err => console.error('[DispatcherPanel] score fetch:', err));
  }, [taskType]);

  // 5초 폴링 — 상태 + 히스토리 모두 갱신
  useEffect(() => {
    fetchStatus();
    fetchHistory();
    const iv = setInterval(() => { fetchStatus(); fetchHistory(); }, 5000);
    return () => clearInterval(iv);
  }, [fetchStatus, fetchHistory]);

  // 입력 변경 시 점수 미리보기 (디바운스 500ms)
  useEffect(() => {
    if (!taskDesc.trim()) { setScoreResult(null); return; }
    const timer = setTimeout(() => fetchScore(taskDesc), 500);
    return () => clearTimeout(timer);
  }, [taskDesc, fetchScore]);

  // ── 디스패치 실행 ────────────────────────────────────────────────────────
  const handleDispatch = () => {
    if (!taskDesc.trim()) return;
    setIsLoading(true);
    fetch(`${API_BASE}/api/dispatcher/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        description: taskDesc,
        type: taskType === 'auto' ? undefined : taskType,
        to: targetAgent === 'auto' ? undefined : targetAgent,
        priority,
        verify: true,
      }),
    })
      .then(r => r.json())
      .then(result => {
        setDispatchHistory(prev => mergeHistory(prev, [{
          ...result,
          description: taskDesc,
          dispatched_at: new Date().toISOString(),
        }]));
        setTaskDesc('');
        fetchStatus();
      })
      .catch(err => console.error('[DispatcherPanel] dispatch:', err))
      .finally(() => setIsLoading(false));
  };

  // ── UI 렌더링 ────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-white/80">멀티-LLM 디스패처</span>
        </div>
        <button onClick={fetchStatus} className="p-1 hover:bg-white/10 rounded" title="새로고침">
          <RefreshCw className="w-3.5 h-3.5 text-white/40" />
        </button>
      </div>

      {/* 상태 요약 카드 */}
      {status && (
        <div className="grid grid-cols-3 gap-1.5 px-1">
          <div className="bg-white/5 rounded px-2 py-1.5 text-center">
            <div className="text-lg font-bold text-blue-400">{status.dispatched}</div>
            <div className="text-[10px] text-white/40">분배됨</div>
          </div>
          <div className="bg-white/5 rounded px-2 py-1.5 text-center">
            <div className="text-lg font-bold text-green-400">{status.verified}</div>
            <div className="text-[10px] text-white/40">검증됨</div>
          </div>
          <div className="bg-white/5 rounded px-2 py-1.5 text-center">
            <div className="text-lg font-bold text-yellow-400">{status.pending_verification}</div>
            <div className="text-[10px] text-white/40">검증대기</div>
          </div>
        </div>
      )}

      {/* 에이전트 부하 */}
      {status?.agent_load && (
        <div className="px-1 flex gap-1.5">
          {Object.entries(status.agent_load).map(([agent, load]) => (
            <div key={agent} className="flex-1 bg-white/5 rounded px-2 py-1 flex items-center gap-1.5">
              <span className="text-sm">{AGENT_ICONS[agent] || '🔧'}</span>
              <span className="text-xs text-white/60 capitalize">{agent}</span>
              <span className="ml-auto text-xs font-mono" style={{ color: AGENT_COLORS[agent] }}>{load}</span>
            </div>
          ))}
        </div>
      )}

      {/* 역량 차트 토글 */}
      <button
        onClick={() => setShowCapabilities(!showCapabilities)}
        className="flex items-center gap-1 px-2 py-1 text-xs text-white/50 hover:text-white/80"
      >
        {showCapabilities ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        <Users className="w-3 h-3" />
        에이전트 역량 프로필
      </button>
      {showCapabilities && scoreResult?.capabilities && (
        <div className="px-1">
          <CapabilityChart capabilities={scoreResult.capabilities} />
        </div>
      )}

      {/* 구분선 */}
      <div className="h-px bg-white/5 mx-1" />

      {/* 디스패치 폼 */}
      <div className="px-1 space-y-1.5">
        <div className="text-xs text-white/50 flex items-center gap-1">
          <Send className="w-3 h-3" /> 새 태스크 디스패치
        </div>

        {/* 태스크 설명 입력 */}
        <textarea
          value={taskDesc}
          onChange={e => setTaskDesc(e.target.value)}
          placeholder="태스크 설명을 입력하세요..."
          className="w-full bg-white/5 border border-white/10 rounded px-2 py-1.5 text-xs text-white/80
                     placeholder:text-white/20 resize-none focus:outline-none focus:border-primary/50"
          rows={2}
        />

        {/* 옵션 행 */}
        <div className="flex gap-1.5">
          <select
            value={taskType}
            onChange={e => setTaskType(e.target.value)}
            className="flex-1 bg-white/5 border border-white/10 rounded px-1.5 py-1 text-xs text-white/70"
          >
            <option value="auto">유형: 자동감지</option>
            <option value="bug_fix">버그 수정</option>
            <option value="feature">기능 추가</option>
            <option value="security">보안</option>
            <option value="perf">성능</option>
            <option value="frontend">프론트엔드</option>
            <option value="refactor">리팩토링</option>
            <option value="test">테스트</option>
            <option value="docs">문서화</option>
            <option value="research">조사</option>
            <option value="review">코드리뷰</option>
          </select>

          <select
            value={targetAgent}
            onChange={e => setTargetAgent(e.target.value)}
            className="flex-1 bg-white/5 border border-white/10 rounded px-1.5 py-1 text-xs text-white/70"
          >
            <option value="auto">에이전트: 자동</option>
            <option value="claude">Claude (T1)</option>
            <option value="gemini">Gemini (T2)</option>
            <option value="codex">Codex (T3)</option>
          </select>

          <select
            value={priority}
            onChange={e => setPriority(e.target.value)}
            className="w-20 bg-white/5 border border-white/10 rounded px-1.5 py-1 text-xs text-white/70"
          >
            <option value="low">Low</option>
            <option value="medium">Med</option>
            <option value="high">High</option>
            <option value="critical">Crit</option>
          </select>
        </div>

        {/* 적합도 미리보기 */}
        {scoreResult && (
          <div className="bg-white/5 rounded px-2 py-1.5 space-y-1">
            <div className="flex items-center gap-1 text-[10px] text-white/40">
              <Zap className="w-3 h-3" />
              유형: <span className="text-primary">{scoreResult.task_type}</span>
              &nbsp;|&nbsp; 최적: <span className="font-bold" style={{ color: AGENT_COLORS[scoreResult.best_agent] }}>
                {scoreResult.best_agent}
              </span>
            </div>
            <div className="flex gap-2">
              {Object.entries(scoreResult.scores).map(([agent, score]) => (
                <div key={agent} className="flex items-center gap-1 text-[10px]">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: AGENT_COLORS[agent] }} />
                  <span className="text-white/50">{agent}</span>
                  <span className="font-mono" style={{ color: AGENT_COLORS[agent] }}>
                    {(score as number).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 디스패치 버튼 */}
        <button
          onClick={handleDispatch}
          disabled={!taskDesc.trim() || isLoading}
          className="w-full py-1.5 rounded text-xs font-semibold flex items-center justify-center gap-1.5
                     bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-30 disabled:cursor-not-allowed
                     transition-colors"
        >
          {isLoading ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
          {isLoading ? '분배 중...' : '디스패치'}
        </button>
      </div>

      {/* 구분선 */}
      <div className="h-px bg-white/5 mx-1" />

      {/* 디스패치 히스토리 */}
      <div className="flex-1 overflow-y-auto px-1 space-y-1">
        <div className="text-xs text-white/50 flex items-center gap-1">
          <Shield className="w-3 h-3" /> 최근 디스패치
        </div>

        {dispatchHistory.length === 0 && (
          <div className="text-center text-xs text-white/20 py-4">
            아직 디스패치 기록이 없습니다
          </div>
        )}

        {dispatchHistory.map(item => (
          <div key={item.task_id} className="bg-white/5 rounded px-2 py-1.5 space-y-0.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono text-white/30">{item.task_id}</span>
              <span className={`text-[10px] px-1.5 rounded-full ${
                item.status === 'dispatched' ? 'bg-blue-500/20 text-blue-400' :
                item.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                'bg-white/10 text-white/50'
              }`}>
                {item.status}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-sm">{AGENT_ICONS[item.assigned_to] || '🔧'}</span>
              <span className="text-xs font-semibold" style={{ color: AGENT_COLORS[item.assigned_to] }}>
                {item.assigned_to}
              </span>
              <span className="text-[10px] text-white/30">({item.task_type})</span>
              {item.verifier && (
                <span className="text-[10px] text-white/30 flex items-center gap-0.5">
                  → <CheckCircle className="w-2.5 h-2.5 text-green-500/50" /> {item.verifier}
                </span>
              )}
            </div>
            <div className="flex gap-1.5 mt-0.5">
              {Object.entries(item.scores).map(([agent, score]) => (
                <span key={agent} className="text-[9px] font-mono text-white/30">
                  {agent}:{(score as number).toFixed(2)}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
