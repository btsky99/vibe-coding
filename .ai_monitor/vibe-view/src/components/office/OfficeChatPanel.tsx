/**
 * ------------------------------------------------------------------------
 * FILE: OfficeChatPanel.tsx
 * DESCRIPTION: 오피스 모드 채팅 패널 — agent/chat API SSE 기반.
 *              PTY 직통에서 REST API 브릿지로 전환.
 *              / 입력 시 스킬 팝업 표시.
 * REVISION HISTORY:
 * - 2026-04-13 Claude: agent/chat API 전환 + 스킬 팝업 추가
 * - 2026-04-11 Claude: PTY 직통 통신으로 전면 재작성 (클래식 분리)
 * - 2026-04-08 Claude: 3모드 채팅 패널로 재설계 (1:1, 회의실, 전체)
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, Square, Terminal, Trash2, Wrench } from 'lucide-react';
import type { OfficeChatMessage } from '../../hooks/useOfficeChat';

const AGENT_COLORS: Record<string, string> = {
  claude: '#a78bfa',
  gemini: '#34d399',
  codex: '#22d3ee',
};

/** 스킬 메타데이터 */
interface SkillMeta {
  name: string;
  description: string;
  userInvocable: boolean;
  /** Platform Phase 3: .claude vs .vibe 출처 배지 */
  origin?: 'claude' | 'vibe';
}

interface OfficeChatPanelProps {
  chatMessages: OfficeChatMessage[];
  selectedAgent: string;
  selectedSlotName: string;
  terminalId: string | null;
  isStreaming: boolean;
  sendError: string | null;
  onSendMessage: (text: string) => void;
  onStopStreaming: () => void;
  onClearChat: () => void;
}

