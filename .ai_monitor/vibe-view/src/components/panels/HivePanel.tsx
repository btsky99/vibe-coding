/**
 * FILE: HivePanel.tsx
 * DESCRIPTION: 하이브 진단 패널 — 에이전트 상태 모니터링 + 시스템 헬스 체크 + 자가 치유 UI.
 *              App.tsx에서 분리된 독립 컴포넌트로, 오케스트레이터 상태와 하이브 헬스를
 *              자체 폴링하여 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import { Bot, AlertTriangle, Cpu, RotateCw, CheckCircle2, Zap, Ghost, Users, Activity, Brain } from 'lucide-react';
import { HiveHealth, OrchestratorStatus, MemoryEntry } from '../../types';
import { API_BASE } from '../../constants';

// 작성자 태그 색상 매핑 — B.2 작성자 식별 강화와 맞물리는 시각적 구분.
// claude 계열은 초록, gemini 계열은 파랑, user는 보라, 기타(unknown/legacy)는 회색.
function authorBadgeClass(author: string): string {
  const a = (author || '').toLowerCase();
  if (a.startsWith('claude')) return 'bg-green-500/15 text-green-400';
  if (a.startsWith('gemini')) return 'bg-blue-500/15 text-blue-400';
  if (a.startsWith('codex')) return 'bg-purple-500/15 text-purple-400';
  if (a === 'user') return 'bg-cyan-500/15 text-cyan-400';
  return 'bg-white/10 text-white/50';
}

// 작성자 LLM 계열 추출 — 'claude-t1' → 'claude', 'gemini:terminal-3' → 'gemini'
function authorFamily(author: string): string {
  const a = (author || '').toLowerCase();
  const cut = a.split(/[-:]/, 2)[0];
  return cut || 'unknown';
}

/**
 * HivePanel
 *
 * 역할: 하이브 에이전트 상태와 시스템 헬스를 실시간으로 표시하고,
 *       스킬 복구 및 자가 치유 액션을 제공하는 독립 패널 컴포넌트.
 *
 * 폴링 주기:
 *   - /api/orchestrator/status : 3초 (에이전트 상태 + 경고 + 터미널 슬롯 현황)
 *   - /api/hive/health         : 30초 (하이브 시스템 진단 데이터)
 *
 * props: 없음 (완전 독립 컴포넌트 — 모든 데이터를 자체 폴링)
 */
