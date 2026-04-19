/**
 * ------------------------------------------------------------------------
 * FILE: SlashCommandMenu.tsx
 * DESCRIPTION: 터미널 입력 영역의 슬래시 커맨드(`/`) 드롭다운 — 카테고리별
 *              그룹화 표시. TerminalSlot에서 분리(hot-file 크기 완화).
 * REVISION HISTORY:
 * - 2026-04-19 Claude: TerminalSlot.tsx에서 추출 (WARN:hot-file-large 해소용)
 * ------------------------------------------------------------------------
 */

import { SLASH_COMMANDS } from '../../constants';

interface SlashCommandMenuProps {
  activeAgent: string;
  showSlashMenu: boolean;
  setShowSlashMenu: (v: boolean) => void;
  onSelect: (cmd: string) => void;
}

export default function SlashCommandMenu({
  activeAgent, showSlashMenu, setShowSlashMenu, onSelect,
}: SlashCommandMenuProps) {
  return (
    <div className="relative">
      <button
        onClick={() => setShowSlashMenu(!showSlashMenu)}
        className={`px-2.5 py-2 rounded text-xs font-bold border transition-all ${showSlashMenu ? 'bg-primary text-white border-primary' : 'bg-[#3c3c3c] text-[#cccccc] border-white/10 hover:bg-white/10'}`}
        title="슬래시 커맨드 목록"
      >
        /
      </button>
      {showSlashMenu && (
        <div className="absolute bottom-full right-0 mb-1 w-72 bg-[#252526] border border-white/15 rounded-md shadow-2xl z-50 overflow-hidden">
          <div className="h-7 bg-[#2d2d2d] border-b border-black/40 flex items-center px-3 gap-1.5">
            <span className="text-primary font-bold text-[11px]">/</span>
            <span className="text-[11px] font-bold text-[#cccccc] uppercase tracking-wider">
              {activeAgent.toUpperCase()} 슬래시 커맨드
            </span>
          </div>
          <div className="max-h-64 overflow-y-auto custom-scrollbar py-1">
            {['설정', '작업', '도움말'].map(cat => {
              const cmds = (SLASH_COMMANDS[activeAgent] ?? SLASH_COMMANDS['claude'])
                .filter(c => c.category === cat);
              if (!cmds.length) return null;
              return (
                <div key={cat}>
                  <div className="px-3 py-0.5 text-[9px] font-bold uppercase tracking-widest text-white/25">{cat}</div>
                  {cmds.map(sc => (
                    <button
                      key={sc.cmd}
                      onClick={() => { onSelect(sc.cmd); setShowSlashMenu(false); }}
                      className="w-full flex items-center gap-3 px-3 py-1.5 hover:bg-primary/20 text-left group transition-colors"
                    >
                      <span className="text-primary font-mono text-[11px] font-bold w-24 shrink-0 group-hover:text-white transition-colors">{sc.cmd}</span>
                      <span className="text-[#969696] text-[10px] group-hover:text-[#cccccc] transition-colors leading-tight">{sc.desc}</span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
