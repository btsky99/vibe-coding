/**
 * ------------------------------------------------------------------------
 * 📄 파일명: ChatSlot.tsx
 * 📝 설명: cokacdir 패턴 채팅 UI 컴포넌트.
 *          메신저 스타일 말풍선으로 에이전트와 대화합니다.
 *          에이전트(Claude/Antigravity/Codex) + 모드(일반/YOLO) + 역할(오케스트레이션/프론트/백엔드) 선택.
 *          /api/agent/chat SSE로 실시간 스트리밍 수신.
 *          텔레그램과 동일한 백엔드를 공유하여 같은 세션 컨텍스트 유지.
 * REVISION HISTORY:
 * - 2026-03-25 Claude: 우클릭 컨텍스트 메뉴 추가 — 복사/붙여넣기 (pywebview 환경 지원)
 * - 2026-03-24 Claude: 최초 생성 — cokacdir 패턴 채팅 UI
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Square, RotateCw, Cpu, Terminal, Code2, Zap,
  ChevronDown, Wrench, Layout, Server, Brain, MessageCircle
} from 'lucide-react';
import { API_BASE } from '../constants';

// ── 타입 정의 ──

/** 채팅 메시지 — source 필드로 대시보드/텔레그램 발신 구분 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  ts: string;
  toolName?: string;  // tool_use일 때 도구 이름
  source?: 'dashboard' | 'telegram';  // 메시지 발신 채널
  tgUser?: string;  // 텔레그램 사용자 이름 (source=="telegram"일 때)
}

/** 역할(포커스) 옵션 — 사용자가 터미널마다 선택 */
type AgentRole = 'orchestration' | 'frontend' | 'backend' | 'general';
const ROLE_OPTIONS: { key: AgentRole; label: string; icon: typeof Brain; color: string; desc: string }[] = [
  { key: 'general',       label: '일반',         icon: MessageCircle, color: 'text-blue-400',   desc: '범용 대화' },
  { key: 'orchestration', label: '오케스트레이션', icon: Brain,         color: 'text-purple-400', desc: '태스크 분배·관리' },
  { key: 'frontend',      label: '프론트엔드',    icon: Layout,        color: 'text-cyan-400',   desc: 'UI·React·CSS' },
  { key: 'backend',       label: '백엔드',        icon: Server,        color: 'text-green-400',  desc: 'API·DB·서버' },
];

/** CLI 에이전트 옵션 */
type AgentCli = 'claude' | 'antigravity' | 'codex';
const CLI_OPTIONS: { key: AgentCli; label: string; icon: typeof Cpu; color: string }[] = [
  { key: 'claude', label: 'Claude', icon: Cpu,      color: 'text-emerald-400' },
  { key: 'antigravity', label: 'Antigravity', icon: Terminal,  color: 'text-orange-400' },
  { key: 'codex',  label: 'Codex',  icon: Code2,    color: 'text-amber-400' },
];

interface ChatSlotProps {
  slotId: number;
  currentPath: string;
  /** 터미널 모드로 전환하는 콜백 */
  onSwitchToTerminal?: () => void;
}

