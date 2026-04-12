/**
 * ------------------------------------------------------------------------
 * FILE: hooks/useOfficePty.ts
 * DESCRIPTION: 오피스 채팅 ↔ PTY 직접 통신 훅.
 *              클래식 메시지 시스템(pg_messages)을 거치지 않고
 *              PTY 서버(9001)와 직접 통신하여 에이전트와 대화한다.
 * REVISION HISTORY:
 * - 2026-04-11 Claude: 초기 구현 — 클래식 분리, PTY 직통 채팅
 * ------------------------------------------------------------------------
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// 메인 서버(9000) 프록시 경유 — PTY 서버 포트를 하드코딩하지 않는다.
// pty_api.py가 /api/pty/office/* 요청을 Node PTY 서버로 투명하게 포워딩한다.
const PTY_BASE = '';

export interface PtySession {
  id: string;           // T1, T2, ...
  running: boolean;
  agent: string;        // 'claude', 'gemini', 'codex'
  slotName: string;
  lastLine: string;
  mainModel: string;
}

export interface PtyChatMessage {
  id: string;
  from: 'user' | string;  // 'user' 또는 에이전트 이름
  content: string;
  timestamp: string;
  type: 'sent' | 'received';
}

// ── PTY 출력 노이즈 필터 ──
// ── PTY 출력 노이즈 판별 ──
// Claude Code CLI의 스피너, 상태바, UI 장식, 에코를 필터링하여 실제 응답만 남긴다.
function isNoiseLine(text: string): boolean {
  const t = text.trim();
  if (t.length < 3) return true;

  // braille 스피너 문자
  if (/^[⠁-⠿⣾⣽⣻⢿⡿⣟⣯⣷]/.test(t)) return true;
  // 터미널 타이틀 (0; 시작 또는 ESC 시퀀스)
  if (/^0;/.test(t) || /\x1b\]0;/.test(text)) return true;
  // Windows cmd.exe 배너
  if (/Microsoft Windows|Microsoft Corporation|chcp\s+\d+|>nul\s*&/.test(t)) return true;
  // 스피너 — 장식 + 단어 + "…" 패턴 (Shenaniganing…, Evaporating…, Cooking… 등)
  if (/^[✢✶✻✽*●◐◑◒◓·•▸►]?\s*[A-Z][a-zéè]+ing…/i.test(t)) return true;
  // 장식 문자 + 짧은 텍스트 (스피너 잔여물)
  if (/^[✢✶✻✽*●◐◑◒◓·•▪▸►▹▻→←↑↓]\s*\S+…?\s*$/.test(t)) return true;
  // 장식 문자로 시작 + 상태 텍스트 (●Ran 2 stop hooks, ✢ · 30s 등)
  if (/^[✢✶✻✽*●◐◑◒◓⎿]/.test(t)) return true;
  // 타이머/토큰 카운터 (30s, ↓10 tokens 등)
  if (/^\(?\d+s\)?$/.test(t) || /↓\d+\s*tokens/i.test(t)) return true;
  // 괄호로 시작하는 상태 메시지 ((running stop hooks… 0/2) 등)
  if (/^\(running\s|^\(waiting\s/i.test(t)) return true;
  // 박스 드로잉 + 구분선
  if (/^[╭╰│├┌└┃┣╮╯┐┘┫─━═]/.test(t)) return true;
  // ❯ 프롬프트 (에코된 입력 포함)
  if (/^❯/.test(t)) return true;
  // Claude Code 버전 배너 + UI 하단바 + 팁
  if (/ClaudeCode|Opus.*context|Claude Max|▐▛|▝▜|▘▘▝|⏵⏵|bypass.*permission|alt\+m.*cycle|esc.*interrupt|Tip:\s*Run\s*\//i.test(t)) return true;
  // stop hooks, 상태 메시지 (앞에 장식 문자 유무 상관없이)
  if (/Ran \d+ stop hooks|stop hook|running stop hooks/i.test(t)) return true;
  if (/^(Thinking|Working|Loading|Searching|Reading|Writing|Review previous session|Resuming)\b/i.test(t)) return true;
  // 빈 줄, 점 반복, ANSI 잔여물, 단순 스피너
  if (/^\s*$/.test(t) || /^\.{2,}$/.test(t) || /^\d+;\d+[Hf]?$/.test(t) || /^[|/\\-] /.test(t)) return true;

  return false;
}

interface UseOfficePtyReturn {
  sessions: PtySession[];
  chatMessages: PtyChatMessage[];
  sendMessage: (terminalId: string, text: string) => Promise<boolean>;
  spawnSession: (agent: string, yolo?: boolean, cwd?: string) => Promise<string | null>;
  sendError: string | null;
  clearChat: () => void;
  ready: boolean; // Claude Code가 ❯ 프롬프트를 표시하여 입력 대기 상태인지
}

/**
 * 오피스 전용 PTY 세션 관리.
 * 클래식(T1~T8)과 완전 분리된 오피스 네임스페이스(O1, O2, ...)를 사용한다.
 */
