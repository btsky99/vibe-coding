/**
 * 📄 LanRoomChat.tsx
 * 📝 LAN 그룹 채팅방 — 페어링된 모든 PC가 함께 보는 방. 1:1 채팅과 저장/표시가 완전 분리된다.
 * 🕒 변경 이력:
 * - 2026-07-30 Claude: 신규 — 3대 이상에서 "각각 1:1 창"만 있던 제약 해소. 중앙 릴레이 없이
 *   각자가 자기 피어 전원에게 팬아웃해 방을 성립시킨다.
 */
// [제약 — UI에 반드시 표기] 방의 완전성은 페어링의 완전성에 종속된다. A-B, A-C만 페어링돼 있으면
//   B의 말은 C에게 닿지 않는다(A만 봄). 그래서 미완성 메시가 감지되면 경고를 띄운다.
// [WHY 폴링] 브리지가 stdlib http.server라 WS 수동구현 부담이 크고, 1:1 채팅이 이미 폴링으로
//   충분히 동작한다([[project-lan-bridge]] Phase 2 결정 계승).
import { useCallback, useEffect, useRef, useState } from 'react';
import { Users, Send } from 'lucide-react';
import { API_BASE } from '../../constants';

interface RoomMsg { id: number; from_peer: string; content: string; ts: string }

interface Props {
  /** 페어링된 피어 수 — 2 미만이면 방이 의미 없어 안내만 표시. */
  peerCount: number;
  /** peer_id → 표시 이름 해석기(LanPanel의 peerName 재사용). */
  peerName: (pid: string) => string;
  selfId: string;
  onFlash?: (msg: string) => void;
}

export default function LanRoomChat({ peerCount, peerName, selfId, onFlash }: Props) {
  const [msgs, setMsgs] = useState<RoomMsg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const sinceRef = useRef(0);          // 폴링 커서 — 클로저 갱신 없이 최신값 유지
  const boxRef = useRef<HTMLDivElement>(null);

  // [불변식] since 커서는 ref로만 갱신한다. state로 두면 폴링 클로저가 옛 값을 붙들어
  //   같은 메시지를 무한 재조회한다(1:1 채팅 폴링과 동일한 함정).
  const poll = useCallback(() => {
    fetch(`${API_BASE}/api/lan/chat/room?since=${sinceRef.current}`)
      .then(r => r.json())
      .then((d: { messages?: RoomMsg[] }) => {
        const fresh = d.messages || [];
        if (!fresh.length) return;
        sinceRef.current = fresh[fresh.length - 1].id;
        setMsgs(prev => [...prev, ...fresh].slice(-300));   // 메모리 상한
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [poll]);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [msgs.length]);

  const send = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    const r = await fetch(`${API_BASE}/api/lan/chat-room-send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }).then(r => r.json()).catch(() => ({ ok: false }));
    setSending(false);
    if (!r.ok) { onFlash?.(`❌ ${r.error || '방 전송 실패'}`); return; }
    setInput('');
    poll();                                    // 내 발신분을 즉시 반영
    if (r.failed?.length) {
      const names = r.failed.map((f: { name: string; peer_id: string }) =>
        f.name || f.peer_id.slice(0, 8)).join(', ');
      onFlash?.(`⚠️ 일부 미도달(오프라인): ${names}`);
    }
  };

  if (peerCount < 1) return null;

  return (
    <div className="bg-black/20 rounded p-2 space-y-2">
      <div className="font-medium flex items-center gap-1 text-teal-200">
        <Users className="w-3.5 h-3.5" /> 그룹방 <span className="text-[#888]">({peerCount}대)</span>
      </div>
      <div className="text-[11px] text-[#888]">
        페어링된 모든 PC가 함께 보는 방이에요. 1:1 채팅과는 완전히 분리돼 있어요.
      </div>
      {peerCount >= 2 && (
        <div className="text-[10px] text-yellow-300/80">
          3대 이상이면 <span className="font-medium">모든 쌍이 서로 페어링</span>돼야 전원이 다 봐요.
          안 된 쌍끼리는 서로의 말이 안 보입니다.
        </div>
      )}

      <div ref={boxRef} className="h-48 overflow-y-auto space-y-1 bg-black/30 rounded p-2">
        {msgs.length === 0 && <div className="text-[#666] text-[12px]">아직 메시지가 없어요.</div>}
        {msgs.map(m => {
          const mine = m.from_peer === selfId;
          return (
            <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded px-2 py-1 text-[12px] ${mine ? 'bg-teal-700/60' : 'bg-white/10'}`}>
                {!mine && (
                  <div className="text-[10px] text-teal-300 font-medium">{peerName(m.from_peer)}</div>
                )}
                {/* [보안] React 텍스트 노드 — 자동 escape(XSS 차단). dangerouslySetInnerHTML 금지 */}
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
                <div className="text-[9px] text-white/40 text-right">{m.ts.slice(11, 16)}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') send(); }}
          placeholder="전원에게 보낼 메시지 후 Enter"
          className="flex-1 bg-black/40 rounded px-2 py-1 text-[12px] outline-none" />
        <button onClick={send} disabled={!input.trim() || sending}
          className="px-3 py-1 bg-teal-700/80 hover:bg-teal-700 disabled:opacity-40 rounded text-[12px] flex items-center gap-1">
          <Send className="w-3 h-3" /> 전원
        </button>
      </div>
    </div>
  );
}
