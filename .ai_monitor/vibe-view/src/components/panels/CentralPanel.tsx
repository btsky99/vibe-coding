/**
 * 📄 파일명: components/panels/CentralPanel.tsx
 * 📝 설명: 중앙 대화(아픽스 서버) 패널 — 여러 PC의 클로드가 한 PG를 공유해 주고받는 대화창.
 *          통신은 전부 로컬 `/api/central/*` 경유. 이 패널은 원격 DB를 직접 알지 않는다.
 * 🕒 변경 이력:
 * - 2026-08-09 Claude: 신규 — Phase 10 Task 29. 백엔드(Task 19~28) 완료분 소비.
 */
// [🔴 이 패널에 원격 실행 UI를 만들지 않는다] api/central_api.py 헤더의 설계 고정 사항이다.
//   중앙은 여러 PC가 붙는 공용 지점이라, 화면에 실행 버튼이 생기면 중앙 DB 계정 하나가
//   전 노드 RCE 권한이 된다. 원격 실행은 LAN 브리지의 3중 게이트 쪽에만 존재한다.
//
// [불변식 — enabled와 connected를 한 색으로 합치지 않는다] '중앙을 안 쓰는 사람'과
//   '서버가 죽은 사람'은 완전히 다른 상태다. 합치면 진짜 장애가 "원래 회색"에 묻힌다
//   (feedback_observability_first / 계획서 Task 29 명시 조건).
//
// [WHY 폴링인가 — NOTIFY를 썼는데도] 서버는 이미 LISTEN으로 0.25초 내 신호를 받지만,
//   그 신호는 서버 프로세스 안에 있다. 브라우저까지 밀어주려면 SSE를 새로 파야 하는데,
//   /api/central/poll 은 신호가 없으면 원격을 조회하지 않고 즉시 반환하도록 설계돼 있어
//   (central_api.poll 주석) 3초 폴링의 실비용이 로컬 왕복뿐이다. SSE 값어치가 없다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Send, Radio, RefreshCw } from 'lucide-react';
import { API_BASE } from '../../constants';

interface CentralMsg {
  id: number;
  from_node: string;
  from_agent: string;
  to_node: string | null;
  to_agent: string | null;
  content: string;
  created_at: string;
}

interface ListenerState {
  running?: boolean;
  mode?: 'off' | 'listen' | 'degraded';
  pending?: boolean;
  last_signal_at?: number;
  last_error?: string;
}

interface CentralStatus {
  enabled: boolean;
  connected: boolean;
  node_id: string;
  pending: number;
  listener: ListenerState;
}

const POLL_MS = 3000;
/** 이 시간을 넘게 상태 갱신이 없으면 값을 낡은 것으로 강등한다(⚠️ + 회색). */
const STALE_MS = 15000;
const MAX_KEEP = 300;

/** 노드 UUID는 화면에 다 못 넣는다 — 앞 8자만. 구분에 충분하고 줄바꿈을 안 만든다. */
const shortNode = (id: string) => (id || '').slice(0, 8) || '?';

/**
 * created_at은 json_response의 default=str을 통과한 파이썬 datetime 문자열이다
 * ("2026-08-09 09:30:06.1+00:00"). JS Date는 공백 구분자를 표준으로 안 받으므로
 * 'T'로 바꿔 넘긴다. 그래도 실패하면 원문을 그대로 보여준다 — 시각을 못 읽었다고
 * 메시지를 숨기면 안 된다.
 */
