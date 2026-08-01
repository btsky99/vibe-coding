/**
 * FILE: components/panels/DaemonsPanel.tsx
 * DESCRIPTION: 백그라운드 데몬 on/off 패널. GET/POST /api/daemons만 사용하며 판정 로직은
 *   전부 서버(infra/daemons.py DAEMON_TOGGLES + daemon_status)에 있다 — 여기는 그리기 전용.
 *
 * REVISION HISTORY:
 * - 2026-08-01 Claude: 신규 — 토글 API는 있는데 이를 쓰는 UI가 없어 사용자가 config.json을
 *   직접 편집해야만 데몬을 끌 수 있었다(저사양 PC에서 상시 데몬 12종이 CPU/메모리 점유).
 */
import { useState, useEffect, useCallback } from 'react';
import { Gauge, RotateCw, Lock } from 'lucide-react';
import { API_BASE } from '../../constants';

interface Daemon {
  key: string;
  label: string;
  enabled: boolean;   // config/env 기준 "켜기로 되어 있음"
  running: boolean;   // 지금 스레드가 살아 있음 (= 이번 부팅에 뜬 상태)
  source: 'env' | 'config';
}

/**
 * [WHY enabled와 running을 따로 그리나] 토글은 다음 부팅부터 적용된다(서버가 런타임에
 * 스레드를 죽이지 않는 이유는 daemons.daemon_status 주석 참조). 두 값이 어긋난 항목만
 * "재시작 후 적용" 배지를 달아야, 껐는데 왜 아직 CPU를 먹는지 사용자가 알 수 있다.
 */
function pendingNote(d: Daemon): string {
  if (d.enabled && !d.running) return '재시작 후 켜짐';
  if (!d.enabled && d.running) return '재시작 후 꺼짐';
  return '';
}

export default function DaemonsPanel() {
  const [list, setList] = useState<Daemon[]>([]);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState('');

  /**
   * [과거사고 2026-08-01] /api/daemons는 신규 라우트라, 라우트 추가 이전에 뜬 서버에 붙으면
   * 서버가 SPA fallback으로 index.html(HTML)을 돌려준다. 그대로 r.json()을 부르면
   * "Unexpected token '<'"만 보여서 사용자는 패널이 깨진 줄 안다. content-type을 먼저 보고
   * "서버가 구버전"이라고 정확히 알린다 — 앱 재시작이 해법임을 화면에서 바로 알 수 있게.
   */
  const load = useCallback(() => {
    setLoading(true); setErr('');
    fetch(`${API_BASE}/api/daemons`)
      .then(async r => {
        if (!(r.headers.get('content-type') || '').includes('json')) {
          throw new Error('실행 중인 서버에 데몬 API가 없습니다 — 앱을 재시작하면 활성화됩니다');
        }
        return r.json();
      })
      .then(d => { if (d.status === 'success') setList(d.daemons || []); else setErr(d.message || '불러오기 실패'); })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  // [WHY 낙관적 갱신 안 함] 저장이 실패하면 UI만 꺼진 것처럼 보이고 데몬은 계속 도는
  //   최악의 오해가 생긴다. 응답을 받고 서버 상태를 다시 읽어 화면을 맞춘다.
  const toggle = (d: Daemon) => {
    if (d.source === 'env') return;
    setSaving(d.key);
    fetch(`${API_BASE}/api/daemons`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [d.key]: !d.enabled }),
    })
      .then(r => r.json())
      .then(r => { if (r.status !== 'success') setErr(r.message || '저장 실패'); load(); })
      .catch(e => setErr(String(e)))
      .finally(() => setSaving(''));
  };

  const pendingCount = list.filter(d => pendingNote(d)).length;

  return (
    <div className="flex flex-col gap-2 overflow-y-auto text-[11px]">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 font-bold text-[#cccccc]">
          <Gauge className="w-4 h-4 text-amber-400" /> 백그라운드 데몬
        </span>
        <button onClick={load} disabled={loading}
          className="p-1 hover:bg-white/10 rounded text-[#888888] disabled:opacity-40" title="새로고침">
          <RotateCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <span className="text-[9px] text-[#666666]">
        안 쓰는 데몬을 끄면 CPU·메모리가 줄어든다. 변경은 <b>앱 재시작</b> 후 적용.
      </span>

      {err && <div className="text-[10px] text-red-400 bg-red-500/10 rounded p-2">{err}</div>}
      {!list.length && !err && <div className="text-[10px] text-[#888888]">불러오는 중…</div>}

      {pendingCount > 0 && (
        <div className="text-[9px] text-yellow-400 bg-yellow-500/10 rounded px-2 py-1">
          🟡 {pendingCount}개 변경이 대기 중 — 앱을 재시작해야 실제로 적용됩니다
        </div>
      )}

      {list.map(d => {
        const pending = pendingNote(d);
        const locked = d.source === 'env';
        return (
          <div key={d.key}
            className="rounded-lg border border-white/10 bg-black/20 p-2.5 flex items-center gap-2">
            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
              <span className="text-[11px] text-[#dddddd] truncate">{d.label}</span>
              <span className="text-[9px] text-[#777777] flex items-center gap-1.5">
                <span className={d.running ? 'text-emerald-400' : 'text-[#666666]'}>
                  {d.running ? '● 실행 중' : '○ 정지'}
                </span>
                <span className="text-[#555555]">{d.key}</span>
                {pending && <span className="text-yellow-400">· {pending}</span>}
                {locked && (
                  <span className="text-[#888888] flex items-center gap-0.5">
                    <Lock className="w-2.5 h-2.5" /> VIBE_DISABLE_DAEMONS
                  </span>
                )}
              </span>
            </div>
            <button
              onClick={() => toggle(d)}
              disabled={locked || saving === d.key}
              title={locked ? '환경변수로 잠김 — config로 켤 수 없습니다' : '클릭하여 전환'}
              className={`w-9 h-5 rounded-full shrink-0 transition-colors relative
                ${d.enabled ? 'bg-emerald-600' : 'bg-white/15'}
                ${locked ? 'opacity-40 cursor-not-allowed' : 'hover:brightness-125'}`}
            >
              {/* [WHY 인라인 left] Tailwind 임의값 대신 px 계산 — 토글 폭(w-9=36px)과
                  손잡이(w-4=16px)가 바뀌면 여기 두 값만 고치면 된다. */}
              <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
                style={{ left: d.enabled ? 18 : 2 }} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
