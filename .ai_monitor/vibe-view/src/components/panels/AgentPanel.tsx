/**
 * ------------------------------------------------------------------------
 * 📄 파일명: AgentPanel.tsx
 * 📝 설명: CLI 오케스트레이터 자율 에이전트 패널.
 *          대시보드에서 직접 지시를 입력하면 Claude Code CLI 또는 Gemini CLI가
 *          자동으로 선택되어 비대화형 모드로 실행되고, 결과를 실시간으로 표시합니다.
 *          OpenHands 스타일의 자율 에이전트 UX를 도커 없이 구현합니다.
 *
 * REVISION HISTORY:
 * - 2026-03-04 Claude: 최초 구현
 *   - 지시 입력창 + CLI 선택 드롭다운 + 실행/중단 버튼
 *   - /api/events/agent SSE로 실시간 출력 스트리밍
 *   - /api/agent/runs로 최근 실행 히스토리 표시
 *   - 터미널 스타일 출력창 (monospace, green-on-black)
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Bot, Play, Square, RotateCw, ChevronDown, ChevronUp, Clock } from 'lucide-react';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

// ─── 타입 정의 ──────────────────────────────────────────────────────────────

type AgentStatus = 'idle' | 'running' | 'done' | 'error' | 'unavailable';
type CliChoice = 'auto' | 'claude' | 'gemini';

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

// ─── CLI 선택 레이블 ────────────────────────────────────────────────────────
const CLI_LABELS: Record<CliChoice, string> = {
  auto: '🤖 Auto (자동 선택)',
  claude: '⚡ Claude Code',
  gemini: '✨ Gemini CLI',
};

// 상태별 배지 색상
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


interface AgentPanelProps {
  /** App.tsx에 에이전트 실행 상태를 알리는 콜백 (ActivityBar 배지 표시용) */
  onStatusChange?: (running: boolean) => void;
}

