/*
 * 📄 파일명: components/panels/LanPanel.tsx
 * 📝 설명: LAN 브리지 패널 — 같은 네트워크의 다른 바이브코딩을 자동발견하고 페어링(6자리 코드)한 뒤
 *          파일을 주고받는 UI. 실제 통신은 lan_bridge 프로세스가, 이 패널은 /api/lan/* 만 호출.
 * 🕒 변경 이력:
 * - 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 9 (파일 전송 UI). 채팅은 Phase 2.
 * - 2026-07-22 Claude: Phase 3 — 원격 Claude 에이전트 실행 UI(전송/승인팝업/출력뷰/마스터토글).
 * - 2026-07-22 Claude: Tailscale/VPN 지원 — 수동 IP 페어링 입력 + 페어링된 기기(발견 안 돼도)를
 *   전송 대상으로 노출. 발견 목록은 미페어링 후보만 표시.
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { Wifi, WifiOff, ShieldAlert, Send, Link2, RefreshCw, MessageSquare, FolderOpen,
  Terminal, Play, Check, X } from 'lucide-react';
import { API_BASE } from '../../constants';
import LanExecDirs from './LanExecDirs';
import LanRoomChat from './LanRoomChat';

interface Peer { peer_id: string; name: string; ip: string; http_port: number }
interface Trusted { peer_id: string; name: string; paired_at: string; exec_trust?: string }
interface ChatMsg { id: number; from_peer: string; to_peer: string; content: string; ts: string }
interface PendingExec { exec_id: string; from_peer: string; task: string; ts: string; exec_trust?: string; target_dir?: string; _seenAt?: number }
/** 상대가 공개한 허용 폴더 — 요청 시 이 목록에서만 고를 수 있다(임의 경로 입력 불가). */
interface PeerDir { path: string; mode: 'copy' | 'direct'; label?: string; exists?: boolean }
/** 진행 중/끝난 원격 실행 1건. peer_id를 키로 보관해 여러 대를 동시에 몰 수 있다. */
interface ExecRun { execId: string; peerId: string; dir: string; out: string; done: boolean }
const PENDING_TTL_MS = 5 * 60 * 1000;   // 승인 대기 5분 — 자리비움 시 자동 거부
interface OutChunk { chunk: string; done: boolean; ts: string }
interface LanStatus {
  running: boolean; firewall_ok?: boolean; self_id?: string; name?: string;
  pending_code?: string | null; online?: Peer[]; trusted?: Trusted[]; error?: string;
}

