/*
 * 📄 파일명: components/panels/LanPanel.tsx
 * 📝 설명: LAN 브리지 패널 — 같은 네트워크의 다른 바이브코딩을 자동발견하고 페어링(6자리 코드)한 뒤
 *          파일을 주고받는 UI. 실제 통신은 lan_bridge 프로세스가, 이 패널은 /api/lan/* 만 호출.
 * 🕒 변경 이력:
 * - 2026-07-19 Claude: 신규 — LAN 브리지 Phase 1 Task 9 (파일 전송 UI). 채팅은 Phase 2.
 */
import { useEffect, useState, useCallback } from 'react';
import { Wifi, WifiOff, ShieldAlert, Send, Link2, RefreshCw } from 'lucide-react';
import { API_BASE } from '../../constants';

interface Peer { peer_id: string; name: string; ip: string; http_port: number }
interface Trusted { peer_id: string; name: string; paired_at: string }
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

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/lan/status`).then(r => r.json()).then(setSt).catch(() => {});
  }, []);

  // [WHY] 3초 폴링 — 발견/온오프라인이 실시간이라 App.tsx 코디네이터 관례와 동일 주기.
  useEffect(() => { refresh(); const t = setInterval(refresh, 3000); return () => clearInterval(t); }, [refresh]);

  const isTrusted = (pid: string) => (st.trusted || []).some(t => t.peer_id === pid);

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

  const doSend = async () => {
    if (!sendPeer || !sendPath) return;
    setFlash('전송 중…');
    const r = await fetch(`${API_BASE}/api/lan/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: sendPeer, path: sendPath }),
    }).then(r => r.json());
    setFlash(r.ok ? `✅ 전송 완료` : `❌ ${r.error || '전송 실패'}`);
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
        <div className="bg-yellow-900/30 border border-yellow-700/50 rounded p-2 text-yellow-200 text-[12px]">
          브리지가 꺼져 있어요. <code>config.json</code>의 <code>lan_bridge_enabled: true</code> 설정 후
          앱을 재시작하세요.
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
          <input value={sendPath} onChange={e => setSendPath(e.target.value)}
            placeholder="보낼 파일의 전체 경로 (예: D:\\문서\\a.zip)"
            className="w-full bg-black/40 rounded px-2 py-1 text-[12px] font-mono outline-none" />
          <div className="text-[11px] text-[#888]">
            대상: {sendPeer ? (st.trusted || []).find(t => t.peer_id === sendPeer)?.name || sendPeer : '위에서 전송 대상 선택'}
          </div>
          <button onClick={doSend} disabled={!sendPeer || !sendPath}
            className="w-full py-1 bg-green-700/70 hover:bg-green-700 disabled:opacity-40 rounded text-[12px]">
            전송
          </button>
        </div>
      )}
    </div>
  );
}
