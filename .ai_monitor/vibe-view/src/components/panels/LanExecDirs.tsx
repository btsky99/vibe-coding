/**
 * 📄 LanExecDirs.tsx
 * 📝 원격 실행 허용 폴더 관리 — 이 PC가 다른 PC의 Claude에게 열어줄 폴더 목록 + 모드 지정.
 *    모드: copy(사본에서 작업, 원본 안 보임) | direct(원본 폴더 직접 편집).
 * 🕒 변경 이력:
 * - 2026-07-30 Claude: 신규 — Phase A. 원격실행이 화이트리스트 없이 프로젝트 루트를 무제한
 *   편집할 수 있던 구멍을 UI에서 닫는다. LanPanel이 530줄이라 별도 컴포넌트로 분리.
 */
// [WHY 저장을 /api/config/update로] 설정 쓰기 경로를 새로 만들지 않는다 — LanPanel의 브리지/
//   원격실행 토글이 이미 이 라우트를 쓰고, config 쓰기 로직이 두 곳으로 갈라지면 한쪽만
//   검증되는 사고가 난다([[feedback-no-duplicates]]).
import { useCallback, useEffect, useState } from 'react';
import { FolderOpen, Plus, Trash2, ShieldCheck, ShieldAlert } from 'lucide-react';
import { API_BASE } from '../../constants';

export interface ExecDir {
  path: string;
  mode: 'copy' | 'direct';
  label?: string;
  exists?: boolean;
}

interface Props {
  /** 원격 실행 마스터 토글 상태 — 꺼져 있으면 폴더 등록이 무의미하므로 안내를 띄운다. */
  execEnabled: boolean;
  onFlash?: (msg: string) => void;
}