export default function OfficeChatPanel({
  chatMessages,
  selectedAgent,
  selectedSlotName,
  terminalId,
  isStreaming,
  sendError,
  onSendMessage,
  onStopStreaming,
  onClearChat,
}: OfficeChatPanelProps) {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const agentColor = AGENT_COLORS[selectedAgent] || '#94a3b8';

  // ── 스킬 팝업 상태 ──
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [showSkills, setShowSkills] = useState(false);
  const [skillFilter, setSkillFilter] = useState('');
  const [selectedSkillIdx, setSelectedSkillIdx] = useState(0);
  const skillsCacheRef = useRef<{ data: SkillMeta[]; ts: number } | null>(null);

  // 스킬 목록 로드 (5분 캐시)
  const loadSkills = useCallback(async () => {
    const cache = skillsCacheRef.current;
    if (cache && Date.now() - cache.ts < 300_000) {
      setSkills(cache.data);
      return;
    }
    try {
      const resp = await fetch('/api/office/skills');
      const data = await resp.json();
      const list: SkillMeta[] = (data.skills || []).filter((s: SkillMeta) => s.userInvocable);
      setSkills(list);
      skillsCacheRef.current = { data: list, ts: Date.now() };
    } catch {
      // 스킬 로드 실패 — 팝업 비활성
    }
  }, []);

  useEffect(() => {
    scrollRef.current && (scrollRef.current.scrollTop = scrollRef.current.scrollHeight);
  }, [chatMessages.length, chatMessages[chatMessages.length - 1]?.content]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setInput(val);

    // / 입력 감지 → 스킬 팝업
    if (val === '/' || (val.startsWith('/') && !val.includes(' '))) {
      const filter = val.slice(1).toLowerCase();
      setSkillFilter(filter);
      setSelectedSkillIdx(0);
      if (!showSkills) {
        loadSkills();
        setShowSkills(true);
      }
    } else {
      setShowSkills(false);
    }
  };

  const filteredSkills = skills.filter(s =>
    s.name.toLowerCase().includes(skillFilter) ||
    s.description.toLowerCase().includes(skillFilter)
  );

  const handleSkillSelect = (skill: SkillMeta) => {
    setInput(`/${skill.name} `);
    setShowSkills(false);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    // 스킬 팝업 키보드 네비게이션
    if (showSkills && filteredSkills.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedSkillIdx(prev => Math.min(prev + 1, filteredSkills.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedSkillIdx(prev => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        handleSkillSelect(filteredSkills[selectedSkillIdx]);
        return;
      }
      if (e.key === 'Escape') {
        setShowSkills(false);
        return;
      }
    }

    // 일반 전송
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || !terminalId) return;
    onSendMessage(trimmed);
    setInput('');
    setShowSkills(false);
  };

  const canSend = !!terminalId && !isStreaming;

  return (
    <div className="flex h-full flex-col">
      {/* 헤더 */}
      <div className="flex shrink-0 flex-col border-b border-white/[0.06] bg-[#080d15]">
        <div className="flex h-10 items-center justify-between px-3">
          <div className="flex items-center gap-2">
            <Terminal className="h-3 w-3 text-white/30" />
            <div className="h-2 w-2 rounded-full" style={{
              backgroundColor: isStreaming ? '#f59e0b' : terminalId ? '#4ade80' : '#ef4444',
              boxShadow: !isStreaming && terminalId ? '0 0 6px rgba(74,222,128,0.5)' : 'none',
              animation: isStreaming ? 'pulse 1.5s infinite' : 'none',
            }} />
            <span className="text-[10px] font-bold text-white/60">
              {selectedSlotName}
            </span>
            {terminalId && (
              <span className="text-[8px] text-white/20">{terminalId}</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: agentColor }} />
            <span className="text-[9px] text-white/40">{selectedAgent}</span>
            {isStreaming && (
              <button
                onClick={onStopStreaming}
                className="ml-1 rounded bg-red-500/15 p-1 text-red-300 hover:bg-red-500/25 transition"
                title="중단"
              >
                <Square className="h-2.5 w-2.5" />
              </button>
            )}
            {chatMessages.length > 0 && (
              <button onClick={onClearChat} className="ml-1 rounded p-1 text-white/15 hover:text-white/40 transition" title="채팅 초기화">
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        {/* 상태 바 */}
        <div className="flex h-5 items-center gap-2 border-t border-white/[0.03] px-3">
          <span className={`text-[9px] font-bold ${!terminalId ? 'text-red-400' : isStreaming ? 'text-amber-400' : 'text-emerald-400'}`}>
            {!terminalId ? '연결 대기' : isStreaming ? '응답 중...' : '대기 중'}
          </span>
          {isStreaming && (
            <div className="flex-1 h-1 rounded bg-white/[0.04] overflow-hidden">
              <div className="h-full w-1/3 rounded bg-amber-500/40 animate-[slide_1.5s_infinite_linear]" />
            </div>
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
                {terminalId
                  ? `${selectedSlotName}에게 메시지를 보내봐`
                  : `${selectedSlotName} 연결 대기 중`}
              </div>
              <div className="mt-1 text-[9px] text-white/15">
                / 를 입력하면 스킬 목록이 표시돼
              </div>
            </div>
          </div>
        ) : (
          chatMessages.map((msg, i) => {
            const isFromUser = msg.role === 'user';
            const isTool = msg.role === 'tool';
            const senderColor = isFromUser ? '#60a5fa' : isTool ? '#f59e0b' : agentColor;
            const senderName = isFromUser ? '나' : isTool ? (msg.toolName || 'tool') : selectedAgent;

            if (isTool) {
              return (
                <div key={msg.id || `${msg.ts}-${i}`} className="flex items-start gap-2 opacity-60">
                  <Wrench className="mt-0.5 h-3 w-3 shrink-0 text-amber-400/60" />
                  <div className="text-[9px] text-white/40 font-mono truncate">
                    {msg.toolName}: {msg.content.slice(0, 120)}
                  </div>
                </div>
              );
            }

            return (
              <div key={msg.id || `${msg.ts}-${i}`} className={`flex ${isFromUser ? 'justify-end' : 'justify-start'} gap-2`}>
                {!isFromUser && (
                  <div
                    className="mt-5 h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-[8px] font-black text-white/80"
                    style={{ backgroundColor: `${senderColor}25`, border: `1.5px solid ${senderColor}55` }}
                  >
                    {senderName[0]?.toUpperCase()}
                  </div>
                )}
                <div className="max-w-[85%]">
                  <div className={`mb-0.5 flex items-center gap-2 text-[8px] ${isFromUser ? 'justify-end' : ''}`}>
                    <span className="font-bold" style={{ color: `${senderColor}bb` }}>
                      {senderName}
                      {msg.source === 'telegram' && msg.tgUser && ` (${msg.tgUser})`}
                    </span>
                    <span className="text-white/15">
                      {new Date(msg.ts).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <div
                    className={`rounded-2xl px-3.5 py-2 text-[11px] leading-relaxed whitespace-pre-wrap ${
                      isFromUser
                        ? 'rounded-tr-sm bg-cyan-500/12 border border-cyan-500/15 text-cyan-50/90'
                        : 'rounded-tl-sm bg-white/[0.04] border border-white/[0.06] text-white/75 font-mono'
                    }`}
                  >
                    {msg.content || (isStreaming && !isFromUser ? '...' : '')}
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

      {/* 스킬 팝업 */}
      {showSkills && filteredSkills.length > 0 && (
        <div className="shrink-0 border-t border-white/[0.06] bg-[#0c1220] max-h-[200px] overflow-y-auto">
          {filteredSkills.map((skill, idx) => (
            <button
              key={skill.name}
              onClick={() => handleSkillSelect(skill)}
              className={`flex w-full items-start gap-2 px-4 py-2 text-left transition ${
                idx === selectedSkillIdx ? 'bg-cyan-500/10' : 'hover:bg-white/[0.03]'
              }`}
            >
              <span className="shrink-0 text-[10px] font-bold text-cyan-400">/{skill.name}</span>
              {skill.origin === 'vibe' && (
                <span
                  className="shrink-0 rounded-sm bg-emerald-500/15 px-1 py-[1px] text-[8px] font-bold uppercase tracking-wide text-emerald-300"
                  title=".vibe/skills/ — 프로젝트별 확장 (Layer 2)"
                >
                  vibe
                </span>
              )}
              <span className="text-[9px] text-white/40 line-clamp-2">{skill.description}</span>
            </button>
          ))}
        </div>
      )}

      {/* 입력창 */}
      <div className="shrink-0 border-t border-white/[0.06] bg-[#080d15] p-3">
        <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2.5 focus-within:border-cyan-500/25 transition-colors">
          <input
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={!terminalId ? '연결 대기 중...' : isStreaming ? '응답 대기 중...' : `${selectedSlotName}에게... (/ 로 스킬 선택)`}
            disabled={!terminalId}
            className="flex-1 bg-transparent text-xs text-white/80 outline-none placeholder:text-white/18 disabled:opacity-30"
          />
          {isStreaming ? (
            <button
              onClick={onStopStreaming}
              className="rounded-lg bg-red-500/15 p-2 text-red-400 transition hover:bg-red-500/25"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim() || !canSend}
              className="rounded-lg bg-cyan-500/15 p-2 text-cyan-400 transition hover:bg-cyan-500/25 disabled:opacity-20 disabled:cursor-not-allowed"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
