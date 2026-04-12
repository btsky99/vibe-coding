/**
 * ------------------------------------------------------------------------
 * FILE: OfficeChatPanel.tsx
 * DESCRIPTION: 오피스 모드 채팅 패널 — PTY 직통 통신.
 *              클래식 메시지 시스템(pg_messages)을 사용하지 않고
 *              PTY 서버와 직접 통신하여 에이전트와 대화한다.
 * REVISION HISTORY:
 * - 2026-04-11 Claude: PTY 직통 통신으로 전면 재작성 (클래식 분리)
 * - 2026-04-08 Claude: 3모드 채팅 패널로 재설계 (1:1, 회의실, 전체)
 * ------------------------------------------------------------------------
 */

import { useEffect, useRef, useState } from 'react';
import { Send, Terminal, Trash2 } from 'lucide-react';
import type { PtyChatMessage } from '../../hooks/useOfficePty';

const AGENT_COLORS: Record<string, string> = {
  claude: '#a78bfa',
  gemini: '#34d399',
  codex: '#22d3ee',
};

interface OfficeChatPanelProps {
  chatMessages: PtyChatMessage[];
  selectedAgent: string;
  selectedSlotName: string;
  terminalId: string | null;
  terminalRunning: boolean;
  terminalReady: boolean;
  sendError: string | null;
  onSendMessage: (text: string) => void;
  onClearChat: () => void;
}

export default function OfficeChatPanel({
  chatMessages,
  selectedAgent,
  selectedSlotName,
  terminalId,
  terminalRunning,
  terminalReady,
  sendError,
  onSendMessage,
  onClearChat,
}: OfficeChatPanelProps) {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const agentColor = AGENT_COLORS[selectedAgent] || '#94a3b8';

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages.length]);

  const canSend = terminalRunning && terminalReady;
  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || !terminalId || !canSend) return;
    onSendMessage(trimmed);
    setInput('');
  };

  return (
    <div className="flex h-full flex-col">
      {/* 헤더 — 연결된 터미널 표시 */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-white/[0.06] bg-[#080d15] px-3">
        <div className="flex items-center gap-2">
          <Terminal className="h-3 w-3 text-white/30" />
          <div className="h-2 w-2 rounded-full" style={{
            backgroundColor: terminalRunning ? '#4ade80' : '#ef4444',
            boxShadow: terminalRunning ? '0 0 6px rgba(74,222,128,0.5)' : 'none',
          }} />
          <span className="text-[10px] font-bold text-white/60">
            {selectedSlotName}
          </span>
          {terminalId && (
            <span className="text-[8px] text-white/20">{terminalId}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: agentColor }} />
          <span className="text-[9px] text-white/40">{selectedAgent}</span>
          {chatMessages.length > 0 && (
            <button
              onClick={onClearChat}
              className="ml-2 rounded p-1 text-white/15 hover:text-white/40 transition"
              title="채팅 초기화"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* 메시지 영역 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {chatMessages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-3 h-10 w-10 rounded-full border border-white/[0.06] bg-white/[0.02] flex items-center justify-center">
                <Terminal className="h-4 w-4 text-white/15" />
              </div>
              <div className="text-[10px] text-white/25">
                {terminalRunning
                  ? `${selectedSlotName}에게 메시지를 보내봐`
                  : `${selectedSlotName} 터미널이 꺼져 있어`}
              </div>
              {!terminalRunning && (
                <div className="mt-1 text-[9px] text-white/15">
                  클래식 모드에서 에이전트를 먼저 시작해봐
                </div>
              )}
            </div>
          </div>
        ) : (
          chatMessages.map((msg, i) => {
            const isFromUser = msg.from === 'user';
            const senderColor = isFromUser ? '#60a5fa' : (AGENT_COLORS[msg.from] || agentColor);
            const senderName = isFromUser ? '나' : msg.from;

            return (
              <div key={msg.id || `${msg.timestamp}-${i}`} className={`flex ${isFromUser ? 'justify-end' : 'justify-start'} gap-2`}>
                {/* 에이전트 아바타 */}
                {!isFromUser && (
                  <div
                    className="mt-5 h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-[8px] font-black text-white/80"
                    style={{ backgroundColor: `${senderColor}25`, border: `1.5px solid ${senderColor}55` }}
                  >
                    {senderName[0]?.toUpperCase()}
                  </div>
                )}
                <div className="max-w-[85%]">
                  {/* 이름 + 시간 */}
                  <div className={`mb-0.5 flex items-center gap-2 text-[8px] ${isFromUser ? 'justify-end' : ''}`}>
                    <span className="font-bold" style={{ color: `${senderColor}bb` }}>{senderName}</span>
                    <span className="text-white/15">
                      {new Date(msg.timestamp).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  {/* 말풍선 */}
                  <div
                    className={`rounded-2xl px-3.5 py-2 text-[11px] leading-relaxed ${
                      isFromUser
                        ? 'rounded-tr-sm bg-cyan-500/12 border border-cyan-500/15 text-cyan-50/90'
                        : 'rounded-tl-sm bg-white/[0.04] border border-white/[0.06] text-white/75 font-mono'
                    }`}
                  >
                    {msg.content}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 전송 에러 배너 */}
      {sendError && (
        <div className="shrink-0 border-t border-red-500/20 bg-red-500/8 px-4 py-2 text-[10px] text-red-300">
          {sendError}
        </div>
      )}

      {/* 입력창 */}
      <div className="shrink-0 border-t border-white/[0.06] bg-[#080d15] p-3">
        <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2.5 focus-within:border-cyan-500/25 transition-colors">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }}}
            placeholder={!terminalRunning ? '터미널이 꺼져 있어' : !terminalReady ? '에이전트 부팅 중...' : `${selectedSlotName}에게...`}
            disabled={!canSend}
            className="flex-1 bg-transparent text-xs text-white/80 outline-none placeholder:text-white/18 disabled:opacity-30"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || !canSend}
            className="rounded-lg bg-cyan-500/15 p-2 text-cyan-400 transition hover:bg-cyan-500/25 disabled:opacity-20 disabled:cursor-not-allowed"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
