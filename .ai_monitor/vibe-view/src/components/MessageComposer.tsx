/**
 * ------------------------------------------------------------------------
 * 📄 파일명: MessageComposer.tsx
 * 📝 설명: 사이드바 하단 고정 메시지 작성/전송 컴포넌트.
 *          발신자(From) / 수신자(To) / 유형(Type) 선택 셀렉트와
 *          메시지 텍스트영역, 전송 버튼으로 구성됩니다.
 *          에이전트 간 메시지 채널 API를 직접 호출합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리.
 * ------------------------------------------------------------------------
 */

import { useRef, useState } from 'react';
import { Send } from 'lucide-react';
import { API_BASE } from '../constants';

interface MessageComposerProps {
  // 전송 완료 후 메시지 목록 갱신을 위해 App에 알림
  onMessageSent?: () => void;
}

export default function MessageComposer({ onMessageSent }: MessageComposerProps) {
  const [msgFrom, setMsgFrom] = useState('claude');
  const [msgTo, setMsgTo] = useState('all');
  const [msgType, setMsgType] = useState('info');
  const [msgContent, setMsgContent] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);
  const [isComposing, setIsComposing] = useState(false);

  // 메시지 전송 — API 호출 후 입력창 초기화 + 상위 갱신 알림
  const sendMessage = (rawContent?: string) => {
    const currentContent = rawContent ?? textareaRef.current?.value ?? msgContent;
    const cleanContent = currentContent.replace(/[\r\n]+$/, '').trim();
    if (!cleanContent) return;
    isComposingRef.current = false;
    setIsComposing(false);

    fetch(`${API_BASE}/api/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: msgFrom, to: msgTo, type: msgType, content: cleanContent }),
    })
      .then(res => res.json())
      .then(() => {
        setMsgContent('');
        onMessageSent?.();
      })
      .catch(() => {});
  };

  return (
    <div className="mt-auto pt-3 border-t border-white/5 flex flex-col gap-2 shrink-0">
      {/* 발신자 / 수신자 선택 행 */}
      <div className="flex gap-1">
        <select
          value={msgFrom}
          onChange={e => setMsgFrom(e.target.value)}
          className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
        >
          <option value="user">User</option>
          <option value="claude">Claude</option>
          <option value="gemini">Gemini</option>
          <option value="system">System</option>
        </select>
        <span className="text-white/30 text-[10px] px-0.5 leading-7">→</span>
        <select
          value={msgTo}
          onChange={e => setMsgTo(e.target.value)}
          className="flex-1 bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
        >
          <option value="all">All</option>
          <option value="claude">Claude</option>
          <option value="gemini">Gemini</option>
        </select>
      </div>

      {/* 메시지 유형 선택 */}
      <select
        value={msgType}
        onChange={e => setMsgType(e.target.value)}
        className="w-full bg-[#3c3c3c] border border-white/5 rounded px-1 py-1 text-[10px] focus:outline-none cursor-pointer hover:border-white/20 transition-colors text-white"
      >
        <option value="info">ℹ️ 정보 공유</option>
        <option value="handoff">🤝 핸드오프 (작업 위임)</option>
        <option value="request">📋 작업 요청</option>
        <option value="task_complete">✅ 완료 알림</option>
        <option value="warning">⚠️ 경고</option>
      </select>

      {/* 메시지 입력 + 전송 버튼 */}
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={msgContent}
          onChange={e => setMsgContent(e.target.value)}
          onCompositionStart={() => {
            isComposingRef.current = true;
            setIsComposing(true);
          }}
          onCompositionEnd={e => {
            isComposingRef.current = false;
            setIsComposing(false);
            setMsgContent(e.currentTarget.value);
          }}
          onKeyDown={e => {
            // Shift+Enter는 줄바꿈, 단독 Enter는 전송 (한글 조합 중 Enter 제외)
            if (e.key === 'Enter' && !e.shiftKey) {
              if (isComposingRef.current || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) {
                return;
              }
              e.preventDefault();
              sendMessage(e.currentTarget.value);
            }
          }}
          placeholder="메시지 입력... (Enter: 전송)"
          rows={2}
          className="w-full bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-[10px] focus:outline-none focus:border-primary text-white transition-colors resize-none pr-8"
        />
        <button
          onMouseDown={e => e.preventDefault()}
          onClick={() => sendMessage()}
          disabled={!msgContent.trim() && !isComposing}
          className="absolute right-1.5 bottom-1.5 p-1 bg-primary hover:bg-primary/80 disabled:opacity-30 text-white rounded transition-colors"
          title="전송 (Enter)"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
