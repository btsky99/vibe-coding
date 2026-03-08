/**
 * ------------------------------------------------------------------------
 * 📄 파일명: AgentPanel.tsx
 * 📝 설명: 자율 에이전트 통합 컨트롤 패널.
 *          (구) AgentPanel + MissionControlPanel + AutonomousPopup 를 하나로 통합.
 *          - 지시 입력 → Claude Code / Gemini CLI 자동 선택 실행
 *          - 탭 전환: 터미널 출력 | 사고 흐름(Thought Stream) | 실행 히스토리
 *          하나의 SSE 스트림을 공유하여 모든 뷰를 동시 업데이트합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-08 Claude: [UI] 각 TerminalCard가 개별 파이프라인 표시하도록 개선
 *   - TerminalState에 pipeline_stage 필드 추가 (서버 값 직접 사용)
 *   - TerminalCard: 서버 pipeline_stage 우선, last_line detectStage fallback
 *   - 하단 통합 WorkflowPipeline 제거 — 카드별 독립 표시로 전환 (T1~T8 동시 추적)
 * - 2026-03-08 Claude: [UI] 상황판 배너에 "실행 중인 터미널" 목록 추가
 *   - 선택 대상(좌) + 현재 running 터미널 배지(우) 좌우 분리 레이아웃
 *   - running 터미널 없으면 "실행 중 없음" 텍스트 표시
 *   - running 배지는 animate-pulse로 시각적 강조 (3초 폴링 실시간 갱신)
 * - 2026-03-08 Claude: [UX] 터미널 카드 실행 상태 명시화 — 어느 터미널이 동작 중인지 한눈에 확인
 *   - 실행 중(running) 카드 상단에 좌→우 스캔 애니메이션 진행 바 추가 (노란색)
 *   - "LIVE" 배지: running 터미널 ID 옆에 pulse 애니메이션으로 표시
 *   - "실행 대상" 배지: selected 터미널 카드 내부에 primary 색상으로 표시
 *   - 상태/시간을 우측으로 이동, 헤더 레이아웃 정리
 * - 2026-03-06 Claude: [Phase6] 모델 라우팅 근거 뱃지 — TerminalCard 헤더에 routing_reason 표시
 *   - 실행 중(running) 상태에서 CLI 배지 옆에 자동 선택 근거 텍스트를 7px 회색으로 표시
 *   - 예: "claude | 코드 수정 감지 (수정)" 형태로 why 모델이 선택됐는지 즉시 확인 가능
 * - 2026-03-05 Claude: [리디자인] 상황판 탭 — TerminalSlot 상단 모니터링 기준 터미널별 패널
 *   - 2열 컴팩트 카드 그리드 → 1열 확장 모니터링 패널 목록으로 교체
 *   - 각 터미널 카드: 파이프라인(분석/수정/검증/완료) + 현재 작업 + 마지막 출력 표시
 *   - TerminalSlot 상단 모니터링 뷰와 동일한 시각 언어 사용 (터미널별 독립 상태)
 *   - 카드 클릭 → 해당 터미널 선택 (선택 터미널로 다음 실행 전송)
 * - 2026-03-05 Claude: [신규] 터미널별 상황판 — T1~T8 카드 그리드
 *   - 상황판 탭: 1개 파이프라인 → T1~T8 독립 카드 2×4 그리드로 전환
 *   - /api/agent/terminals 3초 폴링으로 터미널별 상태 실시간 갱신
 *   - 카드 클릭 → 해당 터미널 선택 → 다음 실행이 그 터미널 ID로 전송
 *   - 할때마다 탭 전환 없이 한 창에서만 보임 (기본 탭 = 상황판)
 * - 2026-03-04 Claude: 최초 구현 (AgentPanel 단독)
 * - 2026-03-04 Claude: [통합 리팩터] AgentPanel + MissionControlPanel + AutonomousPopup 통합
 *   - 세 패널 → 하나의 탭형 패널로 중복 제거
 *   - 터미널 탭: 터미널 스타일 raw 출력 (기존 AgentPanel)
 *   - 사고 흐름 탭: Thought Stream 뷰 (기존 MissionControlPanel)
 *   - 히스토리 탭: 실행 이력 (기존 AgentPanel 하단 아코디언 → 탭으로 승격)
 *   - SSE 연결 단일화: 두 뷰가 동일 EventSource 공유
 * - 2026-03-04 Claude: [버그수정] 30초 타임아웃 미클리어 → 에이전트 중간 강제 오류 전환 수정
 *   - SSE started 수신 시 runTimeoutRef 클리어 추가
 *   - intentionalClose 플래그 비동기 타이밍 오류 수정 (close 전 true → onerror 핸들러 내에서 false)
 * - 2026-03-04 Claude: [버그수정] 경과 시간 카운터 추가 (출력 없어도 UI가 살아있음 표시)
 *   - running 진입 시 1초 단위 카운터 시작, 상태 변경 시 리셋
 *   - 헤더 상태 배지에 MM:SS 형식 경과 시간 표시
 * - 2026-03-04 Claude: [버그수정] SSE 이벤트 유실 시 running 상태 고착 문제 수정
 *   - running 중 3초마다 서버 폴링하여 SSE 누락 이벤트 보완
 *   - runTimeoutRef 선언 위치를 connectSSE 앞으로 이동 (closure 순서 명확화)
 * - 2026-03-04 Claude: [버그수정] 30초 타임아웃 메시지 유실 버그 수정
 *   - 출력이 있을 때 타임아웃 메시지가 추가되지 않아 "중간에 멈춘 것처럼" 보이던 문제 수정
 *   - prev.length === 0 조건 제거 → 항상 타임아웃 이유 메시지를 터미널에 추가
 * - 2026-03-04 Claude: [버그수정] 중간에 멈추는 두 가지 버그 수정
 *   - maxRunTimeoutRef 추가: started 수신 후 5분 내 done 없으면 강제 오류 처리 (subprocess hang 방지)
 *   - outputLines 최대 500줄 제한: 무제한 누적 시 터미널 탭 렌더링 지연/프리즈 방지
 * - 2026-03-04 Claude: [버그수정] 폴링 케이스A2 추가 — 타임아웃 오발 후 완료 감지 누락 수정
 *   - 30초 타임아웃 → UI=error, 이후 에이전트 완료 → 서버 done 반환 시 UI 고착 버그
 *   - 폴링 조건: status==='running' 에서 status==='running' || status==='error' 로 확장
 *   - 단, 새로운 "[동기화] 오류 감지" 메시지는 status='running'일 때만 추가 (중복 방지)
 * - 2026-03-04 Claude: [버그수정] 3초 폴링 오류 상태 무한 메시지 버그 수정
 *   - status=error 시 3초마다 "[동기화] 오류 감지" 메시지 무한 추가 문제 수정
 *   - 동기화 메시지는 running→완료 전환 시에만 추가하도록 조건 강화
 *   - SSE 재연결 딜레이 5000ms→2000ms 단축 (출력 공백 구간 최소화)
 * - 2026-03-04 Claude: [버그수정] es.onopen → 재연결 직후 즉시 상태 동기화
 *   - SSE 재연결(2초) 후 done 이벤트가 유실된 경우 3초 폴 대기 없이 즉시 복구
 * - 2026-03-05 Claude: [신규] 상황판 탭 추가 — 워크플로우 상태 머신 시각화
 *   - 터미널 raw 출력 대신 분석→수정→검증→완료 단계를 시각적으로 표시
 *   - 출력 파싱으로 현재 단계 자동 감지 (키워드 기반)
 *   - 이슈 발생 시 루프 카운터 표시 (분석→수정→검증 재시작)
 * - 2026-03-05 Claude: [UI 한글화] 영어 텍스트 → 한글 전환
 *   - 'Autonomous Agent' → '자율 에이전트'
 *   - '최근 실행 이력' → '최근 실행 이력', 'AI 사고 흐름' → 'AI 사고 흐름'
 *   - 스킬 short 이름(debug/review/…) → 한글(디버그/코드리뷰/…)
 *   - TerminalCard: 이전 날짜 데이터에 날짜 표시 추가 (오늘 것만 HH:MM, 아니면 MM/DD)
 * - 2026-03-05 Claude: [신규] 분석/수정 파일 추적 — 상황판 탭에 표시
 *   - SSE 출력 파싱: '● Read(file)' → 분석 파일, '● Edit(file)' → 수정 파일 추적
 *   - 워크플로우 파이프라인 아래에 '분석한 파일 / 수정한 파일' 목록 표시
 * ------------------------------------------------------------------------
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Bot, Play, Square, RotateCw, ChevronDown, Clock,
  Brain, CheckCircle2, Circle, XCircle, Terminal, LayoutDashboard,
  Search, Pencil, ShieldCheck, RefreshCw, Network, Database,
} from 'lucide-react';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ─── 타입 정의 ──────────────────────────────────────────────────────────────

type AgentStatus   = 'idle' | 'running' | 'done' | 'error' | 'unavailable';
type CliChoice     = 'auto' | 'claude' | 'gemini' | 'codex';
type ActiveTab     = 'workflow' | 'terminal' | 'thoughts' | 'history' | 'orchestrator' | 'hive';

// 하이브 활동 이벤트 타입 — /api/hive/activity 응답 형식
interface HiveEvent {
  timestamp: string;
  agent: string;
  terminal_id?: string;   // 로그를 남긴 터미널 ID (T1~T8, T0=미설정)
  type: 'memory_read' | 'memory_write' | 'orchestrate' | 'message' | 'heal' | 'hive_ctx' | 'session';
  task: string;
}

// ─── 워크플로우 단계 타입 ─────────────────────────────────────────────────────
type WorkflowStage = 'idle' | 'analyzing' | 'modifying' | 'verifying' | 'done' | 'error';

/** 출력 텍스트 한 줄을 보고 워크플로우 단계를 추론합니다.
 *  키워드 기반 휴리스틱: Claude Code의 도구 호출 패턴을 우선 감지 */