export default function ChatSlot({ slotId, currentPath, onSwitchToTerminal }: ChatSlotProps) {
  const terminalId = `T${slotId + 1}`;

  // ── 설정 상태 (localStorage 지속) ──
  const [cli, setCli] = useState<AgentCli>(() => {
    return (localStorage.getItem(`chat_cli_${terminalId}`) as AgentCli) || 'claude';
  });
  const [yolo, setYolo] = useState<boolean>(() => {
    return localStorage.getItem(`chat_yolo_${terminalId}`) === 'true';
  });
  const [role, setRole] = useState<AgentRole>(() => {
    return (localStorage.getItem(`chat_role_${terminalId}`) as AgentRole) || 'general';
  });

  // ── 채팅 상태 ──
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [showCliMenu, setShowCliMenu] = useState(false);
  const [showRoleMenu, setShowRoleMenu] = useState(false);

  // ── 우클릭 컨텍스트 메뉴 상태 (pywebview에서 브라우저 기본 메뉴 차단되므로 커스텀 구현) ──
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; hasSelection: boolean } | null>(null);

  // ── refs ──
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 컨텍스트 메뉴 바깥 클릭 시 닫기
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [ctxMenu]);

  // 클립보드 복사 헬퍼 — navigator.clipboard API 실패 시 execCommand 폴백
  const copyToClipboard = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
  }, []);

  // localStorage 동기화
  useEffect(() => { localStorage.setItem(`chat_cli_${terminalId}`, cli); }, [cli, terminalId]);
  useEffect(() => { localStorage.setItem(`chat_yolo_${terminalId}`, String(yolo)); }, [yolo, terminalId]);
  useEffect(() => { localStorage.setItem(`chat_role_${terminalId}`, role); }, [role, terminalId]);

  // 자동 스크롤
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 히스토리 로드 (마운트 시)
  useEffect(() => {
    fetch(`${API_BASE}/api/agent/chat/history?terminal_id=${terminalId}`)
      .then(r => r.json())
      .then(data => {
        if (data.history?.length) {
          setMessages(data.history.map((m: any, i: number) => ({
            id: `hist-${i}`,
            role: m.role,
            content: m.content,
            ts: m.ts,
          })));
        }
        if (data.session_id) setSessionId(data.session_id);
        if (data.cli) setCli(data.cli as AgentCli);
      })
      .catch(() => {});
  }, [terminalId]);

  // ── 메시지 버스 폴링 (텔레그램 ↔ 대시보드 양방향 동기화) ──
  // 2초 간격으로 /api/agent/chat/feed 폴링, 텔레그램발 메시지를 채팅에 표시
  const busSeqRef = useRef(0);
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/agent/chat/feed?terminal_id=${terminalId}&since=${busSeqRef.current}`
        );
        const data = await resp.json();
        if (data.latest_seq > busSeqRef.current) {
          busSeqRef.current = data.latest_seq;
        }
        if (data.messages?.length) {
          // 텔레그램발 메시지만 추가 (대시보드 발신은 이미 로컬에 있음)
          const telegramMsgs: ChatMessage[] = data.messages
            .filter((m: any) => m.source === 'telegram')
            .map((m: any) => ({
              id: `tg-${m.seq}`,
              role: m.role as ChatMessage['role'],
              content: m.content,
              ts: m.ts,
              source: 'telegram' as const,
              tgUser: m.tg_user,
            }));
          if (telegramMsgs.length > 0) {
            setMessages(prev => {
              // seq 기반 중복 방지
              const existingIds = new Set(prev.map(m => m.id));
              const newOnes = telegramMsgs.filter(m => !existingIds.has(m.id));
              return newOnes.length > 0 ? [...prev, ...newOnes] : prev;
            });
          }
        }
      } catch {
        // 네트워크 오류 무시 — 다음 폴링에서 재시도
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [terminalId]);

  // ── 역할별 시스템 프롬프트 접두사 ──
  const getRolePrefix = useCallback(() => {
    switch (role) {
      case 'orchestration':
        return '[역할: 오케스트레이션] 태스크 분배와 에이전트 관리에 집중하세요. /vibe-orchestrate\n\n';
      case 'frontend':
        return '[역할: 프론트엔드] React/TypeScript/CSS UI 작업에 집중하세요.\n\n';
      case 'backend':
        return '[역할: 백엔드] Python/API/DB/서버 작업에 집중하세요.\n\n';
      default:
        return '';
    }
  }, [role]);

  // ── 메시지 전송 ──
  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    if (!text || isStreaming) return;

    const fullMessage = getRolePrefix() + text;

    // 사용자 메시지 추가
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      ts: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    setIsStreaming(true);

    // 어시스턴트 플레이스홀더
    const assistantId = `assistant-${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      ts: new Date().toISOString(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    // SSE 연결
    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const resp = await fetch(`${API_BASE}/api/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          terminal_id: terminalId,
          message: fullMessage,
          cli,
          yolo,
        }),
        signal: abort.signal,
      });

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));

              if (evt.type === 'text') {
                setMessages(prev => prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: m.content + evt.content }
                    : m
                ));
              } else if (evt.type === 'tool_use') {
                const toolMsg: ChatMessage = {
                  id: `tool-${Date.now()}-${Math.random()}`,
                  role: 'tool',
                  content: evt.input || '',
                  ts: new Date().toISOString(),
                  toolName: evt.name,
                };
                setMessages(prev => [...prev, toolMsg]);
              } else if (evt.type === 'session') {
                setSessionId(evt.session_id);
              } else if (evt.type === 'done') {
                if (evt.session_id) setSessionId(evt.session_id);
              } else if (evt.type === 'error') {
                setMessages(prev => prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: m.content + `\n\n⚠️ 오류: ${evt.message}`, role: 'system' as const }
                    : m
                ));
              }
            } catch {}
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, content: `⚠️ 연결 오류: ${err.message}` }
            : m
        ));
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [inputValue, isStreaming, cli, yolo, terminalId, getRolePrefix]);

  // ── 중지 ──
  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    fetch(`${API_BASE}/api/agent/chat/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ terminal_id: terminalId }),
    }).catch(() => {});
    setIsStreaming(false);
  }, [terminalId]);

  // ── 세션 리셋 ──
  const handleReset = useCallback(() => {
    handleStop();
    setMessages([]);
    setSessionId(null);
  }, [handleStop]);

  // ── 키보드 핸들링 ──
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── 현재 CLI/역할 정보 ──
  const currentCli = CLI_OPTIONS.find(c => c.key === cli) ?? CLI_OPTIONS[0];
  const currentRole = ROLE_OPTIONS.find(r => r.key === role) ?? ROLE_OPTIONS[0];

  return (
    <div className="flex-1 flex flex-col bg-[#1e1e1e] h-full overflow-hidden">

      {/* ── 헤더: 에이전트 + 역할 + 모드 선택 ── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#252526] border-b border-white/10 shrink-0">

        {/* 터미널 ID */}
        <span className="text-xs font-black text-white/40">{terminalId}</span>

        {/* CLI 에이전트 선택 드롭다운 */}
        <div className="relative">
          <button
            onClick={() => { setShowCliMenu(!showCliMenu); setShowRoleMenu(false); }}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-bold border transition-all ${currentCli.color} border-white/10 hover:border-white/20 bg-white/5`}
          >
            <currentCli.icon className="w-3.5 h-3.5" />
            {currentCli.label}
            <ChevronDown className="w-3 h-3 opacity-50" />
          </button>
          <AnimatePresence>
            {showCliMenu && (
              <motion.div
                initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }}
                className="absolute top-full left-0 mt-1 bg-[#2d2d2d] border border-white/10 rounded-lg shadow-xl z-50 min-w-[140px]"
              >
                {CLI_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    onClick={() => { setCli(opt.key); setShowCliMenu(false); }}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-white/10 transition-colors ${cli === opt.key ? 'bg-white/5 font-bold' : ''} ${opt.color}`}
                  >
                    <opt.icon className="w-3.5 h-3.5" /> {opt.label}
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* 역할 선택 드롭다운 */}
        <div className="relative">
          <button
            onClick={() => { setShowRoleMenu(!showRoleMenu); setShowCliMenu(false); }}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-bold border transition-all ${currentRole.color} border-white/10 hover:border-white/20 bg-white/5`}
          >
            <currentRole.icon className="w-3.5 h-3.5" />
            {currentRole.label}
            <ChevronDown className="w-3 h-3 opacity-50" />
          </button>
          <AnimatePresence>
            {showRoleMenu && (
              <motion.div
                initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }}
                className="absolute top-full left-0 mt-1 bg-[#2d2d2d] border border-white/10 rounded-lg shadow-xl z-50 min-w-[180px]"
              >
                {ROLE_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    onClick={() => { setRole(opt.key); setShowRoleMenu(false); }}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-white/10 transition-colors ${role === opt.key ? 'bg-white/5 font-bold' : ''}`}
                  >
                    <opt.icon className={`w-3.5 h-3.5 ${opt.color}`} />
                    <div className="text-left">
                      <div className={opt.color}>{opt.label}</div>
                      <div className="text-[10px] text-white/30">{opt.desc}</div>
                    </div>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* YOLO 토글 */}
        <button
          onClick={() => setYolo(!yolo)}
          className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-black border transition-all ${
            yolo
              ? 'bg-red-500/20 border-red-500/50 text-red-400'
              : 'bg-white/5 border-white/10 text-white/40 hover:text-white/60'
          }`}
        >
          <Zap className={`w-3 h-3 ${yolo ? 'fill-current' : ''}`} />
          {yolo ? 'YOLO' : '일반'}
        </button>

        {/* 세션 ID 표시 */}
        {sessionId && (
          <span className="text-[10px] text-white/20 ml-auto font-mono truncate max-w-[80px]" title={sessionId}>
            {sessionId.slice(0, 8)}...
          </span>
        )}

        {/* 터미널 전환 버튼 */}
        {onSwitchToTerminal && (
          <button
            onClick={onSwitchToTerminal}
            className="ml-auto flex items-center gap-1 px-2 py-1 rounded text-[10px] text-white/40 hover:text-white/70 hover:bg-white/5 transition-colors"
            title="PTY 터미널로 전환"
          >
            <Terminal className="w-3 h-3" /> 터미널
          </button>
        )}
      </div>

      {/* ── 채팅 영역 — select-text로 텍스트 드래그/복사 허용 + 우클릭 커스텀 메뉴 ── */}
      <div
        className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar select-text relative"
        onClick={() => { setShowCliMenu(false); setShowRoleMenu(false); }}
        onContextMenu={(e) => {
          e.preventDefault();
          const selection = window.getSelection();
          const hasSelection = !!(selection && selection.toString().trim());
          setCtxMenu({ x: e.clientX, y: e.clientY, hasSelection });
        }}
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-white/20 gap-3">
            <currentCli.icon className={`w-12 h-12 ${currentCli.color} opacity-30`} />
            <p className="text-sm font-bold">{currentCli.label} — {currentRole.label} 모드</p>
            <p className="text-xs">메시지를 보내 대화를 시작하세요</p>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className={`flex ${
            msg.source === 'telegram' ? 'justify-start' :
            msg.role === 'user' ? 'justify-end' : 'justify-start'
          }`}>
            {/* 도구 사용 표시 */}
            {msg.role === 'tool' ? (
              <div className="max-w-[85%] px-3 py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-[11px]">
                <div className="flex items-center gap-1 text-yellow-400 font-bold mb-0.5">
                  <Wrench className="w-3 h-3" /> {msg.toolName}
                </div>
                <div className="text-white/40 font-mono truncate">{msg.content.slice(0, 100)}</div>
              </div>
            ) : msg.source === 'telegram' && msg.role === 'user' ? (
              /* 텔레그램발 사용자 메시지 (왼쪽, 보라색 말풍선 + ✈️) */
              <div className="max-w-[75%] px-3 py-2 rounded-2xl rounded-bl-sm bg-purple-600/30 border border-purple-500/30 text-purple-100 text-sm whitespace-pre-wrap break-words">
                <div className="flex items-center gap-1 text-[10px] text-purple-300 mb-1 font-bold">
                  <span>✈️</span> {msg.tgUser || 'Telegram'}
                </div>
                {msg.content}
              </div>
            ) : msg.source === 'telegram' && msg.role === 'assistant' ? (
              /* 텔레그램발 에이전트 응답 (왼쪽, 어두운 말풍선 + ✈️ 뱃지) */
              <div className="max-w-[85%] px-3 py-2 rounded-2xl rounded-bl-sm bg-[#2d2d2d] border border-purple-500/20 text-[#d4d4d4] text-sm whitespace-pre-wrap break-words font-mono">
                <div className="flex items-center gap-1 text-[10px] text-purple-300 mb-1">
                  <span>✈️</span> 텔레그램 응답
                </div>
                {msg.content}
              </div>
            ) : msg.role === 'user' ? (
              /* 대시보드 사용자 메시지 (오른쪽, 파란 말풍선) */
              <div className="max-w-[75%] px-3 py-2 rounded-2xl rounded-br-sm bg-blue-600/80 text-white text-sm whitespace-pre-wrap break-words">
                {msg.content}
              </div>
            ) : (
              /* 대시보드 에이전트 응답 (왼쪽, 어두운 말풍선) */
              <div className="max-w-[85%] px-3 py-2 rounded-2xl rounded-bl-sm bg-[#2d2d2d] border border-white/5 text-[#d4d4d4] text-sm whitespace-pre-wrap break-words font-mono">
                {msg.content || (isStreaming ? (
                  <span className="inline-flex items-center gap-1 text-white/30">
                    <span className="animate-pulse">●</span> 생각 중...
                  </span>
                ) : null)}
              </div>
            )}
          </div>
        ))}
        <div ref={chatEndRef} />

        {/* 우클릭 컨텍스트 메뉴 — 복사(선택 있을 때) / 붙여넣기(입력창에 삽입) */}
        {ctxMenu && (
          <div
            className="fixed z-[9999] bg-[#2d2d2d] border border-white/20 rounded shadow-xl text-xs text-white min-w-[120px] py-1"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
            onMouseLeave={() => setCtxMenu(null)}
          >
            {ctxMenu.hasSelection && (
              <button
                className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
                onClick={async () => {
                  const sel = window.getSelection()?.toString() || '';
                  if (sel) await copyToClipboard(sel);
                  setCtxMenu(null);
                }}
              >
                복사
              </button>
            )}
            <button
              className="w-full text-left px-4 py-1.5 hover:bg-white/10 transition-colors"
              onClick={async () => {
                try {
                  const text = await navigator.clipboard.readText();
                  if (text && inputRef.current) {
                    // 입력창에 붙여넣기 — 현재 커서 위치에 삽입
                    const start = inputRef.current.selectionStart;
                    const end = inputRef.current.selectionEnd;
                    const current = inputValue;
                    const newValue = current.slice(0, start) + text + current.slice(end);
                    setInputValue(newValue);
                    // 포커스 및 커서 위치 복원
                    requestAnimationFrame(() => {
                      if (inputRef.current) {
                        inputRef.current.focus();
                        const pos = start + text.length;
                        inputRef.current.setSelectionRange(pos, pos);
                      }
                    });
                  }
                } catch (err) { console.error('붙여넣기 실패:', err); }
                setCtxMenu(null);
              }}
            >
              붙여넣기
            </button>
          </div>
        )}
      </div>

      {/* ── 입력 영역 ── */}
      <div className="border-t border-white/10 bg-[#252526] p-3 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`${currentCli.label}에게 메시지 보내기... (${currentRole.label})`}
            className="flex-1 bg-[#1e1e1e] border border-white/10 rounded-xl px-3 py-2 text-sm text-white placeholder-white/20 resize-none focus:outline-none focus:border-white/20 min-h-[40px] max-h-[120px]"
            rows={1}
            disabled={isStreaming}
          />

          {isStreaming ? (
            <button
              onClick={handleStop}
              className="px-3 py-2 bg-red-500/80 hover:bg-red-500 text-white rounded-xl transition-colors"
              title="중지"
            >
              <Square className="w-4 h-4 fill-current" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!inputValue.trim()}
              className="px-3 py-2 bg-blue-600/80 hover:bg-blue-600 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-xl transition-colors"
              title="전송"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* 하단 액션 버튼 */}
        <div className="flex items-center gap-2 mt-2">
          <button
            onClick={handleReset}
            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors"
          >
            <RotateCw className="w-3 h-3" /> 리셋
          </button>
          <span className="text-[10px] text-white/15">
            {messages.filter(m => m.role === 'user').length}턴
            {isStreaming && ' · 스트리밍 중...'}
          </span>
        </div>
      </div>
    </div>
  );
}
