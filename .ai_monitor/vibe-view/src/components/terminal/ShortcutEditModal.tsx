/**
 * ------------------------------------------------------------------------
 * FILE: ShortcutEditModal.tsx
 * DESCRIPTION: 터미널 단축어(사용자 커스텀 명령) 편집 모달.
 *              TerminalSlot에서 분리 — hot-file 크기 완화(Platform 후속).
 * REVISION HISTORY:
 * - 2026-04-19 Claude: TerminalSlot.tsx에서 추출 (WARN:hot-file-large 해소용)
 * ------------------------------------------------------------------------
 */

import { X, Trash2 } from 'lucide-react';
import { Shortcut, defaultShortcuts } from '../../constants';

interface ShortcutEditModalProps {
  shortcuts: Shortcut[];
  saveShortcuts: (next: Shortcut[]) => void;
  onClose: () => void;
}

export default function ShortcutEditModal({ shortcuts, saveShortcuts, onClose }: ShortcutEditModalProps) {
  return (
    <div className="absolute inset-0 bg-black/80 z-50 flex items-center justify-center p-2">
      <div className="bg-[#252526] border border-black/40 shadow-2xl rounded-md flex flex-col w-full max-w-md max-h-full">
        <div className="h-8 bg-[#2d2d2d] border-b border-black/40 flex items-center justify-between px-3 shrink-0">
          <span className="text-xs font-bold text-[#cccccc]">단축어 편집 (개인화)</span>
          <button onClick={onClose} className="p-1 hover:bg-white/10 rounded text-[#cccccc]"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
          {shortcuts.map((sc, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input value={sc.label} onChange={e => { const n = [...shortcuts]; n[i].label = e.target.value; saveShortcuts(n); }} placeholder="버튼 이름" className="w-1/3 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-xs text-white focus:border-primary focus:outline-none transition-colors" />
              <input value={sc.cmd} onChange={e => { const n = [...shortcuts]; n[i].cmd = e.target.value; saveShortcuts(n); }} placeholder="실행할 명령어" className="flex-1 bg-[#1e1e1e] border border-white/10 hover:border-white/30 rounded px-2 py-1.5 text-xs text-white font-mono focus:border-primary focus:outline-none transition-colors" />
              <button onClick={() => { const n = shortcuts.filter((_, idx) => idx !== i); saveShortcuts(n); }} className="p-1.5 text-red-400 hover:bg-red-400/20 rounded transition-colors"><Trash2 className="w-4 h-4" /></button>
            </div>
          ))}
          <button onClick={() => saveShortcuts([...shortcuts, {label: '새 단축어', cmd: ''}])} className="w-full py-2 mt-2 border border-dashed border-white/20 hover:border-white/40 hover:bg-white/5 rounded text-xs text-[#cccccc] transition-colors">
            + 새 단축어 추가
          </button>
        </div>
        <div className="p-3 border-t border-black/40 flex justify-end gap-2 shrink-0">
          <button onClick={() => { if(confirm('모든 단축어를 기본값으로 초기화하시겠습니까?')) saveShortcuts(defaultShortcuts); }} className="px-3 py-1.5 hover:bg-white/5 text-xs text-[#cccccc] rounded transition-colors">기본값 복원</button>
          <button onClick={onClose} className="px-4 py-1.5 bg-primary hover:bg-primary/80 text-white rounded text-xs font-bold transition-colors">닫기</button>
        </div>
      </div>
    </div>
  );
}
