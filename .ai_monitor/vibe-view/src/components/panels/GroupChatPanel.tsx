import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, RefreshCw, Send, Users } from 'lucide-react';
import { API_BASE } from '../../constants';

type TerminalId = 'T1' | 'T2' | 'T3' | 'T4';
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

const TERMINALS: TerminalId[] = ['T1', 'T2', 'T3', 'T4'];

const TERMINAL_ACCENT: Record<TerminalId, string> = {
  T1: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100',
  T2: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
  T3: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
  T4: 'border-rose-500/30 bg-rose-500/10 text-rose-100',
};

const TERMINAL_BADGE: Record<TerminalId, string> = {
  T1: 'bg-cyan-500/15 text-cyan-300',
  T2: 'bg-emerald-500/15 text-emerald-300',
  T3: 'bg-amber-500/15 text-amber-300',
  T4: 'bg-rose-500/15 text-rose-300',
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
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-[#1b1b1d]">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-[#252526] px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 text-cyan-300">
            <Users className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white">Internal Group Chat</div>
            <div className="text-[11px] text-white/40">Merged room for T1-T4 agent sessions</div>
          </div>
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