export default function LanExecDirs({ execEnabled, onFlash }: Props) {
  const [dirs, setDirs] = useState<ExecDir[]>([]);
  const [newPath, setNewPath] = useState('');
  const [newMode, setNewMode] = useState<'copy' | 'direct'>('copy');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetch(`${API_BASE}/api/lan/exec/dirs`).then(r => r.json())
      .then((d: { dirs?: ExecDir[] }) => setDirs(d.dirs || []))
      .catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  // [불변식] 서버는 config의 배열을 그대로 신뢰하므로 저장 전에 프론트가 정규화한다
  //   (mode 오타 → 백엔드 allowed_dirs가 copy로 강제하지만, UI 표시가 어긋나면 혼란).
  const persist = async (next: ExecDir[]) => {
    setBusy(true);
    const r = await fetch(`${API_BASE}/api/config/update`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lan_exec_allowed_dirs: next }),
    }).then(r => r.json()).catch(() => ({ ok: false }));
    setBusy(false);
    if (r.ok === false) { onFlash?.('❌ 폴더 설정 저장 실패'); return; }
    load();   // 서버가 붙여주는 exists 플래그를 다시 받는다
  };

  const browse = async () => {
    const r = await fetch(`${API_BASE}/api/browse-folder`).then(r => r.json()).catch(() => ({}));
    if (r.path) setNewPath(r.path);
  };

  const add = async () => {
    const p = newPath.trim().replace(/\\/g, '/');
    if (!p) return;
    if (dirs.some(d => d.path.replace(/\\/g, '/').toLowerCase() === p.toLowerCase())) {
      onFlash?.('이미 등록된 폴더예요');
      return;
    }
    await persist([...dirs, { path: p, mode: newMode }]);
    setNewPath('');
    onFlash?.(`✅ 허용 폴더 추가: ${p} (${newMode === 'copy' ? '사본' : '직접'})`);
  };

  const remove = async (path: string) => {
    await persist(dirs.filter(d => d.path !== path));
  };

  const setMode = async (path: string, mode: 'copy' | 'direct') => {
    await persist(dirs.map(d => (d.path === path ? { ...d, mode } : d)));
  };

  return (
    <div className="bg-black/20 border border-purple-800/40 rounded p-2 space-y-2 text-[12px]">
      <div className="font-medium flex items-center gap-1 text-purple-200">
        <ShieldCheck className="w-3.5 h-3.5" /> 원격 실행 허용 폴더
      </div>
      <div className="text-[11px] text-[#888]">
        다른 PC의 Claude는 <span className="text-purple-300">여기 등록된 폴더에서만</span> 작업할 수 있어요.
        등록 안 된 경로로 요청이 오면 실행 없이 거부됩니다.
      </div>

      {execEnabled && dirs.length === 0 && (
        <div className="bg-yellow-900/30 border border-yellow-700/50 rounded px-2 py-1 text-yellow-200 text-[11px]">
          원격 실행은 켜져 있는데 허용 폴더가 없어요 — 모든 요청이 거부됩니다.
        </div>
      )}

      {dirs.length > 0 && (
        <div className="space-y-1">
          {dirs.map(d => (
            <div key={d.path} className="bg-black/30 rounded px-2 py-1.5 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] break-all flex-1">{d.path}</span>
                {d.exists === false && (
                  <span className="text-[10px] text-yellow-400 shrink-0" title="폴더가 지금 존재하지 않음">없음</span>
                )}
                <button onClick={() => remove(d.path)} disabled={busy}
                  className="p-1 hover:bg-white/10 rounded shrink-0 disabled:opacity-40" title="삭제">
                  <Trash2 className="w-3 h-3 text-red-400" />
                </button>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => setMode(d.path, 'copy')} disabled={busy}
                  className={`px-2 py-0.5 rounded text-[11px] ${d.mode !== 'direct'
                    ? 'bg-green-700/70 text-white' : 'bg-white/10 text-[#aaa]'}`}>
                  사본
                </button>
                <button onClick={() => setMode(d.path, 'direct')} disabled={busy}
                  className={`px-2 py-0.5 rounded text-[11px] ${d.mode === 'direct'
                    ? 'bg-orange-700/80 text-white' : 'bg-white/10 text-[#aaa]'}`}>
                  직접
                </button>
                <span className="text-[10px] text-[#777] ml-1">
                  {d.mode === 'direct'
                    ? '원본을 바로 편집 — 되돌리기 어려움'
                    : '사본에서 작업 — 원본 안전'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 폴더 추가 */}
      <div className="space-y-1.5 pt-1 border-t border-white/10">
        <div className="flex gap-2">
          <input value={newPath} onChange={e => setNewPath(e.target.value)}
            placeholder="허용할 폴더 경로"
            className="flex-1 bg-black/40 rounded px-2 py-1 text-[11px] font-mono outline-none" />
          <button onClick={browse}
            className="px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-[11px] flex items-center gap-1 shrink-0">
            <FolderOpen className="w-3.5 h-3.5" /> 찾아보기
          </button>
        </div>
        <div className="flex items-center gap-2">
          <select value={newMode} onChange={e => setNewMode(e.target.value as 'copy' | 'direct')}
            className="bg-black/40 rounded px-2 py-1 text-[11px] outline-none">
            <option value="copy">사본에서 작업 (권장)</option>
            <option value="direct">원본 직접 편집</option>
          </select>
          <button onClick={add} disabled={!newPath.trim() || busy}
            className="px-3 py-1 bg-purple-700/70 hover:bg-purple-700 disabled:opacity-40 rounded text-[11px] flex items-center gap-1">
            <Plus className="w-3 h-3" /> 추가
          </button>
        </div>
        {newMode === 'direct' && (
          <div className="flex items-start gap-1 text-[10px] text-orange-300">
            <ShieldAlert className="w-3 h-3 mt-0.5 shrink-0" />
            <span>
              직접 모드는 완전 격리가 아니에요. 위험한 터미널 명령(push/rm 등)은 차단되지만,
              절대경로 파일 편집까지는 막지 못합니다. 신뢰하는 폴더에만 쓰세요.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
