/**
 * ------------------------------------------------------------------------
 * 📄 파일명: FileTreeNode.tsx
 * 📝 설명: 파일 탐색기의 단일 트리 노드 컴포넌트.
 *          폴더 열기/닫기, 파일 열기, 인라인 이름 변경, 삭제, 새 파일/폴더 생성,
 *          경로 복사 등의 호버 액션을 처리합니다. 재귀적으로 자신을 렌더링합니다.
 * REVISION HISTORY:
 * - 2026-03-01 Claude: App.tsx에서 독립 컴포넌트로 분리. constants.ts의 공유 상수 사용.
 * ------------------------------------------------------------------------
 */

import { ChevronRight, ChevronDown, Plus, Trash2, Edit3, ClipboardList } from 'lucide-react';
import { VscFolder, VscFolderOpened, VscNewFolder } from 'react-icons/vsc';
import { API_BASE, getFileIcon, TreeItem } from '../constants';

interface FileTreeNodeProps {
  item: TreeItem;
  depth: number;
  expanded: Record<string, boolean>;
  treeChildren: Record<string, TreeItem[]>;
  onToggle: (path: string) => void;
  onFileOpen: (item: TreeItem) => void;
  onContextMenu: (e: React.MouseEvent, item: TreeItem) => void;
  onRename: (src: string, dest: string) => Promise<boolean>;
  onDelete: (path: string, isDir: boolean) => void;
  onCreateFile: (parent: string) => void;
  onCreateFolder: (parent: string) => void;
  editingPath: string | null;
  setEditingPath: (path: string | null) => void;
  editValue: string;
  setEditValue: (val: string) => void;
}

export default function FileTreeNode({
  item, depth, expanded, treeChildren,
  onToggle, onFileOpen, onContextMenu,
  onRename, onDelete, onCreateFile, onCreateFolder,
  editingPath, setEditingPath, editValue, setEditValue
}: FileTreeNodeProps) {
  const isOpen = expanded[item.path] || false;
  const kids = treeChildren[item.path] || [];
  const indent = depth * 12;
  const isEditing = editingPath === item.path;

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onContextMenu(e, item);
  };

  // 파일 경로를 클립보드에 복사하고 버튼 텍스트를 1.5초 동안 "Copied!"로 변경
  const handleCopyPath = (e: React.MouseEvent) => {
    e.stopPropagation();
    fetch(`${API_BASE}/api/copy-path?path=${encodeURIComponent(item.path)}`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          const btn = e.currentTarget;
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<span class="text-[8px] text-green-400">Copied!</span>';
          setTimeout(() => btn.innerHTML = originalHtml, 1500);
        }
      });
  };

  // 이름 변경 확정 — 부모 경로 + 새 이름으로 dest 경로 조합 후 onRename 호출
  const submitRename = async () => {
    if (!editValue || editValue === item.name) {
      setEditingPath(null);
      return;
    }
    const parentPath = item.path.split(/[\\\/]/).slice(0, -1).join('/');
    const dest = parentPath ? `${parentPath}/${editValue}` : editValue;
    const success = await onRename(item.path, dest);
    if (success) setEditingPath(null);
  };

  const renderContent = () => (
    <div className="group flex items-center gap-0 pr-1 hover:bg-[#2a2d2e] rounded transition-colors relative">
      <button
        onClick={item.isDir ? () => onToggle(item.path) : () => onFileOpen(item)}
        onContextMenu={handleContextMenu}
        style={{ paddingLeft: `${indent + (item.isDir ? 4 : 20)}px` }}
        className={`flex items-center gap-1.5 py-0.5 transition-colors ${item.isDir ? 'text-[#cccccc]' : 'text-[#ffffff] font-medium'}`}
      >
        {item.isDir ? (
          <>
            {isOpen ? <ChevronDown className="w-3 h-3 shrink-0 text-[#858585]" /> : <ChevronRight className="w-3 h-3 shrink-0 text-[#858585]" />}
            {isOpen ? <VscFolderOpened className="w-4 h-4 text-[#dcb67a] shrink-0" /> : <VscFolder className="w-4 h-4 text-[#dcb67a] shrink-0" />}
          </>
        ) : getFileIcon(item.name)}

        {isEditing ? (
          <input
            autoFocus
            value={editValue}
            onChange={e => setEditValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') submitRename();
              if (e.key === 'Escape') setEditingPath(null);
            }}
            onBlur={submitRename}
            onClick={e => e.stopPropagation()}
            className="flex-1 bg-[#1e1e1e] border border-primary outline-none px-1 text-xs text-white rounded"
          />
        ) : (
          <span className="whitespace-nowrap">{item.name}</span>
        )}
      </button>

      {/* 호버 시 노출되는 액션 버튼 그룹 */}
      {!isEditing && (
        <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 ml-auto shrink-0 pr-1 transition-all">
          {item.isDir && (
            <>
              <button onClick={(e) => { e.stopPropagation(); onCreateFile(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 파일"><Plus className="w-3 h-3" /></button>
              <button onClick={(e) => { e.stopPropagation(); onCreateFolder(item.path); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-white" title="새 폴더"><VscNewFolder className="w-3 h-3" /></button>
            </>
          )}
          <button onClick={handleCopyPath} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary" title="경로 복사"><ClipboardList className="w-3 h-3" /></button>
          <button onClick={(e) => { e.stopPropagation(); setEditingPath(item.path); setEditValue(item.name); }} className="p-1 hover:bg-white/10 rounded text-[#858585] hover:text-primary" title="이름 변경"><Edit3 className="w-3 h-3" /></button>
          <button onClick={(e) => { e.stopPropagation(); onDelete(item.path, item.isDir); }} className="p-1 hover:bg-red-500/20 rounded text-[#858585] hover:text-red-400" title="삭제"><Trash2 className="w-3 h-3" /></button>
        </div>
      )}
    </div>
  );

  return (
    <div>
      {renderContent()}
      {/* 폴더가 열려 있으면 자식 노드를 재귀적으로 렌더링 */}
      {item.isDir && isOpen && (
        <>
          {kids.length === 0 && (
            <div style={{ paddingLeft: `${indent + 28}px` }} className="py-0.5 text-[10px] text-[#858585] italic">비어 있음</div>
          )}
          {kids.map(child => (
            <FileTreeNode
              key={child.path}
              item={child}
              depth={depth + 1}
              expanded={expanded}
              treeChildren={treeChildren}
              onToggle={onToggle}
              onFileOpen={onFileOpen}
              onContextMenu={onContextMenu}
              onRename={onRename}
              onDelete={onDelete}
              onCreateFile={onCreateFile}
              onCreateFolder={onCreateFolder}
              editingPath={editingPath}
              setEditingPath={setEditingPath}
              editValue={editValue}
              setEditValue={setEditValue}
            />
          ))}
        </>
      )}
    </div>
  );
}
