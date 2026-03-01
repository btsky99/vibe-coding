/**
 * FILE: HivePanel.tsx
 * DESCRIPTION: 하이브 진단 패널 — 에이전트 상태 모니터링 + 시스템 헬스 체크 + 자가 치유 UI.
 *              App.tsx에서 분리된 독립 컴포넌트로, 오케스트레이터 상태와 하이브 헬스를
 *              자체 폴링하여 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 */

import { useState, useEffect } from 'react';
import { Bot, AlertTriangle, CircleDot, Cpu, RotateCw, CheckCircle2, Zap } from 'lucide-react';
import { HiveHealth, OrchestratorStatus } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정 (App.tsx와 동일한 패턴)
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

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

  // ── 오케스트레이터 상태 폴링 (3초 간격) ──────────────────────────────────
  useEffect(() => {
    const fetchOrch = () => {
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then((data: OrchestratorStatus) => setOrchStatus(data))
        .catch(() => {});
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
      .catch(() => {});
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
      .catch(() => {});
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
            <div className="p-2 rounded border border-red-500/40 bg-red-500/5">
              <div className="flex items-center gap-1.5 mb-1 text-[10px] font-bold text-red-400">
                <AlertTriangle className="w-3.5 h-3.5" /> 경고 ({orchStatus.warnings.length})
              </div>
              {orchStatus.warnings.map((w, i) => (
                <div key={i} className="text-[9px] text-red-300 pl-3 py-0.5">⚠ {w}</div>
              ))}
            </div>
          )}

          {/* 에이전트 상태 카드 */}
          <div className="p-2 rounded border border-white/10">
            <div className="text-[9px] font-bold text-[#969696] mb-1.5 flex items-center gap-1">
              <Bot className="w-3 h-3" /> 에이전트 상태
            </div>
            {Object.entries(orchStatus.agent_status ?? {}).map(([agent, st]) => {
              // 에이전트 활성 상태별 색상 (active=녹색, idle=노랑, unknown=회색)
              const dotColor =
                st.state === 'active' ? 'text-green-400' :
                st.state === 'idle'   ? 'text-yellow-400' :
                                        'text-[#858585]';
              // 상태 레이블 — 유휴 시 경과 분수 함께 표시
              const stateLabel =
                st.state === 'active' ? '활성' :
                st.state === 'idle'   ? `유휴 ${st.idle_sec ? Math.floor(st.idle_sec / 60) + '분' : ''}` :
                                        '미확인';
              // 이 에이전트의 태스크 분배 현황 (없으면 0으로 처리)
              const taskDist = orchStatus.task_distribution?.[agent] ?? { pending: 0, in_progress: 0, done: 0 };
              // 이 에이전트가 실제로 사용 중인 터미널 슬롯 번호 목록 (PTY 기반 실시간)
              const activeSlots = Object.entries(orchStatus.terminal_agents ?? {})
                .filter(([, a]) => a === agent)
                .map(([slot]) => `T${slot}`);
              return (
                <div key={agent} className="flex items-center gap-2 py-1 border-b border-white/5 last:border-0">
                  <CircleDot className={`w-3 h-3 shrink-0 ${dotColor}`} />
                  <span className={`font-mono font-bold text-[10px] w-12 shrink-0 ${agent === 'claude' ? 'text-green-400' : 'text-blue-400'}`}>
                    {agent}
                  </span>
                  <span className={`text-[9px] ${dotColor}`}>{stateLabel}</span>
                  {/* 실제 실행 중인 터미널 슬롯 번호 배지 */}
                  {activeSlots.length > 0 && (
                    <span className="text-[8px] font-mono text-primary/70 bg-primary/10 px-1 rounded">
                      {activeSlots.join(' ')}
                    </span>
                  )}
                  {/* 태스크 분배 현황 (대기/진행/완료) */}
                  <div className="ml-auto flex gap-1.5 text-[8px] font-mono">
                    <span className="text-[#858585]">P:{taskDist.pending}</span>
                    <span className="text-primary">W:{taskDist.in_progress}</span>
                    <span className="text-green-400">D:{taskDist.done}</span>
                  </div>
                </div>
              );
            })}

            {/* 터미널 슬롯 전체 현황 (T1~T8 그리드 시각화) */}
            <div className="mt-2 pt-2 border-t border-white/5">
              <div className="text-[8px] text-[#555] mb-1">터미널 슬롯 현황</div>
              <div className="grid grid-cols-8 gap-0.5">
                {Array.from({ length: 8 }, (_, i) => {
                  const slot = String(i + 1);
                  const a = (orchStatus.terminal_agents ?? {})[slot] || '';
                  // 에이전트별 색상 (claude=녹색, gemini=파랑, 기타=노랑, 비어있음=흰색)
                  const color =
                    a === 'claude' ? 'bg-green-500/60' :
                    a === 'gemini' ? 'bg-blue-500/60' :
                    a              ? 'bg-yellow-500/60' :
                                     'bg-white/10';
                  // 에이전트별 단축 레이블 (C/G/첫글자/슬롯번호)
                  const label =
                    a === 'claude' ? 'C' :
                    a === 'gemini' ? 'G' :
                    a              ? a[0].toUpperCase() :
                                     '';
                  return (
                    <div
                      key={slot}
                      title={a ? `T${slot}: ${a}` : `T${slot}: 비어있음`}
                      className={`h-4 rounded text-[7px] font-bold flex items-center justify-center ${color} text-white/80`}
                    >
                      {label || slot}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* 태스크 분배 전체 요약 — all 키가 있을 때만 표시 */}
          {orchStatus.task_distribution?.all && (
            <div className="p-2 rounded border border-white/10">
              <div className="text-[9px] font-bold text-[#969696] mb-1">미할당 태스크 (all)</div>
              <div className="flex gap-3 text-[9px] font-mono">
                <span className="text-[#858585]">대기: {orchStatus.task_distribution.all.pending}</span>
                <span className="text-primary">진행: {orchStatus.task_distribution.all.in_progress}</span>
                <span className="text-green-400">완료: {orchStatus.task_distribution.all.done}</span>
              </div>
            </div>
          )}

          {/* 최근 액션은 AI 오케스트레이터 탭(OrchestratorPanel)에서 확인 */}
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
                    ['Master',     hiveHealth.skills?.master],
                    ['Brainstorm', hiveHealth.skills?.brainstorm],
                    ['Memory',     hiveHealth.skills?.memory_script],
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
