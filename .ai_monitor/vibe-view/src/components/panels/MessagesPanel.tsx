/**
 * FILE: MessagesPanel.tsx
 * DESCRIPTION: 에이전트 간 메시지 채널 패널 컴포넌트.
 *              Claude ↔ Gemini ↔ System 간 실시간 메시지를 채팅 버블 스타일로 표시한다.
 *              발신자별 색상과 정렬로 직관적인 대화 흐름을 제공한다.
 *
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 * - 2026-03-01 Claude: Task 4 채팅 버블 스타일 적용 (발신자별 색상/정렬, 자동 스크롤, 아바타)
 */

import { useState, useEffect, useRef } from 'react';
import { MessageSquare, Send } from 'lucide-react';
import { AgentMessage } from '../../types';

// 현재 접속 포트 기반으로 API 주소 자동 결정
const API_BASE = `http://${window.location.hostname}:${window.location.port}`;

interface MessagesPanelProps {
  /** 읽지 않은 메시지 수 변경 시 부모에게 알리는 콜백 */
  onUnreadCount: (count: number) => void;
}

// 발신자별 버블 스타일 정의
// Claude: 파란색 우측, Gemini: 초록색 좌측, System: 중앙 작은 텍스트
const AGENT_STYLE: Record<string, {
  bubble: string;      // 버블 배경/테두리 색상
  text: string;        // 텍스트 색상
  align: string;       // 정렬 방향 (좌/우/중앙)
  avatar: string;      // 아바타 배경색
  label: string;       // 표시 이름
}> = {
  claude: {
    bubble: 'bg-blue-500/15 border-blue-500/30',
    text:   'text-blue-100',
    align:  'items-end',
    avatar: 'bg-blue-500/30 text-blue-300',
    label:  'Claude',
  },
  gemini: {
    bubble: 'bg-green-500/15 border-green-500/30',
    text:   'text-green-100',
    align:  'items-start',
    avatar: 'bg-green-500/30 text-green-300',
    label:  'Gemini',
  },
  system: {
    bubble: 'bg-white/5 border-white/10',
    text:   'text-[#aaaaaa]',
    align:  'items-center',
    avatar: 'bg-white/10 text-[#858585]',
    label:  'System',
  },
  user: {
    bubble: 'bg-purple-500/15 border-purple-500/30',
    text:   'text-purple-100',
    align:  'items-end',
    avatar: 'bg-purple-500/30 text-purple-300',
    label:  'User',
  },
};

// 메시지 유형 배지 색상
const TYPE_BADGE: Record<string, string> = {
  handoff:      'bg-yellow-500/20 text-yellow-400',
  request:      'bg-blue-500/20 text-blue-400',
  task_complete: 'bg-green-500/20 text-green-400',
  warning:      'bg-red-500/20 text-red-400',
  info:         'bg-white/10 text-white/50',
};

