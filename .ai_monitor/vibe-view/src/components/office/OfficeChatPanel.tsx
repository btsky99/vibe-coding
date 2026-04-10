/**
 * ------------------------------------------------------------------------
 * FILE: OfficeChatPanel.tsx
 * DESCRIPTION: 오피스 모드 채팅 패널.
 *              3가지 모드: 1:1 개별 대화, 회의실 그룹 토론, 전체 공지.
 *              에이전트 간 메시지를 채팅 버블로 시각화한다.
 * REVISION HISTORY:
 * - 2026-04-08 Claude: 3모드 채팅 패널로 재설계 (1:1, 회의실, 전체)
 * ------------------------------------------------------------------------
 */

import { useEffect, useRef, useState } from 'react';
import { Send, User, Users, Megaphone } from 'lucide-react';
import type { AgentMessage } from '../../types';

const AGENT_COLORS: Record<string, string> = {
  claude: '#a78bfa',
  gemini: '#34d399',
  codex: '#22d3ee',
  ceo: '#f59e0b',
};

type ChatMode = 'direct' | 'meeting' | 'broadcast';

interface OfficeChatPanelProps {
  messages: AgentMessage[];
  selectedAgent: string;
  selectedSlotName: string;
  allSlotNames: string[];
  allSlotClis: string[];
  ceoCli?: string; // CEO 슬롯의 실제 CLI (예: 'claude') — CEO 메시지 필터링용
  onSendMessage?: (text: string, target: string) => void;
}

const MODE_TABS: Array<{ id: ChatMode; label: string; icon: typeof User }> = [
  { id: 'direct', label: '1:1', icon: User },
  { id: 'meeting', label: '회의실', icon: Users },
  { id: 'broadcast', label: '전체', icon: Megaphone },
];

