/**
 * ------------------------------------------------------------------------
 * 📄 파일명: terminal/SideBus.tsx
 * 📝 설명: 터미널 우측 '서로 대화' 창 — 노드/에이전트가 중앙 버스에서 주고받는 흐름을
 *          왼쪽 일반 챗과 **동시에** 본다. 나도 발신자로 참여한다.
 *
 * [WHY 접기가 기본인가] 처음 켰을 때 왼쪽 챗이 좁아 보이면 사용자는 이 기능을 켜기도 전에
 *   방해물로 인식한다. 접힘이 기본이고, 새 메시지는 접힌 손잡이의 뱃지로만 알린다.
 * [WHY 패널이 아니라 여기인가] 패널은 한 번에 하나만 보인다 — 대화를 보려면 챗을 닫아야 해
 *   실질적으로 못 쓰는 상태였다. 두 흐름을 동시에 보는 것이 이 컴포넌트의 존재 이유다.
 * [제약] 상태를 소유하지 않는다. 메시지·폴링·발신은 전부 useCentralBus(App 단일 마운트).
 *   여기에 fetch를 넣으면 슬롯 수만큼 폴링이 곱해지고 커서가 갈라진다.
 *
 * 🕒 변경 이력:
 * - 2026-08-09 Claude: 신규 — Phase 11 Task 41.
 * ------------------------------------------------------------------------
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Send } from 'lucide-react';
import type { CentralBus } from '../../hooks/useCentralBus';
import { fmtTime } from '../../hooks/useCentralBus';

const WIDTH_KEY = 'vibe_sidebus_width';
const OPEN_KEY = 'vibe_sidebus_open';
const MIN_W = 220;
const MAX_W = 560;
const DEFAULT_W = 300;

/** 이 픽셀 이내로 바닥에 붙어 있을 때만 새 메시지를 따라간다. */
const STICK_PX = 40;

/**
 * fromAgent: 이 창이 붙어 있는 슬롯의 에이전트 주소('claude:T2').
 * [🔴 없으면 서버가 슬롯 없는 'claude'로 기록한다] 그러면 받는 쪽에 발신자가 '1-?'로
 *   찍혀 답장 주소를 만들 수 없다 — 양방향 대화가 한쪽 방향으로 끝난다. 버스는 App에
 *   하나뿐이라 발신 슬롯을 아는 곳은 이 컴포넌트뿐이다.
 */