export default function HivePanel() {
  // 오케스트레이터 상태 — 에이전트별 상태, 터미널 슬롯, 경고, 태스크 분배
  const [orchStatus, setOrchStatus] = useState<OrchestratorStatus | null>(null);
  // 하이브 시스템 진단 데이터 — 파일 존재 여부, DB 상태, 자가 치유 기록 등
  const [hiveHealth, setHiveHealth] = useState<HiveHealth | null>(null);
  // 복구/치유 액션 후 결과 메시지를 잠시 표시하기 위한 상태
  const [spMsg, setSpMsg] = useState('');
  // 스킬 복구 버튼용 현재 경로 — 서버 설정에서 가져옴
  const [currentPath, setCurrentPath] = useState('');
  // B.3 — 최근 공유 메모리 (모든 프로젝트). 20초 폴링.
  const [recentMemory, setRecentMemory] = useState<MemoryEntry[]>([]);

  // ── 오케스트레이터 상태 폴링 (3초 간격) ──────────────────────────────────
  useEffect(() => {
    const fetchOrch = () => {
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then((data: OrchestratorStatus) => setOrchStatus(data))
        .catch((err) => console.error('[HivePanel] fetch error:', err));
    };
    fetchOrch();
    const interval = setInterval(fetchOrch, 3000);
    return () => clearInterval(interval);
  }, []);

  // ── 하이브 헬스 API 호출 함수 (버튼에서도 직접 호출 가능) ────────────────
  const fetchHiveHealth = () => {
    fetch(`${API_BASE}/api/hive/health`)
      .then(res => res.json())
      .then(data => setHiveHealth(data))
      .catch((err) => console.error('[HivePanel] fetch error:', err));
  };

  // ── 하이브 헬스 폴링 — 마운트 시 1회 + 30초 간격 자동 갱신 ─────────────
  useEffect(() => {
    fetchHiveHealth();
    const interval = setInterval(fetchHiveHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  // ── 현재 프로젝트 경로 로드 — 서버 설정에서 가져옴 ──────────────────────
  // 스킬 복구 버튼에서 경로를 API로 전달하기 위해 필요
  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then(res => res.json())
      .then(data => { if (data.path) setCurrentPath(data.path); })
      .catch((err) => console.error('[HivePanel] fetch error:', err));
  }, []);

  // ── 최근 공유 메모리 폴링 (20초) — B.3 + C.1 ─────────────────────────────
  // all=true로 전역 집계, top=20으로 작성자 분포 파악에 충분한 샘플 확보.
  // include_zettel=true로 zettel_notes(정제 지식)도 함께 집계 대상에 포함.
  useEffect(() => {
    const fetchRecent = () => {
      fetch(`${API_BASE}/api/memory?all=true&top=20&include_zettel=true`)
        .then(res => res.json())
        .then(data => setRecentMemory(Array.isArray(data) ? data : []))
        .catch((err) => console.error('[HivePanel] memory fetch error:', err));
    };
    fetchRecent();
    const interval = setInterval(fetchRecent, 20000);
    return () => clearInterval(interval);
  }, []);

  return (
    /* ── 하이브 진단 패널 — 에이전트 상태 + 시스템 헬스 ── */
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* 오케스트레이터 데이터 로딩 중 안내 */}
      {!orchStatus ? (
        <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
          <Bot className="w-7 h-7 opacity-20" />
          하이브 데이터 연결 중...
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-3">

          {/* 경고 배너 — 경고가 있을 때만 표시 */}
          {orchStatus.warnings && orchStatus.warnings.length > 0 && (
            <div className="p-2 rounded border border-yellow-500/40 bg-yellow-500/5">
              <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-yellow-300">
                <AlertTriangle className="w-3.5 h-3.5" /> 경고 ({orchStatus.warnings.length})
              </div>
              {orchStatus.warnings.map((w, i) => (
                <div key={i} className="text-[9px] text-yellow-200 pl-3 py-0.5">⚠ {w}</div>
              ))}
            </div>
          )}

          {/* ── 4.3 오케스트레이터 한 눈에 카드 ── */}
          {(() => {
            const agents = orchStatus.agent_status || {};
            const dist = orchStatus.task_distribution || {};
            const activeCount = Object.values(agents).filter((a: any) => a.state === 'active').length;
            const idleCount = Object.values(agents).filter((a: any) => a.state === 'idle').length;
            const deadCount = Object.values(agents).filter((a: any) =>
              a.state === 'unknown' || (a.state === 'idle' && a.idle_sec > 86400)
            ).length;
            const totalPending = Object.values(dist).reduce((sum: number, d: any) => sum + (d?.pending || 0), 0);
            const totalInProgress = Object.values(dist).reduce((sum: number, d: any) => sum + (d?.in_progress || 0), 0);
            return (
              <div className="p-2.5 rounded border border-white/10 bg-white/[0.02]">
                <div className="text-[10px] font-bold text-[#969696] mb-2 flex items-center gap-1.5">
                  <Activity className="w-3 h-3" /> 오케스트레이터 한 눈에
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="p-1.5 rounded bg-green-500/10 border border-green-500/20">
                    <div className="text-lg font-bold text-green-400">{activeCount}</div>
                    <div className="text-[8px] text-green-300/60">활성</div>
                  </div>
                  <div className="p-1.5 rounded bg-yellow-500/10 border border-yellow-500/20">
                    <div className="text-lg font-bold text-yellow-400">{idleCount}</div>
                    <div className="text-[8px] text-yellow-300/60">유휴</div>
                  </div>
                  <div className={`p-1.5 rounded border ${deadCount > 0 ? 'bg-red-500/10 border-red-500/20' : 'bg-white/5 border-white/10'}`}>
                    <div className={`text-lg font-bold ${deadCount > 0 ? 'text-red-400' : 'text-[#555]'}`}>{deadCount}</div>
                    <div className={`text-[8px] ${deadCount > 0 ? 'text-red-300/60' : 'text-[#555]'}`}>사망</div>
                  </div>
                </div>
                <div className="flex gap-3 mt-2 text-[9px] font-mono justify-center">
                  <span className="text-[#858585]">대기 {totalPending}</span>
                  <span className="text-primary">진행 {totalInProgress}</span>
                </div>
              </div>
            );
          })()}

          {/* ── 4.5+4.6 에이전트 분포 카드 + 유령 배지 ── */}
          {orchStatus.agent_status && (
            <div className="p-2.5 rounded border border-white/10 bg-white/[0.02]">
              <div className="text-[10px] font-bold text-[#969696] mb-2 flex items-center gap-1.5">
                <Users className="w-3 h-3" /> 에이전트 분포
              </div>
              <div className="flex flex-col gap-1.5">
                {Object.entries(orchStatus.agent_status).map(([name, info]: [string, any]) => {
                  const isDead = info.state === 'unknown' || (info.state === 'idle' && info.idle_sec > 86400);
                  const isIdle = info.state === 'idle' && !isDead;
                  const isActive = info.state === 'active';
                  const dist = orchStatus.task_distribution?.[name];
                  const taskCount = dist ? (dist.pending || 0) + (dist.in_progress || 0) : 0;

                  return (
                    <div key={name} className={`flex items-center justify-between p-1.5 rounded text-xs ${isDead ? 'opacity-40' : ''}`}>
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-400 animate-pulse' : isIdle ? 'bg-yellow-400' : 'bg-red-400/50'}`} />
                        <span className="font-mono text-[#ccc]">{name}</span>
                        {isDead && (
                          <span className="flex items-center gap-0.5 text-[8px] text-red-400/70 bg-red-500/10 px-1 rounded">
                            <Ghost className="w-2.5 h-2.5" /> 유령
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[9px] font-mono">
                        {taskCount > 0 && (
                          <span className={`px-1 rounded ${taskCount >= 5 ? 'bg-red-500/20 text-red-400' : 'bg-white/10 text-[#999]'}`}>
                            {taskCount}건
                          </span>
                        )}
                        <span className={`${isActive ? 'text-green-400' : isIdle ? 'text-yellow-400' : 'text-[#555]'}`}>
                          {isActive ? '활성' : isIdle ? `${Math.floor(info.idle_sec / 60)}분 유휴` : '미확인'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── B.3 + C.1 최근 공유 메모리 카드 ── */}
          {/* 에이전트별 누적 메모 분포 + hive/zettel source 집계 + 최근 5건. */}
          {recentMemory.length > 0 && (() => {
            // 작성자 계열별 집계 (claude / gemini / codex / user / unknown 등)
            const familyCounts: Record<string, number> = {};
            let hiveCount = 0;
            let zettelCount = 0;
            for (const e of recentMemory) {
              const fam = authorFamily(e.author);
              familyCounts[fam] = (familyCounts[fam] || 0) + 1;
              if (e.source === 'zettel') zettelCount++;
              else hiveCount++;
            }
            const families = Object.entries(familyCounts).sort((a, b) => b[1] - a[1]);
            const recent5 = recentMemory.slice(0, 5);
            return (
              <div className="p-2.5 rounded border border-white/10 bg-white/[0.02]">
                <div className="text-[10px] font-bold text-[#969696] mb-2 flex items-center gap-1.5">
                  <Brain className="w-3 h-3" /> 최근 공유 메모리
                  <span className="ml-auto text-[9px] text-[#555] font-normal">
                    최근 {recentMemory.length}건
                  </span>
                </div>
                {/* C.1 — hive / zettel 소스 집계 */}
                <div className="flex gap-1 mb-1.5">
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-white/5 text-[#aaa]">
                    💾 hive {hiveCount}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-bold font-mono bg-purple-500/15 text-purple-300">
                    🧠 zettel {zettelCount}
                  </span>
                </div>
                {/* 작성자 계열별 집계 배지 */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {families.map(([fam, cnt]) => (
                    <span
                      key={fam}
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold font-mono ${authorBadgeClass(fam)}`}
                    >
                      {fam} {cnt}
                    </span>
                  ))}
                </div>
                {/* 최근 5건 리스트 */}
                <div className="flex flex-col gap-1">
                  {recent5.map(entry => (
                    <div
                      key={entry.key}
                      className="flex items-center justify-between gap-2 text-[9px] py-0.5"
                      title={entry.title || entry.key}
                    >
                      <span className="shrink-0 text-[8px]" title={entry.source === 'zettel' ? `zettel ${entry.note_type || ''}` : 'hive'}>
                        {entry.source === 'zettel' ? '🧠' : '💾'}
                      </span>
                      <span className="font-mono text-[#ccc] truncate flex-1 min-w-0">
                        {entry.key}
                      </span>
                      <span
                        className={`px-1 rounded text-[8px] font-bold shrink-0 ${authorBadgeClass(entry.author)}`}
                      >
                        {entry.author}
                      </span>
                      <span className="text-[#555] text-[8px] font-mono shrink-0">
                        {(entry.updated_at || '').slice(5, 16).replace('T', ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* 태스크 분배 전체 요약 — all 키가 있을 때만 표시 */}
          {orchStatus.task_distribution?.all && (() => {
            const allDist = orchStatus.task_distribution.all;
            const total = (allDist.pending || 0) + (allDist.in_progress || 0);
            return total > 0 ? (
              <div className={`p-2 rounded border ${total >= 5 ? 'border-red-500/40 bg-red-500/5' : 'border-yellow-500/30 bg-yellow-500/5'}`}>
                <div className="text-[9px] font-bold text-yellow-300 mb-1">⚠ 미할당 태스크 (all): {total}건</div>
                <div className="flex gap-3 text-[9px] font-mono">
                  <span className="text-[#858585]">대기: {allDist.pending}</span>
                  <span className="text-primary">진행: {allDist.in_progress}</span>
                  <span className="text-green-400">완료: {allDist.done}</span>
                </div>
              </div>
            ) : null;
          })()}
        </div>
      )}

      {/* 하이브 시스템 진단 위젯 — 에이전트 상태 하단 고정 배치 */}
      <div className="shrink-0 p-3 rounded border border-white/10 bg-black/20 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-bold text-[#969696] flex items-center gap-1.5 uppercase tracking-tighter">
            <Cpu className="w-4 h-4" /> 하이브 시스템 진단
          </div>
          {/* 수동 새로고침 버튼 */}
          <button
            onClick={fetchHiveHealth}
            className="p-1 hover:bg-white/10 rounded transition-colors text-[#858585]"
            title="새로고침"
          >
            <RotateCw className="w-3 h-3" />
          </button>
        </div>

        {/* 헬스 데이터 로딩 중 안내 */}
        {!hiveHealth ? (
          <div className="text-xs text-[#555] italic">진단 데이터 로드 중...</div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {/* 코어 지침 파일 존재 여부 */}
              <div className="flex flex-col gap-1">
                <div className="text-[10px] text-[#666] mb-0.5 font-bold">📜 코어 지침</div>
                {(
                  [
                    ['RULES.md',   hiveHealth.constitution?.rules_md],
                    ['CLAUDE.md',  hiveHealth.constitution?.claude_md],
                    ['GEMINI.md',  hiveHealth.constitution?.gemini_md],
                    ['AGENTS.md',  hiveHealth.constitution?.agents_md],
                    ['PROJECT_MAP', hiveHealth.constitution?.project_map],
                  ] as [string, boolean | undefined][]
                ).map(([label, ok]) => (
                  <div key={label} className="flex items-center justify-between text-xs">
                    <span className="text-[#bbb]">{label}</span>
                    {ok
                      ? <CheckCircle2 className="w-3 h-3 text-green-400" />
                      : <AlertTriangle className="w-3 h-3 text-red-500" />
                    }
                  </div>
                ))}
              </div>
              {/* 핵심 스킬 파일 존재 여부 */}
              <div className="flex flex-col gap-1">
                <div className="text-[10px] text-[#666] mb-0.5 font-bold">🧠 핵심 스킬</div>
                {(
                  [
                    ['Brainstorm', hiveHealth.skills?.brainstorm],
                    ['Memory',     hiveHealth.skills?.memory_script],
                    ['GUI',        hiveHealth.skills?.gui],
                  ] as [string, boolean | undefined][]
                ).map(([label, ok]) => (
                  <div key={label} className="flex items-center justify-between text-xs">
                    <span className="text-[#bbb]">{label}</span>
                    {ok
                      ? <CheckCircle2 className="w-3 h-3 text-green-400" />
                      : <AlertTriangle className="w-3 h-3 text-red-500" />
                    }
                  </div>
                ))}
              </div>
            </div>

            {/* 자가 치유 엔진 상태 요약 */}
            <div className="pt-2 border-t border-white/10 flex flex-col gap-1.5">
              <div className="text-[10px] text-[#666] flex items-center justify-between font-bold">
                <span>🛡️ 자가 치유 엔진</span>
                <span className="text-primary/60">v4.0</span>
              </div>
              {(
                [
                  ['DB 연결성',   hiveHealth.db_ok    ? '정상' : '오류', hiveHealth.db_ok],
                  ['에이전트 활동', hiveHealth.agent_active ? '활발' : '유휴', hiveHealth.agent_active],
                ] as [string, string, boolean][]
              ).map(([label, val, ok]) => (
                <div key={label} className="flex items-center justify-between text-xs">
                  <span className="text-[#bbb]">{label}</span>
                  <span className={`font-bold ${ok ? 'text-green-400' : 'text-yellow-400'}`}>{val}</span>
                </div>
              ))}
              {/* 인프라 복구 횟수 */}
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#bbb]">인프라 복구</span>
                <span className="text-primary font-bold">{hiveHealth.repair_count ?? 0}회</span>
              </div>
              {/* 스킬 자기치유 횟수 */}
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#bbb]">스킬 자기치유</span>
                <span className="text-green-400 font-bold">{hiveHealth.skill_heal_count ?? 0}회</span>
              </div>
              {/* 마지막 점검 시각 */}
              {hiveHealth.last_check && (
                <div className="text-[10px] text-[#555] text-right italic">
                  최근 점검: {new Date(hiveHealth.last_check).toLocaleTimeString()}
                </div>
              )}
            </div>

            {/* 자기치유 이벤트 로그 — 워치독이 실제로 무엇을 복구했는지 표시 */}
            {hiveHealth.logs && hiveHealth.logs.length > 0 && (
              <div className="pt-2 border-t border-white/10 flex flex-col gap-1">
                <div className="text-[10px] text-[#666] mb-1 font-bold">📋 자기치유 이벤트 로그</div>
                <div className="flex flex-col gap-1 max-h-32 overflow-y-auto pr-0.5">
                  {[...hiveHealth.logs].reverse().map((log, i) => {
                    // 로그 내용에 따라 색상 결정 (치유=녹색, 경고=노랑, 오류=빨강, 기타=회색)
                    const isHeal = log.includes('✅') || log.includes('자기치유') || log.includes('완료');
                    const isWarn = log.includes('⚠️') || log.includes('장시간');
                    const isErr  = log.includes('❌') || log.includes('실패');
                    const color  =
                      isErr  ? 'text-red-400' :
                      isWarn ? 'text-yellow-400' :
                      isHeal ? 'text-green-400' :
                               'text-[#777]';
                    return (
                      <div key={i} className={`text-[10px] font-mono leading-snug ${color}`}>
                        {log}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 복구/치유 액션 결과 메시지 표시 */}
        {spMsg && <div className="text-xs text-green-400 font-mono truncate">{spMsg}</div>}

        {/* 복구 버튼 영역 */}
        <div className="flex gap-2">
          {/* 스킬 복구: 누락된 하이브 지침/스킬을 현재 프로젝트에 자동 설치 */}
          <button
            onClick={() => {
              if (confirm(`현재 프로젝트(${currentPath})에 누락된 하이브 지침과 스킬을 자동 복구하시겠습니까?`)) {
                fetch(`${API_BASE}/api/install-skills?path=${encodeURIComponent(currentPath)}`)
                  .then(res => res.json())
                  .then(data => { setSpMsg(data.message); fetchHiveHealth(); });
              }
            }}
            className="flex-1 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary text-xs font-bold rounded border border-primary/20 transition-all flex items-center justify-center gap-1.5"
          >
            <Zap className="w-3 h-3" /> 스킬 복구
          </button>
          {/* 자가 치유: 하이브 엔진 정밀 점검 및 복구 실행 */}
          <button
            onClick={() => {
              fetch(`${API_BASE}/api/hive/health/repair`)
                .then(res => res.json())
                .then(() => { setSpMsg('하이브 엔진 정밀 진단 및 자가 치유 완료'); fetchHiveHealth(); });
            }}
            className="px-3 py-1.5 bg-green-500/10 hover:bg-green-500/20 text-green-400 text-xs font-bold rounded border border-green-500/20 transition-all flex items-center justify-center gap-1.5"
            title="하이브 엔진 정밀 점검"
          >
            <Cpu className="w-3 h-3" /> 자가 치유
          </button>
        </div>
      </div>
    </div>
  );
}