function detectStage(line: string): WorkflowStage | null {
  const l = line.toLowerCase();

  // 수정 (Edit/Write/Create 도구 호출) — 분석보다 먼저 체크
  if (
    l.startsWith('● edit') || l.startsWith('● write') || l.startsWith('● create') ||
    l.includes('editfile') || l.includes('writefile') || l.includes('createfile') ||
    l.includes('notebookedit') ||
    l.includes(' edit ') || l.includes('수정 중') || l.includes('파일 수정') ||
    l.includes('코드 수정') || l.includes('변경 중')
  ) return 'modifying';

  // 검증 (Bash/Run/Test 도구 호출)
  if (
    l.startsWith('● bash') || l.startsWith('● run') ||
    l.includes('running test') || l.includes('npm test') || l.includes('pytest') ||
    l.includes('검증 중') || l.includes('테스트 중') || l.includes('빌드 중') ||
    l.includes('실행 중...') || (l.includes('bash') && l.includes('tool'))
  ) return 'verifying';

  // 분석 (Read/Glob/Grep/Search 도구 호출)
  if (
    l.startsWith('● read') || l.startsWith('● glob') || l.startsWith('● grep') ||
    l.startsWith('● search') || l.startsWith('● agent') ||
    l.includes('readfile') || l.includes('분석 중') || l.includes('파악 중') ||
    l.includes('코드 분석') || l.includes('let me read') || l.includes('looking at') ||
    l.includes('확인 중') || l.includes('조사 중')
  ) return 'analyzing';

  // 완료
  if (
    l.includes('완료') || l.includes('✓') || l.includes('모든 작업') ||
    l.includes('성공적') || (l.includes('done') && l.length < 30)
  ) return 'done';

  // 오류/이슈
  if (
    l.startsWith('[오류]') || l.startsWith('error:') || l.includes('✗') ||
    l.includes('실패') || l.includes('오류 발생')
  ) return 'error';

  return null;
}


// ─── 터미널별 상태 타입 ──────────────────────────────────────────────────────
interface TerminalState {
  status: 'idle' | 'running' | 'done' | 'error';
  task: string;           // 마지막/현재 실행 지시
  cli: string;            // claude | gemini | ''
  run_id: string;
  ts: string;             // ISO 타임스탬프
  last_line: string;      // 마지막 출력 줄
  pipeline_stage?: string; // 서버에서 직접 받는 파이프라인 단계 (idle|analyzing|modifying|verifying|done|error)
  external?: boolean;     // true = 외부 Gemini 세션 (다른 프로젝트) — UI에서 숨김
  routing_reason?: string; // 모델 자동 선택 근거 (예: "코드 작업 감지 (수정)")
}

interface AgentRun {
  id: string;
  task: string;
  cli: string;
  status: 'done' | 'error' | 'stopped';
  ts: string;
  output_preview?: string[];
}

interface OutputLine {
  text: string;
  ts: string;
  type: 'output' | 'started' | 'done' | 'error' | 'stopped';
}

interface ThoughtEntry {
  id: number;
  time: string;
  agent: string;
  text: string;
}

// ─── 상수 ───────────────────────────────────────────────────────────────────

const CLI_LABELS: Record<CliChoice, string> = {
  auto:   '🤖 Auto (자동 선택)',
  claude: '⚡ Claude Code',
  gemini: '✨ Gemini CLI',
  codex:  '🟠 Codex CLI',
};

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle:        'text-white/40',
  running:     'text-yellow-400',
  done:        'text-green-400',
  error:       'text-red-400',
  unavailable: 'text-white/20',
};

const STATUS_LABELS: Record<AgentStatus, string> = {
  idle:        '대기 중',
  running:     '실행 중',
  done:        '완료',
  error:       '오류',
  unavailable: 'CLI 미설치',
};

// ─── Props ──────────────────────────────────────────────────────────────────

interface AgentPanelProps {
  /** App.tsx에 에이전트 실행 상태를 알리는 콜백 (ActivityBar 배지 표시용) */
  onStatusChange?: (running: boolean) => void;
}

// ─── 상태 아이콘 (히스토리 / 사고 흐름 공용) ───────────────────────────────
function StatusIcon({ status }: { status: string }) {
  if (status === 'done')
    return <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />;
  if (status === 'error')
    return <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />;
  if (status === 'running')
    return (
      <div className="w-3.5 h-3.5 rounded-full border-2 border-primary border-t-transparent animate-spin shrink-0" />
    );
  return <Circle className="w-3.5 h-3.5 text-white/20 shrink-0" />;
}

// ─── 단계 스타일 상수 ────────────────────────────────────────────────────────


// ─── 워크플로우 파이프라인 컴포넌트 ─────────────────────────────────────────
/** 분석 → 수정 → 검증 → 완료 단계를 가로 스텝 형태로 시각화.
 *  현재 단계를 강조하고, 이슈 발생 시 루프 카운터를 표시합니다. */
