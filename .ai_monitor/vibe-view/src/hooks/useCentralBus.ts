/**
 * ------------------------------------------------------------------------
 * 📄 파일명: hooks/useCentralBus.ts
 * 📝 설명: 중앙 대화(아픽스 서버) 버스 — 앱 전체가 공유하는 단 하나의 상태 소유자.
 *          상태·폴링·발신·과거조회·표시명 변환·안읽음 집계를 여기서만 한다.
 *
 * [🔴 불변식 — 이 훅은 앱에서 딱 한 번만 마운트한다]
 *   /api/central/poll 은 이 노드의 커서(agent_id='')를 **전진시킨다**. 터미널 슬롯마다
 *   이 훅을 부르면 한 슬롯이 가져간 메시지를 나머지 슬롯이 영영 못 본다. 게다가
 *   consume_pending()은 프로세스 단위 test-and-clear라 신호도 한 쪽만 먹는다.
 *   → App.tsx에서 1회 호출하고 결과를 props로 내려보낸다. 소비 컴포넌트는 표시만 한다.
 *
 * [WHY 폴링인가 — 서버는 NOTIFY를 쓰는데] 서버는 LISTEN으로 0.25초 내 신호를 받지만 그
 *   신호는 서버 프로세스 안에 있다. 브라우저까지 밀려면 SSE를 새로 파야 하는데,
 *   /api/central/poll 은 신호가 없으면 원격을 조회하지 않고 즉시 반환하도록 설계돼 있어
 *   (central_api.poll 주석) 3초 폴링의 실비용이 로컬 왕복뿐이다. SSE 값어치가 없다.
 *
 * 🕒 변경 이력:
 * - 2026-08-09 Claude: 신규 — Phase 11 Task 39. CentralPanel이 홀로 갖던 상태를 앱 공용
 *                      버스로 승격(슬롯마다 폴링하면 커서가 갈라지는 문제).
 * ------------------------------------------------------------------------
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../constants';

export interface CentralMsg {
  id: number;
  from_node: string;
  from_agent: string;
  to_node: string | null;
  to_agent: string | null;
  content: string;
  created_at: string;
}

export interface ListenerState {
  running?: boolean;
  mode?: 'off' | 'listen' | 'degraded';
  pending?: boolean;
  last_signal_at?: number;
  last_error?: string;
}

export interface CentralStatus {
  enabled: boolean;
  connected: boolean;
  node_id: string;
  pending: number;
  listener: ListenerState;
}

export interface NodeRef {
  node_id: string;
  node_seq: number;
  node_label: string;
}

/** poll 응답의 주입 결과 1건. ok=false면 그 메시지는 화면까지만 오고 CLI엔 안 꽂혔다. */
export interface InjectResult {
  id: number;
  ok: boolean;
  why: string;
  from_seq?: number;
}

/**
 * 상대가 답할 수 없는 상태를 화면이 알아야 하는 이유 —
 * 게이트가 막으면 메시지는 화면에 뜨지만 그 PC의 CLI는 말이 온 사실 자체를 모른다.
 * 사용자에게는 '상대가 답이 없다'로만 보여, 이 값이 없으면 원인을 알 길이 전혀 없다.
 * 열 수 있는 것(허용 안 된 노드)만 배너로 올린다 — 슬롯 미기동 등은 사용자가 손쓸 수 없다.
 */
export interface BlockedNotice {
  fromSeq: number;
  why: string;
  /** [허용] 버튼으로 이 자리에서 풀 수 있는가. false면 안내만 한다. */
  openable: boolean;
  /** 사람이 읽을 한 줄. 사유 코드를 그대로 보여주면 아무도 못 고친다. */
  message: string;
}

const OPENABLE = new Set(['remote_disabled', 'node_not_allowed']);

/**
 * 사유 코드 → 사람이 읽고 **행동할 수 있는** 문장.
 *
 * [WHY 코드를 그대로 안 쓰나] 'slot_not_running' 을 화면에 찍으면 사용자는 그것이
 * 자기 PC 얘기인지 상대 PC 얘기인지조차 모른다. 이 창의 목적은 '왜 답이 없지'에
 * 답하는 것이고, 답이 되려면 다음 행동이 보여야 한다.
 * [제약] 여기 없는 사유는 배너를 띄우지 않는다 — 손쓸 수 없는 실패까지 알리면
 *   배너가 상시 표시돼 정작 고칠 수 있는 것이 묻힌다.
 */