const fmtTime = (raw: string) => {
  const d = new Date(String(raw || '').replace(' ', 'T'));
  if (isNaN(d.getTime())) return String(raw || '');
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export default function CentralPanel() {
  const [st, setSt] = useState<CentralStatus | null>(null);
  const [msgs, setMsgs] = useState<CentralMsg[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [flash, setFlash] = useState('');
  /** 마지막으로 status 응답을 받은 시각(epoch ms). 0이면 아직 한 번도 못 받음. */
  const [syncedAt, setSyncedAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const lastIdRef = useRef(0);
  const boxRef = useRef<HTMLDivElement>(null);

  /**
   * [불변식] 병합은 항상 id 기준 중복 제거 + 오름차순이다. messages(히스토리)와
   * poll(증분)이 같은 행을 줄 수 있고(내가 보낸 직후 refresh + 폴링), id 순서가
   * 어긋나면 대화가 뒤집힌다. lastIdRef는 표시용이 아니라 '어디까지 봤나' 뿐이다.
   */
  const merge = useCallback((incoming: CentralMsg[]) => {
    if (!incoming?.length) return;
    setMsgs(prev => {
      const byId = new Map<number, CentralMsg>();
      for (const m of prev) byId.set(m.id, m);
      for (const m of incoming) byId.set(m.id, m);
      const merged = [...byId.values()].sort((a, b) => a.id - b.id).slice(-MAX_KEEP);
      lastIdRef.current = merged.length ? merged[merged.length - 1].id : lastIdRef.current;
      return merged;
    });
  }, []);

  /** 화면용 히스토리. [제약] 이 경로는 커서를 밀지 않는다 — 열어보는 것과 '처리함'은 다르다. */
  const loadHistory = useCallback(() => {
    fetch(`${API_BASE}/api/central/messages?limit=50`)
      .then(r => r.json())
      .then((d: { messages?: CentralMsg[] }) => merge(d.messages || []))
      .catch(() => {});
  }, [merge]);

  /**
   * [🔴 커서 소유] poll은 이 노드의 기본 커서(agent_id='')를 전진시킨다. 지금 앱 안에서
   *   /api/central/poll을 부르는 곳은 이 패널뿐이고, consume_pending()은 프로세스 단위
   *   test-and-clear다 — 나중에 다른 소비자를 추가하면 둘 중 하나가 신호를 놓친다.
   *   추가할 때는 소비자별 agent 파라미터를 반드시 다르게 준다.
   */
  const tick = useCallback(() => {
    fetch(`${API_BASE}/api/central/status`)
      .then(r => r.json())
      .then((s: CentralStatus) => {
        setSt(s);
        setSyncedAt(Date.now());
        if (!s.enabled) return;
        return fetch(`${API_BASE}/api/central/poll?limit=50`)
          .then(r => r.json())
          .then((d: { messages?: CentralMsg[] }) => merge(d.messages || []));
      })
      .catch(() => {});
  }, [merge]);

  useEffect(() => {
    loadHistory();
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => clearInterval(t);
  }, [loadHistory, tick]);

  // 낡음 판정은 '경과 시간'이라 응답이 끊긴 동안에도 흘러야 한다 — 별도 타이머로 now를 민다.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [msgs.length]);

  const send = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setSending(true);
    const r = await fetch(`${API_BASE}/api/central/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),          // to_node 생략 = 브로드캐스트
    }).then(res => res.json()).catch(() => ({ ok: false, error: '요청 실패' }));
    setSending(false);
    if (!r.ok) { setFlash(`❌ ${r.error || '발신 실패'}`); return; }
    setInput('');
    setFlash('');
    loadHistory();                                 // 내 발신분은 poll이 걸러내므로 직접 다시 읽는다
  };

  const stale = syncedAt > 0 && now - syncedAt > STALE_MS;
  const enabled = !!st?.enabled;
  const connected = !!st?.connected;
  const mode = st?.listener?.mode || 'off';
  const lastSignal = st?.listener?.last_signal_at || 0;

  const chip = (label: string, value: string, tone: 'ok' | 'warn' | 'bad' | 'idle') => {
    const cls = {
      ok: 'bg-green-500/15 text-green-300 border-green-500/30',
      warn: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
      bad: 'bg-red-500/15 text-red-300 border-red-500/30',
      idle: 'bg-white/5 text-white/40 border-white/10',
    }[tone];
    return (
      <div className={`px-2 py-1 rounded border text-[10px] ${stale && tone !== 'idle' ? 'opacity-50' : ''} ${cls}`}>
        <span className="opacity-60">{label}</span> {value}
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col text-xs text-white/80">
      <div className="px-3 py-2 border-b border-white/10 flex items-center gap-2 shrink-0">
        <Radio className={`w-4 h-4 ${connected ? 'text-green-400' : 'text-white/30'}`} />
        <span className="font-bold">중앙 대화</span>
        {enabled && <span className="text-[10px] text-white/40">node {shortNode(st?.node_id || '')}</span>}
        <button onClick={() => { loadHistory(); tick(); }} className="ml-auto p-1 text-white/40 hover:text-white" title="새로고침">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* [불변식] 설정·연결·리스너를 각각 따로 그린다. 하나로 합치지 말 것. */}
      <div className="px-3 py-2 flex flex-wrap gap-1.5 border-b border-white/10 shrink-0">
        {chip('설정', enabled ? '있음' : '없음', enabled ? 'ok' : 'idle')}
        {chip('연결', !enabled ? '—' : connected ? '연결됨' : '끊김', !enabled ? 'idle' : connected ? 'ok' : 'bad')}
        {chip(
          '수신',
          !enabled ? '—' : mode === 'listen' ? '실시간' : mode === 'degraded' ? '폴링 강등' : '중지',
          !enabled ? 'idle' : mode === 'listen' ? 'ok' : mode === 'degraded' ? 'warn' : 'bad',
        )}
        {enabled && (st?.pending || 0) > 0 && chip('미수신', String(st?.pending), 'warn')}
      </div>

      {/* [feedback_observability_first] 값과 '언제 잰 값인지'를 항상 같이 낸다. */}
      <div className={`px-3 py-1 text-[10px] shrink-0 ${stale ? 'text-yellow-400' : 'text-white/35'}`}>
        {syncedAt === 0
          ? '상태 확인 중…'
          : `${stale ? '⚠️ ' : ''}상태 ${Math.round((now - syncedAt) / 1000)}초 전`}
        {enabled && lastSignal > 0 && ` · 마지막 신호 ${Math.max(0, Math.round(now / 1000 - lastSignal))}초 전`}
        {st?.listener?.last_error ? ` · ${st.listener.last_error}` : ''}
      </div>

      {!enabled ? (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center text-white/40 leading-relaxed">
            <div className="text-white/60 mb-2">중앙 대화가 설정되지 않았습니다</div>
            <div className="text-[10px]">
              config.json 의 <code className="text-white/60">central_db</code> 에<br />
              host · port · user · password · dbname 을 채우면 활성화됩니다.<br />
              <span className="text-white/30">설정 전까지 이 기능은 앱의 어떤 동작에도 개입하지 않습니다.</span>
            </div>
          </div>
        </div>
      ) : (
        <div ref={boxRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
          {msgs.length === 0 && <div className="text-white/30 text-center py-6">주고받은 대화가 없습니다</div>}
          {msgs.map(m => {
            const mine = m.from_node === st?.node_id;
            return (
              <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-2 py-1.5 rounded border ${
                  mine ? 'bg-primary/10 border-primary/25' : 'bg-white/5 border-white/10'
                }`}>
                  <div className="text-[10px] text-white/40 mb-0.5">
                    {mine ? '나' : `${shortNode(m.from_node)}/${m.from_agent || '?'}`}
                    {m.to_node ? ' → 지정' : ' → 전체'} · {fmtTime(m.created_at)}
                  </div>
                  <div className="whitespace-pre-wrap break-words">{m.content}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {flash && <div className="px-3 py-1 text-[10px] text-red-300 shrink-0">{flash}</div>}

      {enabled && (
        <div className="p-2 border-t border-white/10 flex gap-1.5 shrink-0">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={connected ? '모든 노드에게 전송…' : '중앙 서버에 연결되지 않음'}
            disabled={!connected}
            className="flex-1 bg-black/30 border border-white/10 rounded px-2 py-1 outline-none focus:border-primary/50 disabled:opacity-40"
          />
          <button
            onClick={send}
            disabled={!connected || sending || !input.trim()}
            className="px-2 py-1 rounded bg-primary/20 border border-primary/30 text-white disabled:opacity-30"
            title="전송"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