export function useOfficePty(activeTerminalId: string | null): UseOfficePtyReturn {
  const [sessions, setSessions] = useState<PtySession[]>([]);
  const [chatMessages, setChatMessages] = useState<PtyChatMessage[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const lastSeqRef = useRef<Record<string, number>>({});
  const initializedRef = useRef<Set<string>>(new Set());
  const userMsgsRef = useRef<PtyChatMessage[]>([]);

  // ── 오피스 전용 세션 목록 폴링 (5초) ──
  useEffect(() => {
    const fetchSessions = () => {
      fetch(`${PTY_BASE}/api/pty/office/sessions`)
        .then(r => r.json())
        .then(data => {
          const list: PtySession[] = [];
          for (const [id, sess] of Object.entries(data) as [string, any][]) {
            list.push({
              id,
              running: sess.running,
              agent: sess.agent || '',
              slotName: sess.slot_name || '',
              lastLine: sess.last_line || '',
              mainModel: sess.main_model || '',
            });
          }
          setSessions(list);
        })
        .catch(() => {});
    };
    fetchSessions();
    const timer = setInterval(fetchSessions, 5000);
    return () => clearInterval(timer);
  }, []);

  // ── 선택된 터미널의 PTY 출력 폴링 (2초) ──
  useEffect(() => {
    if (!activeTerminalId) return;

    const fetchOutput = () => {
      const since = lastSeqRef.current[activeTerminalId] || 0;
      fetch(`${PTY_BASE}/api/pty/output/${activeTerminalId}?since=${since}&limit=50`)
        .then(r => r.json())
        .then(data => {
          // 첫 연결: cmd.exe 부팅 노이즈를 건너뛰되, 이후 출력은 모두 표시
          if (!initializedRef.current.has(activeTerminalId)) {
            initializedRef.current.add(activeTerminalId);
            // 부팅 노이즈(cmd.exe 배너, Claude Code 로고 등)만 스킵 — 최근 seq 기준
            // 단, 유저가 이미 메시지를 보냈으면(userMsgsRef) 스킵하지 않음
            if (userMsgsRef.current.length === 0) {
              lastSeqRef.current[activeTerminalId] = data.latest_seq || 0;
              return;
            }
          }

          // ❯ 프롬프트 감지 → ready 상태 설정
          if (data.entries && data.entries.length > 0) {
            const hasPrompt = (data.entries as any[]).some(
              (e: any) => (e.text || '').includes('❯') && !(e.text || '').includes('bypass')
            );
            if (hasPrompt && !ready) setReady(true);

            // 최근 보낸 메시지 텍스트 (에코 필터용)
            const recentSent = userMsgsRef.current
              .slice(-5)
              .map(m => m.content.trim().toLowerCase().replace(/\s+/g, ''));

            // 노이즈 + 에코 필터링
            const meaningful = (data.entries as any[])
              .filter((entry: any) => {
                if (isNoiseLine(entry.text)) return false;
                // 에코 필터: 최근 보낸 메시지와 동일하면 제거
                const clean = (entry.text || '').trim().toLowerCase().replace(/\s+/g, '');
                if (clean.length > 0 && recentSent.some(s => clean.includes(s) || s.includes(clean))) return false;
                return true;
              });

            if (meaningful.length > 0) {
              // 연속된 줄을 하나의 채팅 메시지로 묶기
              const agentName = sessions.find(s => s.id === activeTerminalId)?.agent || 'agent';
              const grouped = meaningful.map((entry: any) => entry.text).join('\n');
              const newMsg: PtyChatMessage = {
                id: `pty-${activeTerminalId}-${meaningful[meaningful.length - 1].seq}`,
                from: agentName,
                content: grouped,
                timestamp: new Date().toISOString(),
                type: 'received',
              };

              setChatMessages(prev => [...prev, newMsg].slice(-200));
            }

            lastSeqRef.current[activeTerminalId] = data.latest_seq;
          }
        })
        .catch(() => {});
    };

    fetchOutput();
    const timer = setInterval(fetchOutput, 2000);
    return () => clearInterval(timer);
  }, [activeTerminalId, sessions]);

  // ── 터미널 변경 시 채팅 초기화 ──
  const prevTerminalRef = useRef(activeTerminalId);
  useEffect(() => {
    if (prevTerminalRef.current !== activeTerminalId) {
      setChatMessages([]);
      userMsgsRef.current = [];
      setReady(false);
      prevTerminalRef.current = activeTerminalId;
    }
  }, [activeTerminalId]);

  // ── 메시지 전송 (PTY write) ──
  const sendMessage = useCallback(async (terminalId: string, text: string): Promise<boolean> => {
    setSendError(null);
    try {
      const res = await fetch(`${PTY_BASE}/api/pty/write/${terminalId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text + '\r' }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        setSendError(err.error === 'not_running'
          ? '터미널이 실행 중이 아니야. 먼저 에이전트를 시작해봐.'
          : `전송 실패: ${err.error || res.status}`);
        return false;
      }

      // 유저 메시지를 채팅에 추가
      const userMsg: PtyChatMessage = {
        id: `user-${Date.now()}`,
        from: 'user',
        content: text,
        timestamp: new Date().toISOString(),
        type: 'sent',
      };
      setChatMessages(prev => [...prev, userMsg]);
      userMsgsRef.current.push(userMsg);
      return true;
    } catch (err) {
      setSendError('PTY 서버 연결 실패 — 서버가 실행 중인지 확인해봐');
      return false;
    }
  }, []);

  // ── 오피스 전용 세션 생성 ──
  const spawnSession = useCallback(async (agent: string, yolo = true, cwd?: string): Promise<string | null> => {
    try {
      const body: Record<string, unknown> = { agent, yolo };
      if (cwd) body.cwd = cwd;
      const res = await fetch(`${PTY_BASE}/api/pty/office/spawn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setSendError('오피스 세션 생성 실패');
        return null;
      }
      const data = await res.json();
      return data.sessionId || null;
    } catch {
      setSendError('PTY 서버 연결 실패');
      return null;
    }
  }, []);

  const clearChat = useCallback(() => {
    setChatMessages([]);
    userMsgsRef.current = [];
  }, []);

  return { sessions, chatMessages, sendMessage, spawnSession, sendError, clearChat, ready };
}