function describeBlock(why: string, seq: number): { openable: boolean; message: string } | null {
  if (why.startsWith('remote_disabled'))
    return { openable: true, message: `아픽스 ${seq}번의 말이 이 PC의 CLI에 전달되지 않았습니다 — 원격 주입이 꺼져 있습니다.` };
  if (why.startsWith('node_not_allowed'))
    return { openable: true, message: `아픽스 ${seq}번이 이 PC의 허용 목록에 없어 CLI에 전달되지 않았습니다.` };
  if (why.startsWith('slot_not_running'))
    return { openable: false, message: '받을 터미널이 떠 있지 않아 CLI에 전달되지 않았습니다 — 터미널 슬롯을 하나 켜 주세요.' };
  if (why.startsWith('rate_limited'))
    return { openable: false, message: '짧은 시간에 너무 많이 와서 잠시 주입을 멈췄습니다(5분 뒤 자동 해제).' };
  return null;
}

const POLL_MS = 3000;
/** 이 시간을 넘게 상태 갱신이 없으면 값을 낡은 것으로 강등한다(⚠️ + 회색). */
const STALE_MS = 15000;
/** 오른쪽 '서로 대화' 창의 기본 보관량. 왼쪽(300)보다 짧은 이유 — 노드 수만큼 유입이 곱해진다. */
const KEEP_BASE = 150;
/** '이전 N개 더 보기' 한 번에 가져오는 양. 상한도 같은 폭으로 늘린다. */
const PAGE = 50;
/** 명부는 거의 안 바뀐다 — 폴링에 얹지 않고 이 주기로만 새로 읽는다. */
const NODES_REFRESH_MS = 60000;
/**
 * 읽은 지점(id)을 앱 재시작 너머로 남기는 키.
 * [WHY 영속인가] 이게 없으면 lastReadId가 매 실행마다 0에서 시작해, 부팅 직후 불러온
 *   히스토리 전부가 '새 메시지'로 집계된다. SideBus는 접힘이 기본이라 뱃지가 유일한
 *   알림 수단인데, 켤 때마다 '50'이 떠 있으면 사용자는 뱃지를 무시하게 된다 —
 *   알림 장치가 조용히 무력화되는 쪽이 안 뜨는 것보다 나쁘다.
 */
const READ_KEY = 'vibe_central_read_id';

/** 노드 UUID는 화면에 다 못 넣는다 — 앞 8자만. 명부에 없는 노드의 폴백 표시. */
export const shortNode = (id: string) => (id || '').slice(0, 8) || '?';

/**
 * created_at은 json_response의 default=str을 통과한 파이썬 datetime 문자열이다
 * ("2026-08-09 09:30:06.1+00:00"). JS Date는 공백 구분자를 표준으로 안 받으므로
 * 'T'로 바꿔 넘긴다. 그래도 실패하면 원문을 그대로 보여준다 — 시각을 못 읽었다고
 * 메시지를 숨기면 안 된다.
 */
