/**
 * ------------------------------------------------------------------------
 * 📄 파일명: DiscordSettingsModal.tsx
 * 📝 설명: 디스코드 설정을 위한 전용 플로팅 윈도우.
 *          드래그 이동, 리사이즈, 최대화/최소화 기능을 제공하며
 *          내부에 DiscordConfigPanel을 렌더링합니다.
 * ------------------------------------------------------------------------
 */

import { useState, useRef } from 'react';
import { X, Maximize2, Minimize2, Minus, Plus, Settings } from 'lucide-react';
import DiscordConfigPanel from './panels/DiscordConfigPanel';

interface DiscordSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  zIndex: number;
  bringToFront: () => void;
}

export default function DiscordSettingsModal({
  isOpen, onClose, zIndex, bringToFront
}: DiscordSettingsModalProps) {
  const [position, setPosition] = useState({ x: window.innerWidth / 2 - 400, y: window.innerHeight / 2 - 350 });
  const [size, setSize] = useState({ width: 800, height: 700 });
  const [isMaximized, setIsMaximized] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);

  const preMaxState = useRef({ x: 100, y: 100, w: 800, h: 700 });
  const dragStartPos = useRef({ x: 0, y: 0 });
  const resizeStartPos = useRef({ x: 0, y: 0, w: 0, h: 0 });

  if (!isOpen) return null;

  const handlePointerDown = (e: React.PointerEvent) => {
    if (isMaximized) return;
    setIsDragging(true);
    bringToFront();
    dragStartPos.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handleResizePointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    if (isMaximized || isMinimized) return;
    setIsResizing(true);
    bringToFront();
    resizeStartPos.current = { x: e.clientX, y: e.clientY, w: size.width, h: size.height };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStartPos.current.x,
        y: e.clientY - dragStartPos.current.y
      });
    } else if (isResizing) {
      const dw = e.clientX - resizeStartPos.current.x;
      const dh = e.clientY - resizeStartPos.current.y;
      setSize({
        width: Math.max(500, resizeStartPos.current.w + dw),
        height: Math.max(400, resizeStartPos.current.h + dh)
      });
    }
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    setIsDragging(false);
    setIsResizing(false);
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const toggleMaximize = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isMaximized) {
      preMaxState.current = { x: position.x, y: position.y, w: size.width, h: size.height };
      setPosition({ x: 0, y: 0 });
      setSize({ width: window.innerWidth, height: window.innerHeight });
      setIsMaximized(true);
      setIsMinimized(false);
    } else {
      const { x, y, w, h } = preMaxState.current;
      setPosition({ x, y });
      setSize({ width: w, height: h });
      setIsMaximized(false);
    }
  };

  const toggleMinimize = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsMinimized(!isMinimized);
  };

  return (
    <div
      onPointerDown={bringToFront}
      style={{
        zIndex: isMaximized ? 10000 : zIndex,
        position: isMaximized ? 'fixed' : 'absolute',
        left: isMaximized ? 0 : position.x,
        top: isMaximized ? 0 : position.y,
        width: isMaximized ? '100vw' : size.width,
        height: isMinimized ? 40 : (isMaximized ? '100vh' : size.height),
        borderRadius: isMaximized ? 0 : 12,
        transition: isResizing || isDragging ? 'none' : 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      className={`bg-[#0f172a]/95 backdrop-blur-2xl border border-white/10 shadow-2xl flex flex-col overflow-hidden ${isMaximized ? 'inset-0' : ''}`}
    >
      {/* 타이틀바 */}
      <div
        className={`h-10 bg-slate-900 border-b border-white/5 flex items-center justify-between px-4 shrink-0 select-none ${isMaximized ? 'cursor-default' : 'cursor-move'}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div className="flex items-center gap-2 text-slate-300 font-bold text-sm truncate pointer-events-none flex-1">
          <Settings className="w-4 h-4 text-indigo-400" />
          <span>Discord Bridge Settings</span>
        </div>
        <div className="flex items-center gap-1 ml-4" onPointerDown={e => e.stopPropagation()}>
          <button
            onClick={() => window.open('/?page=dashboard&tab=discord', '_blank', 'width=1200,height=900')}
            className="p-1.5 hover:bg-white/10 rounded-md text-slate-400 hover:text-indigo-400 transition-all active:scale-90"
            title="전체 화면(새 창)으로 보기"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
          <div className="w-[1px] h-4 bg-white/5 mx-1" />
          <button
            onClick={toggleMinimize}
            className="p-1.5 hover:bg-white/10 rounded-md text-slate-400 hover:text-white transition-all active:scale-90"
            title={isMinimized ? '확장' : '최소화'}
          >
            {isMinimized ? <Plus className="w-4 h-4" /> : <Minus className="w-4 h-4" />}
          </button>
          <button
            onClick={toggleMaximize}
            className="p-1.5 hover:bg-white/10 rounded-md text-slate-400 hover:text-indigo-400 transition-all active:scale-90"
            title={isMaximized ? '이전 크기로' : '최대화'}
          >
            {isMaximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          <div className="w-[1px] h-4 bg-white/5 mx-1" />
          <button
            onClick={(e) => { e.stopPropagation(); onClose(); }}
            className="p-1.5 hover:bg-red-500/20 rounded-md text-slate-400 hover:text-red-400 transition-all active:scale-90"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 콘텐츠 영역 */}
      {!isMinimized && (
        <div className="flex-1 overflow-hidden bg-slate-950/50 relative">
          <DiscordConfigPanel />
        </div>
      )}

      {/* 리사이즈 핸들 */}
      {!isMaximized && !isMinimized && (
        <div
          onPointerDown={handleResizePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          className="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize z-[100] group"
        >
          <div className="absolute bottom-1 right-1 w-2 h-2 border-r-2 border-b-2 border-white/20 group-hover:border-indigo-500 transition-colors rounded-br-[1px]" />
        </div>
      )}
    </div>
  );
}