export default function LanPanel() {
  const [st, setSt] = useState<LanStatus>({ running: false });
  const [myCode, setMyCode] = useState<string>('');
  const [target, setTarget] = useState<Peer | null>(null);
  const [inputCode, setInputCode] = useState('');
  // [Tailscale] 수동 IP 페어링 — 발견 안 되는 다른 네트워크/VPN 상대를 IP로 직접 연결.
  const [manualIp, setManualIp] = useState('');
  const [manualPort, setManualPort] = useState('');
  const [manualCode, setManualCode] = useState('');
  const [sendPeer, setSendPeer] = useState('');
  const [sendPath, setSendPath] = useState('');
  const [flash, setFlash] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState('');
  const sinceRef = useRef(0);      // 마지막 수신 메시지 id — 증분 폴링 커서
  const selfRef = useRef('');      // 내 peer_id (메시지 좌/우 정렬 판정)
  // [Phase3] 원격 실행 상태
  const [execEnabled, setExecEnabled] = useState(false);   // 이 PC의 원격실행 수락 토글(config)
  const [pending, setPending] = useState<PendingExec[]>([]); // 승인 대기 요청(대상측)
  const [autoNext, setAutoNext] = useState(false);          // 승인 시 '자동승인 격상' 체크
  const [execTask, setExecTask] = useState('');             // 보낼 태스크(요청자)
  // [Phase A] 상대가 허용한 폴더 목록 + 선택값. 상대 토글이 꺼져 있으면 peerExecOn=false로 안내.
  const [peerDirs, setPeerDirs] = useState<PeerDir[]>([]);
  const [peerExecOn, setPeerExecOn] = useState(true);
  const [targetDir, setTargetDir] = useState('');
  // [다중 실행] peer_id → 실행 1건. 백엔드는 exec_id별로 프로세스·작업공간이 분리돼 원래부터
  //   병렬이었지만 UI가 단일 execId 슬롯이라 한 대씩만 몰 수 있었다. 피어별 맵으로 해소.
  //   [불변식] 같은 피어에 동시 2건은 여전히 금지 — 이전 exec를 잊고 orphan 스트림을 남기는
  //   문제(리뷰 W6)는 '피어당 1건'으로 막는다.
  const [runs, setRuns] = useState<Record<string, ExecRun>>({});
  const runsRef = useRef<Record<string, ExecRun>>({});      // 폴링 클로저용(최신값 유지)
  const pendingRef = useRef<PendingExec[]>([]);             // [리뷰W7] 병합/만료 계산 소스(업데이터 순수화)

  // [리뷰W7] 대기 목록 갱신을 ref+state 동시 반영 — 업데이터에서 부수효과 분리.
  const setPendingSynced = useCallback((next: PendingExec[]) => {
    pendingRef.current = next;
    setPending(next);
  }, []);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/lan/status`).then(r => r.json()).then(setSt).catch(() => {});
  }, []);

  // [WHY] 3초 폴링 — 발견/온오프라인이 실시간이라 App.tsx 코디네이터 관례와 동일 주기.
  useEffect(() => { refresh(); const t = setInterval(refresh, 3000); return () => clearInterval(t); }, [refresh]);

  const isTrusted = (pid: string) => (st.trusted || []).some(t => t.peer_id === pid);

  const enableBridge = async () => {
    // config에 플래그 저장(부분 병합) — 브리지는 서버 부팅 때 기동되므로 재시작 후 활성.
    await fetch(`${API_BASE}/api/config/update`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lan_bridge_enabled: true }),
    }).catch(() => {});
    setFlash('✅ 설정 저장됨 — 앱을 재시작하면 LAN 브리지가 켜집니다 (방화벽 위해 관리자 권한 권장)');
  };

  const beginPair = async () => {
    const r = await fetch(`${API_BASE}/api/lan/pair-begin`, { method: 'POST' }).then(r => r.json());
    if (r.code) setMyCode(r.code);
  };

  const doConnect = async () => {
    if (!target || !inputCode) return;
    const r = await fetch(`${API_BASE}/api/lan/pair-connect`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip: target.ip, http_port: target.http_port, code: inputCode }),
    }).then(r => r.json());
    setFlash(r.ok ? `✅ ${target.name} 페어링 완료` : `❌ ${r.error || '페어링 실패'}`);
    setTarget(null); setInputCode(''); refresh();
  };

  // [Tailscale] IP 직접 입력 페어링 — 발견(UDP)이 못 넘는 다른 네트워크/VPN 상대 연결.
  //   포트 기본 9020(브리지 시작 포트). 성공 시 상대는 st.trusted에 뜨고 오프라인이어도 전송 가능.
  const doManualConnect = async () => {
    const ip = manualIp.trim();
    const port = parseInt(manualPort, 10) || 9020;
    if (!ip || !manualCode) return;
    const r = await fetch(`${API_BASE}/api/lan/pair-connect`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, http_port: port, code: manualCode }),
    }).then(r => r.json()).catch(() => ({}));
    setFlash(r.ok ? `✅ ${r.name || ip} 페어링 완료` : `❌ ${r.error || '페어링 실패(IP/포트/코드 확인)'}`);
    if (r.ok) { setManualIp(''); setManualPort(''); setManualCode(''); }
    refresh();
  };

  // [WHY] PyWebView 네이티브 앱이라 <input type=file>은 경로를 못 주고(보안상 fakepath),
  //   전송엔 실제 절대경로가 필요. 백엔드 tkinter 파일 다이얼로그(/api/browse-file)로 경로 획득.
  const browseFile = async () => {
    const r = await fetch(`${API_BASE}/api/browse-file`).then(r => r.json()).catch(() => ({}));
    if (r.path) setSendPath(r.path);
  };

  const doSend = async () => {
    if (!sendPeer || !sendPath) return;
    setFlash('전송 중…');
    const r = await fetch(`${API_BASE}/api/lan/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: sendPeer, path: sendPath }),
    }).then(r => r.json());
    setFlash(r.ok ? `✅ 전송 완료` : `❌ ${r.error || '전송 실패'}`);
  };

  // [WHY] 전송 대상 피어가 정해지면 그 피어와의 대화를 2초 증분 폴링. 피어 전환 시 커서/목록 리셋.
  useEffect(() => {
    if (!sendPeer) { setMessages([]); sinceRef.current = 0; return; }
    setMessages([]); sinceRef.current = 0;
    const poll = () => {
      fetch(`${API_BASE}/api/lan/chat?peer_id=${encodeURIComponent(sendPeer)}&since=${sinceRef.current}`)
        .then(r => r.json()).then((d: { self_id?: string; messages?: ChatMsg[] }) => {
          if (d.self_id) selfRef.current = d.self_id;
          const ms = d.messages || [];
          if (ms.length) {
            sinceRef.current = ms[ms.length - 1].id;
            setMessages(prev => [...prev, ...ms]);
          }
        }).catch(() => {});
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => clearInterval(t);
  }, [sendPeer]);

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!sendPeer || !text) return;
    setChatInput('');
    // 발신분은 다음 폴링에서 DB를 통해 돌아옴(내 DB에도 저장됨) — 낙관적 append 안 함(중복 방지).
    await fetch(`${API_BASE}/api/lan/chat-send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: sendPeer, content: text }),
    }).catch(() => {});
  };

  // [Phase3] 승인 대기 폴링(대상측) — 3초. 게이트 OFF면 enabled=false로 즉시 빈 목록.
  // [불변식] 브리지 pending-drain은 1회성(큐 비움)이라 서버가 매번 새로 준 것만 반환한다.
  //   → 프론트가 덮어쓰면 팝업이 3초 뒤 사라진다. 반드시 exec_id로 dedupe 누적(merge)하고,
  //   승인/거부로만 제거. TTL(5분) 초과분은 자동 거부(자리비움 대비, Task 11).
  useEffect(() => {
    if (!st.running) return;
    const poll = () => {
      fetch(`${API_BASE}/api/lan/exec/pending`).then(r => r.json())
        .then((d: { enabled?: boolean; pending?: PendingExec[] }) => {
          setExecEnabled(!!d.enabled);
          if (!d.enabled) { setPendingSynced([]); return; }
          // [리뷰W7] 병합/만료 계산을 ref 기반으로 업데이터 밖에서 수행 → setState는 순수.
          const now = Date.now();
          const seen = new Set(pendingRef.current.map(p => p.exec_id));
          const fresh = (d.pending || []).filter(p => !seen.has(p.exec_id))
            .map(p => ({ ...p, _seenAt: now }));
          let merged = [...pendingRef.current, ...fresh];
          const expired = merged.filter(p => now - (p._seenAt || now) > PENDING_TTL_MS);
          if (expired.length) {
            const expIds = new Set(expired.map(p => p.exec_id));
            merged = merged.filter(p => !expIds.has(p.exec_id));
            expired.forEach(p => { void rejectExec(p); });   // 자리비움 자동 거부
          }
          setPendingSynced(merged);
        }).catch(() => {});
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st.running]);

  useEffect(() => { runsRef.current = runs; }, [runs]);

  // [다중 실행] 진행 중인 모든 exec의 출력을 하나의 인터벌로 폴링한다.
  //   [WHY 단일 인터벌] 실행별 useEffect를 두면 runs가 바뀔 때마다 effect가 재생성돼
  //   폴링이 리셋되고, 브리지 exec-output-drain은 1회성이라 그 틈에 청크를 흘릴 수 있다.
  //   deps=[]로 고정하고 최신 runs는 ref에서 읽는다.
  useEffect(() => {
    if (!st.running) return;
    const poll = () => {
      const active = Object.values(runsRef.current).filter(r => !r.done);
      active.forEach(run => {
        fetch(`${API_BASE}/api/lan/exec/output?exec_id=${encodeURIComponent(run.execId)}`)
          .then(r => r.json()).then((d: { chunks?: OutChunk[] }) => {
            const chunks = d.chunks || [];
            if (!chunks.length) return;
            setRuns(prev => {
              const cur = prev[run.peerId];
              if (!cur || cur.execId !== run.execId) return prev;   // 그새 교체된 실행은 무시
              return {
                ...prev,
                [run.peerId]: {
                  ...cur,
                  out: cur.out + chunks.map(c => c.chunk).join(''),
                  done: cur.done || chunks.some(c => c.done),
                },
              };
            });
          }).catch(() => {});
      });
    };
    poll();
    const t = setInterval(poll, 1500);
    return () => clearInterval(t);
  }, [st.running]);

  const peerName = (pid: string) =>
    (st.trusted || []).find(t => t.peer_id === pid)?.name
    || (st.online || []).find(p => p.peer_id === pid)?.name || pid.slice(0, 8);

  // [Phase A] 전송 대상이 바뀌면 그 PC의 허용 폴더를 다시 조회한다.
  //   [WHY 매번 조회] 상대가 폴더를 추가/삭제하거나 토글을 끈 것을 이쪽이 알 방법이 없다.
  //   캐시하면 '목록에 있는데 거부됨'이라는 설명 불가능한 실패로 이어진다.
  useEffect(() => {
    setPeerDirs([]); setTargetDir(''); setPeerExecOn(true);
    if (!st.running || !sendPeer) return;
    fetch(`${API_BASE}/api/lan/exec/peer-dirs?peer_id=${encodeURIComponent(sendPeer)}`)
      .then(r => r.json())
      .then((d: { ok?: boolean; enabled?: boolean; dirs?: PeerDir[] }) => {
        setPeerExecOn(d.enabled !== false);
        const list = d.dirs || [];
        setPeerDirs(list);
        if (list.length === 1) setTargetDir(list[0].path);   // 하나뿐이면 고를 이유가 없다
      })
      .catch(() => setPeerDirs([]));
  }, [st.running, sendPeer]);

  const sendExec = async () => {
    const task = execTask.trim();
    if (!sendPeer || !task || !targetDir) return;
    const peer = sendPeer, dir = targetDir;     // 응답 대기 중 선택이 바뀌어도 이 실행에 고정
    const r = await fetch(`${API_BASE}/api/lan/exec`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: peer, task, target_dir: dir }),
    }).then(r => r.json()).catch(() => ({}));
    if (r.ok && r.exec_id) {
      setRuns(prev => ({ ...prev,
        [peer]: { execId: r.exec_id, peerId: peer, dir, out: '', done: false } }));
      setExecTask('');
    } else setFlash(`❌ ${r.error || '실행 요청 실패(상대 오프라인?)'}`);
  };

  const approveExec = async (item: PendingExec) => {
    setPendingSynced(pendingRef.current.filter(p => p.exec_id !== item.exec_id));
    await fetch(`${API_BASE}/api/lan/exec/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: item.exec_id, from_peer: item.from_peer,
        task: item.task, target_dir: item.target_dir || '', trust: autoNext ? 'auto' : 'ask' }),
    }).catch(() => {});
    setAutoNext(false);
  };

  const rejectExec = async (item: PendingExec) => {
    setPendingSynced(pendingRef.current.filter(p => p.exec_id !== item.exec_id));
    await fetch(`${API_BASE}/api/lan/exec/reject`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: item.exec_id, from_peer: item.from_peer }),
    }).catch(() => {});
  };

  const cancelExec = async (run: ExecRun) => {
    // [리뷰C3] peer_id를 함께 보내 대상 PC의 실행 프로세스를 실제로 중단(로컬 UI만 멈추지 않게).
    await fetch(`${API_BASE}/api/lan/exec/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: run.execId, peer_id: run.peerId }),
    }).catch(() => {});
    setRuns(prev => (prev[run.peerId]?.execId === run.execId
      ? { ...prev, [run.peerId]: { ...prev[run.peerId], done: true } } : prev));
  };

  const enableRemoteExec = async () => {
    await fetch(`${API_BASE}/api/config/update`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lan_remote_exec_enabled: true }),
    }).catch(() => {});
    setExecEnabled(true);
    setFlash('✅ 원격 실행 수락 켜짐 — 페어링된 PC가 이 PC에서 태스크 실행을 요청할 수 있어요');
  };

  return (
    <div className="flex-1 overflow-y-auto p-3 text-[13px] text-[#cccccc] space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold">
          {st.running ? <Wifi className="w-4 h-4 text-green-400" /> : <WifiOff className="w-4 h-4 text-red-400" />}
          LAN 브리지 {st.name && <span className="text-[#888]">({st.name})</span>}
        </div>
        <button onClick={refresh} className="p-1 hover:bg-white/10 rounded" title="새로고침">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {!st.running && (
        <div className="bg-yellow-900/30 border border-yellow-700/50 rounded p-2 text-yellow-200 text-[12px] space-y-2">
          <div>LAN 브리지가 꺼져 있어요. 켜면 같은 네트워크의 다른 바이브코딩과 파일·채팅을 주고받을 수 있어요.</div>
          <button onClick={enableBridge}
            className="px-3 py-1 bg-yellow-600/80 hover:bg-yellow-600 rounded text-white text-[12px]">
            브리지 켜기 (재시작 필요)
          </button>
        </div>
      )}

      {st.running && st.firewall_ok === false && (
        <div className="bg-red-900/30 border border-red-700/50 rounded p-2 text-red-200 text-[12px] flex gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <span>방화벽 인바운드 규칙 등록에 실패했어요(관리자 권한 필요). 다른 PC에서 연결이 안 되면
            앱을 관리자 권한으로 실행하거나 방화벽에서 9020/9021 포트를 수동 허용하세요.</span>
        </div>
      )}

      {flash && <div className="text-[12px] text-[#9cdcfe]">{flash}</div>}

      {/* [Phase3] 원격 실행 승인 팝업 — 대기 요청이 있으면 최상단에 표시 */}
      {st.running && pending.length > 0 && (
        <div className="bg-purple-950/50 border border-purple-600/60 rounded p-2 space-y-2">
          <div className="font-medium flex items-center gap-1 text-purple-200">
            <Terminal className="w-3.5 h-3.5" /> 원격 실행 요청 ({pending.length})
          </div>
          {pending.map(item => (
            <div key={item.exec_id} className="bg-black/30 rounded p-2 space-y-1.5">
              <div className="text-[11px] text-[#aaa]">
                <span className="text-purple-300 font-medium">{peerName(item.from_peer)}</span> 님이 요청:
              </div>
              {/* [보안] 태스크 전문 표시(요약 금지) — React 텍스트노드 자동 escape */}
              <div className="whitespace-pre-wrap break-words text-[12px] bg-black/40 rounded px-2 py-1 max-h-32 overflow-y-auto">
                {item.task}
              </div>
              {/* [보안 Phase A] 어느 폴더에서 돌릴지 승인 전에 보여준다 — 태스크 문구만 보고
                  승인하면 폴더 선택이 사실상 무검증이 된다. 미등록 폴더면 실행 없이 거부되지만
                  승인자가 '무엇에 동의하는지' 알아야 한다. */}
              <div className="text-[11px] flex items-start gap-1">
                <span className="text-[#888] shrink-0">작업 폴더:</span>
                {item.target_dir
                  ? <span className="font-mono text-[#9cdcfe] break-all">{item.target_dir}</span>
                  : <span className="text-yellow-400">지정 없음 — 실행 시 거부됩니다</span>}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => approveExec(item)}
                  className="flex items-center gap-1 px-2 py-0.5 bg-green-700/80 hover:bg-green-700 rounded text-[12px]">
                  <Check className="w-3 h-3" /> 승인
                </button>
                <button onClick={() => rejectExec(item)}
                  className="flex items-center gap-1 px-2 py-0.5 bg-red-800/70 hover:bg-red-800 rounded text-[12px]">
                  <X className="w-3 h-3" /> 거부
                </button>
                <label className="flex items-center gap-1 text-[11px] text-[#aaa] ml-auto cursor-pointer">
                  <input type="checkbox" checked={autoNext} onChange={e => setAutoNext(e.target.checked)} />
                  이 PC 자동승인
                </label>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* [Phase3] 원격 실행 수락 마스터 토글 — 기본 OFF */}
      {st.running && !execEnabled && (
        <div className="bg-black/20 border border-purple-800/40 rounded p-2 text-[12px] space-y-1.5">
          <div className="text-[#aaa]">
            원격 실행 <span className="text-purple-300">수락 꺼짐</span> — 켜면 페어링된 PC가 이 PC에서
            Claude 에이전트 태스크 실행을 요청할 수 있어요(요청 시 승인 팝업).
          </div>
          <button onClick={enableRemoteExec}
            className="px-3 py-1 bg-purple-700/70 hover:bg-purple-700 rounded text-white text-[12px]">
            원격 실행 수락 켜기
          </button>
        </div>
      )}

      {/* [Phase A] 허용 폴더 관리 — 브리지가 살아있으면 토글 상태와 무관하게 미리 등록 가능.
          (토글을 켜기 전에 폴더를 먼저 정해두는 순서가 안전하다) */}
      {st.running && <LanExecDirs execEnabled={execEnabled} onFlash={setFlash} />}

      {/* 페어링 개시 — 내 코드 표시 */}
      {st.running && (
        <div className="bg-black/20 rounded p-2 space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-medium">페어링</span>
            <button onClick={beginPair} className="text-[12px] px-2 py-0.5 bg-blue-600/70 hover:bg-blue-600 rounded">
              내 코드 생성
            </button>
          </div>
          {(myCode || st.pending_code) && (
            <div className="text-center py-1">
              <div className="text-[11px] text-[#888]">상대 PC에서 이 코드를 입력</div>
              <div className="text-2xl font-mono tracking-widest text-green-300">{myCode || st.pending_code}</div>
            </div>
          )}
          {/* [Tailscale] 수동 IP 연결 — 발견 안 되는 다른 네트워크/VPN 상대. 상대의 IP·포트·코드 입력 */}
          <div className="border-t border-white/10 pt-2 space-y-1.5">
            <div className="text-[11px] text-[#888]">
              다른 네트워크 / VPN(Tailscale) — 상대 IP 직접 입력
            </div>
            <div className="flex gap-1.5">
              <input value={manualIp} onChange={e => setManualIp(e.target.value)} placeholder="예: 100.101.102.103"
                className="flex-1 bg-black/40 rounded px-2 py-1 text-[12px] font-mono outline-none" />
              <input value={manualPort} onChange={e => setManualPort(e.target.value)} placeholder="9020"
                className="w-16 bg-black/40 rounded px-2 py-1 text-[12px] font-mono outline-none" />
            </div>
            <div className="flex gap-1.5">
              <input value={manualCode} onChange={e => setManualCode(e.target.value.toUpperCase())} placeholder="상대 코드 8자"
                maxLength={8}
                className="flex-1 bg-black/40 rounded px-2 py-1 text-[12px] font-mono tracking-widest outline-none" />
              <button onClick={doManualConnect} disabled={!manualIp.trim() || manualCode.length < 8}
                className="px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-[12px] flex items-center gap-1">
                <Link2 className="w-3 h-3" /> 연결
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 발견된 피어 — 아직 페어링 안 한 후보만(페어링되면 아래 '페어링된 기기'로 이동) */}
      {st.running && (() => {
        const candidates = (st.online || []).filter(p => !isTrusted(p.peer_id));
        return (
          <div className="space-y-1">
            <div className="text-[11px] text-[#888] uppercase">발견된 기기 ({candidates.length})</div>
            {candidates.length === 0 && <div className="text-[#666] text-[12px]">근처에 새로 페어링할 기기가 없어요.</div>}
            {candidates.map(p => (
              <div key={p.peer_id} className="flex items-center justify-between bg-black/20 rounded px-2 py-1.5">
                <div>
                  <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-400" />{p.name}</div>
                  <div className="text-[10px] text-[#666] font-mono">{p.ip}:{p.http_port}</div>
                </div>
                <button onClick={() => setTarget(p)}
                  className="text-[11px] px-2 py-0.5 bg-blue-600/70 hover:bg-blue-600 rounded flex items-center gap-1">
                  <Link2 className="w-3 h-3" /> 페어링
                </button>
              </div>
            ))}
          </div>
        );
      })()}

      {/* 페어링된 기기 — 발견 안 돼도(다른 네트워크/VPN) 전송 대상으로 선택 가능 */}
      {st.running && (st.trusted || []).length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] text-[#888] uppercase">페어링된 기기 ({(st.trusted || []).length})</div>
          {(st.trusted || []).map(t => {
            const online = (st.online || []).some(p => p.peer_id === t.peer_id);
            return (
              <div key={t.peer_id} className="flex items-center justify-between bg-black/20 rounded px-2 py-1.5">
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${online ? 'bg-green-400' : 'bg-gray-500'}`} />
                  {t.name || t.peer_id.slice(0, 8)}
                  <span className="text-[10px] text-[#666]">{online ? '온라인' : '오프라인 / 원격'}</span>
                </div>
                <button onClick={() => setSendPeer(t.peer_id)}
                  className={`text-[11px] px-2 py-0.5 rounded ${sendPeer === t.peer_id ? 'bg-green-600' : 'bg-white/10 hover:bg-white/20'}`}>
                  {sendPeer === t.peer_id ? '전송 대상' : '전송 선택'}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* 페어링 코드 입력 (선택한 상대) */}
      {target && (
        <div className="bg-blue-950/40 border border-blue-700/40 rounded p-2 space-y-2">
          <div className="text-[12px]">{target.name}의 코드 입력</div>
          <div className="flex gap-2">
            <input value={inputCode} onChange={e => setInputCode(e.target.value.toUpperCase())} placeholder="코드 8자"
              className="flex-1 bg-black/40 rounded px-2 py-1 font-mono tracking-widest outline-none" maxLength={8} />
            <button onClick={doConnect} className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-[12px]">연결</button>
            <button onClick={() => setTarget(null)} className="px-2 py-1 bg-white/10 rounded text-[12px]">취소</button>
          </div>
        </div>
      )}

      {/* 파일 전송 */}
      {st.running && (st.trusted || []).length > 0 && (
        <div className="bg-black/20 rounded p-2 space-y-2">
          <div className="font-medium flex items-center gap-1"><Send className="w-3.5 h-3.5" /> 파일 전송</div>
          <div className="flex gap-2">
            <input value={sendPath} onChange={e => setSendPath(e.target.value)}
              placeholder="보낼 파일 경로 — 찾아보기 또는 직접 입력"
              className="flex-1 bg-black/40 rounded px-2 py-1 text-[12px] font-mono outline-none" />
            <button onClick={browseFile}
              className="px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-[12px] flex items-center gap-1 shrink-0">
              <FolderOpen className="w-3.5 h-3.5" /> 찾아보기
            </button>
          </div>
          <div className="text-[11px] text-[#888]">
            대상: {sendPeer ? (st.trusted || []).find(t => t.peer_id === sendPeer)?.name || sendPeer : '위에서 전송 대상 선택'}
          </div>
          <button onClick={doSend} disabled={!sendPeer || !sendPath}
            className="w-full py-1 bg-green-700/70 hover:bg-green-700 disabled:opacity-40 rounded text-[12px]">
            전송
          </button>
        </div>
      )}

      {/* [Phase3] 원격 실행 — 전송대상 피어 선택 시 태스크 전송 + 출력 */}
      {st.running && sendPeer && (
        <div className="bg-black/20 rounded p-2 space-y-2">
          <div className="font-medium flex items-center gap-1 text-purple-200">
            <Terminal className="w-3.5 h-3.5" /> 원격 실행 — {peerName(sendPeer)}
          </div>
          <div className="text-[11px] text-[#888]">
            상대 PC의 Claude에게 태스크를 보냅니다. 상대가 승인해야 실행돼요.
          </div>

          {/* [Phase A] 작업 폴더 선택 — 상대가 허용한 목록에서만 고른다(임의 경로 입력 불가) */}
          {!peerExecOn ? (
            <div className="bg-yellow-900/30 border border-yellow-700/50 rounded px-2 py-1 text-yellow-200 text-[11px]">
              {peerName(sendPeer)}의 원격 실행 수락이 꺼져 있어요. 그쪽 PC의 LAN 패널에서 켜야 합니다.
            </div>
          ) : peerDirs.length === 0 ? (
            <div className="bg-yellow-900/30 border border-yellow-700/50 rounded px-2 py-1 text-yellow-200 text-[11px]">
              {peerName(sendPeer)}가 허용한 작업 폴더가 없어요. 그쪽 PC에서 폴더를 등록해야 합니다.
            </div>
          ) : (
            <div className="space-y-1">
              <select value={targetDir} onChange={e => setTargetDir(e.target.value)}
                className="w-full bg-black/40 rounded px-2 py-1 text-[11px] font-mono outline-none">
                <option value="">작업 폴더 선택…</option>
                {peerDirs.map(d => (
                  <option key={d.path} value={d.path}>
                    {d.path} {d.mode === 'direct' ? '(직접 편집)' : '(사본)'}
                  </option>
                ))}
              </select>
              {targetDir && (
                <div className="text-[10px] text-[#777]">
                  {peerDirs.find(d => d.path === targetDir)?.mode === 'direct'
                    ? '원본 폴더를 직접 편집합니다.'
                    : '사본에서 작업합니다 — 원본은 바뀌지 않고, 변경 파일 목록이 결과에 표시돼요.'}
                </div>
              )}
            </div>
          )}

          <textarea value={execTask} onChange={e => setExecTask(e.target.value)}
            placeholder="예: server.py 띄워서 부팅 에러 있으면 알려줘"
            rows={2}
            className="w-full bg-black/40 rounded px-2 py-1 text-[12px] outline-none resize-y" />
          {/* [리뷰W6 유지] 재전송 차단은 '이 피어'에만 적용 — 다른 PC에는 동시에 보낼 수 있다 */}
          <button onClick={sendExec}
            disabled={!execTask.trim() || !targetDir || !!(runs[sendPeer] && !runs[sendPeer].done)}
            className="w-full py-1 bg-purple-700/70 hover:bg-purple-700 disabled:opacity-40 rounded text-[12px] flex items-center justify-center gap-1">
            <Play className="w-3.5 h-3.5" />
            {runs[sendPeer] && !runs[sendPeer].done ? '이 PC에서 실행 중…' : '실행 요청'}
          </button>
        </div>
      )}

      {/* [다중 실행] 진행 중·완료된 실행을 피어별로 모두 표시 — 여러 대를 동시에 몰 수 있으므로
          '현재 선택한 피어'에 묶이면 다른 대의 결과를 놓친다. 선택과 무관하게 여기 모인다. */}
      {st.running && Object.keys(runs).length > 0 && (
        <div className="bg-black/20 rounded p-2 space-y-2">
          <div className="font-medium flex items-center gap-1 text-purple-200">
            <Terminal className="w-3.5 h-3.5" /> 원격 실행 현황
            <span className="text-[#888] text-[11px]">
              (진행 {Object.values(runs).filter(r => !r.done).length} / 전체 {Object.keys(runs).length})
            </span>
          </div>
          {Object.values(runs).map(run => (
            <div key={run.execId} className="bg-black/30 rounded p-2 space-y-1">
              <div className="flex items-center gap-2 text-[11px]">
                <span className="text-purple-300 font-medium">{peerName(run.peerId)}</span>
                <span className={run.done ? 'text-[#888]' : 'text-green-400'}>
                  {run.done ? '완료' : '실행 중…'}
                </span>
                <span className="font-mono text-[10px] text-[#777] truncate flex-1">{run.dir}</span>
                {!run.done && (
                  <button onClick={() => cancelExec(run)}
                    className="px-2 py-0.5 bg-red-800/60 hover:bg-red-800 rounded shrink-0">취소</button>
                )}
                {run.done && (
                  <button onClick={() => setRuns(prev => {
                    const next = { ...prev }; delete next[run.peerId]; return next;
                  })} className="px-2 py-0.5 bg-white/10 hover:bg-white/20 rounded shrink-0">닫기</button>
                )}
              </div>
              {/* [보안] 출력은 React 텍스트노드 — 자동 escape */}
              <div className="h-40 overflow-y-auto bg-black/40 rounded p-2 text-[12px] font-mono whitespace-pre-wrap break-words">
                {run.out || <span className="text-[#666]">출력 대기 중…</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* [그룹방] 페어링 상대가 있으면 항상 노출 — 피어 선택과 무관하다(전원 대상이라서).
          [주의] selfId는 selfRef가 아니라 st.self_id — ref는 갱신 시 리렌더를 안 일으켜
          내/남 메시지 정렬이 첫 렌더 값('')에 고정된다. */}
      {st.running && (st.trusted || []).length > 0 && (
        <LanRoomChat peerCount={(st.trusted || []).length} peerName={peerName}
          selfId={st.self_id || ''} onFlash={setFlash} />
      )}

      {/* 채팅 — 전송대상 피어 선택 시 */}
      {st.running && sendPeer && (
        <div className="bg-black/20 rounded p-2 space-y-2">
          <div className="font-medium flex items-center gap-1">
            <MessageSquare className="w-3.5 h-3.5" />
            {(st.trusted || []).find(t => t.peer_id === sendPeer)?.name || '채팅'}
          </div>
          <div className="h-48 overflow-y-auto space-y-1 bg-black/30 rounded p-2">
            {messages.length === 0 && <div className="text-[#666] text-[12px]">아직 메시지가 없어요.</div>}
            {messages.map(m => {
              const mine = m.from_peer === selfRef.current;
              return (
                <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] rounded px-2 py-1 text-[12px] ${mine ? 'bg-blue-600/60' : 'bg-white/10'}`}>
                    {/* [보안] React 텍스트 노드 — 자동 escape(XSS 차단). dangerouslySetInnerHTML 금지 */}
                    <div className="whitespace-pre-wrap break-words">{m.content}</div>
                    <div className="text-[9px] text-white/40 text-right">{m.ts.slice(11, 16)}</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex gap-2">
            <input value={chatInput} onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') sendChat(); }}
              placeholder="메시지 입력 후 Enter"
              className="flex-1 bg-black/40 rounded px-2 py-1 text-[12px] outline-none" />
            <button onClick={sendChat} disabled={!chatInput.trim()}
              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 rounded text-[12px]">보내기</button>
          </div>
        </div>
      )}
    </div>
  );
}
