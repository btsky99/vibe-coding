/**
 * FILE: components/panels/WikiPanel.tsx
 * DESCRIPTION: LLM 위키(지식 백과사전) 상태판. 페이지·검색항목 수를 보여주고
 *   갱신/초기화를 실행한다. 판정과 실행은 전부 서버(api/wiki_api.py)에 있다 — 여기는
 *   그리기와 확인 절차만.
 *
 * REVISION HISTORY:
 * - 2026-08-15 Claude: 신설 — W11. 초기화를 설치본에서도 눌러야 해서 UI 가 필요했다.
 */
import { useState, useEffect, useCallback } from 'react';
import { BookOpen, RotateCw, AlertTriangle, HardDriveDownload, Cloud } from 'lucide-react';
import { API_BASE } from '../../constants';

interface WikiStatus {
  status: string;
  wiki_path?: string;
  exists?: boolean;
  hub?: string | null;
  pages?: number;
  indexed?: number;
  embedded?: number;
  message?: string;
}

export default function WikiPanel() {
  const [st, setSt] = useState<WikiStatus | null>(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  // [WHY 2단계인가] 초기화는 페이지를 통째로 지운다. 옵시디언에서 손으로 덧붙인 문단은
  //   원료에 없으므로 복원되지 않는다. 한 번의 오클릭으로 날아가면 안 된다.
  const [armed, setArmed] = useState(false);

  const load = useCallback(() => {
    setErr('');
    fetch(`${API_BASE}/api/wiki/status`)
      .then(async r => {
        // [과거사고 계열] 라우트가 없는 구버전 서버는 SPA fallback 으로 index.html 을
        //   돌려준다. 그대로 json() 하면 "Unexpected token '<'" 만 보여 패널이 깨진 줄 안다.
        if (!(r.headers.get('content-type') || '').includes('json')) {
          throw new Error('실행 중인 서버에 위키 API 가 없습니다 — 앱을 재시작하면 활성화됩니다');
        }
        return r.json();
      })
      .then(setSt)
      .catch(e => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => { load(); }, [load]);

  const run = (kind: 'sync' | 'reset') => {
    setBusy(kind); setMsg(''); setErr('');
    fetch(`${API_BASE}/api/wiki/${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(kind === 'reset' ? { confirm: true } : {}),
    })
      .then(r => r.json())
      .then(d => {
        if (d.status === 'success') setMsg(d.message || '완료');
        else setErr(d.message || '실패');
        setArmed(false);
        load();
      })
      .catch(e => setErr(String(e)))
      .finally(() => setBusy(''));
  };

  return (
    <div className="flex flex-col gap-2 overflow-y-auto text-[11px]">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 font-bold text-[#cccccc]">
          <BookOpen className="w-4 h-4 text-emerald-400" /> 지식 백과사전
        </span>
        <button onClick={load} className="p-1 hover:bg-white/10 rounded text-[#888888]" title="새로고침">
          <RotateCw className="w-3.5 h-3.5" />
        </button>
      </div>

      <span className="text-[9px] text-[#666666]">
        코드 주석에서 자동으로 만들어집니다. 10분마다 갱신되며, 옵시디언으로 열어 읽을 수 있습니다.
      </span>

      {err && <div className="text-[10px] text-red-400 bg-red-500/10 rounded p-2">{err}</div>}
      {msg && <div className="text-[10px] text-emerald-400 bg-emerald-500/10 rounded p-2">{msg}</div>}
      {!st && !err && <div className="text-[10px] text-[#888888]">불러오는 중…</div>}

      {st && st.status === 'success' && (
        <>
          <div className="grid grid-cols-3 gap-1.5">
            {([
              ['페이지', st.pages ?? 0, '사람이 읽는 문서'],
              ['검색 항목', st.indexed ?? 0, '회상이 찾는 단위'],
              ['검색 준비', st.embedded ?? 0, '지문이 만들어진 항목'],
            ] as [string, number, string][]).map(([label, val, hint]) => (
              <div key={label} title={hint}
                className="rounded-lg border border-white/10 bg-black/20 p-2 flex flex-col items-center gap-0.5">
                <span className="text-base font-black text-white">{val}</span>
                <span className="text-[8px] text-[#888888]">{label}</span>
              </div>
            ))}
          </div>

          {/* 검색 준비가 덜 된 항목이 있으면 알려준다 — 임베딩 백필은 데몬이 이어서 채운다 */}
          {(st.indexed ?? 0) > (st.embedded ?? 0) && (
            <div className="text-[9px] text-yellow-400 bg-yellow-500/10 rounded px-2 py-1">
              🟡 {(st.indexed ?? 0) - (st.embedded ?? 0)}개가 아직 검색 준비 중입니다 (백그라운드에서 처리)
            </div>
          )}

          <div className="rounded-lg border border-white/10 bg-black/20 p-2 flex flex-col gap-1">
            <span className="text-[9px] text-[#888888] break-all">📁 {st.wiki_path}</span>
            <span className="text-[9px] flex items-center gap-1 break-all">
              <Cloud className="w-3 h-3 shrink-0 text-sky-400" />
              {st.hub
                ? <span className="text-sky-300/80">{st.hub}</span>
                : <span className="text-[#666666]">구글 드라이브 없음 — 이 PC 에만 저장됩니다</span>}
            </span>
          </div>

          <button
            onClick={() => run('sync')}
            disabled={!!busy}
            className="w-full py-2 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 text-[11px] font-bold disabled:opacity-40 flex items-center justify-center gap-1.5"
          >
            <HardDriveDownload className={`w-3.5 h-3.5 ${busy === 'sync' ? 'animate-pulse' : ''}`} />
            {busy === 'sync' ? '갱신 중…' : '지금 갱신'}
          </button>

          {/* 초기화 — 2단계. 처음 클릭은 '무장'만 하고 실제 실행은 두 번째 클릭. */}
          {!armed ? (
            <button
              onClick={() => setArmed(true)}
              disabled={!!busy}
              className="w-full py-1.5 rounded-lg bg-transparent hover:bg-red-500/10 text-[#777777] hover:text-red-400 border border-white/10 hover:border-red-500/30 text-[10px] transition-colors disabled:opacity-40"
            >
              전체 초기화…
            </button>
          ) : (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-2 flex flex-col gap-1.5">
              <span className="text-[10px] text-red-300 flex items-start gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                모든 페이지를 지우고 코드 주석에서 다시 만듭니다.
                <b className="text-red-200">직접 덧붙여 쓴 내용은 복원되지 않습니다.</b>
              </span>
              <div className="flex gap-1.5">
                <button
                  onClick={() => run('reset')}
                  disabled={!!busy}
                  className="flex-1 py-1.5 rounded bg-red-500/80 hover:bg-red-500 text-white text-[10px] font-black disabled:opacity-40"
                >
                  {busy === 'reset' ? '초기화 중…' : '지우고 다시 만들기'}
                </button>
                <button
                  onClick={() => setArmed(false)}
                  className="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-[#888888] text-[10px]"
                >
                  취소
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