export function _WorkflowPipeline({
  stage, loopCount, agentStatus,
}: {
  stage: WorkflowStage;
  loopCount: number;
  agentStatus: AgentStatus;
}) {
  // 파이프라인 고정 단계 (idle/error는 별도 처리)
  const steps: { id: WorkflowStage; label: string; icon: React.ReactNode }[] = [
    { id: 'analyzing', label: '분석',  icon: <Search       className="w-4 h-4" /> },
    { id: 'modifying', label: '수정',  icon: <Pencil       className="w-4 h-4" /> },
    { id: 'verifying', label: '검증',  icon: <ShieldCheck  className="w-4 h-4" /> },
    { id: 'done',      label: '완료',  icon: <CheckCircle2 className="w-4 h-4" /> },
  ];

  // 단계 순서 인덱스 (done=-1이면 완료)
  const ORDER: Record<string, number> = {
    analyzing: 0, modifying: 1, verifying: 2, done: 3,
  };
  const currentIdx = ORDER[stage] ?? -1;

  return (
    <div className="bg-black/20 rounded border border-white/5 p-3">
      {/* 루프 배지 */}
      {loopCount > 0 && (
        <div className="flex items-center gap-1 mb-2 text-[9px] text-orange-400/80">
          <RefreshCw className="w-3 h-3" />
          <span>재시도 {loopCount}회 — 이슈 발견 후 재분석 중</span>
        </div>
      )}

      {/* 스텝 체인 */}
      <div className="flex items-center gap-0">
        {steps.map((step, i) => {
          const isActive   = step.id === stage && agentStatus === 'running';
          const isDone     = currentIdx > i || (stage === 'done');
          const isError    = stage === 'error' && currentIdx === i;
          const isIdle     = agentStatus === 'idle' || stage === 'idle';

          return (
            <React.Fragment key={step.id}>
              {/* 연결선 (첫 번째 스텝 앞에는 없음) */}
              {i > 0 && (
                <div className={`flex-1 h-px mx-1 transition-all duration-500 ${
                  isDone ? 'bg-green-500/60' : 'bg-white/10'
                }`} />
              )}

              {/* 스텝 원 */}
              <div className={`flex flex-col items-center gap-1 transition-all duration-300`}>
                <div className={`
                  w-9 h-9 rounded-full flex items-center justify-center
                  border-2 transition-all duration-300
                  ${isActive  ? 'border-yellow-400 text-yellow-400 bg-yellow-400/10 shadow-[0_0_8px_rgba(250,204,21,0.4)] animate-pulse' :
                    isError   ? 'border-red-400    text-red-400    bg-red-400/10' :
                    isDone    ? 'border-green-500  text-green-400  bg-green-500/10' :
                    isIdle    ? 'border-white/10   text-white/15' :
                                'border-white/20   text-white/25'}
                `}>
                  {isActive
                    ? <div className="w-3 h-3 rounded-full border-2 border-yellow-400 border-t-transparent animate-spin" />
                    : isDone
                      ? <CheckCircle2 className="w-4 h-4" />
                      : step.icon
                  }
                </div>
                <span className={`text-[9px] font-bold uppercase tracking-tight ${
                  isActive ? 'text-yellow-400' :
                  isDone   ? 'text-green-400/70' :
                  isError  ? 'text-red-400' :
                             'text-white/25'
                }`}>
                  {step.label}
                </span>
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {/* 오류/완료 상태 메시지 */}
      {stage === 'error' && agentStatus !== 'running' && (
        <div className="mt-2 text-[9px] text-red-400/80 flex items-center gap-1">
          <XCircle className="w-3 h-3" /> 오류 발생 — 다시 실행하여 재시도
        </div>
      )}
      {stage === 'done' && (
        <div className="mt-2 text-[9px] text-green-400/80 flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3" /> 모든 단계 완료
        </div>
      )}
      {(stage === 'idle' || agentStatus === 'idle') && (
        <div className="mt-2 text-[9px] text-white/20 text-center">
          실행 전 — 지시를 입력하고 실행하세요
        </div>
      )}
    </div>
  );
}

// ─── 단일 터미널 모니터링 패널 (상황판 목록용) ───────────────────────────────
/** T1~T8 각각의 상태를 TerminalSlot 상단 모니터링 뷰와 동일한 형식으로 표시.
 *  파이프라인 단계 + 현재 작업 + 마지막 출력을 터미널별로 독립 표시합니다.
 *  클릭 시 해당 터미널을 '선택 상태'로 강조합니다. */
function TerminalCard({
  id, state, selected, onClick,
}: {
  id: string;
  state: TerminalState;
  selected: boolean;
  onClick: () => void;
}) {
  const { status, task, cli, ts, last_line, pipeline_stage } = state;

  // 카드 테두리: 선택 > running > 기본
  const cardBorder = selected
    ? 'border-primary/60 bg-primary/5'
    : status === 'running'
      ? 'border-yellow-400/30 bg-yellow-400/5'
      : status === 'done'
        ? 'border-green-600/20 bg-green-900/5'
        : status === 'error'
          ? 'border-red-500/20 bg-red-900/5'
          : 'border-white/8 bg-black/20 hover:border-white/15';

  // 상태 도트 색상 + 애니메이션
  const dotColor =
    status === 'running' ? 'bg-yellow-400 animate-pulse' :
    status === 'done'    ? 'bg-green-500' :
    status === 'error'   ? 'bg-red-500' :
                           'bg-white/15';

  // CLI 배지 색상
  const cliBadge =
    cli === 'claude' ? 'bg-orange-500/20 text-orange-300 border-orange-500/20' :
    cli === 'gemini' ? 'bg-blue-500/20 text-blue-300 border-blue-500/20' :
    cli === 'codex'  ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/20' :
                       'bg-white/5 text-white/20 border-white/5';

  // 시간 포맷: 오늘 → HH:MM, 이전 날짜 → MM/DD
  const timeStr = (() => {
    if (!ts) return '';
    const today = new Date().toISOString().slice(0, 10);
    const itemDate = ts.slice(0, 10);
    if (itemDate === today) return ts.slice(11, 16);
    return `${ts.slice(5, 7)}/${ts.slice(8, 10)}`;
  })();

  // 파이프라인 단계: 서버 pipeline_stage 우선, 없으면 last_line 키워드 fallback
  // Why: 서버(cli_agent.py)가 출력 파싱으로 이미 정확한 stage를 계산해 전달하므로
  //      클라이언트에서 last_line을 재파싱할 필요 없음. 단, SSE로만 실행한 경우
  //      서버 stage가 없을 수 있어 fallback을 유지함.
  const serverStage = pipeline_stage && pipeline_stage !== 'idle' ? pipeline_stage : null;
  const detectedStage = serverStage ?? (last_line ? detectStage(last_line) : null);

  // 파이프라인 단계 목록 — 각 단계별 고유 아이콘/색상으로 한눈에 구분
  const PIPELINE = [
    {
      id: 'analyzing', label: '분석',
      icon: <Search className="w-3 h-3" />,
      activeBorder: 'border-cyan-400 bg-cyan-400/20 shadow-[0_0_6px_rgba(34,211,238,0.4)] animate-pulse',
      activeText: 'text-cyan-400', activeIcon: 'text-cyan-400',
      idleIcon: 'text-cyan-400/25', idleBorder: 'border-cyan-400/20 bg-cyan-400/5',
    },
    {
      id: 'modifying', label: '수정',
      icon: <Pencil className="w-3 h-3" />,
      activeBorder: 'border-yellow-400 bg-yellow-400/20 shadow-[0_0_6px_rgba(250,204,21,0.4)] animate-pulse',
      activeText: 'text-yellow-400', activeIcon: 'text-yellow-400',
      idleIcon: 'text-yellow-400/25', idleBorder: 'border-yellow-400/20 bg-yellow-400/5',
    },
    {
      id: 'verifying', label: '검증',
      icon: <ShieldCheck className="w-3 h-3" />,
      activeBorder: 'border-purple-400 bg-purple-400/20 shadow-[0_0_6px_rgba(168,85,247,0.4)] animate-pulse',
      activeText: 'text-purple-400', activeIcon: 'text-purple-400',
      idleIcon: 'text-purple-400/25', idleBorder: 'border-purple-400/20 bg-purple-400/5',
    },
    {
      id: 'done', label: '완료',
      icon: <CheckCircle2 className="w-3 h-3" />,
      activeBorder: 'border-green-400 bg-green-400/20 shadow-[0_0_6px_rgba(74,222,128,0.4)] animate-pulse',
      activeText: 'text-green-400', activeIcon: 'text-green-400',
      idleIcon: 'text-green-400/25', idleBorder: 'border-green-400/20 bg-green-400/5',
    },
  ] as const;
  const stageOrder: Record<string, number> = { analyzing: 0, modifying: 1, verifying: 2, done: 3 };
  // running 중 단계 미감지 시 → 분析(0)을 디폴트 활성으로 표시 (시작 단계임을 명시)
  const currentIdx = detectedStage
    ? (stageOrder[detectedStage] ?? -1)
    : status === 'done' ? 3
    : status === 'running' ? 0   // 감지 전이면 분析 단계 활성
    : -1;

  // idle 터미널은 최소 높이 유지 (헤더+상태만 표시)
  const isActive = status !== 'idle';

  return (
    <button
      onClick={onClick}
      className={`flex flex-col gap-0 rounded border transition-all duration-200 text-left w-full overflow-hidden ${cardBorder}`}
    >
      {/* ── 실행 중 상태: 상단 애니메이션 진행 바 ────────────────────────────── */}
      {status === 'running' && (
        <div className="h-0.5 w-full overflow-hidden shrink-0 bg-yellow-400/15">
          <div style={{
            height: '100%',
            background: 'rgba(250,204,21,0.7)',
            animation: 'termCardLive 1.6s ease-in-out infinite',
          }} />
          <style>{`
            @keyframes termCardLive {
              0%   { width:0%;  margin-left:0%; }
              50%  { width:55%; margin-left:22%; }
              100% { width:0%;  margin-left:100%; }
            }
          `}</style>
        </div>
      )}

      {/* ── 모니터링 헤더: ID + 배지 + 상태 + 시간 ─────────────────────────── */}
      <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-white/5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* 터미널 ID — 실행 중이면 노란색 강조 */}
          <span className={`font-bold text-[11px] font-mono tracking-wider ${
            status === 'running' ? 'text-yellow-300' : 'text-white/80'
          }`}>{id}</span>

          {/* 실행 중 LIVE 배지 */}
          {status === 'running' && (
            <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-yellow-400/15 border border-yellow-400/35 text-yellow-400 text-[8px] font-bold animate-pulse">
              <span className="w-1 h-1 rounded-full bg-yellow-400 inline-block" />
              LIVE
            </span>
          )}

          {/* 실행 대상(선택됨) 배지 */}
          {selected && (
            <span className="px-1.5 py-0.5 rounded bg-primary/20 border border-primary/40 text-primary text-[8px] font-bold">
              실행 대상
            </span>
          )}

          {/* CLI 배지 */}
          {cli && (
            <span className={`text-[8px] px-1.5 py-0.5 rounded border font-bold ${cliBadge}`}>
              {cli === 'claude' ? '⚡' : '✨'} {cli}
            </span>
          )}
          {/* 모델 자동 선택 근거 뱃지 — 실행 중일 때만 표시 */}
          {state.routing_reason && status === 'running' && (
            <span className="text-[7px] text-white/30 font-mono truncate max-w-[80px]" title={state.routing_reason}>
              {state.routing_reason}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {/* 상태 도트 + 텍스트 */}
          <div className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
            <span className={`text-[9px] font-semibold ${
              status === 'running' ? 'text-yellow-400' :
              status === 'done'    ? 'text-green-400' :
              status === 'error'   ? 'text-red-400' :
                                     'text-white/20'
            }`}>
              {status === 'idle' ? '대기' : status === 'running' ? '실행 중' : status === 'done' ? '완료' : '오류'}
            </span>
          </div>
          <span className="text-[8px] text-white/20 font-mono">{timeStr}</span>
        </div>
      </div>

      {/* ── 파이프라인 단계 (실행 이력이 있는 터미널만 표시) ────────────────── */}
      {isActive && (
        <div className="flex items-center justify-center gap-0 px-3 py-2 border-b border-white/5">
          {PIPELINE.map((step, idx) => {
            const isStepActive = step.id === detectedStage && status === 'running';
            const isPast       = currentIdx > idx;
            return (
              <React.Fragment key={step.id}>
                {/* 단계 간 연결선 */}
                {idx > 0 && (
                  <div className={`flex-1 h-px mx-0.5 transition-all ${
                    isPast || isStepActive ? 'bg-green-600/40' : 'bg-white/8'
                  }`} />
                )}
                {/* 단계 원형 + 레이블 — 단계별 고유 색상으로 현재 위치 즉시 파악 */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center border transition-all duration-300 ${
                    isStepActive ? step.activeBorder :
                    isPast       ? 'border-green-600/50 bg-green-900/20' :
                                   step.idleBorder
                  }`}>
                    <span className={`transition-all ${
                      isStepActive ? step.activeIcon :
                      isPast       ? 'text-green-500/70' :
                                     step.idleIcon
                    }`}>{step.icon}</span>
                  </div>
                  <span className={`text-[8px] font-bold transition-all ${
                    isStepActive ? step.activeText :
                    isPast       ? 'text-green-600/50' :
                                   'text-white/20'
                  }`}>
                    {step.label}
                  </span>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      )}

      {/* ── 현재 작업 텍스트 ────────────────────────────────────────────────── */}
      <div className="flex items-start gap-1.5 px-2.5 py-1.5">
        <Clock className={`w-3 h-3 shrink-0 mt-0.5 ${
          status === 'running' ? 'text-yellow-400/60' : 'text-white/15'
        }`} />
        <span className={`text-[9px] truncate leading-tight ${
          status === 'running' ? 'text-yellow-200/70' :
          status === 'done'    ? 'text-green-200/40 line-through' :
                                 'text-white/25'
        }`}>
          {task || '—'}
        </span>
      </div>

      {/* ── 마지막 출력 줄 (running 중에만 표시) ────────────────────────────── */}
      {last_line && status === 'running' && (
        <div className="px-2.5 pb-1.5">
          <div className="text-[8px] text-white/25 font-mono truncate bg-black/30 rounded px-1.5 py-0.5 border border-white/5">
            {last_line}
          </div>
        </div>
      )}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────────────

export default function AgentPanel({ onStatusChange }: AgentPanelProps) {
  // ─── 상태 ───────────────────────────────────────────────────────────────
  const [taskInput, setTaskInput]     = useState('');
  const [selectedCli, setSelectedCli] = useState<CliChoice>('auto');
  const [status, setStatus]           = useState<AgentStatus>('idle');
  const [activeCli, setActiveCli]     = useState<string>('');
  const [showCliMenu, setShowCliMenu] = useState(false);
  const [activeTab, setActiveTab]     = useState<ActiveTab>('workflow');

  // 터미널 탭 데이터
  const [outputLines, setOutputLines] = useState<OutputLine[]>([]);

  // 사고 흐름 탭 데이터
  const [thoughts, setThoughts]       = useState<ThoughtEntry[]>([]);
  const [activeSkill, setActiveSkill] = useState<string>('대기 중');
  const thoughtIdRef                  = useRef(0);

  // 히스토리 탭 데이터
  const [history, setHistory]         = useState<AgentRun[]>([]);

  // ── 분석/수정 파일 추적 (상황판 탭에서 표시) ──────────────────────────────
  // SSE 출력에서 '● Read(file)' → 분석, '● Edit(file)' → 수정 으로 파싱
  const [_analyzedFiles, setAnalyzedFiles] = useState<string[]>([]);
  const [_modifiedFiles, setModifiedFiles] = useState<string[]>([]);

  // ── 하이브 활동 탭 데이터 — /api/hive/activity 3초 폴링 ───────────────────
  // 하이브 메모리 읽기/쓰기, 오케스트레이션, 메시지 수신 이벤트를 시각화
  const [hiveEvents, setHiveEvents] = useState<HiveEvent[]>([]);

  // ── 오케스트레이터 탭 데이터 (구 OrchestratorPanel 통합) ──────────────────
  // 스킬 레지스트리: 기본 7개 고정, API 데이터 우선
  const DEFAULT_ORCH_SKILLS = [
    { num: 1, name: 'vibe-debug',        short: '디버그' },
    { num: 2, name: 'vibe-tdd',          short: 'TDD' },
    { num: 3, name: 'vibe-brainstorm',   short: '아이디어' },
    { num: 4, name: 'vibe-write-plan',   short: '계획작성' },
    { num: 5, name: 'vibe-execute-plan', short: '계획실행' },
    { num: 6, name: 'vibe-code-review',  short: '코드리뷰' },
    { num: 7, name: 'vibe-release',      short: '릴리스' },
  ];
  const CIRCLE_NUMS = ['', '①', '②', '③', '④', '⑤', '⑥', '⑦'];
  const [orchChainData, setOrchChainData] = useState<{
    skill_registry: { num: number; name: string; short: string }[];
    terminals: Record<string, {
      session_id: string; request: string; status: string;
      updated_at: string; agent?: string;
      steps: { label: string; skill_num: number; skill_name: string;
               step_order: number; status: string; summary: string }[];
    }>;
  }>({ skill_registry: [], terminals: {} });
  const [orchRunning, setOrchRunning]     = useState(false);
  const [orchLastRun, setOrchLastRun]     = useState<string | null>(null);
  const [orchTerminalAgents, setOrchTerminalAgents] = useState<Record<string, string>>({});

  // ── 터미널별 상태 카드 (T1~T8) — /api/agent/terminals 폴링 ─────────────────
  const [terminals, setTerminals] = useState<Record<string, TerminalState>>(() => {
    const init: Record<string, TerminalState> = {};
    for (let i = 1; i <= 8; i++) {
      init[`T${i}`] = { status: 'idle', task: '', cli: '', run_id: '', ts: '', last_line: '' };
    }
    return init;
  });
  // 실행할 터미널 선택 (카드 클릭으로 변경, 기본: T1)
  const [selectedTerminalId, setSelectedTerminalId] = useState<string>('T1');

  // ── 상황판 탭: 워크플로우 상태 머신 ────────────────────────────────────────
  // wfStage/wfLoop: WorkflowPipeline 렌더링에 사용
  // wfAction/wfLog: 선택 터미널 실행 중일 때만 파이프라인 표시 (상황판 탭 내)
  const [_wfStage, setWfStage]        = useState<WorkflowStage>('idle');
  const [_wfLoop, setWfLoop]          = useState(0);
  const wfCurrentStageRef             = useRef<WorkflowStage>('idle');

  const outputEndRef      = useRef<HTMLDivElement>(null);
  const thoughtEndRef     = useRef<HTMLDivElement>(null);
  const sseRef            = useRef<EventSource | null>(null);
  const textareaRef       = useRef<HTMLTextAreaElement>(null);
  // 재연결 타이머 ref — 언마운트/신규 연결 시 취소하여 stale 재연결 완전 차단
  const reconnectTimer    = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 실행 응답 대기 타임아웃 ref — connectSSE 클로저에서 참조하므로 먼저 선언
  const runTimeoutRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 전체 실행 최대 시간 타임아웃 ref — started 이후에도 5분 이상 실행 시 강제 오류 처리
  const maxRunTimeoutRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 실행 중 경과 시간 카운터 — 출력이 없어도 UI가 살아있음을 사용자에게 알림
  const [elapsedSec, setElapsedSec]   = useState(0);
  const elapsedTimerRef               = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 자동 스크롤 ────────────────────────────────────────────────────────
  useEffect(() => {
    if (activeTab === 'terminal')
      outputEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [outputLines, activeTab]);

  useEffect(() => {
    if (activeTab === 'thoughts')
      thoughtEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thoughts, activeTab]);

  // ─── 오케스트레이터 스킬 체인 폴링 (3초) — 오케스트레이터 탭 데이터 갱신 ──
  useEffect(() => {
    const fetchOrch = () => {
      // 스킬 체인 데이터 (스킬 목록 + 터미널별 단계)
      fetch(`${API_BASE}/api/orchestrator/skill-chain`)
        .then(res => res.json())
        .then(data => { if (data.skill_registry !== undefined) setOrchChainData(data); })
        .catch(() => {});
      // 터미널 에이전트 매핑 (orchTerminalAgents)
      fetch(`${API_BASE}/api/orchestrator/status`)
        .then(res => res.json())
        .then(data => { if (data.terminal_agents) setOrchTerminalAgents(data.terminal_agents); })
        .catch(() => {});
    };
    fetchOrch();
    const iv = setInterval(fetchOrch, 3000);
    return () => clearInterval(iv);
  }, []);

  // ─── 하이브 활동 폴링 (5초) — 하이브 탭 데이터 갱신 ─────────────────────
  // task_logs에서 하이브 시스템 관련 이벤트만 필터링하여 표시
  // → 사용자가 Claude/Gemini가 실제로 하이브를 사용하는지 눈으로 확인 가능
  useEffect(() => {
    const fetchHive = () => {
      fetch(`${API_BASE}/api/hive/activity`)
        .then(res => res.json())
        .then((data: HiveEvent[]) => { if (Array.isArray(data)) setHiveEvents(data); })
        .catch(() => {});
    };
    fetchHive();
    const iv = setInterval(fetchHive, 5000);
    return () => clearInterval(iv);
  }, []);

  // ─── 오케스트레이터 수동 실행 핸들러 ───────────────────────────────────
  const runOrchestrator = () => {
    setOrchRunning(true);
    fetch(`${API_BASE}/api/orchestrator/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then(res => res.json())
      .then(() => setOrchLastRun(new Date().toLocaleTimeString()))
      .catch(() => {})
      .finally(() => setOrchRunning(false));
  };

  // ─── 터미널별 상태 폴링 (T1~T8 상황판 카드 갱신) ────────────────────────
  const loadTerminals = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/terminals`);
      if (!res.ok) return;
      const data: Record<string, TerminalState> = await res.json();
      // 선택된 터미널이 외부에서 새로 running 진입 시 워크플로우 파이프라인 초기화
      // (대시보드가 아닌 T1.bat 등 외부 실행으로 감지된 경우)
      setTerminals(prev => {
        const prevStatus  = prev[selectedTerminalId]?.status;
        const newStatus   = data[selectedTerminalId]?.status;
        // 외부 실행으로 running 진입 → 파이프라인 초기화
        if (newStatus === 'running' && prevStatus !== 'running' && status !== 'running') {
          setWfStage('analyzing');
          wfCurrentStageRef.current = 'analyzing';
          setWfLoop(0);
        }
        // 서버에 저장된 pipeline_stage로 wfStage 복원
        // — 대시보드를 새로 열었을 때 이전 실행의 파이프라인 단계를 복구합니다.
        const serverStage = (data[selectedTerminalId] as any)?.pipeline_stage as WorkflowStage | undefined;
        if (serverStage && serverStage !== 'idle' && wfCurrentStageRef.current === 'idle') {
          wfCurrentStageRef.current = serverStage;
          setWfStage(serverStage);
        }
        return data;
      });
    } catch {
      // 서버 미실행 시 무시 (초기 idle 상태 유지)
    }
  }, [selectedTerminalId, status]);

  // ─── 히스토리 로드 ──────────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/runs`);
      if (!res.ok) return;
      const data: AgentRun[] = await res.json();
      setHistory(data);
    } catch {
      // 서버 미실행 시 무시
    }
  }, []);

  // ─── 현재 실행 상태 로드 ────────────────────────────────────────────────
  // setStatus만 하면 onStatusChange가 호출되지 않아 ActivityBar 배지가 고착되므로
  // running → 완료 전환 시 onStatusChange?.(false)도 함께 호출해야 함
  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/status`);
      const data = await res.json();
      const srvStatus = data.status as AgentStatus;
      setStatus(prev => {
        // running → 비running 전환 시 ActivityBar 배지 해제
        if (prev === 'running' && srvStatus !== 'running') {
          onStatusChange?.(false);
        }
        return srvStatus;
      });
      if (data.current?.cli) setActiveCli(data.current.cli);
    } catch {
      // 무시
    }
  }, []);

  // ─── SSE 연결: 단일 스트림이 터미널 + 사고 흐름 동시 업데이트 ────────────
  const connectSSE = useCallback(() => {
    // 기존 연결 닫기. onerror는 sseRef.current !== es 체크로 stale 재연결 방지
    sseRef.current?.close();

    const es = new EventSource(`${API_BASE}/api/events/agent`);
    sseRef.current = es;

    // SSE 연결 성공 직후 서버 상태 즉시 동기화
    // — onerror → 2초 대기 → 재연결 사이에 done 이벤트가 유실됐을 때 즉시 복구
    es.onopen = () => { loadStatus(); };

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const type = data.type as OutputLine['type'];
        const ts   = data.ts || new Date().toISOString();
        const time = ts.slice(11, 19);

        if (type === 'started') {
          // ── 실행 시작 — 초기 응답 타임아웃 해제 + 최대 실행 타임아웃(5분) 시작 ─
          if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }
          // 5분(300초) 내 done 이벤트 없으면 강제 오류 처리 (subprocess hang 방지)
          if (maxRunTimeoutRef.current) clearTimeout(maxRunTimeoutRef.current);
          maxRunTimeoutRef.current = setTimeout(() => {
            setStatus(prev => prev === 'running' ? 'error' : prev);
            setOutputLines(prev => [...prev, {
              text: '[오류] 최대 실행 시간(5분) 초과 — 에이전트가 응답하지 않습니다',
              ts: new Date().toISOString(), type: 'error',
            }]);
            setActiveSkill('오류');
            onStatusChange?.(false);
            maxRunTimeoutRef.current = null;
          }, 300_000);

          const cli = data.cli || 'auto';
          setStatus('running');
          onStatusChange?.(true);
          setActiveCli(cli);
          setActiveSkill(cli === 'claude' ? 'Claude Code' : cli === 'gemini' ? 'Gemini' : cli === 'codex' ? 'Codex' : 'Auto');

          // 상황판: 초기화
          setWfStage('analyzing');
          wfCurrentStageRef.current = 'analyzing';
          setWfLoop(0);
          setAnalyzedFiles([]);
          setModifiedFiles([]);

          // 터미널: 구분선 추가
          setOutputLines(prev => [...prev, { text: `── 실행 시작 (ID: ${data.run_id}) ──`, ts, type: 'started' }]);

          // 사고 흐름: 초기화 후 시작 메시지
          const id = ++thoughtIdRef.current;
          setThoughts([{ id, time, agent: cli.toUpperCase(), text: `▶ 에이전트 시작 [${data.run_id || ''}]` }]);

        } else if (type === 'output' || type === 'error') {
          const line = data.line || '';

          // output 수신 시 타임아웃 클리어 (started 누락 대비)
          if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }

          // 터미널: raw 출력 추가 (최대 500줄 유지 — 무제한 누적 시 렌더링 지연 방지)
          setOutputLines(prev => [...prev.slice(-499), { text: line, ts, type }]);

          // 상황판: 출력 라인에서 워크플로우 단계 추론 및 갱신
          if (line) {
            const detected = detectStage(line);
            if (detected && detected !== 'idle') {
              const prev = wfCurrentStageRef.current;
              // 검증 후 오류 발생 → 분석으로 루프백 시 루프 카운터 증가
              if (detected === 'analyzing' && (prev === 'verifying' || prev === 'error')) {
                setWfLoop(n => n + 1);
              }
              if (detected !== prev) {
                wfCurrentStageRef.current = detected;
                setWfStage(detected);
              }
            }
          }

          // 상황판: 분석/수정 파일 추적 — Claude Code 도구 호출 패턴 파싱
          // '● Read(file)' → 분석 파일, '● Edit(file)' → 수정 파일 목록에 추가
          if (line) {
            // 경로에서 파일명만 추출하는 헬퍼 (경로 구분자 기준 마지막 세그먼트 반환)
            const basename = (p: string) => {
              const segs = p.replace(/\\\\/g, '/').split('/');
              return (segs[segs.length - 1] || p).trim();
            };
            const readMatch = /Read|Glob|Grep|Search/i.test(line)
              ? line.match(/(?:Read|Glob|Grep|Search)\s*\(([^)]{3,80})\)/i) : null;
            if (readMatch) {
              const fname = basename(readMatch[1]);
              setAnalyzedFiles(prev => prev.includes(fname) ? prev : [...prev.slice(-9), fname]);
            }
            const editMatch = /Edit|Write|Create/i.test(line)
              ? line.match(/(?:Edit|Write|Create)\s*\(([^)]{3,80})\)/i) : null;
            if (editMatch) {
              const fname = basename(editMatch[1]);
              setModifiedFiles(prev => prev.includes(fname) ? prev : [...prev.slice(-9), fname]);
            }
          }

          // 사고 흐름: Thought 엔트리로 추가
          if (line) {
            const id = ++thoughtIdRef.current;
            setThoughts(prev => [...prev.slice(-99), {
              id, time,
              agent: type === 'error' ? 'ERROR' : 'AGENT',
              text: line,
            }]);
          }

        } else if (type === 'done') {
          // 최대 실행 타임아웃 해제
          if (maxRunTimeoutRef.current) { clearTimeout(maxRunTimeoutRef.current); maxRunTimeoutRef.current = null; }
          // data.status로 성공/실패 구분 (cli_agent는 type='done' 고정, status 필드로 판단)
          const runStatus: AgentStatus = data.status === 'error' ? 'error' : 'done';
          setStatus(runStatus);
          onStatusChange?.(false);
          setActiveSkill(runStatus === 'error' ? '오류' : '완료');

          // 상황판: 최종 단계 반영
          const finalStage: WorkflowStage = runStatus === 'error' ? 'error' : 'done';
          wfCurrentStageRef.current = finalStage;
          setWfStage(finalStage);

          const doneText = runStatus === 'error' ? '── 실행 오류 ──' : '── 실행 완료 ──';
          setOutputLines(prev => [...prev, { text: doneText, ts, type: 'done' }]);
          const id = ++thoughtIdRef.current;
          const doneLabel = runStatus === 'error' ? '✗ 오류' : '✓ 완료';
          setThoughts(prev => [...prev, { id, time, agent: 'DONE', text: `${doneLabel} [${data.run_id || ''}]` }]);
          loadHistory();

        } else if (type === 'stopped') {
          // 최대 실행 타임아웃 해제
          if (maxRunTimeoutRef.current) { clearTimeout(maxRunTimeoutRef.current); maxRunTimeoutRef.current = null; }
          setStatus('idle');
          onStatusChange?.(false);
          setActiveSkill('대기 중');

          setOutputLines(prev => [...prev, { text: data.line || '[중단됨]', ts, type: 'stopped' }]);
          loadHistory();
        }
      } catch {
        // JSON 파싱 오류 (하트비트 등) 무시
      }
    };

    es.onerror = () => {
      // 현재 활성 연결이 아닌 stale EventSource의 onerror는 무시 (재연결 루프 방지)
      if (sseRef.current !== es) return;
      // ① 즉시 상태 동기화 — SSE 끊김 사이 done/stopped 이벤트를 놓쳤을 경우
      //    running 고착을 방지하기 위해 딜레이 없이 실제 상태를 폴링
      loadStatus();
      // ② 2초 후 SSE 재연결 (중복 타이머 방지) — 5초에서 단축, 이벤트 소실 구간 축소
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      reconnectTimer.current = setTimeout(connectSSE, 2000);
    };
  }, [loadHistory, loadStatus, onStatusChange]);

  // ─── 초기화 ─────────────────────────────────────────────────────────────
  useEffect(() => {
    loadStatus();
    loadHistory();
    loadTerminals();
    connectSSE();

    // 10초마다 히스토리 + 에이전트 상태 자동 동기화
    // SSE가 done/stopped 이벤트를 유실했을 때 running 고착 방지
    const timer = setInterval(() => {
      loadHistory();
      loadStatus();
    }, 10000);

    // 3초마다 터미널별 상태 폴링 (상황판 T1~T8 카드 갱신)
    const terminalTimer = setInterval(() => {
      loadTerminals();
    }, 3000);
    return () => {
      clearInterval(timer);
      clearInterval(terminalTimer);
      // 언마운트 시: 모든 타이머 취소 + sseRef null 교체 → stale 재연결/타임아웃 완전 차단
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null; }
      if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }
      if (maxRunTimeoutRef.current) { clearTimeout(maxRunTimeoutRef.current); maxRunTimeoutRef.current = null; }
      const es = sseRef.current;
      sseRef.current = null;
      es?.close();
    };
  }, [loadStatus, loadHistory, loadTerminals, connectSSE]);

  // ─── 양방향 상태 동기화: 3초마다 서버 폴링 ─────────────────────────────────
  // 케이스 A: UI=running, 서버!=running → done 이벤트 유실 복구 (running 고착 해소)
  // 케이스 B: UI=error, 서버=running → 30초 타임아웃 오발 복구 (실제로는 실행 중)
  //
  // ⚠️ 중요: 동기화 메시지(outputLines 추가)는 반드시 status='running' → 완료 전환 시에만 실행.
  //    status='error' 상태에서 서버도 'error'를 반환하면 아무것도 하지 않아야 함.
  //    이 조건을 빠뜨리면 3초마다 "[동기화] 오류 감지" 메시지가 무한 누적되는 버그 발생.
  useEffect(() => {
    if (status !== 'running' && status !== 'error') return;

    const poll = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agent/status`);
        if (!res.ok) return;
        const data = await res.json();
        const srvStatus = data.status as AgentStatus;

        if (srvStatus !== 'running') {
          if (status === 'running' || status === 'error') {
            // 케이스 A: UI=running → 서버가 완료/오류 반환 → SSE done 이벤트 유실 복구
            // 케이스 A2: UI=error(30초 타임아웃 오발) → 서버가 done 반환 → 완료 상태로 갱신
            //   30초 타임아웃이 먼저 터지고 에이전트가 이후에 완료되면 status='error' 고착 발생.
            //   폴링에서 srvStatus='done'/'idle'이 오면 최종 상태로 강제 동기화해야 함.
            setStatus(srvStatus);
            onStatusChange?.(false);
            if (srvStatus === 'done') {
              setActiveSkill('완료');
              setOutputLines(prev => [
                ...prev,
                { text: '── [동기화] 완료 감지 ──', ts: new Date().toISOString(), type: 'done' },
              ]);
            } else if (srvStatus === 'error') {
              setActiveSkill('오류');
              if (status === 'running') {
                setOutputLines(prev => [
                  ...prev,
                  { text: '── [동기화] 오류 감지 ──', ts: new Date().toISOString(), type: 'error' },
                ]);
              }
            } else {
              setActiveSkill('대기 중');
            }
            loadHistory();
            if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }
          }

        } else if (status === 'error' && srvStatus === 'running') {
          // 케이스 B: 30초 타임아웃 오발 → UI=error인데 서버는 실행 중 → 복구
          setStatus('running');
          onStatusChange?.(true);
          if (data.current?.cli) {
            setActiveCli(data.current.cli);
            const cli = String(data.current.cli);
            setActiveSkill(cli === 'claude' ? 'Claude Code' : cli === 'gemini' ? 'Gemini' : cli === 'codex' ? 'Codex' : 'Auto');
          }
          if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }
        }
      } catch {
        // 서버 미실행 시 무시
      }
    }, 3000);

    return () => clearInterval(poll);
  }, [status, loadHistory, onStatusChange]);

  // ─── 경과 시간 카운터: running 진입 시 0에서 1초 단위 증가, 종료 시 리셋 ──
  useEffect(() => {
    if (status === 'running') {
      setElapsedSec(0);
      elapsedTimerRef.current = setInterval(() => setElapsedSec(s => s + 1), 1000);
    } else {
      if (elapsedTimerRef.current) { clearInterval(elapsedTimerRef.current); elapsedTimerRef.current = null; }
    }
    return () => {
      if (elapsedTimerRef.current) { clearInterval(elapsedTimerRef.current); elapsedTimerRef.current = null; }
    };
  }, [status]);

  // ─── 실행 요청 ──────────────────────────────────────────────────────────
  const handleRun = async () => {
    const task = taskInput.trim();
    if (!task || status === 'running') return;

    setOutputLines([]);
    setStatus('running');
    setActiveCli(selectedCli === 'auto' ? '분석 중...' : selectedCli);

    // 상황판 초기화 (분석/수정 파일 목록도 함께 초기화)
    setWfStage('analyzing');
    wfCurrentStageRef.current = 'analyzing';
    setWfLoop(0);
    setAnalyzedFiles([]);
    setModifiedFiles([]);

    // 30초 내 SSE started 이벤트 없으면 자동 오류 처리
    // 출력 유무와 무관하게 항상 타임아웃 메시지를 추가해야 "중간에 멈춘 것처럼 보이는" 버그를 방지
    if (runTimeoutRef.current) clearTimeout(runTimeoutRef.current);
    runTimeoutRef.current = setTimeout(() => {
      setStatus(prev => prev === 'running' ? 'error' : prev);
      setOutputLines(prev => [
        ...prev,
        { text: '[오류] 에이전트 응답 없음 (30초 타임아웃) — CLI가 시작되지 않았거나 SSE 연결이 끊겼습니다', ts: new Date().toISOString(), type: 'error' },
      ]);
    }, 30000);

    try {
      const res = await fetch(`${API_BASE}/api/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, cli: selectedCli, terminal_id: selectedTerminalId }),
      });
      const data = await res.json();
      if (data.error) {
        clearTimeout(runTimeoutRef.current!);
        setStatus('error');
        setOutputLines([{ text: `[오류] ${data.error}`, ts: new Date().toISOString(), type: 'error' }]);
      } else {
        setActiveCli(data.cli || selectedCli);
      }
    } catch {
      clearTimeout(runTimeoutRef.current!);
      setStatus('error');
      setOutputLines([{ text: '[오류] 서버 연결 실패', ts: new Date().toISOString(), type: 'error' }]);
    }
  };

  // ─── 중단 요청 ──────────────────────────────────────────────────────────
  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/api/agent/stop`, { method: 'POST' });
      setStatus('idle');
      // SSE stopped 이벤트를 기다리지 않고 즉시 배지 해제 (SSE 끊김 시 배지 고착 방지)
      onStatusChange?.(false);
      setActiveSkill('대기 중');
    } catch {
      // 무시
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); handleRun(); }
  };

  // ─── 터미널 출력 줄 색상 ────────────────────────────────────────────────
  const getLineColor = (line: OutputLine): string => {
    if (line.type === 'error')   return 'text-red-400';
    if (line.type === 'started') return 'text-yellow-400';
    if (line.type === 'done')    return 'text-green-400';
    if (line.type === 'stopped') return 'text-orange-400';
    if (line.text.startsWith('[오류]') || line.text.startsWith('Error')) return 'text-red-400';
    if (line.text.startsWith('✓') || line.text.includes('완료')) return 'text-green-400';
    return 'text-green-300/80';
  };

  // ─── 탭 버튼 렌더 ───────────────────────────────────────────────────────
  const tabBtn = (id: ActiveTab, label: string, icon: React.ReactNode) => (
    <button
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-1 px-2 py-1 text-[10px] rounded transition
        ${activeTab === id
          ? 'bg-primary/20 text-primary font-bold'
          : 'text-white/30 hover:text-white/60'
        }`}
    >
      {icon}
      {label}
    </button>
  );

  // ════════════════════════════════════════════════════════════════════════
  return (
    <div className="flex flex-col h-full gap-2 overflow-hidden text-[11px]">

      {/* ── 헤더: 에이전트 이름 + 상태 배지 ──────────────────────────────── */}
      <div className="flex items-center justify-between shrink-0 px-1">
        <div className="flex items-center gap-1.5 font-bold text-primary uppercase tracking-tighter">
          <Bot className="w-3.5 h-3.5" />
          자율 에이전트
        </div>
        <div className={`flex items-center gap-1 ${STATUS_COLORS[status]}`}>
          {status === 'running' && (
            <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
          )}
          <span>{STATUS_LABELS[status]}</span>
          {status === 'running' && (
            <span className="text-white/30 ml-1 font-mono text-[10px]">
              {/* 경과 시간 표시: 출력 없어도 에이전트가 살아있음을 사용자에게 알림 */}
              {`${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, '0')}`}
              {activeCli && ` (${activeCli})`}
            </span>
          )}
        </div>
      </div>

      {/* ── 지시 입력 영역 ──────────────────────────────────────────────── */}
      <div className="shrink-0 flex flex-col gap-1.5 bg-black/20 rounded border border-white/5 p-2">
        <textarea
          ref={textareaRef}
          value={taskInput}
          onChange={e => setTaskInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="AI에게 지시하세요... (Ctrl+Enter 실행)"
          rows={3}
          disabled={status === 'running'}
          className="w-full bg-transparent text-white/80 placeholder-white/20 resize-none
                     focus:outline-none text-[11px] leading-relaxed disabled:opacity-50"
        />

        <div className="flex items-center gap-1.5">
          {/* CLI 선택 드롭다운 */}
          <div className="relative">
            <button
              onClick={() => setShowCliMenu(v => !v)}
              disabled={status === 'running'}
              className="flex items-center gap-1 px-2 py-1 rounded bg-white/5 hover:bg-white/10
                         text-white/60 hover:text-white/80 transition disabled:opacity-40"
            >
              <span>{CLI_LABELS[selectedCli]}</span>
              <ChevronDown className="w-3 h-3" />
            </button>
            {showCliMenu && (
              <div className="absolute bottom-full mb-1 left-0 z-50 bg-[#1e1e2e] border border-white/10
                              rounded shadow-xl min-w-[160px] overflow-hidden">
                {(Object.keys(CLI_LABELS) as CliChoice[]).map(k => (
                  <button
                    key={k}
                    onClick={() => { setSelectedCli(k); setShowCliMenu(false); }}
                    className={`w-full text-left px-3 py-1.5 hover:bg-white/10 transition
                                ${selectedCli === k ? 'text-primary' : 'text-white/60'}`}
                  >
                    {CLI_LABELS[k]}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex-1" />

          {status === 'running' && (
            <button
              onClick={handleStop}
              className="flex items-center gap-1 px-2 py-1 rounded bg-red-500/20 hover:bg-red-500/30
                         text-red-400 hover:text-red-300 transition"
            >
              <Square className="w-3 h-3" />
              중단
            </button>
          )}

          <button
            onClick={handleRun}
            disabled={status === 'running' || !taskInput.trim()}
            className="flex items-center gap-1 px-3 py-1 rounded bg-primary/80 hover:bg-primary
                       text-white font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {status === 'running'
              ? <div className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
              : <Play className="w-3 h-3" />}
            실행
          </button>
        </div>
      </div>

      {/* ── 탭 바 ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 shrink-0 border-b border-white/5 pb-1">
        {tabBtn('workflow',     '상황판',    <LayoutDashboard className="w-3 h-3" />)}
        {tabBtn('terminal',    '터미널',   <Terminal className="w-3 h-3" />)}
        {tabBtn('thoughts',    '사고 흐름', <Brain className="w-3 h-3" />)}
        {tabBtn('history',     '히스토리', <Clock className="w-3 h-3" />)}
        {tabBtn('orchestrator','스킬체인', <Network className="w-3 h-3" />)}
        {tabBtn('hive',        '하이브',   <Database className="w-3 h-3" />)}
        <div className="ml-auto text-[9px] text-primary/60 font-mono uppercase">{activeSkill}</div>
      </div>

      {/* ── 탭 콘텐츠 ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden min-h-0">

        {/* ──────────────────────────────────────────────────────────────
             상황판 탭: T1~T8 터미널별 모니터링 패널 목록 (1열 스크롤)
             TerminalSlot 상단 모니터링 기준: 파이프라인 + 작업 + 출력 표시.
             3초 폴링으로 각 터미널 상태 실시간 갱신.
             카드 클릭 → 해당 터미널 선택 → 실행 버튼이 그 터미널로 전송.
        ─────────────────────────────────────────────────────────────── */}
        {activeTab === 'workflow' && (
          <div className="flex flex-col h-full overflow-y-auto gap-1.5 pr-0.5">

            {/* ── 선택 터미널 안내 배너 + 현재 실행 중인 터미널 목록 ──────── */}
            {/* 좌측: 다음 실행을 보낼 대상 터미널. 우측: 지금 실제 동작 중인 터미널 배지 */}
            <div className="shrink-0 flex items-center justify-between px-0.5 pb-0.5">
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-white/25">실행 대상:</span>
                <span className="text-[10px] font-bold font-mono text-primary">{selectedTerminalId}</span>
                <span className="text-[9px] text-white/15">— 카드 클릭으로 변경</span>
              </div>
              {/* 현재 running 상태인 터미널을 노란 배지로 우측에 나열 */}
              {(() => {
                const runningIds = Array.from({ length: 8 }, (_, i) => `T${i + 1}`)
                  .filter(tid => terminals[tid]?.status === 'running' && !(terminals[tid] as any)?.external);
                if (runningIds.length === 0) return (
                  <span className="text-[8px] text-white/15 font-mono">실행 중 없음</span>
                );
                return (
                  <div className="flex items-center gap-1">
                    <span className="text-[8px] text-yellow-400/50">실행 중:</span>
                    {runningIds.map(tid => (
                      <span
                        key={tid}
                        className="text-[9px] font-bold font-mono text-yellow-300 bg-yellow-400/15 px-1.5 py-0.5 rounded border border-yellow-400/30 animate-pulse"
                      >
                        {tid}
                      </span>
                    ))}
                  </div>
                );
              })()}
            </div>

            {/* ── 활성 터미널만 표시 (idle 카드 숨김, 선택된 터미널은 예외) ── */}
            {/* external=true인 외부 Gemini 세션은 다른 프로젝트이므로 표시 제외 */}
            <div className="flex flex-col gap-1.5 shrink-0">
              {Array.from({ length: 8 }, (_, i) => `T${i + 1}`).map(tid => {
                const state: TerminalState = terminals[tid] ?? {
                  status: 'idle', task: '', cli: '', run_id: '', ts: '', last_line: '',
                };
                // 외부 에이전트(다른 프로젝트 Gemini)는 목록에서 제외
                if (state.external) return null;
                // running 중이 아니고 선택된 터미널도 아니면 숨김
                // (idle/done 상태의 비선택 터미널은 불필요하게 표시하지 않음)
                if (state.status !== 'running' && selectedTerminalId !== tid) return null;
                return (
                  <TerminalCard
                    key={tid}
                    id={tid}
                    state={state}
                    selected={selectedTerminalId === tid}
                    onClick={() => setSelectedTerminalId(tid)}
                  />
                );
              })}
            </div>

          </div>
        )}

        {/* 터미널 탭: raw 출력 */}
        {activeTab === 'terminal' && (
          <div className="flex flex-col h-full bg-black/40 rounded border border-white/5 overflow-hidden">
            <div className="flex items-center justify-between px-2 py-1 border-b border-white/5 shrink-0">
              <span className="text-white/30 font-mono text-[10px]">실시간 출력</span>
              <button
                onClick={() => setOutputLines([])}
                className="text-white/20 hover:text-white/50 transition"
                title="출력 초기화"
              >
                <RotateCw className="w-3 h-3" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed">
              {outputLines.length === 0
                ? <div className="text-white/15 italic">실행 결과가 여기에 표시됩니다...</div>
                : outputLines.map((line, i) => (
                    <div key={i} className={`${getLineColor(line)} whitespace-pre-wrap break-all`}>
                      {line.text}
                    </div>
                  ))
              }
              <div ref={outputEndRef} />
            </div>
          </div>
        )}

        {/* 사고 흐름 탭: Thought Stream (구 MissionControlPanel) */}
        {activeTab === 'thoughts' && (
          <div className="flex flex-col h-full gap-2 overflow-hidden">
            {/* 최근 실행 이력: 최근 실행 이력 */}
            <div className="flex flex-col gap-1 shrink-0">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-primary uppercase tracking-tighter">
                <CheckCircle2 className="w-3 h-3" /> 최근 실행 이력
              </div>
              <div className="bg-black/20 rounded border border-white/5 p-2 flex flex-col gap-1.5 max-h-28 overflow-y-auto">
                {history.length === 0
                  ? <div className="text-[10px] text-white/30 text-center py-1">실행 이력 없음</div>
                  : history.slice(-5).map(run => (
                      <div key={run.id} className="flex items-center gap-2 text-[10px]">
                        <StatusIcon status={run.status} />
                        <span className={`flex-1 truncate ${run.status === 'done' ? 'text-white/40 line-through' : 'text-white/80'}`}>
                          {run.task}
                        </span>
                        <span className={`text-[9px] font-bold uppercase px-1 py-0.5 rounded ${
                          run.cli === 'claude' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'
                        }`}>
                          {run.cli}
                        </span>
                      </div>
                    ))
                }
              </div>
            </div>

            {/* AI 사고 흐름 */}
            <div className="flex flex-col flex-1 gap-1 overflow-hidden">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-cyan-400 uppercase tracking-tighter">
                <Brain className="w-3 h-3" /> AI 사고 흐름
              </div>
              <div className="flex-1 bg-black/40 rounded border border-white/5 p-2 font-mono text-[10px]
                              overflow-y-auto flex flex-col gap-1.5">
                {thoughts.length === 0
                  ? <div className="text-white/20 text-center py-4">에이전트 대기 중...</div>
                  : thoughts.map(t => (
                      <div key={t.id} className="flex flex-col gap-0.5 border-l border-white/10 pl-2">
                        <div className="flex items-center gap-2">
                          <span className="text-white/30">[{t.time}]</span>
                          <span className={`font-bold ${
                            t.agent === 'ERROR'  ? 'text-red-400' :
                            t.agent === 'DONE'   ? 'text-green-400' :
                            t.agent === 'CLAUDE' ? 'text-orange-400' :
                            t.agent === 'GEMINI' ? 'text-blue-400' :
                            t.agent === 'CODEX'  ? 'text-yellow-400' :
                            'text-primary'
                          }`}>{t.agent}</span>
                        </div>
                        <div className="text-white/70 leading-relaxed whitespace-pre-wrap break-all">
                          {t.text}
                        </div>
                      </div>
                    ))
                }
                <div ref={thoughtEndRef} />
              </div>
            </div>
          </div>
        )}

        {/* 히스토리 탭: 전체 실행 기록 */}
        {activeTab === 'history' && (
          <div className="h-full overflow-y-auto">
            {history.length === 0
              ? <div className="text-white/20 italic p-4 text-center">실행 기록 없음</div>
              : [...history].reverse().map(run => (
                  <button
                    key={run.id}
                    onClick={() => { setTaskInput(run.task); setActiveTab('terminal'); }}
                    className="w-full text-left px-2 py-1.5 hover:bg-white/5 transition
                               border-b border-white/5 last:border-0"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={
                        run.status === 'done'  ? 'text-green-400' :
                        run.status === 'error' ? 'text-red-400' : 'text-orange-400'
                      }>
                        {run.status === 'done' ? '✓' : run.status === 'error' ? '✗' : '■'}
                      </span>
                      <span className={`px-1 rounded text-[9px] ${
                        run.cli === 'claude' ? 'bg-purple-500/20 text-purple-300' : 'bg-blue-500/20 text-blue-300'
                      }`}>
                        {run.cli}
                      </span>
                      <span className="text-white/60 truncate flex-1">
                        {run.task.slice(0, 40)}{run.task.length > 40 ? '...' : ''}
                      </span>
                      <span className="text-white/20 text-[9px] shrink-0">
                        {run.ts.slice(11, 19)}
                      </span>
                    </div>
                  </button>
                ))
            }
          </div>
        )}

        {/* ──────────────────────────────────────────────────────────────
             스킬체인 탭: AI 오케스트레이터 스킬 레지스트리 + 터미널별 체인
             (구 OrchestratorPanel 내용을 이 탭으로 통합)
             - 상단: 스킬 ①~⑦ 세로 목록 + 각 스킬 사용 중인 터미널 배지
             - 하단: 터미널별 스킬 체인 순서 (T1: 1-① → 1-③ → ...)
        ─────────────────────────────────────────────────────────────── */}
        {activeTab === 'orchestrator' && (() => {
          // 표시할 스킬 목록 (API 없으면 기본값)
          const orchSkills = orchChainData.skill_registry.length > 0
            ? orchChainData.skill_registry : DEFAULT_ORCH_SKILLS;
          // 활성 터미널 (steps 있는 것만, 번호 순)
          const activeOrchTerminals = Object.entries(orchChainData.terminals ?? {})
            .filter(([, chain]) => chain.steps && chain.steps.length > 0)
            .sort(([a], [b]) => Number(a) - Number(b));
          // 스킬번호 → 사용 터미널+스텝 매핑
          const skillUsage: Record<number, { termId: string; step: typeof activeOrchTerminals[0][1]['steps'][0] }[]> = {};
          activeOrchTerminals.forEach(([termId, chain]) => {
            chain.steps.forEach(step => {
              if (!skillUsage[step.skill_num]) skillUsage[step.skill_num] = [];
              skillUsage[step.skill_num].push({ termId, step });
            });
          });
          const stepBadgeColor = (s: string) =>
            s === 'done'    ? 'bg-green-500/20 text-green-400 border-green-500/30' :
            s === 'running' ? 'bg-primary/20 text-primary border-primary/40 animate-pulse' :
            s === 'failed'  ? 'bg-red-500/20 text-red-400 border-red-500/30' :
            s === 'skipped' ? 'bg-white/5 text-[#555] border-white/10' :
                              'bg-white/5 text-[#666] border-white/10';
          const stepIcon = (s: string) =>
            s === 'done' ? '✅' : s === 'running' ? '🔄' : s === 'failed' ? '❌' : s === 'skipped' ? '⏭️' : '⏳';
          const agentBadgeColor = (agent: string) =>
            agent === 'claude' ? 'bg-green-500/20 text-green-400' :
            agent === 'gemini' ? 'bg-blue-500/20 text-blue-400' :
                                 'bg-yellow-500/20 text-yellow-400';

          return (
            <div className="flex flex-col h-full overflow-hidden gap-2">
              {/* 헤더: 마지막 실행 시각 + 수동 실행 버튼 */}
              <div className="flex items-center justify-between shrink-0">
                <div className="text-[9px] text-[#858585] font-mono">
                  {orchLastRun ? `마지막 실행: ${orchLastRun}` : '스킬 체인 모니터'}
                </div>
                <button
                  onClick={runOrchestrator}
                  disabled={orchRunning}
                  className="flex items-center gap-1 px-2 py-1 bg-primary/20 hover:bg-primary/40
                             disabled:opacity-40 text-primary rounded text-[9px] font-bold transition-colors"
                >
                  <Play className="w-3 h-3" />
                  {orchRunning ? '실행 중...' : '지금 실행'}
                </button>
              </div>

              {/* 스킬 레지스트리 ①~⑦ */}
              <div className="shrink-0 rounded border border-white/10 overflow-hidden">
                <div className="px-2 py-1.5 border-b border-white/10 flex items-center justify-between">
                  <span className="text-[9px] font-bold text-[#969696] uppercase tracking-wider">스킬 레지스트리</span>
                  <span className="text-[8px] text-[#555]">사용 중인 터미널 →</span>
                </div>
                <div className="flex flex-col">
                  {orchSkills.map((sk, idx) => {
                    const usages = skillUsage[sk.num] ?? [];
                    const isInUse = usages.length > 0;
                    return (
                      <div
                        key={sk.num}
                        className={`flex items-center gap-2 px-2 py-1.5 ${
                          idx < orchSkills.length - 1 ? 'border-b border-white/5' : ''
                        } ${isInUse ? 'bg-white/3' : ''}`}
                      >
                        <span className="text-primary font-bold text-[10px] font-mono w-4 shrink-0">
                          {CIRCLE_NUMS[sk.num] ?? sk.num}
                        </span>
                        <span className={`text-[9px] font-mono w-16 shrink-0 ${isInUse ? 'text-[#cccccc]' : 'text-[#666]'}`}>
                          {sk.short}
                        </span>
                        <div className="flex items-center gap-1 flex-wrap flex-1">
                          {usages.map(({ termId, step }, i) => (
                            <div
                              key={i}
                              className={`flex items-center gap-0.5 px-1 py-0.5 rounded border text-[8px] font-mono font-bold cursor-default ${stepBadgeColor(step.status)}`}
                              title={step.summary || `T${termId} — ${step.status}`}
                            >
                              {stepIcon(step.status)} T{termId}
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 터미널별 스킬 체인 순서 */}
              <div className="flex-1 overflow-y-auto flex flex-col gap-1.5">
                {activeOrchTerminals.length > 0 ? (
                  <>
                    <div className="text-[9px] font-bold text-[#969696] uppercase tracking-wider px-1 shrink-0">
                      터미널별 사용 순서
                    </div>
                    {activeOrchTerminals.map(([termId, chain]) => {
                      const agentName = orchTerminalAgents[termId] || chain.agent || '';
                      const chainBorder =
                        chain.status === 'running' ? 'border-primary/30 bg-primary/5' :
                        chain.status === 'done'    ? 'border-green-500/20 bg-green-500/5' :
                                                     'border-white/10';
                      return (
                        <div key={termId} className={`rounded border ${chainBorder} p-2 shrink-0`}>
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px] font-bold text-[#dddddd] font-mono">T{termId}</span>
                              {agentName && (
                                <span className={`px-1 py-0.5 rounded text-[7px] font-bold ${agentBadgeColor(agentName)}`}>
                                  {agentName}
                                </span>
                              )}
                              {chain.status === 'running' && (
                                <span className="text-[7px] text-primary animate-pulse">● 실행중</span>
                              )}
                              {chain.status === 'done' && (
                                <span className="text-[7px] text-green-400">✓ 완료</span>
                              )}
                            </div>
                            {chain.updated_at && (
                              <span className="text-[7px] text-[#555] font-mono shrink-0">
                                {new Date(chain.updated_at).toLocaleTimeString()}
                              </span>
                            )}
                          </div>
                          {chain.request && (
                            <div className="text-[7px] text-[#777] mb-1.5 truncate" title={chain.request}>
                              "{chain.request}"
                            </div>
                          )}
                          <div className="flex items-center gap-1 flex-wrap">
                            {chain.steps.map((step, i) => {
                              const circleNum = CIRCLE_NUMS[step.skill_num] ?? step.skill_num;
                              return (
                                <div key={i} className="flex items-center gap-1">
                                  {i > 0 && <span className="text-[#333] text-[8px]">→</span>}
                                  <div
                                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded border text-[8px] font-mono font-bold ${stepBadgeColor(step.status)}`}
                                    title={step.summary || step.skill_name}
                                  >
                                    {stepIcon(step.status)}
                                    <span className="text-[#555]">{termId}-</span>
                                    <span>{circleNum}</span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                          {(() => {
                            const running = chain.steps.find(s => s.status === 'running');
                            const lastDone = [...chain.steps].reverse().find(s => s.status === 'done');
                            if (running) return (
                              <div className="mt-1.5 text-[7px] text-primary truncate">
                                ⚡ {running.skill_name} 실행 중...
                              </div>
                            );
                            if (lastDone?.summary) return (
                              <div className="mt-1.5 text-[7px] text-[#777] truncate">
                                ✅ {lastDone.summary}
                              </div>
                            );
                            return null;
                          })()}
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <div className="text-center text-[#555] text-[9px] py-4 italic">
                    실행 중인 터미널 없음
                    <div className="text-[8px] mt-1 text-[#444]">
                      /vibe-orchestrate 실행 시 여기에 순서가 표시됩니다
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {/* ──────────────────────────────────────────────────────────────
             하이브 활동 탭: Claude/Gemini가 하이브 시스템을 실제로 쓰는지 시각화
             - 초록: 메모리 읽기 (current-work 자동 로드)
             - 파랑: 메모리 쓰기 (작업 후 저장)
             - 보라: 오케스트레이션 (스킬 체인 실행)
             - 노랑: 메시지 수신 (Gemini↔Claude 통신)
             - 빨강: 자기치유 (스킬 자동 설치)
             5초마다 /api/hive/activity 폴링 → 실시간 갱신
        ─────────────────────────────────────────────────────────────── */}
        {activeTab === 'hive' && (
          <div className="flex flex-col h-full overflow-hidden">
            {/* 범례 헤더 */}
            <div className="shrink-0 flex items-center gap-2 px-1 py-1 border-b border-white/5 flex-wrap">
              <span className="text-[8px] text-white/30">범례:</span>
              {[
                { type: 'memory_read',  label: '메모리 읽기',    color: 'text-emerald-400' },
                { type: 'memory_write', label: '메모리 쓰기',    color: 'text-blue-400'   },
                { type: 'hive_ctx',     label: '컨텍스트 주입',  color: 'text-cyan-400'   },
                { type: 'orchestrate',  label: '오케스트레이션', color: 'text-purple-400' },
                { type: 'message',      label: '메시지',         color: 'text-yellow-400' },
                { type: 'heal',         label: '자기치유',       color: 'text-red-400'    },
                { type: 'session',      label: '세션',           color: 'text-white/30'   },
              ].map(({ label, color }) => (
                <span key={label} className={`text-[8px] font-mono ${color}`}>● {label}</span>
              ))}
            </div>

            {/* 이벤트 피드 — selectedTerminalId 기준 필터링 */}
            <div className="flex-1 overflow-y-auto flex flex-col gap-0.5 p-1">
              {(() => {
                // selectedTerminalId(T1~T8) 기준으로 필터링. T0는 미설정(전체 표시)
                const filtered = selectedTerminalId && selectedTerminalId !== 'T0'
                  ? hiveEvents.filter(e => !e.terminal_id || e.terminal_id === selectedTerminalId)
                  : hiveEvents;
                if (filtered.length === 0) return (
                  <div className="flex items-center justify-center h-full text-[10px] text-white/20">
                    {selectedTerminalId && selectedTerminalId !== 'T0'
                      ? `${selectedTerminalId} 하이브 활동 없음`
                      : '하이브 활동 없음 — 서버를 시작하고 Claude에게 지시를 내려보세요'}
                  </div>
                );
                return filtered.map((ev, i) => {
                // 이벤트 타입별 색상 및 아이콘
                const typeStyle: Record<string, { color: string; icon: string; label: string }> = {
                  memory_read:  { color: 'text-emerald-400 border-emerald-900/40', icon: '↓', label: '읽기' },
                  memory_write: { color: 'text-blue-400 border-blue-900/40',       icon: '↑', label: '저장' },
                  hive_ctx:     { color: 'text-cyan-400 border-cyan-900/40',       icon: '⬇', label: '주입' },
                  orchestrate:  { color: 'text-purple-400 border-purple-900/40',   icon: '⚡', label: '오케' },
                  message:      { color: 'text-yellow-400 border-yellow-900/40',   icon: '✉', label: '메시지' },
                  heal:         { color: 'text-red-400 border-red-900/40',         icon: '🔧', label: '치유' },
                  session:      { color: 'text-white/25 border-white/5',           icon: '—', label: '세션' },
                };
                const style = typeStyle[ev.type] ?? typeStyle.session;
                // 시간 포맷: HH:MM:SS
                const ts = ev.timestamp ? ev.timestamp.substring(11, 19) : '';
                // 에이전트 배지 색상
                const agentColor = ev.agent === 'Claude' ? 'text-primary' :
                                   ev.agent === 'Gemini' ? 'text-yellow-400' :
                                   ev.agent === 'Hive'   ? 'text-cyan-400' : 'text-white/40';
                return (
                  <div
                    key={i}
                    className={`flex items-start gap-1.5 px-1.5 py-1 rounded border ${style.color} bg-white/2 hover:bg-white/4 transition-colors`}
                  >
                    {/* 타입 아이콘 */}
                    <span className={`shrink-0 text-[10px] w-3 text-center ${style.color.split(' ')[0]}`}>
                      {style.icon}
                    </span>
                    {/* 타입 배지 */}
                    <span className={`shrink-0 text-[8px] font-mono font-bold w-8 ${style.color.split(' ')[0]}`}>
                      {style.label}
                    </span>
                    {/* 에이전트 */}
                    <span className={`shrink-0 text-[8px] font-mono font-bold w-10 ${agentColor}`}>
                      {ev.agent}
                    </span>
                    {/* 내용 */}
                    <span className="flex-1 text-[9px] text-white/60 font-mono truncate" title={ev.task}>
                      {ev.task}
                    </span>
                    {/* 터미널 배지 */}
                    {ev.terminal_id && ev.terminal_id !== 'T0' && (
                      <span className="shrink-0 text-[7px] font-mono font-bold px-1 rounded bg-white/5 text-white/40">
                        {ev.terminal_id}
                      </span>
                    )}
                    {/* 시간 */}
                    <span className="shrink-0 text-[8px] text-white/20 font-mono">{ts}</span>
                  </div>
                );
              });
              })()}
            </div>

            {/* 요약 푸터 — 필터 적용 기준으로 카운트 */}
            {(() => {
              const filtered = selectedTerminalId && selectedTerminalId !== 'T0'
                ? hiveEvents.filter(e => !e.terminal_id || e.terminal_id === selectedTerminalId)
                : hiveEvents;
              return (
                <div className="shrink-0 flex items-center gap-3 px-2 py-1 border-t border-white/5 text-[8px] text-white/25 font-mono">
                  <span className="text-primary/50 font-bold">{selectedTerminalId}</span>
                  <span>총 {filtered.length}개</span>
                  <span>읽기: {filtered.filter(e => e.type === 'memory_read' || e.type === 'hive_ctx').length}회</span>
                  <span>저장: {filtered.filter(e => e.type === 'memory_write').length}회</span>
                  <span>오케: {filtered.filter(e => e.type === 'orchestrate').length}회</span>
                </div>
              );
            })()}
          </div>
        )}

      </div>
    </div>
  );
}
