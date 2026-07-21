/*
 * 📄 파일명: components/panels/LanPanel.tsx
 * 📝 설명: LAN 브리지 패널 — 같은 네트워크의 다른 바이브코딩을 자동발견하고 페어링(6자리 코드)한 뒤
 *          파일을 주고받는 UI. 실제 통신은 lan_bridge 프로세스가, 이 패널은 /api/lan/* 만 호출.
 * 🕒 변경 이력:
 * - 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 9 (파일 전송 UI). 채팅은 Phase 2.
 * - 2026-07-22 Claude: Phase 3 — 원격 Claude 에이전트 실행 UI(전송/승인팝업/출력뷰/마스터토글).
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { Wifi, WifiOff, ShieldAlert, Send, Link2, RefreshCw, MessageSquare, FolderOpen,
  Terminal, Play, Check, X } from 'lucide-react';
import { API_BASE } from '../../constants';

interface Peer { peer_id: string; name: string; ip: string; http_port: number }
interface Trusted { peer_id: string; name: string; paired_at: string; exec_trust?: string }
interface ChatMsg { id: number; from_peer: string; to_peer: string; content: string; ts: string }
interface PendingExec { exec_id: string; from_peer: string; task: string; ts: string; exec_trust?: string; _seenAt?: number }
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
  const [execId, setExecId] = useState('');                 // 현재 요청한 exec_id
  const [execOut, setExecOut] = useState('');               // 수신 출력 누적
  const [execDone, setExecDone] = useState(false);          // 실행 완료 여부
  const execIdRef = useRef('');                             // 폴링 클로저용

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
          if (!d.enabled) { setPending([]); return; }
          const now = Date.now();
          setPending(prev => {
            const seen = new Set(prev.map(p => p.exec_id));
            const fresh = (d.pending || []).filter(p => !seen.has(p.exec_id))
              .map(p => ({ ...p, _seenAt: now }));
            const merged = [...prev, ...fresh];
            // TTL 초과분은 자동 거부(비동기 통지) 후 목록에서 제외.
            const expired = merged.filter(p => now - (p._seenAt || now) > PENDING_TTL_MS);
            expired.forEach(p => { void rejectExec(p); });
            const expIds = new Set(expired.map(p => p.exec_id));
            return merged.filter(p => !expIds.has(p.exec_id));
          });
        }).catch(() => {});
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st.running]);

  // [Phase3] 원격 실행 출력 폴링(요청자측) — exec_id 있고 완료 전까지 1.5초 증분.
  useEffect(() => {
    if (!execId || execDone) return;
    execIdRef.current = execId;
    const poll = () => {
      fetch(`${API_BASE}/api/lan/exec/output?exec_id=${encodeURIComponent(execIdRef.current)}`)
        .then(r => r.json()).then((d: { chunks?: OutChunk[] }) => {
          const chunks = d.chunks || [];
          if (chunks.length) {
            setExecOut(prev => prev + chunks.map(c => c.chunk).join(''));
            if (chunks.some(c => c.done)) setExecDone(true);
          }
        }).catch(() => {});
    };
    poll();
    const t = setInterval(poll, 1500);
    return () => clearInterval(t);
  }, [execId, execDone]);

  const peerName = (pid: string) =>
    (st.trusted || []).find(t => t.peer_id === pid)?.name
    || (st.online || []).find(p => p.peer_id === pid)?.name || pid.slice(0, 8);

  const sendExec = async () => {
    const task = execTask.trim();
    if (!sendPeer || !task) return;
    setExecOut(''); setExecDone(false); setExecId('');
    const r = await fetch(`${API_BASE}/api/lan/exec`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: sendPeer, task }),
    }).then(r => r.json()).catch(() => ({}));
    if (r.ok && r.exec_id) { setExecId(r.exec_id); setExecTask(''); }
    else setFlash(`❌ ${r.error || '실행 요청 실패(상대 오프라인?)'}`);
  };

  const approveExec = async (item: PendingExec) => {
    setPending(prev => prev.filter(p => p.exec_id !== item.exec_id));
    await fetch(`${API_BASE}/api/lan/exec/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: item.exec_id, from_peer: item.from_peer,
        task: item.task, trust: autoNext ? 'auto' : 'ask' }),
    }).catch(() => {});
    setAutoNext(false);
  };

  const rejectExec = async (item: PendingExec) => {
    setPending(prev => prev.filter(p => p.exec_id !== item.exec_id));
    await fetch(`${API_BASE}/api/lan/exec/reject`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: item.exec_id, from_peer: item.from_peer }),
    }).catch(() => {});
  };

  const cancelExec = async () => {
    if (!execId) return;
    await fetch(`${API_BASE}/api/lan/exec/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exec_id: execId }),
    }).catch(() => {});
    setExecDone(true);
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
        </div>
      )}

      {/* 발견된 피어 */}
      {st.running && (
        <div className="space-y-1">
          <div className="text-[11px] text-[#888] uppercase">발견된 기기 ({(st.online || []).length})</div>
          {(st.online || []).length === 0 && <div className="text-[#666] text-[12px]">근처에 켜진 바이브코딩이 없어요.</div>}
          {(st.online || []).map(p => (
            <div key={p.peer_id} className="flex items-center justify-between bg-black/20 rounded px-2 py-1.5">
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-green-400" />{p.name}
                  {isTrusted(p.peer_id) && <span className="text-[10px] text-green-400">✓ 신뢰됨</span>}
                </div>
                <div className="text-[10px] text-[#666] font-mono">{p.ip}:{p.http_port}</div>
              </div>
              {isTrusted(p.peer_id) ? (
                <button onClick={() => setSendPeer(p.peer_id)}
                  className={`text-[11px] px-2 py-0.5 rounded ${sendPeer === p.peer_id ? 'bg-green-600' : 'bg-white/10 hover:bg-white/20'}`}>
                  {sendPeer === p.peer_id ? '전송 대상' : '전송 선택'}
                </button>
              ) : (
                <button onClick={() => setTarget(p)}
                  className="text-[11px] px-2 py-0.5 bg-blue-600/70 hover:bg-blue-600 rounded flex items-center gap-1">
                  <Link2 className="w-3 h-3" /> 페어링
                </button>
              )}
            </div>
          ))}
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
            상대 PC의 Claude에게 태스크를 보냅니다. 상대가 승인해야 실행돼요(같은 LAN 전용).
          </div>
          <textarea value={execTask} onChange={e => setExecTask(e.target.value)}
            placeholder="예: server.py 띄워서 부팅 에러 있으면 알려줘"
            rows={2}
            className="w-full bg-black/40 rounded px-2 py-1 text-[12px] outline-none resize-y" />
          <button onClick={sendExec} disabled={!execTask.trim()}
            className="w-full py-1 bg-purple-700/70 hover:bg-purple-700 disabled:opacity-40 rounded text-[12px] flex items-center justify-center gap-1">
            <Play className="w-3.5 h-3.5" /> 실행 요청
          </button>
          {execId && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-[#888]">{execDone ? '완료' : '실행 중…'}</span>
                {!execDone && (
                  <button onClick={cancelExec} className="px-2 py-0.5 bg-red-800/60 hover:bg-red-800 rounded">취소</button>
                )}
              </div>
              {/* [보안] 출력은 React 텍스트노드 — 자동 escape */}
              <div className="h-40 overflow-y-auto bg-black/40 rounded p-2 text-[12px] font-mono whitespace-pre-wrap break-words">
                {execOut || <span className="text-[#666]">출력 대기 중…</span>}
              </div>
            </div>
          )}
        </div>
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
