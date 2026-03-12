/**
 * ------------------------------------------------------------------------
 * 📄 파일명: MessagesPanel.tsx
 * 📝 설명: 에이전트 간 메시지 채널 패널 컴포넌트.
 *          Claude ↔ Gemini ↔ System 간 실시간 메시지를 채팅 버블 스타일로 표시합니다.
 *          발신자별 색상/정렬, 방향별 버블 코너, 상대 타임스탬프, 자동 스크롤,
 *          미읽음 카운트, 전체 삭제를 포함합니다.
 * REVISION HISTORY:
 * - 2026-03-05 Claude: 긴 메시지 접기(200자 초과 → 더보기), session_summary 배지, 날짜 구분선 추가
 * - 2026-03-02 Claude: 버블 방향별 코너, 상대 타임스탬프, 미읽음 카운트 로직 수정,
 *                      헤더 + 메시지 건수 + 전체 삭제 버튼 추가
 * - 2026-03-01 Claude: App.tsx에서 분리 — 독립 컴포넌트화
 * - 2026-03-01 Claude: Task 4 채팅 버블 스타일 적용 (발신자별 색상/정렬, 자동 스크롤, 아바타)
 * ------------------------------------------------------------------------
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { MessageSquare, Send, Trash2, ChevronDown, ChevronUp } from 'lucide-react';

// 긴 메시지 접기 기준 (글자 수)
const COLLAPSE_THRESHOLD = 200;
import { AgentMessage } from '../../types';
import { API_BASE } from '../../constants';
import FilePathText from '../FilePathText';

interface MessagesPanelProps {
  /** 읽지 않은 메시지 수 변경 시 부모(ActivityBar 배지)에게 알리는 콜백 */
  onUnreadCount: (count: number) => void;
  onOpenFilePath?: (path: string) => void;
}

// ─── 발신자별 버블 스타일 정의 ───────────────────────────────────────────────
// Claude: 파란색 우측 / Gemini: 초록색 좌측 / System: 중앙 작은 텍스트 / User: 보라 우측
const AGENT_STYLE: Record<string, {
  bubble: string;     // 버블 배경+테두리
  text: string;       // 본문 텍스트 색상
  side: 'right' | 'left' | 'center';  // 정렬 방향
  avatar: string;     // 아바타 배경색
  label: string;      // 표시 이름
}> = {
  claude: {
    bubble: 'bg-blue-500/20 border-blue-500/40',
    text:   'text-blue-100',
    side:   'right',
    avatar: 'bg-blue-500/40 text-blue-200',
    label:  'Claude',
  },
  gemini: {
    bubble: 'bg-emerald-500/20 border-emerald-500/40',
    text:   'text-emerald-100',
    side:   'left',
    avatar: 'bg-emerald-500/40 text-emerald-200',
    label:  'Gemini',
  },
  system: {
    bubble: 'bg-white/5 border-white/10',
    text:   'text-[#888888]',
    side:   'center',
    avatar: 'bg-white/10 text-[#888888]',
    label:  'System',
  },
  user: {
    bubble: 'bg-violet-500/20 border-violet-500/40',
    text:   'text-violet-100',
    side:   'right',
    avatar: 'bg-violet-500/40 text-violet-200',
    label:  'User',
  },
};

// ─── 메시지 유형 배지 스타일 ────────────────────────────────────────────────
const TYPE_BADGE: Record<string, { cls: string; emoji: string }> = {
  handoff:         { cls: 'bg-yellow-500/25 text-yellow-300',  emoji: '🤝' },
  request:         { cls: 'bg-blue-500/25 text-blue-300',      emoji: '📋' },
  task_complete:   { cls: 'bg-green-500/25 text-green-300',    emoji: '✅' },
  warning:         { cls: 'bg-red-500/25 text-red-300',        emoji: '⚠️' },
  info:            { cls: 'bg-white/10 text-white/40',         emoji: 'ℹ️' },
  session_summary: { cls: 'bg-purple-500/25 text-purple-300',  emoji: '📝' },
};