export default function MessagesPanel({ onUnreadCount }: MessagesPanelProps) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [msgFrom, setMsgFrom] = useState('claude');
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');

  // 읽지 않은 메시지 추적
  const [baseCount, setBaseCount] = useState(0);
  const [isVisible] = useState(true);

  // 자동 스크롤용 ref
  const bottomRef = useRef<HTMLDivElement>(null);

  // 메시지 채널 폴링 (3초 간격)
  useEffect(() => {
    const fetchMessages = () => {
      fetch(`${API_BASE}/api/messages`)
        .then(res => res.json())
        .then((data: AgentMessage[]) => {
          const list = Array.isArray(data) ? data : [];
          setMessages(list);
          if (isVisible) {
            setBaseCount(list.length);
            onUnreadCount(0);
          } else {
            onUnreadCount(Math.max(0, list.length - baseCount));
          }
        })
        .catch(() => {});
    };
    fetchMessages();
    const interval = setInterval(fetchMessages, 3000);
    return () => clearInterval(interval);
  }, [isVisible, baseCount, onUnreadCount]);

  // 패널 마운트 시 읽음 처리 + 스크롤 최하단
  useEffect(() => {
    setBaseCount(messages.length);
    onUnreadCount(0);
  }, []);

  // 새 메시지 추가 시 자동 스크롤 하단
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // 메시지 전송 핸들러
  const sendMessage = () => {
    if (!msgContent.trim()) return;
    const cleanContent = msgContent.replace(/[\r\n]+$/, '');
    fetch(`${API_BASE}/api/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: msgFrom, to: msgTo, type: msgType, content: cleanContent }),
    })
      .then(res => res.json())
      .then(() => {
        setMsgContent('');
        return fetch(`${API_BASE}/api/messages`);
      })
      .then(res => res.json())
      .then((data: AgentMessage[]) => setMessages(Array.isArray(data) ? data : []))
      .catch(() => {});
  };

  // 발신자 스타일 결정 (알 수 없는 에이전트는 system 스타일 사용)
  const getStyle = (from: string) => AGENT_STYLE[from.toLowerCase()] ?? AGENT_STYLE['system'];

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-2">

      {/* ── 채팅 메시지 목록 ── */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-1 py-2 space-y-3">
        {messages.length === 0 ? (
          <div className="text-center text-[#858585] text-xs py-10 flex flex-col items-center gap-2 italic">
            <MessageSquare className="w-7 h-7 opacity-20" />
            아직 메시지가 없습니다
          </div>
        ) : (
          messages.map(msg => {
            const style = getStyle(msg.from);
            const isSystem = msg.from.toLowerCase() === 'system';

            return (
              <div key={msg.id} className={`flex flex-col ${style.align} gap-0.5`}>
                {/* 발신자 레이블 + 타임스탬프 */}
                <div className={`flex items-center gap-1.5 ${style.align === 'items-end' ? 'flex-row-reverse' : ''}`}>
                  {/* 아바타 (이니셜) */}
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0 ${style.avatar}`}>
                    {msg.from.charAt(0).toUpperCase()}
                  </div>
                  <span className="text-[9px] text-[#555] font-mono">
                    {msg.from} → {msg.to}
                  </span>
                  <span className="text-[8px] text-[#444] font-mono">
                    {msg.timestamp.replace('T', ' ').slice(0, 16)}
                  </span>
                </div>

                {/* 버블 본문 */}
                <div className={`max-w-[90%] ${style.align === 'items-end' ? 'mr-6' : style.align === 'items-start' ? 'ml-6' : 'mx-auto'}`}>
                  <div className={`rounded-lg border px-2.5 py-1.5 ${style.bubble}`}>
                    {/* 메시지 유형 배지 (system/info 제외) */}
                    {msg.type !== 'info' && (
                      <span className={`text-[8px] font-bold px-1 py-0.5 rounded mb-1 inline-block ${TYPE_BADGE[msg.type] ?? TYPE_BADGE['info']}`}>
                        {msg.type}
                      </span>
                    )}
                    {/* 본문 */}
                    <p className={`text-[10px] leading-relaxed break-words whitespace-pre-wrap ${isSystem ? 'italic text-center text-[9px]' : style.text}`}>
                      {msg.content}
                    </p>
                  </div>
                </div>
              </div>
            );
          })
        )}
        {/* 자동 스크롤 앵커 */}
        <div ref={bottomRef} />
      </div>

      {/* ── 메시지 작성 폼 ── */}
      <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
        {/* 발신자 → 수신자 선택 */}
        <div className="flex gap-1 items-center">
          <select
            value={msgFrom}
            onChange={e => setMsgFrom(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors"
          >
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
            <option value="system">System</option>
          </select>
          <span className="text-white/30 text-[10px] px-0.5">→</span>
          <select
            value={msgTo}
            onChange={e => setMsgTo(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors"
          >
            <option value="all">All</option>
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
          </select>
          <select
            value={msgType}
            onChange={e => setMsgType(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors"
          >
            <option value="info">정보</option>
            <option value="handoff">핸드오프</option>
            <option value="request">요청</option>
            <option value="task_complete">완료</option>
            <option value="warning">경고</option>
          </select>
        </div>

        {/* 본문 입력 + 전송 버튼 */}
        <div className="flex gap-1 items-end">
          <textarea
            value={msgContent}
            onChange={e => setMsgContent(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (!e.nativeEvent.isComposing && msgContent.trim()) {
                  sendMessage();
                  setTimeout(() => setMsgContent(''), 0);
                }
              }
            }}
            placeholder="메시지... (Enter: 전송)"
            rows={2}
            className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors resize-none"
          />
          <button
            onClick={sendMessage}
            disabled={!msgContent.trim()}
            className="p-2 bg-primary/80 hover:bg-primary disabled:opacity-30 disabled:cursor-not-allowed text-white rounded transition-colors shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