export default function SideBus({ bus, fromAgent }: { bus: CentralBus; fromAgent?: string }) {
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) === '1');
  const [width, setWidth] = useState(() => {
    const raw = Number(localStorage.getItem(WIDTH_KEY));
    return raw >= MIN_W && raw <= MAX_W ? raw : DEFAULT_W;
  });
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [allowing, setAllowing] = useState(false);
  const [allowErr, setAllowErr] = useState('');
  const [err, setErr] = useState('');

  const boxRef = useRef<HTMLDivElement>(null);
  /** 사용자가 위로 올려 과거를 읽는 중인지. true면 새 메시지가 와도 화면을 밀지 않는다. */
  const stickRef = useRef(true);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  useEffect(() => { localStorage.setItem(OPEN_KEY, open ? '1' : '0'); }, [open]);
  useEffect(() => { localStorage.setItem(WIDTH_KEY, String(width)); }, [width]);

  // 열려 있는 동안 본 것으로 친다 — 닫혀 있을 때만 뱃지가 쌓여야 의미가 있다.
  useEffect(() => { if (open) bus.markRead(); }, [open, bus.messages.length]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open || !stickRef.current) return;
    const el = boxRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [open, bus.messages.length]);

  const onScroll = () => {
    const el = boxRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_PX;
  };

  // [WHY 전역 리스너인가] 드래그 중 커서가 좁은 손잡이를 벗어나면 mousemove가 끊겨 폭이
  //   중간에 멈춘다. 시작할 때만 window에 붙이고 끝나면 뗀다.
  const startDrag = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startW: width };
    const move = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      // 오른쪽 패널이라 왼쪽으로 끌수록 넓어진다 — 부호를 뒤집는다.
      const next = Math.min(MAX_W, Math.max(MIN_W, d.startW + (d.startX - ev.clientX)));
      setWidth(next);
    };
    const up = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  const send = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    const r = await bus.send(content, undefined, fromAgent);
    setSending(false);
    if (!r.ok) { setErr(r.error || '발신 실패'); return; }
    setInput('');
    setErr('');
    stickRef.current = true;      // 내가 보냈으면 바닥으로 따라간다
  };

  const enabled = !!bus.status?.enabled;
  const connected = !!bus.status?.connected;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="서로 대화 열기"
        className="w-6 shrink-0 border-l border-black/40 bg-[#252526] hover:bg-white/5 flex flex-col items-center justify-center gap-2 transition-colors"
      >
        <ChevronLeft className="w-3.5 h-3.5 text-white/40" />
        {bus.unread > 0 && (
          <span className="px-1 py-0.5 rounded-full bg-primary/30 border border-primary/40 text-[9px] text-white font-bold">
            {bus.unread > 99 ? '99+' : bus.unread}
          </span>
        )}
        <span className="text-[9px] text-white/35 [writing-mode:vertical-rl] tracking-wider">서로 대화</span>
      </button>
    );
  }

  return (
    <div className="flex shrink-0 min-h-0" style={{ width }}>
      {/* 폭 조절 손잡이 */}
      <div
        onMouseDown={startDrag}
        className="w-1 cursor-col-resize bg-black/40 hover:bg-primary/40 transition-colors shrink-0"
        title="드래그해서 폭 조절"
      />
      <div className="flex-1 min-w-0 flex flex-col bg-[#252526] border-l border-black/40">
        <div className="h-7 px-2 flex items-center gap-1.5 border-b border-black/40 shrink-0">
          <span className="text-[10px] font-bold text-[#bbbbbb] tracking-wider">서로 대화</span>
          {bus.selfSeq > 0 && <span className="text-[9px] text-white/35">아픽스 {bus.selfSeq}</span>}
          <span className={`ml-auto text-[9px] ${
            !enabled ? 'text-white/25' : connected ? 'text-green-400/70' : 'text-red-400/70'
          }`}>
            {!enabled ? '미설정' : connected ? (bus.stale ? '⚠️ 낡음' : '연결됨') : '끊김'}
          </span>
          <button onClick={() => setOpen(false)} title="접기" className="p-0.5 text-white/40 hover:text-white">
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* [🔴 지정된 3대에서는 절대 뜨지 않는다] 번호는 호스트명 매핑으로 자동 배정된다
            (src/node_identity.py _DEFAULT_SEQ). 이 안내는 매핑에 없는 **네 번째 PC**가
            붙었을 때만 보이는 폴백이다. 중앙을 안 쓰면(enabled=false) 아예 안 보인다. */}
        {enabled && bus.selfSeq === 0 && (
          <div className="px-2 py-1.5 border-b border-yellow-500/20 bg-yellow-500/5 text-[10px] text-yellow-200/80 leading-relaxed shrink-0">
            이 PC의 번호가 정해지지 않았습니다 — 발신자가 uuid로 표시됩니다.<br />
            <span className="text-yellow-200/50">
              config.json 의 <code>node_seq</code> 에 번호를 넣거나, 알려진 PC라면
              호스트명을 <code>_DEFAULT_SEQ</code> 에 추가하세요.
            </span>
          </div>
        )}

        {/* [🔴 이 배너가 없으면 사용자는 원인을 알 방법이 전혀 없다]
            게이트가 막으면 상대 메시지는 여기 화면에 뜨지만 이 PC의 CLI에는 안 꽂힌다.
            즉 "말은 보이는데 여기 있는 클로드는 답을 안 한다"로 보인다. 예전에는 이걸
            알아내려고 그 PC에서 설정 파일을 열어야 했고, 그러다 BOM 하나로 노드를 통째로
            잃었다(2026-08-11). 판단은 사람이 하되 쓰기는 앱이 한다 — 버튼 하나로 끝낸다. */}
        {enabled && bus.blocked && (
          <div className="px-2 py-1.5 border-b border-amber-500/25 bg-amber-500/5 shrink-0">
            <div className="text-[10px] text-amber-200/85 leading-relaxed">
              {bus.blocked.message}
            </div>
            <div className="mt-1 flex items-center gap-1.5">
              {/* 버튼은 이 자리에서 풀 수 있는 사유일 때만. 손쓸 수 없는 사유에 버튼을
                  달면 눌러도 아무 일이 없어 '고장난 앱'으로 읽힌다. */}
              {bus.blocked.openable && (
                <button
                  onClick={async () => {
                    const seq = bus.blocked?.fromSeq;
                    if (!seq) return;
                    setAllowing(true);
                    const r = await bus.allowNode(seq);
                    setAllowing(false);
                    if (!r.ok) setAllowErr(r.error || '실패');
                  }}
                  disabled={allowing}
                  className="px-2 py-0.5 text-[10px] rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 border border-amber-400/30 disabled:opacity-40"
                >
                  {allowing ? '허용하는 중…' : `${bus.blocked.fromSeq}번 노드 허용`}
                </button>
              )}
              <button
                onClick={bus.dismissBlocked}
                className="px-1.5 py-0.5 text-[10px] text-white/40 hover:text-white/70"
              >
                {bus.blocked.openable ? '나중에' : '닫기'}
              </button>
              {allowErr && <span className="text-[9px] text-red-300/80">{allowErr}</span>}
            </div>
          </div>
        )}

        {!enabled ? (
          <div className="flex-1 flex items-center justify-center p-4 text-center text-[10px] text-white/35 leading-relaxed">
            중앙 대화가 설정되지 않았습니다.<br />
            config.json 의 <code className="text-white/50">central_db</code> 를 채우면 켜집니다.
          </div>
        ) : (
          <div ref={boxRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-2 py-1.5 space-y-1.5 min-h-0">
            {bus.hasMore && bus.messages.length > 0 && (
              <button
                onClick={bus.loadOlder}
                disabled={bus.loadingOlder}
                className="w-full py-1 text-[10px] text-white/40 hover:text-white/70 border border-white/10 rounded disabled:opacity-40"
              >
                {bus.loadingOlder ? '불러오는 중…' : '이전 50개 더 보기'}
              </button>
            )}
            {bus.messages.length === 0 && (
              <div className="text-white/25 text-center py-6 text-[10px]">주고받은 대화가 없습니다</div>
            )}
            {bus.messages.map(m => {
              const mine = bus.isSelf(m);
              const label = bus.labelOf(m.from_node);
              return (
                <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[92%] px-2 py-1 rounded border text-[11px] ${
                    mine ? 'bg-primary/10 border-primary/25' : 'bg-white/5 border-white/10'
                  }`}>
                    <div className="text-[9px] text-white/40 mb-0.5">
                      {mine ? '나' : `${bus.addressOf(m)}${label ? ` (${label})` : ''}`}
                      {m.to_node ? ' → 지정' : ''} · {fmtTime(m.created_at)}
                    </div>
                    <div className="whitespace-pre-wrap break-words text-white/85">{m.content}</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {err && <div className="px-2 py-1 text-[9px] text-red-300 shrink-0">❌ {err}</div>}

        {enabled && (
          <div className="p-1.5 border-t border-black/40 flex gap-1 shrink-0">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={connected ? '모두에게…' : '연결 안 됨'}
              disabled={!connected}
              className="flex-1 min-w-0 bg-black/30 border border-white/10 rounded px-2 py-1 text-[11px] outline-none focus:border-primary/50 disabled:opacity-40 text-white"
            />
            <button
              onClick={send}
              disabled={!connected || sending || !input.trim()}
              className="px-1.5 rounded bg-primary/20 border border-primary/30 text-white disabled:opacity-30"
              title="전송"
            >
              <Send className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
