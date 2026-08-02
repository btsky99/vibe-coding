/**
 * ------------------------------------------------------------------------
 * 📄 파일명: RemoteHostCards.tsx
 * 📝 설명: ~/.ssh/config의 Host 별칭을 카드로 띄우고, 원격 셸/클로드/코덱스를
 *          해당 노드에서 실행하도록 슬롯 실행을 위임한다.
 *
 * [WHY 별도 컴포넌트] AgentSelectCards는 로컬 CLI 3종 전용으로 이미 자리를 잡았고,
 *   원격은 목록이 서버에서 오는 비동기 데이터 + 미설정/ssh없음 같은 별도 상태를 가진다.
 *   같은 파일에 넣으면 로컬 카드가 원격 로딩 상태에 얽매인다.
 *
 * [WHY 하드코딩이 없는가 — 맥 이전 대비] 호스트/계정/키 경로가 이 파일에 하나도 없다.
 *   전부 ~/.ssh/config가 소유하고 백엔드가 파싱해 내려준다. 맥으로 옮길 때 옮길 것은
 *   ssh config 파일 하나뿐이며 이 컴포넌트는 손대지 않는다.
 *
 * REVISION HISTORY:
 * - 2026-07-29 Claude: 최초 작성 — 레노버(APIS) 원격 터미널 슬롯 Phase 3.
 * ------------------------------------------------------------------------
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Server, Terminal, Cpu, Code2, AlertTriangle, Gauge } from 'lucide-react';

interface RemoteHost {
  alias: string;
  aliases: string[];
  hostName: string;
  user: string;
}

interface RemoteMode {
  id: string;
  label: string;
}

const MODE_ICON: Record<string, typeof Terminal> = {
  shell: Terminal,
  claude: Cpu,
  codex: Code2,
};

export default function RemoteHostCards({ onLaunchRemote, onLaunchLocal }: {
  onLaunchRemote: (alias: string, mode: string) => void;
  // [WHY 로컬도 여기인가] "상태를 보고 싶다"는 목적에서 이 PC와 원격 노드는 같은 줄에 있다.
  //   기존 3장(클로드/안티그래비티/코덱스)은 '에이전트를 띄운다'는 다른 목적이라 섞지 않는다.
  onLaunchLocal: (mode: string) => void;
}) {
  const [hosts, setHosts] = useState<RemoteHost[]>([]);
  const [modes, setModes] = useState<RemoteMode[]>([]);
  const [sshAvailable, setSshAvailable] = useState(true);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // [제약] /api/pty/*는 Python 서버(pty_api.py)가 Node PTY 서버로 투명 프록시한다.
    //   상대 경로로 부르면 되고 PTY 포트를 프론트가 알 필요가 없다.
    fetch('/api/pty/remote/hosts')
      .then((r) => r.json())
      .then((d) => {
        setHosts(Array.isArray(d.hosts) ? d.hosts : []);
        setModes(Array.isArray(d.modes) ? d.modes : []);
        setSshAvailable(d.sshAvailable !== false);
      })
      .catch(() => {
        // 목록을 못 받아도 로컬 카드는 정상 동작해야 한다 — 조용히 비운다.
        setHosts([]);
      })
      .finally(() => setLoaded(true));
  }, []);

  // [WHY loaded만 보는가] 원격 노드가 없어도 '이 PC 상태판' 버튼은 항상 쓸모가 있다.
  //   (초기 렌더에서 목록 fetch 전에 깜빡이는 것만 막는다.)
  if (!loaded) return null;

  return (
    <div className="w-full mt-5">
      <div className="flex items-center gap-2 mb-2 px-1">
        <Server className="w-3.5 h-3.5 text-primary/70" />
        <span className="text-[10px] font-black uppercase tracking-widest text-[#888]">
          상태판 · 원격 노드
        </span>
        <div className="flex-1 h-px bg-white/10" />
      </div>

      {/* 상태판 — 독립 창(?page=status)으로 띄운다.
          [WHY 슬롯 TUI가 아니라 독립 창인가] 상태판은 옆에 띄워 두고 곁눈질하는 물건이라
          슬롯을 하나 잡아먹으면 정작 작업할 터미널이 줄어든다. 슬롯 TUI 경로는 SSH로
          붙었을 때(창을 못 띄우는 환경)를 위해 scripts/tui.py로 그대로 남아 있다. */}
      <div className="mb-2">
        <button
          onClick={() => {
            fetch('/api/dashboard/launch', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tab: 'status' }),
            }).catch(() => onLaunchLocal('tui'));  // 창을 못 띄우면 슬롯 TUI로 폴백
          }}
          className="w-full py-2 bg-primary/15 hover:bg-primary/30 text-primary rounded-xl text-[11px] font-black transition-all border border-primary/30 flex items-center justify-center gap-2"
        >
          <Gauge className="w-3.5 h-3.5" /> 상태판 열기 (노드 · 콘솔 창)
        </button>
      </div>

      {!sshAvailable && (
        // [과거사고 2026-07-29] 레노버에 OpenSSH Server만 있고 Client가 없어 ssh 자체가
        //   없었다. 이 경우 카드를 눌러도 spawn이 실패하므로 미리 이유를 보여준다.
        <div className="flex items-center gap-2 mb-2 px-3 py-2 rounded-lg bg-warning/10 border border-warning/30">
          <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0" />
          <span className="text-[10px] text-warning leading-relaxed">
            ssh 실행파일이 없어 원격 접속이 불가능합니다. (윈도우: OpenSSH 클라이언트 설치 필요)
          </span>
        </div>
      )}

      {hosts.length > 0 && (
      <div className="flex flex-wrap gap-2">
        {hosts.map((h) => (
          <motion.div
            key={h.alias}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex-1 min-w-[190px] bg-[#252526] border border-white/10 rounded-xl p-3 flex flex-col gap-2 hover:border-primary/40 transition-colors"
          >
            <div className="flex items-baseline gap-2 min-w-0">
              <span className="text-sm font-black text-white tracking-tight truncate">{h.alias}</span>
              <span className="text-[9px] text-[#777] truncate">
                {h.user ? `${h.user}@` : ''}{h.hostName || '—'}
              </span>
            </div>
            <div className="flex gap-1">
              {modes.map((m) => {
                const Icon = MODE_ICON[m.id] || Terminal;
                return (
                  <button
                    key={m.id}
                    disabled={!sshAvailable}
                    onClick={() => onLaunchRemote(h.alias, m.id)}
                    title={`${h.alias} — ${m.label}`}
                    className="flex-1 py-1.5 px-1 bg-[#3c3c3c] hover:bg-primary/20 hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed rounded-lg text-[10px] font-bold transition-all border border-white/5 flex items-center justify-center gap-1"
                  >
                    <Icon className="w-3 h-3" />
                    {m.label.replace('원격 ', '')}
                  </button>
                );
              })}
            </div>
          </motion.div>
        ))}
      </div>
      )}
    </div>
  );
}