export default function AgentPanel({ onStatusChange }: AgentPanelProps) {
  // ─── 상태 ────────────────────────────────────────────────────────────────
  const [taskInput, setTaskInput]       = useState('');
  const [selectedCli, setSelectedCli]   = useState<CliChoice>('auto');
  const [status, setStatus]             = useState<AgentStatus>('idle');
  const [outputLines, setOutputLines]   = useState<OutputLine[]>([]);
  const [history, setHistory]           = useState<AgentRun[]>([]);
  const [showHistory, setShowHistory]   = useState(false);
  const [activeCli, setActiveCli]       = useState<string>('');
  const [showCliMenu, setShowCliMenu]   = useState(false);

  const outputEndRef  = useRef<HTMLDivElement>(null);
  const sseRef        = useRef<EventSource | null>(null);
  const textareaRef   = useRef<HTMLTextAreaElement>(null);

  // ─── 자동 스크롤 ─────────────────────────────────────────────────────────
  useEffect(() => {
    outputEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [outputLines]);

  // ─── 초기 상태 + 히스토리 로드 ───────────────────────────────────────────
  useEffect(() => {
    loadStatus();
    loadHistory();
  }, []);

  // ─── SSE 연결 (에이전트 실행 시 자동 구독) ───────────────────────────────
  const connectSSE = useCallback(() => {
    // 기존 연결 닫기
    if (sseRef.current) {
      sseRef.current.close();
    }

    const es = new EventSource(`${API_BASE}/api/events/agent`);
    sseRef.current = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const type = data.type as OutputLine['type'];

        if (type === 'output' || type === 'error') {
          // 일반 출력 줄 추가
          setOutputLines(prev => [...prev, {
            text: data.line || '',
            ts: data.ts || new Date().toISOString(),
            type,
          }]);
        } else if (type === 'started') {
          // 실행 시작 이벤트
          setStatus('running');
          onStatusChange?.(true);
          setOutputLines(prev => [...prev, {
            text: `── 실행 시작 (ID: ${data.run_id}) ──`,
            ts: data.ts || new Date().toISOString(),
            type: 'started',
          }]);
        } else if (type === 'done') {
          // 완료 이벤트
          setStatus('done');
          onStatusChange?.(false);
          setOutputLines(prev => [...prev, {
            text: `── 실행 완료 ──`,
            ts: data.ts || new Date().toISOString(),
            type: 'done',
          }]);
          loadHistory(); // 히스토리 갱신
        } else if (type === 'stopped') {
          // 중단 이벤트
          setStatus('idle');
          onStatusChange?.(false);
          setOutputLines(prev => [...prev, {
            text: data.line || '[중단됨]',
            ts: data.ts || new Date().toISOString(),
            type: 'stopped',
          }]);
        }
      } catch {
        // JSON 파싱 실패 시 무시 (하트비트 등)
      }
    };

    es.onerror = () => {
      // SSE 연결 오류는 자동 재연결을 브라우저에 맡김
    };
  }, []);

  // 컴포넌트 마운트 시 SSE 연결, 언마운트 시 정리
  useEffect(() => {
    connectSSE();
    return () => {
      sseRef.current?.close();
    };
  }, [connectSSE]);

  // ─── API 호출 함수들 ────────────────────────────────────────────────────
  const loadStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/status`);
      const data = await res.json();
      setStatus(data.status as AgentStatus);
      if (data.current?.cli) setActiveCli(data.current.cli);
    } catch {
      // 서버 미실행 시 무시
    }
  };

  const loadHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agent/runs`);
      const data = await res.json();
      setHistory(data as AgentRun[]);
    } catch {
      // 무시
    }
  };

  const handleRun = async () => {
    const task = taskInput.trim();
    if (!task || status === 'running') return;

    // 출력 초기화
    setOutputLines([]);
    setStatus('running');
    setActiveCli(selectedCli === 'auto' ? '분석 중...' : selectedCli);

    try {
      const res = await fetch(`${API_BASE}/api/agent/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, cli: selectedCli }),
      });
      const data = await res.json();

      if (data.error) {
        setStatus('error');
        setOutputLines([{
          text: `[오류] ${data.error}`,
          ts: new Date().toISOString(),
          type: 'error',
        }]);
      } else {
        setActiveCli(data.cli || selectedCli);
      }
    } catch (e) {
      setStatus('error');
      setOutputLines([{
        text: `[오류] 서버 연결 실패`,
        ts: new Date().toISOString(),
        type: 'error',
      }]);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/api/agent/stop`, { method: 'POST' });
      setStatus('idle');
    } catch {
      // 무시
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter로 실행
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      handleRun();
    }
  };

  // ─── 출력 줄 색상 결정 ──────────────────────────────────────────────────
  const getLineColor = (line: OutputLine): string => {
    if (line.type === 'error') return 'text-red-400';
    if (line.type === 'started') return 'text-yellow-400';
    if (line.type === 'done') return 'text-green-400';
    if (line.type === 'stopped') return 'text-orange-400';
    // 일반 출력: Claude 관련은 보라색, 그 외 초록색
    if (line.text.startsWith('[오류]') || line.text.startsWith('Error')) return 'text-red-400';
    if (line.text.startsWith('✓') || line.text.includes('완료')) return 'text-green-400';
    return 'text-green-300/80';
  };

  return (
    <div className="flex flex-col h-full gap-2 overflow-hidden text-[11px]">

      {/* ── 헤더 ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between shrink-0 px-1">
        <div className="flex items-center gap-1.5 text-[11px] font-bold text-primary uppercase tracking-tighter">
          <Bot className="w-3.5 h-3.5" />
          Autonomous Agent
        </div>
        {/* 상태 배지 */}
        <div className={`flex items-center gap-1 ${STATUS_COLORS[status]}`}>
          {status === 'running' && (
            <div className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
          )}
          <span>{STATUS_LABELS[status]}</span>
          {activeCli && status === 'running' && (
            <span className="text-white/30 ml-1">({activeCli})</span>
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

        {/* ── 컨트롤 바 ──────────────────────────────────────────────── */}
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

          {/* 중단 버튼 */}
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

          {/* 실행 버튼 */}
          <button
            onClick={handleRun}
            disabled={status === 'running' || !taskInput.trim()}
            className="flex items-center gap-1 px-3 py-1 rounded bg-primary/80 hover:bg-primary
                       text-white font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {status === 'running' ? (
              <div className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
            ) : (
              <Play className="w-3 h-3" />
            )}
            실행
          </button>
        </div>
      </div>

      {/* ── 실시간 출력 영역 ────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col bg-black/40 rounded border border-white/5 overflow-hidden min-h-0">
        <div className="flex items-center justify-between px-2 py-1 border-b border-white/5 shrink-0">
          <span className="text-white/30 font-mono">실시간 출력</span>
          <button
            onClick={() => setOutputLines([])}
            className="text-white/20 hover:text-white/50 transition"
            title="출력 초기화"
          >
            <RotateCw className="w-3 h-3" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed">
          {outputLines.length === 0 ? (
            <div className="text-white/15 italic">
              실행 결과가 여기에 표시됩니다...
            </div>
          ) : (
            outputLines.map((line, i) => (
              <div key={i} className={`${getLineColor(line)} whitespace-pre-wrap break-all`}>
                {line.text}
              </div>
            ))
          )}
          <div ref={outputEndRef} />
        </div>
      </div>

      {/* ── 실행 히스토리 ────────────────────────────────────────────────── */}
      <div className="shrink-0 bg-black/20 rounded border border-white/5 overflow-hidden">
        <button
          onClick={() => { setShowHistory(v => !v); if (!showHistory) loadHistory(); }}
          className="w-full flex items-center justify-between px-2 py-1.5
                     text-white/40 hover:text-white/60 transition"
        >
          <div className="flex items-center gap-1.5">
            <Clock className="w-3 h-3" />
            <span>실행 히스토리</span>
            {history.length > 0 && (
              <span className="bg-white/10 rounded px-1">{history.length}</span>
            )}
          </div>
          {showHistory ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>

        {showHistory && (
          <div className="border-t border-white/5 max-h-[120px] overflow-y-auto">
            {history.length === 0 ? (
              <div className="px-2 py-2 text-white/20 italic">실행 기록 없음</div>
            ) : (
              history.map(run => (
                <button
                  key={run.id}
                  onClick={() => setTaskInput(run.task)}
                  className="w-full text-left px-2 py-1.5 hover:bg-white/5 transition
                             border-b border-white/5 last:border-0"
                >
                  <div className="flex items-center gap-1.5">
                    {/* 상태 표시 */}
                    <span className={
                      run.status === 'done' ? 'text-green-400' :
                      run.status === 'error' ? 'text-red-400' : 'text-orange-400'
                    }>
                      {run.status === 'done' ? '✓' : run.status === 'error' ? '✗' : '■'}
                    </span>
                    {/* CLI 배지 */}
                    <span className={`px-1 rounded text-[9px] ${
                      run.cli === 'claude' ? 'bg-purple-500/20 text-purple-300' :
                      'bg-blue-500/20 text-blue-300'
                    }`}>
                      {run.cli}
                    </span>
                    {/* 지시 내용 (앞 40자) */}
                    <span className="text-white/60 truncate flex-1">
                      {run.task.slice(0, 40)}{run.task.length > 40 ? '...' : ''}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
