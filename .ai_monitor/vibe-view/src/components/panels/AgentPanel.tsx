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
 * ------------------------------------------------------------------------
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Bot, Play, Square, RotateCw, ChevronDown, Clock,
  Brain, CheckCircle2, Circle, XCircle, Terminal,
} from 'lucide-react';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ─── 타입 정의 ──────────────────────────────────────────────────────────────

type AgentStatus = 'idle' | 'running' | 'done' | 'error' | 'unavailable';
type CliChoice   = 'auto' | 'claude' | 'gemini';
type ActiveTab   = 'terminal' | 'thoughts' | 'history';

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

// ────────────────────────────────────────────────────────────────────────────

export default function AgentPanel({ onStatusChange }: AgentPanelProps) {
  // ─── 상태 ───────────────────────────────────────────────────────────────
  const [taskInput, setTaskInput]     = useState('');
  const [selectedCli, setSelectedCli] = useState<CliChoice>('auto');
  const [status, setStatus]           = useState<AgentStatus>('idle');
  const [activeCli, setActiveCli]     = useState<string>('');
  const [showCliMenu, setShowCliMenu] = useState(false);
  const [activeTab, setActiveTab]     = useState<ActiveTab>('terminal');

  // 터미널 탭 데이터
  const [outputLines, setOutputLines] = useState<OutputLine[]>([]);

  // 사고 흐름 탭 데이터
  const [thoughts, setThoughts]       = useState<ThoughtEntry[]>([]);
  const [activeSkill, setActiveSkill] = useState<string>('대기 중');
  const thoughtIdRef                  = useRef(0);

  // 히스토리 탭 데이터
  const [history, setHistory]         = useState<AgentRun[]>([]);

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
          setActiveSkill(cli === 'claude' ? 'Claude Code' : cli === 'gemini' ? 'Gemini' : 'Auto');

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
    connectSSE();

    // 10초마다 히스토리 + 에이전트 상태 자동 동기화
    // SSE가 done/stopped 이벤트를 유실했을 때 running 고착 방지
    const timer = setInterval(() => {
      loadHistory();
      loadStatus();
    }, 10000);
    return () => {
      clearInterval(timer);
      // 언마운트 시: 모든 타이머 취소 + sseRef null 교체 → stale 재연결/타임아웃 완전 차단
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null; }
      if (runTimeoutRef.current) { clearTimeout(runTimeoutRef.current); runTimeoutRef.current = null; }
      if (maxRunTimeoutRef.current) { clearTimeout(maxRunTimeoutRef.current); maxRunTimeoutRef.current = null; }
      const es = sseRef.current;
      sseRef.current = null;
      es?.close();
    };
  }, [loadStatus, loadHistory, connectSSE]);

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
            setActiveSkill(cli === 'claude' ? 'Claude Code' : cli === 'gemini' ? 'Gemini' : 'Auto');
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
        body: JSON.stringify({ task, cli: selectedCli }),
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
          Autonomous Agent
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
        {tabBtn('terminal', '터미널', <Terminal className="w-3 h-3" />)}
        {tabBtn('thoughts', '사고 흐름', <Brain className="w-3 h-3" />)}
        {tabBtn('history',  '히스토리', <Clock className="w-3 h-3" />)}
        {/* 활성 스킬 표시 (우측 정렬) */}
        <div className="ml-auto text-[9px] text-primary/60 font-mono uppercase">{activeSkill}</div>
      </div>

      {/* ── 탭 콘텐츠 ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden min-h-0">

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
            {/* Live Micro-Plan: 최근 실행 이력 */}
            <div className="flex flex-col gap-1 shrink-0">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-primary uppercase tracking-tighter">
                <CheckCircle2 className="w-3 h-3" /> Live Micro-Plan
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

            {/* AI Thought Stream */}
            <div className="flex flex-col flex-1 gap-1 overflow-hidden">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-cyan-400 uppercase tracking-tighter">
                <Brain className="w-3 h-3" /> AI Thought Stream
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

      </div>
    </div>
  );
}