export const fmtTime = (raw: string) => {
  const d = new Date(String(raw || '').replace(' ', 'T'));
  if (isNaN(d.getTime())) return String(raw || '');
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

/**
 * from_agent('claude:T1' | 'claude')에서 슬롯 번호만 뽑는다.
 * [제약] 외부 connector(디스코드·텔레그램)가 보낸 값은 슬롯이 없다 — 0을 돌려주고
 *   호출부가 번호 없이 그린다. 여기서 1로 폴백하면 남의 슬롯을 사칭하게 된다.
 */
export const slotOfAgent = (agent: string): number => {
  const m = /[:@]?T(\d+)\b/i.exec(String(agent || ''));
  return m ? Number(m[1]) : 0;
};

export interface CentralBus {
  status: CentralStatus | null;
  messages: CentralMsg[];
  stale: boolean;
  /** 마지막 status 응답 시각(epoch ms). 0이면 아직 한 번도 못 받음. */
  syncedAt: number;
  /** 매초 갱신되는 현재 시각 — '몇 초 전' 표시가 응답이 끊긴 동안에도 흘러야 한다. */
  nowMs: number;
  /** 수동 새로고침(버튼). 폴링과 같은 경로를 탄다. */
  refresh: () => void;
  selfNodeId: string;
  selfSeq: number;
  nodes: NodeRef[];
  unread: number;
  hasMore: boolean;
  loadingOlder: boolean;
  send: (content: string, to?: { to_node?: string; to_agent?: string },
         fromAgent?: string) => Promise<{ ok: boolean; error?: string }>;
  loadOlder: () => Promise<number>;
  markRead: () => void;
  /** 'a3f9…/claude:T1' 같은 원본 → '아픽스 3-1' (라벨은 호출부가 붙인다) */
  addressOf: (msg: CentralMsg) => string;
  labelOf: (nodeId: string) => string;
  isSelf: (msg: CentralMsg) => boolean;
  /** 사용자가 열 수 있는 '주입 막힘'. null이면 배너를 그리지 않는다. */
  blocked: BlockedNotice | null;
  /** 그 노드를 허용 목록에 넣는다(설정 쓰기는 서버가 한다). */
  allowNode: (seq: number) => Promise<{ ok: boolean; error?: string }>;
  dismissBlocked: () => void;
}

export function useCentralBus(): CentralBus {
  const [status, setStatus] = useState<CentralStatus | null>(null);
  const [messages, setMessages] = useState<CentralMsg[]>([]);
  const [nodes, setNodes] = useState<NodeRef[]>([]);
  const [selfNodeId, setSelfNodeId] = useState('');
  const [selfSeq, setSelfSeq] = useState(0);
  const [syncedAt, setSyncedAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [lastReadId, setLastReadId] = useState(() => {
    const raw = Number(localStorage.getItem(READ_KEY));
    return Number.isFinite(raw) && raw > 0 ? raw : 0;
  });
  const [hasMore, setHasMore] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [blocked, setBlocked] = useState<BlockedNotice | null>(null);

  /**
   * 주입 결과에서 '사용자가 열 수 있는 막힘'만 골라 배너 대상으로 세운다.
   *
   * [WHY 마지막 1건만 들고 있나] 같은 노드가 여러 줄을 보내면 전부 같은 이유로 막힌다.
   *   목록으로 쌓으면 배너가 도배되고 사용자가 할 일은 여전히 버튼 하나뿐이다.
   * [제약] why는 'node_not_allowed(seq=3)'처럼 값이 붙어 오므로 접두사로 판정한다.
   *   완전일치로 비교하면 그 경우가 조용히 누락된다.
   */
  const noteBlocked = useCallback((results: InjectResult[]) => {
    for (const r of results) {
      if (r.ok) continue;
      const seq = r.from_seq || 0;
      const desc = describeBlock(r.why || '', seq);
      if (!desc) continue;
      // [제약] 열 수 있는 막힘은 발신 번호를 알아야 버튼이 성립한다. 번호가 0이면
      //   허용할 대상을 특정할 수 없으므로 배너를 띄우지 않는다(누구를 허용하라는
      //   말인지 알 수 없는 버튼은 없느니만 못하다).
      if (desc.openable && seq <= 0) continue;
      setBlocked({ fromSeq: seq, why: r.why, ...desc });
      return;
    }
  }, []);

  /** 배너의 [허용] — 설정 쓰기는 서버가 한다(사용자가 파일을 손대면 안 된다). */
  const allowNode = useCallback(async (seq: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/central/allow-node`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seq }),
      });
      const data = await res.json();
      if (data?.ok) { setBlocked(null); return { ok: true }; }
      return { ok: false, error: String(data?.error || '실패') };
    } catch {
      return { ok: false, error: '서버 응답 없음' };
    }
  }, []);

  const dismissBlocked = useCallback(() => setBlocked(null), []);

  /** 보관 상한. '이전 더 보기'를 누르면 그만큼 늘린다 — 방금 불러온 과거를 즉시 잘라내면 모순이다. */
  const keepRef = useRef(KEEP_BASE);
  const oldestRef = useRef(0);

  /**
   * [불변식] 병합은 항상 id 기준 중복 제거 + 오름차순이다. messages(히스토리)와
   * poll(증분)이 같은 행을 줄 수 있고(내가 보낸 직후 refresh + 폴링), id 순서가
   * 어긋나면 대화가 뒤집힌다.
   */
  const merge = useCallback((incoming: CentralMsg[]) => {
    if (!incoming?.length) return;
    setMessages(prev => {
      const byId = new Map<number, CentralMsg>();
      for (const m of prev) byId.set(m.id, m);
      for (const m of incoming) byId.set(m.id, m);
      const merged = [...byId.values()].sort((a, b) => a.id - b.id).slice(-keepRef.current);
      oldestRef.current = merged.length ? merged[0].id : 0;
      return merged;
    });
  }, []);

  /** 화면용 히스토리. [제약] 이 경로는 커서를 밀지 않는다 — 열어보는 것과 '처리함'은 다르다. */
  const loadHistory = useCallback(() => {
    fetch(`${API_BASE}/api/central/messages?limit=${PAGE}`)
      .then(r => r.json())
      .then((d: { messages?: CentralMsg[] }) => merge(d.messages || []))
      .catch(() => {});
  }, [merge]);

  const loadNodes = useCallback(() => {
    fetch(`${API_BASE}/api/central/nodes`)
      .then(r => r.json())
      .then((d: { nodes?: NodeRef[]; self_node_id?: string; self_seq?: number }) => {
        setNodes(d.nodes || []);
        if (d.self_node_id) setSelfNodeId(d.self_node_id);
        if (typeof d.self_seq === 'number') setSelfSeq(d.self_seq);
      })
      .catch(() => {});
  }, []);

  const tick = useCallback(() => {
    fetch(`${API_BASE}/api/central/status`)
      .then(r => r.json())
      .then((s: CentralStatus) => {
        setStatus(s);
        setSyncedAt(Date.now());
        if (s.node_id) setSelfNodeId(s.node_id);
        if (!s.enabled) return;
        return fetch(`${API_BASE}/api/central/poll?limit=${PAGE}`)
          .then(r => r.json())
          .then((d: { messages?: CentralMsg[]; injected?: InjectResult[] }) => {
            merge(d.messages || []);
            noteBlocked(d.injected || []);
          });
      })
      .catch(() => {});
  }, [merge, noteBlocked]);

  useEffect(() => {
    loadHistory();
    loadNodes();
    tick();
    const t = setInterval(tick, POLL_MS);
    const tn = setInterval(loadNodes, NODES_REFRESH_MS);
    return () => { clearInterval(t); clearInterval(tn); };
  }, [loadHistory, loadNodes, tick]);

  // 낡음 판정은 '경과 시간'이라 응답이 끊긴 동안에도 흘러야 한다 — 별도 타이머로 now를 민다.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  /**
   * 본문 맨 앞의 @토큰을 수신 대상으로 바꾼다. '@1-1'(주소)과 '@프론트'(이름) 둘 다 받는다.
   *
   * [🔴 못 찾으면 브로드캐스트로 보낸다 — 막지 않는다] 오타 하나로 메시지가 사라지는 편이
   *   엉뚱한 데로 가는 것보다 나쁘다. central_api.send가 to_node를 비우면 브로드캐스트로
   *   두는 것과 같은 판단이다(그 함수 주석 참조).
   * [제약] @토큰은 본문에서 지우지 않는다 — 받는 쪽 화면에 '누구에게 한 말인지'가 남아야
   *   여러 노드가 섞인 버스에서 맥락을 잃지 않는다.
   */
  const resolveMention = useCallback((text: string): { to_node?: string; to_agent?: string } => {
    const m = /^@(\S+)/.exec(text.trim());
    if (!m) return {};
    const token = m[1].replace(/[,:]$/, '');

    // ① 주소 형식 '1-1' / '아픽스 1-1'의 숫자쌍
    const addr = /^(?:아픽스)?(\d+)-(\d+)$/.exec(token);
    if (addr) {
      const seq = Number(addr[1]);
      const slot = Number(addr[2]);
      const ref = nodes.find(n => n.node_seq === seq);
      if (ref) return { to_node: ref.node_id, to_agent: `claude:T${slot}` };
      return {};
    }

    // ② 이름 — config의 slot_names는 이 PC 것만 알 수 있으므로, 노드 라벨과만 대조한다.
    //    (다른 PC의 터미널 이름까지 풀려면 명부에 이름을 실어야 한다 — 지금 범위 밖)
    const byLabel = nodes.find(n => n.node_label && n.node_label.toLowerCase() === token.toLowerCase());
    if (byLabel) return { to_node: byLabel.node_id };
    return {};
  }, [nodes]);

  const send = useCallback(async (content: string, to?: { to_node?: string; to_agent?: string },
                                  fromAgent?: string) => {
    const body = content.trim();
    if (!body) return { ok: false, error: '빈 메시지' };
    // 호출부가 대상을 명시하지 않았을 때만 멘션을 해석한다.
    if (!to || (!to.to_node && !to.to_agent)) to = resolveMention(body);
    const r = await fetch(`${API_BASE}/api/central/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // [🔴 from_agent를 빼면 답장 주소가 만들어지지 않는다] 서버 기본값은 슬롯 없는
      //   'claude'라, 받는 쪽에 '1-?'로 찍혀 누구에게 답해야 할지가 사라진다. 발신 슬롯을
      //   아는 곳은 호출부(SideBus)뿐이므로 여기서 그대로 실어 보낸다.
      body: JSON.stringify({ content: body, ...(to || {}),
                             ...(fromAgent ? { from_agent: fromAgent } : {}) }),
    }).then(res => res.json()).catch(() => ({ ok: false, error: '요청 실패' }));
    // 내 발신분은 poll이 걸러내므로(자기 노드 제외) 직접 다시 읽어야 화면에 남는다.
    if (r.ok) loadHistory();
    return r;
  }, [loadHistory, resolveMention]);

  const loadOlder = useCallback(async () => {
    if (loadingOlder || !hasMore) return 0;
    const before = oldestRef.current;
    if (!before) return 0;
    setLoadingOlder(true);
    try {
      const d = await fetch(`${API_BASE}/api/central/messages?limit=${PAGE}&before_id=${before}`)
        .then(r => r.json())
        .catch(() => ({ messages: [] as CentralMsg[] }));
      const rows: CentralMsg[] = d.messages || [];
      // 상한을 먼저 늘린다 — merge가 slice(-keep)로 자르므로 순서가 뒤바뀌면 방금 받은 게 사라진다.
      keepRef.current += PAGE;
      merge(rows);
      if (rows.length < PAGE) setHasMore(false);
      return rows.length;
    } finally {
      setLoadingOlder(false);
    }
  }, [hasMore, loadingOlder, merge]);

  const nodeById = useMemo(() => {
    const m = new Map<string, NodeRef>();
    for (const n of nodes) m.set(n.node_id, n);
    return m;
  }, [nodes]);

  /** 같은 번호를 두 노드가 쓰면 화면에서 한 대가 다른 대를 사칭한다 — ⚠로 드러낸다. */
  const dupSeq = useMemo(() => {
    const seen = new Map<number, string>();
    const dup = new Set<number>();
    for (const n of nodes) {
      const prev = seen.get(n.node_seq);
      if (prev && prev !== n.node_id) dup.add(n.node_seq);
      else seen.set(n.node_seq, n.node_id);
    }
    return dup;
  }, [nodes]);

  const addressOf = useCallback((msg: CentralMsg) => {
    const ref = nodeById.get(msg.from_node);
    const slot = slotOfAgent(msg.from_agent);
    if (!ref) return `${shortNode(msg.from_node)}${slot ? `-${slot}` : ''}`;
    const warn = dupSeq.has(ref.node_seq) ? '⚠' : '';
    return `아픽스 ${ref.node_seq}${slot ? `-${slot}` : ''}${warn}`;
  }, [dupSeq, nodeById]);

  const labelOf = useCallback((nodeId: string) => nodeById.get(nodeId)?.node_label || '', [nodeById]);

  const isSelf = useCallback((msg: CentralMsg) => !!selfNodeId && msg.from_node === selfNodeId, [selfNodeId]);

  const unread = useMemo(
    () => messages.filter(m => m.id > lastReadId && m.from_node !== selfNodeId).length,
    [messages, lastReadId, selfNodeId],
  );

  const markRead = useCallback(() => {
    setLastReadId(prev => {
      const last = messages.length ? messages[messages.length - 1].id : prev;
      const next = Math.max(prev, last);
      // [제약] 저장 실패(할당량 초과·프라이빗 모드)를 삼킨다 — 읽음 표시가 안 남는 것보다
      //   대화창이 예외로 죽는 쪽이 훨씬 나쁘다. 최악이라도 이번 실행 안에서는 정상 동작한다.
      if (next !== prev) { try { localStorage.setItem(READ_KEY, String(next)); } catch { /* 무시 */ } }
      return next;
    });
  }, [messages]);

  const refresh = useCallback(() => { loadHistory(); loadNodes(); tick(); }, [loadHistory, loadNodes, tick]);

  return {
    status,
    messages,
    stale: syncedAt > 0 && now - syncedAt > STALE_MS,
    syncedAt,
    nowMs: now,
    refresh,
    selfNodeId,
    selfSeq,
    nodes,
    unread,
    hasMore,
    loadingOlder,
    send,
    loadOlder,
    markRead,
    addressOf,
    labelOf,
    isSelf,
    blocked,
    allowNode,
    dismissBlocked,
  };
}
