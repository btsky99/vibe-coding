/**
 * ------------------------------------------------------------------------
 * 📄 파일명: StatusBoard.tsx
 * 📝 설명: 상태판 독립 창(?page=status) 본체. 이 PC의 콘솔 창 —
 *          화면에 떠 있는 검은 창의 정체와 "닫아도 되는지"를 보여준다.
 *
 * [WHY 독립 창인가 — 좌측 패널이 아니라]
 *   상태판은 옆에 띄워 두고 곁눈질하는 물건이다. 좌측 액티비티 바 패널로 만들면
 *   파일 트리나 Git을 볼 때마다 가려져 "띄워 둔다"는 목적 자체가 성립하지 않는다.
 *   오피스 창과 같은 dashboard_window.py 경로를 타므로 창 인프라는 추가 비용이 없다.
 *
 * [WHY 여기서 원격 실행 버튼을 안 그리는가]
 *   터미널 슬롯은 메인 창의 상태다. 독립 창에서 슬롯을 배정하려면 창 간 IPC가 필요한데
 *   얻는 것에 비해 과하다. 실행은 기존 RemoteHostCards(슬롯 안)가 계속 담당하고
 *   이 창은 "상태를 본다 + 점검한다 + 정리한다"만 맡는다.
 *
 * [제약] 콘솔 목록은 윈도우 전용(conhost 기반 판정). 비윈도우는 안내 문구만 뜬다.
 *
 * REVISION HISTORY:
 * - 2026-08-02 Claude: 최초 작성 — 정체불명 콘솔 창 식별 + 원격 노드 상태판.
 * ------------------------------------------------------------------------
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Loader2, Monitor, RefreshCw, ShieldAlert, Terminal, X,
} from 'lucide-react';

// 창이 뜨고 지는 것을 지켜보는 화면이라 촘촘히 본다(백엔드에 3초 TTL 캐시가 있어 안전).
const CONSOLE_POLL_MS = 5000;

interface ConsoleItem {
  pid: number;
  title: string;
  name: string;
  exe: string;
  created: string;
  cmdline: string;
  summary: string;
  owner: 'owned' | 'slot' | 'foreign';
  label: string;
  ancestry: string[];
}

const OWNER_STYLE: Record<string, { dot: string; chip: string; note: string }> = {
  owned: {
    dot: 'bg-green-500',
    chip: 'bg-green-500/15 text-green-400 border-green-500/30',
    note: '닫으면 앱이 멈춰',
  },
  slot: {
    dot: 'bg-yellow-400',
    chip: 'bg-yellow-400/15 text-yellow-300 border-yellow-400/30',
    note: '에이전트가 실행한 것',
  },
  foreign: {
    dot: 'bg-white/30',
    chip: 'bg-white/5 text-[#aaa] border-white/10',
    note: '다른 앱이 띄운 것',
  },
};

export default function StatusBoard() {
  const [consoles, setConsoles] = useState<ConsoleItem[]>([]);
  const [consoleSupported, setConsoleSupported] = useState(true);
  const [consoleLoading, setConsoleLoading] = useState(true);

  const [killing, setKilling] = useState<Record<number, boolean>>({});
  const [confirmKill, setConfirmKill] = useState<ConsoleItem | null>(null);
  const [notice, setNotice] = useState('');

  // 창이 닫히고 나서 setState가 불리면 React 경고가 난다 — 언마운트 후 반영 차단.
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const loadConsoles = useCallback(async () => {
    try {
      const r = await fetch('/api/nodes/consoles');
      const d = await r.json();
      if (!alive.current) return;
      setConsoleSupported(d.supported !== false);
      setConsoles(Array.isArray(d.consoles) ? d.consoles : []);
    } catch { /* 동상 */ } finally {
      if (alive.current) setConsoleLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConsoles();
    const t = setInterval(loadConsoles, CONSOLE_POLL_MS);
    return () => clearInterval(t);
  }, [loadConsoles]);

  // [🔴 불변식] created/exe를 조회 시점 값 그대로 되돌려줘야 서버가 PID 재사용을 걸러낸다.
  //   pid만 보내면 서버가 mismatch로 거부한다(의도된 동작 — 오폭 방지).
  const doKill = useCallback(async (item: ConsoleItem) => {
    setConfirmKill(null);
    setKilling((s) => ({ ...s, [item.pid]: true }));
    try {
      const r = await fetch('/api/nodes/console/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pid: item.pid, created: item.created, exe: item.exe }),
      });
      const d = await r.json();
      if (!alive.current) return;
      setNotice(d.ok ? `종료했어 — ${item.summary}` : (d.message || '종료하지 못했어.'));
      loadConsoles();
    } catch (e) {
      if (alive.current) setNotice(`종료 실패: ${e}`);
    } finally {
      if (alive.current) setKilling((s) => ({ ...s, [item.pid]: false }));
    }
  }, [loadConsoles]);

  const counts = useMemo(() => ({
    owned: consoles.filter((c) => c.owner === 'owned').length,
    slot: consoles.filter((c) => c.owner === 'slot').length,
    foreign: consoles.filter((c) => c.owner === 'foreign').length,
  }), [consoles]);

  return (
    <div className="w-screen h-screen bg-[#1e1e1e] text-white overflow-y-auto">
      {/* ── 헤더 — 이 PC 자신 ─────────────────────────────────────────── */}
      <div className="sticky top-0 z-20 bg-[#1e1e1e]/95 backdrop-blur border-b border-white/10 px-5 py-3 flex items-center gap-3">
        <Monitor className="w-4 h-4 text-primary" />
        <div className="min-w-0">
          <div className="text-[13px] font-black tracking-tight truncate">
            이 PC
          </div>
        </div>
        <div className="flex-1" />
        <button
          onClick={() => loadConsoles()}
          className="p-1.5 rounded-lg hover:bg-white/10 text-[#aaa] hover:text-white transition-colors"
          title="새로고침"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {notice && (
        <div className="mx-5 mt-3 px-3 py-2 rounded-lg bg-primary/10 border border-primary/30 text-[11px] flex items-start gap-2">
          <span className="flex-1 leading-relaxed">{notice}</span>
          <button onClick={() => setNotice('')} className="text-[#888] hover:text-white shrink-0">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* ── 콘솔 창 ──────────────────────────────────────────────────── */}
      <section className="px-5 py-4">
        <div className="flex items-center gap-2 mb-1">
          <Terminal className="w-3.5 h-3.5 text-primary/70" />
          <span className="text-[10px] font-black uppercase tracking-widest text-[#888]">
            떠 있는 콘솔 창
          </span>
          <div className="flex-1 h-px bg-white/10" />
          <span className="text-[10px] text-[#666]">
            앱 {counts.owned} · 슬롯 {counts.slot} · 외부 {counts.foreign}
          </span>
        </div>
        <p className="text-[10px] text-[#666] mb-2 leading-relaxed">
          화면에 떠 있는 검은 창을 창 제목으로 대조할 수 있어. 콘솔 창은 윈도우에서 하나로 합칠 수 없어서,
          대신 누가 띄운 건지 알려준다.
        </p>

        {!consoleSupported ? (
          <div className="text-[11px] text-[#666] py-3">콘솔 창 식별은 윈도우 전용 기능이야.</div>
        ) : consoleLoading ? (
          <div className="flex items-center gap-2 text-[11px] text-[#666] py-3">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> 프로세스 훑는 중…
          </div>
        ) : consoles.length === 0 ? (
          <div className="text-[11px] text-[#666] py-3">떠 있는 콘솔 창이 없어. 깔끔하네.</div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {consoles.map((c) => {
              const st = OWNER_STYLE[c.owner] || OWNER_STYLE.foreign;
              return (
                <div
                  key={c.pid}
                  className="rounded-xl border border-white/10 bg-[#252526] p-3 flex items-start gap-3"
                >
                  <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${st.dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[12px] font-bold truncate max-w-full">{c.title || c.name}</span>
                      <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold shrink-0 ${st.chip}`}>
                        {c.label}
                      </span>
                    </div>
                    <div className="text-[10px] text-[#999] mt-0.5 break-all">{c.summary}</div>
                    <div className="text-[9px] text-[#666] mt-0.5">
                      PID {c.pid} · {st.note}
                      {c.ancestry.length > 0 && ` · ${c.ancestry.join(' ← ')}`}
                    </div>
                  </div>

                  {c.owner === 'owned' ? (
                    // [불변식] owned는 종료 버튼을 아예 그리지 않는다. 서버도 거부하지만
                    //   버튼이 보이면 눌러보게 되므로 UI에서 먼저 없앤다.
                    <span className="text-[9px] text-green-400/70 shrink-0 flex items-center gap-1 mt-1">
                      <ShieldAlert className="w-3 h-3" /> 보호됨
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirmKill(c)}
                      disabled={!!killing[c.pid]}
                      className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#3c3c3c] hover:bg-red-500/20 hover:text-red-400 disabled:opacity-30 border border-white/5 shrink-0 flex items-center gap-1 transition-colors"
                    >
                      {killing[c.pid] ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
                      종료
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── 종료 확인 — 소유하지 않은 프로세스는 반드시 한 단계 거친다 ─────── */}
      {confirmKill && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6">
          <div className="bg-[#252526] border border-white/15 rounded-2xl p-5 max-w-lg w-full">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-warning" />
              <span className="text-[13px] font-black">이 프로세스를 종료할까?</span>
            </div>
            <div className="text-[11px] text-[#bbb] leading-relaxed mb-3">
              {confirmKill.owner === 'foreign'
                ? '이 앱이 소유하지 않은 프로세스야. 다른 프로그램이 쓰고 있을 수 있어 — 종료하면 그쪽이 멈춘다.'
                : '터미널 슬롯의 에이전트가 실행한 프로세스야. 진행 중인 작업이 있으면 중단된다.'}
            </div>
            <div className="rounded-lg bg-black/40 border border-white/10 p-3 mb-4">
              <div className="text-[11px] font-bold mb-1 break-all">{confirmKill.title || confirmKill.name}</div>
              <div className="text-[10px] text-[#999] break-all mb-1">PID {confirmKill.pid}</div>
              <div className="text-[9px] text-[#777] break-all font-mono leading-relaxed">
                {confirmKill.cmdline || confirmKill.summary}
              </div>
            </div>
            <div className="text-[9px] text-[#666] mb-3">
              자식 프로세스까지 함께 종료돼(트리 종료). 콘솔 창의 껍데기만 닫으면 실제 작업이 고아로 남기 때문이야.
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmKill(null)}
                className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-[#3c3c3c] hover:bg-white/10 transition-colors"
              >
                취소
              </button>
              <button
                onClick={() => doKill(confirmKill)}
                className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30 transition-colors"
              >
                종료할게
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