// ─── 상대 타임스탬프 헬퍼 ────────────────────────────────────────────────────
function relativeTime(iso: string): string {
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 10)   return '방금 전';
    if (diff < 60)   return `${diff}초 전`;
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    return new Date(iso).toLocaleString('ko-KR', {
      month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso; }
}

// ─── 버블 아이템 서브컴포넌트 (접기 상태 독립 관리) ────────────────────────

interface BubbleItemProps {
  msg: AgentMessage;
  style: typeof AGENT_STYLE[string];
  isRight: boolean;
  typeBadge: typeof TYPE_BADGE[string];
  isNew: boolean;
  isLong: boolean;
  cornerCls: string;
  showDateSep: boolean;
  dateLabel: string;
  onOpenFilePath?: (path: string) => void;
}

function BubbleItem({ msg, style, isRight, typeBadge, isNew, isLong, cornerCls, showDateSep, dateLabel, onOpenFilePath }: BubbleItemProps) {
  // 긴 메시지 접힘 상태 — 기본적으로 접힘
  const [expanded, setExpanded] = useState(false);
  const displayContent = isLong && !expanded
    ? msg.content.slice(0, COLLAPSE_THRESHOLD) + '…'
    : msg.content;

  return (
    <div>
      {/* 날짜 구분선 */}
      {showDateSep && (
        <div className="flex items-center gap-2 my-2">
          <div className="flex-1 h-px bg-white/5" />
          <span className="text-[8px] text-[#444] font-mono shrink-0">{dateLabel}</span>
          <div className="flex-1 h-px bg-white/5" />
        </div>
      )}
      <div className={`flex flex-col gap-0.5 ${isRight ? 'items-end' : 'items-start'} ${isNew ? 'opacity-100' : 'opacity-80'}`}>
        {/* 발신자 메타 */}
        <div className={`flex items-center gap-1.5 ${isRight ? 'flex-row-reverse' : ''}`}>
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black shrink-0 ${style.avatar}`}>
            {msg.from.charAt(0).toUpperCase()}
          </div>
          <span className="text-[9px] text-[#555] font-mono">
            {msg.from}<span className="text-[#333] mx-0.5">→</span>{msg.to}
          </span>
          <span className="text-[8px] text-[#444]">{relativeTime(msg.timestamp)}</span>
        </div>

        {/* 버블 본문 */}
        <div className={`max-w-[88%] ${isRight ? 'mr-7' : 'ml-7'}`}>
          <div className={`border px-2.5 py-1.5 ${style.bubble} ${cornerCls} ${isNew ? 'ring-1 ring-yellow-400/20' : ''}`}>
            {/* 유형 배지 (info 제외) */}
            {msg.type !== 'info' && (
              <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded-full mb-1 inline-flex items-center gap-0.5 ${typeBadge.cls}`}>
                <span>{typeBadge.emoji}</span>
                <span>{msg.type}</span>
              </span>
            )}
            {/* 본문 텍스트 */}
            <p className={`text-[10px] leading-relaxed break-words whitespace-pre-wrap ${style.text}`}>
              <FilePathText
                text={displayContent}
                onPathClick={onOpenFilePath}
                pathClassName={style.text}
              />
            </p>
            {/* 더보기 / 접기 토글 (긴 메시지만) */}
            {isLong && (
              <button
                onClick={() => setExpanded(v => !v)}
                className={`mt-1 flex items-center gap-0.5 text-[8px] font-bold opacity-60 hover:opacity-100 transition-opacity ${style.text}`}
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {expanded ? '접기' : `더보기 (${msg.content.length}자)`}
              </button>
            )}
            {/* 읽음 표시 */}
            {isRight && (
              <div className="text-right mt-0.5">
                <span className={`text-[7px] ${msg.read ? 'text-primary/60' : 'text-white/20'}`}>
                  {msg.read ? '읽음' : '•'}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MessagesPanel({ onUnreadCount, onOpenFilePath }: MessagesPanelProps) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [msgFrom, setMsgFrom] = useState('claude');
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');
  // 패널이 마지막으로 열렸을 때의 메시지 수 — 그 이후 수신된 것이 미읽음
  const [seenCount, setSeenCount] = useState(0);

  // 자동 스크롤용 ref
  const bottomRef = useRef<HTMLDivElement>(null);
  // 마운트 여부 (첫 fetch 후 seenCount 초기화)
  const mountedRef = useRef(false);

  // 메시지 채널 폴링 (3초 간격)
  const fetchMessages = useCallback(() => {
    fetch(`${API_BASE}/api/messages`)
      .then(res => res.json())
      .then((data: AgentMessage[]) => {
        const list = Array.isArray(data) ? data : [];
        setMessages(list);
        if (!mountedRef.current) {
          // 첫 로드 시: 현재 메시지 수를 기준점으로 저장 → 미읽음 0
          setSeenCount(list.length);
          onUnreadCount(0);
          mountedRef.current = true;
        } else {
          // 이후: 기준점 이후 새로 온 것만 미읽음
          setSeenCount(prev => {
            const unread = Math.max(0, list.length - prev);
            onUnreadCount(unread);
            return prev;
          });
        }
      })
      .catch(() => {});
  }, [onUnreadCount]);

  useEffect(() => {
    fetchMessages();
    const interval = setInterval(fetchMessages, 3000);
    return () => clearInterval(interval);
  }, [fetchMessages]);

  // 패널이 보일 때 (탭 전환으로 마운트될 때) 미읽음 리셋
  useEffect(() => {
    setSeenCount(messages.length);
    onUnreadCount(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 새 메시지 도착 시 자동 스크롤 최하단
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // 메시지 전송
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
      .then((data: AgentMessage[]) => {
        const list = Array.isArray(data) ? data : [];
        setMessages(list);
        setSeenCount(list.length);
        onUnreadCount(0);
      })
      .catch(() => {});
  };

  // 전체 메시지 삭제 (서버 API 호출)
  const clearMessages = () => {
    if (!confirm('모든 메시지를 삭제하시겠습니까?')) return;
    fetch(`${API_BASE}/api/messages/clear`, { method: 'POST' })
      .then(() => {
        setMessages([]);
        setSeenCount(0);
        onUnreadCount(0);
      })
      .catch(() => {});
  };

  // 발신자 스타일 결정 (알 수 없는 에이전트 → system 스타일)
  const getStyle = (from: string) => AGENT_STYLE[from.toLowerCase()] ?? AGENT_STYLE['system'];

  // 날짜 문자열 추출 (날짜 구분선용)
  const toDateLabel = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
    } catch { return ''; }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden gap-0">

      {/* ── 패널 헤더 — 메시지 수 + 전체 삭제 ── */}
      <div className="flex items-center gap-2 pb-2 shrink-0 border-b border-white/5 mb-1">
        <MessageSquare className="w-3.5 h-3.5 text-[#858585]" />
        <span className="text-[10px] font-bold text-white/60">메시지 채널</span>
        <span className="text-[9px] text-[#555] ml-1">{messages.length}건</span>
        {messages.length > 0 && (
          <button
            onClick={clearMessages}
            className="ml-auto p-1 hover:bg-red-500/20 rounded text-[#555] hover:text-red-400 transition-colors"
            title="전체 삭제"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* ── 채팅 버블 목록 ── */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-1 py-1 space-y-2.5">
        {messages.length === 0 ? (
          <div className="text-center text-[#555] text-xs py-10 flex flex-col items-center gap-2 italic">
            <MessageSquare className="w-7 h-7 opacity-15" />
            아직 메시지가 없습니다
          </div>
        ) : (
          messages.map((msg, idx) => {
            const style = getStyle(msg.from);
            const isCenter = style.side === 'center';
            const isRight  = style.side === 'right';
            const typeBadge = TYPE_BADGE[msg.type] ?? TYPE_BADGE['info'];

            // 새로 수신된 메시지 (seenCount 기준) — 미읽음 강조
            const isNew = idx >= seenCount;

            // 날짜 구분선: 이전 메시지와 날짜가 다를 때 표시
            const prevMsg = messages[idx - 1];
            const showDateSep = idx === 0 || toDateLabel(msg.timestamp) !== toDateLabel(prevMsg?.timestamp ?? '');

            // 버블 코너 — 채팅앱 스타일: 자기 쪽 상단 코너는 각지게
            const cornerCls = isCenter
              ? 'rounded-lg'
              : isRight
                ? 'rounded-l-xl rounded-br-xl rounded-tr-sm'
                : 'rounded-r-xl rounded-bl-xl rounded-tl-sm';

            // 긴 메시지 접기 여부 — 컴포넌트 외부에서 관리하려면 Map 필요,
            // 여기서는 key를 msg.id로 쓰는 expandedIds Set으로 관리
            const isLong = msg.content.length > COLLAPSE_THRESHOLD;

            if (isCenter) {
              return (
                <div key={msg.id}>
                  {showDateSep && (
                    <div className="flex items-center gap-2 my-2">
                      <div className="flex-1 h-px bg-white/5" />
                      <span className="text-[8px] text-[#444] font-mono shrink-0">{toDateLabel(msg.timestamp)}</span>
                      <div className="flex-1 h-px bg-white/5" />
                    </div>
                  )}
                  {/* 시스템 메시지 — 중앙 작은 텍스트 */}
                  <div className="flex justify-center">
                    <div className={`rounded-full border px-3 py-0.5 ${style.bubble} ${isNew ? 'ring-1 ring-yellow-500/30' : ''}`}>
                      <p className={`text-[9px] italic ${style.text}`}>
                        <FilePathText
                          text={msg.content}
                          onPathClick={onOpenFilePath}
                          pathClassName={style.text}
                        />
                      </p>
                    </div>
                  </div>
                </div>
              );
            }

            return (
              <BubbleItem
                key={msg.id}
                msg={msg}
                style={style}
                isRight={isRight}
                typeBadge={typeBadge}
                isNew={isNew}
                isLong={isLong}
                cornerCls={cornerCls}
                showDateSep={showDateSep}
                dateLabel={toDateLabel(msg.timestamp)}
                onOpenFilePath={onOpenFilePath}
              />
            );
          })
        )}
        {/* 자동 스크롤 앵커 */}
        <div ref={bottomRef} />
      </div>

      {/* ── 메시지 작성 폼 ── */}
      <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5 shrink-0">
        {/* From → To / 유형 선택 행 */}
        <div className="flex gap-1 items-center">
          <select
            value={msgFrom}
            onChange={e => setMsgFrom(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
          >
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
            <option value="system">System</option>
            <option value="user">User</option>
          </select>
          <span className="text-white/20 text-[10px] px-0.5">→</span>
          <select
            value={msgTo}
            onChange={e => setMsgTo(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
          >
            <option value="all">All</option>
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
          </select>
          <select
            value={msgType}
            onChange={e => setMsgType(e.target.value)}
            className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
          >
            <option value="info">ℹ️ 정보</option>
            <option value="handoff">🤝 핸드오프</option>
            <option value="request">📋 요청</option>
            <option value="task_complete">✅ 완료</option>
            <option value="warning">⚠️ 경고</option>
          </select>
        </div>

        {/* 본문 textarea + 전송 버튼 */}
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
            placeholder="메시지... (Enter: 전송, Shift+Enter: 줄바꿈)"
            rows={2}
            className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded-lg px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors resize-none"
          />
          <button
            onClick={sendMessage}
            disabled={!msgContent.trim()}
            className="p-2 bg-primary/80 hover:bg-primary disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg transition-colors shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