export default function OfficeChatPanel({
  messages,
  selectedAgent,
  selectedSlotName,
  allSlotNames,
  allSlotClis,
  ceoCli,
  onSendMessage,
}: OfficeChatPanelProps) {
  const [mode, setMode] = useState<ChatMode>('direct');
  const [input, setInput] = useState('');
  const [localMessages, setLocalMessages] = useState<AgentMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const agentColor = AGENT_COLORS[selectedAgent] || '#94a3b8';

  // 서버 + 로컬 메시지 합치기
  const allMessages = [...messages, ...localMessages];

  // 서버에서 메시지가 도착하면 로컬 메시지 제거 (중복 방지)
  useEffect(() => {
    if (localMessages.length > 0 && messages.length > 0) {
      const serverTimestamps = new Set(messages.map(m => m.timestamp));
      setLocalMessages(prev => prev.filter(m => !serverTimestamps.has(m.timestamp)));
    }
  }, [messages, localMessages.length]);

  // 모드별 메시지 필터
  const filteredMessages = allMessages.filter(m => {
    if (mode === 'direct') {
      const agent = selectedAgent.toLowerCase();
      const from = (m.from || '').toLowerCase();
      const to = (m.to || '').toLowerCase();
      /* CEO 채팅: from/to가 'ceo' 또는 CEO의 실제 CLI(예: 'claude') 포함 */
      if (agent === 'ceo') {
        const cli = ceoCli?.toLowerCase() || '';
        return from === 'ceo' || to === 'ceo'
          || (cli && (from === cli || to === cli))
          || from === 'user' || to === 'user';
      }
      return from.includes(agent) || to.includes(agent);
    }
    if (mode === 'meeting') {
      return m.to === 'all' || m.to === 'meeting' || (m.from && m.to);
    }
    return true;
  }).slice(-80);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredMessages.length, mode]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const target = mode === 'direct' ? selectedAgent : mode === 'meeting' ? 'meeting' : 'all';

    // 즉시 로컬에 추가 (서버 응답 전에 UI에 표시)
    const localMsg: AgentMessage = {
      id: `local-${Date.now()}`,
      from: 'user',
      to: target,
      type: 'info',
      content: trimmed,
      timestamp: new Date().toISOString(),
      read: true,
    };
    setLocalMessages(prev => [...prev, localMsg]);

    onSendMessage?.(trimmed, target);
    setInput('');
  };

  const placeholderText = mode === 'direct'
    ? `${selectedSlotName}에게...`
    : mode === 'meeting'
      ? '회의실에 메시지...'
      : '전체 공지...';

  return (
    <div className="flex h-full flex-col">
      {/* 모드 탭 */}
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-white/[0.06] bg-[#080d15] px-3">
        {MODE_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setMode(tab.id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[10px] font-bold transition-all ${
              mode === tab.id
                ? 'bg-cyan-500/12 text-cyan-300 border border-cyan-500/25'
                : 'text-white/30 hover:text-white/55 border border-transparent'
            }`}
          >
            <tab.icon className="h-3 w-3" />
            {tab.label}
          </button>
        ))}

        {/* 1:1 모드일 때 에이전트 표시 */}
        {mode === 'direct' && (
          <div className="ml-auto flex items-center gap-2">
            <div className="h-2 w-2 rounded-full animate-pulse" style={{ backgroundColor: agentColor }} />
            <span className="text-[10px] font-bold text-white/60">{selectedSlotName}</span>
          </div>
        )}
        {mode === 'meeting' && (
          <div className="ml-auto flex items-center gap-1">
            {allSlotClis.slice(0, 4).map((cli, i) => (
              <div key={i} className="h-2 w-2 rounded-full" style={{ backgroundColor: AGENT_COLORS[cli] || '#94a3b8' }} />
            ))}
            <span className="ml-1 text-[9px] text-white/30">{allSlotNames.length}명</span>
          </div>
        )}
      </div>

      {/* 메시지 영역 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
        {filteredMessages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-3 h-10 w-10 rounded-full border border-white/[0.06] bg-white/[0.02] flex items-center justify-center">
                {mode === 'direct' ? <User className="h-4 w-4 text-white/15" /> : mode === 'meeting' ? <Users className="h-4 w-4 text-white/15" /> : <Megaphone className="h-4 w-4 text-white/15" />}
              </div>
              <div className="text-[10px] text-white/25">
                {mode === 'direct' ? `${selectedSlotName}와 대화를 시작해봐` : mode === 'meeting' ? '회의를 시작해봐' : '전체 공지를 보내봐'}
              </div>
            </div>
          </div>
        ) : (
          filteredMessages.map((msg, i) => {
            const isFromUser = !msg.from || msg.from === 'user' || msg.from === 'operator';
            const senderCli = (msg.from || '').toLowerCase();
            const senderColor = AGENT_COLORS[senderCli] || (isFromUser ? '#60a5fa' : '#94a3b8');
            const senderName = isFromUser ? '나' : (msg.from || 'unknown');

            return (
              <div key={`${msg.timestamp}-${i}`} className={`flex ${isFromUser ? 'justify-end' : 'justify-start'} gap-2`}>
                {/* 에이전트 아바타 */}
                {!isFromUser && (
                  <div
                    className="mt-5 h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-[8px] font-black text-white/80"
                    style={{ backgroundColor: `${senderColor}25`, border: `1.5px solid ${senderColor}55` }}
                  >
                    {senderName[0]?.toUpperCase()}
                  </div>
                )}
                <div className={`max-w-[80%] ${isFromUser ? '' : ''}`}>
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
                        : 'rounded-tl-sm bg-white/[0.04] border border-white/[0.06] text-white/75'
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

      {/* 입력창 */}
      <div className="shrink-0 border-t border-white/[0.06] bg-[#080d15] p-3">
        <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2.5 focus-within:border-cyan-500/25 transition-colors">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }}}
            placeholder={placeholderText}
            className="flex-1 bg-transparent text-xs text-white/80 outline-none placeholder:text-white/18"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="rounded-lg bg-cyan-500/15 p-2 text-cyan-400 transition hover:bg-cyan-500/25 disabled:opacity-20 disabled:cursor-not-allowed"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
