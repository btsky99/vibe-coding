/**
 * ------------------------------------------------------------------------
 * 📄 파일명: FloatingWindow.tsx
 * 📝 설명: 파일 탐색기에서 파일 클릭 시 열리는 플로팅(부유형) 편집 창 컴포넌트.
 *          드래그 이동, 좌하단 리사이즈 핸들, 최대화/최소화 토글,
 *          이미지 미리보기 vs VibeEditor 코드 뷰어 분기를 담당합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리. constants.ts의 공유 상수 사용.
 * ------------------------------------------------------------------------
 */

import { useState, useRef } from 'react';
import { X, Maximize2, Minimize2, Minus, Plus, Save } from 'lucide-react';
import VibeEditor from './VibeEditor';
import { API_BASE, getFileIcon, OpenFile } from '../constants';

interface FloatingWindowProps {
  file: OpenFile;
  idx: number;
  bringToFront: (id: string) => void;
  closeFile: (id: string) => void;
  updateFileContent: (id: string, content: string) => void;
  handleSaveFile: (path: string, content: string) => void;
}

export default function FloatingWindow({
  file, idx, bringToFront, closeFile, updateFileContent, handleSaveFile
}: FloatingWindowProps) {
  const [position, setPosition] = useState({ x: 100 + (idx * 30), y: 100 + (idx * 30) });
  const [size, setSize] = useState({ width: 700, height: 600 });
  const [isMaximized, setIsMaximized] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);

  // 최대화 전 원래 상태 기억용 — 최대화 해제 시 복원에 사용
  const preMaxState = useRef({ x: 100, y: 100, w: 700, h: 600 });
  const dragStartPos = useRef({ x: 0, y: 0 });
  const resizeStartPos = useRef({ x: 0, y: 0, w: 0, h: 0 });

  const handlePointerDown = (e: React.PointerEvent) => {
    if (isMaximized) return; // 최대화 모드에서는 드래그 불가
    setIsDragging(true);
    bringToFront(file.id);
    dragStartPos.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handleResizePointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    if (isMaximized || isMinimized) return; // 최대화/최소화 시 리사이즈 불가
    setIsResizing(true);
    bringToFront(file.id);
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
        width: Math.max(300, resizeStartPos.current.w + dw),
        height: Math.max(200, resizeStartPos.current.h + dh)
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
      // 현재 상태 저장 후 최대화
      preMaxState.current = { x: position.x, y: position.y, w: size.width, h: size.height };
      setPosition({ x: 0, y: 0 });
      setSize({ width: window.innerWidth, height: window.innerHeight });
      setIsMaximized(true);
      setIsMinimized(false); // 최소화 해제
    } else {
      // 이전 상태로 복구
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
      onPointerDown={() => bringToFront(file.id)}
      style={{
        zIndex: isMaximized ? 9999 : file.zIndex,
        position: isMaximized ? 'fixed' : 'absolute',
        left: isMaximized ? 0 : position.x,
        top: isMaximized ? 0 : position.y,
        width: isMaximized ? '100vw' : size.width,
        height: isMinimized ? 40 : (isMaximized ? '100vh' : size.height),
        borderRadius: isMaximized ? 0 : 12,
        transition: isResizing || isDragging ? 'none' : 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
      className={`bg-[#1e1e1e]/95 backdrop-blur-2xl border border-white/20 shadow-2xl flex flex-col overflow-hidden ${isMaximized ? 'inset-0' : ''}`}
    >
      {/* 타이틀바 — 드래그 핸들 역할 */}
      <div
        className={`h-10 bg-[#2d2d2d]/95 border-b border-white/10 flex items-center justify-between px-4 shrink-0 select-none ${isMaximized ? 'cursor-default' : 'cursor-move'}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <div className="flex items-center gap-2 text-[#cccccc] font-mono text-sm truncate pointer-events-none flex-1">
          {getFileIcon(file.name)}
          <span className="truncate font-bold">{file.name}</span>
          {!isMinimized && <span className="text-[10px] opacity-40 ml-2 truncate max-w-[300px] hidden md:inline">{file.path}</span>}
        </div>
        <div className="flex items-center gap-1 ml-4" onPointerDown={e => e.stopPropagation()}>
          {/* 최소화(접기) 버튼 */}
          <button
            onClick={toggleMinimize}
            className="p-1.5 hover:bg-white/10 rounded-md text-[#cccccc] hover:text-white transition-all active:scale-90"
            title={isMinimized ? '확장' : '최소화'}
          >
            {isMinimized ? <Plus className="w-4 h-4" /> : <Minus className="w-4 h-4" />}
          </button>
          {/* 최대화 토글 버튼 */}
          <button
            onClick={toggleMaximize}
            className="p-1.5 hover:bg-white/10 rounded-md text-[#cccccc] hover:text-primary transition-all active:scale-90"
            title={isMaximized ? '이전 크기로' : '최대화'}
          >
            {isMaximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
          <div className="w-[1px] h-4 bg-white/10 mx-1" />
          <button
            onClick={(e) => { e.stopPropagation(); handleSaveFile(file.path, file.content); }}
            className="p-1.5 hover:bg-primary/20 rounded-md text-[#cccccc] hover:text-primary transition-all cursor-pointer group active:scale-90"
            title="저장 (Ctrl+S)"
          >
            <Save className="w-4.5 h-4.5 group-active:scale-95 transition-transform" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); closeFile(file.id); }}
            className="p-1.5 hover:bg-red-500/20 rounded-md text-[#cccccc] hover:text-red-400 transition-all cursor-pointer active:scale-90"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 콘텐츠 영역 — 이미지면 img 태그, 아니면 VibeEditor */}
      {!isMinimized && (
        <div
          className="flex-1 overflow-hidden bg-transparent relative"
          onPointerDownCapture={e => e.stopPropagation()}
        >
          {file.isLoading ? (
            <div className="absolute inset-0 flex items-center justify-center text-[#858585] animate-pulse">Loading content...</div>
          ) : /\.(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/i.test(file.name) ? (
            <div className="absolute inset-0 flex items-center justify-center p-4 overflow-auto custom-scrollbar">
              <img
                src={`${API_BASE}/api/image-file?path=${encodeURIComponent(file.path)}`}
                alt={file.name}
                className="max-w-full max-h-full object-contain shadow-2xl rounded-sm"
              />
            </div>
          ) : (
            <VibeEditor
              path={file.path}
              content={file.content}
              onChange={(val) => updateFileContent(file.id, val)}
            />
          )}
        </div>
      )}

      {/* 리사이즈 핸들 (최대화/최소화가 아닐 때만 노출) */}
      {!isMaximized && !isMinimized && (
        <div
          onPointerDown={handleResizePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          className="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize z-[100] group"
        >
          <div className="absolute bottom-1 right-1 w-2 h-2 border-r-2 border-b-2 border-white/20 group-hover:border-primary transition-colors rounded-br-[1px]" />
        </div>
      )}
    </div>
  );
}
