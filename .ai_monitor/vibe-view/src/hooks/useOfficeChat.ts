/**
 * ------------------------------------------------------------------------
 * FILE: hooks/useOfficeChat.ts
 * DESCRIPTION: 오피스 채팅 ↔ agent_api REST 브릿지 훅.
 *              PTY 직통 대신 /api/agent/chat SSE 스트리밍을 사용한다.
 *              ChatSlot.tsx의 SSE 로직을 오피스 전용으로 추출.
 * REVISION HISTORY:
 * - 2026-04-13 Claude: 초기 구현 — PTY→agent/chat API 전환
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/** 채팅 메시지 */
export interface OfficeChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  ts: string;
  toolName?: string;
  source?: 'dashboard' | 'telegram';
  tgUser?: string;
}

interface UseOfficeChatReturn {
  messages: OfficeChatMessage[];
  isStreaming: boolean;
  sendError: string | null;
  sendMessage: (text: string) => Promise<void>;
  stopStreaming: () => void;
  clearChat: () => void;
  sessionId: string | null;
}

/**
 * 오피스 전용 채팅 훅.
 * /api/agent/chat SSE로 CLI와 실시간 통신한다.
 * @param terminalId 오피스 터미널 ID ("O1", "O2", ...)
 * @param cli 에이전트 CLI ("claude" | "gemini" | "codex")
 * @param yolo 자율 실행 모드
 */
export function useOfficeChat(
  terminalId: string | null,
  cli: string,
  yolo: boolean,
): UseOfficeChatReturn {
  const [messages, setMessages] = useState<OfficeChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busSeqRef = useRef(0);

  // 히스토리 로드 (터미널 변경 시)
  useEffect(() => {
    if (!terminalId) return;
    setMessages([]);
    busSeqRef.current = 0;
    fetch(`/api/agent/chat/history?terminal_id=${terminalId}`)
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
      })
      .catch(() => {});
  }, [terminalId]);

  // 메시지 버스 폴링 (2초) — 텔레그램 동기화
  useEffect(() => {
    if (!terminalId) return;
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(
          `/api/agent/chat/feed?terminal_id=${terminalId}&since=${busSeqRef.current}`
        );
        const data = await resp.json();
        if (data.latest_seq > busSeqRef.current) {
          busSeqRef.current = data.latest_seq;
        }
        if (data.messages?.length) {
          const telegramMsgs: OfficeChatMessage[] = data.messages
            .filter((m: any) => m.source === 'telegram')
            .map((m: any) => ({
              id: `tg-${m.seq}`,
              role: m.role as OfficeChatMessage['role'],
              content: m.content,
              ts: m.ts,
              source: 'telegram' as const,
              tgUser: m.tg_user,
            }));
          if (telegramMsgs.length > 0) {
            setMessages(prev => {
              const existingIds = new Set(prev.map(m => m.id));
              const newOnes = telegramMsgs.filter(m => !existingIds.has(m.id));
              return newOnes.length > 0 ? [...prev, ...newOnes] : prev;
            });
          }
        }
      } catch {
        // 다음 폴링에서 재시도
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [terminalId]);

  // 메시지 전송 (SSE 스트리밍)
  const sendMessage = useCallback(async (text: string) => {
    if (!terminalId || isStreaming) return;
    setSendError(null);

    // 사용자 메시지 추가
    const userMsg: OfficeChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      ts: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setIsStreaming(true);

    // 어시스턴트 플레이스홀더
    const assistantId = `assistant-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      ts: new Date().toISOString(),
    }]);

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          terminal_id: terminalId,
          message: text,
          cli,
          yolo,
        }),
        signal: abort.signal,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
        setSendError(err.detail || err.error || `전송 실패 (${resp.status})`);
        setIsStreaming(false);
        // 빈 어시스턴트 메시지 제거
        setMessages(prev => prev.filter(m => m.id !== assistantId));
        return;
      }

      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let streamDone = false;

      if (reader) {
        try {
          while (!streamDone) {
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
                  setMessages(prev => [...prev, {
                    id: `tool-${Date.now()}-${Math.random()}`,
                    role: 'tool',
                    content: evt.input || '',
                    ts: new Date().toISOString(),
                    toolName: evt.name,
                  }]);
                } else if (evt.type === 'session') {
                  setSessionId(evt.session_id);
                } else if (evt.type === 'done') {
                  if (evt.session_id) setSessionId(evt.session_id);
                  streamDone = true;
                } else if (evt.type === 'error') {
                  setSendError(evt.message || '에이전트 에러');
                  streamDone = true;
                }
              } catch {
                // JSON 파싱 실패 무시
              }
            }
          }
        } finally {
          reader.cancel().catch(() => {});
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setSendError('서버 연결 실패 — 서버가 실행 중인지 확인해봐');
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [terminalId, cli, yolo, isStreaming]);

  // 스트리밍 중단
  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (terminalId) {
      fetch('/api/agent/chat/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terminal_id: terminalId }),
      }).catch(() => {});
    }
  }, [terminalId]);

  // 채팅 초기화
  const clearChat = useCallback(() => {
    setMessages([]);
    setSendError(null);
    busSeqRef.current = 0;
  }, []);

  return { messages, isStreaming, sendError, sendMessage, stopStreaming, clearChat, sessionId };
}
