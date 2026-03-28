import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, Copy, Radio, RefreshCw, Send, Users, Wifi, WifiOff } from 'lucide-react';
import { API_BASE } from '../../constants';

// ── WebSocket 실시간 채팅 탭 ──

interface WsChatMessage {
  type: 'message' | 'join' | 'leave' | 'system';
  sender: string;
  content: string;
  room: string;
  timestamp: string;
}

// WebSocket 서버 주소 — 127.0.0.1 사용 (localhost DNS 해석 지연/실패 방지)
const WS_URL = 'ws://127.0.0.1:8765';

function LiveChatTab() {
  const [messages, setMessages] = useState<WsChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [nickname, setNickname] = useState('dashboard');
  const [connected, setConnected] = useState(false);
  const [statusText, setStatusText] = useState('연결 대기 중...');
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const reconnectTimer = useRef<number | null>(null);
  const nicknameRef = useRef(nickname);
  nicknameRef.current = nickname;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    // 이전 연결 정리
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    setStatusText('연결 중...');

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setStatusText('연결됨');
        // 입장 메시지 전송
        const joinMsg: WsChatMessage = {
          type: 'join',
          sender: nicknameRef.current,
          content: '',
          room: 'default',
          timestamp: new Date().toISOString(),
        };
        ws.send(JSON.stringify(joinMsg));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WsChatMessage;
          setMessages((prev) => [...prev.slice(-500), msg]);
        } catch {
          // 파싱 실패 무시
        }
      };

      ws.onclose = () => {
        setConnected(false);
        setStatusText('연결 끊김 — 3초 후 재시도');
        // 3초 후 재연결 시도
        reconnectTimer.current = window.setTimeout(() => connect(), 3000);
      };

      ws.onerror = () => {
        setStatusText('연결 실패');
        ws.close();
      };
    } catch {
      setConnected(false);
      setStatusText('WebSocket 생성 실패');
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(() => {
    const content = inputValue.trim();
    if (!content || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const msg: WsChatMessage = {
      type: 'message',
      sender: nicknameRef.current,
      content,
      room: 'default',
      timestamp: new Date().toISOString(),
    };
    wsRef.current.send(JSON.stringify(msg));

    // 자기 메시지도 로컬에 표시 (서버는 sender에게 에코하지 않으므로)
    setMessages((prev) => [...prev.slice(-500), msg]);
    setInputValue('');
  }, [inputValue]);

  const formatTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return '';
    }
  };

  const senderColor = (sender: string): string => {
    const colors = [
      'text-cyan-300', 'text-emerald-300', 'text-amber-300', 'text-rose-300',
      'text-violet-300', 'text-pink-300', 'text-teal-300', 'text-orange-300',
    ];
    let hash = 0;
    for (let i = 0; i < sender.length; i++) hash = (hash * 31 + sender.charCodeAt(i)) | 0;
    return colors[Math.abs(hash) % colors.length];
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 상태 바 + 닉네임 설정 */}
      <div className="flex items-center gap-2 border-b border-white/5 px-3 py-2 text-[11px]">
        {connected ? (
          <Wifi className="h-3.5 w-3.5 text-emerald-400" />
        ) : (
          <WifiOff className="h-3.5 w-3.5 text-red-400" />
        )}
        <span className={connected ? 'text-emerald-300' : 'text-red-300'}>
          {statusText}
        </span>
        <span className="text-white/20">|</span>
        <label className="text-white/40">닉네임</label>
        <input
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          className="w-24 rounded border border-white/10 bg-[#202124] px-2 py-0.5 text-[11px] text-white outline-none"
          disabled={connected}
        />
        {!connected && (
          <button
            onClick={connect}
            className="rounded border border-white/10 px-2 py-0.5 text-white/60 hover:bg-white/5"
          >
            재연결
          </button>
        )}
      </div>

      {/* 메시지 목록 */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {messages.length === 0 && (
          <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 text-center text-white/30">
            <Radio className="h-8 w-8" />
            <div className="text-sm font-semibold text-white/50">실시간 그룹 채팅</div>
            <div className="text-xs">오른쪽 터미널에서 에이전트를 실행하고, 여기서 실시간 대화하세요</div>
            <div className="mt-1 rounded bg-white/5 px-2 py-1 text-[10px] font-mono text-white/30">python -m llm_group_chat join --name gemini</div>
          </div>
        )}

        <div className="space-y-1">
          {messages.map((msg, i) => {
            if (msg.type === 'system') {
              return (
                <div key={i} className="text-center text-[11px] text-white/30">
                  ** {msg.content} **
                </div>
              );
            }
            if (msg.type === 'join') {
              return (
                <div key={i} className="text-center text-[11px] text-emerald-400/50">
                  &gt;&gt; {msg.sender} 입장
                </div>
              );
            }
            if (msg.type === 'leave') {
              return (
                <div key={i} className="text-center text-[11px] text-red-400/50">
                  &lt;&lt; {msg.sender} 퇴장
                </div>
              );
            }
            const isMe = msg.sender === nickname;
            return (
              <div key={i} className={`group/msg flex ${isMe ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`relative max-w-[85%] rounded-xl px-3 py-1.5 text-sm ${
                    isMe
                      ? 'bg-cyan-600/30 text-cyan-50'
                      : 'bg-white/5 text-white/90'
                  }`}
                >
                  {/* 복사 버튼 — hover 시 표시 */}
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(msg.content).then(() => {
                        const btn = document.getElementById(`copy-${i}`);
                        if (btn) { btn.dataset.copied = 'true'; setTimeout(() => { btn.dataset.copied = ''; }, 1500); }
                      });
                    }}
                    id={`copy-${i}`}
                    className="absolute -top-1 right-1 hidden group-hover/msg:flex items-center gap-0.5 rounded bg-white/10 px-1.5 py-0.5 text-[9px] text-white/50 hover:bg-white/20 hover:text-white/80 transition-colors data-[copied=true]:text-emerald-400"
                    title="복사"
                  >
                    <Copy className="h-2.5 w-2.5" />
                  </button>
                  {!isMe && (
                    <div className={`text-[10px] font-semibold ${senderColor(msg.sender)}`}>
                      {msg.sender}
                    </div>
                  )}
                  <div className="whitespace-pre-wrap break-words leading-5 select-text cursor-text">{msg.content}</div>
                  <div className="mt-0.5 text-right text-[9px] text-white/20">{formatTime(msg.timestamp)}</div>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* 입력 */}
      <div className="border-t border-white/10 bg-[#202124] p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={2}
            placeholder={connected ? `메시지를 입력하세요 (${nickname})` : '서버 연결 대기 중...'}
            disabled={!connected}
            className="min-h-[52px] flex-1 resize-none rounded-xl border border-white/10 bg-[#111214] px-3 py-2 text-sm text-white outline-none placeholder:text-white/20 focus:border-cyan-500/40 disabled:opacity-40"
          />
          <button
            onClick={handleSend}
            disabled={!connected || !inputValue.trim()}
            className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-cyan-500 px-4 text-sm font-semibold text-black hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/25"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 메인 패널 (탭 전환: Internal / Live) ──

type TerminalId = 'T1' | 'T2' | 'T3' | 'T4' | 'T5' | 'T6' | 'T7' | 'T8';
type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

interface HistoryRow {
  role: MessageRole;
  content: string;
  ts: string;
}

interface HistoryResponse {
  terminal_id: string;
  cli?: string;
  history?: HistoryRow[];
  streaming?: boolean;
}

interface GroupMessage {
  id: string;
  terminalId: TerminalId;
  cli: string;
  role: MessageRole;
  content: string;
  ts: string;
  pending?: boolean;
  error?: boolean;
}

const TERMINALS: TerminalId[] = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8'];

const TERMINAL_ACCENT: Record<TerminalId, string> = {
  T1: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100',
  T2: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
  T3: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
  T4: 'border-rose-500/30 bg-rose-500/10 text-rose-100',
  T5: 'border-violet-500/30 bg-violet-500/10 text-violet-100',
  T6: 'border-pink-500/30 bg-pink-500/10 text-pink-100',
  T7: 'border-teal-500/30 bg-teal-500/10 text-teal-100',
  T8: 'border-orange-500/30 bg-orange-500/10 text-orange-100',
};

const TERMINAL_BADGE: Record<TerminalId, string> = {
  T1: 'bg-cyan-500/15 text-cyan-300',
  T2: 'bg-emerald-500/15 text-emerald-300',
  T3: 'bg-amber-500/15 text-amber-300',
  T4: 'bg-rose-500/15 text-rose-300',
  T5: 'bg-violet-500/15 text-violet-300',
  T6: 'bg-pink-500/15 text-pink-300',
  T7: 'bg-teal-500/15 text-teal-300',
  T8: 'bg-orange-500/15 text-orange-300',
};

function parseTs(ts: string): number {
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}

function normalizeCli(cli?: string): string {
  return (cli || 'agent').toUpperCase();
}

export default function GroupChatPanel() {
  const [activeTab, setActiveTab] = useState<'live' | 'internal'>('live');

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-[#1b1b1d]">
      {/* 탭 헤더 */}
      <div className="flex items-center border-b border-white/10 bg-[#252526]">
        <button
          onClick={() => setActiveTab('live')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold transition-colors ${
            activeTab === 'live'
              ? 'border-b-2 border-cyan-400 text-cyan-300'
              : 'text-white/40 hover:text-white/70'
          }`}
        >
          <Radio className="h-3.5 w-3.5" />
          실시간 채팅
        </button>
        <button
          onClick={() => setActiveTab('internal')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold transition-colors ${
            activeTab === 'internal'
              ? 'border-b-2 border-cyan-400 text-cyan-300'
              : 'text-white/40 hover:text-white/70'
          }`}
        >
          <Users className="h-3.5 w-3.5" />
          에이전트 내부
        </button>
      </div>

      {activeTab === 'live' ? <LiveChatTab /> : <InternalChatTab />}
    </div>
  );
}

function InternalChatTab() {
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [pendingMessages, setPendingMessages] = useState<GroupMessage[]>([]);
  const [targetTerminal, setTargetTerminal] = useState<TerminalId>(TERMINALS[0]);
  const [filterTerminal, setFilterTerminal] = useState<'all' | TerminalId>('all');
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadHistories = useCallback(async () => {
    try {
      const responses = await Promise.all(
        TERMINALS.map(async (terminalId) => {
          const response = await fetch(
            `${API_BASE}/api/agent/chat/history?terminal_id=${terminalId}`
          );
          if (!response.ok) {
            throw new Error(`${terminalId} history load failed`);
          }
          return response.json() as Promise<HistoryResponse>;
        })
      );

      const merged = responses
        .flatMap((response) =>
          (response.history || []).map((entry, index) => ({
            id: `hist-${response.terminal_id}-${index}-${entry.role}-${entry.ts}`,
            terminalId: response.terminal_id as TerminalId,
            cli: normalizeCli(response.cli),
            role: entry.role,
            content: entry.content,
            ts: entry.ts,
          }))
        )
        .sort((a, b) => parseTs(a.ts) - parseTs(b.ts));

      setMessages(merged);
      setLoadError(null);
    } catch (error: any) {
      setLoadError(error?.message || 'Failed to load group chat.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistories();
    const interval = window.setInterval(() => {
      void loadHistories();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadHistories]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pendingMessages, filterTerminal]);

  const visibleMessages = useMemo(() => {
    const merged = [...messages, ...pendingMessages].sort((a, b) => {
      const tsDiff = parseTs(a.ts) - parseTs(b.ts);
      return tsDiff !== 0 ? tsDiff : a.id.localeCompare(b.id);
    });

    if (filterTerminal === 'all') {
      return merged;
    }
    return merged.filter((message) => message.terminalId === filterTerminal);
  }, [filterTerminal, messages, pendingMessages]);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    void loadHistories();
  }, [loadHistories]);

  const handleSend = useCallback(async () => {
    const content = inputValue.trim();
    if (!content || isSending) return;

    const now = new Date().toISOString();
    const pendingUserId = `pending-user-${Date.now()}`;
    const pendingAssistantId = `pending-assistant-${Date.now()}`;

    setPendingMessages((prev) => [
      ...prev,
      {
        id: pendingUserId,
        terminalId: targetTerminal,
        cli: 'YOU',
        role: 'user',
        content,
        ts: now,
        pending: true,
      },
      {
        id: pendingAssistantId,
        terminalId: targetTerminal,
        cli: '...',
        role: 'assistant',
        content: '',
        ts: new Date(Date.now() + 1).toISOString(),
        pending: true,
      },
    ]);
    setInputValue('');
    setIsSending(true);
    setLoadError(null);

    try {
      const response = await fetch(`${API_BASE}/api/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          terminal_id: targetTerminal,
          message: content,
          cli: 'claude',
          yolo: false,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`${targetTerminal} send failed`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          try {
            const event = JSON.parse(raw);
            if (event.type === 'text') {
              finalText += event.content || '';
              setPendingMessages((prev) =>
                prev.map((message) =>
                  message.id === pendingAssistantId
                    ? {
                        ...message,
                        content: finalText,
                      }
                    : message
                )
              );
            } else if (event.type === 'done') {
              finalText = event.full_text || finalText;
            } else if (event.type === 'error') {
              throw new Error(event.message || 'Agent response failed');
            }
          } catch (error) {
            if (error instanceof Error) {
              throw error;
            }
          }
        }
      }

      setPendingMessages((prev) =>
        prev.filter((message) => ![pendingUserId, pendingAssistantId].includes(message.id))
      );
      await loadHistories();
    } catch (error: any) {
      setPendingMessages((prev) =>
        prev.map((message) =>
          message.id === pendingAssistantId
            ? {
                ...message,
                content: error?.message || 'Failed to send message.',
                cli: 'ERROR',
                error: true,
              }
            : message.id === pendingUserId
              ? { ...message, error: true }
              : message
        )
      );
      setLoadError(error?.message || 'Failed to send message.');
    } finally {
      setIsSending(false);
    }
  }, [inputValue, isSending, loadHistories, targetTerminal]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-[#252526] px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold text-white/60">T1-T4 Agent Sessions</div>
        </div>
        <button
          onClick={handleRefresh}
          className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-[11px] text-white/60 transition-colors hover:bg-white/5 hover:text-white"
          title="Refresh"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-white/5 px-3 py-2 text-[11px]">
        <label className="text-white/40">View</label>
        <select
          value={filterTerminal}
          onChange={(event) => setFilterTerminal(event.target.value as 'all' | TerminalId)}
          className="rounded-md border border-white/10 bg-[#202124] px-2 py-1 text-white outline-none"
        >
          <option value="all">All terminals</option>
          {TERMINALS.map((terminalId) => (
            <option key={terminalId} value={terminalId}>
              {terminalId}
            </option>
          ))}
        </select>

        <label className="ml-3 text-white/40">Send to</label>
        <select
          value={targetTerminal}
          onChange={(event) => setTargetTerminal(event.target.value as TerminalId)}
          className="rounded-md border border-white/10 bg-[#202124] px-2 py-1 text-white outline-none"
        >
          {TERMINALS.map((terminalId) => (
            <option key={terminalId} value={terminalId}>
              {terminalId}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {loadError && (
          <div className="mb-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {loadError}
          </div>
        )}

        {!isLoading && visibleMessages.length === 0 && (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 text-center text-white/30">
            <Bot className="h-10 w-10" />
            <div className="text-sm font-semibold text-white/60">No conversation yet</div>
            <div className="max-w-sm text-xs leading-5">
              Send a message to one terminal and use this room as the internal group chat view.
            </div>
          </div>
        )}

        <div className="space-y-3">
          {visibleMessages.map((message) => {
            const isUser = message.role === 'user';
            const accent = TERMINAL_ACCENT[message.terminalId];
            const badge = TERMINAL_BADGE[message.terminalId];
            return (
              <div
                key={message.id}
                className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[88%] rounded-2xl border px-3 py-2 ${
                    isUser
                      ? message.error
                        ? 'border-red-500/30 bg-red-500/10 text-red-100'
                        : 'border-blue-500/30 bg-blue-600/70 text-white'
                      : message.error
                        ? 'border-red-500/30 bg-red-500/10 text-red-100'
                        : accent
                  }`}
                >
                  <div className="mb-1 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide">
                    <span className={`rounded-full px-1.5 py-0.5 ${badge}`}>
                      {message.terminalId}
                    </span>
                    <span className="text-white/55">{message.cli}</span>
                    <span className="text-white/35">{formatTs(message.ts)}</span>
                    {message.pending && <span className="text-amber-300">pending</span>}
                  </div>
                  <div className="whitespace-pre-wrap break-words text-sm leading-6">
                    {message.content || (message.pending ? 'Waiting for response...' : '')}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-white/10 bg-[#202124] p-3">
        <div className="mb-2 text-[11px] text-white/35">
          Current target: <span className="font-semibold text-white/70">{targetTerminal}</span>
        </div>
        <div className="flex items-end gap-2">
          <textarea
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            rows={3}
            placeholder={`Send to ${targetTerminal}...`}
            className="min-h-[72px] flex-1 resize-none rounded-xl border border-white/10 bg-[#111214] px-3 py-2 text-sm text-white outline-none transition-colors placeholder:text-white/20 focus:border-cyan-500/40"
          />
          <button
            onClick={() => void handleSend()}
            disabled={isSending || !inputValue.trim()}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-cyan-500 px-4 text-sm font-semibold text-black transition-all hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/25"
          >
            <Send className="h-4 w-4" />
            {isSending ? 'Sending' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  );
}
